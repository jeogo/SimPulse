"""
SimPulse Modem Detector
Real-time event-driven modem detection using Windows WMI
Combines initial scan with real-time device monitoring
"""

import serial
import serial.tools.list_ports
import threading
import time
import logging
from typing import List, Dict, Optional, Callable
from .config import (
    MAX_COM_PORTS, 
    PORT_SCAN_DELAY, 
    MAX_DETECTION_ATTEMPTS,
    STARTUP_FULL_SCAN,
    DEVICE_EVENT_MONITORING
)
from .port_filter import port_filter
from .database import db
from .device_monitor import device_monitor

logger = logging.getLogger(__name__)

class ModemDetector:
    """Handles real-time event-driven modem detection with Windows WMI integration"""
    
    def __init__(self):
        self.max_com_ports = MAX_COM_PORTS
        self.port_scan_delay = PORT_SCAN_DELAY
        self.max_attempts = MAX_DETECTION_ATTEMPTS
        self.startup_full_scan = STARTUP_FULL_SCAN
        self.device_event_monitoring = DEVICE_EVENT_MONITORING
        
        # Event callbacks
        self.on_modem_detected = None
        self.on_modem_removed = None
        self.on_scan_complete = None
        
        # Internal state
        self.known_modems = {}  # IMEI -> modem info
        self.scanning = False
        self.scan_thread = None
        self.real_time_monitoring = False
        
        # Initialize with existing modems from database
        self._load_known_modems()
        
        # Setup device monitor callbacks
        device_monitor.set_callbacks(
            on_device_connected=self._on_device_connected,
            on_device_disconnected=self._on_device_disconnected,
            on_com_port_change=self._on_com_port_change
        )
    
    def set_callbacks(self, on_modem_detected: Callable = None, 
                     on_modem_removed: Callable = None,
                     on_scan_complete: Callable = None):
        """Set event callbacks"""
        self.on_modem_detected = on_modem_detected
        self.on_modem_removed = on_modem_removed
        self.on_scan_complete = on_scan_complete
    
    def start_detection(self):
        """Start the enhanced modem detection system with real-time monitoring"""
        logger.info("🚀 Starting enhanced modem detection system")
        logger.info("     ✅ Initial full scan")
        logger.info("     ✅ Real-time WMI monitoring")
        
        # Start initial full scan
        self.start_full_scan()
        
        # Start real-time device monitoring
        self._start_real_time_monitoring()
    
    def stop_detection(self):
        """Stop the modem detection system"""
        logger.info("🛑 Stopping modem detection system")
        self.scanning = False
        self.real_time_monitoring = False
        
        # Stop device monitoring
        try:
            device_monitor.stop_monitoring()
        except Exception as e:
            logger.error(f"Error stopping device monitor: {e}")
        
        # Stop scan thread
        if self.scan_thread and self.scan_thread.is_alive():
            self.scan_thread.join(timeout=5)
    
    def _start_real_time_monitoring(self):
        """Start real-time device monitoring"""
        try:
            logger.info("🔄 Starting real-time device monitoring...")
            self.real_time_monitoring = True
            device_monitor.start_monitoring()
            logger.info("✅ Real-time monitoring started")
        except Exception as e:
            logger.error(f"❌ Failed to start real-time monitoring: {e}")
            # Continue without real-time monitoring
    
    def _on_device_connected(self, device_info: Dict):
        """Handle device connection events from WMI"""
        try:
            logger.info(f"🔌 Device connected event: {device_info['type']}")
            
            # Wait a moment for device to be ready
            time.sleep(2)
            
            # Trigger quick scan to detect new modems
            self._trigger_device_change_scan("Device connected")
            
        except Exception as e:
            logger.error(f"Error handling device connection: {e}")
    
    def _on_device_disconnected(self, device_info: Dict):
        """Handle device disconnection events from WMI"""
        try:
            logger.info(f"🔌❌ Device disconnected event: {device_info['type']}")
            
            # Check for removed modems
            self._check_modem_availability()
            
        except Exception as e:
            logger.error(f"Error handling device disconnection: {e}")
    
    def _on_com_port_change(self, change_info: Dict):
        """Handle COM port changes from WMI"""
        try:
            change_type = change_info['type']
            port = change_info['port']
            
            logger.info(f"📡 COM port change: {change_type} - {port}")
            
            if change_type in ['COM_PORT_ADDED', 'COM_PORT_DETECTED']:
                # New COM port detected - scan it
                self._scan_specific_port(port)
            
            elif change_type in ['COM_PORT_REMOVED', 'COM_PORT_LOST']:
                # COM port removed - check which modem lost it
                self._handle_port_removal(port)
            
        except Exception as e:
            logger.error(f"Error handling COM port change: {e}")
    
    def _trigger_device_change_scan(self, reason: str):
        """Trigger a scan due to device changes"""
        if self.scanning:
            logger.info(f"⏳ Scan already in progress, skipping trigger: {reason}")
            return
        
        logger.info(f"🔍 Triggering device change scan: {reason}")
        
        # Get current system ports and scan them
        system_ports = self._get_system_ports()
        if system_ports:
            threading.Thread(
                target=self._device_change_scan_worker,
                args=(system_ports, reason),
                daemon=True
            ).start()
    
    def _device_change_scan_worker(self, ports: List[str], reason: str):
        """Worker for device change scans"""
        try:
            logger.info(f"🔍 Device change scan starting: {reason}")
            logger.info(f"     Scanning {len(ports)} ports: {ports}")
            
            self._process_detected_ports(ports)
            
            logger.info(f"✅ Device change scan completed: {reason}")
            
        except Exception as e:
            logger.error(f"Error in device change scan: {e}")
    
    def _scan_specific_port(self, port: str):
        """Scan a specific COM port that was just detected"""
        try:
            logger.info(f"🔍 Scanning specific port: {port}")
            
            # Quick scan of just this port
            threading.Thread(
                target=self._process_detected_ports,
                args=([port],),
                daemon=True
            ).start()
            
        except Exception as e:
            logger.error(f"Error scanning specific port {port}: {e}")
    
    def _handle_port_removal(self, removed_port: str):
        """Handle removal of a specific COM port"""
        try:
            logger.info(f"📡❌ Handling removal of port: {removed_port}")
            
            # Find which modem was using this port
            affected_modem = None
            for imei, modem_info in self.known_modems.items():
                if modem_info.get('port') == removed_port:
                    affected_modem = imei
                    break
            
            if affected_modem:
                logger.info(f"🔌❌ Modem {affected_modem} lost port {removed_port}")
                
                # Trigger modem removed callback
                if self.on_modem_removed:
                    self.on_modem_removed(self.known_modems[affected_modem])
                
                # Remove from known modems (will be re-added if reconnected)
                del self.known_modems[affected_modem]
            
        except Exception as e:
            logger.error(f"Error handling port removal: {e}")
    
    def _check_modem_availability(self):
        """Check if current modems are still available"""
        try:
            logger.info("🔍 Checking modem availability after device change")
            
            current_ports = set(self._get_system_ports())
            unavailable_modems = []
            
            for imei, modem_info in self.known_modems.items():
                modem_port = modem_info.get('port')
                if modem_port and modem_port not in current_ports:
                    unavailable_modems.append(imei)
            
            # Remove unavailable modems
            for imei in unavailable_modems:
                logger.info(f"🔌❌ Modem {imei} no longer available")
                
                if self.on_modem_removed:
                    self.on_modem_removed(self.known_modems[imei])
                
                del self.known_modems[imei]
            
        except Exception as e:
            logger.error(f"Error checking modem availability: {e}")
    
    def start_full_scan(self):
        """Start full COM port scan"""
        if self.scanning:   
            logger.warning("Scan already in progress")
            return
        
        logger.info("Starting full COM port scan")
        self.scanning = True
        self.scan_thread = threading.Thread(target=self._full_scan_worker, daemon=True)
        self.scan_thread.start()
    
    def quick_scan(self, specific_ports: List[str] = None):
        """Quick scan of specific ports or recently changed ports"""
        if specific_ports:
            logger.info(f"Starting quick scan of ports: {specific_ports}")
            threading.Thread(target=self._quick_scan_worker, 
                           args=(specific_ports,), daemon=True).start()
        else:
            # Quick scan of system-detected ports
            available_ports = self._get_system_ports()
            if available_ports:
                logger.info(f"Starting quick scan of {len(available_ports)} system ports")
                threading.Thread(target=self._quick_scan_worker, 
                               args=(available_ports,), daemon=True).start()
    
    def _full_scan_worker(self):
        """Worker thread for full COM port scan"""
        try:
            logger.info(f"Scanning COM ports 1-{self.max_com_ports}")
            
            # Get all possible COM ports
            all_ports = [f"COM{i}" for i in range(1, self.max_com_ports + 1)]
            
            # Filter to find available ports
            available_ports = []
            for port in all_ports:
                try:
                    # Quick availability check
                    with serial.Serial(port, timeout=0.1) as ser:
                        available_ports.append(port)
                except serial.SerialException:
                    continue
                except Exception as e:
                    logger.debug(f"Error checking port {port}: {e}")
                    continue
                
                # Small delay to prevent overwhelming the system
                time.sleep(self.port_scan_delay)
                
                if not self.scanning:
                    break
            
            logger.info(f"Found {len(available_ports)} available COM ports")
            
            if available_ports:
                self._process_detected_ports(available_ports)
            
        except Exception as e:
            logger.error(f"Error in full scan worker: {e}")
        finally:
            self.scanning = False
            if self.on_scan_complete:
                self.on_scan_complete()
    
    def _quick_scan_worker(self, ports: List[str]):
        """Worker thread for quick port scan"""
        try:
            logger.info(f"Quick scanning {len(ports)} ports")
            self._process_detected_ports(ports)
        except Exception as e:
            logger.error(f"Error in quick scan worker: {e}")
    
    def _process_detected_ports(self, ports: List[str]):
        """Process detected ports to find valid modems"""
        try:
            # Use port filter to identify valid modem ports
            valid_modems = port_filter.filter_ports(ports)
            
            logger.info(f"Found {len(valid_modems)} valid modems")
            
            # Debug: Print each modem info
            for i, modem_info in enumerate(valid_modems):
                logger.debug(f"Modem {i+1} keys: {list(modem_info.keys())}")
                logger.debug(f"Modem {i+1} data: {modem_info}")
            
            # Process each detected modem
            for modem_info in valid_modems:
                self._process_detected_modem(modem_info)
            
            # Check for removed modems
            self._check_removed_modems(valid_modems)
            
        except Exception as e:
            logger.error(f"Error processing detected ports: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
    
    def _process_detected_modem(self, modem_info: Dict[str, str]):
        """Process a single detected modem"""
        try:
            logger.debug(f"Processing modem_info: {modem_info}")
            
            # Validate required keys
            if 'imei' not in modem_info:
                logger.error("Modem info missing 'imei' key")
                return
            if 'port' not in modem_info:
                logger.error("Modem info missing 'port' key")
                return
                
            imei = modem_info['imei']
            port = modem_info['port']  # Single best port
            
            # Check if this is a new modem
            if imei not in self.known_modems:
                logger.info(f"New modem detected: IMEI {imei} on port {port}")
                
                # Add to database (no port tracking)
                try:
                    modem_id = db.add_modem(imei)
                    
                    # Update known modems
                    self.known_modems[imei] = {
                        'id': modem_id,
                        'imei': imei,
                        'port': port,  # Current working port
                        'sim_status': modem_info.get('sim_status', 'UNKNOWN'),
                        'signal_quality': modem_info.get('signal_quality', '0,0'),
                        'is_diagnostic': modem_info.get('is_diagnostic', False)
                    }
                    
                    # Trigger callback
                    if self.on_modem_detected:
                        self.on_modem_detected(self.known_modems[imei])
                    
                    logger.info(f"Modem {imei} added to system")
                    
                except Exception as e:
                    logger.error(f"Failed to add modem {imei} to database: {e}")
            
            else:
                # Update existing modem port if changed
                existing_modem = self.known_modems[imei]
                existing_port = existing_modem.get('port')  # May be None if not set
                
                if existing_port != port:
                    logger.info(f"Updating modem {imei} port from {existing_port} to {port}")
                    
                    # Update known modems
                    self.known_modems[imei].update({
                        'port': port,
                        'sim_status': modem_info.get('sim_status', 'UNKNOWN'),
                        'signal_quality': modem_info.get('signal_quality', '0,0'),
                        'is_diagnostic': modem_info.get('is_diagnostic', False)
                    })
            
        except Exception as e:
            logger.error(f"Error processing modem: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            logger.error(f"Modem info that caused error: {modem_info}")
    
    def _check_removed_modems(self, current_modems: List[Dict[str, str]]):
        """Check for modems that were removed"""
        try:
            current_imeis = {modem['imei'] for modem in current_modems}
            known_imeis = set(self.known_modems.keys())
            
            removed_imeis = known_imeis - current_imeis
            
            for imei in removed_imeis:
                logger.info(f"Modem {imei} appears to be removed")
                
                # Don't immediately remove from database - just mark as potentially offline
                # This prevents false positives from temporary disconnections
                
                # Trigger callback
                if self.on_modem_removed:
                    self.on_modem_removed(self.known_modems[imei])
                
                # Remove from known modems (will be re-added if detected again)
                del self.known_modems[imei]
            
        except Exception as e:
            logger.error(f"Error checking removed modems: {e}")
    
    def _get_system_ports(self) -> List[str]:
        """Get COM ports detected by the system"""
        try:
            ports = serial.tools.list_ports.comports()
            return [port.device for port in ports]
        except Exception as e:
            logger.error(f"Failed to get system ports: {e}")
            return []
    
    def _start_device_monitoring(self):
        """Start monitoring for device events (Windows)"""
        try:
            # This is a simplified implementation
            # In production, you might want to use Windows API for device events
            threading.Thread(target=self._device_monitor_worker, daemon=True).start()
        except Exception as e:
            logger.error(f"Failed to start device monitoring: {e}")
    
    def _device_monitor_worker(self):
        """Worker thread for device event monitoring"""
        try:
            last_ports = set(self._get_system_ports())
            
            while self.device_event_monitoring:
                time.sleep(2)  # Check every 2 seconds
                
                current_ports = set(self._get_system_ports())
                
                # Check for new ports
                new_ports = current_ports - last_ports
                if new_ports:
                    logger.info(f"New ports detected: {new_ports}")
                    self.quick_scan(list(new_ports))
                
                # Check for removed ports
                removed_ports = last_ports - current_ports
                if removed_ports:
                    logger.info(f"Ports removed: {removed_ports}")
                    # Handle port removal if needed
                
                last_ports = current_ports
            
        except Exception as e:
            logger.error(f"Error in device monitor worker: {e}")
    
    def _load_known_modems(self):
        """Load known modems from database"""
        try:
            modems = db.get_all_modems()
            for modem in modems:
                self.known_modems[modem['imei']] = modem
            
            logger.info(f"Loaded {len(self.known_modems)} known modems from database")
            
        except Exception as e:
            logger.error(f"Failed to load known modems: {e}")
    
    def get_known_modems(self) -> Dict[str, Dict]:
        """Get all known modems"""
        return self.known_modems.copy()
    
    def get_modem_by_imei(self, imei: str) -> Optional[Dict]:
        """Get modem by IMEI"""
        return self.known_modems.get(imei)
    
    def refresh_modem_info(self, imei: str) -> bool:
        """Refresh information for a specific modem"""
        try:
            modem = self.known_modems.get(imei)
            if not modem:
                return False
            
            # Test the modem's primary port
            ports_to_test = [modem['primary_port']]
            self.quick_scan(ports_to_test)
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to refresh modem {imei}: {e}")
            return False
    
    def force_rescan(self):
        """Force a complete rescan of all ports"""
        logger.info("Forcing complete rescan")
        self.known_modems.clear()
        self.start_full_scan()

# Global modem detector instance
modem_detector = ModemDetector()
