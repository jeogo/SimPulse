"""
SimPulse Port Filter
Smart filtering to identify real modem ports vs diagnostic/auxiliary ports
"""

import re
import logging
import serial
import time
from typing import List, Dict, Optional, Tuple
from config import (
    DIAGNOSTIC_PORT_KEYWORDS, 
    VALID_MODEM_KEYWORDS, 
    AT_TIMEOUT, 
    CONNECTION_TIMEOUT,
    BAUD_RATE,
    PORT_SCAN_DELAY
)

logger = logging.getLogger(__name__)

class PortFilter:
    """Filters and identifies real modem ports from diagnostic/auxiliary ports"""
    
    def __init__(self):
        self.diagnostic_keywords = DIAGNOSTIC_PORT_KEYWORDS
        self.valid_keywords = VALID_MODEM_KEYWORDS
        self.at_timeout = AT_TIMEOUT
        self.connection_timeout = CONNECTION_TIMEOUT
        self.baud_rate = BAUD_RATE
    
    def filter_ports(self, available_ports: List[str]) -> List[Dict[str, str]]:
        """Filter ports to find real modem ports"""
        logger.info(f"Filtering {len(available_ports)} available ports")
        
        valid_ports = []
        
        for port in available_ports:
            try:
                time.sleep(PORT_SCAN_DELAY)  # Small delay between port checks
                
                port_info = self._analyze_port(port)
                if port_info and port_info['is_modem']:
                    valid_ports.append(port_info)
                    logger.info(f"Valid modem port found: {port}")
                else:
                    logger.debug(f"Filtered out port: {port}")
                    
            except Exception as e:
                logger.warning(f"Error analyzing port {port}: {e}")
                continue
        
        # Group ports by IMEI to identify multiple ports for same modem
        grouped_ports = self._group_ports_by_imei(valid_ports)
        
        logger.info(f"Found {len(grouped_ports)} unique modems across {len(valid_ports)} ports")
        return grouped_ports
    
    def _analyze_port(self, port: str) -> Optional[Dict[str, str]]:
        """Analyze a single port to determine if it's a valid modem port"""
        try:
            # First check port name for obvious diagnostic indicators
            if self._is_diagnostic_port_by_name(port):
                logger.debug(f"Port {port} filtered by name")
                return None
            
            # Try to connect and test with AT commands
            port_info = self._test_port_connection(port)
            
            if port_info:
                port_info['port'] = port
                port_info['is_modem'] = self._is_valid_modem_port(port_info)
                return port_info
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to analyze port {port}: {e}")
            return None
    
    def _is_diagnostic_port_by_name(self, port: str) -> bool:
        """Check if port name indicates it's a diagnostic port"""
        try:
            port_lower = port.lower()
            
            # Check for diagnostic keywords
            for keyword in self.diagnostic_keywords:
                if keyword.lower() in port_lower:
                    return True
            
            # Additional checks for common diagnostic port patterns
            diagnostic_patterns = [
                r'diag',
                r'diagnostic',
                r'aux',
                r'auxiliary',
                r'gps',
                r'at.*command',
                r'pc.*ui',
                r'application.*interface'
            ]
            
            for pattern in diagnostic_patterns:
                if re.search(pattern, port_lower):
                    return True
            
            return False
            
        except Exception as e:
            logger.error(f"Failed to check diagnostic port name: {e}")
            return False
    
    def _test_port_connection(self, port: str) -> Optional[Dict[str, str]]:
        """Test port connection with AT commands"""
        try:
            # Try to open serial connection
            with serial.Serial(
                port=port,
                baudrate=self.baud_rate,
                timeout=self.connection_timeout,
                write_timeout=self.connection_timeout
            ) as ser:
                
                # Clear any existing data
                ser.reset_input_buffer()
                ser.reset_output_buffer()
                
                # Test basic AT command
                if not self._send_at_command(ser, "AT"):
                    logger.debug(f"Port {port} doesn't respond to AT")
                    return None
                
                # Get IMEI
                imei = self._get_imei(ser)
                if not imei:
                    logger.debug(f"Port {port} doesn't provide IMEI")
                    return None
                
                # Get additional info
                info = {
                    'imei': imei,
                    'responds_to_at': True,
                    'signal_quality': self._get_signal_quality(ser),
                    'sim_status': self._get_sim_status(ser)
                }
                
                return info
                
        except serial.SerialException as e:
            logger.debug(f"Serial error on port {port}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error testing port {port}: {e}")
            return None
    
    def _send_at_command(self, ser: serial.Serial, command: str) -> bool:
        """Send AT command and check for OK response"""
        try:
            # Send command
            ser.write(f"{command}\r\n".encode())
            
            # Read response
            response = ""
            start_time = time.time()
            
            while time.time() - start_time < self.at_timeout:
                if ser.in_waiting > 0:
                    data = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
                    response += data
                    
                    if "OK" in response:
                        return True
                    elif "ERROR" in response:
                        return False
                
                time.sleep(0.1)
            
            return False
            
        except Exception as e:
            logger.error(f"Failed to send AT command: {e}")
            return False
    
    def _get_imei(self, ser: serial.Serial) -> Optional[str]:
        """Get IMEI from modem"""
        try:
            # Send IMEI command
            ser.write("AT+CGSN\r\n".encode())
            
            # Read response
            response = ""
            start_time = time.time()
            
            while time.time() - start_time < self.at_timeout:
                if ser.in_waiting > 0:
                    data = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
                    response += data
                    
                    if "OK" in response:
                        break
                
                time.sleep(0.1)
            
            # Extract IMEI from response
            imei_match = re.search(r'(\d{15})', response)
            if imei_match:
                return imei_match.group(1)
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to get IMEI: {e}")
            return None
    
    def _get_signal_quality(self, ser: serial.Serial) -> Optional[str]:
        """Get signal quality"""
        try:
            ser.write("AT+CSQ\r\n".encode())
            
            response = ""
            start_time = time.time()
            
            while time.time() - start_time < self.at_timeout:
                if ser.in_waiting > 0:
                    data = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
                    response += data
                    
                    if "OK" in response:
                        break
                
                time.sleep(0.1)
            
            # Extract signal quality
            csq_match = re.search(r'\+CSQ:\s*(\d+),(\d+)', response)
            if csq_match:
                return f"{csq_match.group(1)},{csq_match.group(2)}"
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to get signal quality: {e}")
            return None
    
    def _get_sim_status(self, ser: serial.Serial) -> Optional[str]:
        """Get SIM status"""
        try:
            ser.write("AT+CPIN?\r\n".encode())
            
            response = ""
            start_time = time.time()
            
            while time.time() - start_time < self.at_timeout:
                if ser.in_waiting > 0:
                    data = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
                    response += data
                    
                    if "OK" in response:
                        break
                
                time.sleep(0.1)
            
            # Extract SIM status
            if "READY" in response:
                return "READY"
            elif "PIN" in response:
                return "PIN_REQUIRED"
            elif "PUK" in response:
                return "PUK_REQUIRED"
            else:
                return "UNKNOWN"
            
        except Exception as e:
            logger.error(f"Failed to get SIM status: {e}")
            return None
    
    def _is_valid_modem_port(self, port_info: Dict[str, str]) -> bool:
        """Determine if port is a valid modem port based on collected info"""
        try:
            # Must have IMEI
            if not port_info.get('imei'):
                return False
            
            # Must respond to AT commands
            if not port_info.get('responds_to_at'):
                return False
            
            # Check for valid IMEI format (15 digits)
            imei = port_info.get('imei', '')
            if not re.match(r'^\d{15}$', imei):
                return False
            
            # Additional validation can be added here
            return True
            
        except Exception as e:
            logger.error(f"Failed to validate modem port: {e}")
            return False
    
    def _group_ports_by_imei(self, valid_ports: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """Group ports by IMEI and select the BEST port for each modem (diagnostic/GSM capable)"""
        try:
            imei_groups = {}
            
            for port_info in valid_ports:
                imei = port_info.get('imei')
                if imei:
                    if imei not in imei_groups:
                        imei_groups[imei] = []
                    imei_groups[imei].append(port_info)
            
            # Select the BEST port for each modem (prefer diagnostic ports)
            result = []
            for imei, ports in imei_groups.items():
                # Sort ports to choose the BEST one (diagnostic/GSM capable first)
                ports.sort(key=lambda x: (
                    x.get('sim_status') == 'READY',  # Prefer ports with SIM ready
                    self._is_diagnostic_capable(x.get('port', '')),  # Prefer diagnostic ports
                    x.get('signal_quality', '0').split(',')[0],  # Prefer better signal
                    x.get('port', 'ZZZ')  # Fallback to port name
                ), reverse=True)
                
                best_port = ports[0]  # Select the best port
                
                result.append({
                    'imei': imei,
                    'port': best_port['port'],  # Single best port
                    'sim_status': best_port.get('sim_status', 'UNKNOWN'),
                    'signal_quality': best_port.get('signal_quality', '0,0'),
                    'port_count': len(ports),
                    'is_diagnostic': self._is_diagnostic_capable(best_port.get('port', ''))
                })
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to group ports by IMEI: {e}")
            return []
    
    def test_port_functionality(self, port: str) -> Dict[str, bool]:
        """Test port functionality for various AT commands"""
        try:
            result = {
                'basic_at': False,
                'imei': False,
                'sim_status': False,
                'signal_quality': False,
                'sms_support': False,
                'ussd_support': False
            }
            
            with serial.Serial(
                port=port,
                baudrate=self.baud_rate,
                timeout=self.connection_timeout,
                write_timeout=self.connection_timeout
            ) as ser:
                
                # Test basic AT
                result['basic_at'] = self._send_at_command(ser, "AT")
                
                # Test IMEI
                result['imei'] = self._get_imei(ser) is not None
                
                # Test SIM status
                result['sim_status'] = self._get_sim_status(ser) is not None
                
                # Test signal quality
                result['signal_quality'] = self._get_signal_quality(ser) is not None
                
                # Test SMS support
                result['sms_support'] = self._send_at_command(ser, "AT+CMGF=1")
                
                # Test USSD support
                result['ussd_support'] = self._send_at_command(ser, "AT+CUSD=1")
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to test port functionality: {e}")
            return {k: False for k in result.keys()}
    
    def _is_diagnostic_capable(self, port: str) -> bool:
        """Check if port is diagnostic capable (supports GSM/USSD commands)"""
        try:
            # Test if port supports diagnostic commands
            with serial.Serial(
                port=port,
                baudrate=self.baud_rate,
                timeout=self.connection_timeout,
                write_timeout=self.connection_timeout
            ) as ser:
                
                # Test USSD support
                ussd_support = self._send_at_command(ser, "AT+CUSD=1")
                
                # Test SMS support
                sms_support = self._send_at_command(ser, "AT+CMGF=1")
                
                # Return true if supports both USSD and SMS (diagnostic capable)
                return ussd_support and sms_support
                
        except Exception as e:
            logger.debug(f"Could not test diagnostic capability for port {port}: {e}")
            return False

# Global port filter instance
port_filter = PortFilter()
