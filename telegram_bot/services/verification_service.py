"""
Verification Service
Handles SMS verification logic and processing
"""

import logging
from typing import Dict, Optional

from core.database import db
from telegram_bot.utils.sms_verifier import sms_verifier

logger = logging.getLogger(__name__)

class VerificationService:
    """Service for balance verification operations"""
    
    def __init__(self):
        pass
    
    async def verify_balance(self, user_id: int, amount: float, date_input: str, time_input: str) -> Dict:
        """Verify balance against SMS records"""
        try:
            # Get user's SIM info
            sim_info = db.get_user_sim_by_telegram_id(user_id)
            if not sim_info:
                return {
                    'result': 'failed',
                    'details': 'لم يتم العثور على شريحة مرتبطة'
                }
            
            # Parse user datetime
            user_datetime = sms_verifier.parse_user_datetime(date_input, time_input)
            if not user_datetime:
                return {
                    'result': 'failed',
                    'details': 'تنسيق التاريخ أو الوقت غير صحيح'
                }
            
            # Get SMS messages for verification
            sms_messages = db.get_sms_for_verification(
                sim_info['id'], 
                str(amount), 
                user_datetime, 
                3  # 3 minute margin as requested
            )
            
            verification_result = "failed"
            details = ""
            actual_amount = None
            
            # Check each SMS message
            for sms in sms_messages:
                sms_content = sms['message']
                
                # Check if it's a valid recharge SMS (not SCB)
                if not sms_verifier.is_valid_recharge_sms(sms_content):
                    verification_result = "scb_rejected"
                    details = "رصيد مفعل مرفوض"
                    break
                
                # Extract recharge info
                recharge_info = sms_verifier.extract_recharge_info(sms_content)
                if not recharge_info:
                    continue
                
                # Check amount match
                if sms_verifier.is_amount_match(recharge_info['amount'], amount):
                    verification_result = "success"
                    details = f"تم العثور على تعبئة مطابقة: {recharge_info['amount']} دج"
                    actual_amount = recharge_info['amount']
                    break
            
            # Log verification attempt
            db.add_balance_verification(
                user_id, amount, date_input, time_input, verification_result, details
            )
            
            # Update user's verified balance if successful
            if verification_result == "success" and actual_amount:
                db.update_user_verified_balance(user_id, actual_amount)
            
            return {
                'result': verification_result,
                'details': details,
                'actual_amount': actual_amount,
                'sim_number': sim_info.get('phone_number', 'غير متصل')
            }
            
        except Exception as e:
            logger.error(f"Error in verification service: {e}")
            return {
                'result': 'failed',
                'details': 'حدث خطأ في النظام'
            }
