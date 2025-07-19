"""
Settlement Handlers
Handles settlement-related conversations in the bot
"""

import logging
import os
from typing import Dict
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

from core.database import db
from telegram_bot.services.settlement_service import SettlementService
from telegram_bot.messages import SETTLEMENT_MESSAGES

logger = logging.getLogger(__name__)

# Conversation states
SETTLEMENT_SELECT_USER, SETTLEMENT_CONFIRM, SETTLEMENT_PROCESSING = range(3)

class SettlementHandler:
    """Handler for settlement operations"""
    
    def __init__(self):
        self.settlement_service = SettlementService()
    
    async def show_settlement_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Show settlement main menu"""
        try:
            query = update.callback_query
            await query.answer()
            
            # Get users with pending settlements
            pending_users = self.settlement_service.get_users_with_pending_settlements()
            
            if not pending_users:
                await query.edit_message_text(
                    SETTLEMENT_MESSAGES['no_pending_settlements'],
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="admin_menu")
                    ]])
                )
                return ConversationHandler.END
            
            # Create user selection keyboard
            keyboard = []
            for user_info in pending_users[:10]:  # Limit to 10 users per page
                user = user_info['user_data']
                summary = user_info['summary']
                
                button_text = (
                    f"👤 {user.get('first_name', 'مستخدم')} - "
                    f"💰 {summary['total_amount']:.2f} ر.س "
                    f"({summary['total_verifications']} تحقق)"
                )
                
                keyboard.append([InlineKeyboardButton(
                    button_text,
                    callback_data=f"settlement_user_{user['telegram_id']}"
                )])
            
            # Add navigation buttons
            keyboard.append([
                InlineKeyboardButton("🔙 العودة", callback_data="admin_menu")
            ])
            
            message_text = SETTLEMENT_MESSAGES['select_user_for_settlement'].format(
                count=len(pending_users)
            )
            
            await query.edit_message_text(
                message_text,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
            return SETTLEMENT_SELECT_USER
            
        except Exception as e:
            logger.error(f"Error showing settlement menu: {e}")
            await query.edit_message_text(
                "حدث خطأ في عرض قائمة التسوية",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 العودة", callback_data="admin_menu")
                ]])
            )
            return ConversationHandler.END
    
    async def show_user_settlement_details(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Show settlement details for selected user"""
        try:
            query = update.callback_query
            await query.answer()
            
            # Extract user ID from callback data
            user_id = int(query.data.split('_')[-1])
            context.user_data['settlement_user_id'] = user_id
            
            # Get settlement summary
            summary = self.settlement_service.get_user_settlement_summary(user_id)
            if not summary:
                await query.edit_message_text(
                    "لا توجد بيانات تسوية لهذا المستخدم",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔙 العودة", callback_data="settlement_menu")
                    ]])
                )
                return SETTLEMENT_SELECT_USER
            
            # Validate settlement
            validation = self.settlement_service.validate_settlement_data(user_id)
            if not validation['valid']:
                await query.edit_message_text(
                    f"لا يمكن تسوية هذا المستخدم: {validation['message']}",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔙 العودة", callback_data="settlement_menu")
                    ]])
                )
                return SETTLEMENT_SELECT_USER
            
            # Format settlement details
            user_data = summary['user_data']
            sim_info = summary.get('sim_info', {})
            
            message_text = SETTLEMENT_MESSAGES['settlement_confirmation'].format(
                user_name=f"{user_data.get('first_name', '')} {user_data.get('last_name', '')}".strip(),
                user_phone=user_data.get('phone_number', 'غير محدد'),
                sim_number=sim_info.get('phone_number', 'غير محدد'),
                total_amount=summary['total_amount'],
                total_verifications=summary['total_verifications'],
                period_start=summary['period_start'][:10],  # Date only
                period_end=summary['period_end'][:10],      # Date only
                current_balance=summary['current_balance']
            )
            
            keyboard = [
                [
                    InlineKeyboardButton("✅ تأكيد التسوية", callback_data=f"confirm_settlement_{user_id}"),
                    InlineKeyboardButton("❌ إلغاء", callback_data="settlement_menu")
                ],
                [
                    InlineKeyboardButton("📊 عرض تفاصيل التحققات", callback_data=f"show_verifications_{user_id}")
                ],
                [
                    InlineKeyboardButton("🔙 العودة", callback_data="settlement_menu")
                ]
            ]
            
            await query.edit_message_text(
                message_text,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
            return SETTLEMENT_CONFIRM
            
        except Exception as e:
            logger.error(f"Error showing user settlement details: {e}")
            await query.edit_message_text(
                "حدث خطأ في عرض تفاصيل التسوية",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 العودة", callback_data="settlement_menu")
                ]])
            )
            return SETTLEMENT_SELECT_USER
    
    async def show_user_verifications(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show detailed verifications for user"""
        try:
            query = update.callback_query
            await query.answer()
            
            user_id = int(query.data.split('_')[-1])
            
            # Get verification details
            verifications = db.get_user_unsettled_verifications(user_id)
            if not verifications:
                await query.answer("لا توجد تحققات", show_alert=True)
                return
            
            # Format verification details (first 10)
            details_text = "📊 **تفاصيل التحققات:**\n\n"
            
            for i, verification in enumerate(verifications[:10]):
                details_text += f"**{i+1}.** "
                details_text += f"📅 {verification['created_at'][:16]} | "
                details_text += f"💰 {verification['amount']} ر.س | "
                details_text += f"📱 {verification.get('phone_number', 'غير محدد')} | "
                details_text += f"{'✅' if verification['result'] == 'success' else '❌'}\n"
            
            if len(verifications) > 10:
                details_text += f"\n... و {len(verifications) - 10} تحقق إضافي"
            
            keyboard = [[
                InlineKeyboardButton("🔙 العودة للتسوية", callback_data=f"settlement_user_{user_id}")
            ]]
            
            await query.edit_message_text(
                details_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Error showing user verifications: {e}")
            await query.answer("حدث خطأ في عرض التحققات", show_alert=True)
    
    async def process_settlement(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Process the settlement"""
        try:
            query = update.callback_query
            await query.answer()
            
            user_id = int(query.data.split('_')[-1])
            admin_id = update.effective_user.id
            
            # Show processing message
            await query.edit_message_text(
                "⏳ جاري معالجة التسوية...\nيرجى الانتظار...",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⏸️ جاري المعالجة...", callback_data="processing")
                ]])
            )
            
            # Process settlement
            result = await self.settlement_service.process_user_settlement(user_id, admin_id)
            
            if result['success']:
                # Send success message
                success_text = SETTLEMENT_MESSAGES['settlement_success'].format(
                    settlement_id=result['settlement_id'],
                    total_amount=result['total_amount'],
                    total_verifications=result['total_verifications']
                )
                
                keyboard = [
                    [
                        InlineKeyboardButton("📄 إرسال التقرير", callback_data=f"send_report_{result['settlement_id']}"),
                        InlineKeyboardButton("📊 تسوية أخرى", callback_data="settlement_menu")
                    ],
                    [
                        InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="admin_menu")
                    ]
                ]
                
                await query.edit_message_text(
                    success_text,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                
                # Send PDF to admin
                if os.path.exists(result['pdf_file_path']):
                    try:
                        await context.bot.send_document(
                            chat_id=admin_id,
                            document=open(result['pdf_file_path'], 'rb'),
                            caption=f"📄 تقرير التسوية رقم {result['settlement_id']}"
                        )
                    except Exception as e:
                        logger.error(f"Error sending PDF to admin: {e}")
                
                # Send notification to user
                try:
                    user_message = SETTLEMENT_MESSAGES['user_settlement_notification'].format(
                        total_amount=result['total_amount'],
                        total_verifications=result['total_verifications']
                    )
                    
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=user_message
                    )
                    
                    # Send PDF to user
                    if os.path.exists(result['pdf_file_path']):
                        await context.bot.send_document(
                            chat_id=user_id,
                            document=open(result['pdf_file_path'], 'rb'),
                            caption="📄 نسخة من تقرير التسوية الخاص بك"
                        )
                        
                except Exception as e:
                    logger.warning(f"Could not notify user {user_id}: {e}")
                
            else:
                # Show error message
                error_text = f"❌ فشلت التسوية: {result['message']}"
                
                keyboard = [
                    [
                        InlineKeyboardButton("🔄 إعادة المحاولة", callback_data=f"settlement_user_{user_id}"),
                        InlineKeyboardButton("📊 تسوية أخرى", callback_data="settlement_menu")
                    ],
                    [
                        InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="admin_menu")
                    ]
                ]
                
                await query.edit_message_text(
                    error_text,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            
            return ConversationHandler.END
            
        except Exception as e:
            logger.error(f"Error processing settlement: {e}")
            
            keyboard = [[
                InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="admin_menu")
            ]]
            
            await query.edit_message_text(
                f"❌ حدث خطأ في معالجة التسوية: {str(e)}",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
            return ConversationHandler.END
    
    async def send_settlement_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Send settlement report again"""
        try:
            query = update.callback_query
            await query.answer()
            
            settlement_id = int(query.data.split('_')[-1])
            
            # Get settlement details
            settlement = db.get_settlement_by_id(settlement_id)
            if not settlement:
                await query.answer("لم يتم العثور على التسوية", show_alert=True)
                return
            
            # Send PDF if exists
            if settlement.get('pdf_file_path') and os.path.exists(settlement['pdf_file_path']):
                await context.bot.send_document(
                    chat_id=update.effective_user.id,
                    document=open(settlement['pdf_file_path'], 'rb'),
                    caption=f"📄 تقرير التسوية رقم {settlement_id}"
                )
                await query.answer("تم إرسال التقرير", show_alert=True)
            else:
                await query.answer("ملف التقرير غير متوفر", show_alert=True)
                
        except Exception as e:
            logger.error(f"Error sending settlement report: {e}")
            await query.answer("حدث خطأ في إرسال التقرير", show_alert=True)
    
    async def cancel_settlement(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Cancel settlement operation"""
        query = update.callback_query
        await query.answer()
        
        await query.edit_message_text(
            "تم إلغاء عملية التسوية",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="admin_menu")
            ]])
        )
        
        return ConversationHandler.END
