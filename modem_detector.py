"""
SimPulse Modem Detector
Event-driven modem detection that scans ALL COM ports (1-999)
"""

import serial
import serial.tools.list_ports
import threading
import time
import logging
from typing import List, Dict, Optional, Callable
from config import (
    MAX_COM_PORTS, 
    PORT_SCAN_DELAY, 
    MAX_DETECTION_ATTEMPTS,
    STARTUP_FULL_SCAN,
    DEVICE_EVENT_MONITORING
)
from port_filter import port_filter
from database import db

logger = logging.getLogger(__name__)

class ModemDetector:
    """Handles event-driven modem detection across all COM ports"""
    
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
        
        # Initialize with existing modems from database
        self._load_known_modems()
    
    def set_callbacks(self, on_modem_detected: Callable = None, 
                     on_modem_removed: Callable = None,
                     on_scan_complete: Callable = None):
        """Set event callbacks"""
        self.on_modem_detected = on_modem_detected
        self.on_modem_removed = on_modem_removed
        self.on_scan_complete = on_scan_complete
    
    def start_detection(self):
        """Start the modem detection system - ONE TIME ONLY"""
        logger.info("Starting modem detection system (ONE TIME SCAN)")
        
        # Only do full scan once, no continuous monitoring
        self.start_full_scan()
    
    def stop_detection(self):
        """Stop the modem detection system"""
        logger.info("Stopping modem detection system")
        self.scanning = False
        
        if self.scan_thread and self.scan_thread.is_alive():
            self.scan_thread.join(timeout=5)
    
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
            
            # Process each detected modem
            for modem_info in valid_modems:
                self._process_detected_modem(modem_info)
            
            # Check for removed modems
            self._check_removed_modems(valid_modems)
            
        except Exception as e:
            logger.error(f"Error processing detected ports: {e}")
    
    def _process_detected_modem(self, modem_info: Dict[str, str]):
        """Process a single detected modem"""
        try:
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
                if existing_modem['port'] != port:
                    logger.info(f"Updating modem {imei} port from {existing_modem['port']} to {port}")
                    
                    # Update known modems
                    self.known_modems[imei].update({
                        'port': port,
                        'sim_status': modem_info.get('sim_status', 'UNKNOWN'),
                        'signal_quality': modem_info.get('signal_quality', '0,0'),
                        'is_diagnostic': modem_info.get('is_diagnostic', False)
                    })
            
        except Exception as e:
            logger.error(f"Error processing modem: {e}")
    
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
