"""
SimPulse SMS Poller
Sequential SMS polling and management system
"""

import serial
import time
import re
import logging
import threading
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from .database import db
from .modem_detector import modem_detector
from .balance_checker import balance_checker

logger = logging.getLogger(__name__)

class SMSPoller:
    """Handles sequential SMS polling across all SIMs with message deletion"""
    
    def __init__(self):
        self.baud_rate = 9600
        self.connection_timeout = 3
        self.at_timeout = 5
        self.poll_interval = 30  # seconds between full cycles
        self.sim_delay = 5  # seconds between SIMs
        
        # State management
        self.polling_active = False
        self.polling_thread = None
        self.current_sim_index = 0
        self.active_sims = []
        
        # Statistics
        self.stats = {
            'total_polls': 0,
            'total_sms_found': 0,
            'total_sms_saved': 0,
            'total_sms_deleted': 0,
            'recharge_detected': 0,
            'balance_checks': 0,
            'last_poll_time': None,
            'errors': 0
        }
        
    def start_polling(self):
        """Start SMS polling thread"""
        if self.polling_active:
            logger.warning("SMS polling already active")
            return
            
        logger.info("🔄 Starting SMS polling system")
        self.polling_active = True
        self.polling_thread = threading.Thread(target=self._polling_worker, daemon=True)
        self.polling_thread.start()
        
    def stop_polling(self):
        """Stop SMS polling"""
        if not self.polling_active:
            return
            
        logger.info("⏹️  Stopping SMS polling")
        self.polling_active = False
        
        if self.polling_thread and self.polling_thread.is_alive():
            self.polling_thread.join(timeout=10)
            
        logger.info("✅ SMS polling stopped")
        
    def _polling_worker(self):
        """Main polling worker thread"""
        logger.info("📱 SMS polling worker started")
        
        while self.polling_active:
            try:
                # Refresh active SIMs list
                self._refresh_active_sims()
                
                if not self.active_sims:
                    logger.debug("No active SIMs found, waiting...")
                    time.sleep(self.poll_interval)
                    continue
                
                # Poll current SIM
                current_sim = self.active_sims[self.current_sim_index]
                self._poll_sim(current_sim)
                
                # Move to next SIM
                self.current_sim_index = (self.current_sim_index + 1) % len(self.active_sims)
                
                # If we completed a full cycle, wait the full interval
                if self.current_sim_index == 0:
                    self.stats['total_polls'] += 1
                    self.stats['last_poll_time'] = datetime.now()
                    
                    # Cleanup old pending balance requests (every full cycle)
                    balance_checker.cleanup_old_pending_requests(max_age_minutes=30)
                    
                    logger.info(f"🔄 Completed polling cycle {self.stats['total_polls']}")
                    logger.info(f"📊 Stats: Found={self.stats['total_sms_found']}, Saved={self.stats['total_sms_saved']}, Deleted={self.stats['total_sms_deleted']}, Recharge={self.stats['recharge_detected']}, Balance Checks={self.stats['balance_checks']}")
                    time.sleep(self.poll_interval)
                else:
                    # Short delay between SIMs
                    time.sleep(self.sim_delay)
                    
            except Exception as e:
                logger.error(f"SMS polling error: {e}")
                self.stats['errors'] += 1
                time.sleep(10)  # Wait before retry on error
                
        logger.info("📱 SMS polling worker stopped")
        
    def _refresh_active_sims(self):
        """Refresh list of active SIMs with their modem ports"""
        try:
            # Get all active SIMs from database
            with db.get_connection() as conn:
                cursor = conn.execute("""
                    SELECT s.id, s.modem_id, s.phone_number, m.imei 
                    FROM sims s 
                    JOIN modems m ON s.modem_id = m.id 
                    WHERE s.status = 'active' AND m.status = 'active'
                    ORDER BY s.created_at
                """)
                db_sims = [dict(row) for row in cursor.fetchall()]
            
            # Match with known modems to get ports
            active_sims = []
            for sim in db_sims:
                imei = sim['imei']
                if imei in modem_detector.known_modems:
                    modem_info = modem_detector.known_modems[imei]
                    sim['port'] = modem_info['port']
                    active_sims.append(sim)
                else:
                    logger.warning(f"SIM {sim['id']} (IMEI {imei}) - no port info available")
            
            # Update active SIMs list if changed
            if len(active_sims) != len(self.active_sims):
                logger.info(f"📱 Active SIMs updated: {len(active_sims)} SIMs available")
                self.active_sims = active_sims
                # Reset index if needed
                if self.current_sim_index >= len(self.active_sims):
                    self.current_sim_index = 0
            else:
                self.active_sims = active_sims
                
        except Exception as e:
            logger.error(f"Failed to refresh active SIMs: {e}")
            
    def _poll_sim(self, sim_info: Dict):
        """Poll SMS messages for a single SIM"""
        sim_id = sim_info['id']
        imei = sim_info['imei']
        port = sim_info['port']
        phone = sim_info.get('phone_number', 'Unknown')
        
        logger.info(f"📨 Polling SIM {sim_id} (IMEI {imei[-6:]}, Phone {phone}) on port {port}")
        
        try:
            with serial.Serial(
                port=port,
                baudrate=self.baud_rate,
                timeout=self.connection_timeout,
                write_timeout=self.connection_timeout
            ) as ser:
                
                # Initialize modem
                if not self._initialize_modem(ser):
                    logger.warning(f"⚠️  SIM {sim_id}: Failed to initialize modem")
                    return
                
                # Set SMS text mode
                if not self._set_sms_text_mode(ser):
                    logger.warning(f"⚠️  SIM {sim_id}: Failed to set SMS text mode")
                    return
                
                # List all SMS messages
                messages = self._list_all_messages(ser)
                
                if messages:
                    logger.info(f"📨 SIM {sim_id}: Found {len(messages)} SMS messages")
                    self.stats['total_sms_found'] += len(messages)
                    
                # Process messages - first consolidate fragments, then save CONSOLIDATED ONLY
                if messages:
                    consolidated_messages = self._consolidate_message_fragments(messages)
                    logger.info(f"📨 SIM {sim_id}: Consolidated {len(messages)} fragments into {len(consolidated_messages)} messages")
                    
                    # Track which original messages were used in consolidation
                    all_fragment_indices = []
                    
                    for msg in consolidated_messages:
                        # Save ONLY consolidated message to database (not fragments)
                        if self._save_message_to_db(sim_id, msg):
                            self.stats['total_sms_saved'] += 1
                            logger.info(f"💾 CONSOLIDATED: Saved message from {msg['sender']}: {msg['content'][:50]}...")
                            
                            # Track fragment indices used in this consolidated message
                            if 'fragment_indices' in msg:
                                all_fragment_indices.extend(msg['fragment_indices'])
                            else:
                                # Single message (not consolidated from fragments)
                                if 'index' in msg:
                                    all_fragment_indices.append(msg['index'])
                            
                            # Check if this is a recharge notification (MOBLIS ONLY)
                            recharge_info = balance_checker.detect_recharge_message(
                                msg['content'], msg['sender']
                            )
                            
                            if recharge_info and recharge_info.get('is_recharge'):
                                logger.info(f"💰 Recharge SMS detected from {recharge_info['sender']}: {recharge_info['amount']}")
                                self.stats['recharge_detected'] += 1
                                
                                # Trigger automatic balance check
                                if balance_checker.trigger_balance_check(sim_id, recharge_info):
                                    self.stats['balance_checks'] += 1
                                    logger.info(f"✅ SIM {sim_id}: Balance updated after recharge")
                                else:
                                    logger.warning(f"⚠️  SIM {sim_id}: Failed to update balance after recharge")
                            elif recharge_info and recharge_info.get('error'):
                                # Log error but don't crash the polling
                                logger.warning(f"⚠️  SIM {sim_id}: Recharge detection error: {recharge_info['error']}")
                            
                            # Check if this is a balance SMS (could be response to SBC)
                            balance_sms_info = balance_checker.detect_balance_sms(
                                msg['content'], msg['sender']
                            )
                            
                            if balance_sms_info:
                                if balance_sms_info.get('is_balance_sms'):
                                    logger.info(f"💰 Balance SMS detected: {balance_sms_info['balance']}")
                                    
                                    # Process balance SMS (will validate against pending requests)
                                    if balance_checker.process_balance_sms(sim_id, balance_sms_info):
                                        logger.info(f"✅ SIM {sim_id}: Balance SMS processed successfully")
                                    else:
                                        logger.warning(f"⚠️  SIM {sim_id}: Failed to process balance SMS")
                                        
                                elif balance_sms_info.get('is_package_activation'):
                                    logger.info(f"📦 Package activation SMS ignored: {msg['content'][:50]}...")
                                    # Just log and ignore package activations
                    
                    # Delete ALL original message fragments after consolidation and processing
                    deleted_count = 0
                    for original_msg in messages:
                        if self._delete_message(ser, original_msg['index']):
                            deleted_count += 1
                            self.stats['total_sms_deleted'] += 1
                            logger.debug(f"🗑️  SIM {sim_id}: Deleted original fragment {original_msg['index']}")
                        else:
                            logger.warning(f"⚠️  SIM {sim_id}: Failed to delete original fragment {original_msg['index']}")
                    
                    logger.info(f"🗑️  SIM {sim_id}: Deleted {deleted_count}/{len(messages)} original fragments after consolidation")
                else:
                    logger.debug(f"📨 SIM {sim_id}: No new messages")
                    
        except Exception as e:
            logger.error(f"Failed to poll SIM {sim_id}: {e}")
            
    def _initialize_modem(self, ser: serial.Serial) -> bool:
        """Initialize modem for SMS operations"""
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
            
            # Set preferred message storage to SIM card
            logger.debug("Setting SMS storage to SIM card")
            response = self._send_at_command_with_response(ser, 'AT+CPMS="SM","SM","SM"')
            logger.debug(f"SMS storage set: {repr(response)}")
                
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize modem: {e}")
            return False
            
    def _set_sms_text_mode(self, ser: serial.Serial) -> bool:
        """Set SMS to text mode"""
        try:
            return self._send_at_command(ser, "AT+CMGF=1")
        except Exception as e:
            logger.error(f"Failed to set SMS text mode: {e}")
            return False
            
    def _list_all_messages(self, ser: serial.Serial) -> List[Dict]:
        """List all SMS messages on SIM"""
        try:
            # Multiple attempts with different storage settings
            logger.debug("Setting message storage to different options...")
            
            # Try setting to SIM memory first
            response = self._send_at_command_with_response(ser, 'AT+CPMS="SM","SM","SM"')
            logger.debug(f"SIM storage response: {repr(response)}")
            
            # Check message count first
            response = self._send_at_command_with_response(ser, "AT+CPMS?")
            logger.debug(f"Message count check: {repr(response)}")
            
            # Try different commands to list messages
            commands_to_try = [
                'AT+CMGL="ALL"',
                'AT+CMGL=4',
                'AT+CMGL="REC UNREAD"',
                'AT+CMGL="REC READ"'
            ]
            
            for cmd in commands_to_try:
                logger.debug(f"Trying command: {cmd}")
                response = self._send_at_command_with_response(ser, cmd, timeout=10)
                logger.debug(f"Response: {repr(response[:200])}...")
                
                if "ERROR" not in response and "+CMGL:" in response:
                    # Parse messages from response
                    messages = self._parse_message_list(response)
                    logger.debug(f"Parsed {len(messages)} messages from {cmd}")
                    if messages:
                        return messages
                
                time.sleep(0.5)  # Small delay between commands
            
            logger.debug("No messages found with any command")
            return []
                
        except Exception as e:
            logger.error(f"Failed to list messages: {e}")
            return []
            
    def _parse_message_list(self, response: str) -> List[Dict]:
        """Parse SMS message list response"""
        messages = []
        
        try:
            lines = response.split('\n')
            i = 0
            
            while i < len(lines):
                line = lines[i].strip()
                
                # Look for +CMGL response line
                if line.startswith('+CMGL:'):
                    # Parse header with multiple patterns to handle different formats
                    # Pattern 1: +CMGL: index,status,sender,,timestamp (with empty alpha field)
                    # Pattern 2: +CMGL: index,status,sender,alpha,timestamp (with alpha field)
                    # Pattern 3: +CMGL: index,status,sender,timestamp (without alpha field)
                    
                    patterns = [
                        r'\+CMGL:\s*(\d+),"([^"]*?)","([^"]*?)",,"([^"]*?)"',  # Empty alpha field
                        r'\+CMGL:\s*(\d+),"([^"]*?)","([^"]*?)","([^"]*?)","([^"]*?)"',  # With alpha field
                        r'\+CMGL:\s*(\d+),"([^"]*?)","([^"]*?)","([^"]*?)"'  # Without alpha field
                    ]
                    
                    match = None
                    for pattern in patterns:
                        match = re.search(pattern, line)
                        if match:
                            break
                    
                    if match:
                        groups = match.groups()
                        index = int(groups[0])
                        status = groups[1]
                        sender = groups[2]
                        
                        # Handle different group counts
                        if len(groups) == 4:  # Without alpha field
                            timestamp = groups[3]
                        elif len(groups) == 5:  # With alpha field or empty alpha
                            timestamp = groups[4] if groups[3] else groups[3]  # Use non-empty field
                            if not timestamp:  # If both are empty, use last
                                timestamp = groups[4]
                        else:
                            timestamp = groups[-1]  # Use last group as timestamp
                        
                        # Get message content from next line
                        if i + 1 < len(lines):
                            content = lines[i + 1].strip()
                            
                            # Decode message content
                            decoded_content = self._decode_sms_content(content)
                            
                            # Parse timestamp
                            received_at = self._parse_sms_timestamp(timestamp)
                            
                            message = {
                                'index': index,
                                'status': status,
                                'sender': sender,
                                'content': decoded_content,
                                'received_at': received_at,
                                'raw_content': content
                            }
                            
                            messages.append(message)
                            logger.debug(f"📨 Parsed message {index}: From {sender}, Content: {decoded_content[:50]}...")
                
                i += 1
                
        except Exception as e:
            logger.error(f"Failed to parse message list: {e}")
            
        return messages
        
    def _decode_sms_content(self, content: str) -> str:
        """Decode SMS content (handle various encodings)"""
        try:
            # If content looks like hex (all hex characters), try to decode
            if re.match(r'^[0-9A-Fa-f]+$', content) and len(content) % 2 == 0:
                try:
                    # Try UTF-16 Big Endian decoding for hex content
                    hex_bytes = bytes.fromhex(content)
                    decoded = hex_bytes.decode('utf-16be', errors='ignore')
                    if decoded and decoded.isprintable():
                        return decoded
                except:
                    pass
                
                try:
                    # Try UTF-8 decoding for hex content
                    hex_bytes = bytes.fromhex(content)
                    decoded = hex_bytes.decode('utf-8', errors='ignore')
                    if decoded and decoded.isprintable():
                        return decoded
                except:
                    pass
                    
                try:
                    # Try Latin-1 decoding for hex content
                    hex_bytes = bytes.fromhex(content)
                    decoded = hex_bytes.decode('latin-1', errors='ignore')
                    if decoded and decoded.isprintable():
                        return decoded
                except:
                    pass
            
            # Return as-is if not hex or decoding failed
            return content
            
        except Exception as e:
            logger.warning(f"SMS content decode error: {e}")
            return content
            
    def _parse_sms_timestamp(self, timestamp_str: str) -> datetime:
        """Parse SMS timestamp string"""
        try:
            # Format: "yy/MM/dd,hh:mm:ss+tz"
            # Example: "25/07/17,14:30:45+01"
            
            # Remove timezone part for now
            ts_part = timestamp_str.split('+')[0].split('-')[0]
            
            # Parse date and time
            dt = datetime.strptime(ts_part, "%y/%m/%d,%H:%M:%S")
            
            # Adjust year (assuming 2000+ for years < 50)
            if dt.year < 1950:
                dt = dt.replace(year=dt.year + 100)
                
            return dt
            
        except Exception as e:
            logger.warning(f"Failed to parse SMS timestamp '{timestamp_str}': {e}")
            return datetime.now()
            
    def _save_message_to_db(self, sim_id: int, message: Dict) -> bool:
        """Save SMS message to database (consolidated messages only)"""
        try:
            sender = message.get('sender', 'Unknown')
            content = message.get('content', '')
            received_at = message.get('received_at', datetime.now())
            
            # Special logging for consolidated messages
            if 'fragment_indices' in message:
                fragment_count = len(message['fragment_indices'])
                logger.info(f"💾 CONSOLIDATED: Saving message from {fragment_count} fragments - Sender: {sender}")
                logger.debug(f"💾 Fragments used: {message['fragment_indices']}")
            else:
                logger.info(f"💾 SINGLE: Saving individual message - Sender: {sender}")
            
            with db.get_connection() as conn:
                cursor = conn.execute("""
                    INSERT INTO sms (sim_id, sender, message, received_at)
                    VALUES (?, ?, ?, ?)
                """, (
                    sim_id,
                    sender,
                    content,
                    received_at
                ))
                
                # Get the ID of the inserted message
                message_id = cursor.lastrowid
                conn.commit()
                
            logger.info(f"💾 ✅ SMS saved with ID {message_id}: {content[:50]}...")
            
            # Additional logging for Moblis messages
            if sender == '7711198105108105115':
                logger.info(f"🚨 MOBLIS MESSAGE SAVED: ID={message_id}, Length={len(content)} chars")
                logger.debug(f"🚨 MOBLIS Content: {content}")
            
            return True
            
        except Exception as e:
            logger.error(f"💾 ❌ Failed to save SMS to database: {e}")
            return False
            
    def _delete_message(self, ser: serial.Serial, message_index: int) -> bool:
        """Delete SMS message from SIM"""
        try:
            # Delete specific message
            command = f"AT+CMGD={message_index}"
            response = self._send_at_command_with_response(ser, command)
            
            if "OK" in response:
                return True
            else:
                logger.warning(f"Delete message failed: {response}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to delete message {message_index}: {e}")
            return False
            
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
            
    def _send_at_command_with_response(self, ser: serial.Serial, command: str, timeout: int = None) -> str:
        """Send AT command and return full response"""
        try:
            if timeout is None:
                timeout = self.at_timeout
                
            ser.write(f"{command}\r\n".encode())
            
            response = ""
            start_time = time.time()
            
            while time.time() - start_time < timeout:
                if ser.in_waiting > 0:
                    data = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
                    response += data
                    
                    # For CMGL commands, wait a bit more for complete response
                    if "CMGL" in command and "+CMGL:" in response:
                        time.sleep(1)  # Allow full response to come in
                        # Read any remaining data
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
            
    def _consolidate_message_fragments(self, messages: List[Dict]) -> List[Dict]:
        """Consolidate fragmented SMS messages into complete messages"""
        if not messages:
            return []
        
        try:
            # Group messages by sender and approximate time (within 2 minutes)
            from collections import defaultdict
            import re
            
            # First, normalize senders (decode hex if needed)
            for msg in messages:
                msg['normalized_sender'] = self._normalize_sender(msg['sender'])
                msg['time_group'] = self._get_time_group(msg.get('timestamp', ''))
            
            # Group by normalized sender and time group
            groups = defaultdict(list)
            for msg in messages:
                key = (msg['normalized_sender'], msg['time_group'])
                groups[key].append(msg)
            
            consolidated = []
            
            for (sender, time_group), group_messages in groups.items():
                if len(group_messages) == 1:
                    # Single message, use as-is
                    consolidated.append(group_messages[0])
                else:
                    # Multiple messages - check if they are REAL fragments
                    fragments = self._detect_real_fragments(group_messages)
                    
                    if len(fragments) > 1:
                        # REAL fragments detected - consolidate them
                        logger.info(f"🔗 Consolidating {len(fragments)} REAL fragments from {sender}")
                        
                        # Sort by fragment order or index
                        fragments.sort(key=lambda x: self._get_fragment_order(x))
                        
                        # Combine content intelligently
                        combined_content = self._combine_fragment_content(fragments)
                        combined_indices = [msg.get('index', 0) for msg in fragments]
                        
                        # Create consolidated message using first message as template
                        base_msg = fragments[0].copy()
                        base_msg['content'] = combined_content
                        # IMPORTANT: Use ORIGINAL sender, not normalized (to preserve phone numbers)
                        base_msg['sender'] = fragments[0]['sender']  # Keep original sender
                        base_msg['index'] = combined_indices[0]  # Use first index for deletion
                        base_msg['fragment_indices'] = combined_indices  # Track all indices
                        
                        logger.info(f"📝 Consolidated message: {combined_content[:100]}...")
                        logger.info(f"📝 Original sender preserved: {fragments[0]['sender']}")
                        consolidated.append(base_msg)
                        
                        # Add any non-fragments as separate messages
                        non_fragments = [msg for msg in group_messages if msg not in fragments]
                        for msg in non_fragments:
                            logger.info(f"📨 Separate message from {sender}: {msg['content'][:50]}...")
                            consolidated.append(msg)
                    else:
                        # Not real fragments - treat as separate messages
                        logger.info(f"📨 {len(group_messages)} separate messages from {sender} (not fragments)")
                        for msg in group_messages:
                            logger.info(f"� Individual message: {msg['content'][:50]}...")
                            consolidated.append(msg)
            
            return consolidated
            
        except Exception as e:
            logger.error(f"Failed to consolidate fragments: {e}")
            # Return original messages if consolidation fails
            return messages
    
    def _normalize_sender(self, sender: str) -> str:
        """Normalize sender - decode hex if needed, but preserve phone numbers"""
        try:
            # IMPORTANT: Don't decode phone numbers that look normal
            # Check if sender looks like a phone number (digits with optional + and spaces)
            if re.match(r'^[\+\d\s\-\(\)]+$', sender) and len(sender.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')) >= 8:
                logger.debug(f"Sender looks like phone number, keeping as-is: {sender}")
                return sender
            
            # Check if sender is already readable text (not hex)
            if sender.isascii() and not re.match(r'^[0-9A-Fa-f]+$', sender):
                logger.debug(f"Sender is readable text, keeping as-is: {sender}")
                return sender
            
            # Only try hex decoding for very long hex-looking strings
            if re.match(r'^[0-9A-Fa-f]+$', sender) and len(sender) > 16:
                try:
                    # Try UTF-16 Big Endian decoding
                    if len(sender) % 4 == 0:  # Must be multiple of 4 for UTF-16
                        hex_bytes = bytes.fromhex(sender)
                        decoded = hex_bytes.decode('utf-16be', errors='ignore')
                        if decoded and decoded.isprintable() and len(decoded.strip()) > 0:
                            logger.debug(f"Decoded sender {sender} -> {decoded}")
                            return decoded.strip()
                except:
                    pass
                
                try:
                    # Try UTF-8 decoding
                    if len(sender) % 2 == 0:
                        hex_bytes = bytes.fromhex(sender)
                        decoded = hex_bytes.decode('utf-8', errors='ignore')
                        if decoded and decoded.isprintable() and len(decoded.strip()) > 0:
                            logger.debug(f"Decoded sender {sender} -> {decoded}")
                            return decoded.strip()
                except:
                    pass
            
            # Return original if no decoding worked or not needed
            return sender
            
        except Exception as e:
            logger.warning(f"Failed to normalize sender {sender}: {e}")
            return sender
    
    def _get_time_group(self, timestamp: str) -> str:
        """Get time group for grouping messages (rounded to 2-minute intervals)"""
        try:
            if not timestamp:
                return "unknown"
            
            # Parse timestamp and round to 2-minute intervals
            from datetime import datetime
            
            # Handle different timestamp formats
            dt = None
            for fmt in ['%y/%m/%d,%H:%M:%S', '%Y-%m-%d %H:%M:%S', '%d/%m/%y,%H:%M:%S']:
                try:
                    # Remove timezone info if present
                    clean_timestamp = timestamp.split('+')[0].split('-')[0]
                    dt = datetime.strptime(clean_timestamp, fmt)
                    break
                except:
                    continue
            
            if dt:
                # Round to 2-minute intervals
                minutes = (dt.minute // 2) * 2
                return f"{dt.year}-{dt.month:02d}-{dt.day:02d} {dt.hour:02d}:{minutes:02d}"
            
            return timestamp[:16] if len(timestamp) >= 16 else timestamp
            
        except Exception as e:
            logger.warning(f"Failed to parse timestamp {timestamp}: {e}")
            return "unknown"
    
    def _clean_fragment_content(self, content: str) -> str:
        """Clean fragment content - remove artifacts and normalize"""
        try:
            if not content:
                return ""
            
            # Remove common fragment artifacts
            content = content.strip()
            
            # Remove single characters that are likely artifacts
            if len(content) <= 2 and not content.isalnum():
                logger.debug(f"Skipping fragment artifact: '{content}'")
                return ""
            
            # Remove common SMS continuation markers
            content = re.sub(r'^[\.\s]*$', '', content)  # Just dots or spaces
            content = re.sub(r'^[0-9]+\.\s*', '', content)  # Leading numbers like "0. "
            
            return content.strip()
            
        except Exception as e:
            logger.warning(f"Failed to clean fragment content: {e}")
            return content
    
    def _detect_real_fragments(self, messages: List[Dict]) -> List[Dict]:
        """Detect which messages are REAL fragments of the same SMS"""
        if len(messages) <= 1:
            return messages
        
        try:
            import re
            
            # Get sender information
            sender = messages[0].get('normalized_sender', messages[0].get('sender', ''))
            original_sender = messages[0].get('sender', '')
            is_moblis = sender == '7711198105108105115' or original_sender == '7711198105108105115'
            
            logger.info(f"� Fragment Detection for {len(messages)} messages from {original_sender}")
            
            # Special handling for Moblis (more aggressive)
            if is_moblis:
                logger.info(f"🚨 MOBLIS Fragment Detection for {len(messages)} messages")
                moblis_fragments = self._detect_moblis_fragments(messages)
                if len(moblis_fragments) > 1:
                    logger.info(f"🔗 MOBLIS: Found {len(moblis_fragments)} fragments to consolidate")
                    return moblis_fragments
                else:
                    # Even if detection failed, for Moblis always try to consolidate multiple messages
                    # from same time period as they are likely fragments
                    if len(messages) > 1:
                        logger.info(f"🔗 MOBLIS: Forcing consolidation of {len(messages)} messages (fallback)")
                        return messages
            
            # ENHANCED: General fragment detection for ALL senders (not just Moblis)
            logger.info(f"🔍 GENERAL: Checking fragments for sender {original_sender}")
            
            # Method 1: Check for part indicators (1/2, 2/2, etc.)
            part_pattern = r'\b(\d+)\s*/\s*(\d+)\b'
            messages_with_parts = []
            
            for msg in messages:
                content = msg.get('content', '')
                match = re.search(part_pattern, content)
                if match:
                    part_num = int(match.group(1))
                    total_parts = int(match.group(2))
                    msg['part_number'] = part_num
                    msg['total_parts'] = total_parts
                    messages_with_parts.append(msg)
            
            if len(messages_with_parts) > 1:
                # Check if part numbers make sense
                total_parts = messages_with_parts[0].get('total_parts', 0)
                if all(m.get('total_parts') == total_parts for m in messages_with_parts):
                    part_numbers = [m.get('part_number', 0) for m in messages_with_parts]
                    if len(set(part_numbers)) == len(part_numbers):  # No duplicates
                        logger.info(f"🔍 Found {len(messages_with_parts)} messages with part indicators")
                        return messages_with_parts
            
            # Method 2: Check for content continuation patterns
            continuation_fragments = self._find_content_continuation(messages)
            if len(continuation_fragments) > 1:
                logger.info(f"🔍 Found {len(continuation_fragments)} messages with content continuation")
                return continuation_fragments
            
            # Method 3: Check for identical timestamps (exact same minute)
            exact_time_fragments = self._find_exact_time_fragments(messages)
            if len(exact_time_fragments) > 1:
                logger.info(f"🔍 Found {len(exact_time_fragments)} messages with similar timestamps")
                return exact_time_fragments
            
            # Method 4: ENHANCED - Check for very long total content (likely fragmented)
            total_content_length = sum(len(msg.get('content', '')) for msg in messages)
            if total_content_length > 300 and len(messages) > 1:  # Long content likely fragmented
                logger.info(f"🔍 Long content detected ({total_content_length} chars) - likely fragments")
                
                # Additional check: messages received within reasonable time (5 minutes)
                time_check_passed = self._check_reasonable_timeframe(messages, max_minutes=5)
                if time_check_passed:
                    logger.info(f"🔍 Messages within 5 minutes timeframe - consolidating as fragments")
                    return messages
            
            # Method 5: Check for short fragments that look like continuations
            short_fragments = self._find_short_fragments(messages)
            if len(short_fragments) > 1:
                logger.info(f"🔍 Found {len(short_fragments)} short messages that might be fragments")
                return short_fragments
            
            # If no clear fragments found, return empty list (treat as separate messages)
            logger.debug(f"🔍 No real fragments detected among {len(messages)} messages from {original_sender}")
            return []
            
        except Exception as e:
            logger.error(f"Error detecting real fragments: {e}")
            return []
    
    def _detect_moblis_fragments(self, messages: List[Dict]) -> List[Dict]:
        """Special fragment detection for Moblis messages (7711198105108105115)"""
        try:
            if len(messages) <= 1:
                return messages
            
            logger.info(f"🚨 MOBLIS: Analyzing {len(messages)} messages for fragment consolidation")
            
            # For Moblis, be more aggressive - check multiple indicators
            fragment_score = 0
            
            # Check if messages are received very close in time (within 60 seconds for Moblis)
            timestamps = []
            for msg in messages:
                received_at = msg.get('received_at')
                if received_at:
                    timestamps.append(received_at)
            
            if len(timestamps) == len(messages):
                # Check if all messages are within 60 seconds of each other
                time_diffs = []
                for i in range(1, len(timestamps)):
                    if isinstance(timestamps[i], datetime) and isinstance(timestamps[i-1], datetime):
                        diff = abs((timestamps[i] - timestamps[i-1]).total_seconds())
                        time_diffs.append(diff)
                
                if time_diffs and all(diff <= 60 for diff in time_diffs):
                    fragment_score += 3
                    logger.info(f"🕐 MOBLIS: All messages within 60 seconds - fragment score +3")
            
            # Check content patterns for fragmentation
            contents = [msg.get('content', '') for msg in messages]
            
            # Moblis fragment indicators:
            for i, content in enumerate(contents):
                content = content.strip()
                if not content:
                    continue
                
                # Check if starts with lowercase (likely continuation)
                if content and content[0].islower():
                    fragment_score += 1
                    logger.debug(f"MOBLIS fragment indicator: starts with lowercase: '{content[:20]}...'")
                
                # Check if ends without proper punctuation
                if content and content[-1] not in '.!?':
                    fragment_score += 1
                    logger.debug(f"MOBLIS fragment indicator: no ending punctuation: '...{content[-20:]}'")
                
                # Check for incomplete words or sentences
                if len(content) < 50 and not content.endswith(('.', '!', '?')):
                    fragment_score += 1
                    logger.debug(f"MOBLIS fragment indicator: short incomplete content: '{content}'")
            
            # Check for common Moblis keywords across all messages
            all_content = ' '.join(contents).lower()
            moblis_keywords = ['offre', 'internet', 'mo', 'contactez', 'gsm', 'gratuit', 'service', 'recharge', 'solde']
            keyword_count = sum(1 for keyword in moblis_keywords if keyword in all_content)
            
            if keyword_count >= 2:
                fragment_score += keyword_count
                logger.info(f"🔤 MOBLIS: Found {keyword_count} keywords - fragment score +{keyword_count}")
            
            # Lower threshold for Moblis - if we have any reasonable indicators, consolidate
            logger.info(f"🚨 MOBLIS: Total fragment score: {fragment_score}")
            
            if fragment_score >= 2:  # Lower threshold for Moblis
                logger.info(f"🔗 MOBLIS: Score {fragment_score} >= 2 - CONSOLIDATING {len(messages)} messages")
                return messages
            else:
                logger.info(f"🚫 MOBLIS: Score {fragment_score} < 2 - treating as separate messages")
                return []
            
        except Exception as e:
            logger.error(f"Error in Moblis fragment detection: {e}")
            # For Moblis, if detection fails but we have multiple messages, consolidate anyway
            if len(messages) > 1:
                logger.warning(f"🚨 MOBLIS: Detection failed, but consolidating {len(messages)} messages anyway")
                return messages
            return []

    def _combine_fragment_content(self, fragments: List[Dict]) -> str:
        """Intelligently combine content from message fragments"""
        try:
            if not fragments:
                return ""
            
            if len(fragments) == 1:
                return fragments[0].get('content', '')
            
            # Extract and clean content from each fragment
            contents = []
            for fragment in fragments:
                content = fragment.get('content', '').strip()
                if content:
                    # Clean fragment content
                    cleaned = self._clean_fragment_content(content)
                    if cleaned:
                        contents.append(cleaned)
            
            if not contents:
                return ""
            
            # Special handling for Moblis messages
            sender = fragments[0].get('normalized_sender', fragments[0].get('sender', ''))
            is_moblis = sender == '7711198105108105115'
            
            if is_moblis:
                return self._combine_moblis_fragments(contents)
            else:
                return self._combine_regular_fragments(contents)
                
        except Exception as e:
            logger.error(f"Error combining fragment content: {e}")
            # Fallback: just join with spaces
            return ' '.join(fragment.get('content', '') for fragment in fragments)
    
    def _combine_moblis_fragments(self, contents: List[str]) -> str:
        """Combine Moblis fragments with smart spacing"""
        try:
            if not contents:
                return ""
            
            if len(contents) == 1:
                return contents[0]
            
            combined = []
            
            for i, content in enumerate(contents):
                content = content.strip()
                if not content:
                    continue
                
                if i == 0:
                    # First fragment
                    combined.append(content)
                else:
                    prev_content = combined[-1] if combined else ""
                    
                    # Check if we need to add space
                    needs_space = True
                    
                    # No space if previous ends with space or current starts with punctuation
                    if prev_content.endswith(' ') or content.startswith(('.', ',', '!', '?', ':', ';')):
                        needs_space = False
                    
                    # No space if previous ends with hyphen and current starts with lowercase
                    if prev_content.endswith('-') and content and content[0].islower():
                        needs_space = False
                    
                    # No space if current starts with lowercase and looks like continuation
                    if content and content[0].islower() and not content.startswith(('et', 'ou', 'de', 'du', 'le', 'la', 'les')):
                        needs_space = False
                    
                    if needs_space:
                        combined.append(' ')
                    
                    combined.append(content)
            
            result = ''.join(combined)
            logger.debug(f"📝 MOBLIS combined: {result}")
            return result
            
        except Exception as e:
            logger.error(f"Error combining Moblis fragments: {e}")
            return ' '.join(contents)
    
    def _combine_regular_fragments(self, contents: List[str]) -> str:
        """Combine regular fragments with standard spacing"""
        try:
            if not contents:
                return ""
            
            # For regular fragments, just join with spaces
            # but remove excessive spacing
            combined = ' '.join(contents)
            
            # Clean up multiple spaces
            import re
            combined = re.sub(r'\s+', ' ', combined)
            
            return combined.strip()
            
        except Exception as e:
            logger.error(f"Error combining regular fragments: {e}")
            return ' '.join(contents)

    def _get_fragment_order(self, fragment: Dict) -> int:
        """Get the order of a fragment for sorting"""
        try:
            # Try to get part number if available
            part_num = fragment.get('part_number')
            if part_num is not None:
                return part_num
            
            # Otherwise use message index
            return fragment.get('index', 0)
            
        except Exception as e:
            logger.debug(f"Error getting fragment order: {e}")
            return 0

    def _find_content_continuation(self, messages: List[Dict]) -> List[Dict]:
        """Find messages that look like content continuation"""
        try:
            if len(messages) <= 1:
                return []
            
            continuation_messages = []
            
            for i, msg in enumerate(messages):
                content = msg.get('content', '').strip()
                if not content:
                    continue
                
                # Check if content starts with lowercase (likely continuation)
                if content and content[0].islower():
                    continuation_messages.append(msg)
                    continue
                
                # Check if content ends abruptly (no punctuation)
                if content and content[-1] not in '.!?':
                    continuation_messages.append(msg)
                    continue
                
                # Check if content is very short (likely fragment)
                if len(content) < 50:
                    continuation_messages.append(msg)
                    continue
            
            # If most messages look like continuations, return all
            if len(continuation_messages) >= len(messages) * 0.6:  # 60% threshold
                return messages
            
            return []
            
        except Exception as e:
            logger.error(f"Error finding content continuation: {e}")
            return []
    
    def _find_exact_time_fragments(self, messages: List[Dict]) -> List[Dict]:
        """Find messages with very close timestamps"""
        try:
            if len(messages) <= 1:
                return []
            
            # Check if messages are received within 2 minutes of each other
            timestamps = []
            for msg in messages:
                received_at = msg.get('received_at')
                if received_at and isinstance(received_at, datetime):
                    timestamps.append(received_at)
            
            if len(timestamps) < 2:
                return []
            
            # Sort by timestamp
            sorted_timestamps = sorted(timestamps)
            
            # Check if all messages are within 2 minutes of each other
            time_span = (sorted_timestamps[-1] - sorted_timestamps[0]).total_seconds()
            
            if time_span <= 120:  # 2 minutes
                logger.debug(f"Messages span {time_span} seconds - likely fragments")
                return messages
            
            return []
            
        except Exception as e:
            logger.error(f"Error finding exact time fragments: {e}")
            return []
    
    def _find_short_fragments(self, messages: List[Dict]) -> List[Dict]:
        """Find short messages that might be fragments"""
        try:
            if len(messages) <= 1:
                return []
            
            short_messages = []
            
            for msg in messages:
                content = msg.get('content', '').strip()
                # Consider messages under 80 characters as potentially short fragments
                if len(content) < 80:
                    short_messages.append(msg)
            
            # If most messages are short, they might be fragments
            if len(short_messages) >= len(messages) * 0.7:  # 70% threshold
                logger.debug(f"Found {len(short_messages)} short messages out of {len(messages)}")
                return messages
            
            return []
            
        except Exception as e:
            logger.error(f"Error finding short fragments: {e}")
            return []
    
    def _check_reasonable_timeframe(self, messages: List[Dict], max_minutes: int = 5) -> bool:
        """Check if messages are within a reasonable timeframe for fragments"""
        try:
            timestamps = []
            for msg in messages:
                received_at = msg.get('received_at')
                if received_at and isinstance(received_at, datetime):
                    timestamps.append(received_at)
            
            if len(timestamps) < 2:
                return True  # Single message or no timestamps
            
            # Sort by timestamp
            sorted_timestamps = sorted(timestamps)
            
            # Check if all messages are within max_minutes of each other
            time_span = (sorted_timestamps[-1] - sorted_timestamps[0]).total_seconds()
            max_seconds = max_minutes * 60
            
            return time_span <= max_seconds
            
        except Exception as e:
            logger.error(f"Error checking timeframe: {e}")
            return False

    # ...existing code...
    
    def get_stats(self) -> Dict:
        """Get polling statistics"""
        return self.stats.copy()
        
    def get_status(self) -> Dict:
        """Get current polling status"""
        return {
            'active': self.polling_active,
            'total_sims': len(self.active_sims),
            'current_sim_index': self.current_sim_index,
            'stats': self.get_stats()
        }

# Global SMS poller instance
sms_poller = SMSPoller()
