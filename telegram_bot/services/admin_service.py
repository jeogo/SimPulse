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
