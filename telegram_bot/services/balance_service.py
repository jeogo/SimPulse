"""
Balance Service
Handles balance checking for users and admin groups
"""

import logging
from typing import Dict, Optional
from datetime import datetime

from core.database import db
from core.balance_checker import balance_checker
from telegram_bot.messages import *

logger = logging.getLogger(__name__)

class BalanceService:
    """خدمة فحص الرصيد للمستخدمين والإداريين"""
    
    def __init__(self):
        self.balance_checker = balance_checker
    
    async def check_user_balance(self, telegram_user_id: int) -> Dict:
        """فحص رصيد المستخدم"""
        try:
            logger.info(f"🔍 Checking balance for user {telegram_user_id}")
            
            # Get user's SIM info
            sim_info = db.get_user_sim_by_telegram_id(telegram_user_id)
            if not sim_info:
                logger.warning(f"No SIM found for user {telegram_user_id}")
                return {
                    'success': False,
                    'message': BALANCE_CHECK_NO_SIM
                }
            
            logger.info(f"📱 Found SIM for user: {sim_info['phone_number']}")
            
            # Get live balance from modem
            balance = await self._get_live_balance(sim_info)
            if balance is None:
                logger.error(f"Failed to get live balance for SIM {sim_info['id']}")
                return {
                    'success': False,
                    'message': BALANCE_CHECK_FAILED
                }
            
            logger.info(f"💰 Balance retrieved: {balance} DZD")
            
            # Format response
            check_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            return {
                'success': True,
                'data': {
                    'sim_number': sim_info['phone_number'],
                    'balance': balance,
                    'check_time': check_time
                }
            }
            
        except Exception as e:
            logger.error(f"Error in check_user_balance: {e}")
            return {
                'success': False,
                'message': BALANCE_CHECK_FAILED
            }
    
    async def check_group_balance(self, group_id: int) -> Dict:
        """فحص رصيد مجموعة معينة"""
        try:
            logger.info(f"🔍 Checking balance for group {group_id}")
            
            # Get group info with SIM details
            from core.group_manager import group_manager
            groups = group_manager.get_all_groups()
            group = next((g for g in groups if g['id'] == group_id), None)
            
            if not group:
                logger.error(f"Group {group_id} not found")
                return {
                    'success': False,
                    'message': "❌ لم يتم العثور على المجموعة"
                }
            
            # Get SIM info for this group
            sim_info = self._get_group_sim_info(group)
            if not sim_info:
                logger.error(f"No SIM info found for group {group_id}")
                return {
                    'success': False,
                    'message': "❌ لا توجد شريحة مرتبطة بهذه المجموعة"
                }
            
            logger.info(f"📱 Found SIM for group: {sim_info['phone_number']}")
            
            # Get live balance from modem
            balance = await self._get_live_balance(sim_info)
            if balance is None:
                logger.error(f"Failed to get live balance for group SIM")
                return {
                    'success': False,
                    'message': BALANCE_CHECK_FAILED
                }
            
            logger.info(f"💰 Group balance retrieved: {balance} DZD")
            
            # Format response
            check_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            return {
                'success': True,
                'data': {
                    'sim_number': sim_info['phone_number'],
                    'balance': balance,
                    'check_time': check_time
                }
            }
            
        except Exception as e:
            logger.error(f"Error in check_group_balance: {e}")
            return {
                'success': False,
                'message': BALANCE_CHECK_FAILED
            }
    
    async def _get_live_balance(self, sim_info: Dict) -> Optional[str]:
        """الحصول على الرصيد المباشر من المودم وتحديث قاعدة البيانات"""
        try:
            sim_id = sim_info.get('id')
            if not sim_id:
                logger.error(f"❌ SIM ID is missing from sim_info: {sim_info}")
                # Try to get SIM ID from phone number if available
                phone_number = sim_info.get('phone_number')
                if phone_number:
                    # Find SIM by phone number
                    try:
                        with db.get_connection() as conn:
                            cursor = conn.execute(
                                "SELECT id FROM sims WHERE phone_number = ? AND status = 'active'",
                                (phone_number,)
                            )
                            row = cursor.fetchone()
                            if row:
                                sim_id = row[0]
                                sim_info['id'] = sim_id  # Update sim_info with found ID
                                logger.info(f"✅ Found SIM ID {sim_id} for phone {phone_number}")
                            else:
                                logger.error(f"❌ No active SIM found for phone {phone_number}")
                                return None
                    except Exception as e:
                        logger.error(f"❌ Error finding SIM ID by phone: {e}")
                        return None
                else:
                    logger.error(f"❌ No phone number available to find SIM ID")
                    return None
            
            logger.info(f"📞 Extracting live balance for SIM {sim_id}")
            
            # Get current balance from database for comparison
            old_balance = db.get_current_balance(sim_id)
            logger.info(f"📊 Current database balance: {old_balance}")
            
            # Prepare SIM info for balance checker
            balance_sim_info = {
                'id': sim_id,
                'phone_number': sim_info['phone_number'],
                'imei': sim_info.get('imei'),
                'port': None
            }
            
            # Get port from modem detector
            from core.modem_detector import modem_detector
            imei = balance_sim_info['imei']
            
            if imei and imei in modem_detector.known_modems:
                port_info = modem_detector.known_modems[imei]
                if isinstance(port_info, dict):
                    balance_sim_info['port'] = port_info.get('port')
                else:
                    # Handle case where port_info might be a string
                    balance_sim_info['port'] = port_info
                logger.info(f"🔌 Found port for IMEI {imei[-6:] if imei else 'Unknown'}: {balance_sim_info['port']}")
            else:
                logger.warning(f"⚠️ Port not found for IMEI {imei if imei else 'Unknown'}, will use database balance")
                # Fallback to database balance if no port available
                return db.get_current_balance(sim_id)
            
            # ===== PRIORITY: LIVE SMS CHECK OVER USSD =====
            # First try to get the most recent balance SMS to ensure we have the latest real balance
            logger.info(f"🔍 Checking for recent balance SMS updates for SIM {sim_id}")
            
            # Check for recent balance SMS messages from the last 5 minutes
            from datetime import datetime, timedelta
            recent_time = datetime.now() - timedelta(minutes=5)
            
            # Get recent SMS messages that might contain balance info
            try:
                with db.get_connection() as conn:
                    cursor = conn.execute("""
                        SELECT message, sender, received_at FROM sms 
                        WHERE sim_id = ? AND received_at >= ? 
                        ORDER BY received_at DESC LIMIT 10
                    """, (sim_id, recent_time))
                    recent_sms = cursor.fetchall()
                
                # Check if any recent SMS contains balance information
                for sms_row in recent_sms:
                    sms_content = sms_row[0]
                    sender = sms_row[1]
                    
                    # Use balance checker to detect if this SMS contains balance
                    balance_sms_result = self.balance_checker.detect_balance_sms(sms_content, sender)
                    if balance_sms_result and balance_sms_result.get('is_balance_sms'):
                        sms_balance = balance_sms_result.get('balance')
                        logger.info(f"📱 Found recent balance SMS with balance: {sms_balance}")
                        
                        # Update database with SMS balance if it's different from current
                        old_amount = self.balance_checker._parse_balance_amount(old_balance)
                        sms_amount = self.balance_checker._parse_balance_amount(sms_balance)
                        
                        if abs(sms_amount - old_amount) > 0.01:  # Only update if there's a meaningful difference
                            logger.info(f"📲 Updating database with SMS balance: {old_balance} → {sms_balance}")
                            await self._update_balance_in_database(
                                sim_id, old_balance, sms_balance, 'sms_balance_update'
                            )
                            return sms_balance
                        else:
                            logger.info(f"📲 SMS balance matches database, no update needed")
                            return sms_balance
            except Exception as e:
                logger.warning(f"Could not check recent SMS: {e}")
            
            # If no recent SMS balance found, proceed with USSD check
            logger.info(f"📞 No recent SMS balance found, proceeding with USSD check")
            
            # Use balance checker to get live balance via USSD
            result = self.balance_checker._extract_live_balance_enhanced(balance_sim_info)
            
            new_balance = None
            balance_updated = False
            
            if result:
                if result.get('is_sbc_response'):
                    # SBC response - balance will come via SMS, use current database balance
                    logger.info("📱 SBC response detected, balance will be updated via SMS later")
                    # Store pending request for future SMS processing
                    self.balance_checker.pending_balance_requests[sim_id] = {
                        'timestamp': datetime.now(),
                        'recharge_info': {
                            'is_critical': False,
                            'amount': '0.00',
                            'sender': 'balance_service',
                            'content': 'Live balance check via SBC'
                        }
                    }
                    new_balance = db.get_current_balance(sim_id)
                else:
                    # Direct balance from USSD
                    live_balance = result.get('balance')
                    if live_balance:
                        logger.info(f"✅ Live balance extracted via USSD: {live_balance}")
                        new_balance = live_balance
                        
                        # Always update database with live USSD balance (this is the real current balance)
                        logger.info(f"💾 Updating database with live USSD balance")
                        await self._update_balance_in_database(
                            sim_id, old_balance, new_balance, 'live_ussd_check'
                        )
                        balance_updated = True
            
            if not new_balance:
                # Fallback to database balance
                logger.warning("⚠️ Failed to get live balance, using database balance")
                new_balance = db.get_current_balance(sim_id)
            
            # Log the operation
            if balance_updated:
                logger.info(f"💾 Balance updated in database: {old_balance} → {new_balance}")
            else:
                logger.info(f"📋 Using existing database balance: {new_balance}")
                
            return new_balance
            
        except Exception as e:
            logger.error(f"Error getting live balance: {e}")
            # Fallback to database balance if we have a sim_id
            try:
                sim_id = sim_info.get('id')
                if sim_id:
                    return db.get_current_balance(sim_id)
                else:
                    logger.error("No SIM ID available for fallback balance lookup")
                    return "0.00"  # Return default balance if no SIM ID
            except:
                return "0.00"  # Final fallback
    
    async def _update_balance_in_database(self, sim_id: int, old_balance: str, new_balance: str, change_type: str):
        """تحديث الرصيد في قاعدة البيانات مع التتبع والإشعارات"""
        try:
            logger.info(f"💾 Updating balance in database for SIM {sim_id}")
            
            # Calculate balance change
            old_amount = self.balance_checker._parse_balance_amount(old_balance)
            new_amount = self.balance_checker._parse_balance_amount(new_balance)
            change_amount = new_amount - old_amount
            
            # Update SIM balance in database
            db.update_sim_info(sim_id, balance=new_balance)
            logger.info(f"✅ SIM {sim_id} balance updated: {old_balance} → {new_balance}")
            
            # Add balance history record
            db.add_balance_history(
                sim_id=sim_id,
                old_balance=old_balance,
                new_balance=new_balance,
                change_amount=f"{change_amount:+.2f}",
                change_type=change_type,
                detected_from_sms=False,
                sms_sender='live_balance_service',
                sms_content=f"Live balance check via Telegram bot - {change_type}"
            )
            logger.info(f"📝 Balance history recorded for SIM {sim_id}")
            
            # Check if balance limit is reached and send notification
            if self.balance_checker._check_balance_limit(sim_id, new_balance):
                logger.info(f"🚨 Balance limit reached for SIM {sim_id} during live check, sending notification...")
                self.balance_checker._notify_balance_limit_reached(sim_id, new_balance)
            
            logger.info(f"✅ Balance update completed for SIM {sim_id}")
            
        except Exception as e:
            logger.error(f"Error updating balance in database for SIM {sim_id}: {e}")
            # Don't raise the exception to avoid breaking the balance check
    
    async def check_and_update_balance_after_recharge(self, sim_id: int, expected_recharge_amount: str = None) -> Dict:
        """فحص وتحديث الرصيد بعد تعبئة الرصيد"""
        try:
            logger.info(f"🔄 Checking balance after recharge for SIM {sim_id}")
            
            # Get SIM info
            sim_info = db.get_sim_by_id(sim_id)
            if not sim_info:
                logger.error(f"SIM {sim_id} not found")
                return {
                    'success': False,
                    'message': "SIM not found"
                }
            
            # Get current balance from database
            old_balance = db.get_current_balance(sim_id)
            logger.info(f"📊 Balance before recharge check: {old_balance}")
            
            # Prepare SIM info for balance checker
            balance_sim_info = {
                'id': sim_id,
                'phone_number': sim_info['phone_number'],
                'imei': sim_info.get('imei'),
                'port': None
            }
            
            # Get port from modem detector
            from core.modem_detector import modem_detector
            imei = balance_sim_info['imei']
            
            if imei and imei in modem_detector.known_modems:
                port_info = modem_detector.known_modems[imei]
                if isinstance(port_info, dict):
                    balance_sim_info['port'] = port_info.get('port')
                else:
                    # Handle case where port_info might be a string
                    balance_sim_info['port'] = port_info
                logger.info(f"🔌 Found port for recharge check: {balance_sim_info['port']}")
            else:
                logger.warning(f"⚠️ Port not found for recharge check")
                return {
                    'success': False,
                    'message': "Port not available for balance check"
                }
            
            # Wait a bit for telecom system to process recharge
            import asyncio
            await asyncio.sleep(5)
            
            # Get live balance
            result = self.balance_checker._extract_live_balance_enhanced(balance_sim_info)
            
            if result and not result.get('is_sbc_response'):
                new_balance = result.get('balance')
                if new_balance:
                    # Update database with new balance
                    change_type = 'post_recharge_check'
                    if expected_recharge_amount:
                        change_type = f'post_recharge_check_{expected_recharge_amount}DZD'
                    
                    await self._update_balance_in_database(
                        sim_id, old_balance, new_balance, change_type
                    )
                    
                    return {
                        'success': True,
                        'old_balance': old_balance,
                        'new_balance': new_balance,
                        'change_amount': self.balance_checker._parse_balance_amount(new_balance) - self.balance_checker._parse_balance_amount(old_balance)
                    }
            
            logger.warning(f"Failed to get updated balance after recharge for SIM {sim_id}")
            return {
                'success': False,
                'message': "Failed to check balance after recharge"
            }
            
        except Exception as e:
            logger.error(f"Error checking balance after recharge for SIM {sim_id}: {e}")
            return {
                'success': False,
                'message': f"Error: {str(e)}"
            }
    
    def _get_group_sim_info(self, group: Dict) -> Optional[Dict]:
        """الحصول على معلومات الشريحة للمجموعة"""
        try:
            # Group should have SIM information - now includes sim_id from updated query
            sim_id = group.get('sim_id')
            if not sim_id:
                logger.error(f"No SIM ID found in group data: {group}")
                return None
                
            return {
                'id': sim_id,  # This is the actual SIM ID from the database
                'phone_number': group.get('phone_number'),
                'imei': group.get('imei'),
                'balance': group.get('balance', '0.00')  # Include current balance
            }
        except Exception as e:
            logger.error(f"Error getting group SIM info: {e}")
            return None

    async def force_live_balance_update(self, sim_id: int) -> Dict:
        """إجبار فحص الرصيد المباشر وتحديث قاعدة البيانات - قوي ومتين"""
        try:
            logger.info(f"🔥 FORCE: Live balance update for SIM {sim_id}")
            
            # Get SIM info
            sim_info = db.get_sim_by_id(sim_id)
            if not sim_info:
                logger.error(f"SIM {sim_id} not found")
                return {
                    'success': False,
                    'message': "SIM not found"
                }
            
            # Get current balance from database
            old_balance = db.get_current_balance(sim_id)
            logger.info(f"📊 Current database balance: {old_balance}")
            
            # Prepare SIM info for balance checker
            balance_sim_info = {
                'id': sim_id,
                'phone_number': sim_info['phone_number'],
                'imei': sim_info.get('imei'),
                'port': None
            }
            
            # Get port from modem detector
            from core.modem_detector import modem_detector
            imei = balance_sim_info['imei']
            
            if imei and imei in modem_detector.known_modems:
                port_info = modem_detector.known_modems[imei]
                if isinstance(port_info, dict):
                    balance_sim_info['port'] = port_info.get('port')
                else:
                    balance_sim_info['port'] = port_info
                logger.info(f"🔌 Found port for FORCE check: {balance_sim_info['port']}")
            else:
                logger.error(f"❌ Port not found for FORCE check")
                return {
                    'success': False,
                    'message': "Port not available"
                }
            
            # Get live balance via USSD
            logger.info(f"📞 FORCE: Extracting live balance via USSD")
            result = self.balance_checker._extract_live_balance_enhanced(balance_sim_info)
            
            if result:
                if result.get('is_sbc_response'):
                    logger.info(f"📱 FORCE: SBC response - will wait for SMS")
                    return {
                        'success': True,
                        'message': "SBC response - balance will be updated via SMS",
                        'balance_type': 'sbc_pending'
                    }
                else:
                    # Direct balance from USSD
                    live_balance = result.get('balance')
                    if live_balance:
                        logger.info(f"✅ FORCE: Live balance retrieved: {live_balance}")
                        
                        # ALWAYS update database with live balance - this is the real current balance
                        await self._update_balance_in_database(
                            sim_id, old_balance, live_balance, 'force_live_update'
                        )
                        
                        return {
                            'success': True,
                            'old_balance': old_balance,
                            'new_balance': live_balance,
                            'balance_type': 'ussd_direct',
                            'change_amount': self.balance_checker._parse_balance_amount(live_balance) - self.balance_checker._parse_balance_amount(old_balance)
                        }
            
            logger.error(f"❌ FORCE: Failed to get live balance")
            return {
                'success': False,
                'message': "Failed to get live balance"
            }
            
        except Exception as e:
            logger.error(f"Error in force_live_balance_update for SIM {sim_id}: {e}")
            return {
                'success': False,
                'message': f"Error: {str(e)}"
            }

# Global balance service instance
balance_service = BalanceService()
