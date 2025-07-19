"""
Settlement Service
Handles user settlement operations and PDF generation
"""

import logging
import os
from datetime import datetime
from typing import Dict, List, Optional

from core.database import db
from telegram_bot.utils.pdf_generator import PDFGenerator

logger = logging.getLogger(__name__)

class SettlementService:
    """Service for settlement operations"""
    
    def __init__(self):
        self.pdf_generator = PDFGenerator()
    
    def get_user_settlement_summary(self, telegram_user_id: int) -> Optional[Dict]:
        """Get settlement summary for a user"""
        try:
            # Get user data
            user_data = db.get_telegram_user_by_id(telegram_user_id)
            if not user_data or user_data['status'] != 'approved':
                return None
            
            # Get unsettled verifications
            verifications = db.get_user_unsettled_verifications(telegram_user_id)
            if not verifications:
                return None
            
            # Calculate summary
            total_amount = sum(float(v['amount']) for v in verifications if v['result'] == 'success')
            total_verifications = len(verifications)
            
            # Get period dates
            period_start = verifications[0]['created_at']
            period_end = verifications[-1]['created_at']
            
            # Get SIM info
            sim_info = db.get_user_sim_by_telegram_id(telegram_user_id)
            
            return {
                'user_data': user_data,
                'sim_info': sim_info,
                'verifications': verifications,
                'total_amount': total_amount,
                'total_verifications': total_verifications,
                'period_start': period_start,
                'period_end': period_end,
                'current_balance': user_data.get('verified_balance', 0.0)
            }
            
        except Exception as e:
            logger.error(f"Error getting settlement summary for user {telegram_user_id}: {e}")
            return None
    
    async def process_user_settlement(self, telegram_user_id: int, admin_telegram_id: int) -> Dict:
        """Process settlement for a user"""
        try:
            # Get settlement summary
            summary = self.get_user_settlement_summary(telegram_user_id)
            if not summary:
                return {
                    'success': False,
                    'message': 'لا توجد تحققات قابلة للتسوية'
                }
            
            # Generate PDF report
            pdf_result = await self.pdf_generator.generate_settlement_report(summary)
            if not pdf_result['success']:
                return {
                    'success': False,
                    'message': f'فشل في إنتاج التقرير: {pdf_result["message"]}'
                }
            
            # Create settlement record
            settlement_id = db.create_user_settlement(
                telegram_user_id=telegram_user_id,
                period_start=summary['period_start'],
                period_end=summary['period_end'],
                total_verifications=summary['total_verifications'],
                total_amount=summary['total_amount'],
                admin_telegram_id=admin_telegram_id,
                pdf_file_path=pdf_result['file_path']
            )
            
            # Link verifications to settlement
            verification_ids = [v['id'] for v in summary['verifications']]
            link_success = db.link_verifications_to_settlement(verification_ids, settlement_id)
            
            if not link_success:
                logger.error(f"Failed to link verifications to settlement {settlement_id}")
                # Continue anyway as settlement was created
            
            # Reset user's verified balance
            reset_success = db.reset_user_verified_balance(telegram_user_id)
            if not reset_success:
                logger.error(f"Failed to reset verified balance for user {telegram_user_id}")
                # Continue anyway
            
            return {
                'success': True,
                'settlement_id': settlement_id,
                'pdf_file_path': pdf_result['file_path'],
                'total_amount': summary['total_amount'],
                'total_verifications': summary['total_verifications'],
                'message': 'تمت التسوية بنجاح'
            }
            
        except Exception as e:
            logger.error(f"Error processing settlement for user {telegram_user_id}: {e}")
            return {
                'success': False,
                'message': f'خطأ في معالجة التسوية: {str(e)}'
            }
    
    def get_users_with_pending_settlements(self) -> List[Dict]:
        """Get all users who have unsettled verifications"""
        try:
            # Get all approved users
            all_users = db.get_approved_telegram_users()
            users_with_settlements = []
            
            for user in all_users:
                summary = self.get_user_settlement_summary(user['telegram_id'])
                if summary and summary['total_verifications'] > 0:
                    users_with_settlements.append({
                        'user_data': user,
                        'summary': summary
                    })
            
            return users_with_settlements
            
        except Exception as e:
            logger.error(f"Error getting users with pending settlements: {e}")
            return []
    
    def get_user_settlement_history(self, telegram_user_id: int) -> List[Dict]:
        """Get settlement history for a user"""
        try:
            settlements = db.get_user_settlements_history(telegram_user_id)
            
            # Enrich with verification details
            for settlement in settlements:
                verifications = db.get_verifications_by_settlement(settlement['id'])
                settlement['verifications'] = verifications
            
            return settlements
            
        except Exception as e:
            logger.error(f"Error getting settlement history for user {telegram_user_id}: {e}")
            return []
    
    def validate_settlement_data(self, telegram_user_id: int) -> Dict:
        """Validate that user can be settled"""
        try:
            # Check if user exists and is approved
            user_data = db.get_telegram_user_by_id(telegram_user_id)
            if not user_data:
                return {'valid': False, 'message': 'المستخدم غير موجود'}
            
            if user_data['status'] != 'approved':
                return {'valid': False, 'message': 'المستخدم غير معتمد'}
            
            # Check if user has unsettled verifications
            verifications = db.get_user_unsettled_verifications(telegram_user_id)
            if not verifications:
                return {'valid': False, 'message': 'لا توجد تحققات قابلة للتسوية'}
            
            # Check if user has SIM assigned
            sim_info = db.get_user_sim_by_telegram_id(telegram_user_id)
            if not sim_info:
                return {'valid': False, 'message': 'لا توجد شريحة مرتبطة بالمستخدم'}
            
            return {'valid': True, 'message': 'البيانات صحيحة للتسوية'}
            
        except Exception as e:
            logger.error(f"Error validating settlement data for user {telegram_user_id}: {e}")
            return {'valid': False, 'message': f'خطأ في التحقق: {str(e)}'}
