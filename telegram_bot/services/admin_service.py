"""
Admin Service
Handles admin notifications and operations
"""

import logging
from datetime import datetime
from typing import List, Dict

import core.config as config
from core.database import db
from core.group_manager import group_manager
from telegram_bot.messages import *

logger = logging.getLogger(__name__)

class AdminService:
    """Service for admin operations"""
    
    def __init__(self, bot_instance):
        self.bot = bot_instance
    
    async def notify_new_user(self, user_id: int, name: str, phone: str):
        """Send notification to all admins about new user"""
        if not config.ADMIN_TELEGRAM_IDS:
            logger.warning("No admin IDs configured")
            return
        
        message = NEW_USER_NOTIFICATION.format(
            name=name,
            phone=phone,
            telegram_id=user_id,
            registration_date=datetime.now().strftime("%Y-%m-%d %H:%M")
        )
        
        for admin_id in config.ADMIN_TELEGRAM_IDS:
            try:
                await self.bot.application.bot.send_message(
                    chat_id=admin_id,
                    text=message
                )
                logger.info(f"Notified admin {admin_id} about new user {user_id}")
            except Exception as e:
                logger.error(f"Failed to notify admin {admin_id}: {e}")
    
    async def notify_verification_result(self, user_data: Dict, verification_data: Dict):
        """Notify admins about verification result"""
        if not config.ADMIN_TELEGRAM_IDS:
            return
        
        admin_message = VERIFICATION_ADMIN_NOTIFICATION.format(
            user_name=user_data['full_name'],
            amount=verification_data['amount'],
            date=verification_data['date'],
            time=verification_data['time'],
            sim_number=verification_data.get('sim_number', 'غير متصل'),
            result=verification_data['result'],
            details=verification_data.get('details', '')
        )
        
        for admin_id in config.ADMIN_TELEGRAM_IDS:
            try:
                await self.bot.application.bot.send_message(admin_id, admin_message)
            except Exception as e:
                logger.error(f"Failed to notify admin {admin_id}: {e}")
    
    def get_pending_users(self) -> List[Dict]:
        """Get all pending users"""
        return db.get_pending_telegram_users()
    
    def get_approved_users(self) -> List[Dict]:
        """Get all approved users"""
        return db.get_approved_telegram_users()
    
    def get_rejected_users(self) -> List[Dict]:
        """Get all rejected users"""
        return db.get_rejected_telegram_users()
    
    def get_all_users(self) -> List[Dict]:
        """Get all users"""
        return db.get_all_telegram_users()
    
    def get_all_groups(self) -> List[Dict]:
        """Get all groups"""
        return group_manager.get_all_groups()
    
    async def approve_user(self, telegram_id: int) -> Dict:
        """Approve user and assign to group"""
        try:
            user_data = db.get_telegram_user_by_id(telegram_id)
            if not user_data:
                return {"success": False, "message": "المستخدم غير موجود"}
            
            if user_data['status'] != 'pending':
                return {"success": False, "message": f"حالة المستخدم: {user_data['status']}"}
            
            # Get available groups
            groups = group_manager.get_all_groups()
            if not groups:
                return {"success": False, "message": "لا توجد مجموعات متاحة"}
            
            # Assign to first available group
            group_id = groups[0]['id']
            
            # Update user status
            success = db.update_telegram_user_status(telegram_id, 'approved', group_id)
            
            if success:
                # Get group and SIM info
                group_info = group_manager.get_group_with_modem_info(group_id)
                sim_phone = group_info.get('phone_number', 'غير متصل')
                current_balance = group_info.get('balance', '0.00')
                
                # Notify user
                await self.bot.application.bot.send_message(
                    chat_id=telegram_id,
                    text=USER_APPROVED_NOTIFICATION.format(
                        group_name=groups[0]['group_name'],
                        sim_number=sim_phone,
                        current_balance=current_balance
                    )
                )
                
                return {
                    "success": True, 
                    "message": f"تم قبول المستخدم {user_data['full_name']}",
                    "user_name": user_data['full_name']
                }
            else:
                return {"success": False, "message": "فشل في قبول المستخدم"}
                
        except Exception as e:
            logger.error(f"Error approving user: {e}")
            return {"success": False, "message": f"خطأ: {str(e)}"}
    
    async def reject_user(self, telegram_id: int) -> Dict:
        """Reject user"""
        try:
            user_data = db.get_telegram_user_by_id(telegram_id)
            if not user_data:
                return {"success": False, "message": "المستخدم غير موجود"}
            
            # Update user status
            success = db.update_telegram_user_status(telegram_id, 'rejected')
            
            if success:
                # Notify user
                await self.bot.application.bot.send_message(
                    chat_id=telegram_id,
                    text=USER_REJECTED_NOTIFICATION
                )
                
                return {
                    "success": True, 
                    "message": f"تم رفض المستخدم {user_data['full_name']}",
                    "user_name": user_data['full_name']
                }
            else:
                return {"success": False, "message": "فشل في رفض المستخدم"}
                
        except Exception as e:
            logger.error(f"Error rejecting user: {e}")
            return {"success": False, "message": f"خطأ: {str(e)}"}

    async def notify_sim_swap(self, group_name: str, imei: str, old_sim_number: str, 
                             new_sim_number: str, old_balance: str, new_balance: str) -> bool:
        """
        إرسال إشعار تغيير الشريحة لجميع مستخدمي المجموعة والإداريين
        """
        try:
            from datetime import datetime
            from telegram_bot.messages import SIM_SWAP_NOTIFICATION_USERS, SIM_SWAP_NOTIFICATION_ADMIN
            
            current_time = datetime.now()
            change_date = current_time.strftime("%Y-%m-%d")
            change_time = current_time.strftime("%H:%M:%S")
            
            # الحصول على مستخدمي المجموعة
            group_users = db.get_group_users(group_name)
            user_count = len(group_users) if group_users else 0
            
            # إرسال إشعار لمستخدمي المجموعة
            users_message = SIM_SWAP_NOTIFICATION_USERS.format(
                group_name=group_name,
                new_sim_number=new_sim_number,
                new_balance=new_balance,
                change_date=change_date,
                change_time=change_time
            )
            
            if group_users:
                for user in group_users:
                    try:
                        await self.bot.application.bot.send_message(
                            chat_id=user['telegram_id'],
                            text=users_message,
                            parse_mode='HTML'
                        )
                        logger.info(f"تم إرسال إشعار تغيير الشريحة للمستخدم {user['telegram_id']}")
                    except Exception as e:
                        logger.error(f"فشل في إرسال إشعار تغيير الشريحة للمستخدم {user['telegram_id']}: {e}")
            
            # إرسال إشعار للإداريين
            admin_message = SIM_SWAP_NOTIFICATION_ADMIN.format(
                group_name=group_name,
                new_sim_number=new_sim_number,
                new_balance=new_balance,
                change_date=change_date,
                change_time=change_time
            )
            
            # إرسال للإداريين من config.py
            if config.ADMIN_TELEGRAM_IDS:
                for admin_id in config.ADMIN_TELEGRAM_IDS:
                    try:
                        await self.bot.application.bot.send_message(
                            chat_id=admin_id,
                            text=admin_message,
                            parse_mode='HTML'
                        )
                        logger.info(f"تم إرسال إشعار تغيير الشريحة للإداري {admin_id}")
                    except Exception as e:
                        logger.error(f"فشل في إرسال إشعار تغيير الشريحة للإداري {admin_id}: {e}")
            else:
                logger.warning("No admin IDs configured in config.ADMIN_TELEGRAM_IDS")
            
            logger.info(f"تم إرسال إشعار تغيير الشريحة بنجاح للمجموعة {group_name}")
            return True
            
        except Exception as e:
            logger.error(f"فشل في إرسال إشعار تغيير الشريحة: {e}")
            return False
    
    async def notify_sms_processed(self, sms_data: Dict) -> bool:
        """
        إرسال إشعار للإداريين عن معالجة رسالة SMS جديدة
        """
        try:
            if not config.ADMIN_TELEGRAM_IDS:
                logger.warning("No admin IDs configured for SMS notifications")
                return False
            
            from telegram_bot.messages import SMS_ADMIN_NOTIFICATION, SMS_TYPE_RECHARGE, SMS_TYPE_BALANCE, SMS_TYPE_REGULAR, SMS_FRAGMENT_INFO
            
            # Determine SMS type
            sender = sms_data.get('sender', 'غير معروف')
            content = sms_data.get('content', '')
            
            sms_type = SMS_TYPE_REGULAR
            if sender == '7711198105108105115':  # Moblis recharge
                if any(keyword in content.lower() for keyword in ['rechargé', 'recharge', 'شحن']):
                    sms_type = SMS_TYPE_RECHARGE
            elif any(keyword in content.lower() for keyword in ['solde', 'balance', 'رصيد']):
                sms_type = SMS_TYPE_BALANCE
            
            # Fragment info
            fragment_info = ""
            fragment_count = sms_data.get('fragment_count', 0)
            if fragment_count > 1:
                fragment_info = SMS_FRAGMENT_INFO.format(fragment_count=fragment_count)
            
            # Content preview (limit to 200 characters)
            content_preview = content[:200] + "..." if len(content) > 200 else content
            
            # Format timestamp
            timestamp = sms_data.get('timestamp', 'غير محدد')
            if hasattr(timestamp, 'strftime'):
                timestamp = timestamp.strftime("%Y-%m-%d %H:%M:%S")
            
            # Format notification message
            notification_message = SMS_ADMIN_NOTIFICATION.format(
                sim_number=sms_data.get('sim_number', 'غير معروف'),
                sender=sender,
                timestamp=timestamp,
                group_name=sms_data.get('group_name', 'غير محدد'),
                content=content_preview,
                sms_type=sms_type,
                fragment_info=fragment_info
            )
            
            # Send to all admins
            sent_count = 0
            for admin_id in config.ADMIN_TELEGRAM_IDS:
                try:
                    await self.bot.application.bot.send_message(
                        chat_id=admin_id,
                        text=notification_message
                    )
                    sent_count += 1
                    logger.debug(f"SMS notification sent to admin {admin_id}")
                except Exception as e:
                    logger.error(f"Failed to send SMS notification to admin {admin_id}: {e}")
            
            if sent_count > 0:
                logger.info(f"SMS notification sent to {sent_count} admins - Sender: {sender}")
                return True
            else:
                logger.warning("Failed to send SMS notification to any admin")
                return False
                
        except Exception as e:
            logger.error(f"Error sending SMS notification: {e}")
            return False
    
    async def notify_balance_limit_reached(self, balance_data: Dict) -> bool:
        """
        إرسال إشعار وصول الرصيد للحد المطلوب للمستخدمين والإداريين
        """
        try:
            from datetime import datetime
            from telegram_bot.messages import BALANCE_LIMIT_USER_NOTIFICATION, BALANCE_LIMIT_ADMIN_NOTIFICATION
            
            logger.info(f"Processing balance limit notification with data: {balance_data}")
            
            sim_number = balance_data.get('sim_number', 'غير معروف')
            current_balance = balance_data.get('current_balance', '0.00')
            limit = balance_data.get('limit', '45000.00')
            group_name = balance_data.get('group_name', 'غير محدد')
            group_id = balance_data.get('group_id')
            
            current_time = datetime.now()
            timestamp = current_time.strftime("%Y-%m-%d %H:%M:%S")
            
            logger.info(f"Sending balance limit notification for SIM {sim_number} - Balance: {current_balance}")
            
            user_notification_sent = 0
            admin_notification_sent = 0
            
            # إرسال إشعار لمستخدمي المجموعة
            if group_id:
                logger.info(f"Looking for users in group ID: {group_id}")
                group_users = db.get_group_users_by_group_id(group_id)
                user_count = len(group_users) if group_users else 0
                logger.info(f"Found {user_count} users in group {group_name}")
                
                user_message = BALANCE_LIMIT_USER_NOTIFICATION.format(
                    sim_number=sim_number,
                    current_balance=current_balance,
                    limit=limit
                )
                
                if group_users:
                    for user in group_users:
                        try:
                            await self.bot.application.bot.send_message(
                                chat_id=user['telegram_id'],
                                text=user_message
                            )
                            user_notification_sent += 1
                            logger.info(f"Balance limit notification sent to user {user['telegram_id']}")
                        except Exception as e:
                            logger.error(f"Failed to send balance limit notification to user {user['telegram_id']}: {e}")
                else:
                    logger.warning(f"No users found for group {group_name} (ID: {group_id})")
            else:
                logger.warning(f"No group_id provided for balance limit notification")
            
            # إرسال إشعار للإداريين
            admin_message = BALANCE_LIMIT_ADMIN_NOTIFICATION.format(
                group_name=group_name,
                sim_number=sim_number,
                current_balance=current_balance,
                limit=limit,
                timestamp=timestamp
            )
            
            logger.info(f"Sending admin notification to {len(config.ADMIN_TELEGRAM_IDS) if config.ADMIN_TELEGRAM_IDS else 0} admins")
            
            if config.ADMIN_TELEGRAM_IDS:
                for admin_id in config.ADMIN_TELEGRAM_IDS:
                    try:
                        await self.bot.application.bot.send_message(
                            chat_id=admin_id,
                            text=admin_message
                        )
                        admin_notification_sent += 1
                        logger.info(f"Balance limit notification sent to admin {admin_id}")
                    except Exception as e:
                        logger.error(f"Failed to send balance limit notification to admin {admin_id}: {e}")
                
                logger.info(f"Admin notifications sent: {admin_notification_sent}/{len(config.ADMIN_TELEGRAM_IDS)}")
            else:
                logger.warning("No admin IDs configured for balance limit notifications")
            
            total_sent = user_notification_sent + admin_notification_sent
            logger.info(f"Balance limit notification completed - Users: {user_notification_sent}, Admins: {admin_notification_sent}, Total: {total_sent}")
            
            return total_sent > 0
            
        except Exception as e:
            logger.error(f"Error sending balance limit notification: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False
