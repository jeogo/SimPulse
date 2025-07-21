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
        self.at_timeout = 15  # Increased from 10 to 15 seconds for better USSD response
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
        
        # Enhanced balance SMS patterns - COMPREHENSIVE DETECTION with European format support
        self.balance_sms_patterns = [
            # European format with thousands and decimal: 48.410,82DA
            r'Solde\s+(\d{1,3}(?:\.\d{3})*,\d{2})\s*(?:DZD|DA)',  # "Solde 48.410,82DA"
            r'Balance\s+(\d{1,3}(?:\.\d{3})*,\d{2})\s*(?:DZD|DA)',  # "Balance 48.410,82DA"
            r'votre\s+solde\s+est\s+(\d{1,3}(?:\.\d{3})*,\d{2})\s*(?:DZD|DA)',  # "Votre solde est 48.410,82DA"
            r'solde\s+actuel\s*:?\s*(\d{1,3}(?:\.\d{3})*,\d{2})\s*(?:DZD|DA)',  # "Solde actuel: 48.410,82DA"
            r'credit\s+(\d{1,3}(?:\.\d{3})*,\d{2})\s*(?:DZD|DA)',  # "Credit 48.410,82DA"
            r'montant\s+disponible\s*:?\s*(\d{1,3}(?:\.\d{3})*,\d{2})\s*(?:DZD|DA)',  # "Montant disponible: 48.410,82DA"
            r'(\d{1,3}(?:\.\d{3})*,\d{2})\s*(?:DZD|DA)\s+disponible',  # "48.410,82DA disponible"
            r'Sama\s+.*?(\d{1,3}(?:\.\d{3})*,\d{2})\s*(?:DZD|DA)',  # "Sama Mix: Solde 48.410,82DA"
            
            # European format without thousands: 410,82DA
            r'Solde\s+(\d+,\d{2})\s*(?:DZD|DA)',              # "Solde 410,82DA"
            r'Balance\s+(\d+,\d{2})\s*(?:DZD|DA)',            # "Balance 410,82DA" 
            r'votre\s+solde\s+est\s+(\d+,\d{2})\s*(?:DZD|DA)',  # "Votre solde est 410,82DA"
            r'solde\s+actuel\s*:?\s*(\d+,\d{2})\s*(?:DZD|DA)', # "Solde actuel: 410,82DA"
            r'credit\s+(\d+,\d{2})\s*(?:DZD|DA)',             # "Credit 410,82DA"
            r'montant\s+disponible\s*:?\s*(\d+,\d{2})\s*(?:DZD|DA)', # "Montant disponible: 410,82DA"
            r'(\d+,\d{2})\s*(?:DZD|DA)\s+disponible',         # "410,82DA disponible"
            
            # US format with thousands: 48,410.82DA
            r'Solde\s+(\d{1,3}(?:,\d{3})*\.\d{2})\s*(?:DZD|DA)',  # "Solde 48,410.82DA"
            r'Balance\s+(\d{1,3}(?:,\d{3})*\.\d{2})\s*(?:DZD|DA)',  # "Balance 48,410.82DA"
            r'votre\s+solde\s+est\s+(\d{1,3}(?:,\d{3})*\.\d{2})\s*(?:DZD|DA)',  # "Votre solde est 48,410.82DA"
            
            # US format without thousands: 410.82DA
            r'Solde\s+(\d+\.\d{2})\s*(?:DZD|DA)',             # "Solde 410.82DA"
            r'Balance\s+(\d+\.\d{2})\s*(?:DZD|DA)',           # "Balance 410.82DA"
            r'votre\s+solde\s+est\s+(\d+\.\d{2})\s*(?:DZD|DA)', # "Votre solde est 410.82DA"
            
            # Integer amounts: 100DA
            r'Solde\s+(\d+)\s*(?:DZD|DA)',                    # "Solde 100DA"
            r'Balance\s+(\d+)\s*(?:DZD|DA)',                  # "Balance 100DA"
            
            # Arabic patterns
            r'رصيدك\s+(\d+[.,]\d+)\s*(?:دج|دينار)',            # Arabic balance
            r'الرصيد\s+(\d+[.,]\d+)\s*(?:دج|دينار)',             # Arabic balance
            r'رصيد\s+(\d+[.,]\d+)\s*(?:دج|دينار)',             # Arabic with typo
            
            # Simple fallback patterns (less specific)
            r'(\d{1,3}(?:\.\d{3})*,\d{2})\s*DA\b',           # European format: 48.410,82DA
            r'(\d{1,3}(?:,\d{3})*\.\d{2})\s*DA\b',           # US format: 48,410.82DA
            r'(\d+,\d{2})\s*DA\b',                            # Simple European: 410,82DA
            r'(\d+\.\d{2})\s*DA\b',                           # Simple US: 410.82DA
            r'(\d+)\s*DA\b',                                  # Integer: 100DA
            r'(\d{1,3}(?:\.\d{3})*,\d{2})\s*DZD\b',          # European DZD
            r'(\d{1,3}(?:,\d{3})*\.\d{2})\s*DZD\b',          # US DZD
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
            'last_check_time': None,
            'balance_limit_notifications': 0,  # إحصائية تنبيهات حد الرصيد
            # Enhanced method tracking
            'ussd_direct_success': 0,
            'ussd_sbc_responses': 0,
            'sms_fallback_success': 0,
            'forced_sms_success': 0,
            'ussd_failed': 0,
            'all_methods_failed': 0,
            'pattern_usage': {},  # Track which SMS patterns are used
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
        """Trigger balance check after recharge detection - ENHANCED WITH FALLBACKS"""
        try:
            is_critical = recharge_info.get('is_critical', False)
            sender = recharge_info.get('sender', 'Unknown')
            
            # Only process Moblis recharges
            if not is_critical or sender != self.critical_recharge_sender:
                logger.info(f"🚫 Ignoring non-Moblis recharge from {sender}")
                return False
            
            logger.info(f"💎 ENHANCED MOBLIS BALANCE CHECK for SIM {sim_id} - WITH FALLBACKS")
            
            # Get current balance from database (before recharge)
            old_balance = db.get_current_balance(sim_id)
            logger.info(f"📊 Old balance from DB: {old_balance}")
            
            # Get SIM info to find the port
            sim_info = self._get_sim_info(sim_id)
            if not sim_info:
                logger.error(f"❌ Could not find SIM info for SIM {sim_id}")
                self.stats['failed_checks'] += 1
                return False
            
            # Add sim_id to sim_info for enhanced methods
            sim_info['id'] = sim_id
            
            # Wait for telecom system to process the recharge
            logger.info("⏱️  MOBLIS: Waiting 10 seconds for telecom processing...")
            time.sleep(10)
            
            # Extract live balance using enhanced method with fallbacks
            balance_result = self._extract_live_balance_enhanced(sim_info)
            if not balance_result or not balance_result.get('success'):
                error_msg = balance_result.get('error', 'unknown') if balance_result else 'no_result'
                logger.error(f"❌ All balance extraction methods failed for SIM {sim_id}: {error_msg}")
                self.stats['failed_checks'] += 1
                
                # Record the failure in balance history for tracking
                db.add_balance_history(
                    sim_id=sim_id,
                    old_balance=old_balance,
                    new_balance=old_balance,  # No change since we couldn't get new balance
                    change_amount="0.00",
                    recharge_amount=recharge_info.get('amount'),
                    change_type='balance_check_failed',
                    detected_from_sms=True,
                    sms_sender=sender,
                    sms_content=f"BALANCE CHECK FAILED: {error_msg} | {recharge_info.get('content', '')[:400]}"
                )
                return False
            
            # Check the method used and handle accordingly
            method_used = balance_result.get('method', 'unknown')
            logger.info(f"📊 Balance extracted using method: {method_used}")
            
            # Check if we got SBC response (balance will come via SMS)
            if balance_result.get('is_sbc_response'):
                logger.info(f"📱 SBC Response detected - balance will come via SMS")
                
                # Store this as a pending balance request
                self.pending_balance_requests[sim_id] = {
                    'timestamp': datetime.now(),
                    'recharge_info': recharge_info,
                    'method': method_used
                }
                self.stats['pending_balance_requests'] += 1
                self.stats['sbc_responses_detected'] += 1
                
                logger.info(f"⏳ Waiting for balance SMS for SIM {sim_id}")
                return True  # Return success, validation will happen when SMS arrives
            
            # We got direct balance from USSD or SMS
            new_balance = balance_result.get('balance')
            balance_sender = balance_result.get('sender', 'USSD')
            
            logger.info(f"📊 New balance from {method_used}: {new_balance}")
            
            # Validate and update the balance
            validation_success = self._validate_and_update_balance(
                sim_id=sim_id,
                old_balance=old_balance,
                new_balance=new_balance,
                recharge_info=recharge_info,
                method_used=method_used,
                balance_sender=balance_sender
            )
            
            if validation_success:
                logger.info(f"✅ ENHANCED BALANCE CHECK COMPLETED SUCCESSFULLY for SIM {sim_id}")
                self.stats['successful_checks'] += 1
                self.stats['last_check_time'] = datetime.now()
                
                # فحص حد الرصيد وإرسال تنبيه إذا لزم الأمر
                if self._check_balance_limit(sim_id, new_balance):
                    logger.info(f"🚨 Balance limit reached for SIM {sim_id}, sending notification...")
                    self._notify_balance_limit_reached(sim_id, new_balance)
                
                return True
            else:
                logger.error(f"❌ Balance validation failed for SIM {sim_id}")
                self.stats['failed_checks'] += 1
                return False
            
        except Exception as e:
            logger.error(f"Failed enhanced balance check for SIM {sim_id}: {e}")
            self.stats['failed_checks'] += 1
            return False
    
    def _validate_and_update_balance(self, sim_id: int, old_balance: str, new_balance: str, 
                                   recharge_info: Dict, method_used: str, balance_sender: str) -> bool:
        """Validate balance change and update database"""
        try:
            is_critical = recharge_info.get('is_critical', False)
            sender = recharge_info.get('sender', 'Unknown')
            
            # Calculate balance change
            old_amount = self._parse_balance_amount(old_balance)
            new_amount = self._parse_balance_amount(new_balance)
            change_amount = new_amount - old_amount
            expected_amount = float(recharge_info.get('amount', '0').replace(',', '.'))
            
            logger.info(f"📈 Balance change: {old_amount} → {new_amount} (Δ{change_amount:+.2f})")
            logger.info(f"🎯 Expected recharge: {expected_amount}")
            logger.info(f"📊 Method: {method_used}, Source: {balance_sender}")
            
            # **CRITICAL VALIDATION - ZERO TOLERANCE**
            if is_critical:
                amount_difference = abs(change_amount - expected_amount)
                if amount_difference > 0.01:  # Allow only 0.01 DZD tolerance for floating point precision
                    logger.error(f"🚨 CRITICAL VALIDATION FAILED!")
                    logger.error(f"   Expected: {expected_amount} DZD")
                    logger.error(f"   Actual:   {change_amount} DZD")
                    logger.error(f"   Diff:     {amount_difference} DZD")
                    logger.error(f"   Method:   {method_used}")
                    self.stats['validation_mismatches'] += 1
                    
                    # Record the validation failure
                    db.add_balance_history(
                        sim_id=sim_id,
                        old_balance=old_balance,
                        new_balance=new_balance,
                        change_amount=f"{change_amount:+.2f}",
                        recharge_amount=recharge_info.get('amount'),
                        change_type=f'recharge_validation_failed_{method_used}',
                        detected_from_sms=True,
                        sms_sender=sender,
                        sms_content=f"VALIDATION FAILED [{method_used}] - Expected: {expected_amount}, Actual: {change_amount} | {recharge_info.get('content', '')[:400]}"
                    )
                    
                    return False
                else:
                    logger.info(f"✅ CRITICAL VALIDATION PASSED - Amount matches exactly! (Method: {method_used})")
            
            # Update SIM balance in database - save as clean number (100.00)
            db.update_sim_info(sim_id, balance=new_balance)
            
            # Record balance history with enhanced tracking
            change_type = f'critical_recharge_validated_{method_used}' if is_critical else f'recharge_{method_used}'
            db.add_balance_history(
                sim_id=sim_id,
                old_balance=old_balance,
                new_balance=new_balance,
                change_amount=f"{change_amount:+.2f}",
                recharge_amount=recharge_info.get('amount'),
                change_type=change_type,
                detected_from_sms=True,
                sms_sender=sender,
                sms_content=f"[{method_used}] Balance from {balance_sender} | {recharge_info.get('content', '')[:400]}"
            )
            
            logger.info(f"✅ Balance validation and update completed using {method_used}")
            return True
            
        except Exception as e:
            logger.error(f"Error in balance validation and update: {e}")
            return False
    
    def initial_balance_check_for_all_sims(self) -> Dict:
        """Perform initial balance check for all active SIMs when system starts"""
        try:
            logger.info("🚀 STARTUP: Initial balance check for all active SIMs")
            
            # Get all active SIMs
            with db.get_connection() as conn:
                cursor = conn.execute("""
                    SELECT s.id, s.modem_id, s.phone_number, s.balance, m.imei 
                    FROM sims s 
                    JOIN modems m ON s.modem_id = m.id 
                    WHERE s.status = 'active' AND m.status = 'active'
                    ORDER BY s.created_at
                """)
                active_sims = [dict(row) for row in cursor.fetchall()]
            
            if not active_sims:
                logger.info("📊 No active SIMs found for initial balance check")
                return {'total_sims': 0, 'checked': 0, 'failed': 0, 'updated': 0}
            
            logger.info(f"📊 Found {len(active_sims)} active SIMs for initial balance check")
            
            results = {
                'total_sims': len(active_sims),
                'checked': 0,
                'failed': 0,
                'updated': 0,
                'details': []
            }
            
            from .modem_detector import modem_detector
            
            for sim in active_sims:
                sim_id = sim['id']
                imei = sim['imei']
                current_balance = sim['balance']
                
                try:
                    logger.info(f"🔍 Initial balance check for SIM {sim_id} (IMEI: {imei[-6:]})")
                    
                    # Check if we have port info for this modem
                    if imei in modem_detector.known_modems:
                        port = modem_detector.known_modems[imei]['port']
                        
                        sim_info = {
                            'id': sim_id,
                            'imei': imei,
                            'port': port
                        }
                        
                        # Extract current balance
                        balance_result = self._extract_live_balance_enhanced(sim_info)
                        
                        if balance_result and balance_result.get('success'):
                            new_balance = balance_result.get('balance')
                            method = balance_result.get('method', 'unknown')
                            
                            if new_balance and new_balance != current_balance:
                                # Update database with new balance
                                db.update_sim_info(sim_id, balance=new_balance)
                                
                                # Record in balance history
                                old_amount = self._parse_balance_amount(current_balance)
                                new_amount = self._parse_balance_amount(new_balance)
                                change = new_amount - old_amount
                                
                                db.add_balance_history(
                                    sim_id=sim_id,
                                    old_balance=current_balance or "0.00",
                                    new_balance=new_balance,
                                    change_amount=f"{change:+.2f}",
                                    change_type=f'initial_startup_check_{method}',
                                    detected_from_sms=False,
                                    sms_sender='SYSTEM_STARTUP',
                                    sms_content=f"Initial balance check using {method}"
                                )
                                
                                logger.info(f"✅ SIM {sim_id}: Updated balance {current_balance} → {new_balance}")
                                results['updated'] += 1
                            else:
                                logger.info(f"📊 SIM {sim_id}: Balance unchanged ({new_balance})")
                            
                            results['checked'] += 1
                            results['details'].append({
                                'sim_id': sim_id,
                                'imei': imei[-6:],
                                'status': 'success',
                                'method': method,
                                'balance': new_balance
                            })
                        else:
                            logger.warning(f"⚠️  SIM {sim_id}: Balance check failed")
                            results['failed'] += 1
                            results['details'].append({
                                'sim_id': sim_id,
                                'imei': imei[-6:],
                                'status': 'failed',
                                'error': balance_result.get('error', 'unknown') if balance_result else 'no_response'
                            })
                    else:
                        logger.warning(f"⚠️  SIM {sim_id}: No port information available")
                        results['failed'] += 1
                        results['details'].append({
                            'sim_id': sim_id,
                            'imei': imei[-6:],
                            'status': 'failed',
                            'error': 'no_port_info'
                        })
                    
                    # Wait between SIMs to avoid conflicts
                    time.sleep(3)
                    
                except Exception as e:
                    logger.error(f"❌ Initial balance check failed for SIM {sim_id}: {e}")
                    results['failed'] += 1
                    results['details'].append({
                        'sim_id': sim_id,
                        'imei': imei[-6:] if imei else 'unknown',
                        'status': 'failed',
                        'error': str(e)
                    })
            
            logger.info(f"🎯 Initial balance check completed: {results['checked']}/{results['total_sims']} checked, {results['updated']} updated, {results['failed']} failed")
            return results
            
        except Exception as e:
            logger.error(f"❌ Initial balance check for all SIMs failed: {e}")
            return {'total_sims': 0, 'checked': 0, 'failed': 0, 'updated': 0, 'error': str(e)}

    def _get_emergency_balance_from_db(self, sim_id: int) -> Optional[str]:
        """Get emergency balance from database as last resort"""
        try:
            logger.info(f"🚨 Emergency: Getting last known balance from database for SIM {sim_id}")
            
            # Get the most recent balance from database
            with db.get_connection() as conn:
                cursor = conn.execute("""
                    SELECT balance FROM sims WHERE id = ?
                """, (sim_id,))
                row = cursor.fetchone()
                
                if row and row['balance']:
                    db_balance = row['balance']
                    logger.info(f"📊 Found database balance: {db_balance}")
                    return db_balance
                
                # Try to get from balance history
                cursor = conn.execute("""
                    SELECT new_balance FROM balance_history 
                    WHERE sim_id = ? AND new_balance IS NOT NULL
                    ORDER BY created_at DESC LIMIT 1
                """, (sim_id,))
                row = cursor.fetchone()
                
                if row and row['new_balance']:
                    history_balance = row['new_balance']
                    logger.info(f"📈 Found balance from history: {history_balance}")
                    return history_balance
                
                logger.warning(f"⚠️  No emergency balance found in database for SIM {sim_id}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Emergency balance check failed: {e}")
            return None

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
        """Extract live balance from modem using *222# with comprehensive SMS fallback - ENHANCED WITH ROBUST RETRY"""
        try:
            port = sim_info['port']
            imei = sim_info['imei']
            sim_id = sim_info['id']
            
            logger.info(f"📞 ENHANCED: Extracting live balance from IMEI {imei[-6:]} on port {port}")
            
            # Small delay to ensure recharge is processed by telecom system
            time.sleep(3)
            
            # **ATTEMPT 1: Try USSD *222# (Primary Method) with Retry**
            logger.info(f"🔄 ATTEMPT 1: USSD *222# extraction with retry logic")
            for attempt in range(3):  # Try up to 3 times
                logger.info(f"🔄 USSD attempt {attempt + 1}/3")
                ussd_result = self._try_ussd_balance_extraction(port, sim_id)
                
                if ussd_result and ussd_result.get('success'):
                    logger.info(f"✅ USSD balance extraction successful on attempt {attempt + 1}")
                    # Update statistics based on method
                    if ussd_result.get('is_sbc_response'):
                        self.stats['ussd_sbc_responses'] += 1
                        logger.info(f"📱 SBC Response - balance will arrive via SMS")
                        return ussd_result
                    else:
                        self.stats['ussd_direct_success'] += 1
                        logger.info(f"💰 Direct USSD balance: {ussd_result.get('balance')}")
                        return ussd_result
                else:
                    logger.warning(f"⚠️  USSD attempt {attempt + 1} failed: {ussd_result.get('error', 'Unknown error') if ussd_result else 'No response'}")
                    if attempt < 2:  # Don't wait after last attempt
                        time.sleep(2)  # Wait 2 seconds between attempts
            
            self.stats['ussd_failed'] += 1
            logger.error(f"❌ All USSD attempts failed for SIM {sim_id}")
            
            # **ATTEMPT 2: Check for recent SMS balance (Fallback Method)**
            logger.warning(f"🔄 ATTEMPT 2: SMS balance fallback for SIM {sim_id}")
            sms_result = self._try_sms_balance_fallback(sim_id)
            if sms_result and sms_result.get('success'):
                logger.info(f"✅ SMS balance fallback successful: {sms_result.get('balance')}")
                self.stats['sms_fallback_success'] += 1
                return sms_result
            
            # **ATTEMPT 3: Force SMS balance check by triggering *222# and waiting for SMS**
            logger.warning(f"🔄 ATTEMPT 3: Forcing SMS balance check for SIM {sim_id}")
            forced_result = self._force_sms_balance_check_with_ussd(port, sim_id)
            if forced_result and forced_result.get('success'):
                logger.info(f"✅ Forced SMS balance check successful: {forced_result.get('balance')}")
                self.stats['forced_sms_success'] += 1
                return forced_result
            
            # **ATTEMPT 4: Emergency Database Balance Check**
            logger.warning(f"🔄 ATTEMPT 4: Emergency database balance check for SIM {sim_id}")
            db_balance = self._get_emergency_balance_from_db(sim_id)
            if db_balance:
                logger.info(f"⚠️  Using emergency database balance: {db_balance}")
                return {
                    'success': True,
                    'is_sbc_response': False,
                    'balance': db_balance,
                    'method': 'emergency_db',
                    'sender': 'DATABASE'
                }
            
            # **ALL METHODS FAILED**
            logger.error(f"❌ ALL 4 ATTEMPTS FAILED for SIM {sim_id}")
            self.stats['all_methods_failed'] += 1
            return {
                'success': False,
                'error': 'all_methods_failed',
                'method': 'none',
                'attempts_made': 4
            }
                    
        except Exception as e:
            logger.error(f"Failed to extract live balance: {e}")
            self.stats['all_methods_failed'] += 1
            return {
                'success': False,
                'error': str(e),
                'method': 'exception'
            }
    
    def _try_ussd_balance_extraction(self, port: str, sim_id: int) -> Optional[Dict]:
        """Try to extract balance using USSD *222# command - ENHANCED WITH ROBUST ERROR HANDLING"""
        try:
            logger.info(f"🔄 ENHANCED: USSD balance extraction on port {port}")
            
            with serial.Serial(
                port=port,
                baudrate=self.baud_rate,
                timeout=self.connection_timeout,
                write_timeout=self.connection_timeout
            ) as ser:
                
                # Initialize modem with retry
                init_attempts = 0
                max_init_attempts = 3
                
                while init_attempts < max_init_attempts:
                    if self._initialize_modem(ser):
                        logger.info(f"✅ Modem initialized successfully on attempt {init_attempts + 1}")
                        break
                    init_attempts += 1
                    if init_attempts < max_init_attempts:
                        logger.warning(f"⚠️  Modem init attempt {init_attempts} failed, retrying...")
                        time.sleep(2)
                
                if init_attempts >= max_init_attempts:
                    logger.error(f"❌ Failed to initialize modem after {max_init_attempts} attempts")
                    return {'success': False, 'error': 'modem_init_failed_all_attempts'}
                
                # Send USSD command for balance with enhanced handling
                logger.info(f"📞 Sending enhanced *222# command...")
                raw_response = self._send_ussd_command_enhanced(ser, self.balance_command)
                
                if raw_response:
                    logger.debug(f"USSD raw response: {raw_response}")
                    
                    # Decode the response
                    decoded_response = decode_ussd_response(raw_response)
                    logger.info(f"💰 USSD decoded: {decoded_response}")
                    
                    # Check if this is an SBC response (SMS will be sent)
                    if self.detect_sbc_response(decoded_response):
                        logger.info(f"📱 SBC Response detected - balance will come via SMS")
                        return {
                            'success': True,
                            'is_sbc_response': True,
                            'decoded_response': decoded_response,
                            'method': 'ussd_sbc'
                        }
                    
                    # Extract balance amount (normal response)
                    balance_amount = extract_balance_amount_only(decoded_response)
                    if balance_amount:
                        logger.info(f"💰 USSD balance amount: {balance_amount}")
                        return {
                            'success': True,
                            'is_sbc_response': False,
                            'balance': balance_amount,
                            'method': 'ussd_direct'
                        }
                    else:
                        logger.warning(f"⚠️  Could not extract balance from USSD: {decoded_response}")
                        
                        # Try alternative extraction methods for the response
                        alt_balance = self._try_alternative_balance_extraction(decoded_response)
                        if alt_balance:
                            logger.info(f"💰 Alternative extraction successful: {alt_balance}")
                            return {
                                'success': True,
                                'is_sbc_response': False,
                                'balance': alt_balance,
                                'method': 'ussd_alternative'
                            }
                        
                        return {'success': False, 'error': 'ussd_parse_failed', 'response': decoded_response}
                else:
                    logger.warning("No USSD response received")
                    return {'success': False, 'error': 'no_ussd_response'}
                    
        except Exception as e:
            logger.error(f"USSD balance extraction failed: {e}")
            return {'success': False, 'error': str(e)}
    
    def _try_sms_balance_fallback(self, sim_id: int) -> Optional[Dict]:
        """Try to get balance from recent SMS messages"""
        try:
            logger.info(f"📱 Attempting SMS balance fallback for SIM {sim_id}")
            
            # Look for balance SMS in the last 10 minutes
            from datetime import datetime, timedelta
            recent_time = datetime.now() - timedelta(minutes=10)
            
            with db.get_connection() as conn:
                cursor = conn.execute("""
                    SELECT message, sender, received_at FROM sms 
                    WHERE sim_id = ? AND received_at >= ? 
                    ORDER BY received_at DESC LIMIT 10
                """, (sim_id, recent_time))
                recent_sms = cursor.fetchall()
            
            logger.info(f"📱 Found {len(recent_sms)} recent SMS messages to check")
            
            # Check each SMS for balance information
            for sms_row in recent_sms:
                sms_content = sms_row[0]
                sender = sms_row[1]
                received_at = sms_row[2]
                
                logger.debug(f"🔍 Checking SMS from {sender}: {sms_content[:50]}...")
                
                # Check if this SMS contains balance info
                balance_sms_result = self.detect_balance_sms(sms_content, sender)
                if balance_sms_result and balance_sms_result.get('is_balance_sms'):
                    balance = balance_sms_result.get('balance')
                    logger.info(f"💰 Found SMS balance: {balance} from {sender} at {received_at}")
                    
                    return {
                        'success': True,
                        'is_sbc_response': False,
                        'balance': balance,
                        'method': 'sms_fallback',
                        'sender': sender
                    }
            
            logger.warning(f"❌ No balance SMS found in recent messages for SIM {sim_id}")
            return {'success': False, 'error': 'no_recent_balance_sms'}
                
        except Exception as e:
            logger.error(f"SMS balance fallback failed: {e}")
            return {'success': False, 'error': str(e)}
    
    def _force_sms_balance_check_with_ussd(self, port: str, sim_id: int) -> Optional[Dict]:
        """Force balance check by sending *222# and waiting for SMS response"""
        try:
            logger.info(f"🔥 Forcing SMS balance check for SIM {sim_id} on port {port}")
            
            with serial.Serial(
                port=port,
                baudrate=self.baud_rate,
                timeout=self.connection_timeout,
                write_timeout=self.connection_timeout
            ) as ser:
                
                # Initialize modem
                if not self._initialize_modem(ser):
                    logger.warning(f"⚠️  Failed to initialize modem for forced check")
                    return {'success': False, 'error': 'modem_init_failed'}
                
                # Send USSD command to trigger SMS
                logger.info(f"📞 Sending *222# to trigger SMS balance...")
                raw_response = self._send_ussd_command(ser, self.balance_command)
                
                if raw_response:
                    decoded_response = decode_ussd_response(raw_response)
                    logger.info(f"📞 USSD response: {decoded_response}")
                
                # Wait for SMS response (extended timeout)
                logger.info(f"⏳ Waiting up to 60 seconds for balance SMS...")
                max_wait_time = 60  # seconds
                check_interval = 3  # seconds
                start_time = time.time()
                
                while time.time() - start_time < max_wait_time:
                    time.sleep(check_interval)
                    
                    # Check for new SMS messages
                    with db.get_connection() as conn:
                        cursor = conn.execute("""
                            SELECT message, sender, received_at FROM sms 
                            WHERE sim_id = ? AND received_at >= datetime('now', '-5 minutes')
                            ORDER BY received_at DESC LIMIT 5
                        """, (sim_id,))
                        new_sms = cursor.fetchall()
                    
                    # Check each new SMS for balance
                    for sms_row in new_sms:
                        sms_content = sms_row[0]
                        sender = sms_row[1]
                        received_at = sms_row[2]
                        
                        balance_sms_result = self.detect_balance_sms(sms_content, sender)
                        if balance_sms_result and balance_sms_result.get('is_balance_sms'):
                            balance = balance_sms_result.get('balance')
                            logger.info(f"💰 Found forced SMS balance: {balance} from {sender}")
                            
                            return {
                                'success': True,
                                'is_sbc_response': False,
                                'balance': balance,
                                'method': 'forced_sms',
                                'sender': sender
                            }
                    
                    elapsed = time.time() - start_time
                    logger.debug(f"⏳ Still waiting for SMS... ({elapsed:.1f}s elapsed)")
                
                logger.warning(f"⏰ Timeout: No balance SMS received within {max_wait_time}s")
                return {'success': False, 'error': 'sms_timeout'}
                
        except Exception as e:
            logger.error(f"Forced SMS balance check failed: {e}")
            return {'success': False, 'error': str(e)}
    
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
    
    def _send_ussd_command_enhanced(self, ser: serial.Serial, command: str) -> Optional[str]:
        """Send USSD command with enhanced error handling and retry logic"""
        try:
            logger.debug(f"📞 Enhanced USSD command: {command}")
            
            # Clear buffers thoroughly
            ser.reset_input_buffer()
            ser.reset_output_buffer()
            time.sleep(0.5)  # Give time for buffer clearing
            
            # Send USSD command with retry logic
            max_attempts = 3
            for attempt in range(max_attempts):
                logger.debug(f"📞 USSD attempt {attempt + 1}/{max_attempts}")
                
                # Send USSD command
                ussd_at_command = f'AT+CUSD=1,"{command}",15'
                ser.write(f"{ussd_at_command}\r\n".encode())
                
                # Wait for initial OK with timeout
                response = ""
                start_time = time.time()
                ok_timeout = 3
                
                while time.time() - start_time < ok_timeout:
                    if ser.in_waiting > 0:
                        data = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
                        response += data
                        if "OK" in response or "ERROR" in response:
                            break
                    time.sleep(0.1)
                
                if "ERROR" in response:
                    logger.warning(f"⚠️  USSD command failed on attempt {attempt + 1}: {response}")
                    if attempt < max_attempts - 1:
                        time.sleep(2)  # Wait before retry
                        continue
                    else:
                        return None
                
                # Wait for +CUSD response with extended timeout
                ussd_response = ""
                start_time = time.time()
                extended_timeout = 25  # Increased timeout for better reliability
                
                while time.time() - start_time < extended_timeout:
                    if ser.in_waiting > 0:
                        data = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
                        ussd_response += data
                        
                        if "+CUSD:" in ussd_response:
                            # Wait a bit more for complete response
                            time.sleep(1)
                            if ser.in_waiting > 0:
                                data = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
                                ussd_response += data
                            logger.info(f"📞 Enhanced USSD response received")
                            return ussd_response
                    
                    time.sleep(0.2)
                
                logger.warning(f"⚠️  No +CUSD response on attempt {attempt + 1}")
                if attempt < max_attempts - 1:
                    time.sleep(3)  # Wait before retry
            
            logger.error(f"❌ All USSD attempts failed for {command}")
            return None
            
        except Exception as e:
            logger.error(f"Failed to send enhanced USSD command: {e}")
            return None

    def _try_alternative_balance_extraction(self, response: str) -> Optional[str]:
        """Try alternative methods to extract balance from USSD response"""
        try:
            logger.info(f"🔍 Trying alternative balance extraction from: {response}")
            
            # Alternative patterns for balance extraction
            alt_patterns = [
                r'(\d+[.,]\d{2})\s*(?:DA|DZD|دج)',  # Number with currency
                r'(\d+)\s*[.,]\s*(\d{2})\s*(?:DA|DZD|دج)',  # Split number format
                r'Balance[:\s]*(\d+[.,]\d+)',  # Balance keyword
                r'Solde[:\s]*(\d+[.,]\d+)',   # French balance
                r'رصيد[:\s]*(\d+[.,]\d+)',     # Arabic balance
                r'Credit[:\s]*(\d+[.,]\d+)',  # Credit keyword
                r'(\d+[.,]\d+)',              # Any decimal number
                r'(\d{2,6})',                 # Any significant number
            ]
            
            for i, pattern in enumerate(alt_patterns):
                match = re.search(pattern, response, re.IGNORECASE)
                if match:
                    if len(match.groups()) > 1:
                        # Handle split format like "35,97"
                        balance = f"{match.group(1)}.{match.group(2)}"
                    else:
                        balance = match.group(1).replace(',', '.')
                    
                    # Validate that this looks like a reasonable balance
                    try:
                        balance_float = float(balance)
                        if 0 <= balance_float <= 50000:  # Reasonable range for balance
                            logger.info(f"✅ Alternative extraction successful (pattern {i+1}): {balance}")
                            return balance
                    except ValueError:
                        continue
            
            logger.warning(f"⚠️  Alternative extraction failed for: {response}")
            return None
            
        except Exception as e:
            logger.error(f"Alternative balance extraction error: {e}")
            return None

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
        """ENHANCED: Parse balance string to float amount with COMPLETE European number format preservation"""
        try:
            if not balance_str:
                return 0.0
            
            # Clean the balance string
            balance_clean = str(balance_str).strip()
            logger.info(f"� COMPREHENSIVE: Parsing balance: '{balance_clean}'")
            
            # Remove common currency indicators
            balance_clean = re.sub(r'\s*(?:DZD|DA|دج|دينار)\s*', '', balance_clean, flags=re.IGNORECASE)
            balance_clean = balance_clean.strip()
            
            # COMPREHENSIVE: Handle European vs US number format properly
            if '.' in balance_clean and ',' in balance_clean:
                # Determine format by position of last dot vs last comma
                last_dot_pos = balance_clean.rfind('.')
                last_comma_pos = balance_clean.rfind(',')
                
                if last_comma_pos > last_dot_pos:
                    # European format: 48.410,82 -> 48410.82
                    # Dots are thousands separators, comma is decimal
                    # CRITICAL: Keep the complete amount together
                    thousands_part = balance_clean[:last_comma_pos].replace('.', '')
                    decimal_part = balance_clean[last_comma_pos + 1:]
                    standardized = f"{thousands_part}.{decimal_part}"
                    result = float(standardized)
                    logger.info(f"🇪🇺 COMPLETE BALANCE: '{balance_clean}' -> '{standardized}' -> {result}")
                    return result
                else:
                    # US format: 48,410.82 -> 48410.82
                    # Commas are thousands separators, dot is decimal
                    standardized = balance_clean.replace(',', '')
                    result = float(standardized)
                    logger.info(f"🇺🇸 COMPLETE BALANCE: '{balance_clean}' -> '{standardized}' -> {result}")
                    return result
                    
            elif ',' in balance_clean and '.' not in balance_clean:
                # European decimal only: 410,82 -> 410.82
                standardized = balance_clean.replace(',', '.')
                result = float(standardized)
                logger.info(f"🇪🇺 DECIMAL BALANCE: '{balance_clean}' -> '{standardized}' -> {result}")
                return result
                
            elif '.' in balance_clean and ',' not in balance_clean:
                # Could be US decimal or thousands separator
                if balance_clean.count('.') == 1:
                    decimal_part = balance_clean.split('.')[1]
                    if len(decimal_part) == 2:
                        # US decimal: 410.82 -> 410.82
                        result = float(balance_clean)
                        logger.info(f"🇺🇸 DECIMAL BALANCE: '{balance_clean}' -> {result}")
                        return result
                    else:
                        # Thousands separator only: 48.410 -> 48410.00
                        # CRITICAL: Keep as complete amount
                        standardized = balance_clean.replace('.', '')
                        result = float(standardized)
                        logger.info(f"� THOUSANDS BALANCE: '{balance_clean}' -> '{standardized}' -> {result}")
                        return result
                else:
                    # Multiple dots, treat as thousands: 1.234.567 -> 1234567.00
                    standardized = balance_clean.replace('.', '')
                    result = float(standardized)
                    logger.info(f"� MULTIPLE THOUSANDS BALANCE: '{balance_clean}' -> '{standardized}' -> {result}")
                    return result
            else:
                # Just a number
                result = float(balance_clean)
                logger.info(f"� PLAIN BALANCE: '{balance_clean}' -> {result}")
                return result
            
        except ValueError as e:
            logger.warning(f"COMPREHENSIVE: Failed to parse balance amount '{balance_str}': {e}")
            # Try to extract just digits and decimal point
            try:
                digits_only = re.search(r'(\d+(?:[.,]\d+)?)', balance_str)
                if digits_only:
                    fallback = digits_only.group(1).replace(',', '.')
                    logger.info(f"🔄 COMPREHENSIVE Fallback: '{balance_str}' -> {fallback}")
                    return float(fallback)
            except:
                pass
            return 0.0
        except Exception as e:
            logger.error(f"COMPREHENSIVE: Unexpected error parsing balance '{balance_str}': {e}")
            return 0.0
    
    def _parse_european_number_format(self, number_str: str) -> float:
        """COMPREHENSIVE FIX: Parse European number format (48.410,82) to standard float (48410.82)"""
        try:
            if not number_str:
                return 0.0
            
            number_clean = str(number_str).strip()
            
            # Remove currency symbols and extra whitespace
            number_clean = re.sub(r'\s*(?:DZD|DA|دج|دينار)\s*', '', number_clean, flags=re.IGNORECASE)
            number_clean = number_clean.strip()
            
            logger.info(f"� COMPREHENSIVE: Parsing European format '{number_clean}'")
            
            # COMPREHENSIVE: Handle European vs US number format properly
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
                    logger.info(f"🇪🇺 COMPLETE NUMBER: '{number_clean}' -> '{standardized}' -> {result}")
                    return result
                else:
                    # US format: 48,410.82 -> 48410.82
                    # Commas are thousands separators, dot is decimal
                    standardized = number_clean.replace(',', '')
                    result = float(standardized)
                    logger.info(f"🇺🇸 COMPLETE NUMBER: '{number_clean}' -> '{standardized}' -> {result}")
                    return result
                    
            elif ',' in number_clean and '.' not in number_clean:
                # European decimal only: 410,82 -> 410.82
                standardized = number_clean.replace(',', '.')
                result = float(standardized)
                logger.info(f"🇪🇺 DECIMAL NUMBER: '{number_clean}' -> '{standardized}' -> {result}")
                return result
                
            elif '.' in number_clean and ',' not in number_clean:
                # Could be US decimal or thousands separator
                if number_clean.count('.') == 1:
                    decimal_part = number_clean.split('.')[1]
                    if len(decimal_part) == 2:
                        # US decimal: 410.82 -> 410.82
                        result = float(number_clean)
                        logger.info(f"🇺🇸 DECIMAL NUMBER: '{number_clean}' -> {result}")
                        return result
                    else:
                        # Thousands separator only: 48.410 -> 48410.00
                        # CRITICAL: Keep as complete amount
                        standardized = number_clean.replace('.', '')
                        result = float(standardized)
                        logger.info(f"🔢 THOUSANDS NUMBER: '{number_clean}' -> '{standardized}' -> {result}")
                        return result
                else:
                    # Multiple dots, treat as thousands: 1.234.567 -> 1234567.00
                    standardized = number_clean.replace('.', '')
                    result = float(standardized)
                    logger.info(f"🔢 MULTIPLE THOUSANDS NUMBER: '{number_clean}' -> '{standardized}' -> {result}")
                    return result
            else:
                # Just a number
                result = float(number_clean)
                logger.info(f"🔢 PLAIN NUMBER: '{number_clean}' -> {result}")
                return result
                
        except Exception as e:
            logger.warning(f"COMPREHENSIVE: Failed to parse European number format '{number_str}': {e}")
            return 0.0
    
    def get_stats(self) -> Dict:
        """Get comprehensive balance checker statistics including enhanced methods"""
        stats = self.stats.copy()
        stats['moblis_sender_id'] = self.critical_recharge_sender
        stats['pending_requests_info'] = self.get_pending_requests_info()
        
        # Add success rates
        total_checks = stats['successful_checks'] + stats['failed_checks']
        if total_checks > 0:
            stats['success_rate'] = (stats['successful_checks'] / total_checks) * 100
        else:
            stats['success_rate'] = 0.0
        
        # Add method breakdown
        stats['method_breakdown'] = {
            'ussd_direct': stats['ussd_direct_success'],
            'ussd_sbc': stats['ussd_sbc_responses'], 
            'sms_fallback': stats['sms_fallback_success'],
            'forced_sms': stats['forced_sms_success'],
            'ussd_failures': stats['ussd_failed'],
            'total_failures': stats['all_methods_failed']
        }
        
        return stats
    
    def test_balance_extraction_methods(self, sim_id: int) -> Dict:
        """Test all balance extraction methods for a specific SIM"""
        try:
            logger.info(f"🧪 Testing all balance extraction methods for SIM {sim_id}")
            
            # Get SIM info
            sim_info = self._get_sim_info(sim_id)
            if not sim_info:
                return {'success': False, 'error': 'sim_not_found'}
            
            sim_info['id'] = sim_id
            port = sim_info['port']
            results = {}
            
            # Test Method 1: USSD Direct
            logger.info(f"🧪 Testing USSD direct method...")
            ussd_result = self._try_ussd_balance_extraction(port, sim_id)
            results['ussd_direct'] = {
                'success': ussd_result.get('success', False) if ussd_result else False,
                'result': ussd_result,
                'method': 'ussd_direct'
            }
            
            # Test Method 2: SMS Fallback
            logger.info(f"🧪 Testing SMS fallback method...")
            sms_result = self._try_sms_balance_fallback(sim_id)
            results['sms_fallback'] = {
                'success': sms_result.get('success', False) if sms_result else False,
                'result': sms_result,
                'method': 'sms_fallback'
            }
            
            # Test Method 3: Forced SMS (only if others fail)
            if not results['ussd_direct']['success'] and not results['sms_fallback']['success']:
                logger.info(f"🧪 Testing forced SMS method...")
                forced_result = self._force_sms_balance_check_with_ussd(port, sim_id)
                results['forced_sms'] = {
                    'success': forced_result.get('success', False) if forced_result else False,
                    'result': forced_result,
                    'method': 'forced_sms'
                }
            
            # Summary
            successful_methods = [method for method, data in results.items() if data['success']]
            
            return {
                'success': len(successful_methods) > 0,
                'sim_id': sim_id,
                'successful_methods': successful_methods,
                'results': results,
                'summary': f"{len(successful_methods)}/{len(results)} methods successful"
            }
            
        except Exception as e:
            logger.error(f"Error testing balance extraction methods for SIM {sim_id}: {e}")
            return {'success': False, 'error': str(e)}
    
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
        """Detect if SMS contains real balance information - ENHANCED DETECTION"""
        try:
            logger.debug(f"🔍 Enhanced balance SMS check from {sender}: {message_content[:100]}...")
            
            # **COMPREHENSIVE BALANCE DETECTION with enhanced number format handling**
            # Try each pattern and log which one matches
            for i, pattern in enumerate(self.balance_sms_patterns):
                match = re.search(pattern, message_content, re.IGNORECASE)
                if match:
                    balance_raw = match.group(1)
                    
                    # Parse balance using the enhanced parsing logic
                    balance_amount = self._parse_european_number_format(balance_raw)
                    
                    logger.info(f"💰 BALANCE SMS DETECTED (Pattern {i+1}): '{balance_raw}' -> {balance_amount} from {sender}")
                    logger.debug(f"📋 Pattern matched: {pattern}")
                    logger.debug(f"📋 Full message: {message_content}")
                    self.stats['balance_sms_processed'] += 1
                    
                    # Track pattern usage
                    pattern_key = f"pattern_{i+1}"
                    self.stats['pattern_usage'][pattern_key] = self.stats['pattern_usage'].get(pattern_key, 0) + 1
                    return {
                        'is_balance_sms': True,
                        'balance': str(balance_amount),
                        'sender': sender,
                        'content': message_content,
                        'pattern_used': i + 1,
                        'raw_amount': balance_raw
                    }
            
            # **FALLBACK: Try flexible numeric extraction for balance-like messages**
            # Look for standalone numbers followed by currency in SMS-like contexts
            flexible_patterns = [
                r'(\d{1,3}(?:\.\d{3})*,\d{2})\s*(?:DA|DZD)\b',     # European format with currency
                r'(\d{1,3}(?:,\d{3})*\.\d{2})\s*(?:DA|DZD)\b',     # US format with currency
                r'(\d+,\d{2})\s*(?:DA|DZD)\b',                     # European decimal with currency
                r'(\d+\.\d{2})\s*(?:DA|DZD)\b',                    # US decimal with currency
                r'(\d+)\s*(?:DA|DZD)\b',                           # Integer with currency
                r'\b(\d+[.,]\d+)\s*(?:دج|دينار)\b',                 # Arabic currency
                r'(?:solde|balance|رصيد)\D*(\d+[.,]\d+)',          # Balance keyword followed by number
            ]
            
            for i, pattern in enumerate(flexible_patterns):
                match = re.search(pattern, message_content, re.IGNORECASE)
                if match:
                    balance_raw = match.group(1)
                    
                    # Additional verification: check if this looks like a real balance message
                    if self._is_likely_balance_message(message_content):
                        balance_amount = self._parse_european_number_format(balance_raw)
                        logger.info(f"💰 BALANCE SMS DETECTED (Flexible Pattern {i+1}): '{balance_raw}' -> {balance_amount} from {sender}")
                        logger.debug(f"📋 Flexible pattern: {pattern}")
                        self.stats['balance_sms_processed'] += 1
                        
                        # Track flexible pattern usage
                        pattern_key = f"flexible_{i+1}"
                        self.stats['pattern_usage'][pattern_key] = self.stats['pattern_usage'].get(pattern_key, 0) + 1
                        return {
                            'is_balance_sms': True,
                            'balance': str(balance_amount),
                            'sender': sender,
                            'content': message_content,
                            'pattern_used': f"flexible_{i+1}",
                            'raw_amount': balance_raw
                        }
            
            # **CHECK IF IT'S ONLY A PACKAGE ACTIVATION** (no balance info)
            if self._is_package_activation(message_content):
                logger.info(f"📦 Package activation detected (no balance), ignoring: {message_content[:100]}...")
                self.stats['package_activations_ignored'] += 1
                return {
                    'is_balance_sms': False,
                    'is_package_activation': True,
                    'sender': sender,
                    'content': message_content
                }
            
            # No balance pattern matched
            logger.debug(f"❌ No balance pattern matched for SMS from {sender}")
            return None
            
        except Exception as e:
            logger.error(f"Error detecting balance SMS: {e}")
            return None
    
    def _is_likely_balance_message(self, content: str) -> bool:
        """Check if message content looks like a balance message"""
        try:
            content_lower = content.lower()
            
            # Balance-related keywords that increase confidence
            balance_keywords = [
                'solde', 'balance', 'crédit', 'credit', 'montant', 'disponible',
                'رصيد', 'الرصيد', 'رصيدك', 'sama', 'compte', 'account'
            ]
            
            # Non-balance keywords that decrease confidence
            non_balance_keywords = [
                'mix', 'plan', 'bonus', 'internet', 'appel', 'sms', 'valable',
                'activated', 'ajouté', 'ajoutée', 'service', 'contact'
            ]
            
            has_balance_keyword = any(keyword in content_lower for keyword in balance_keywords)
            has_non_balance_keyword = any(keyword in content_lower for keyword in non_balance_keywords)
            
            # If it has balance keywords and no non-balance keywords, likely a balance message
            if has_balance_keyword and not has_non_balance_keyword:
                return True
            
            # If message is short and contains numbers with currency, likely balance
            if len(content) < 100 and re.search(r'\d+[.,]\d+\s*(?:da|dzd|دج)', content_lower):
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error checking if likely balance message: {e}")
            return False
    
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
        """Process balance SMS and validate against pending recharge if any - ENHANCED"""
        try:
            sender = balance_sms_info.get('sender', 'Unknown')
            new_balance = balance_sms_info.get('balance')
            pattern_used = balance_sms_info.get('pattern_used', 'unknown')
            
            logger.info(f"📱 Processing enhanced balance SMS for SIM {sim_id}: {new_balance} from {sender} (Pattern: {pattern_used})")
            
            # ===== ALWAYS UPDATE DATABASE WITH SMS BALANCE =====
            # SMS balance is considered the most accurate real-time balance
            old_balance = db.get_current_balance(sim_id)
            logger.info(f"📊 Current database balance: {old_balance}, New SMS balance: {new_balance}")
            
            # Check if there's a meaningful difference before updating
            old_amount = self._parse_balance_amount(old_balance)
            new_amount = self._parse_balance_amount(new_balance)
            balance_difference = abs(new_amount - old_amount)
            
            if balance_difference > 0.01:  # Update if difference is more than 1 cent
                logger.info(f"💾 SMS balance differs from database, updating: {old_balance} → {new_balance}")
                
                # Update SIM balance in database
                db.update_sim_info(sim_id, balance=new_balance)
                
                # Record balance history with pattern information
                change_amount = new_amount - old_amount
                db.add_balance_history(
                    sim_id=sim_id,
                    old_balance=old_balance,
                    new_balance=new_balance, 
                    change_amount=f"{change_amount:+.2f}",
                    change_type=f'sms_balance_update_pattern_{pattern_used}',
                    detected_from_sms=True,
                    sms_sender=sender,
                    sms_content=f"[Pattern {pattern_used}] {balance_sms_info.get('content', '')[:450]}"
                )
                
                logger.info(f"✅ Database updated with SMS balance for SIM {sim_id} using pattern {pattern_used}")
            else:
                logger.info(f"📲 SMS balance matches database balance, no update needed")
            
            # Check if there's a pending balance request for this SIM
            if sim_id in self.pending_balance_requests:
                pending = self.pending_balance_requests[sim_id]
                recharge_info = pending['recharge_info']
                pending_method = pending.get('method', 'unknown')
                
                logger.info(f"🔗 Found pending balance request for SIM {sim_id} (method: {pending_method}), validating recharge")
                
                # Remove from pending
                del self.pending_balance_requests[sim_id]
                self.stats['pending_balance_requests'] -= 1
                
                # Validate the recharge using SMS balance
                return self._validate_recharge_with_sms_balance_enhanced(sim_id, recharge_info, new_balance, pattern_used, pending_method)
            else:
                # No pending request, this is a standalone balance SMS update
                logger.info(f"📊 No pending request, standalone SMS balance update for SIM {sim_id}")
                
                # فحص حد الرصيد وإرسال تنبيه إذا لزم الأمر (للتحديث عبر SMS)
                if self._check_balance_limit(sim_id, new_balance):
                    logger.info(f"🚨 Balance limit reached for SIM {sim_id} (SMS update), sending notification...")
                    self._notify_balance_limit_reached(sim_id, new_balance)
                
                return True
                
        except Exception as e:
            logger.error(f"Error processing enhanced balance SMS for SIM {sim_id}: {e}")
            return False
    
    def _validate_recharge_with_sms_balance_enhanced(self, sim_id: int, recharge_info: Dict, new_balance: str, 
                                                   pattern_used: str, original_method: str) -> bool:
        """Enhanced validation of recharge using balance received via SMS"""
        try:
            is_critical = recharge_info.get('is_critical', False)
            sender = recharge_info.get('sender', 'Unknown')
            
            logger.info(f"📱 Enhanced SMS balance validation for SIM {sim_id} (Pattern: {pattern_used}, Original: {original_method})")
            
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
            logger.info(f"📊 Detection method: {original_method} → SMS (Pattern: {pattern_used})")
            
            # **CRITICAL VALIDATION - ZERO TOLERANCE**
            if is_critical:
                amount_difference = abs(change_amount - expected_amount)
                if amount_difference > 0.01:  # Allow only 0.01 DZD tolerance
                    logger.error(f"🚨 CRITICAL VALIDATION FAILED (Enhanced SMS)!")
                    logger.error(f"   Expected: {expected_amount} DZD")
                    logger.error(f"   Actual:   {change_amount} DZD")
                    logger.error(f"   Diff:     {amount_difference} DZD")
                    logger.error(f"   Pattern:  {pattern_used}")
                    logger.error(f"   Method:   {original_method} → SMS")
                    self.stats['validation_mismatches'] += 1
                    
                    # Record the validation failure with enhanced details
                    db.add_balance_history(
                        sim_id=sim_id,
                        old_balance=old_balance,
                        new_balance=new_balance,
                        change_amount=f"{change_amount:+.2f}",
                        recharge_amount=recharge_info.get('amount'),
                        change_type=f'recharge_validation_failed_sms_pattern_{pattern_used}',
                        detected_from_sms=True,
                        sms_sender=sender,
                        sms_content=f"SMS VALIDATION FAILED [{original_method}→SMS Pattern {pattern_used}] - Expected: {expected_amount}, Actual: {change_amount} | {recharge_info.get('content', '')[:350]}"
                    )
                    
                    return False
                else:
                    logger.info(f"✅ CRITICAL VALIDATION PASSED (Enhanced SMS) - Amount matches exactly! (Pattern: {pattern_used})")
            
            # Update SIM balance in database - save as clean number (100.00)
            db.update_sim_info(sim_id, balance=new_balance)
            
            # Record balance history with enhanced tracking
            change_type = f'critical_recharge_validated_sms_pattern_{pattern_used}' if is_critical else f'recharge_sms_pattern_{pattern_used}'
            db.add_balance_history(
                sim_id=sim_id,
                old_balance=old_balance,
                new_balance=new_balance,
                change_amount=f"{change_amount:+.2f}",
                recharge_amount=recharge_info.get('amount'),
                change_type=change_type,
                detected_from_sms=True,
                sms_sender=sender,
                sms_content=f"Enhanced SMS Validation [{original_method}→SMS Pattern {pattern_used}] | {recharge_info.get('content', '')[:350]}"
            )
            
            if is_critical:
                logger.info(f"✅ CRITICAL ENHANCED BALANCE CHECK COMPLETED (SMS Pattern {pattern_used}) for SIM {sim_id}")
            else:
                logger.info(f"✅ Enhanced balance check completed (SMS Pattern {pattern_used}) for SIM {sim_id}")
                
            self.stats['successful_checks'] += 1
            self.stats['last_check_time'] = datetime.now()
            
            # فحص حد الرصيد وإرسال تنبيه إذا لزم الأمر (للتحقق عبر SMS)
            if self._check_balance_limit(sim_id, new_balance):
                logger.info(f"🚨 Balance limit reached for SIM {sim_id} (Enhanced SMS validation), sending notification...")
                self._notify_balance_limit_reached(sim_id, new_balance)
            
            return True
            
        except Exception as e:
            logger.error(f"Error in enhanced SMS balance validation: {e}")
            self.stats['failed_checks'] += 1
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
            
            # فحص حد الرصيد وإرسال تنبيه إذا لزم الأمر (للتحقق عبر SMS)
            if self._check_balance_limit(sim_id, new_balance):
                logger.info(f"🚨 Balance limit reached for SIM {sim_id} (SMS validation), sending notification...")
                self._notify_balance_limit_reached(sim_id, new_balance)
            
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
    
    def _check_balance_limit(self, sim_id: int, new_balance: str) -> bool:
        """فحص ما إذا كان الرصيد الجديد وصل للحد المطلوب (45000 دج)"""
        try:
            from core.config import BALANCE_LIMIT
            
            # تحويل الرصيد الجديد إلى رقم
            balance_amount = self._parse_balance_amount(new_balance)
            
            logger.debug(f"Checking balance limit for SIM {sim_id}: {balance_amount} vs {BALANCE_LIMIT}")
            
            # فحص إذا وصل أو تجاوز الحد المطلوب
            if balance_amount >= BALANCE_LIMIT:
                logger.info(f"🚨 BALANCE LIMIT REACHED for SIM {sim_id}: {balance_amount} >= {BALANCE_LIMIT}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error checking balance limit for SIM {sim_id}: {e}")
            return False
    
    def _notify_balance_limit_reached(self, sim_id: int, new_balance: str):
        """إرسال تنبيه وصول الرصيد للحد المطلوب"""
        try:
            from core.config import BALANCE_LIMIT
            
            logger.info(f"📨 Sending balance limit notification for SIM {sim_id}")
            
            # الحصول على معلومات الشريحة والمودم والمجموعة
            sim_info = db.get_sim_by_id(sim_id)
            if not sim_info:
                logger.error(f"Could not find SIM info for ID {sim_id}")
                return False
            
            # الحصول على معلومات المجموعة من خلال المودم
            modem_id = sim_info.get('modem_id')
            group_info = None
            group_name = 'غير محدد'
            group_id = None
            
            if modem_id:
                # البحث عن المجموعة المرتبطة بهذا المودم
                with db.get_connection() as conn:
                    cursor = conn.execute(
                        "SELECT id, group_name FROM groups WHERE modem_id = ? AND status = 'active'",
                        (modem_id,)
                    )
                    group_row = cursor.fetchone()
                    if group_row:
                        group_id = group_row[0]
                        group_name = group_row[1]
                        logger.info(f"Found group for SIM {sim_id}: {group_name} (ID: {group_id})")
                    else:
                        logger.warning(f"No group found for modem {modem_id}")
            
            # إعداد بيانات التنبيه
            from datetime import datetime
            balance_data = {
                'sim_number': sim_info.get('phone_number', 'غير معروف'),
                'current_balance': new_balance,
                'limit': f"{BALANCE_LIMIT:.2f}",
                'group_name': group_name,
                'group_id': group_id,
                'sim_id': sim_id,
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            
            logger.info(f"Balance notification data: {balance_data}")
            
            # إرسال التنبيه بشكل غير متزامن
            self._notify_balance_limit_async(balance_data)
            
            # تحديث الإحصائيات
            self.stats['balance_limit_notifications'] += 1
            
            logger.info(f"✅ Balance limit notification queued for SIM {sim_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error setting up balance limit notification for SIM {sim_id}: {e}")
            return False
    
    def _notify_balance_limit_async(self, balance_data: Dict):
        """إرسال تنبيه حد الرصيد بشكل غير متزامن"""
        try:
            logger.info(f"Setting up async balance limit notification...")
            
            # الحصول على bot instance
            from core.group_manager import get_telegram_bot
            telegram_bot = get_telegram_bot()
            
            if telegram_bot and hasattr(telegram_bot, 'admin_service'):
                logger.info(f"Telegram bot found, creating notification thread...")
                
                import asyncio
                import threading
                
                def run_notification():
                    try:
                        logger.info(f"Starting balance limit notification thread...")
                        
                        # إنشاء event loop جديد
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        
                        # تشغيل التنبيه
                        result = loop.run_until_complete(
                            telegram_bot.admin_service.notify_balance_limit_reached(balance_data)
                        )
                        loop.close()
                        
                        if result:
                            logger.info(f"✅ Balance limit notification sent successfully")
                        else:
                            logger.error(f"❌ Balance limit notification failed")
                            
                    except Exception as e:
                        logger.error(f"Error in balance limit notification thread: {e}")
                        import traceback
                        logger.error(f"Traceback: {traceback.format_exc()}")
                
                # تشغيل التنبيه في thread منفصل
                notification_thread = threading.Thread(target=run_notification, daemon=True)
                notification_thread.start()
                logger.info(f"Balance limit notification thread started")
                
            else:
                logger.error(f"Telegram bot not available for balance limit notification")
                logger.error(f"Bot instance: {telegram_bot}")
                if telegram_bot:
                    logger.error(f"Has admin_service: {hasattr(telegram_bot, 'admin_service')}")
                
        except Exception as e:
            logger.error(f"Error setting up balance limit notification: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            logger.error(f"Error setting up balance limit notification: {e}")

    def cleanup_old_sms_for_balance_extraction(self, sim_id: int, days_to_keep: int = 7) -> int:
        """Clean up old SMS messages to improve balance extraction performance"""
        try:
            from datetime import datetime, timedelta
            cutoff_date = datetime.now() - timedelta(days=days_to_keep)
            
            logger.info(f"🧹 Cleaning up SMS older than {days_to_keep} days for SIM {sim_id}")
            
            with db.get_connection() as conn:
                # Count messages to be deleted
                cursor = conn.execute("""
                    SELECT COUNT(*) FROM sms 
                    WHERE sim_id = ? AND received_at < ?
                """, (sim_id, cutoff_date))
                count_to_delete = cursor.fetchone()[0]
                
                if count_to_delete > 0:
                    # Delete old messages
                    conn.execute("""
                        DELETE FROM sms 
                        WHERE sim_id = ? AND received_at < ?
                    """, (sim_id, cutoff_date))
                    conn.commit()
                    
                    logger.info(f"🧹 Cleaned up {count_to_delete} old SMS messages for SIM {sim_id}")
                else:
                    logger.info(f"🧹 No old SMS messages to clean up for SIM {sim_id}")
                
                return count_to_delete
                
        except Exception as e:
            logger.error(f"Error cleaning up old SMS for SIM {sim_id}: {e}")
            return 0
    
    def get_balance_extraction_report(self, sim_id: int = None) -> Dict:
        """Get comprehensive report on balance extraction performance"""
        try:
            report = {
                'timestamp': datetime.now().isoformat(),
                'overall_stats': self.get_stats(),
                'sim_specific': {}
            }
            
            # If specific SIM requested, get detailed info
            if sim_id:
                sim_info = self._get_sim_info(sim_id)
                if sim_info:
                    # Get recent balance history
                    with db.get_connection() as conn:
                        cursor = conn.execute("""
                            SELECT change_type, COUNT(*) as count
                            FROM balance_history 
                            WHERE sim_id = ? AND created_at >= datetime('now', '-7 days')
                            GROUP BY change_type
                            ORDER BY count DESC
                        """, (sim_id,))
                        balance_history = [dict(row) for row in cursor.fetchall()]
                        
                        # Get recent SMS count
                        cursor = conn.execute("""
                            SELECT COUNT(*) as total_sms,
                                   COUNT(CASE WHEN received_at >= datetime('now', '-24 hours') THEN 1 END) as recent_sms
                            FROM sms WHERE sim_id = ?
                        """, (sim_id,))
                        sms_stats = dict(cursor.fetchone())
                    
                    report['sim_specific'][sim_id] = {
                        'sim_info': sim_info,
                        'recent_balance_changes': balance_history,
                        'sms_stats': sms_stats
                    }
            
            return report
            
        except Exception as e:
            logger.error(f"Error generating balance extraction report: {e}")
            return {'error': str(e), 'timestamp': datetime.now().isoformat()}

    def force_sms_balance_check(self, sim_id: int) -> Dict:
        """Force comprehensive balance check using all available methods"""
        try:
            logger.info(f"🔥 FORCE: Comprehensive balance check for SIM {sim_id}")
            
            # Get SIM info
            sim_info = self._get_sim_info(sim_id)
            if not sim_info:
                return {
                    'success': False,
                    'balance_found': False,
                    'message': f"SIM {sim_id} not found in database"
                }
            
            sim_info['id'] = sim_id
            
            # Try the enhanced balance extraction with all fallbacks
            balance_result = self._extract_live_balance_enhanced(sim_info)
            
            if balance_result and balance_result.get('success'):
                method_used = balance_result.get('method', 'unknown')
                
                if balance_result.get('is_sbc_response'):
                    # SBC response - balance will come via SMS
                    return {
                        'success': True,
                        'balance_found': False,
                        'is_sbc': True,
                        'method': method_used,
                        'message': f"SBC response detected using {method_used} - balance will arrive via SMS"
                    }
                else:
                    # Direct balance obtained
                    balance = balance_result.get('balance')
                    
                    # Update database with the new balance
                    old_balance = db.get_current_balance(sim_id)
                    db.update_sim_info(sim_id, balance=balance)
                    
                    # Record the manual balance check in history
                    old_amount = self._parse_balance_amount(old_balance)
                    new_amount = self._parse_balance_amount(balance)
                    change_amount = new_amount - old_amount
                    
                    db.add_balance_history(
                        sim_id=sim_id,
                        old_balance=old_balance,
                        new_balance=balance,
                        change_amount=f"{change_amount:+.2f}",
                        change_type=f'manual_force_check_{method_used}',
                        detected_from_sms=method_used.startswith('sms'),
                        sms_sender='MANUAL_CHECK',
                        sms_content=f"Manual force balance check using {method_used}"
                    )
                    
                    logger.info(f"✅ Force balance check successful: {balance} using {method_used}")
                    
                    return {
                        'success': True,
                        'balance_found': True,
                        'balance': balance,
                        'method': method_used,
                        'old_balance': old_balance,
                        'change': f"{change_amount:+.2f}",
                        'message': f"Balance updated successfully using {method_used}: {balance}"
                    }
            else:
                error_msg = balance_result.get('error', 'unknown_error') if balance_result else 'no_result'
                logger.error(f"❌ All balance extraction methods failed for SIM {sim_id}: {error_msg}")
                
                return {
                    'success': False,
                    'balance_found': False,
                    'error': error_msg,
                    'message': f"All balance extraction methods failed: {error_msg}"
                }
                
        except Exception as e:
            logger.error(f"Error in force comprehensive balance check for SIM {sim_id}: {e}")
            return {
                'success': False,
                'balance_found': False,
                'error': str(e),
                'message': f"Error: {str(e)}"
            }

# Global balance checker instance
balance_checker = BalanceChecker()
