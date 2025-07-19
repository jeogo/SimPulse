"""
SimPulse Balance Checker
Automatic balance checking triggered by recharge SMS messages
"""

import serial
import time
import re
import logging
from typing import Dict, Optional, Tuple
from datetime import datetime
from .database import db
from .modem_detector import modem_detector
from .sim_manager import decode_ussd_response, extract_balance_amount_only

logger = logging.getLogger(__name__)

class BalanceChecker:
    """Handles automatic balance checking for recharge notifications"""
    
    def __init__(self):
        self.baud_rate = 9600
        self.connection_timeout = 3
        self.at_timeout = 10
        self.balance_command = '*222#'
        
        # MOBLIS SENDER - ZERO TOLERANCE VALIDATION
        # Only this sender triggers balance validation
        self.critical_recharge_sender = '7711198105108105115'  # Moblis
        
        # Enhanced recharge detection patterns for Moblis only
        self.critical_recharge_patterns = [
            r'Vous\s+avez\s+rechargé\s+(\d+[.,]\d+)\s*(?:DZD|DA)\s+avec\s+succès',  # "Vous avez rechargé 100.00 DZD avec succès"
            r'rechargé\s+(\d+[.,]\d+)\s*(?:DZD|DA)\s+avec\s+succès',                # "rechargé 100.00 DA avec succès"
            r'rechargé\s+(\d+[.,]\d+)\s*(?:DZD|DA)',                                # "rechargé 100.00 DA"
            r'recharge\s+de\s+(\d+[.,]\d+)\s*(?:DZD|DA)',                           # "recharge de 100.00 DA"
            r'montant\s+(\d+[.,]\d+)\s*(?:DZD|DA)',                                 # "montant 100.00 DA"
        ]
        
        # SBC (SMS Balance Check) patterns
        self.sbc_patterns = [
            r'Votre\s+demande\s+est\s+prise\s+en\s+charge',
            r'un\s+SMS\s+vous\s+sera\s+envoyé',
            r'Your\s+request\s+is\s+being\s+processed',
            r'SMS\s+will\s+be\s+sent'
        ]
        
        # Real balance SMS patterns 
        self.balance_sms_patterns = [
            r'Solde\s+(\d+[.,]\d+)\s*(?:DZD|DA)',              # "Solde 35,97DA"
            r'Balance\s+(\d+[.,]\d+)\s*(?:DZD|DA)',            # "Balance 35,97DA" 
            r'رصيدك\s+(\d+[.,]\d+)\s*(?:دج|دينار)',            # Arabic balance
            r'الرصيد\s+(\d+[.,]\d+)\s*(?:دج|دينار)'             # Arabic balance
        ]
        
        # Package activation patterns (to ignore)
        self.package_activation_patterns = [
            r'est\s+ajoutée\s+à\s+votre\s+numéro',            # "est ajoutée à votre numéro"
            r'Mix\s+\d+\s+est\s+ajoutée',                      # "Mix 100 est ajoutée"
            r'package\s+activated',                            # English
            r'تم\s+تفعيل\s+الباقة',                             # Arabic package activation
            r'Bonus\s+\d+.*valable',                           # Bonus valid messages
            r'valable\s+au\s+\d+\/\d+\/\d+'                   # Validity dates
        ]
        
        # Enhanced statistics for critical sender validation
        self.stats = {
            'recharge_detected': 0,
            'critical_recharge_detected': 0,
            'balance_checks': 0,
            'successful_checks': 0,
            'failed_checks': 0,
            'validation_mismatches': 0,
            'critical_sender_processed': 0,
            'moblis_recharge_messages': 0,
            'moblis_package_messages': 0,
            'moblis_other_messages': 0,
            'sbc_responses_detected': 0,
            'balance_sms_processed': 0,
            'package_activations_ignored': 0,
            'pending_balance_requests': 0,
            'last_check_time': None
        }
        
        # Track pending balance requests (SBC responses)
        self.pending_balance_requests = {}  # sim_id -> {'timestamp': datetime, 'recharge_info': Dict}
    
    def detect_recharge_message(self, message_content: str, sender: str) -> Optional[Dict]:
        """Detect if an SMS is a recharge notification - ONLY from Moblis (7711198105108105115)"""
        try:
            logger.debug(f"🔍 Checking message from {sender}: {message_content[:100]}...")
            
            # **MOBLIS SENDER DETECTION - ZERO TOLERANCE**
            if sender == self.critical_recharge_sender:
                logger.info(f"🚨 MOBLIS SENDER DETECTED: {sender}")
                self.stats['critical_sender_processed'] += 1
                
                # **FIRST FILTER: Check if this is actually a recharge message**
                if not self._is_recharge_message(message_content):
                    logger.info(f"📱 MOBLIS: Not a recharge message, ignoring: {message_content[:50]}...")
                    return None
                
                # Extract recharge amount using specialized patterns
                recharge_amount = self._extract_critical_recharge_amount(message_content)
                
                if recharge_amount:
                    logger.info(f"💰 MOBLIS RECHARGE DETECTED: {recharge_amount} DZD from {sender}")
                    self.stats['critical_recharge_detected'] += 1
                    return {
                        'is_recharge': True,
                        'is_critical': True,
                        'amount': recharge_amount,
                        'sender': sender,
                        'content': message_content,
                        'validation_required': True
                    }
                else:
                    logger.info(f"📱 MOBLIS: No recharge amount found (not a recharge SMS): {message_content[:50]}...")
                    return None
            
            # **IGNORE ALL OTHER SENDERS**
            # Only Moblis triggers balance validation
            logger.debug(f"📱 Ignoring message from non-Moblis sender: {sender}")
            return None
            
        except Exception as e:
            logger.error(f"Error detecting recharge message: {e}")
            return None
    
    def _extract_critical_recharge_amount(self, content: str) -> Optional[str]:
        """Extract recharge amount from MOBLIS with ZERO TOLERANCE"""
        try:
            logger.info(f"🎯 Extracting amount from Moblis message: {content}")
            
            # Try each Moblis pattern in order of specificity
            for i, pattern in enumerate(self.critical_recharge_patterns):
                match = re.search(pattern, content, re.IGNORECASE)
                if match:
                    amount = match.group(1).replace(',', '.')
                    logger.info(f"✅ MOBLIS AMOUNT EXTRACTED (Pattern {i+1}): {amount} DZD")
                    return amount
            
            # If no pattern matches, log the content for analysis
            logger.error(f"❌ MOBLIS: No amount pattern matched in message: {content}")
            return None
            
        except Exception as e:
            logger.error(f"❌ MOBLIS ERROR extracting recharge amount: {e}")
            return None
    
    def _is_recharge_message(self, content: str) -> bool:
        """Check if a Moblis message is actually about recharge (not package activation)"""
        try:
            # **HANDLE ENCODED/BROKEN MESSAGES**
            if not content or len(content.strip()) < 10:
                logger.debug(f"❓ MOBLIS: Message too short or empty: '{content}'")
                self.stats['moblis_other_messages'] += 1
                return False
            
            # Check for hex-encoded content
            if re.match(r'^[0-9A-Fa-f]+$', content.strip()) and len(content) > 20:
                logger.debug(f"🔗 MOBLIS: Hex-encoded message, treating as non-recharge: {content[:50]}...")
                self.stats['moblis_other_messages'] += 1
                return False
            
            # Check for obviously fragmented messages (start/end with incomplete words)
            if (content.startswith(('cès', 'tion', 'ment')) or 
                content.endswith(('...', 'pour p', 'à votr', 'le serv'))):
                logger.debug(f"🧩 MOBLIS: Fragment message, treating as non-recharge: {content[:50]}...")
                self.stats['moblis_other_messages'] += 1
                return False
            
            content_lower = content.lower()
            
            # **RECHARGE INDICATORS** - These suggest it's a recharge message
            recharge_indicators = [
                'rechargé',
                'recharge',
                'succès',
                'success',
                'payment',
                'paiement',
                'montant',
                'amount',
                'dzd',
                'da ',
                'dinar'
            ]
            
            # **PACKAGE/ACTIVATION INDICATORS** - These suggest it's NOT a recharge message
            package_indicators = [
                'plan',
                'mix',
                'ajouté',
                'ajoutée',
                'activated',
                'valable',
                'valid',
                'bonus',
                'internet',
                'sms',
                'appels',
                'calls',
                'contactez',
                'contact',
                'service client',
                'customer service'
            ]
            
            # Check for recharge indicators
            has_recharge_indicators = any(indicator in content_lower for indicator in recharge_indicators)
            
            # Check for package indicators
            has_package_indicators = any(indicator in content_lower for indicator in package_indicators)
            
            # Decision logic:
            # - If it has recharge indicators and no package indicators -> likely recharge
            # - If it has package indicators -> likely package activation (ignore)
            # - If it has both -> need to check which is stronger
            # - If it has neither -> probably ignore (fragment or other message)
            
            if has_recharge_indicators and not has_package_indicators:
                logger.debug(f"✅ MOBLIS: Identified as recharge message")
                self.stats['moblis_recharge_messages'] += 1
                return True
            elif has_package_indicators:
                logger.debug(f"📦 MOBLIS: Identified as package/activation message")
                self.stats['moblis_package_messages'] += 1
                return False
            elif has_recharge_indicators and has_package_indicators:
                # Both types present - check which is stronger by counting keywords
                recharge_count = sum(1 for indicator in recharge_indicators if indicator in content_lower)
                package_count = sum(1 for indicator in package_indicators if indicator in content_lower)
                
                if recharge_count > package_count:
                    logger.debug(f"✅ MOBLIS: Mixed message but recharge keywords stronger ({recharge_count} vs {package_count})")
                    self.stats['moblis_recharge_messages'] += 1
                    return True
                else:
                    logger.debug(f"📦 MOBLIS: Mixed message but package keywords stronger ({package_count} vs {recharge_count})")
                    self.stats['moblis_package_messages'] += 1
                    return False
            else:
                # No clear indicators - probably fragment or other message
                logger.debug(f"❓ MOBLIS: No clear indicators, treating as non-recharge")
                self.stats['moblis_other_messages'] += 1
                return False
                
        except Exception as e:
            logger.error(f"Error checking if message is recharge: {e}")
            self.stats['moblis_other_messages'] += 1
            return False
    
    
    def trigger_balance_check(self, sim_id: int, recharge_info: Dict) -> bool:
        """Trigger balance check after recharge detection - MOBLIS ONLY"""
        try:
            is_critical = recharge_info.get('is_critical', False)
            sender = recharge_info.get('sender', 'Unknown')
            
            # Only process Moblis recharges
            if not is_critical or sender != self.critical_recharge_sender:
                logger.info(f"🚫 Ignoring non-Moblis recharge from {sender}")
                return False
            
            logger.info(f"� MOBLIS BALANCE CHECK for SIM {sim_id} - ZERO TOLERANCE VALIDATION")
            
            # Get current balance from database (before recharge)
            old_balance = db.get_current_balance(sim_id)
            logger.info(f"📊 Old balance from DB: {old_balance}")
            
            # Get SIM info to find the port
            sim_info = self._get_sim_info(sim_id)
            if not sim_info:
                logger.error(f"❌ Could not find SIM info for SIM {sim_id}")
                self.stats['failed_checks'] += 1
                return False
            
            # Wait for telecom system to process the recharge
            logger.info("⏱️  MOBLIS: Waiting 10 seconds for telecom processing...")
            time.sleep(10)
            
            # Extract live balance from modem (enhanced SBC handling)
            balance_result = self._extract_live_balance_enhanced(sim_info)
            if not balance_result:
                logger.error(f"❌ Failed to extract live balance for SIM {sim_id}")
                self.stats['failed_checks'] += 1
                return False
            
            # Check if we got SBC response (balance will come via SMS)
            if balance_result.get('is_sbc_response'):
                logger.info(f"📱 SBC Response detected - balance will come via SMS")
                
                # Store this as a pending balance request
                self.pending_balance_requests[sim_id] = {
                    'timestamp': datetime.now(),
                    'recharge_info': recharge_info
                }
                self.stats['pending_balance_requests'] += 1
                self.stats['sbc_responses_detected'] += 1
                
                logger.info(f"⏳ Waiting for balance SMS for SIM {sim_id}")
                return True  # Return success, validation will happen when SMS arrives
            
            # We got direct balance from USSD
            new_balance = balance_result.get('balance')
            
            logger.info(f"📊 New balance from modem: {new_balance}")
            
            # Calculate balance change
            old_amount = self._parse_balance_amount(old_balance)
            new_amount = self._parse_balance_amount(new_balance)
            change_amount = new_amount - old_amount
            expected_amount = float(recharge_info.get('amount', '0').replace(',', '.'))
            
            logger.info(f"📈 Balance change: {old_amount} → {new_amount} (Δ{change_amount:+.2f})")
            logger.info(f"🎯 Expected recharge: {expected_amount}")
            
            # **CRITICAL VALIDATION - ZERO TOLERANCE**
            if is_critical:
                amount_difference = abs(change_amount - expected_amount)
                if amount_difference > 0.01:  # Allow only 0.01 DZD tolerance for floating point precision
                    logger.error(f"🚨 CRITICAL VALIDATION FAILED!")
                    logger.error(f"   Expected: {expected_amount} DZD")
                    logger.error(f"   Actual:   {change_amount} DZD")
                    logger.error(f"   Diff:     {amount_difference} DZD")
                    self.stats['validation_mismatches'] += 1
                    
                    # Record the validation failure
                    db.add_balance_history(
                        sim_id=sim_id,
                        old_balance=old_balance,
                        new_balance=new_balance,
                        change_amount=f"{change_amount:+.2f}",
                        recharge_amount=recharge_info.get('amount'),
                        change_type='recharge_validation_failed',
                        detected_from_sms=True,
                        sms_sender=sender,
                        sms_content=f"VALIDATION FAILED - Expected: {expected_amount}, Actual: {change_amount} | {recharge_info.get('content', '')[:400]}"
                    )
                    
                    return False
                else:
                    logger.info(f"✅ CRITICAL VALIDATION PASSED - Amount matches exactly!")
            
            # Update SIM balance in database - save as clean number (100.00)
            db.update_sim_info(sim_id, balance=new_balance)
            
            # Record balance history with enhanced tracking
            change_type = 'critical_recharge_validated' if is_critical else 'recharge'
            db.add_balance_history(
                sim_id=sim_id,
                old_balance=old_balance,
                new_balance=new_balance,
                change_amount=f"{change_amount:+.2f}",
                recharge_amount=recharge_info.get('amount'),
                change_type=change_type,
                detected_from_sms=True,
                sms_sender=sender,
                sms_content=recharge_info.get('content', '')[:500]
            )
            
            if is_critical:
                logger.info(f"✅ CRITICAL BALANCE CHECK COMPLETED SUCCESSFULLY for SIM {sim_id}")
            else:
                logger.info(f"✅ Balance check completed for SIM {sim_id}")
                
            self.stats['successful_checks'] += 1
            self.stats['last_check_time'] = datetime.now()
            
            return True
            
        except Exception as e:
            logger.error(f"Failed balance check for SIM {sim_id}: {e}")
            self.stats['failed_checks'] += 1
            return False
    
    def _get_sim_info(self, sim_id: int) -> Optional[Dict]:
        """Get SIM information including port"""
        try:
            with db.get_connection() as conn:
                cursor = conn.execute("""
                    SELECT s.id, s.modem_id, s.phone_number, m.imei 
                    FROM sims s 
                    JOIN modems m ON s.modem_id = m.id 
                    WHERE s.id = ? AND s.status = 'active' AND m.status = 'active'
                """, (sim_id,))
                row = cursor.fetchone()
                
                if row:
                    sim_data = dict(row)
                    imei = sim_data['imei']
                    
                    # Get port from modem detector
                    if imei in modem_detector.known_modems:
                        sim_data['port'] = modem_detector.known_modems[imei]['port']
                        return sim_data
                    else:
                        logger.warning(f"IMEI {imei} not found in known modems")
                
                return None
                
        except Exception as e:
            logger.error(f"Failed to get SIM info for {sim_id}: {e}")
            return None
    
    def _extract_live_balance_enhanced(self, sim_info: Dict) -> Optional[Dict]:
        """Extract live balance from modem using *222# with SBC detection"""
        try:
            port = sim_info['port']
            imei = sim_info['imei']
            
            logger.info(f"📞 Extracting live balance from IMEI {imei[-6:]} on port {port}")
            
            # Small delay to ensure recharge is processed by telecom system
            time.sleep(3)
            
            with serial.Serial(
                port=port,
                baudrate=self.baud_rate,
                timeout=self.connection_timeout,
                write_timeout=self.connection_timeout
            ) as ser:
                
                # Initialize modem
                if not self._initialize_modem(ser):
                    logger.warning(f"⚠️  Failed to initialize modem on port {port}")
                    return None
                
                # Send USSD command for balance
                raw_response = self._send_ussd_command(ser, self.balance_command)
                
                if raw_response:
                    logger.debug(f"Balance raw response: {raw_response}")
                    
                    # Decode the response
                    decoded_response = decode_ussd_response(raw_response)
                    logger.info(f"💰 Balance decoded: {decoded_response}")
                    
                    # Check if this is an SBC response
                    if self.detect_sbc_response(decoded_response):
                        return {
                            'is_sbc_response': True,
                            'decoded_response': decoded_response
                        }
                    
                    # Extract balance amount (normal response)
                    balance_amount = extract_balance_amount_only(decoded_response)
                    if balance_amount:
                        logger.info(f"💰 Balance amount: {balance_amount}")
                        return {
                            'is_sbc_response': False,
                            'balance': balance_amount
                        }
                    else:
                        logger.warning(f"⚠️  Could not extract balance from: {decoded_response}")
                        return None
                else:
                    logger.warning("No USSD response received for balance")
                    return None
                    
        except Exception as e:
            logger.error(f"Failed to extract live balance: {e}")
            return None
    
    def _initialize_modem(self, ser: serial.Serial) -> bool:
        """Initialize modem for USSD operations"""
        try:
            # Clear buffers
            ser.reset_input_buffer()
            ser.reset_output_buffer()
            
            # Basic AT command
            if not self._send_at_command(ser, "AT"):
                return False
            
            # Check SIM status
            response = self._send_at_command_with_response(ser, "AT+CPIN?")
            if "READY" not in response:
                logger.warning(f"SIM not ready: {response}")
                return False
                
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize modem: {e}")
            return False
    
    def _send_ussd_command(self, ser: serial.Serial, command: str) -> Optional[str]:
        """Send USSD command and wait for response"""
        try:
            logger.debug(f"Sending USSD command: {command}")
            
            # Clear buffers
            ser.reset_input_buffer()
            ser.reset_output_buffer()
            
            # Send USSD command
            ussd_at_command = f'AT+CUSD=1,"{command}",15'
            ser.write(f"{ussd_at_command}\r\n".encode())
            
            # Wait for initial OK
            response = ""
            start_time = time.time()
            
            while time.time() - start_time < 2:
                if ser.in_waiting > 0:
                    data = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
                    response += data
                    if "OK" in response or "ERROR" in response:
                        break
                time.sleep(0.1)
            
            if "ERROR" in response:
                logger.error(f"USSD command failed: {response}")
                return None
            
            # Wait for +CUSD response
            ussd_response = ""
            start_time = time.time()
            
            while time.time() - start_time < self.at_timeout:
                if ser.in_waiting > 0:
                    data = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
                    ussd_response += data
                    
                    if "+CUSD:" in ussd_response:
                        # Wait a bit more for complete response
                        time.sleep(0.5)
                        if ser.in_waiting > 0:
                            data = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
                            ussd_response += data
                        return ussd_response
                
                time.sleep(0.2)
            
            logger.warning(f"No +CUSD response received for {command}")
            return None
            
        except Exception as e:
            logger.error(f"Failed to send USSD command: {e}")
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
    
    def _parse_balance_amount(self, balance_str: str) -> float:
        """Parse balance string to float amount"""
        try:
            if not balance_str:
                return 0.0
            
            # Extract numbers from balance string
            amount_match = re.search(r'(\d+[.,]\d*)', balance_str)
            if amount_match:
                amount = amount_match.group(1).replace(',', '.')
                return float(amount)
            
            return 0.0
            
        except Exception as e:
            logger.warning(f"Failed to parse balance amount '{balance_str}': {e}")
            return 0.0
    
    def get_stats(self) -> Dict:
        """Get Moblis balance checker statistics including SBC handling"""
        stats = self.stats.copy()
        stats['moblis_sender_id'] = self.critical_recharge_sender
        stats['pending_requests_info'] = self.get_pending_requests_info()
        return stats
    
    def detect_sbc_response(self, decoded_response: str) -> bool:
        """Detect if USSD response is SBC (SMS Balance Check) - balance will come via SMS"""
        try:
            if not decoded_response:
                return False
                
            logger.debug(f"🔍 Checking for SBC response: {decoded_response}")
            
            # Check for SBC patterns
            for pattern in self.sbc_patterns:
                if re.search(pattern, decoded_response, re.IGNORECASE):
                    logger.info(f"📱 SBC RESPONSE DETECTED: {decoded_response}")
                    self.stats['sbc_responses_detected'] += 1
                    return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error detecting SBC response: {e}")
            return False
    
    def detect_balance_sms(self, message_content: str, sender: str) -> Optional[Dict]:
        """Detect if SMS contains real balance information"""
        try:
            logger.debug(f"🔍 Checking for balance SMS from {sender}: {message_content[:100]}...")
            
            # **FIRST CHECK FOR BALANCE** - This takes priority over package detection
            for pattern in self.balance_sms_patterns:
                match = re.search(pattern, message_content, re.IGNORECASE)
                if match:
                    balance_amount = match.group(1).replace(',', '.')
                    logger.info(f"💰 BALANCE SMS DETECTED: {balance_amount} from {sender}")
                    self.stats['balance_sms_processed'] += 1
                    return {
                        'is_balance_sms': True,
                        'balance': balance_amount,
                        'sender': sender,
                        'content': message_content
                    }
            
            # **THEN CHECK IF IT'S ONLY A PACKAGE ACTIVATION** (no balance info)
            if self._is_package_activation(message_content):
                logger.info(f"📦 Package activation detected (no balance), ignoring: {message_content[:100]}...")
                self.stats['package_activations_ignored'] += 1
                return {
                    'is_balance_sms': False,
                    'is_package_activation': True,
                    'sender': sender,
                    'content': message_content
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Error detecting balance SMS: {e}")
            return None
    
    def _is_package_activation(self, content: str) -> bool:
        """Check if message is about package activation (should be ignored)"""
        try:
            for pattern in self.package_activation_patterns:
                if re.search(pattern, content, re.IGNORECASE):
                    logger.debug(f"📦 Package activation pattern matched: {pattern}")
                    return True
            return False
        except Exception as e:
            logger.error(f"Error checking package activation: {e}")
            return False
    
    def process_balance_sms(self, sim_id: int, balance_sms_info: Dict) -> bool:
        """Process balance SMS and validate against pending recharge if any"""
        try:
            sender = balance_sms_info.get('sender', 'Unknown')
            new_balance = balance_sms_info.get('balance')
            
            logger.info(f"📱 Processing balance SMS for SIM {sim_id}: {new_balance}")
            
            # Check if there's a pending balance request for this SIM
            if sim_id in self.pending_balance_requests:
                pending = self.pending_balance_requests[sim_id]
                recharge_info = pending['recharge_info']
                
                logger.info(f"🔗 Found pending balance request for SIM {sim_id}")
                
                # Remove from pending
                del self.pending_balance_requests[sim_id]
                self.stats['pending_balance_requests'] -= 1
                
                # Validate the recharge using SMS balance
                return self._validate_recharge_with_sms_balance(sim_id, recharge_info, new_balance)
            else:
                # No pending request, just update the balance - save as clean number (100.00)
                logger.info(f"📊 No pending request, updating balance for SIM {sim_id}")
                
                # Get old balance for comparison
                old_balance = db.get_current_balance(sim_id)
                
                # Update SIM balance in database
                db.update_sim_info(sim_id, balance=new_balance)
                
                # Record balance history
                db.add_balance_history(
                    sim_id=sim_id,
                    old_balance=old_balance,
                    new_balance=new_balance, 
                    change_amount="0.00",  # No specific change tracked
                    change_type='balance_sms_update',
                    detected_from_sms=True,
                    sms_sender=sender,
                    sms_content=balance_sms_info.get('content', '')[:500]
                )
                
                return True
                
        except Exception as e:
            logger.error(f"Error processing balance SMS for SIM {sim_id}: {e}")
            return False
    
    def _validate_recharge_with_sms_balance(self, sim_id: int, recharge_info: Dict, new_balance: str) -> bool:
        """Validate recharge using balance received via SMS instead of USSD"""
        try:
            is_critical = recharge_info.get('is_critical', False)
            sender = recharge_info.get('sender', 'Unknown')
            
            logger.info(f"📱 Validating recharge with SMS balance for SIM {sim_id}")
            
            # Get old balance from database
            old_balance = db.get_current_balance(sim_id)
            logger.info(f"📊 Old balance: {old_balance}")
            logger.info(f"📊 New balance from SMS: {new_balance}")
            
            # Calculate balance change
            old_amount = self._parse_balance_amount(old_balance)
            new_amount = self._parse_balance_amount(new_balance)
            change_amount = new_amount - old_amount
            expected_amount = float(recharge_info.get('amount', '0').replace(',', '.'))
            
            logger.info(f"📈 Balance change: {old_amount} → {new_amount} (Δ{change_amount:+.2f})")
            logger.info(f"🎯 Expected recharge: {expected_amount}")
            
            # **CRITICAL VALIDATION - ZERO TOLERANCE**
            if is_critical:
                amount_difference = abs(change_amount - expected_amount)
                if amount_difference > 0.01:  # Allow only 0.01 DZD tolerance
                    logger.error(f"🚨 CRITICAL VALIDATION FAILED (SMS Balance)!");
                    logger.error(f"   Expected: {expected_amount} DZD")
                    logger.error(f"   Actual:   {change_amount} DZD")
                    logger.error(f"   Diff:     {amount_difference} DZD")
                    self.stats['validation_mismatches'] += 1
                    
                    # Record the validation failure - save as clean number (100.00)
                    db.add_balance_history(
                        sim_id=sim_id,
                        old_balance=old_balance,
                        new_balance=new_balance,
                        change_amount=f"{change_amount:+.2f}",
                        recharge_amount=recharge_info.get('amount'),
                        change_type='recharge_validation_failed_sms',
                        detected_from_sms=True,
                        sms_sender=sender,
                        sms_content=f"SMS VALIDATION FAILED - Expected: {expected_amount}, Actual: {change_amount} | {recharge_info.get('content', '')[:400]}"
                    )
                    
                    return False
                else:
                    logger.info(f"✅ CRITICAL VALIDATION PASSED (SMS Balance) - Amount matches exactly!")
            
            # Update SIM balance in database - save as clean number (100.00)
            db.update_sim_info(sim_id, balance=new_balance)
            
            # Record balance history with enhanced tracking
            change_type = 'critical_recharge_validated_sms' if is_critical else 'recharge_sms'
            db.add_balance_history(
                sim_id=sim_id,
                old_balance=old_balance,
                new_balance=new_balance,
                change_amount=f"{change_amount:+.2f}",
                recharge_amount=recharge_info.get('amount'),
                change_type=change_type,
                detected_from_sms=True,
                sms_sender=sender,
                sms_content=f"SMS Balance Validation | {recharge_info.get('content', '')[:400]}"
            )
            
            if is_critical:
                logger.info(f"✅ CRITICAL BALANCE CHECK COMPLETED (SMS) for SIM {sim_id}")
            else:
                logger.info(f"✅ Balance check completed (SMS) for SIM {sim_id}")
                
            self.stats['successful_checks'] += 1
            self.stats['last_check_time'] = datetime.now()
            
            return True
            
        except Exception as e:
            logger.error(f"Error validating recharge with SMS balance: {e}")
            self.stats['failed_checks'] += 1
            return False
    
    def cleanup_old_pending_requests(self, max_age_minutes: int = 30):
        """Clean up old pending balance requests that never received SMS"""
        try:
            current_time = datetime.now()
            expired_sim_ids = []
            
            for sim_id, pending in self.pending_balance_requests.items():
                age_minutes = (current_time - pending['timestamp']).total_seconds() / 60
                if age_minutes > max_age_minutes:
                    expired_sim_ids.append(sim_id)
            
            for sim_id in expired_sim_ids:
                logger.warning(f"⏰ Cleaning up expired pending request for SIM {sim_id}")
                del self.pending_balance_requests[sim_id]
                self.stats['pending_balance_requests'] -= 1
                
            if expired_sim_ids:
                logger.info(f"🧹 Cleaned up {len(expired_sim_ids)} expired pending requests")
                
        except Exception as e:
            logger.error(f"Error cleaning up pending requests: {e}")
    
    def get_pending_requests_info(self) -> Dict:
        """Get information about pending balance requests"""
        try:
            return {
                'count': len(self.pending_balance_requests),
                'sim_ids': list(self.pending_balance_requests.keys()),
                'requests': {
                    sim_id: {
                        'timestamp': pending['timestamp'].isoformat(),
                        'sender': pending['recharge_info'].get('sender', 'Unknown'),
                        'amount': pending['recharge_info'].get('amount', 'Unknown'),
                        'is_critical': pending['recharge_info'].get('is_critical', False)
                    }
                    for sim_id, pending in self.pending_balance_requests.items()
                }
            }
        except Exception as e:
            logger.error(f"Error getting pending requests info: {e}")
            return {'count': 0, 'sim_ids': [], 'requests': {}}

# Global balance checker instance
balance_checker = BalanceChecker()
