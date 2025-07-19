"""
Verification Handlers
Handles balance verification conversation flow
"""

import logging
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler

from core.database import db
from telegram_bot.messages import *
from ..services.verification_service import VerificationService
from ..services.admin_service import AdminService

logger = logging.getLogger(__name__)

# Conversation states
WAITING_FOR_AMOUNT, WAITING_FOR_DATE, WAITING_FOR_TIME, CONFIRM_VERIFICATION = range(10, 14)

class VerificationHandlers:
    """Handles balance verification conversation"""
    
    def __init__(self, bot_instance):
        self.bot = bot_instance
        self.verification_service = VerificationService()
        self.admin_service = AdminService(bot_instance)
    
    async def start_verification_process(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start balance verification process"""
        keyboard = [["❌ إلغاء"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            REQUEST_AMOUNT,
            reply_markup=reply_markup
        )
        return WAITING_FOR_AMOUNT
    
    async def handle_amount(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle amount input for verification"""
        amount_text = update.message.text.strip()
        
        # Check for cancel button
        if amount_text == "❌ إلغاء":
            return await self.cancel(update, context)
        
        try:
            amount = float(amount_text)
            
            if amount <= 0:
                await update.message.reply_text("❌ يجب أن يكون المبلغ أكبر من صفر")
                return WAITING_FOR_AMOUNT
            
            # Store amount in session
            user_id = update.effective_user.id
            if user_id not in self.bot.user_sessions:
                self.bot.user_sessions[user_id] = {}
            self.bot.user_sessions[user_id]['amount'] = amount
            
            # Show date input with cancel button
            keyboard = [["❌ إلغاء"]]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            
            await update.message.reply_text(REQUEST_DATE, reply_markup=reply_markup)
            return WAITING_FOR_DATE
            
        except ValueError:
            await update.message.reply_text("❌ يرجى إدخال رقم صحيح")
            return WAITING_FOR_AMOUNT
    
    async def handle_date(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle date input for verification"""
        date_text = update.message.text.strip()
        
        # Check for cancel button
        if date_text == "❌ إلغاء":
            return await self.cancel(update, context)
        
        user_id = update.effective_user.id
        
        # Store date in session
        if user_id not in self.bot.user_sessions:
            self.bot.user_sessions[user_id] = {}
        self.bot.user_sessions[user_id]['date'] = date_text
        
        # Show time input with cancel button
        keyboard = [["❌ إلغاء"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(REQUEST_TIME, reply_markup=reply_markup)
        return WAITING_FOR_TIME
    
    async def handle_time(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle time input for verification"""
        time_text = update.message.text.strip()
        
        # Check for cancel button
        if time_text == "❌ إلغاء":
            return await self.cancel(update, context)
        
        user_id = update.effective_user.id
        
        # Store time in session
        if user_id not in self.bot.user_sessions:
            self.bot.user_sessions[user_id] = {}
        self.bot.user_sessions[user_id]['time'] = time_text
        
        # Get all session data
        session_data = self.bot.user_sessions[user_id]
        amount = session_data.get('amount')
        date = session_data.get('date')
        time = session_data.get('time')
        
        # Get user's SIM info
        sim_info = db.get_user_sim_by_telegram_id(user_id)
        if not sim_info:
            await update.message.reply_text("❌ لم يتم العثور على شريحة مرتبطة بحسابك")
            if user_id in self.bot.user_sessions:
                del self.bot.user_sessions[user_id]
            await self.bot.show_main_menu(update, context)
            return ConversationHandler.END
        
        # Show confirmation
        confirmation_text = VERIFICATION_CONFIRM.format(
            amount=amount,
            date=date,
            time=time,
            sim_number=sim_info.get('phone_number', 'غير متصل')
        )
        
        keyboard = [["✅ تأكيد", "❌ إلغاء"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(confirmation_text, reply_markup=reply_markup)
        return CONFIRM_VERIFICATION
    
    async def handle_verification_confirm(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle verification confirmation"""
        user_id = update.effective_user.id
        response = update.message.text.strip()
        
        if response == "❌ إلغاء":
            await update.message.reply_text(
                "❌ تم إلغاء عملية التحقق من الرصيد.",
                reply_markup=ReplyKeyboardRemove()
            )
            if user_id in self.bot.user_sessions:
                del self.bot.user_sessions[user_id]
            await self.bot.show_main_menu(update, context)
            return ConversationHandler.END
        
        if response != "✅ تأكيد":
            await update.message.reply_text("يرجى الضغط على أحد الأزرار")
            return CONFIRM_VERIFICATION
        
        # Process verification
        await self.process_verification(update, context)
        return ConversationHandler.END
    
    async def process_verification(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Process the verification request"""
        user_id = update.effective_user.id
        session_data = self.bot.user_sessions.get(user_id, {})
        
        try:
            amount = session_data.get('amount')
            date_input = session_data.get('date')
            time_input = session_data.get('time')
            
            # Get user data
            user_data = db.get_telegram_user_by_id(user_id)
            if not user_data:
                await update.message.reply_text(ERROR_GENERAL)
                return
            
            # Process verification
            result = await self.verification_service.verify_balance(
                user_id, amount, date_input, time_input
            )
            
            # Send response to user
            if result['result'] == "scb_rejected":
                await update.message.reply_text(
                    VERIFICATION_SCB_REJECTED,
                    reply_markup=ReplyKeyboardRemove()
                )
            elif result['result'] == "success":
                await update.message.reply_text(
                    VERIFICATION_SUCCESS.format(
                        amount=result['actual_amount'],
                        date=date_input,
                        time=time_input,
                        current_balance=result['actual_amount']
                    ),
                    reply_markup=ReplyKeyboardRemove()
                )
            else:
                await update.message.reply_text(
                    VERIFICATION_FAILED.format(
                        amount=amount,
                        date=date_input,
                        time=time_input
                    ),
                    reply_markup=ReplyKeyboardRemove()
                )
            
            # Notify admin
            verification_data = {
                'amount': amount,
                'date': date_input,
                'time': time_input,
                'result': result['result'],
                'details': result.get('details', ''),
                'sim_number': result.get('sim_number', 'غير متصل')
            }
            await self.admin_service.notify_verification_result(user_data, verification_data)
            
        except Exception as e:
            logger.error(f"Error processing verification: {e}")
            await update.message.reply_text(ERROR_GENERAL, reply_markup=ReplyKeyboardRemove())
        
        finally:
            # Clean up session
            if user_id in self.bot.user_sessions:
                del self.bot.user_sessions[user_id]
            
            # Show main menu
            await self.bot.show_main_menu(update, context)
    
    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Cancel current operation"""
        user_id = update.effective_user.id
        if user_id in self.bot.user_sessions:
            del self.bot.user_sessions[user_id]
        
        await update.message.reply_text(
            "❌ تم إلغاء عملية التحقق من الرصيد.",
            reply_markup=ReplyKeyboardRemove()
        )
        
        # Show main menu
        await self.bot.show_main_menu(update, context)
        return ConversationHandler.END
