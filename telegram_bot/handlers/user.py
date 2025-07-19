"""
User Handlers
Handles user-specific operations like profile, main menu, etc.
"""

import logging
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ContextTypes

from core.database import db
from telegram_bot.messages import *

logger = logging.getLogger(__name__)

class UserHandlers:
    """Handles user operations"""
    
    def __init__(self, bot_instance):
        self.bot = bot_instance
    
    async def show_main_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show main menu for approved users"""
        keyboard = [[button] for button in MAIN_MENU_BUTTONS]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            MAIN_MENU,
            reply_markup=reply_markup
        )
    
    async def show_profile(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show user profile information"""
        user_id = update.effective_user.id
        user_data = db.get_telegram_user_by_id(user_id)
        
        if not user_data:
            await update.message.reply_text(ERROR_NOT_REGISTERED)
            return
        
        # Get SIM info if available
        sim_info = db.get_user_sim_by_telegram_id(user_id)
        
        profile_text = PROFILE_INFO.format(
            name=user_data['full_name'],
            phone=user_data['phone_number'],
            group_name=sim_info['group_name'] if sim_info else "غير محدد",
            sim_number=sim_info['phone_number'] if sim_info else "غير متصل",
            verified_balance=user_data.get('verified_balance', 0.0),
            registration_date=user_data['created_at'][:10],
            last_verification="لم يتم بعد",
            status="معتمد" if user_data['status'] == 'approved' else user_data['status']
        )
        
        await update.message.reply_text(profile_text)
    
    async def show_contact_admin(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show contact admin message"""
        await update.message.reply_text(CONTACT_ADMIN_MESSAGE)
        # TODO: Implement contact admin functionality
    
    def is_user_approved(self, user_id: int) -> bool:
        """Check if user is approved"""
        user_data = db.get_telegram_user_by_id(user_id)
        return user_data and user_data['status'] == 'approved'
    
    def is_user_registered(self, user_id: int) -> bool:
        """Check if user is registered"""
        user_data = db.get_telegram_user_by_id(user_id)
        return user_data is not None
    
    def get_user_status(self, user_id: int) -> str:
        """Get user status"""
        user_data = db.get_telegram_user_by_id(user_id)
        return user_data['status'] if user_data else 'not_registered'
