"""
SimPulse Telegram Bot
Complete working bot with admin and user functionality
"""

import asyncio
import logging
import sys
import os
import threading
from typing import Dict, Any
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from telegram.error import NetworkError, BadRequest, Forbidden, TelegramError

import core.config as config
from core.database import db
from core.group_manager import group_manager
from telegram_bot.messages import *
from telegram_bot.services.settlement_service import SettlementService
from telegram_bot.services.admin_service import AdminService
from telegram_bot.services.balance_service import balance_service
from telegram_bot.handlers.verification import VerificationHandlers, WAITING_FOR_AMOUNT, WAITING_FOR_DATE, WAITING_FOR_TIME, CONFIRM_VERIFICATION

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Conversation states
WAITING_FOR_NAME, WAITING_FOR_PHONE = range(2)
# Admin interactive states
SELECTING_USER_ACTION, SELECTING_GROUP, CONFIRMING_APPROVAL = range(2, 5)
# Contact admin states
WAITING_FOR_ADMIN_MESSAGE = range(5, 6)
# Group management states
WAITING_FOR_GROUP_NAME = range(6, 7)

# Pagination constants
USERS_PER_PAGE = 8  # Show 8 users per page for better UI
MAX_BUTTON_TEXT_LENGTH = 45  # Truncate long user names for buttons
GROUPS_PER_PAGE = 6  # Show 6 groups per page

class SimPulseTelegramBot:
    """Main Telegram Bot class"""
    
    def __init__(self):
        self.application = None
        self.user_sessions = {}  # Store user session data
        self.navigation_history = {}  # Store navigation history for each user
        self.settlement_service = SettlementService()
        self.verification_handlers = VerificationHandlers(self)
        self.admin_service = AdminService(self)
    
    def push_navigation(self, user_id: int, current_state: str):
        """Push current state to navigation history"""
        if user_id not in self.navigation_history:
            self.navigation_history[user_id] = []
        
        # Avoid duplicate states
        if not self.navigation_history[user_id] or self.navigation_history[user_id][-1] != current_state:
            self.navigation_history[user_id].append(current_state)
            logger.debug(f"User {user_id} navigation: pushed '{current_state}' -> stack: {self.navigation_history[user_id]}")
            
        # Limit history size to prevent memory issues
        if len(self.navigation_history[user_id]) > 10:
            self.navigation_history[user_id] = self.navigation_history[user_id][-10:]
    
    def pop_navigation(self, user_id: int) -> str:
        """Pop last state from navigation history"""
        if user_id in self.navigation_history and self.navigation_history[user_id]:
            # Remove current state
            if len(self.navigation_history[user_id]) > 1:
                current_state = self.navigation_history[user_id].pop()
                previous_state = self.navigation_history[user_id][-1]
                logger.debug(f"User {user_id} navigation: popped '{current_state}' -> returning to '{previous_state}' -> stack: {self.navigation_history[user_id]}")
                
                # Security check: Admin users should never be directed to main_menu
                if self.is_admin(user_id) and previous_state == "main_menu":
                    logger.warning(f"Admin {user_id} was about to be directed to main_menu, redirecting to admin_menu")
                    return "admin_menu"
                
                return previous_state
        
        # Fallback: determine appropriate default based on user role
        default_state = "admin_menu" if self.is_admin(user_id) else "main_menu"
        logger.debug(f"User {user_id} navigation: no history, fallback to '{default_state}'")
        return default_state
    
    def clear_navigation(self, user_id: int):
        """Clear navigation history for user"""
        if user_id in self.navigation_history:
            self.navigation_history[user_id] = []
    
    def ensure_admin_navigation(self, user_id: int):
        """Ensure admin user has proper navigation state"""
        if self.is_admin(user_id):
            # Clear any incorrect navigation history
            if user_id in self.navigation_history:
                # Remove any main_menu entries for admin users
                self.navigation_history[user_id] = [
                    state for state in self.navigation_history[user_id] 
                    if state != "main_menu"
                ]
                # Ensure admin_menu is in the stack
                if not self.navigation_history[user_id] or self.navigation_history[user_id][-1] != "admin_menu":
                    self.navigation_history[user_id].append("admin_menu")
            else:
                self.navigation_history[user_id] = ["admin_menu"]

    # ========================================================================
    # PAGINATION HELPER FUNCTIONS
    # ========================================================================
    
    def calculate_pagination(self, total_items: int, items_per_page: int = USERS_PER_PAGE) -> dict:
        """Calculate pagination info"""
        if total_items == 0:
            return {
                'total_pages': 0,
                'items_per_page': items_per_page,
                'total_items': 0
            }
        
        total_pages = (total_items + items_per_page - 1) // items_per_page
        return {
            'total_pages': total_pages,
            'items_per_page': items_per_page,
            'total_items': total_items
        }
    
    def get_page_items(self, items: list, page: int, items_per_page: int = USERS_PER_PAGE) -> list:
        """Get items for specific page"""
        start_idx = (page - 1) * items_per_page
        end_idx = start_idx + items_per_page
        return items[start_idx:end_idx]
    
    def create_pagination_buttons(self, current_page: int, total_pages: int) -> list:
        """Create pagination navigation buttons"""
        buttons = []
        
        if total_pages <= 1:
            return buttons
        
        nav_row = []
        
        # Previous button
        if current_page > 1:
            nav_row.append("◀️ السابق")
        
        # Page info
        nav_row.append(f"🔢 {current_page} من {total_pages}")
        
        # Next button  
        if current_page < total_pages:
            nav_row.append("التالي ▶️")
        
        if nav_row:
            buttons.append(nav_row)
        
        return buttons
    
    def truncate_button_text(self, text: str, max_length: int = MAX_BUTTON_TEXT_LENGTH) -> str:
        """Truncate button text if too long"""
        if len(text) <= max_length:
            return text
        return text[:max_length-3] + "..."

    # ========================================================================
    # PAGINATION NAVIGATION HANDLERS
    # ========================================================================
    
    async def handle_pagination_previous(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle previous page navigation"""
        user_id = update.effective_user.id
        
        # Get current navigation state to determine which list we're paginating
        if user_id in self.navigation_history and self.navigation_history[user_id]:
            current_state = self.navigation_history[user_id][-1]
            
            if current_state == "pending_users":
                current_page = context.user_data.get('pending_users_page', 1)
                if current_page > 1:
                    context.user_data['pending_users_page'] = current_page - 1
                await self.show_pending_users_interactive(update, context)
                
            elif current_state == "users_list":
                current_page = context.user_data.get('all_users_page', 1)
                if current_page > 1:
                    context.user_data['all_users_page'] = current_page - 1
                await self.show_all_users_interactive(update, context)
    
    async def handle_pagination_next(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle next page navigation"""
        user_id = update.effective_user.id
        
        # Get current navigation state to determine which list we're paginating
        if user_id in self.navigation_history and self.navigation_history[user_id]:
            current_state = self.navigation_history[user_id][-1]
            
            if current_state == "pending_users":
                pending_users = db.get_pending_telegram_users()
                total_pages = self.calculate_pagination(len(pending_users))['total_pages']
                current_page = context.user_data.get('pending_users_page', 1)
                if current_page < total_pages:
                    context.user_data['pending_users_page'] = current_page + 1
                await self.show_pending_users_interactive(update, context)
                
            elif current_state == "users_list":
                all_users = db.get_all_telegram_users()
                total_pages = self.calculate_pagination(len(all_users))['total_pages']
                current_page = context.user_data.get('all_users_page', 1)
                if current_page < total_pages:
                    context.user_data['all_users_page'] = current_page + 1
                await self.show_all_users_interactive(update, context)
    
    async def handle_back_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle back button navigation"""
        user_id = update.effective_user.id
        last_state = self.pop_navigation(user_id)
        
        logger.info(f"User {user_id} going back to state: {last_state}")
        
        # Route to appropriate function based on last state
        if last_state == "admin_menu":
            await self.show_admin_menu(update, context)
        elif last_state == "main_menu":
            await self.show_main_menu(update, context)
        elif last_state == "settlement_menu":
            await self.show_settlement_menu(update, context)
        elif last_state == "users_list":
            await self.show_all_users_interactive(update, context)
        elif last_state == "groups_list":
            await self.show_groups_interactive(update, context)
        elif last_state == "pending_users":
            await self.show_pending_users_interactive(update, context)
        else:
            # Default fallback - Use safe navigation
            await self.safe_navigate_to_default(update, context)
    
    async def handle_back_navigation(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle back navigation with one step back"""
        user_id = update.effective_user.id
        
        # Get the previous navigation state
        last_state = self.pop_navigation(user_id)
        
        if last_state == "admin_menu":
            await self.show_admin_menu(update, context)
        elif last_state == "main_menu":
            await self.show_main_menu(update, context)
        elif last_state == "settlement_menu":
            await self.show_settlement_menu(update, context)
        elif last_state == "users_list":
            await self.show_all_users_interactive(update, context)
        elif last_state == "groups_list":
            await self.show_groups_interactive(update, context)
        elif last_state == "pending_users":
            await self.show_pending_users_interactive(update, context)
        else:
            # Default fallback - Use safe navigation
            await self.safe_navigate_to_default(update, context)
    
    def is_admin(self, user_id: int) -> bool:
        """Check if user is admin"""
        return user_id in config.ADMIN_TELEGRAM_IDS
    
    def get_appropriate_default_menu(self, user_id: int) -> str:
        """Get appropriate default menu based on user role"""
        return "admin_menu" if self.is_admin(user_id) else "main_menu"
    
    async def safe_navigate_to_default(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Safely navigate to appropriate default menu"""
        user_id = update.effective_user.id
        if self.is_admin(user_id):
            await self.show_admin_menu(update, context)
            logger.info(f"Admin {user_id} navigated to admin menu (safe default)")
        else:
            await self.show_main_menu(update, context)
            logger.info(f"User {user_id} navigated to main menu (safe default)")
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command - Different behavior for admin vs users"""
        user = update.effective_user
        
        logger.info(f"User {user.id} ({user.first_name}) started the bot")
        
        # Clear navigation history on start for fresh session
        self.clear_navigation(user.id)
        
        # Check if user is admin
        if self.is_admin(user.id):
            logger.info(f"Admin {user.id} accessed admin interface")
            await self.show_admin_menu(update, context)
            return ConversationHandler.END
        
        # Regular user flow
        # Check if user already exists in database
        existing_user = db.get_telegram_user_by_id(user.id)
        
        if existing_user:
            status = existing_user['status']
            if status == 'pending':
                await update.message.reply_text(
                    ALREADY_REGISTERED.format(status_message=STATUS_PENDING),
                    reply_markup=ReplyKeyboardRemove()
                )
            elif status == 'approved':
                await self.show_main_menu(update, context)
            else:  # blocked or rejected
                await update.message.reply_text(
                    ALREADY_REGISTERED.format(status_message=STATUS_REJECTED),
                    reply_markup=ReplyKeyboardRemove()
                )
            return ConversationHandler.END
        
        # New user - start registration
        await update.message.reply_text(START_REGISTRATION)
        return WAITING_FOR_NAME
    
    # ========================================================================
    # USER REGISTRATION HANDLERS
    # ========================================================================
    
    async def handle_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle name input"""
        name = update.message.text.strip()
        
        if len(name) < 2:
            await update.message.reply_text("الرجاء إدخال اسم صحيح (أكثر من حرفين)")
            return WAITING_FOR_NAME
        
        # Store name in session
        user_id = update.effective_user.id
        self.user_sessions[user_id] = {'name': name}
        
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
        name = self.user_sessions.get(user_id, {}).get('name', 'Unknown')
        
        try:
            # Add user to database
            db.add_telegram_user(user_id, name, phone)
            
            # Send confirmation to user
            await update.message.reply_text(
                REGISTRATION_COMPLETE.format(name=name, phone=phone),
                reply_markup=ReplyKeyboardRemove()
            )
            
            # Notify admins
            await self.notify_admins_new_user(user_id, name, phone)
            
            # Clean up session
            if user_id in self.user_sessions:
                del self.user_sessions[user_id]
            
            return ConversationHandler.END
            
        except Exception as e:
            logger.error(f"Error registering user {user_id}: {e}")
            await update.message.reply_text(ERROR_GENERAL)
            return ConversationHandler.END
    
    async def notify_admins_new_user(self, user_id: int, name: str, phone: str):
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
                await self.application.bot.send_message(
                    chat_id=admin_id,
                    text=message
                )
                logger.info(f"Notified admin {admin_id} about new user {user_id}")
            except Exception as e:
                logger.error(f"Failed to notify admin {admin_id}: {e}")
    
    # ========================================================================
    # USER MENU HANDLERS
    # ========================================================================
    
    async def show_main_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show main menu for approved users"""
        user_id = update.effective_user.id
        
        # Set navigation state for regular users only
        if not self.is_admin(user_id):
            self.push_navigation(user_id, "main_menu")
        
        keyboard = [[button] for button in MAIN_MENU_BUTTONS]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            MAIN_MENU,
            reply_markup=reply_markup
        )
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle non-command messages"""
        user = update.effective_user
        message_text = update.message.text
        
        # Check if user is admin first
        if self.is_admin(user.id):
            await self.handle_admin_message(update, context)
            return
        
        # Check if user is registered and approved
        user_data = db.get_telegram_user_by_id(user.id)
        
        if not user_data:
            await update.message.reply_text(ERROR_NOT_REGISTERED)
            return
        
        if user_data['status'] == 'pending':
            await update.message.reply_text(ERROR_PENDING_APPROVAL)
            return
        
        if user_data['status'] != 'approved':
            await update.message.reply_text(ERROR_ACCESS_DENIED)
            return
        
        # Handle menu buttons for approved users
        if message_text == "👤 ملفي الشخصي":
            await self.show_profile(update, context)
        elif message_text == "💰 التحقق من الرصيد":
            # This will be handled by the ConversationHandler
            pass
        elif message_text == BUTTON_CHECK_BALANCE:
            await self.handle_user_balance_check(update, context)
        elif message_text == "📞 التواصل مع المشرف":
            # This will be handled by the contact_admin_handler ConversationHandler
            pass
        else:
            # Show main menu if unknown command
            await self.show_main_menu(update, context)
    
    async def show_profile(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show user profile information"""
        try:
            user_id = update.effective_user.id
            user_data = db.get_telegram_user_by_id(user_id)
            
            if not user_data:
                await self._safe_reply(update, ERROR_NOT_REGISTERED)
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
            
            await self._safe_reply(update, profile_text)
            
        except Exception as e:
            logger.error(f"Error in show_profile: {e}")
            await self._safe_reply(update, "❌ حدث خطأ في عرض الملف الشخصي. الرجاء المحاولة لاحقاً.")
    
    async def handle_user_balance_check(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """معالج فحص الرصيد للمستخدمين"""
        try:
            user_id = update.effective_user.id
            logger.info(f"🔍 User {user_id} requested balance check")
            
            # Send processing message
            processing_msg = await update.message.reply_text(BALANCE_CHECK_PROCESSING)
            
            # Check balance via service
            result = await balance_service.check_user_balance(user_id)
            
            # Delete processing message
            try:
                await processing_msg.delete()
            except Exception as e:
                logger.warning(f"Could not delete processing message: {e}")
            
            # Send result
            if result['success']:
                await self._safe_reply(update, 
                    BALANCE_CHECK_SUCCESS.format(**result['data'])
                )
                logger.info(f"✅ Balance check successful for user {user_id}")
            else:
                await self._safe_reply(update, result.get('message', BALANCE_CHECK_FAILED))
                logger.warning(f"❌ Balance check failed for user {user_id}")
                
        except Exception as e:
            logger.error(f"Error in handle_user_balance_check: {e}")
            # Try to delete processing message if it exists
            try:
                if 'processing_msg' in locals():
                    await processing_msg.delete()
            except:
                pass
            await self._safe_reply(update, BALANCE_CHECK_FAILED)
    
    async def _safe_reply(self, update: Update, text: str, reply_markup=None):
        """Safely send a reply message with comprehensive error handling"""
        try:
            # Check if update and message exist
            if not update or not hasattr(update, 'message') or not update.message:
                logger.warning("Invalid update object for reply")
                return False
                
            # Check if the bot and application are still running
            if not self.application or not self.application.bot:
                logger.warning("Bot application not available, cannot send message")
                return False
            
            # Check if the event loop is available and not closed
            try:
                current_loop = asyncio.get_running_loop()
                if current_loop.is_closed():
                    logger.error("Current event loop is closed - cannot send reply")
                    return False
            except RuntimeError:
                # No running event loop
                logger.error("No running event loop available for reply")
                return False
                
            # Try to send the message
            await update.message.reply_text(text, reply_markup=reply_markup)
            return True
            
        except NetworkError as e:
            logger.warning(f"Network error during reply: {e}")
            return False
        except BadRequest as e:
            logger.warning(f"Bad request during reply: {e}")
            return False
        except Forbidden as e:
            logger.warning(f"Forbidden error during reply (user may have blocked bot): {e}")
            return False
        except TelegramError as e:
            logger.error(f"Telegram API error during reply: {e}")
            return False
        except RuntimeError as e:
            if "event loop is closed" in str(e).lower():
                logger.error("Event loop closed during reply attempt")
            else:
                logger.error(f"Runtime error during reply: {e}")
            return False
        except Exception as e:
            error_msg = str(e).lower()
            
            # Handle specific error types
            if "event loop is closed" in error_msg:
                logger.error(f"Event loop closed error: {e}")
                
            elif "network" in error_msg or "connection" in error_msg:
                logger.error(f"Network error in _safe_reply: {e}")
                
            elif "rate" in error_msg or "flood" in error_msg:
                logger.error(f"Rate limit error in _safe_reply: {e}")
                # Could implement retry logic here
                
            else:
                logger.error(f"Unknown error in _safe_reply: {e}")
                
            return False
    
    async def show_contact_admin(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show contact admin message and start conversation"""
        # Create keyboard with cancel button
        keyboard = [[button] for button in CONTACT_ADMIN_BUTTONS]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            CONTACT_ADMIN_MESSAGE,
            reply_markup=reply_markup
        )
        return WAITING_FOR_ADMIN_MESSAGE
    
    async def handle_admin_contact_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle message from user to admin"""
        user = update.effective_user
        user_message = update.message.text.strip()
        
        # Check if user wants to cancel
        if user_message == "❌ إلغاء":
            await update.message.reply_text(
                CONTACT_ADMIN_CANCELLED,
                reply_markup=ReplyKeyboardRemove()
            )
            # Clear state and return to main menu
            context.user_data.clear()
            await self.show_main_menu(update, context)
            return ConversationHandler.END
        
        if not user_message:
            await update.message.reply_text("❌ الرجاء إدخال رسالة صحيحة")
            return WAITING_FOR_ADMIN_MESSAGE
        
        try:
            # Get user data from database
            user_data = db.get_telegram_user_by_id(user.id)
            
            if not user_data:
                await update.message.reply_text("❌ لم يتم العثور على بياناتك")
                context.user_data.clear()
                await self.show_main_menu(update, context)
                return ConversationHandler.END
            
            # Format admin notification message
            admin_notification = ADMIN_USER_MESSAGE.format(
                user_name=user_data['full_name'],
                username=user.username if user.username else "لا يوجد",
                phone=user_data['phone_number'],
                user_id=user.id,
                message=user_message
            )
            
            # Send to all admins
            sent_count = 0
            for admin_id in config.ADMIN_TELEGRAM_IDS:
                try:
                    await self.application.bot.send_message(
                        chat_id=admin_id,
                        text=admin_notification
                    )
                    sent_count += 1
                    logger.info(f"Sent user message to admin {admin_id}")
                except Exception as e:
                    logger.error(f"Failed to send message to admin {admin_id}: {e}")
            
            if sent_count > 0:
                await update.message.reply_text(
                    MESSAGE_SENT_TO_ADMIN,
                    reply_markup=ReplyKeyboardRemove()
                )
            else:
                await update.message.reply_text(
                    "❌ فشل في إرسال الرسالة، الرجاء المحاولة لاحقاً",
                    reply_markup=ReplyKeyboardRemove()
                )
            
            # Clear state and return to main menu
            context.user_data.clear()
            await self.show_main_menu(update, context)
            return ConversationHandler.END
            
        except Exception as e:
            logger.error(f"Error handling admin contact message: {e}")
            await update.message.reply_text(
                "❌ حدث خطأ أثناء إرسال الرسالة",
                reply_markup=ReplyKeyboardRemove()
            )
            context.user_data.clear()
            await self.show_main_menu(update, context)
            return ConversationHandler.END
    
    # ========================================================================
    # ADMIN FUNCTIONS
    # ========================================================================
    
    async def show_admin_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show admin menu with buttons"""
        user_id = update.effective_user.id
        
        # Double-check admin status for security
        if not self.is_admin(user_id):
            logger.warning(f"Non-admin user {user_id} attempted to access admin menu")
            await update.message.reply_text("❌ غير مسموح لك بالوصول لهذه القائمة")
            await self.show_main_menu(update, context)
            return
        
        # Ensure proper admin navigation state
        self.ensure_admin_navigation(user_id)
        self.push_navigation(user_id, "admin_menu")
        
        keyboard = [[button] for button in ADMIN_MENU_BUTTONS]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(ADMIN_MENU, reply_markup=reply_markup)
    
    async def handle_admin_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle admin messages"""
        message_text = update.message.text
        user_id = update.effective_user.id
        
        # Security check - ensure user is still admin
        if not self.is_admin(user_id):
            logger.warning(f"Non-admin user {user_id} attempted admin action: {message_text}")
            await update.message.reply_text("❌ غير مسموح لك بهذا الإجراء")
            await self.show_main_menu(update, context)
            return
        
        if message_text == BUTTON_BACK_ONE_STEP:
            await self.handle_back_button(update, context)
        elif message_text == "👥 المستخدمين المعلقين":
            self.push_navigation(user_id, "admin_menu")
            await self.show_pending_users_interactive(update, context)
        elif message_text == "👤 جميع المستخدمين":
            self.push_navigation(user_id, "admin_menu")
            await self.show_all_users_interactive(update, context)
        elif message_text == "📁 المجموعات":
            self.push_navigation(user_id, "admin_menu")
            await self.show_groups_interactive(update, context)
        elif message_text == "💰 نظام التسوية":
            self.push_navigation(user_id, "admin_menu")
            await self.show_settlement_menu(update, context)
        elif message_text == BUTTON_BACK_TO_MENU:
            await self.show_admin_menu(update, context)
        elif message_text == BUTTON_BACK_ONE_STEP:
            await self.handle_back_navigation(update, context)
        # Pagination handlers
        elif message_text == "◀️ السابق":
            await self.handle_pagination_previous(update, context)
        elif message_text == "التالي ▶️":
            await self.handle_pagination_next(update, context)
        elif message_text.startswith("🔢 "):  # Page info button (ignore clicks)
            return  # Do nothing for page info button clicks
        elif message_text.startswith("👤 "):  # User button clicked
            await self.handle_user_selection(update, context)
        elif message_text == BUTTON_APPROVE_USER:
            await self.start_approval_process(update, context)
        elif message_text == BUTTON_REJECT_USER:
            await self.reject_selected_user(update, context)
        elif message_text.startswith("📁 "):  # Group button clicked
            await self.handle_group_selection(update, context)
        elif message_text == BUTTON_RENAME_GROUP:  # Group rename button clicked
            return await self.handle_group_rename_request(update, context)
        elif message_text == BUTTON_CHECK_BALANCE:  # Group balance check button
            await self.handle_admin_group_balance_check(update, context)
        elif message_text == BUTTON_VIEW_GROUP_USERS:  # New button to view group users
            await self.show_group_users(update, context)
        elif message_text == BUTTON_NEXT_PAGE:  # Pagination buttons
            await self.handle_next_page(update, context)
        elif message_text == BUTTON_PREV_PAGE:
            await self.handle_prev_page(update, context)
        elif message_text == BUTTON_BACK_TO_GROUP:
            await self.handle_back_to_group(update, context)
        elif message_text == BUTTON_BACK_TO_GROUPS:
            await self.handle_back_to_groups(update, context)
        # Handle user selection from group users list
        elif " (" in message_text and ")" in message_text and any(emoji in message_text for emoji in ['✅', '⏳', '❌']):
            # This is a user selection from group users list
            phone = message_text.split("(")[1].split(")")[0]
            await self.show_user_details_from_group(update, context, phone)
        elif message_text == BUTTON_CONFIRM_ACTION:
            await self.confirm_user_approval(update, context)
        elif message_text == BUTTON_CANCEL_ACTION:
            await self.cancel_current_action(update, context)
        # Settlement buttons
        elif message_text == BUTTON_USER_VERIFICATIONS_SETTLEMENT:
            await self.show_user_settlement_details(update, context)
        elif message_text == BUTTON_PROCESS_SETTLEMENT:
            await self.handle_settlement_confirmation(update, context)
        elif message_text == BUTTON_CONFIRM_SETTLEMENT:
            await self.process_user_settlement(update, context)
        elif message_text == BUTTON_CANCEL_SETTLEMENT:
            await self.show_user_settlement_details(update, context)  # Go back to settlement details
        elif message_text == BUTTON_VIEW_ALL_VERIFICATIONS:
            await self.show_user_all_verifications(update, context)
        elif message_text == BUTTON_SETTLEMENT_HISTORY:
            await self.show_user_settlement_history(update, context)
        # User management buttons
        elif message_text == BUTTON_REMOVE_FROM_GROUP:
            await self.confirm_user_removal(update, context)
        elif message_text == BUTTON_TRANSFER_TO_GROUP:
            await self.show_transfer_group_selection(update, context)
        elif message_text == BUTTON_CONFIRM_REMOVAL:
            await self.process_user_removal(update, context)
        elif message_text == BUTTON_CONFIRM_TRANSFER:
            await self.process_user_transfer(update, context)
        else:
            # If admin sends unknown message, show admin menu
            await self.show_admin_menu(update, context)
    
    # ========================================================================
    # INTERACTIVE ADMIN FUNCTIONS
    # ========================================================================
    
    async def handle_next_page(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle next page navigation for group users"""
        current_page = context.user_data.get('current_page', 1)
        context.user_data['current_page'] = current_page + 1
        await self.show_group_users(update, context)
    
    async def handle_prev_page(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle previous page navigation for group users"""
        current_page = context.user_data.get('current_page', 1)
        if current_page > 1:
            context.user_data['current_page'] = current_page - 1
        await self.show_group_users(update, context)
    
    async def handle_back_to_group(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle back to group details navigation"""
        current_group = context.user_data.get('current_group')
        if current_group:
            # Reset pagination
            context.user_data.pop('current_page', None)
            # Clear selected user
            context.user_data.pop('selected_user', None)
            # Show group details
            await self.show_group_details(update, context, current_group['name'])
        else:
            await self.show_groups_interactive(update, context)
    
    async def handle_back_to_groups(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle back to groups list navigation"""
        # Clear current group context
        context.user_data.pop('current_group', None)
        context.user_data.pop('current_page', None) 
        context.user_data.pop('selected_user', None)
        await self.show_groups_interactive(update, context)

    async def show_pending_users_interactive(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show pending users as interactive buttons with pagination"""
        user_id = update.effective_user.id
        self.push_navigation(user_id, "pending_users")
        
        pending_users = db.get_pending_telegram_users()
        
        if not pending_users:
            keyboard = [[BUTTON_BACK_ONE_STEP]]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            await update.message.reply_text(NO_PENDING_USERS, reply_markup=reply_markup)
            return
        
        # Get current page from context or default to 1
        current_page = context.user_data.get('pending_users_page', 1)
        
        # Calculate pagination
        pagination_info = self.calculate_pagination(len(pending_users), USERS_PER_PAGE)
        total_pages = pagination_info['total_pages']
        
        # Validate current page
        if current_page > total_pages:
            current_page = 1
        elif current_page < 1:
            current_page = 1
        
        # Update context with current page
        context.user_data['pending_users_page'] = current_page
        
        # Get users for current page
        page_users = self.get_page_items(pending_users, current_page, USERS_PER_PAGE)
        
        # Create buttons for users on current page
        keyboard = []
        for user in page_users:
            user_button = f"👤 {user['full_name']} ({user['phone_number']})"
            user_button = self.truncate_button_text(user_button)
            keyboard.append([user_button])
        
        # Add pagination navigation buttons
        pagination_buttons = self.create_pagination_buttons(current_page, total_pages)
        keyboard.extend(pagination_buttons)
        
        # Add back button
        keyboard.append([BUTTON_BACK_ONE_STEP])
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        # Create header with page info
        if total_pages > 1:
            header_text = f"👥 المستخدمين المعلقين ({len(pending_users)})\n\n📄 الصفحة {current_page} من {total_pages}\n\nاختر مستخدم للموافقة أو الرفض:"
        else:
            header_text = PENDING_USERS_HEADER.format(count=len(pending_users))
        
        await update.message.reply_text(header_text, reply_markup=reply_markup)
    
    async def show_all_users_interactive(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show all users as interactive buttons with pagination"""
        user_id = update.effective_user.id
        self.push_navigation(user_id, "users_list")
        
        all_users = db.get_all_telegram_users()
        
        if not all_users:
            keyboard = [[BUTTON_BACK_ONE_STEP]]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            await update.message.reply_text(NO_USERS_FOUND, reply_markup=reply_markup)
            return
        
        # Get current page from context or default to 1
        current_page = context.user_data.get('all_users_page', 1)
        
        # Calculate pagination
        pagination_info = self.calculate_pagination(len(all_users), USERS_PER_PAGE)
        total_pages = pagination_info['total_pages']
        
        # Validate current page
        if current_page > total_pages:
            current_page = 1
        elif current_page < 1:
            current_page = 1
        
        # Update context with current page
        context.user_data['all_users_page'] = current_page
        
        # Get users for current page
        page_users = self.get_page_items(all_users, current_page, USERS_PER_PAGE)
        
        # Create buttons for users on current page with status indicator
        keyboard = []
        for user in page_users:
            status_emoji = {
                'pending': '⏳',
                'approved': '✅', 
                'rejected': '❌'
            }.get(user['status'], '❓')
            
            user_button = f"👤 {status_emoji} {user['full_name']} ({user['phone_number']})"
            user_button = self.truncate_button_text(user_button)
            keyboard.append([user_button])
        
        # Add pagination navigation buttons
        pagination_buttons = self.create_pagination_buttons(current_page, total_pages)
        keyboard.extend(pagination_buttons)
        
        # Add back button
        keyboard.append([BUTTON_BACK_ONE_STEP])
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        # Create header with page info
        if total_pages > 1:
            header_text = f"👤 جميع المستخدمين ({len(all_users)})\n\n📄 الصفحة {current_page} من {total_pages}\n\nاختر مستخدم لعرض التفاصيل:"
        else:
            header_text = ALL_USERS_HEADER.format(count=len(all_users))
        
        await update.message.reply_text(header_text, reply_markup=reply_markup)
    
    async def show_groups_interactive(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show groups as interactive buttons with details"""
        groups = group_manager.get_all_groups()
        
        if not groups:
            await update.message.reply_text(NO_GROUPS_FOUND)
            return
        
        # Create buttons for each group with enhanced formatting
        keyboard = []
        for group in groups:
            # Get user count for this group
            user_count = len(db.get_users_by_group_id(group['id']))
            phone = group.get('phone_number', 'غير متصل')
            balance = group.get('balance', '0.00')
            
            # Enhanced button text with better formatting
            group_button = f"📁 {group['group_name']}\n   👥 {user_count} مستخدم | 💰 {balance}دج"
            keyboard.append([group_button])
        
        keyboard.append([BUTTON_BACK_ONE_STEP])
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        
        header_text = GROUPS_HEADER.format(count=len(groups))
        await update.message.reply_text(header_text, reply_markup=reply_markup)
    
    async def show_settlement_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show settlement system menu"""
        settlement_info = """
💰 نظام التسوية
━━━━━━━━━━━━━━━━━━━━━━━━━
يمكنك استخدام نظام التسوية من خلال:

1️⃣ انقر على "👤 جميع المستخدمين"
2️⃣ اختر مستخدم معتمد لديه تحققات
3️⃣ انقر على "📊 التحققات والتسوية"
4️⃣ اختر "💰 إجراء التسوية"

✅ المميزات:
• تصفير عداد المستخدم
• إنتاج تقرير PDF مفصل
• إرسال التقرير للمستخدم والمشرف
• حفظ سجل التسوية في النظام

💡 التسوية متاحة فقط للمستخدمين المعتمدين الذين لديهم تحققات ناجحة غير مسواة.
"""
        keyboard = [[BUTTON_BACK_ONE_STEP]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text(settlement_info, reply_markup=reply_markup)
    
    async def handle_user_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle when admin selects a user"""
        message_text = update.message.text
        
        # Extract user info from button text
        if "(" in message_text and ")" in message_text:
            phone = message_text.split("(")[1].split(")")[0]
            user_data = db.get_telegram_user_by_phone(phone)
            
            if user_data:
                # Store selected user in context
                context.user_data['selected_user'] = user_data
                
                # Show user action menu
                keyboard = []
                if user_data['status'] == 'pending':
                    keyboard.append([BUTTON_APPROVE_USER, BUTTON_REJECT_USER])
                elif user_data['status'] == 'approved':
                    # Always show settlement button for approved users
                    keyboard.append([BUTTON_USER_VERIFICATIONS_SETTLEMENT])
                    
                    # Add user management options for approved users with groups
                    if user_data.get('group_id'):
                        keyboard.append([BUTTON_REMOVE_FROM_GROUP])
                        keyboard.append([BUTTON_TRANSFER_TO_GROUP])
                
                keyboard.append([BUTTON_BACK_ONE_STEP])
                reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
                
                # Get group info if user is assigned
                group_name = "غير محدد"
                if user_data.get('group_id'):
                    group_info = db.get_group_by_id(user_data['group_id'])
                    if group_info:
                        group_name = group_info['group_name']
                
                user_info = USER_ACTION_MENU.format(
                    name=user_data['full_name'],
                    phone=user_data['phone_number'],
                    telegram_id=user_data['telegram_id'],
                    registration_date=user_data['created_at'][:16],
                    status=f"{user_data['status']} - {group_name}"
                )
                
                await update.message.reply_text(user_info, reply_markup=reply_markup)
    
    async def start_approval_process(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start the approval process by showing group selection"""
        selected_user = context.user_data.get('selected_user')
        if not selected_user:
            await update.message.reply_text("❌ خطأ: لم يتم اختيار مستخدم")
            return
        
        # Get available groups
        groups = group_manager.get_all_groups()
        if not groups:
            await update.message.reply_text("❌ لا توجد مجموعات متاحة")
            return
        
        # Show group selection
        keyboard = []
        for group in groups:
            user_count = len(db.get_users_by_group_id(group['id']))
            group_button = f"📁 {group['group_name']} (👥{user_count})"
            keyboard.append([group_button])
        
        keyboard.append([BUTTON_CANCEL_ACTION])
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        group_selection_text = GROUP_SELECTION_MENU.format(name=selected_user['full_name'])
        await update.message.reply_text(group_selection_text, reply_markup=reply_markup)
    
    async def handle_group_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle when admin selects a group - either for viewing details or user approval"""
        message_text = update.message.text
        selected_user = context.user_data.get('selected_user')
        
        # Extract group name from button text
        if "📁" in message_text:
            # Check if this is the new enhanced format (with newline) or old format
            if "\n" in message_text and " مستخدم |" in message_text:
                # New enhanced format: "📁 GroupName\n   👥 X مستخدم | 💰 Ydج"
                group_name = message_text.split("📁 ")[1].split("\n")[0].strip()
                await self.show_group_details(update, context, group_name)
            elif " | " in message_text:
                # Old format for compatibility: "📁 GroupName | 👥X | 💰Ydج"
                group_name = message_text.split("📁 ")[1].split(" | ")[0]
                await self.show_group_details(update, context, group_name)
            elif " (" in message_text:
                # This could be group selection for user approval OR transfer
                if not selected_user:
                    await update.message.reply_text("❌ خطأ: لم يتم اختيار مستخدم")
                    return
                
                group_name = message_text.split("📁 ")[1].split(" (")[0]
                
                # Find group by name
                groups = group_manager.get_all_groups()
                selected_group = next((g for g in groups if g['group_name'] == group_name), None)
                
                if selected_group:
                    # Check if this is for transfer (user already has group) or approval (pending user)
                    if selected_user['status'] == 'pending':
                        # This is for approval
                        context.user_data['selected_group'] = selected_group
                        
                        # Show confirmation
                        keyboard = [[BUTTON_CONFIRM_ACTION, BUTTON_CANCEL_ACTION]]
                        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
                        
                        confirmation_text = CONFIRM_USER_APPROVAL.format(
                            name=selected_user['full_name'],
                            group_name=group_name
                        )
                        
                        await update.message.reply_text(confirmation_text, reply_markup=reply_markup)
                    
                    elif selected_user['status'] == 'approved' and selected_user.get('group_id'):
                        # This is for transfer
                        context.user_data['selected_transfer_group'] = {
                            'id': selected_group['id'],
                            'name': group_name
                        }
                        
                        # Get current group info
                        old_group_info = db.get_group_by_id(selected_user['group_id'])
                        old_group_name = old_group_info['group_name'] if old_group_info else "غير محدد"
                        
                        # Show transfer confirmation
                        confirmation_text = USER_TRANSFER_CONFIRM.format(
                            user_name=selected_user['full_name'],
                            user_phone=selected_user['phone_number'],
                            old_group=old_group_name,
                            new_group=group_name
                        )
                        
                        keyboard = [[BUTTON_CONFIRM_TRANSFER, BUTTON_CANCEL_ACTION]]
                        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
                        
                        await update.message.reply_text(confirmation_text, reply_markup=reply_markup)
            else:
                # Fallback: try to extract group name after 📁
                parts = message_text.split("📁 ")
                if len(parts) > 1:
                    group_name = parts[1].strip()
                    await self.show_group_details(update, context, group_name)
    
    async def show_group_details(self, update: Update, context: ContextTypes.DEFAULT_TYPE, group_name: str):
        """Show detailed information about a specific group"""
        try:
            # Find group by name
            groups = group_manager.get_all_groups()
            group = next((g for g in groups if g['group_name'] == group_name), None)
            
            if not group:
                await update.message.reply_text("❌ لم يتم العثور على المجموعة")
                return
            
            # Get users in this group
            users_in_group = db.get_users_by_group_id(group['id'])
            user_count = len(users_in_group)
            
            # Get group details
            phone = group.get('phone_number', 'غير متصل')
            balance = group.get('balance', '0.00')
            imei = group.get('imei', 'غير متاح')
            status = group.get('status', 'غير معروف')
            
            # Format group details with improved styling
            group_details = GROUP_DETAILS.format(
                group_name=group_name,
                phone_number=phone,
                user_count=user_count,
                balance=balance,
                imei=imei[-8:] if len(imei) > 8 else imei,
                status=status
            )
            
            # Build user preview (show up to 5 users in summary)
            users_preview = ""
            if users_in_group:
                users_preview += "👥 آخر المستخدمين المسجلين:\n"
                for i, user in enumerate(users_in_group[:5]):  # Show up to 5 users in preview
                    status_emoji = {
                        'pending': '⏳',
                        'approved': '✅',
                        'rejected': '❌'
                    }.get(user.get('status', 'approved'), '✅')
                    
                    users_preview += f"{i+1}. {status_emoji} {user['full_name']}\n"
                    users_preview += f"   📞 {user['phone_number']}\n"
                
                if user_count > 5:
                    users_preview += f"\n... و {user_count - 5} مستخدمين آخرين"
            else:
                users_preview = "👥 لا يوجد مستخدمين في هذه المجموعة بعد"
            
            # Combine messages
            full_message = group_details + "\n" + users_preview
            
            # Store group info for navigation
            context.user_data['current_group'] = {
                'id': group['id'],
                'name': group_name,
                'original_group_data': group
            }
            
            # Create enhanced buttons with user management option
            keyboard = [
                [BUTTON_CHECK_BALANCE],
                [BUTTON_VIEW_GROUP_USERS],  # New button to view all users
                [BUTTON_RENAME_GROUP], 
                [BUTTON_BACK_ONE_STEP]
            ]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
            
            await update.message.reply_text(full_message, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error showing group details: {e}")
            await update.message.reply_text("❌ حدث خطأ أثناء عرض تفاصيل المجموعة. الرجاء المحاولة مرة أخرى.")
    
    async def show_group_users(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show all users in the current group with pagination"""
        try:
            current_group = context.user_data.get('current_group')
            if not current_group:
                await update.message.reply_text("❌ خطأ: لم يتم اختيار مجموعة")
                return
            
            group_id = current_group['id']
            group_name = current_group['name']
            
            # Get all users in this group
            users_in_group = db.get_users_by_group_id(group_id)
            
            if not users_in_group:
                await update.message.reply_text(
                    NO_USERS_IN_GROUP.format(group_name=group_name)
                )
                return
            
            # Pagination setup
            page = context.user_data.get('current_page', 1)
            users_per_page = 8
            total_users = len(users_in_group)
            total_pages = (total_users + users_per_page - 1) // users_per_page
            
            # Calculate start and end indices
            start_idx = (page - 1) * users_per_page
            end_idx = min(start_idx + users_per_page, total_users)
            page_users = users_in_group[start_idx:end_idx]
            
            # Create header message
            header_message = GROUP_USERS_HEADER.format(
                group_name=group_name,
                total_users=total_users,
                current_page=page,
                total_pages=total_pages
            )
            
            # Create user buttons
            keyboard = []
            for user in page_users:
                status_emoji = {
                    'pending': '⏳',
                    'approved': '✅', 
                    'rejected': '❌'
                }.get(user.get('status', 'approved'), '✅')
                
                # Create user button with name and phone for identification
                user_button = f"{status_emoji} {user['full_name']} ({user['phone_number']})"
                keyboard.append([user_button])
            
            # Add navigation buttons
            nav_buttons = []
            if page > 1:
                nav_buttons.append(BUTTON_PREV_PAGE)
            if page < total_pages:
                nav_buttons.append(BUTTON_NEXT_PAGE)
            
            if nav_buttons:
                keyboard.append(nav_buttons)
            
            # Add back button
            keyboard.append([BUTTON_BACK_TO_GROUP])
            
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
            
            await update.message.reply_text(header_message, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error showing group users: {e}")
            await update.message.reply_text("❌ حدث خطأ أثناء عرض المستخدمين. الرجاء المحاولة مرة أخرى.")
    
    async def show_user_details_from_group(self, update: Update, context: ContextTypes.DEFAULT_TYPE, user_phone: str):
        """Show user details when selected from group users list"""
        try:
            current_group = context.user_data.get('current_group')
            if not current_group:
                await update.message.reply_text("❌ خطأ: لم يتم اختيار مجموعة")
                return
            
            # Get user by phone number
            user_data = db.get_telegram_user_by_phone(user_phone)
            if not user_data:
                await update.message.reply_text("❌ لم يتم العثور على المستخدم")
                return
            
            # Store selected user for further actions
            context.user_data['selected_user'] = user_data
            
            # Get user details
            status_text = {
                'pending': '⏳ معلق',
                'approved': '✅ مُعتمد',
                'rejected': '❌ مرفوض'
            }.get(user_data.get('status', 'approved'), '✅ مُعتمد')
            
            verified_balance = user_data.get('verified_balance', 0.0)
            
            # Format user details
            user_details = GROUP_USER_DETAILS.format(
                group_name=current_group['name'],
                user_name=user_data['full_name'],
                user_phone=user_data['phone_number'],
                telegram_id=user_data['telegram_id'],
                registration_date=user_data['created_at'][:16],
                status=status_text,
                verified_balance=verified_balance
            )
            
            # Create action buttons based on user status
            keyboard = []
            
            if user_data['status'] == 'approved':
                # Settlement button always available for approved users
                keyboard.append([BUTTON_USER_VERIFICATIONS_SETTLEMENT])
                
                # Management buttons
                keyboard.append([BUTTON_TRANSFER_TO_GROUP, BUTTON_REMOVE_FROM_GROUP])
            elif user_data['status'] == 'pending':
                # Approval actions for pending users
                keyboard.append([BUTTON_APPROVE_USER, BUTTON_REJECT_USER])
            
            # Navigation buttons
            keyboard.append([BUTTON_BACK_TO_GROUP])
            
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
            
            await update.message.reply_text(user_details, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error showing user details from group: {e}")
            await update.message.reply_text("❌ حدث خطأ أثناء عرض تفاصيل المستخدم. الرجاء المحاولة مرة أخرى.")

    async def handle_admin_group_balance_check(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """معالج فحص رصيد المجموعة للإداريين"""
        try:
            current_group = context.user_data.get('current_group')
            if not current_group:
                await update.message.reply_text("❌ خطأ: لم يتم اختيار مجموعة")
                return
            
            group_id = current_group['id']
            group_name = current_group['name']
            
            logger.info(f"🔍 Admin checking balance for group {group_id} ({group_name})")
            
            # Send processing message
            processing_msg = await update.message.reply_text(BALANCE_CHECK_PROCESSING)
            
            # Check balance via service
            result = await balance_service.check_group_balance(group_id)
            
            # Delete processing message
            try:
                await processing_msg.delete()
            except Exception as e:
                logger.warning(f"Could not delete processing message: {e}")
            
            # Send result
            if result['success']:
                success_message = f"📁 **{group_name}**\n\n" + BALANCE_CHECK_SUCCESS.format(**result['data'])
                await update.message.reply_text(success_message)
                logger.info(f"✅ Balance check successful for group {group_id}")
            else:
                await update.message.reply_text(result.get('message', BALANCE_CHECK_FAILED))
                logger.warning(f"❌ Balance check failed for group {group_id}")
                
        except Exception as e:
            logger.error(f"Error in handle_admin_group_balance_check: {e}")
            # Try to delete processing message if it exists
            try:
                if 'processing_msg' in locals():
                    await processing_msg.delete()
            except:
                pass
            await update.message.reply_text(BALANCE_CHECK_FAILED)
    
    async def handle_group_rename_request(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle group rename button click"""
        current_group = context.user_data.get('current_group')
        
        if not current_group:
            await update.message.reply_text("❌ خطأ: لم يتم اختيار مجموعة")
            await self.show_admin_menu(update, context)
            return ConversationHandler.END
        
        # Show rename request message with enhanced formatting
        message = GROUP_RENAME_REQUEST.format(current_name=current_group['name'])
        
        # Remove keyboard to get text input
        await update.message.reply_text(
            message, 
            reply_markup=ReplyKeyboardRemove()
        )
        
        return WAITING_FOR_GROUP_NAME
    
    async def handle_new_group_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle new group name input"""
        new_name = update.message.text.strip()
        current_group = context.user_data.get('current_group')
        
        if not current_group:
            await update.message.reply_text("❌ خطأ: انتهت الجلسة")
            await self.show_admin_menu(update, context)
            return ConversationHandler.END
        
        # Validate group name
        validation_error = self._validate_group_name(new_name)
        if validation_error:
            await update.message.reply_text(GROUP_NAME_VALIDATION_ERROR)
            return WAITING_FOR_GROUP_NAME
        
        # Check if name already exists
        existing_groups = group_manager.get_all_groups()
        if any(g['group_name'].lower() == new_name.lower() and g['id'] != current_group['id'] for g in existing_groups):
            await update.message.reply_text(
                GROUP_NAME_VALIDATION_ERROR.replace(
                    "📝 شروط اسم المجموعة:\n• يجب أن يكون بين 3 و 50 حرف\n• يجب ألا يحتوي على رموز خاصة\n• يجب ألا يحتوي على أرقام في البداية",
                    "❌ اسم المجموعة موجود بالفعل"
                )
            )
            return WAITING_FOR_GROUP_NAME
        
        # Try to update group name
        try:
            success = group_manager.update_group_name(current_group['id'], new_name)
            
            if success:
                # Show success message
                success_message = GROUP_RENAME_SUCCESS.format(
                    old_name=current_group['name'],
                    new_name=new_name
                )
                await update.message.reply_text(success_message)
                
                # Clear user data and return to admin menu
                context.user_data.clear()
                await self.show_admin_menu(update, context)
                
            else:
                # Show error message
                error_message = GROUP_RENAME_ERROR.format(
                    error_message="فشل في تحديث قاعدة البيانات"
                )
                await update.message.reply_text(error_message)
                return WAITING_FOR_GROUP_NAME
                
        except Exception as e:
            logger.error(f"Error renaming group: {e}")
            error_message = GROUP_RENAME_ERROR.format(
                error_message=f"خطأ تقني: {str(e)}"
            )
            await update.message.reply_text(error_message)
            return WAITING_FOR_GROUP_NAME
        
        return ConversationHandler.END
    
    def _validate_group_name(self, name: str) -> str:
        """Validate group name and return error message if invalid"""
        if not name:
            return "اسم المجموعة فارغ"
        
        if len(name) < 3:
            return "اسم المجموعة قصير جداً"
        
        if len(name) > 50:
            return "اسم المجموعة طويل جداً"
        
        # Check for invalid characters (allow Arabic, English, spaces, numbers, and basic punctuation)
        import re
        if not re.match(r'^[\u0600-\u06FF\u0750-\u077Fa-zA-Z0-9\s\-_().]+$', name):
            return "اسم المجموعة يحتوي على رموز غير مسموحة"
        
        # Check if starts with number
        if name[0].isdigit():
            return "اسم المجموعة لا يجب أن يبدأ برقم"
        
        return None  # No error
    
    async def confirm_user_approval(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Confirm and execute user approval"""
        selected_user = context.user_data.get('selected_user')
        selected_group = context.user_data.get('selected_group')
        
        if not selected_user or not selected_group:
            await update.message.reply_text("❌ خطأ: بيانات غير مكتملة")
            return
        
        try:
            # Update user status and assign to group
            success = db.update_telegram_user_status(
                selected_user['telegram_id'], 
                'approved', 
                selected_group['id']
            )
            
            if success:
                # Get group info for notification
                group_info = group_manager.get_group_with_modem_info(selected_group['id'])
                sim_phone = group_info.get('phone_number', 'غير متصل')
                current_balance = group_info.get('balance', '0.00')
                
                # Notify user
                await self.application.bot.send_message(
                    chat_id=selected_user['telegram_id'],
                    text=USER_APPROVED_NOTIFICATION.format(
                        group_name=selected_group['group_name'],
                        sim_number=sim_phone,
                        current_balance=current_balance
                    )
                )
                
                await update.message.reply_text(
                    f"✅ تم قبول المستخدم {selected_user['full_name']} في مجموعة {selected_group['group_name']}"
                )
                
                # Clean up context and return to admin menu
                context.user_data.clear()
                await self.show_admin_menu(update, context)
                
            else:
                await update.message.reply_text("❌ فشل في قبول المستخدم")
                
        except Exception as e:
            logger.error(f"Error approving user: {e}")
            await update.message.reply_text(f"❌ خطأ: {str(e)}")
    
    async def reject_selected_user(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Reject selected user and delete from database"""
        selected_user = context.user_data.get('selected_user')
        
        if not selected_user:
            await update.message.reply_text("❌ خطأ: لم يتم اختيار مستخدم")
            return
        
        try:
            # Delete user from database
            success = db.delete_telegram_user(selected_user['telegram_id'])
            
            if success:
                # Notify user to re-register
                await self.application.bot.send_message(
                    chat_id=selected_user['telegram_id'],
                    text=USER_REJECTED_NOTIFICATION
                )
                
                await update.message.reply_text(
                    f"❌ تم رفض وحذف المستخدم {selected_user['full_name']}"
                )
                
                # Clean up context and return to admin menu
                context.user_data.clear()
                await self.show_admin_menu(update, context)
                
            else:
                await update.message.reply_text("❌ فشل في رفض المستخدم")
                
        except Exception as e:
            logger.error(f"Error rejecting user: {e}")
            await update.message.reply_text(f"❌ خطأ: {str(e)}")
    
    async def cancel_current_action(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Cancel current action and return to admin menu"""
        context.user_data.clear()
        await update.message.reply_text("❌ تم إلغاء العملية")
        await self.show_admin_menu(update, context)
        """Show all users with their status and group info"""
        all_users = db.get_all_telegram_users()
        
        if not all_users:
            await update.message.reply_text("❌ لا يوجد مستخدمين")
            return
        
        message = "👥 جميع المستخدمين:\n\n"
        for user in all_users:
            status_emoji = {
                'pending': '⏳',
                'approved': '✅', 
                'rejected': '❌'
            }.get(user['status'], '❓')
            
            # Get group info
            group_name = "غير محدد"
            if user.get('group_id'):
                group_info = db.get_group_by_id(user['group_id'])
                if group_info:
                    group_name = group_info['group_name']
            
            message += f"{status_emoji} {user['full_name']}\n"
            message += f"  📞 {user['phone_number']}\n"
            message += f"  🆔 {user['telegram_id']}\n"
            message += f"  📁 {group_name}\n"
            
            if user['status'] == 'pending':
                message += f"  💬 /approve {user['telegram_id']} | /reject {user['telegram_id']}\n"
            
            message += "\n"
        
        await update.message.reply_text(message)
        """Show pending users for approval"""
        pending_users = db.get_pending_telegram_users()
        
        if not pending_users:
            await update.message.reply_text("✅ لا يوجد مستخدمين معلقين")
            return
        
        message = "👥 المستخدمين المعلقين:\n\n"
        for user in pending_users:
            message += f"• {user['full_name']}\n"
            message += f"  📞 {user['phone_number']}\n"
            message += f"  🆔 {user['telegram_id']}\n"
            message += f"  📅 {user['created_at'][:16]}\n"
            message += f"  💬 /approve {user['telegram_id']} | /reject {user['telegram_id']}\n\n"
        
        await update.message.reply_text(message)
    
    async def show_approved_users(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show approved users"""
        approved_users = db.get_approved_telegram_users()
        
        if not approved_users:
            await update.message.reply_text("❌ لا يوجد مستخدمين معتمدين")
            return
        
        message = "✅ المستخدمين المعتمدين:\n\n"
        for user in approved_users:
            message += f"• {user['full_name']}\n"
            message += f"  📞 {user['phone_number']}\n"
            message += f"  🆔 {user['telegram_id']}\n"
            message += f"  📁 {user.get('group_name', 'غير محدد')}\n"
            message += f"  📱 {user.get('sim_phone', 'غير متصل')}\n"
            message += f"  💰 {user.get('verified_balance', 0.0)} دج\n\n"
        
        await update.message.reply_text(message)
    
    async def show_groups(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show all groups"""
        groups = group_manager.get_all_groups()
        
        if not groups:
            await update.message.reply_text("❌ لا يوجد مجموعات")
            return
        
        message = "📁 جميع المجموعات:\n\n"
        for group in groups:
            message += f"📁 {group['group_name']}\n"
            message += f"  📱 {group.get('phone_number', 'غير متصل')}\n"
            message += f"  💰 {group.get('balance', '0.00')} دج\n"
            message += f"  🆔 IMEI: {group['imei'][-6:]}\n\n"
        
        await update.message.reply_text(message)
    
    async def show_statistics(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show system statistics"""
        all_users = db.get_all_telegram_users()
        pending_count = len([u for u in all_users if u['status'] == 'pending'])
        approved_count = len([u for u in all_users if u['status'] == 'approved'])
        rejected_count = len([u for u in all_users if u['status'] == 'rejected'])
        
        groups = group_manager.get_all_groups()
        
        stats_message = f"""
📊 إحصائيات النظام

👥 إجمالي المستخدمين: {len(all_users)}
⏳ المعلقين: {pending_count}
✅ المعتمدين: {approved_count}
❌ المرفوضين: {rejected_count}

📁 إجمالي المجموعات: {len(groups)}
📱 الشرائح النشطة: {len([g for g in groups if g.get('phone_number')])}

🤖 حالة البوت: نشط ✅
"""
        
        await update.message.reply_text(stats_message)
    
    async def approve_user_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Approve user command: /approve telegram_id"""
        try:
            parts = update.message.text.split()
            if len(parts) != 2:
                await update.message.reply_text("❌ استخدم: /approve [telegram_id]")
                return
            
            telegram_id = int(parts[1])
            user_data = db.get_telegram_user_by_id(telegram_id)
            
            if not user_data:
                await update.message.reply_text("❌ المستخدم غير موجود")
                return
            
            if user_data['status'] != 'pending':
                await update.message.reply_text(f"❌ حالة المستخدم: {user_data['status']}")
                return
            
            # Get available groups
            groups = group_manager.get_all_groups()
            if not groups:
                await update.message.reply_text("❌ لا توجد مجموعات متاحة")
                return
            
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
                await self.application.bot.send_message(
                    chat_id=telegram_id,
                    text=USER_APPROVED_NOTIFICATION.format(
                        group_name=groups[0]['group_name'],
                        sim_number=sim_phone,
                        current_balance=current_balance
                    )
                )
                
                await update.message.reply_text(f"✅ تم قبول المستخدم {user_data['full_name']}")
            else:
                await update.message.reply_text("❌ فشل في قبول المستخدم")
                
        except Exception as e:
            logger.error(f"Error approving user: {e}")
            await update.message.reply_text(f"❌ خطأ: {str(e)}")
    
    async def reject_user_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Reject user command: /reject telegram_id - Delete from DB and ask to re-register"""
        try:
            parts = update.message.text.split()
            if len(parts) != 2:
                await update.message.reply_text("❌ استخدم: /reject [telegram_id]")
                return
            
            telegram_id = int(parts[1])
            user_data = db.get_telegram_user_by_id(telegram_id)
            
            if not user_data:
                await update.message.reply_text("❌ المستخدم غير موجود")
                return
            
            # Delete user from database
            success = db.delete_telegram_user(telegram_id)
            
            if success:
                # Notify user to re-register with correct info
                await self.application.bot.send_message(
                    chat_id=telegram_id,
                    text="❌ تم رفض طلب التسجيل\n\nالرجاء إعادة التسجيل بمعلومات صحيحة.\nاضغط /start للتسجيل مرة أخرى."
                )
                
                await update.message.reply_text(f"❌ تم رفض وحذف المستخدم {user_data['full_name']}")
            else:
                await update.message.reply_text("❌ فشل في رفض المستخدم")
                
        except Exception as e:
            logger.error(f"Error rejecting user: {e}")
            await update.message.reply_text(f"❌ خطأ: {str(e)}")
    
    async def reply_to_user_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Admin reply to user command: /reply user_id message"""
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("❌ غير مسموح لك بهذا الأمر")
            return
        
        try:
            parts = update.message.text.split(maxsplit=2)
            if len(parts) < 3:
                await update.message.reply_text("❌ استخدم: /reply [user_id] [رسالتك]")
                return
            
            user_id = int(parts[1])
            reply_message = parts[2]
            
            # Check if user exists
            user_data = db.get_telegram_user_by_id(user_id)
            if not user_data:
                await update.message.reply_text("❌ لم يتم العثور على المستخدم")
                return
            
            # Send reply to user
            admin_reply = f"""
📨 رد من المشرف:

{reply_message}

---
يمكنك الرد مرة أخرى باستخدام زر "📞 التواصل مع المشرف"
"""
            
            await self.application.bot.send_message(
                chat_id=user_id,
                text=admin_reply
            )
            
            await update.message.reply_text(f"✅ تم إرسال الرد إلى {user_data['full_name']}")
            
        except ValueError:
            await update.message.reply_text("❌ معرف المستخدم يجب أن يكون رقماً")
        except Exception as e:
            logger.error(f"Error in reply command: {e}")
            await update.message.reply_text(f"❌ خطأ: {str(e)}")
    
    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Cancel current operation"""
        await update.message.reply_text("❌ تم إلغاء العملية", reply_markup=ReplyKeyboardRemove())
        if self.is_admin(update.effective_user.id):
            await self.show_admin_menu(update, context)
        return ConversationHandler.END

    # ============================================================================
    # SETTLEMENT FUNCTIONS
    # ============================================================================
    
    async def show_user_settlement_details(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show user's settlement details and options"""
        selected_user = context.user_data.get('selected_user')
        if not selected_user:
            await update.message.reply_text("❌ خطأ: لم يتم اختيار مستخدم")
            return
        
        try:
            # Get settlement summary from service
            settlement_summary = self.settlement_service.get_user_settlement_summary(selected_user['telegram_id'])
            
            if not settlement_summary:
                # No verifications to settle - show empty state but still show options
                message = NO_VERIFICATIONS_TO_SETTLE.format(user_name=selected_user['full_name'])
                
                # Show limited options when no verifications
                keyboard = [
                    [BUTTON_VIEW_ALL_VERIFICATIONS, BUTTON_SETTLEMENT_HISTORY],
                    [BUTTON_BACK_ONE_STEP]
                ]
                reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
                await update.message.reply_text(message, reply_markup=reply_markup)
                return
            
            # Get user's group info
            group_info = db.get_group_by_id(selected_user['group_id'])
            group_name = group_info['group_name'] if group_info else "غير محدد"
            
            # Format recent verifications
            recent_verifications = ""
            for i, verification in enumerate(settlement_summary['verifications'][:5], 1):
                recent_verifications += f"{i}. {verification['amount']} دج - {verification['created_at'][:16]}\n"
            
            if not recent_verifications:
                recent_verifications = "لا توجد تحققات حديثة"
            
            # Show settlement details
            message = USER_SETTLEMENT_DETAILS.format(
                user_name=selected_user['full_name'],
                user_phone=selected_user['phone_number'],
                sim_number=selected_user['phone_number'],  # Assuming sim_number same as phone
                group_name=group_name,
                current_balance=settlement_summary['current_balance'],
                total_verifications=settlement_summary['total_verifications'],
                total_amount=settlement_summary['total_amount'],
                period_start=settlement_summary['period_start'],
                period_end=settlement_summary['period_end'],
                recent_verifications=recent_verifications
            )
            
            # Show action buttons (with settlement processing only if verifications exist)
            keyboard = [
                [BUTTON_PROCESS_SETTLEMENT],
                [BUTTON_VIEW_ALL_VERIFICATIONS, BUTTON_SETTLEMENT_HISTORY],
                [BUTTON_BACK_ONE_STEP]
            ]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            
            await update.message.reply_text(message, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error showing settlement details: {e}")
            await update.message.reply_text("❌ حدث خطأ في عرض تفاصيل التسوية")
    
    async def handle_settlement_confirmation(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle settlement confirmation request"""
        selected_user = context.user_data.get('selected_user')
        if not selected_user:
            await update.message.reply_text("❌ خطأ: لم يتم اختيار مستخدم")
            return
        
        try:
            # Get settlement summary
            settlement_summary = self.settlement_service.get_user_settlement_summary(selected_user['telegram_id'])
            
            if not settlement_summary:
                await update.message.reply_text("❌ لا توجد تحققات للتسوية")
                return
            
            # Show confirmation message
            message = USER_SETTLEMENT_CONFIRMATION.format(
                user_name=selected_user['full_name'],
                user_phone=selected_user['phone_number'],
                sim_number=selected_user['phone_number'],
                total_verifications=settlement_summary['total_verifications'],
                total_amount=settlement_summary['total_amount'],
                period_start=settlement_summary['period_start'],
                period_end=settlement_summary['period_end']
            )
            
            keyboard = [
                [BUTTON_CONFIRM_SETTLEMENT],
                [BUTTON_CANCEL_SETTLEMENT]
            ]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            
            await update.message.reply_text(message, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error in settlement confirmation: {e}")
            await update.message.reply_text("❌ حدث خطأ في تأكيد التسوية")
    
    async def process_user_settlement(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Process the actual settlement"""
        selected_user = context.user_data.get('selected_user')
        admin_user_id = update.effective_user.id
        
        if not selected_user:
            await update.message.reply_text("❌ خطأ: لم يتم اختيار مستخدم")
            return
        
        try:
            # Process settlement
            settlement_result = await self.settlement_service.process_user_settlement(
                telegram_user_id=selected_user['telegram_id'],
                admin_telegram_id=admin_user_id
            )
            
            if settlement_result['success']:
                # Settlement successful
                message = USER_SETTLEMENT_SUCCESS.format(
                    user_name=selected_user['full_name'],
                    total_amount=settlement_result['total_amount'],
                    settlement_date=datetime.now().strftime('%Y-%m-%d %H:%M'),
                    settlement_id=settlement_result['settlement_id']
                )
                
                # Send notification to user
                user_notification = USER_SETTLEMENT_NOTIFICATION.format(
                    total_amount=settlement_result['total_amount'],
                    total_verifications=settlement_result['total_verifications']
                )
                
                # Always send PDF if available
                pdf_sent_to_admin = False
                pdf_sent_to_user = False
                
                if settlement_result.get('pdf_file_path') and os.path.exists(settlement_result['pdf_file_path']):
                    try:
                        # Send PDF report to admin
                        await context.bot.send_document(
                            chat_id=admin_user_id,
                            document=open(settlement_result['pdf_file_path'], 'rb'),
                            caption=f"📄 تقرير تسوية #{settlement_result['settlement_id']}"
                        )
                        pdf_sent_to_admin = True
                        logger.info(f"PDF sent to admin for settlement {settlement_result['settlement_id']}")
                    except Exception as e:
                        logger.error(f"Error sending PDF to admin: {e}")
                
                try:
                    # Send notification to user
                    await context.bot.send_message(
                        chat_id=selected_user['telegram_id'],
                        text=user_notification
                    )
                    
                    # Send PDF to user if available
                    if settlement_result.get('pdf_file_path') and os.path.exists(settlement_result['pdf_file_path']):
                        await context.bot.send_document(
                            chat_id=selected_user['telegram_id'],
                            document=open(settlement_result['pdf_file_path'], 'rb'),
                            caption="📄 تقرير تسويتك المفصل"
                        )
                        pdf_sent_to_user = True
                        logger.info(f"PDF sent to user for settlement {settlement_result['settlement_id']}")
                    
                except Exception as e:
                    logger.error(f"Error sending notifications to user: {e}")
                    message += "\n\n⚠️ تم إجراء التسوية لكن حدث خطأ في إرسال الإشعار للمستخدم"
                
                # Add PDF status to admin message
                if pdf_sent_to_admin and pdf_sent_to_user:
                    message += "\n\n✅ تم إرسال PDF للمشرف والمستخدم"
                elif pdf_sent_to_admin:
                    message += "\n\n✅ تم إرسال PDF للمشرف | ⚠️ خطأ في الإرسال للمستخدم"
                elif pdf_sent_to_user:
                    message += "\n\n⚠️ خطأ في إرسال PDF للمشرف | ✅ تم الإرسال للمستخدم"
                else:
                    message += "\n\n⚠️ خطأ في إرسال PDF"
                
                keyboard = [[BUTTON_BACK_ONE_STEP]]
                reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
                await update.message.reply_text(message, reply_markup=reply_markup)
                
            else:
                await update.message.reply_text(f"❌ فشل في إجراء التسوية: {settlement_result.get('message', 'خطأ غير معروف')}")
                
        except Exception as e:
            logger.error(f"Error processing settlement: {e}")
            await update.message.reply_text("❌ حدث خطأ في معالجة التسوية")

    async def show_user_all_verifications(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show all verifications for selected user"""
        selected_user = context.user_data.get('selected_user')
        if not selected_user:
            await update.message.reply_text("❌ خطأ: لم يتم اختيار مستخدم")
            return
        
        try:
            # Get all verifications for user
            verifications = db.get_user_verifications(selected_user['telegram_id'], limit=50)
            
            if not verifications:
                message = f"📄 سجل التحققات\n\n👤 المستخدم: {selected_user['full_name']}\n📊 الحالة: لا توجد تحققات"
            else:
                message = f"📄 سجل التحققات\n\n👤 المستخدم: {selected_user['full_name']}\n🔢 إجمالي التحققات: {len(verifications)}\n\n"
                
                for i, verification in enumerate(verifications[:20], 1):  # Show first 20
                    status_icon = "✅" if verification['result'] == 'success' else "❌"
                    settlement_status = "✅ مسوى" if verification.get('settlement_id') else "⏳ غير مسوى"
                    
                    message += f"{i}. {status_icon} {verification['amount']} دج\n"
                    message += f"   📅 {verification['created_at'][:16]}\n"
                    message += f"   📊 {settlement_status}\n\n"
                
                if len(verifications) > 20:
                    message += f"... و {len(verifications) - 20} تحقق إضافي"
            
            keyboard = [[BUTTON_BACK_ONE_STEP]]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            await update.message.reply_text(message, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error showing user verifications: {e}")
            await update.message.reply_text("❌ حدث خطأ في عرض التحققات")

    async def show_user_settlement_history(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show settlement history for selected user"""
        selected_user = context.user_data.get('selected_user')
        if not selected_user:
            await update.message.reply_text("❌ خطأ: لم يتم اختيار مستخدم")
            return
        
        try:
            # Get settlement history
            settlements = db.get_user_settlements_history(selected_user['telegram_id'])
            
            if not settlements:
                message = SETTLEMENT_HISTORY_EMPTY.format(user_name=selected_user['full_name'])
            else:
                message = f"📈 سجل التسويات السابقة\n\n👤 المستخدم: {selected_user['full_name']}\n🔢 إجمالي التسويات: {len(settlements)}\n\n"
                
                for i, settlement in enumerate(settlements, 1):
                    message += f"{i}. 🆔 التسوية #{settlement['id']}\n"
                    message += f"   📅 التاريخ: {settlement['settlement_date'][:16]}\n"
                    message += f"   💰 المبلغ: {settlement['total_amount']:.2f} دج\n"
                    message += f"   🔢 التحققات: {settlement['total_verifications']} تحقق\n\n"
                
                # Send PDF reports for all settlements
                for settlement in settlements:
                    pdf_sent = False
                    pdf_path = settlement.get('pdf_file_path')
                    
                    # Check if PDF exists, if not create it
                    if not pdf_path or not os.path.exists(pdf_path):
                        try:
                            # Generate PDF for this settlement
                            logger.info(f"Generating enhanced PDF for settlement {settlement['id']}")
                            
                            # Get settlement verifications
                            settlement_verifications = db.get_verifications_by_settlement(settlement['id'])
                            
                            if settlement_verifications:
                                from telegram_bot.utils.pdf_generator import PDFGenerator
                                pdf_generator = PDFGenerator()
                                
                                # Get additional data for enhanced PDF
                                admin_data = None
                                group_data = None
                                sim_data = None
                                
                                try:
                                    # Get admin info
                                    admin_id = settlement.get('admin_telegram_id')
                                    if admin_id:
                                        admin_data = db.get_telegram_user_by_id(admin_id)
                                    
                                    # Get group info
                                    if selected_user.get('group_id'):
                                        group_data = db.get_group_by_id(selected_user['group_id'])
                                    
                                    # Get SIM info
                                    sim_data = db.get_user_sim_by_telegram_id(selected_user['telegram_id'])
                                    
                                except Exception as data_error:
                                    logger.warning(f"Could not fetch additional data for PDF: {data_error}")
                                
                                pdf_path = pdf_generator.generate_settlement_report_sync(
                                    user_data=selected_user,
                                    verifications=settlement_verifications,
                                    settlement_data=settlement,
                                    admin_data=admin_data,
                                    group_data=group_data,
                                    sim_data=sim_data
                                )
                                
                                if pdf_path and os.path.exists(pdf_path):
                                    # Update settlement with PDF path
                                    db.update_settlement_pdf_path(settlement['id'], pdf_path)
                                    logger.info(f"Generated and saved enhanced PDF for settlement {settlement['id']}")
                                
                        except Exception as e:
                            logger.error(f"Error generating enhanced PDF for settlement {settlement['id']}: {e}")
                    
                    # Try to send the PDF
                    if pdf_path and os.path.exists(pdf_path):
                        try:
                            await context.bot.send_document(
                                chat_id=update.effective_user.id,
                                document=open(pdf_path, 'rb'),
                                caption=f"📄 تقرير التسوية #{settlement['id']} - {settlement['settlement_date'][:10]}"
                            )
                            pdf_sent = True
                            logger.info(f"Successfully sent PDF for settlement {settlement['id']}")
                        except Exception as e:
                            logger.error(f"Error sending settlement PDF {settlement['id']}: {e}")
                    
                    if not pdf_sent:
                        message += f"⚠️ لا يمكن إرسال تقرير التسوية #{settlement['id']}\n"
            
            keyboard = [[BUTTON_BACK_ONE_STEP]]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            await update.message.reply_text(message, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error showing settlement history: {e}")
            await update.message.reply_text("❌ حدث خطأ في عرض سجل التسويات")

    # ============================================================================
    # USER MANAGEMENT FUNCTIONS
    # ============================================================================
    
    async def confirm_user_removal(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show confirmation for removing user from group"""
        selected_user = context.user_data.get('selected_user')
        if not selected_user:
            await update.message.reply_text("❌ خطأ: لم يتم اختيار مستخدم")
            return
        
        if not selected_user.get('group_id'):
            await update.message.reply_text("❌ المستخدم غير مرتبط بأي مجموعة")
            return
        
        # Get group info
        group_info = db.get_group_by_id(selected_user['group_id'])
        group_name = group_info['group_name'] if group_info else "غير محدد"
        
        message = USER_REMOVE_FROM_GROUP_CONFIRM.format(
            user_name=selected_user['full_name'],
            user_phone=selected_user['phone_number'],
            current_group=group_name
        )
        
        keyboard = [
            [BUTTON_CONFIRM_REMOVAL],
            [BUTTON_CANCEL_ACTION]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(message, reply_markup=reply_markup)
    
    async def show_transfer_group_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show group selection for transferring user"""
        selected_user = context.user_data.get('selected_user')
        if not selected_user:
            await update.message.reply_text("❌ خطأ: لم يتم اختيار مستخدم")
            return
        
        if not selected_user.get('group_id'):
            await update.message.reply_text("❌ المستخدم غير مرتبط بأي مجموعة")
            return
        
        # Get current group info
        current_group_info = db.get_group_by_id(selected_user['group_id'])
        current_group_name = current_group_info['group_name'] if current_group_info else "غير محدد"
        
        # Get all groups except current one
        all_groups = group_manager.get_all_groups()
        available_groups = [g for g in all_groups if g['id'] != selected_user['group_id']]
        
        if not available_groups:
            await update.message.reply_text("❌ لا توجد مجموعات أخرى متاحة للنقل")
            return
        
        # Show group selection
        message = USER_TRANSFER_GROUP_SELECT.format(
            user_name=selected_user['full_name'],
            user_phone=selected_user['phone_number'],
            current_group=current_group_name
        )
        
        keyboard = []
        for group in available_groups:
            user_count = len(db.get_users_by_group_id(group['id']))
            group_button = f"📁 {group['group_name']} (👥{user_count})"
            keyboard.append([group_button])
        
        keyboard.append([BUTTON_CANCEL_ACTION])
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(message, reply_markup=reply_markup)
    
    async def process_user_removal(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Process user removal from group"""
        selected_user = context.user_data.get('selected_user')
        if not selected_user:
            await update.message.reply_text("❌ خطأ: لم يتم اختيار مستخدم")
            return
        
        try:
            # Get current group info
            old_group_info = db.get_group_by_id(selected_user['group_id'])
            old_group_name = old_group_info['group_name'] if old_group_info else "غير محدد"
            
            # Remove user from group
            db.update_user_group(selected_user['id'], None)
            
            # Send success message to admin
            success_message = USER_REMOVED_SUCCESS.format(
                user_name=selected_user['full_name'],
                old_group=old_group_name
            )
            
            keyboard = [[BUTTON_BACK_ONE_STEP]]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            await update.message.reply_text(success_message, reply_markup=reply_markup)
            
            # Send notification to user
            user_notification = USER_REMOVAL_NOTIFICATION.format(
                old_group=old_group_name
            )
            
            try:
                await self.application.bot.send_message(
                    chat_id=selected_user['telegram_id'],
                    text=user_notification
                )
            except Exception as e:
                logger.error(f"Failed to notify user about removal: {e}")
            
        except Exception as e:
            logger.error(f"Error removing user from group: {e}")
            await update.message.reply_text("❌ حدث خطأ في إزالة المستخدم")
    
    async def process_user_transfer(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Process user transfer to new group"""
        selected_user = context.user_data.get('selected_user')
        new_group_data = context.user_data.get('selected_transfer_group')
        
        if not selected_user or not new_group_data:
            await update.message.reply_text("❌ خطأ: بيانات غير مكتملة")
            return
        
        try:
            # Get old group info
            old_group_info = db.get_group_by_id(selected_user['group_id'])
            old_group_name = old_group_info['group_name'] if old_group_info else "غير محدد"
            
            # Update user group
            db.update_user_group(selected_user['id'], new_group_data['id'])
            
            # Send success message to admin
            success_message = USER_TRANSFERRED_SUCCESS.format(
                user_name=selected_user['full_name'],
                old_group=old_group_name,
                new_group=new_group_data['name']
            )
            
            keyboard = [[BUTTON_BACK_ONE_STEP]]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            await update.message.reply_text(success_message, reply_markup=reply_markup)
            
            # Send notification to user
            user_notification = USER_TRANSFER_NOTIFICATION.format(
                old_group=old_group_name,
                new_group=new_group_data['name']
            )
            
            try:
                await self.application.bot.send_message(
                    chat_id=selected_user['telegram_id'],
                    text=user_notification
                )
            except Exception as e:
                logger.error(f"Failed to notify user about transfer: {e}")
            
        except Exception as e:
            logger.error(f"Error transferring user: {e}")
            await update.message.reply_text("❌ حدث خطأ في نقل المستخدم")

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Cancel current operation"""
        user_id = update.effective_user.id
        if user_id in self.user_sessions:
            del self.user_sessions[user_id]
        
        # Clear conversation data
        context.user_data.clear()
        
        await update.message.reply_text(
            "تم إلغاء العملية.",
            reply_markup=ReplyKeyboardRemove()
        )
        
        # Check if user is admin
        if self.is_admin(user_id):
            await self.show_admin_menu(update, context)
        else:
            # If user is approved, show main menu
            user_data = db.get_telegram_user_by_id(user_id)
            if user_data and user_data['status'] == 'approved':
                await self.show_main_menu(update, context)
        
        return ConversationHandler.END
    
    # ========================================================================
    # BOT SETUP AND RUNNING
    # ========================================================================
    
    def setup_handlers(self):
        """Setup all bot handlers"""
        
        # Initialize verification handlers
        self.verification_handlers = VerificationHandlers(self)
        
        # Registration conversation handler
        registration_handler = ConversationHandler(
            entry_points=[CommandHandler('start', self.start)],
            states={
                WAITING_FOR_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_name)],
                WAITING_FOR_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_phone)],
            },
            fallbacks=[CommandHandler('cancel', self.cancel)]
        )
        
        # Verification conversation handler
        verification_handler = ConversationHandler(
            entry_points=[MessageHandler(filters.Regex("^💰 التحقق من الرصيد$"), self.verification_handlers.start_verification_process)],
            states={
                WAITING_FOR_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.verification_handlers.handle_amount)],
                WAITING_FOR_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.verification_handlers.handle_date)],
                WAITING_FOR_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.verification_handlers.handle_time)],
                CONFIRM_VERIFICATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.verification_handlers.handle_verification_confirm)],
            },
            fallbacks=[
                CommandHandler('cancel', self.verification_handlers.cancel),
                MessageHandler(filters.Regex("^❌ إلغاء$"), self.verification_handlers.cancel)
            ]
        )
        
        # Group management conversation handler  
        group_management_handler = ConversationHandler(
            entry_points=[MessageHandler(filters.Regex(f'^{BUTTON_RENAME_GROUP}$'), self.handle_group_rename_request)],
            states={
                WAITING_FOR_GROUP_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_new_group_name)],
            },
            fallbacks=[CommandHandler('cancel', self.cancel)]
        )
        
        # Contact admin conversation handler
        contact_admin_handler = ConversationHandler(
            entry_points=[MessageHandler(filters.Regex("^📞 التواصل مع المشرف$"), self.show_contact_admin)],
            states={
                WAITING_FOR_ADMIN_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_admin_contact_message)],
            },
            fallbacks=[
                CommandHandler('cancel', self.cancel),
                MessageHandler(filters.Regex("^❌ إلغاء$"), self.cancel)
            ]
        )
        
        # Add handlers in order of priority
        self.application.add_handler(registration_handler)
        self.application.add_handler(verification_handler)
        self.application.add_handler(group_management_handler)
        self.application.add_handler(contact_admin_handler)
        self.application.add_handler(CommandHandler('admin', self.show_admin_menu))
        self.application.add_handler(CommandHandler('reply', self.reply_to_user_command))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        
        # Add error handler
        self.application.add_error_handler(self.error_handler)
        
        logger.info("Bot handlers setup complete")
    
    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE):
        """Handle errors in the bot"""
        error = context.error
        error_message = str(error).lower()
        
        logger.error(f"Exception while handling an update: {error}")
        
        # Handle specific error types
        if "event loop is closed" in error_message:
            logger.error("Event loop is closed - this is a critical issue that may require bot restart")
            # Don't try to send messages when event loop is closed
            return
            
        elif "network" in error_message or "connection" in error_message:
            logger.warning(f"Network error occurred: {error}")
            # Network errors are usually temporary, just log them
            
        elif "flood" in error_message or "rate" in error_message:
            logger.warning(f"Rate limiting detected: {error}")
            # Rate limit errors don't need user notification
            
        elif "bad request" in error_message:
            logger.warning(f"Bad request to Telegram API: {error}")
            
        else:
            logger.error(f"Unhandled bot error: {error}")
        
        # Try to notify the user if possible and it's a user-facing error
        if (update and hasattr(update, 'effective_message') and 
            update.effective_message and 
            "event loop is closed" not in error_message and
            "network" not in error_message):
            
            try:
                await self._safe_reply(update, "❌ حدث خطأ مؤقت. الرجاء المحاولة مرة أخرى.")
            except Exception as e:
                logger.error(f"Failed to send error message to user: {e}")
    
    async def run(self):
        """Run the bot"""
        try:
            # Create application
            self.application = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
            
            # Setup handlers
            self.setup_handlers()
            
            logger.info("Starting SimPulse Telegram Bot...")
            
            # Start bot
            await self.application.initialize()
            await self.application.start()
            await self.application.updater.start_polling()
            
            logger.info("Bot is running! Press Ctrl+C to stop.")
            
            # Keep running
            try:
                await asyncio.Event().wait()
            except KeyboardInterrupt:
                logger.info("Stopping bot...")
        except Exception as e:
            logger.error(f"Error in bot run: {e}")
        finally:
            try:
                if hasattr(self, 'application') and self.application:
                    await self.application.stop()
                    await self.application.shutdown()
            except Exception as e:
                logger.error(f"Error stopping application: {e}")
    
    def start_bot(self):
        """Start the bot in background thread"""
        if not config.TELEGRAM_BOT_TOKEN:
            logger.error("TELEGRAM_BOT_TOKEN not configured!")
            return
        
        def run_bot():
            try:
                # Create new event loop for this thread
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                # Store reference to loop for safe shutdown
                self._bot_loop = loop
                
                # Run the bot
                loop.run_until_complete(self.run())
            except Exception as e:
                logger.error(f"Bot error: {e}")
            finally:
                try:
                    # Clean shutdown
                    if hasattr(self, '_bot_loop') and not self._bot_loop.is_closed():
                        # Cancel all pending tasks
                        pending = asyncio.all_tasks(self._bot_loop)
                        for task in pending:
                            task.cancel()
                        
                        # Wait for tasks to complete cancellation
                        if pending:
                            self._bot_loop.run_until_complete(
                                asyncio.gather(*pending, return_exceptions=True)
                            )
                        
                        self._bot_loop.close()
                        logger.info("Event loop closed properly")
                except Exception as e:
                    logger.error(f"Error closing event loop: {e}")
        
        self.bot_thread = threading.Thread(target=run_bot, daemon=True)
        self.bot_thread.start()
        logger.info("✅ Telegram Bot started in background thread")
    
    def stop_bot(self):
        """Stop the bot properly to avoid conflicts"""
        try:
            logger.info("Telegram Bot stopping...")
            if hasattr(self, 'application') and self.application:
                # Signal the bot to stop
                if hasattr(self.application, 'updater') and self.application.updater:
                    # Use proper async shutdown to avoid conflicts
                    try:
                        # Create a new event loop for shutdown if needed
                        import asyncio
                        try:
                            loop = asyncio.get_event_loop()
                            if loop.is_closed():
                                loop = asyncio.new_event_loop()
                                asyncio.set_event_loop(loop)
                        except RuntimeError:
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                        
                        # Run shutdown properly
                        loop.run_until_complete(self._async_shutdown())
                        
                    except Exception as e:
                        logger.error(f"Error during graceful shutdown: {e}")
                        # Force stop if graceful shutdown fails
                        if hasattr(self.application, 'updater'):
                            try:
                                self.application.updater.stop()
                            except:
                                pass
                
            # Wait for thread to finish (with timeout)
            if hasattr(self, 'bot_thread') and self.bot_thread.is_alive():
                self.bot_thread.join(timeout=5.0)
                if self.bot_thread.is_alive():
                    logger.warning("Bot thread did not terminate within timeout")
                    
        except Exception as e:
            logger.error(f"Error stopping bot: {e}")
            
    async def _async_shutdown(self):
        """Async shutdown method to properly close the bot"""
        try:
            if hasattr(self, 'application') and self.application:
                await self.application.stop()
                await self.application.shutdown()
        except Exception as e:
            logger.error(f"Error in async shutdown: {e}")

# Global bot instance
bot = SimPulseTelegramBot()

async def main():
    """Main entry point"""
    if not config.TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not configured!")
        return
    
    await bot.run()

if __name__ == "__main__":
    asyncio.run(main())