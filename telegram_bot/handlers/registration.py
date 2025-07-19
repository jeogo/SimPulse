"""
User Registration Handlers
Handles user registration conversation flow
"""

import logging
from telegram import Update, ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler

from core.database import db
from telegram_bot.messages import *
from ..services.admin_service import AdminService

logger = logging.getLogger(__name__)

# Conversation states
WAITING_FOR_NAME, WAITING_FOR_PHONE = range(2)

class RegistrationHandlers:
    """Handles user registration conversation"""
    
    def __init__(self, bot_instance):
        self.bot = bot_instance
        self.admin_service = AdminService(bot_instance)
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle /start command"""
        user = update.effective_user
        
        # Check if user already exists
        existing_user = db.get_telegram_user_by_id(user.id)
        
        if existing_user:
            status = existing_user['status']
            if status == 'pending':
                await update.message.reply_text(
                    ALREADY_REGISTERED.format(status_message=STATUS_PENDING),
                    reply_markup=ReplyKeyboardRemove()
                )
            elif status == 'approved':
                await self.bot.show_main_menu(update, context)
            else:  # blocked or rejected
                await update.message.reply_text(
                    ALREADY_REGISTERED.format(status_message=STATUS_REJECTED),
                    reply_markup=ReplyKeyboardRemove()
                )
            return ConversationHandler.END
        
        # New user - start registration
        await update.message.reply_text(START_REGISTRATION)
        return WAITING_FOR_NAME
    
    async def handle_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle name input"""
        name = update.message.text.strip()
        
        if len(name) < 2:
            await update.message.reply_text("الرجاء إدخال اسم صحيح (أكثر من حرفين)")
            return WAITING_FOR_NAME
        
        # Store name in session
        user_id = update.effective_user.id
        self.bot.user_sessions[user_id] = {'name': name}
        
        await update.message.reply_text(REQUEST_PHONE.format(name=name))
        return WAITING_FOR_PHONE
    
    async def handle_phone(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle phone number input"""
        phone = update.message.text.strip()
        user_id = update.effective_user.id
        
        # Basic phone validation
        if not phone.isdigit() or len(phone) < 9:
            await update.message.reply_text("الرجاء إدخال رقم هاتف صحيح")
            return WAITING_FOR_PHONE
        
        # Get name from session
        name = self.bot.user_sessions.get(user_id, {}).get('name', 'Unknown')
        
        try:
            # Add user to database
            db.add_telegram_user(user_id, name, phone)
            
            # Send confirmation to user
            await update.message.reply_text(
                REGISTRATION_COMPLETE.format(name=name, phone=phone),
                reply_markup=ReplyKeyboardRemove()
            )
            
            # Notify admins
            await self.admin_service.notify_new_user(user_id, name, phone)
            
            # Clean up session
            if user_id in self.bot.user_sessions:
                del self.bot.user_sessions[user_id]
            
            return ConversationHandler.END
            
        except Exception as e:
            logger.error(f"Error registering user {user_id}: {e}")
            await update.message.reply_text(ERROR_GENERAL)
            return ConversationHandler.END
    
    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Cancel current operation"""
        user_id = update.effective_user.id
        if user_id in self.bot.user_sessions:
            del self.bot.user_sessions[user_id]
        
        await update.message.reply_text(
            "تم إلغاء العملية.",
            reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END
