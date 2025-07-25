"""
SimPulse SIM Manager
One-time SIM information extraction (balance and phone number)
"""

import serial
import time
import re
import logging
import threading
from typing import Dict, Optional, Callable, List
from datetime import datetime
from .config import (
    BALANCE_COMMAND, 
    NUMBER_COMMAND,
    AT_TIMEOUT,
    CONNECTION_TIMEOUT,
    BAUD_RATE,
    MAX_ERROR_RETRIES,
    ERROR_RETRY_DELAY
)
from .database import db

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
    """Extract only balance amount from decoded text - returns clean number like 100.00"""
    try:
        import re
        # Look for balance patterns (100,00DA or similar)
        balance_match = re.search(r'(\d+[,.]?\d*)\s*DA', text)
        if balance_match:
            # Return just the number, standardized with decimal separator
            return balance_match.group(1).replace(',', '.')
        
        # Alternative pattern for numbers with currency
        balance_match = re.search(r'(\d+[,.]?\d*)', text)
        if balance_match:
            # Return just the number, standardized with decimal separator  
            return balance_match.group(1).replace(',', '.')
            
        return None
    except Exception as e:
        logger.error(f"Failed to extract balance from text: {e}")
        return None

def extract_phone_number_only(decoded_response: str) -> Optional[str]:
    """Extract only the phone number from decoded response"""
    try:
        if not decoded_response:
            return None
        
        # Look for phone number patterns (digits only)
        # Common patterns: 213654666769, +213654666769, 0654666769
        
        # First try to find a long number (IMSI-style, 12-15 digits)
        long_number_match = re.search(r'(\d{12,15})', decoded_response)
        if long_number_match:
            return long_number_match.group(1)
        
        # Then try to find any phone number pattern
        phone_patterns = [
            r'\+?(\d{10,14})',  # International format
            r'(\d{10,14})',     # Local format
            r'(\d{3,4}[\s\-]?\d{3,4}[\s\-]?\d{3,4})',  # Formatted number
        ]
        
        for pattern in phone_patterns:
            match = re.search(pattern, decoded_response)
            if match:
                # Clean the number (remove spaces and dashes)
                number = re.sub(r'[\s\-]', '', match.group(1))
                if len(number) >= 9:  # Minimum phone number length
                    return number
        
        return None
        
    except Exception as e:
        logger.error(f"Error extracting phone number: {e}")
        return None

def extract_balance_amount_only(decoded_response: str) -> Optional[str]:
    """Extract only the balance amount from decoded response with ENHANCED European number format handling"""
    try:
        if not decoded_response:
            return None
        
        logger.debug(f"🔍 ENHANCED: Extracting balance from: {decoded_response}")
        
        # ENHANCED balance patterns with COMPLETE AMOUNT preservation
        # European format: 48.410,82DA -> 48410.82 (PRESERVE COMPLETE AMOUNT)
        # US format: 48,410.82DA -> 48410.82 (PRESERVE COMPLETE AMOUNT)
        # User requirement: 48.410,82 + 1000 = 49.410,82 (complete amounts only)
        
        balance_patterns = [
            # European format with thousands and decimal: 48.410,82DA -> 48410.82
            r'(\d{1,3}(?:\.\d{3})*,\d{2})\s*(?:DA|DZD)',  # 48.410,82DA or 1.234.567,89DA
            r'Solde\s+(\d{1,3}(?:\.\d{3})*,\d{2})',  # Solde 48.410,82
            r'Balance\s+(\d{1,3}(?:\.\d{3})*,\d{2})',  # Balance 48.410,82
            
            # European format without thousands: 410,82DA -> 410.82
            r'(\d+,\d{2})\s*(?:DA|DZD)',  # 410,82DA
            r'Solde\s+(\d+,\d{2})',  # Solde 410,82
            r'Balance\s+(\d+,\d{2})',  # Balance 410,82
            
            # US format with thousands and decimal: 48,410.82DA -> 48410.82
            r'(\d{1,3}(?:,\d{3})*\.\d{2})\s*(?:DA|DZD)',  # 48,410.82DA
            
            # US format without thousands: 410.82DA -> 410.82
            r'(\d+\.\d{2})\s*(?:DA|DZD)',  # 410.82DA
            
            # Thousands separator only: 48.410DA -> 48410.00 (FIXED)
            r'(\d{1,3}(?:\.\d{3})+)\s*(?:DA|DZD)',  # 48.410DA or 1.234.567DA
            
            # Integer amounts: 100DA -> 100.00
            r'(\d+)\s*(?:DA|DZD)',  # 100DA
            
            # Fallback patterns without DA/DZD
            r'(\d{1,3}(?:\.\d{3})*,\d{2})',  # European format: 48.410,82
            r'(\d{1,3}(?:,\d{3})*\.\d{2})',  # US format: 48,410.82
            r'(\d{1,3}(?:\.\d{3})+)',  # Thousands only: 48.410 (FIXED)
            r'(\d+,\d{2})',  # European decimal: 410,82
            r'(\d+\.\d{2})',  # US decimal: 410.82
            r'(\d+)',  # Just any number
        ]
        
        for i, pattern in enumerate(balance_patterns):
            match = re.search(pattern, decoded_response, re.IGNORECASE)
            if match:
                balance_str = match.group(1)
                
                # ENHANCED FIX: Convert to standard format preserving COMPLETE amounts
                # CRITICAL: User wants 48.410,82 + 1000 = 49.410,82 (complete amounts)
                balance_float = _parse_european_number_format(balance_str)
                
                # SPECIAL HANDLING: Detect thousands-only patterns like "48.410"
                if '.' in balance_str and ',' not in balance_str and not balance_str.endswith(('.00', '.82')):
                    # Check if this looks like European thousands format (48.410)
                    if re.match(r'^\d{1,3}(?:\.\d{3})+$', balance_str):
                        # This is thousands format: 48.410 -> 48410.00
                        thousands_amount = float(balance_str.replace('.', ''))
                        balance_formatted = f"{thousands_amount:.2f}"
                        logger.info(f"💰 THOUSANDS FORMAT DETECTED: '{balance_str}' -> {thousands_amount} -> '{balance_formatted}' using pattern {i+1}")
                        logger.info(f"📊 CALCULATION TEST: {thousands_amount} + 1000 = {thousands_amount + 1000}")
                        return balance_formatted
                
                # CRITICAL: Return complete amount as string with proper formatting
                # For amounts like 48410.82, return "48410.82" (NEVER split or truncate)
                balance_formatted = f"{balance_float:.2f}"
                
                logger.info(f"✅ COMPLETE AMOUNT PRESERVED: '{balance_str}' -> {balance_float} -> '{balance_formatted}' using pattern {i+1}")
                logger.info(f"📊 CALCULATION TEST: {balance_float} + 1000 = {balance_float + 1000}")
                return balance_formatted
        
        logger.warning(f"❌ No balance pattern matched in: {decoded_response}")
        return None
        
    except Exception as e:
        logger.error(f"Error extracting balance amount: {e}")
        return None

def _parse_european_number_format(number_str: str) -> float:
    """FIXED: Parse European number format (48.410,82) to standard float (48410.82)"""
    try:
        if not number_str:
            return 0.0
        
        number_clean = str(number_str).strip()
        logger.info(f"� COMPREHENSIVE: Parsing European format: '{number_clean}'")
        
        # FIXED: Handle European vs US number format properly
        if '.' in number_clean and ',' in number_clean:
            # Determine format by position of last dot vs last comma
            last_dot_pos = number_clean.rfind('.')
            last_comma_pos = number_clean.rfind(',')
            
            if last_comma_pos > last_dot_pos:
                # European format: 48.410,82 -> 48410.82
                # Dots are thousands separators, comma is decimal
                # CRITICAL: Keep the complete amount together
                thousands_part = number_clean[:last_comma_pos].replace('.', '')
                decimal_part = number_clean[last_comma_pos + 1:]
                standardized = f"{thousands_part}.{decimal_part}"
                result = float(standardized)
                logger.info(f"🇪🇺 COMPLETE AMOUNT: '{number_clean}' -> '{standardized}' -> {result}")
                return result
            else:
                # US format: 48,410.82 -> 48410.82
                # Commas are thousands separators, dot is decimal
                standardized = number_clean.replace(',', '')
                result = float(standardized)
                logger.info(f"🇺🇸 COMPLETE AMOUNT: '{number_clean}' -> '{standardized}' -> {result}")
                return result
                
        elif ',' in number_clean and '.' not in number_clean:
            # European decimal only: 410,82 -> 410.82
            standardized = number_clean.replace(',', '.')
            result = float(standardized)
            logger.info(f"🇪🇺 DECIMAL ONLY: '{number_clean}' -> '{standardized}' -> {result}")
            return result
            
        elif '.' in number_clean and ',' not in number_clean:
            # Could be US decimal or thousands separator
            if number_clean.count('.') == 1:
                decimal_part = number_clean.split('.')[1]
                if len(decimal_part) == 2:
                    # US decimal: 410.82 -> 410.82
                    result = float(number_clean)
                    logger.info(f"🇺🇸 DECIMAL: '{number_clean}' -> {result}")
                    return result
                else:
                    # Thousands separator: 48.410 -> 48410
                    standardized = number_clean.replace('.', '')
                    result = float(standardized)
                    logger.debug(f"� FIXED Thousands only: {number_clean} -> {standardized} -> {result}")
                    return result
            else:
                # Multiple dots, treat as thousands: 1.234.567 -> 1234567
                standardized = number_clean.replace('.', '')
                result = float(standardized)
                logger.debug(f"� FIXED Multiple thousands: {number_clean} -> {standardized} -> {result}")
                return result
        else:
            # Just a number
            result = float(number_clean)
            logger.info(f"🔢 PLAIN NUMBER: '{number_clean}' -> {result}")
            return result
            
    except Exception as e:
        logger.warning(f"COMPREHENSIVE: Failed to parse European number format '{number_str}': {e}")
        return 0.0

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
        self.on_sim_swap = None
        
        # State
        self.active_extractions = {}  # IMEI -> extraction status
    
    def set_callbacks(self, on_info_extracted: Callable = None, 
                     on_extraction_failed: Callable = None,
                     on_sim_swap: Callable = None):
        """Set event callbacks"""
        self.on_info_extracted = on_info_extracted
        self.on_extraction_failed = on_extraction_failed
        self.on_sim_swap = on_sim_swap
    
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
                previous_sim_data = db.get_sim_info(sim_id)
                db.update_sim_info(sim_id, phone_number, balance)
                
                # Check for SIM swap
                if previous_sim_data and previous_sim_data.get('phone_number'):
                    old_phone = previous_sim_data.get('phone_number')
                    old_balance = previous_sim_data.get('balance', '0.00')
                    
                    # Detect SIM swap (phone number changed)
                    if old_phone != phone_number and old_phone != phone_number:
                        logger.info(f"🔄 SIM SWAP DETECTED for IMEI {imei}!")
                        logger.info(f"Old: {old_phone} ({old_balance}) -> New: {phone_number} ({balance})")
                        
                        # Trigger SIM swap notification
                        if hasattr(self, 'on_sim_swap') and self.on_sim_swap:
                            self.on_sim_swap({
                                'imei': imei,
                                'sim_id': sim_id,
                                'old_phone_number': old_phone,
                                'new_phone_number': phone_number,
                                'old_balance': old_balance,
                                'new_balance': balance
                            })
                
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
        """Extract balance using *222# command - ENHANCED WITH COMPREHENSIVE FALLBACK SYSTEM"""
        try:
            logger.info("💰 ENHANCED: Extracting balance with *222# and comprehensive fallback")
            
            # **METHOD 1: Direct USSD with retry logic**
            for attempt in range(3):
                logger.info(f"🔄 Balance extraction attempt {attempt + 1}/3")
                
                # Send USSD command
                raw_response = self._send_ussd_command_with_timeout(ser, self.balance_command, 25)
                
                if raw_response:
                    logger.info(f"💰 Balance raw response: {raw_response}")
                    
                    # Decode the response
                    decoded_response = decode_ussd_response(raw_response)
                    logger.info(f"💰 Balance decoded: {decoded_response}")
                    
                    # Check if this is an SBC response (SMS will be sent)
                    if self._is_sbc_response(decoded_response):
                        logger.info(f"📱 SBC Response detected - will wait for SMS balance")
                        
                        # **METHOD 2: Wait for balance SMS**
                        sms_balance = self._wait_for_balance_sms(ser, max_wait_seconds=90)
                        if sms_balance:
                            logger.info(f"💰 Balance from SMS: {sms_balance}")
                            return sms_balance
                        else:
                            logger.warning(f"⚠️  No balance SMS received, trying alternative extraction")
                    else:
                        # Extract balance amount directly - NO SMS WAITING
                        balance_amount = extract_balance_amount_only(decoded_response)
                        if balance_amount:
                            logger.info(f"💰 Balance from USSD: {balance_amount}")
                            return balance_amount
                        else:
                            # **METHOD 3: Try alternative extraction patterns**
                            alt_balance = self._extract_balance_alternative(decoded_response)
                            if alt_balance:
                                logger.info(f"💰 Balance from alternative extraction: {alt_balance}")
                                return alt_balance
                            
                            logger.warning(f"⚠️  Could not extract balance from: {decoded_response}")
                else:
                    logger.warning(f"⚠️  No USSD response on attempt {attempt + 1}")
                
                # Wait before retry
                if attempt < 2:
                    time.sleep(3)
            
            # **METHOD 4: Try simple AT commands for balance info**
            logger.warning("💰 All USSD attempts failed, trying AT command alternatives")
            at_balance = self._try_at_balance_commands(ser)
            if at_balance:
                logger.info(f"💰 Balance from AT commands: {at_balance}")
                return at_balance
            
            # **METHOD 5: Return decoded response as is for manual review**
            if 'decoded_response' in locals() and decoded_response:
                logger.info("💰 Returning decoded response for manual analysis")
                return decoded_response
            
            logger.warning("💰 All balance extraction methods failed")
            return None
                
        except Exception as e:
            logger.error(f"Failed to extract balance: {e}")
            return None
    
    def _is_sbc_response(self, response: str) -> bool:
        """Check if response indicates SMS balance check (SBC)"""
        if not response:
            return False
        
        sbc_patterns = [
            r'Votre\s+demande\s+est\s+prise\s+en\s+charge',
            r'un\s+SMS\s+vous\s+sera\s+envoyé',
            r'Your\s+request\s+is\s+being\s+processed',
            r'SMS\s+will\s+be\s+sent',
            r'Request\s+processed',
            r'Balance\s+will\s+be\s+sent'
        ]
        
        for pattern in sbc_patterns:
            if re.search(pattern, response, re.IGNORECASE):
                logger.info(f"📱 SBC Response detected: {response}")
                return True
        
        return False

    def _extract_balance_alternative(self, response: str) -> Optional[str]:
        """Try alternative patterns to extract balance"""
        try:
            alt_patterns = [
                r'(\d+[.,]\d{2})\s*(?:DA|DZD|دج)',  # Number with currency
                r'(\d+)\s*[.,]\s*(\d{2})\s*(?:DA|DZD|دج)',  # Split format
                r'Credit[:\s]*(\d+[.,]\d+)',  # Credit keyword
                r'Available[:\s]*(\d+[.,]\d+)',  # Available keyword
                r'(\d+[.,]\d+)',  # Any decimal number
                r'(\d{2,6})',     # Any significant whole number
            ]
            
            for pattern in alt_patterns:
                match = re.search(pattern, response, re.IGNORECASE)
                if match:
                    if len(match.groups()) > 1:
                        balance = f"{match.group(1)}.{match.group(2)}"
                    else:
                        balance = match.group(1).replace(',', '.')
                    
                    # Validate balance range
                    try:
                        balance_float = float(balance)
                        if 0 <= balance_float <= 50000:
                            return balance
                    except ValueError:
                        continue
            
            return None
            
        except Exception as e:
            logger.error(f"Alternative balance extraction failed: {e}")
            return None

    def _try_at_balance_commands(self, ser: serial.Serial) -> Optional[str]:
        """Try alternative AT commands for balance information"""
        try:
            logger.info("💰 Trying alternative AT commands for balance")
            
            # Try different USSD codes that might work
            alternative_codes = ['*222*1#', '*222*2#', '*100#', '*120#']
            
            for code in alternative_codes:
                logger.info(f"💰 Trying alternative code: {code}")
                response = self._send_ussd_command_with_timeout(ser, code, 15)
                
                if response:
                    decoded = decode_ussd_response(response)
                    balance = extract_balance_amount_only(decoded)
                    if balance:
                        logger.info(f"💰 Alternative code {code} worked: {balance}")
                        return balance
                
                time.sleep(2)  # Wait between attempts
            
            logger.warning("💰 No alternative AT commands worked")
            return None
            
        except Exception as e:
            logger.error(f"AT balance commands failed: {e}")
            return None

    def _is_sms_confirmation_response(self, response: str) -> bool:
        """Check if response indicates SMS will be sent"""
        if not response:
            return False
        
        confirmation_patterns = [
            r'Votre\s+demande\s+est\s+prise\s+en\s+charge',
            r'un\s+SMS\s+vous\s+sera\s+envoyé',
            r'Your\s+request\s+is+being\s+processed',
            r'SMS\s+will\s+be\s+sent'
        ]
        
        for pattern in confirmation_patterns:
            if re.search(pattern, response, re.IGNORECASE):
                logger.debug(f"SMS confirmation pattern matched: {pattern}")
                return True
        
        return False
    
    def _wait_for_balance_sms(self, ser: serial.Serial, max_wait_seconds: int = 90) -> Optional[str]:
        """Wait for balance SMS after confirmation - INCREASED TIMEOUT"""
        logger.info(f"⏱️  Waiting up to {max_wait_seconds} seconds for balance SMS...")
        
        start_time = time.time()
        
        while time.time() - start_time < max_wait_seconds:
            try:
                # Check for SMS messages every 3 seconds
                messages = self._check_for_sms_messages(ser)
                
                for msg in messages:
                    content = msg.get('content', '')
                    logger.debug(f"📨 Checking SMS: {content[:50]}...")
                    
                    # Check if this SMS contains balance info
                    if self._is_balance_sms(content):
                        logger.info(f"✅ Balance SMS found: {content}")
                        
                        # Extract balance from SMS - use the same method as balance extraction
                        balance = extract_balance_amount_only(content)
                        if balance:
                            logger.info(f"💰 Balance amount extracted from SMS: {balance}")
                            # Delete the SMS after reading
                            self._delete_sms_message(ser, msg.get('index'))
                            return balance
                
                # Wait 3 seconds before checking again
                time.sleep(3)
                
            except Exception as e:
                logger.warning(f"Error while waiting for balance SMS: {e}")
                time.sleep(3)
        
        logger.warning(f"⏰ Timeout: No balance SMS received within {max_wait_seconds} seconds")
        return None
    
    def _check_for_sms_messages(self, ser: serial.Serial) -> List[Dict]:
        """Check for new SMS messages"""
        try:
            # Set SMS text mode
            ser.write("AT+CMGF=1\r\n".encode())
            time.sleep(0.5)
            
            # List all messages
            ser.write('AT+CMGL="ALL"\r\n'.encode())
            
            response = ""
            start_time = time.time()
            
            while time.time() - start_time < 5:
                if ser.in_waiting > 0:
                    data = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
                    response += data
                    if "OK" in response or "ERROR" in response:
                        break
                time.sleep(0.1)
            
            # Parse SMS messages from response
            return self._parse_sms_list(response)
            
        except Exception as e:
            logger.error(f"Failed to check SMS messages: {e}")
            return []
    
    def _parse_sms_list(self, response: str) -> List[Dict]:
        """Parse SMS list response"""
        messages = []
        
        try:
            lines = response.split('\n')
            i = 0
            
            while i < len(lines):
                line = lines[i].strip()
                
                # Look for +CMGL response line
                if line.startswith('+CMGL:'):
                    # Parse header
                    match = re.search(r'\+CMGL:\s*(\d+),"([^"]*?)","([^"]*?)","([^"]*?)"', line)
                    if match:
                        index = int(match.group(1))
                        status = match.group(2)
                        sender = match.group(3)
                        timestamp = match.group(4)
                        
                        # Get message content from next line
                        if i + 1 < len(lines):
                            content = lines[i + 1].strip()
                            
                            message = {
                                'index': index,
                                'status': status,
                                'sender': sender,
                                'content': content,
                                'timestamp': timestamp
                            }
                            
                            messages.append(message)
                
                i += 1
                
        except Exception as e:
            logger.error(f"Failed to parse SMS list: {e}")
            
        return messages
    
    def _is_balance_sms(self, content: str) -> bool:
        """Check if SMS content contains balance information"""
        balance_patterns = [
            r'Solde\s+\d+[.,]\d+\s*(?:DZD|DA)',
            r'Sama.*Solde',
            r'Balance.*\d+[.,]\d+',
            r'Credit.*\d+[.,]\d+'
        ]
        
        for pattern in balance_patterns:
            if re.search(pattern, content, re.IGNORECASE):
                return True
        
        return False
    
    def _extract_balance_from_sms_content(self, content: str) -> Optional[str]:
        """Extract balance amount from SMS content"""
        try:
            # Pattern: "Solde 35,97DA" or similar
            balance_patterns = [
                r'Solde\s+(\d+[.,]\d+)\s*(?:DZD|DA)',
                r'Balance\s+(\d+[.,]\d+)',
                r'Credit\s+(\d+[.,]\d+)'
            ]
            
            for pattern in balance_patterns:
                match = re.search(pattern, content, re.IGNORECASE)
                if match:
                    balance_str = match.group(1)
                    # Normalize decimal separator
                    balance_str = balance_str.replace(',', '.')
                    logger.debug(f"Extracted balance from SMS: {balance_str}")
                    return balance_str
            
            logger.warning(f"Could not extract balance from SMS: {content}")
            return None
            
        except Exception as e:
            logger.error(f"Failed to extract balance from SMS: {e}")
            return None
    
    def _delete_sms_message(self, ser: serial.Serial, message_index: int) -> bool:
        """Delete SMS message after reading"""
        try:
            command = f"AT+CMGD={message_index}"
            ser.write(f"{command}\r\n".encode())
            
            response = ""
            start_time = time.time()
            
            while time.time() - start_time < 3:
                if ser.in_waiting > 0:
                    data = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
                    response += data
                    if "OK" in response:
                        logger.debug(f"✅ SMS message {message_index} deleted")
                        return True
                    elif "ERROR" in response:
                        logger.warning(f"⚠️  Failed to delete SMS {message_index}: {response}")
                        return False
                time.sleep(0.1)
            
            return False
            
        except Exception as e:
            logger.error(f"Failed to delete SMS message {message_index}: {e}")
            return False
    
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
        """Extract SIM information sequentially - use the single best port for each modem"""
        imei = sim_info['imei']
        sim_id = sim_info['id']
        port = sim_info['port']  # Single best port from modem detector
        
        logger.info(f"🔄 Starting sequential SIM extraction for IMEI {imei} on port {port}")
        
        # Mark as active
        self.active_extractions[imei] = {
            'sim_id': sim_id,
            'port': port,
            'status': 'extracting',
            'start_time': time.time()
        }
        
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
                        continue
                    
                    # Check SIM status
                    sim_status = self._check_sim_status(ser)
                    if sim_status != "READY":
                        logger.warning(f"⚠️  IMEI {imei}: SIM not ready on port {port}: {sim_status}")
                        continue
                    
                    logger.info(f"📞 IMEI {imei}: SIM is ready on port {port}, starting USSD extraction")
                    
                    # ENHANCED STEP 1: Extract phone number with retry logic
                    logger.info(f"📱 IMEI {imei}: Step 1/2 - Extracting phone number with *101#")
                    phone_number = None
                    for phone_attempt in range(3):  # Try up to 3 times
                        logger.info(f"📱 IMEI {imei}: Phone attempt {phone_attempt + 1}/3")
                        phone_number = self._extract_phone_number_with_timeout(ser, 20)
                        if phone_number:
                            logger.info(f"✅ IMEI {imei}: Phone number extracted: {phone_number}")
                            break
                        else:
                            logger.warning(f"⚠️  IMEI {imei}: Phone attempt {phone_attempt + 1} failed")
                            if phone_attempt < 2:  # Don't wait after last attempt
                                time.sleep(2)
                    
                    # If no phone number after 3 attempts, STOP here
                    if not phone_number:
                        logger.error(f"❌ IMEI {imei}: Failed to get phone number after 3 attempts - STOPPING extraction")
                        return
                    
                    logger.info(f"📱 IMEI {imei}: Phone number: {phone_number}")
                    
                    # Wait between USSD commands
                    logger.info(f"⏱️  IMEI {imei}: Waiting 3 seconds between USSD commands...")
                    time.sleep(3)
                    
                    # ENHANCED STEP 2: Extract balance with SBC detection
                    logger.info(f"💰 IMEI {imei}: Step 2/2 - Extracting balance with *222#")
                    balance = self._extract_balance_with_timeout(ser, 20)  # 20 second timeout
                    
                    # Check if balance is SBC response (balance will come via SMS)
                    balance_extracted = False
                    if balance:
                        # Import balance checker to detect SBC
                        from .balance_checker import balance_checker
                        if balance_checker.detect_sbc_response(balance):
                            logger.info(f"� IMEI {imei}: SBC response detected - balance will come via SMS")
                            balance = None  # Set to None to indicate SMS expected
                        else:
                            logger.info(f"💰 IMEI {imei}: Direct balance extracted: {balance}")
                            balance_extracted = True
                    else:
                        logger.warning(f"⚠️  IMEI {imei}: No balance response received")
                    
                    # Only proceed if we have phone number (required)
                    if phone_number:
                        logger.info(f"💾 IMEI {imei}: Safely saving to database...")
                        
                        if self._safe_update_sim_info(sim_id, phone_number, balance, imei):
                            # Update status
                            self.active_extractions[imei]['status'] = 'completed'
                            self.active_extractions[imei]['working_port'] = port
                            
                            logger.info(f"✅ IMEI {imei}: Sequential extraction completed successfully on port {port}")
                            
                            # Get final data for callback
                            updated_sim = db.get_sim_by_id(sim_id)
                            final_phone = updated_sim.get('phone_number') if updated_sim else phone_number
                            final_balance = updated_sim.get('balance') if updated_sim else balance
                            
                            # Trigger callback
                            if self.on_info_extracted:
                                self.on_info_extracted({
                                    'imei': imei,
                                    'id': sim_id,
                                    'sim_id': sim_id,
                                    'port': port,
                                    'phone_number': final_phone,
                                    'balance': final_balance
                                })
                            
                            if final_phone and final_balance:
                                logger.info(f"✅ IMEI {imei}: SIM successfully registered with complete info")
                            elif final_phone and not final_balance:
                                logger.info(f"✅ IMEI {imei}: SIM registered with phone - balance will update via SMS polling")
                            else:
                                logger.warning(f"⚠️  IMEI {imei}: Partial registration - Phone: {final_phone}, Balance: {final_balance}")
                            
                            # Success - release port and return
                            logger.info(f"🔓 IMEI {imei}: Releasing port {port} and waiting 2 seconds...")
                            time.sleep(2)
                            return
                        else:
                            logger.warning(f"⚠️  IMEI {imei}: Failed to save SIM info safely")
                    else:
                        logger.error(f"❌ IMEI {imei}: No phone number - cannot proceed with registration")
                        
            except OSError as e:
                if "resource is in use" in str(e) or "The requested resource is in use" in str(e):
                    logger.warning(f"⚠️  IMEI {imei}: Port {port} is in use (attempt {attempt + 1}/{max_retries})")
                    if attempt < max_retries - 1:
                        logger.info(f"⏳ IMEI {imei}: Waiting {retry_delay} seconds before retry...")
                        time.sleep(retry_delay)
                        continue
                    else:
                        logger.error(f"❌ IMEI {imei}: Port {port} still in use after {max_retries} attempts")
                        break
                else:
                    logger.error(f"❌ IMEI {imei}: Port error on {port}: {e}")
                    break
                    
            except Exception as e:
                logger.error(f"❌ IMEI {imei}: Extraction error on port {port}: {e}")
                if attempt < max_retries - 1:
                    logger.info(f"⏳ IMEI {imei}: Waiting {retry_delay} seconds before retry...")
                    time.sleep(retry_delay)
                    continue
                else:
                    logger.error(f"❌ IMEI {imei}: Failed on port {port} after {max_retries} attempts")
                    break
        
        # If we reach here, extraction failed
        logger.error(f"❌ IMEI {imei}: Extraction failed on port {port}")
        self.active_extractions[imei]['status'] = 'failed'
        self.active_extractions[imei]['error'] = f"Port {port} failed"
        
        # Trigger callback
        if self.on_extraction_failed:
            self.on_extraction_failed({
                'imei': imei,
                'sim_id': sim_id,
                'error': f"Port {port} failed"
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
                phone_number = extract_phone_number_only(decoded_response)
                logger.info(f"📱 Phone number extracted: {phone_number}")
                
                return phone_number
            else:
                logger.warning("No response received for phone number extraction")
                return None
                
        except Exception as e:
            logger.error(f"Failed to extract phone number: {e}")
            return None
    
    def _extract_balance_with_timeout(self, ser: serial.Serial, timeout: int) -> Optional[str]:
        """Extract balance with specific timeout - DIRECT USSD ONLY"""
        try:
            # Send USSD command
            raw_response = self._send_ussd_command_with_timeout(ser, self.balance_command, timeout)
            
            if raw_response:
                logger.info(f"Balance raw response: {raw_response}")
                
                # Decode the response  
                decoded_response = decode_ussd_response(raw_response)
                logger.info(f"💰 Balance decoded: {decoded_response}")
                
                # Extract balance amount directly - NO SMS WAITING
                balance_amount = extract_balance_amount_only(decoded_response)
                if balance_amount:
                    logger.info(f"💰 Balance amount from USSD: {balance_amount}")
                    return balance_amount
                else:
                    logger.info("💰 No balance amount found, returning decoded text")
                    return decoded_response
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
    
    def _safe_update_sim_info(self, sim_id: int, phone_number: Optional[str], balance: Optional[str], imei: str) -> bool:
        """Safely update SIM info without overwriting existing data with null values and detect SIM swaps"""
        try:
            # Get current data from database to avoid overwriting
            current_sim = db.get_sim_by_id(sim_id)
            current_phone = current_sim.get('phone_number') if current_sim else None
            current_balance = current_sim.get('balance') if current_sim else None
            
            # Use new data if available, otherwise keep existing data
            final_phone = phone_number if phone_number else current_phone
            final_balance = balance if balance else current_balance
            
            logger.info(f"💾 IMEI {imei}: Current DB - Phone: {current_phone}, Balance: {current_balance}")
            logger.info(f"💾 IMEI {imei}: New data - Phone: {phone_number}, Balance: {balance}")
            logger.info(f"💾 IMEI {imei}: Final save - Phone: {final_phone}, Balance: {final_balance}")
            
            # Detect SIM swap (phone number change)
            sim_swap_detected = False
            if current_phone and phone_number and current_phone != phone_number:
                sim_swap_detected = True
                logger.info(f"🔄 SIM SWAP DETECTED for IMEI {imei}:")
                logger.info(f"     Old Phone: {current_phone}")
                logger.info(f"     New Phone: {phone_number}")
                logger.info(f"     Old Balance: {current_balance}")
                logger.info(f"     New Balance: {balance}")
            
            # Only update if we have at least phone number (required field)
            if final_phone:
                # Update database with preserved data
                db.update_sim_info(sim_id, final_phone, final_balance)
                logger.info(f"✅ IMEI {imei}: SIM info updated successfully")
                
                # Trigger SIM swap notification if detected
                if sim_swap_detected:
                    self._handle_sim_swap_notification(
                        imei=imei, 
                        sim_id=sim_id,
                        old_phone=current_phone, 
                        new_phone=phone_number,
                        old_balance=str(current_balance) if current_balance else "0.00",
                        new_balance=balance if balance else "0.00"
                    )
                
                return True
            else:
                logger.warning(f"⚠️  IMEI {imei}: No phone number available (required) - cannot save")
                return False
                
        except Exception as e:
            logger.error(f"❌ IMEI {imei}: Failed to safely update SIM info: {e}")
            return False
    
    def _handle_sim_swap_notification(self, imei: str, sim_id: int, old_phone: str, 
                                    new_phone: str, old_balance: str, new_balance: str):
        """Handle SIM swap notification by getting group info and triggering notification"""
        try:
            # Get modem information
            modem = db.get_modem_by_imei(imei)
            if not modem:
                logger.error(f"Could not find modem for IMEI {imei}")
                return
            
            # Get group information  
            from .group_manager import group_manager
            group = group_manager.get_group_by_modem_id(modem['id'])
            if not group:
                logger.error(f"Could not find group for modem IMEI {imei}")
                return
            
            group_name = group['group_name']
            
            # Trigger the notification through group manager
            group_manager._trigger_sim_swap_notification(
                group_name=group_name,
                imei=imei,
                old_sim_number=old_phone,
                new_sim_number=new_phone,
                old_balance=old_balance,
                new_balance=new_balance
            )
            
            logger.info(f"✅ SIM swap notification initiated for IMEI {imei} in group {group_name}")
            
        except Exception as e:
            logger.error(f"Error handling SIM swap notification for IMEI {imei}: {e}")
    
    def update_balance_from_sms(self, sim_id: int, balance_sms_content: str) -> bool:
        """Update SIM balance from SMS balance message"""
        try:
            logger.info(f"💰 SIM {sim_id}: Attempting to update balance from SMS")
            logger.info(f"💰 SMS content: {balance_sms_content}")
            
            # Extract balance from SMS content
            balance_amount = extract_balance_amount_only(balance_sms_content)
            
            if balance_amount:
                # Get current SIM data
                current_sim = db.get_sim_by_id(sim_id)
                if not current_sim:
                    logger.error(f"❌ SIM {sim_id}: SIM not found in database")
                    return False
                
                current_phone = current_sim.get('phone_number')
                old_balance = current_sim.get('balance', '0.00')
                
                # Update balance while preserving phone number
                if current_phone:
                    db.update_sim_info(sim_id, current_phone, balance_amount)
                    
                    # Record balance history for SMS update
                    old_amount = float(re.sub(r'[^\d.]', '', old_balance) or '0')
                    new_amount = float(re.sub(r'[^\d.]', '', balance_amount) or '0')
                    change_amount = new_amount - old_amount
                    
                    db.add_balance_history(
                        sim_id=sim_id,
                        old_balance=old_balance,
                        new_balance=balance_amount,
                        change_amount=f"{change_amount:+.2f}",
                        change_type='sms_balance_update_simmanager',
                        detected_from_sms=True,
                        sms_sender='SMS_UPDATE',
                        sms_content=balance_sms_content[:500]
                    )
                    
                    logger.info(f"✅ SIM {sim_id}: Balance updated from SMS to {balance_amount}")
                    return True
                else:
                    logger.warning(f"⚠️  SIM {sim_id}: No phone number in database - cannot update safely")
                    return False
            else:
                logger.warning(f"⚠️  SIM {sim_id}: Could not extract balance from SMS content")
                return False
                
        except Exception as e:
            logger.error(f"❌ SIM {sim_id}: Failed to update balance from SMS: {e}")
            return False
    
    def enhanced_balance_extraction(self, sim_info: Dict) -> Optional[Dict]:
        """Enhanced balance extraction with multiple fallback methods"""
        try:
            port = sim_info['port']
            imei = sim_info['imei']
            sim_id = sim_info.get('id')
            
            logger.info(f"🔧 Enhanced balance extraction for IMEI {imei[-6:]} on port {port}")
            
            # Import balance_checker for enhanced extraction
            from .balance_checker import balance_checker
            
            # Use the enhanced balance extraction from balance_checker
            if sim_id:
                result = balance_checker._extract_live_balance_enhanced(sim_info)
                if result and result.get('success'):
                    if result.get('is_sbc_response'):
                        logger.info(f"📱 SBC response for SIM {sim_id} - balance will come via SMS")
                        return {
                            'success': True,
                            'is_sbc_response': True,
                            'method': result.get('method', 'unknown')
                        }
                    else:
                        balance = result.get('balance')
                        logger.info(f"💰 Enhanced extraction successful: {balance}")
                        return {
                            'success': True,
                            'balance': balance,
                            'method': result.get('method', 'unknown')
                        }
            
            # Fallback to original method if enhanced fails
            logger.warning(f"Enhanced extraction failed, trying original method...")
            return self._extract_balance_original(port)
            
        except Exception as e:
            logger.error(f"Enhanced balance extraction failed: {e}")
            return None
    
    def _extract_balance_original(self, port: str) -> Optional[Dict]:
        """Original balance extraction method as fallback"""
        try:
            with serial.Serial(
                port=port,
                baudrate=BAUD_RATE,
                timeout=CONNECTION_TIMEOUT,
                write_timeout=CONNECTION_TIMEOUT
            ) as ser:
                
                if not self._initialize_modem(ser):
                    return None
                
                # Send USSD command for balance
                raw_response = self._send_ussd_command(ser, BALANCE_COMMAND)
                
                if raw_response:
                    decoded_response = decode_ussd_response(raw_response)
                    balance_amount = extract_balance_amount_only(decoded_response)
                    
                    if balance_amount:
                        return {
                            'success': True,
                            'balance': balance_amount,
                            'method': 'original_ussd'
                        }
                
                return None
                
        except Exception as e:
            logger.error(f"Original balance extraction failed: {e}")
            return None
    
    def re_extract_missing_data(self, sim_id: int, missing_data_type: str) -> bool:
        """Re-extract specific missing data for a SIM (phone or balance)"""
        try:
            logger.info(f"🔄 SIM {sim_id}: Re-extracting missing {missing_data_type}")
            
            # Get SIM and modem info
            sim_data = db.get_sim_by_id(sim_id)
            if not sim_data:
                logger.error(f"❌ SIM {sim_id}: Not found in database")
                return False
            
            modem = db.get_modem_by_id(sim_data['modem_id'])
            if not modem:
                logger.error(f"❌ SIM {sim_id}: Modem not found")
                return False
            
            imei = modem['imei']
            
            # Get port from modem detector (live port detection)
            from .modem_detector import modem_detector
            detected_modem = modem_detector.get_modem_by_imei(imei)
            if not detected_modem:
                logger.error(f"❌ SIM {sim_id}: Modem {imei} not found in detector")
                return False
            
            port = detected_modem.get('port')
            if not port:
                logger.error(f"❌ SIM {sim_id}: No port available for modem {imei}")
                return False
            
            logger.info(f"🔄 SIM {sim_id}: Attempting re-extraction on port {port} for {missing_data_type}")
            
            # Connect to modem
            try:
                with serial.Serial(
                    port=port,
                    baudrate=self.baud_rate,
                    timeout=self.connection_timeout,
                    write_timeout=self.connection_timeout
                ) as ser:
                    
                    logger.info(f"✅ SIM {sim_id}: Connected to port {port}")
                    
                    # Initialize modem
                    if not self._initialize_modem(ser):
                        logger.warning(f"⚠️ SIM {sim_id}: Failed to initialize modem")
                        return False
                    
                    # Check SIM status
                    sim_status = self._check_sim_status(ser)
                    if sim_status != "READY":
                        logger.warning(f"⚠️ SIM {sim_id}: SIM not ready: {sim_status}")
                        return False
                    
                    # Extract specific missing data
                    if missing_data_type == "phone":
                        logger.info(f"📱 SIM {sim_id}: Extracting missing phone number...")
                        phone_number = self._extract_phone_number_with_timeout(ser, 20)
                        if phone_number:
                            # Update only phone number, preserve balance
                            current_balance = sim_data.get('balance')
                            db.update_sim_info(sim_id, phone_number, current_balance)
                            logger.info(f"✅ SIM {sim_id}: Phone number extracted: {phone_number}")
                            return True
                        else:
                            logger.warning(f"⚠️ SIM {sim_id}: Failed to extract phone number")
                            return False
                            
                    elif missing_data_type == "balance":
                        logger.info(f"💰 SIM {sim_id}: Extracting missing balance...")
                        balance = self._extract_balance_with_timeout(ser, 20)
                        if balance:
                            # Update only balance, preserve phone number
                            current_phone = sim_data.get('phone_number')
                            db.update_sim_info(sim_id, current_phone, balance)
                            logger.info(f"✅ SIM {sim_id}: Balance extracted: {balance}")
                            return True
                        else:
                            logger.warning(f"⚠️ SIM {sim_id}: Failed to extract balance")
                            return False
                    
                    elif missing_data_type == "both":
                        logger.info(f"📱💰 SIM {sim_id}: Extracting both phone and balance...")
                        
                        # Extract phone first
                        phone_number = self._extract_phone_number_with_timeout(ser, 20)
                        time.sleep(3)  # Wait between commands
                        
                        # Extract balance
                        balance = self._extract_balance_with_timeout(ser, 20)
                        
                        if phone_number or balance:
                            # Preserve existing data
                            final_phone = phone_number if phone_number else sim_data.get('phone_number')
                            final_balance = balance if balance else sim_data.get('balance')
                            db.update_sim_info(sim_id, final_phone, final_balance)
                            logger.info(f"✅ SIM {sim_id}: Extraction complete - Phone: {final_phone}, Balance: {final_balance}")
                            return True
                        else:
                            logger.warning(f"⚠️ SIM {sim_id}: Failed to extract any data")
                            return False
                    
                    else:
                        logger.error(f"❌ SIM {sim_id}: Invalid missing_data_type: {missing_data_type}")
                        return False
                        
            except Exception as e:
                logger.error(f"❌ SIM {sim_id}: Connection error: {e}")
                return False
                
        except Exception as e:
            logger.error(f"❌ SIM {sim_id}: Re-extraction failed: {e}")
            return False

    def fix_all_incomplete_sims(self) -> Dict:
        """Fix all SIMs with incomplete data"""
        logger.info("🔧 Starting fix for all incomplete SIMs...")
        
        results = {
            'fixed': 0,
            'failed': 0,
            'details': []
        }
        
        # Get SIMs needing extraction
        sims_needing = db.get_sims_needing_extraction()
        
        if not sims_needing:
            logger.info("✅ No SIMs need fixing - all have complete data!")
            return results
        
        logger.info(f"🔍 Found {len(sims_needing)} SIMs needing data extraction")
        
        for sim in sims_needing:
            sim_id = sim['id']
            phone = sim.get('phone_number')
            balance = sim.get('balance')
            imei = sim.get('imei')
            
            # Determine what's missing
            missing_phone = not phone or phone == ''
            missing_balance = not balance or balance == ''
            
            if missing_phone and missing_balance:
                missing_type = "both"
            elif missing_phone:
                missing_type = "phone"
            elif missing_balance:
                missing_type = "balance"
            else:
                continue  # Nothing missing
            
            logger.info(f"📱 SIM {sim_id} (IMEI: {imei}): Missing {missing_type}")
            
            # Attempt to fix
            success = self.re_extract_missing_data(sim_id, missing_type)
            
            detail = {
                'sim_id': sim_id,
                'imei': imei,
                'missing_type': missing_type,
                'success': success
            }
            
            if success:
                results['fixed'] += 1
                logger.info(f"✅ SIM {sim_id}: Successfully fixed missing {missing_type}")
            else:
                results['failed'] += 1
                logger.warning(f"⚠️ SIM {sim_id}: Failed to fix missing {missing_type}")
            
            results['details'].append(detail)
            
            # Wait between SIMs to avoid conflicts
            time.sleep(2)
        
        logger.info(f"🎯 Fix completed: {results['fixed']} fixed, {results['failed']} failed")
        return results

# Global SIM manager instance
sim_manager = SIMManager()
