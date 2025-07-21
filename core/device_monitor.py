"""
SimPulse Device Monitor
Real-time Windows device change detection using WMI
Replaces periodic polling with event-driven hardware monitoring
Thread-safe implementation to avoid COM marshalling errors
"""

import threading
import time
import logging
import serial.tools.list_ports
from typing import Callable, Dict, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# Thread-local storage for WMI connections
import threading
_thread_local = threading.local()

def get_wmi_connection():
    """Get thread-local WMI connection to avoid marshalling errors"""
    if not hasattr(_thread_local, 'wmi_connection'):
        try:
            import wmi
            _thread_local.wmi_connection = wmi.WMI()
            logger.debug(f"Created WMI connection for thread {threading.current_thread().name}")
        except Exception as e:
            logger.error(f"Failed to create WMI connection: {e}")
            _thread_local.wmi_connection = None
    return _thread_local.wmi_connection

class WindowsDeviceMonitor:
    """Real-time Windows device monitoring using WMI events"""
    
    def __init__(self):
        self.monitoring = False
        self.monitor_thread = None
        
        # Event callbacks
        self.on_device_connected = None
        self.on_device_disconnected = None
        self.on_com_port_change = None
        
        # Device tracking
        self.known_devices = {}
        self.known_com_ports = set()
        
        # Thread safety
        self._lock = threading.Lock()
        
        logger.info("WindowsDeviceMonitor initialized (thread-safe)")
    
    def set_callbacks(self, on_device_connected: Callable = None,
                     on_device_disconnected: Callable = None,
                     on_com_port_change: Callable = None):
        """Set event callbacks for device changes"""
        self.on_device_connected = on_device_connected
        self.on_device_disconnected = on_device_disconnected
        self.on_com_port_change = on_com_port_change
        logger.info("Device monitor callbacks configured")
    
    def start_monitoring(self):
        """Start real-time device monitoring"""
        if self.monitoring:
            logger.warning("Device monitoring already active")
            return
        
        try:
            logger.info("🔄 Starting Windows device monitoring (thread-safe)...")
            
            self.monitoring = True
            
            # Get initial device state
            self._get_initial_device_state()
            
            # Start monitoring thread
            self.monitor_thread = threading.Thread(target=self._monitor_worker, daemon=True)
            self.monitor_thread.start()
            
            logger.info("✅ Windows device monitoring started successfully")
            
        except Exception as e:
            logger.error(f"❌ Failed to start device monitoring: {e}")
            self.monitoring = False
            raise
    
    def stop_monitoring(self):
        """Stop device monitoring"""
        logger.info("🛑 Stopping device monitoring...")
        
        self.monitoring = False
        
        # Wait for monitor thread to finish
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=5)
        
        logger.info("✅ Device monitoring stopped")
    
    def _get_initial_device_state(self):
        """Get initial state of devices and COM ports using thread-safe approach"""
        try:
            logger.info("📋 Getting initial device state...")
            
            # Use serial tools for COM port detection (more reliable)
            ports = serial.tools.list_ports.comports()
            for port in ports:
                self.known_com_ports.add(port.device)
            
            # Try WMI for USB devices if available
            wmi_conn = get_wmi_connection()
            if wmi_conn:
                try:
                    usb_devices = wmi_conn.Win32_USBHub()
                    for device in usb_devices:
                        device_id = getattr(device, 'DeviceID', 'Unknown')
                        self.known_devices[device_id] = {
                            'type': 'USB',
                            'name': getattr(device, 'Name', 'Unknown'),
                            'description': getattr(device, 'Description', 'Unknown'),
                            'detected_at': datetime.now()
                        }
                except Exception as e:
                    logger.warning(f"WMI USB device enumeration failed: {e}")
            
            logger.info(f"📋 Initial state: {len(self.known_devices)} USB devices, {len(self.known_com_ports)} COM ports")
            
        except Exception as e:
            logger.error(f"Error getting initial device state: {e}")
    
    def _monitor_worker(self):
        """Main monitoring worker thread using polling approach"""
        try:
            logger.info("🔄 Device monitor worker started (polling mode)")
            
            # Start polling-based monitoring
            self._start_polling_monitoring()
            
        except Exception as e:
            logger.error(f"Error in monitor worker: {e}")
        finally:
            logger.info("📴 Device monitor worker stopped")
    
    def _start_polling_monitoring(self):
        """Start polling-based monitoring for better stability"""
        try:
            logger.info("� Starting polling-based device monitoring...")
            
            last_check_time = time.time()
            check_interval = 3  # Check every 3 seconds
            
            while self.monitoring:
                try:
                    current_time = time.time()
                    
                    # Check for changes every interval
                    if current_time - last_check_time >= check_interval:
                        self._check_device_changes()
                        last_check_time = current_time
                    
                    time.sleep(0.5)  # Small sleep to prevent busy waiting
                    
                except Exception as e:
                    logger.error(f"Error in polling loop: {e}")
                    time.sleep(2)  # Wait before retrying
            
        except Exception as e:
            logger.error(f"Error in polling monitoring: {e}")
    
    def _check_device_changes(self):
        """Check for device changes using polling"""
        try:
            # Check COM port changes
            self._check_com_port_changes()
            
            # Check USB device changes (less frequently)
            if int(time.time()) % 10 == 0:  # Every 10 seconds
                self._check_usb_device_changes()
            
        except Exception as e:
            logger.error(f"Error checking device changes: {e}")
    
    def _check_com_port_changes(self):
        """Check for COM port changes using thread-safe approach"""
        try:
            with self._lock:
                # Use serial tools for more reliable detection
                current_ports = set()
                ports = serial.tools.list_ports.comports()
                for port in ports:
                    current_ports.add(port.device)
                
                # Check for new ports
                new_ports = current_ports - self.known_com_ports
                for port_name in new_ports:
                    logger.info(f"📡✅ New COM port detected: {port_name}")
                    self.known_com_ports.add(port_name)
                    
                    if self.on_com_port_change:
                        change_info = {
                            'type': 'COM_PORT_ADDED',
                            'port': port_name,
                            'timestamp': datetime.now()
                        }
                        # Call callback in separate thread to avoid blocking
                        threading.Thread(
                            target=self.on_com_port_change,
                            args=(change_info,),
                            daemon=True
                        ).start()
                
                # Check for removed ports
                removed_ports = self.known_com_ports - current_ports
                for port_name in removed_ports:
                    logger.info(f"📡❌ COM port removed: {port_name}")
                    self.known_com_ports.discard(port_name)
                    
                    if self.on_com_port_change:
                        change_info = {
                            'type': 'COM_PORT_REMOVED',
                            'port': port_name,
                            'timestamp': datetime.now()
                        }
                        # Call callback in separate thread to avoid blocking
                        threading.Thread(
                            target=self.on_com_port_change,
                            args=(change_info,),
                            daemon=True
                        ).start()
            
        except Exception as e:
            logger.error(f"Error checking COM port changes: {e}")
    
    def _check_usb_device_changes(self):
        """Check for USB device changes"""
        try:
            current_devices = {}
            # Use thread-local WMI connection
            wmi_conn = get_wmi_connection()
            if not wmi_conn:
                logger.warning("No WMI connection available for USB device check")
                return
            
            usb_devices = wmi_conn.Win32_USBHub()
            
            for device in usb_devices:
                device_id = getattr(device, 'DeviceID', 'Unknown')
                current_devices[device_id] = {
                    'type': 'USB',
                    'name': getattr(device, 'Name', 'Unknown'),
                    'description': getattr(device, 'Description', 'Unknown'),
                    'detected_at': datetime.now()
                }
            
            # Check for new devices
            new_device_ids = set(current_devices.keys()) - set(self.known_devices.keys())
            for device_id in new_device_ids:
                logger.info(f"�✅ New USB device: {current_devices[device_id]['name']}")
                self.known_devices[device_id] = current_devices[device_id]
                
                if self.on_device_connected:
                        device_info = {
                            'type': 'USB_CONNECTED',
                            'device_id': device_id,
                            'device': current_devices[device_id],
                            'timestamp': datetime.now()
                        }
                        # Call callback in separate thread
                        threading.Thread(
                            target=self.on_device_connected,
                            args=(device_info,),
                            daemon=True
                        ).start()
            
            # Check for removed devices
            removed_device_ids = set(self.known_devices.keys()) - set(current_devices.keys())
            for device_id in removed_device_ids:
                logger.info(f"�❌ USB device removed: {self.known_devices[device_id]['name']}")
                
                if self.on_device_disconnected:
                    device_info = {
                        'type': 'USB_DISCONNECTED',
                        'device_id': device_id,
                        'device': self.known_devices[device_id],
                        'timestamp': datetime.now()
                    }
                    # Call callback in separate thread
                    threading.Thread(
                        target=self.on_device_disconnected,
                        args=(device_info,),
                        daemon=True
                    ).start()
                
                del self.known_devices[device_id]
            
        except Exception as e:
            logger.error(f"Error checking USB device changes: {e}")
    
    def get_status(self) -> Dict:
        """Get monitoring status"""
        with self._lock:
            return {
                'monitoring': self.monitoring,
                'known_devices': len(self.known_devices),
                'known_com_ports': len(self.known_com_ports),
                'thread_alive': self.monitor_thread.is_alive() if self.monitor_thread else False
            }
    
    def get_current_com_ports(self) -> List[str]:
        """Get current COM ports"""
        return list(self.known_com_ports)

# Global device monitor instance
device_monitor = WindowsDeviceMonitor()
