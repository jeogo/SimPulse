"""
SimPulse SIM Manager
One-time SIM information extraction (balance and phone number)
"""

import serial
import time
import re
import logging
import threading
from typing import Dict, Optional, Callable
from datetime import datetime
from config import (
    BALANCE_COMMAND, 
    NUMBER_COMMAND,
    AT_TIMEOUT,
    CONNECTION_TIMEOUT,
    BAUD_RATE,
    MAX_ERROR_RETRIES,
    ERROR_RETRY_DELAY
)
from database import db

logger = logging.getLogger(__name__)

def decode_ussd_response(raw_response: str) -> str:
    """Decode USSD response from hex-encoded Unicode"""
    try:
        if not raw_response:
            return ""
        
        # Extract the hex-encoded part from +CUSD response
        # Format: +CUSD: 0,"004300680065007200200063006C00690065006E0074...",72
        import re
        match = re.search(r'\+CUSD:\s*\d+,"([^"]+)"', raw_response)
        if not match:
            return raw_response  # Return as-is if no match
        
        hex_string = match.group(1)
        
        # Convert hex to bytes and decode as UTF-16-BE
        decoded = ""
        for i in range(0, len(hex_string), 4):
            hex_chunk = hex_string[i:i+4]
            if len(hex_chunk) == 4:
                try:
                    # Convert hex to int and then to character
                    char_code = int(hex_chunk, 16)
                    decoded += chr(char_code)
                except ValueError:
                    continue
        
        return decoded.strip()
        
    except Exception as e:
        logger.error(f"Failed to decode USSD response: {e}")
        return raw_response  # Return raw response if decoding fails

def extract_phone_number_from_text(text: str) -> Optional[str]:
    """Extract only phone number from decoded text"""
    try:
        import re
        # Look for phone number patterns (213xxxxxxxxx or similar)
        phone_match = re.search(r'(\+?\d{12,15})', text)
        if phone_match:
            return phone_match.group(1)
        
        # Alternative pattern for Algerian numbers
        phone_match = re.search(r'(\d{12,15})', text)
        if phone_match:
            return phone_match.group(1)
            
        return None
    except Exception as e:
        logger.error(f"Failed to extract phone number from text: {e}")
        return None

def extract_balance_from_text(text: str) -> Optional[str]:
    """Extract only balance amount from decoded text"""
    try:
        import re
        # Look for balance patterns (100,00DA or similar)
        balance_match = re.search(r'(\d+[,.]?\d*\s*DA)', text)
        if balance_match:
            return balance_match.group(1)
        
        # Alternative pattern for numbers with currency
        balance_match = re.search(r'(\d+[,.]?\d*)', text)
        if balance_match:
            return balance_match.group(1) + "DA"
            
        return None
    except Exception as e:
        logger.error(f"Failed to extract balance from text: {e}")
        return None

class SIMManager:
    """Handles one-time SIM information extraction"""
    
    def __init__(self):
        self.balance_command = BALANCE_COMMAND
        self.number_command = NUMBER_COMMAND
        self.at_timeout = AT_TIMEOUT
        self.connection_timeout = CONNECTION_TIMEOUT
        self.baud_rate = BAUD_RATE
        self.max_retries = MAX_ERROR_RETRIES
        self.retry_delay = ERROR_RETRY_DELAY
        
        # Callbacks
        self.on_info_extracted = None
        self.on_extraction_failed = None
        
        # State
        self.active_extractions = {}  # IMEI -> extraction status
    
    def set_callbacks(self, on_info_extracted: Callable = None, 
                     on_extraction_failed: Callable = None):
        """Set event callbacks"""
        self.on_info_extracted = on_info_extracted
        self.on_extraction_failed = on_extraction_failed
    
    def start_extraction_for_new_sims(self):
        """Start extraction for all SIMs that need info extraction - SEQUENTIAL ONLY"""
        try:
            # Get SIMs that need extraction
            sims_needing_extraction = db.get_sims_needing_extraction()
            
            if not sims_needing_extraction:
                logger.info("No SIMs need information extraction")
                return
            
            logger.info(f"Starting SEQUENTIAL extraction for {len(sims_needing_extraction)} SIMs")
            logger.info("⚠️  Processing ONE BY ONE to avoid port conflicts")
            
            # Process SIMs one by one sequentially - NO THREADING
            for i, sim_info in enumerate(sims_needing_extraction):
                logger.info(f"📱 Processing SIM {i+1}/{len(sims_needing_extraction)}: IMEI {sim_info['imei']}")
                
                # Extract info for this SIM and wait for completion
                self.extract_sim_info_sequential(sim_info)
                
                # Add delay between SIM processing to avoid conflicts
                logger.info("⏱️  Waiting 5 seconds before next SIM...")
                time.sleep(5)
                
            logger.info("✅ Sequential SIM extraction completed for all modems")
            
        except Exception as e:
            logger.error(f"Failed to start extraction for new SIMs: {e}")
    
    def extract_sim_info(self, sim_info: Dict):
        """Extract SIM information - REDIRECT TO SEQUENTIAL"""
        logger.info("🔄 Redirecting to sequential extraction to avoid port conflicts")
        self.extract_sim_info_sequential(sim_info)
    
    def _extraction_worker(self, imei: str, sim_id: int, port: str):
        """Worker thread for SIM info extraction"""
        try:
            logger.info(f"Starting extraction worker for IMEI {imei}")
            
            # Connect to modem
            with serial.Serial(
                port=port,
                baudrate=self.baud_rate,
                timeout=self.connection_timeout,
                write_timeout=self.connection_timeout
            ) as ser:
                
                # Initialize modem
                if not self._initialize_modem(ser):
                    raise Exception("Failed to initialize modem")
                
                # Check SIM status
                sim_status = self._check_sim_status(ser)
                if sim_status != "READY":
                    raise Exception(f"SIM not ready: {sim_status}")
                
                # Extract phone number
                phone_number = self._extract_phone_number(ser)
                
                # Extract balance
                balance = self._extract_balance(ser)
                
                # Update database
                db.update_sim_info(sim_id, phone_number, balance)
                
                # Update status
                self.active_extractions[imei]['status'] = 'completed'
                
                logger.info(f"SIM extraction completed for IMEI {imei}")
                logger.info(f"Phone: {phone_number}, Balance: {balance}")
                
                # Trigger callback
                if self.on_info_extracted:
                    self.on_info_extracted({
                        'imei': imei,
                        'id': sim_id,  # Include both id and sim_id for compatibility
                        'sim_id': sim_id,
                        'primary_port': port,
                        'phone_number': phone_number,
                        'balance': balance
                    })
            
            # Add delay to ensure port is fully released before SMS polling starts
            time.sleep(2)
            
        except Exception as e:
            logger.error(f"SIM extraction failed for IMEI {imei}: {e}")
            
            # Update status
            if imei in self.active_extractions:
                self.active_extractions[imei]['status'] = 'failed'
                self.active_extractions[imei]['error'] = str(e)
            
            # Trigger callback
            if self.on_extraction_failed:
                self.on_extraction_failed({
                    'imei': imei,
                    'sim_id': sim_id,
                    'error': str(e)
                })
        
        finally:
            # Clean up
            if imei in self.active_extractions:
                # Keep record for a bit for status checking
                threading.Timer(300, lambda: self.active_extractions.pop(imei, None)).start()
    
    def _initialize_modem(self, ser: serial.Serial) -> bool:
        """Initialize modem for SIM operations"""
        try:
            # Clear buffers
            ser.reset_input_buffer()
            ser.reset_output_buffer()
            
            # Basic AT command
            if not self._send_at_command(ser, "AT"):
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize modem: {e}")
            return False
    
    def _check_sim_status(self, ser: serial.Serial) -> str:
        """Check SIM status"""
        try:
            response = self._send_at_command_with_response(ser, "AT+CPIN?")
            
            if "READY" in response:
                return "READY"
            elif "SIM PIN" in response:
                return "PIN_REQUIRED"
            elif "SIM PUK" in response:
                return "PUK_REQUIRED"
            else:
                return "UNKNOWN"
            
        except Exception as e:
            logger.error(f"Failed to check SIM status: {e}")
            return "ERROR"
    
    def _extract_phone_number(self, ser: serial.Serial) -> Optional[str]:
        """Extract phone number using *101# command - DECODED RESPONSE"""
        try:
            logger.info("Extracting phone number with *101# (decoded response)")
            
            # Send USSD command
            raw_response = self._send_ussd_command(ser, self.number_command)
            
            if raw_response:
                logger.info(f"Phone number raw response: {raw_response}")
                
                # Decode the response
                decoded_response = decode_ussd_response(raw_response)
                logger.info(f"📱 Phone number decoded: {decoded_response}")
                
                return decoded_response
            else:
                logger.warning("No response received for phone number extraction")
                return None
                
        except Exception as e:
            logger.error(f"Failed to extract phone number: {e}")
            return None
    
    def _extract_balance(self, ser: serial.Serial) -> Optional[str]:
        """Extract balance using *222# command - DECODED RESPONSE"""
        try:
            logger.info("Extracting balance with *222# (decoded response)")
            
            # Send USSD command
            raw_response = self._send_ussd_command(ser, self.balance_command)
            
            if raw_response:
                logger.info(f"Balance raw response: {raw_response}")
                
                # Decode the response
                decoded_response = decode_ussd_response(raw_response)
                logger.info(f"💰 Balance decoded: {decoded_response}")
                
                return decoded_response
            else:
                logger.warning("No response received for balance extraction")
                return None
                
        except Exception as e:
            logger.error(f"Failed to extract balance: {e}")
            return None
    
    def _send_ussd_command(self, ser: serial.Serial, command: str) -> Optional[str]:
        """Send USSD command and wait for response with proper AT+CUSD format"""
        try:
            logger.debug(f"Sending USSD command: {command}")
            
            # Clear buffers before sending
            ser.reset_input_buffer()
            ser.reset_output_buffer()
            
            # Send AT command to send USSD with proper format
            ussd_at_command = f'AT+CUSD=1,"{command}",15'
            logger.debug(f"Sending AT command: {ussd_at_command}")
            ser.write(f"{ussd_at_command}\r\n".encode())
            
            # Wait for initial OK response
            response = ""
            start_time = time.time()
            timeout = 2  # Short timeout for initial OK
            
            while time.time() - start_time < timeout:
                if ser.in_waiting > 0:
                    data = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
                    response += data
                    if "OK" in response or "ERROR" in response:
                        break
                time.sleep(0.1)
            
            if "ERROR" in response:
                logger.error(f"USSD command failed: {response}")
                return None
            
            # Now wait for the actual +CUSD response
            logger.debug(f"Waiting for +CUSD response...")
            ussd_response = ""
            start_time = time.time()
            timeout = 30  # Longer timeout for USSD response
            
            while time.time() - start_time < timeout:
                if ser.in_waiting > 0:
                    data = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
                    ussd_response += data
                    logger.debug(f"Received data: {repr(data)}")
                    
                    # Check for +CUSD response
                    if "+CUSD:" in ussd_response:
                        # Wait a bit more for complete response
                        time.sleep(0.5)
                        if ser.in_waiting > 0:
                            data = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
                            ussd_response += data
                        logger.debug(f"Complete +CUSD response: {repr(ussd_response)}")
                        return ussd_response
                
                time.sleep(0.2)
            
            logger.warning(f"No +CUSD response received within {timeout}s for {command}")
            return None
            
        except Exception as e:
            logger.error(f"Failed to send USSD command {command}: {e}")
            return None
           
    
    def _send_at_command(self, ser: serial.Serial, command: str) -> bool:
        """Send AT command and check for OK response"""
        try:
            ser.write(f"{command}\r\n".encode())
            
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
    
    def _send_at_command_with_response(self, ser: serial.Serial, command: str) -> str:
        """Send AT command and return full response"""
        try:
            ser.write(f"{command}\r\n".encode())
            
            response = ""
            start_time = time.time()
            
            while time.time() - start_time < self.at_timeout:
                if ser.in_waiting > 0:
                    data = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
                    response += data
                    
                    if "OK" in response or "ERROR" in response:
                        break
                
                time.sleep(0.1)
            
            return response
            
        except Exception as e:
            logger.error(f"Failed to send AT command with response: {e}")
            return ""
    
    def get_extraction_status(self, imei: str) -> Optional[Dict]:
        """Get extraction status for a specific IMEI"""
        return self.active_extractions.get(imei)
    
    def get_all_extraction_status(self) -> Dict:
        """Get all active extraction statuses"""
        return self.active_extractions.copy()
    
    def create_sim_for_modem(self, modem_id: int) -> int:
        """Create a SIM record for a modem"""
        try:
            sim_id = db.add_sim(modem_id)
            logger.info(f"Created SIM record for modem {modem_id}")
            return sim_id
        except Exception as e:
            logger.error(f"Failed to create SIM for modem {modem_id}: {e}")
            raise
    
    def retry_failed_extraction(self, imei: str):
        """Retry failed extraction for a specific IMEI"""
        try:
            # Get modem info
            modem = db.get_modem_by_imei(imei)
            if not modem:
                logger.error(f"Modem {imei} not found")
                return
            
            # Get SIM info
            sim = db.get_sim_by_modem(modem['id'])
            if not sim:
                logger.error(f"SIM not found for modem {imei}")
                return
            
            # Remove from active extractions if exists
            if imei in self.active_extractions:
                del self.active_extractions[imei]
            
            # Start extraction
            sim_info = {
                'imei': imei,
                'id': sim['id'],
                'primary_port': modem['primary_port']
            }
            
            self.extract_sim_info(sim_info)
            
        except Exception as e:
            logger.error(f"Failed to retry extraction for {imei}: {e}")
    
    def extract_sim_info_sequential(self, sim_info: Dict):
        """Extract SIM information sequentially - try multiple ports for each modem"""
        imei = sim_info['imei']
        sim_id = sim_info['id']
        primary_port = sim_info['primary_port']
        
        # Get all available ports for this modem
        all_ports = sim_info.get('all_ports', primary_port).split(',')
        
        logger.info(f"🔄 Starting sequential SIM extraction for IMEI {imei}")
        logger.info(f"📱 Available ports: {all_ports}")
        
        # Mark as active
        self.active_extractions[imei] = {
            'sim_id': sim_id,
            'ports': all_ports,
            'status': 'extracting',
            'start_time': time.time()
        }
        
        # Try each port until we find one that works
        for port in all_ports:
            logger.info(f"🔌 IMEI {imei}: Trying port {port}")
            
            # Retry logic for port conflicts
            max_retries = 3
            retry_delay = 5  # 5 seconds between retries
            
            for attempt in range(max_retries):
                try:
                    logger.info(f"📱 IMEI {imei}: Attempt {attempt + 1}/{max_retries} - Connecting to port {port}")
                    
                    # Try to connect to modem with timeout
                    with serial.Serial(
                        port=port,
                        baudrate=self.baud_rate,
                        timeout=self.connection_timeout,
                        write_timeout=self.connection_timeout
                    ) as ser:
                        
                        logger.info(f"✅ IMEI {imei}: Connected successfully to port {port}")
                        
                        # Initialize modem
                        if not self._initialize_modem(ser):
                            logger.warning(f"⚠️  IMEI {imei}: Failed to initialize modem on port {port}")
                            break  # Try next port
                        
                        # Check SIM status
                        sim_status = self._check_sim_status(ser)
                        if sim_status != "READY":
                            logger.warning(f"⚠️  IMEI {imei}: SIM not ready on port {port}: {sim_status}")
                            break  # Try next port
                        
                        logger.info(f"📞 IMEI {imei}: SIM is ready on port {port}, starting USSD extraction")
                        
                        # Extract phone number first
                        logger.info(f"📱 IMEI {imei}: Step 1/2 - Extracting phone number with *101#")
                        phone_number = self._extract_phone_number_with_timeout(ser, 20)  # 20 second timeout
                        logger.info(f"📱 IMEI {imei}: Phone number: {phone_number}")
                        
                        # Wait between USSD commands
                        logger.info(f"⏱️  IMEI {imei}: Waiting 3 seconds between USSD commands...")
                        time.sleep(3)
                        
                        # Extract balance second
                        logger.info(f"💰 IMEI {imei}: Step 2/2 - Extracting balance with *222#")
                        balance = self._extract_balance_with_timeout(ser, 20)  # 20 second timeout
                        logger.info(f"💰 IMEI {imei}: Balance: {balance}")
                        
                        # Check if we got at least one piece of information
                        if phone_number or balance:
                            # Update database
                            logger.info(f"💾 IMEI {imei}: Saving to database...")
                            db.update_sim_info(sim_id, phone_number, balance)
                            
                            # Update status
                            self.active_extractions[imei]['status'] = 'completed'
                            self.active_extractions[imei]['working_port'] = port
                            
                            logger.info(f"✅ IMEI {imei}: Sequential extraction completed successfully on port {port}")
                            
                            # Trigger callback if we have complete info
                            if phone_number and balance:
                                if self.on_info_extracted:
                                    self.on_info_extracted({
                                        'imei': imei,
                                        'id': sim_id,
                                        'sim_id': sim_id,
                                        'primary_port': port,
                                        'phone_number': phone_number,
                                        'balance': balance
                                    })
                                logger.info(f"✅ IMEI {imei}: SIM successfully registered with complete info")
                            else:
                                logger.info(f"✅ IMEI {imei}: SIM registered with partial info (Phone: {phone_number}, Balance: {balance})")
                            
                            # Success - release port and return
                            logger.info(f"🔓 IMEI {imei}: Releasing port {port} and waiting 2 seconds...")
                            time.sleep(2)
                            return
                        else:
                            logger.warning(f"⚠️  IMEI {imei}: No USSD responses on port {port}")
                            break  # Try next port
                        
                except OSError as e:
                    if "resource is in use" in str(e) or "The requested resource is in use" in str(e):
                        logger.warning(f"⚠️  IMEI {imei}: Port {port} is in use (attempt {attempt + 1}/{max_retries})")
                        if attempt < max_retries - 1:
                            logger.info(f"⏳ IMEI {imei}: Waiting {retry_delay} seconds before retry...")
                            time.sleep(retry_delay)
                            continue
                        else:
                            logger.warning(f"⚠️  IMEI {imei}: Port {port} still in use after {max_retries} attempts, trying next port")
                            break  # Try next port
                    else:
                        logger.error(f"❌ IMEI {imei}: Port error on {port}: {e}")
                        break  # Try next port
                        
                except Exception as e:
                    logger.error(f"❌ IMEI {imei}: Extraction error on port {port}: {e}")
                    if attempt < max_retries - 1:
                        logger.info(f"⏳ IMEI {imei}: Waiting {retry_delay} seconds before retry...")
                        time.sleep(retry_delay)
                        continue
                    else:
                        logger.warning(f"⚠️  IMEI {imei}: Failed on port {port} after {max_retries} attempts, trying next port")
                        break  # Try next port
        
        # If we reach here, all ports failed
        logger.error(f"❌ IMEI {imei}: All ports failed for extraction")
        self.active_extractions[imei]['status'] = 'failed'
        self.active_extractions[imei]['error'] = "All ports failed"
        
        # Trigger callback
        if self.on_extraction_failed:
            self.on_extraction_failed({
                'imei': imei,
                'sim_id': sim_id,
                'error': "All ports failed"
            })
        
        logger.info(f"🔓 IMEI {imei}: Waiting 2 seconds before next modem...")
        time.sleep(2)
    
    def _extract_phone_number_with_timeout(self, ser: serial.Serial, timeout: int) -> Optional[str]:
        """Extract phone number with specific timeout - ONLY NUMBER"""
        try:
            # Send USSD command
            raw_response = self._send_ussd_command_with_timeout(ser, self.number_command, timeout)
            
            if raw_response:
                logger.info(f"Phone number raw response: {raw_response}")
                
                # Decode the response
                decoded_response = decode_ussd_response(raw_response)
                logger.info(f"📱 Phone number decoded: {decoded_response}")
                
                # Extract ONLY the phone number
                phone_number = extract_phone_number_from_text(decoded_response)
                logger.info(f"📱 Phone number extracted: {phone_number}")
                
                return phone_number
            else:
                logger.warning("No response received for phone number extraction")
                return None
                
        except Exception as e:
            logger.error(f"Failed to extract phone number: {e}")
            return None
    
    def _extract_balance_with_timeout(self, ser: serial.Serial, timeout: int) -> Optional[str]:
        """Extract balance with specific timeout - ONLY BALANCE AMOUNT"""
        try:
            # Send USSD command
            raw_response = self._send_ussd_command_with_timeout(ser, self.balance_command, timeout)
            
            if raw_response:
                logger.info(f"Balance raw response: {raw_response}")
                
                # Decode the response  
                decoded_response = decode_ussd_response(raw_response)
                logger.info(f"💰 Balance decoded: {decoded_response}")
                
                # Extract ONLY the balance amount
                balance_amount = extract_balance_from_text(decoded_response)
                logger.info(f"💰 Balance amount extracted: {balance_amount}")
                
                return balance_amount
            else:
                logger.warning("No response received for balance extraction")
                return None
                
        except Exception as e:
            logger.error(f"Failed to extract balance: {e}")
            return None
    
    def _send_ussd_command_with_timeout(self, ser: serial.Serial, command: str, timeout: int) -> Optional[str]:
        """Send USSD command with specific timeout"""
        try:
            logger.debug(f"Sending USSD command: {command} (timeout: {timeout}s)")
            
            # Clear buffers before sending
            ser.reset_input_buffer()
            ser.reset_output_buffer()
            
            # Send AT command to send USSD with proper format
            ussd_at_command = f'AT+CUSD=1,"{command}",15'
            logger.debug(f"Sending AT command: {ussd_at_command}")
            ser.write(f"{ussd_at_command}\r\n".encode())
            
            # Wait for initial OK response
            response = ""
            start_time = time.time()
            initial_timeout = 2  # Short timeout for initial OK
            
            while time.time() - start_time < initial_timeout:
                if ser.in_waiting > 0:
                    data = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
                    response += data
                    if "OK" in response or "ERROR" in response:
                        break
                time.sleep(0.1)
            
            if "ERROR" in response:
                logger.error(f"USSD command failed: {response}")
                return None
            
            # Now wait for the actual +CUSD response
            logger.debug(f"Waiting for +CUSD response (timeout: {timeout}s)...")
            ussd_response = ""
            start_time = time.time()
            
            while time.time() - start_time < timeout:
                if ser.in_waiting > 0:
                    data = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
                    ussd_response += data
                    logger.debug(f"Received data: {repr(data)}")
                    
                    # Check for +CUSD response
                    if "+CUSD:" in ussd_response:
                        # Wait a bit more for complete response
                        time.sleep(0.5)
                        if ser.in_waiting > 0:
                            data = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
                            ussd_response += data
                        logger.debug(f"Complete +CUSD response: {repr(ussd_response)}")
                        return ussd_response
                
                time.sleep(0.2)
            
            logger.warning(f"No +CUSD response received within {timeout}s for {command}")
            return None
            
        except Exception as e:
            logger.error(f"Failed to send USSD command {command}: {e}")
            return None

# Global SIM manager instance
sim_manager = SIMManager()
