"""
SimPulse SMS Verification Helper
Functions to validate and parse SMS messages for balance verification
"""

import re
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from dateutil import parser

logger = logging.getLogger(__name__)

class SMSVerificationHelper:
    """Helper class for SMS verification logic"""
    
    def __init__(self):
        # Valid recharge patterns - messages that are acceptable
        self.valid_patterns = [
            r'Vous avez rechargé.*?(\d+(?:[.,]\d+)?)\s*(?:DZD|DA).*?le\s*(\d{2}[/\-]\d{2}[/\-]\d{4})\s*(\d{2}:\d{2}:\d{2})'
        ]
        
        # Invalid patterns - SCB/activated balance messages to reject
        self.invalid_patterns = [
            r'Sama Mix',
            r'valable',
            r'Bonus',
            r'est ajoutée',
            r'Cher\s+(?:Mr|Mrs)',
            r'contactez le service client'
        ]
    
    def is_valid_recharge_sms(self, sms_content: str) -> bool:
        """Check if SMS is a valid recharge message (not SCB/activated balance)"""
        try:
            # First check if it's an invalid/SCB message
            for pattern in self.invalid_patterns:
                if re.search(pattern, sms_content, re.IGNORECASE):
                    logger.debug(f"SMS rejected due to invalid pattern: {pattern}")
                    return False
            
            # Then check if it matches valid recharge patterns
            for pattern in self.valid_patterns:
                if re.search(pattern, sms_content, re.IGNORECASE):
                    logger.debug(f"SMS accepted as valid recharge message")
                    return True
            
            # If no valid pattern matches, it's not a recharge SMS
            logger.debug("SMS does not match any valid recharge pattern")
            return False
            
        except Exception as e:
            logger.error(f"Error validating SMS: {e}")
            return False
    
    def extract_recharge_info(self, sms_content: str) -> Optional[Dict]:
        """Extract recharge information from valid SMS"""
        try:
            for pattern in self.valid_patterns:
                match = re.search(pattern, sms_content, re.IGNORECASE)
                if match:
                    amount_str = match.group(1).replace(',', '.')
                    date_str = match.group(2)
                    time_str = match.group(3)
                    
                    # Parse amount
                    amount = float(amount_str)
                    
                    # Parse date and time
                    datetime_str = f"{date_str} {time_str}"
                    
                    # Handle different date formats
                    if '/' in date_str:
                        dt = datetime.strptime(datetime_str, "%d/%m/%Y %H:%M:%S")
                    elif '-' in date_str:
                        dt = datetime.strptime(datetime_str, "%d-%m-%Y %H:%M:%S")
                    else:
                        logger.error(f"Unknown date format: {date_str}")
                        return None
                    
                    return {
                        'amount': amount,
                        'datetime': dt,
                        'date_str': date_str,
                        'time_str': time_str,
                        'raw_amount': amount_str
                    }
            
            logger.warning(f"Could not extract recharge info from: {sms_content}")
            return None
            
        except Exception as e:
            logger.error(f"Error extracting recharge info: {e}")
            return None
    
    def parse_user_datetime(self, date_input: str, time_input: str) -> Optional[datetime]:
        """Parse user input for date and time into datetime object"""
        try:
            # Normalize date input
            date_str = date_input.strip()
            time_str = time_input.strip()
            
            # Handle different date formats
            date_formats = [
                "%Y-%m-%d",      # 2025-07-18
                "%d/%m/%Y",      # 18/07/2025
                "%d-%m-%Y",      # 18-07-2025
                "%Y/%m/%d",      # 2025/07/18
            ]
            
            parsed_date = None
            for fmt in date_formats:
                try:
                    parsed_date = datetime.strptime(date_str, fmt).date()
                    break
                except ValueError:
                    continue
            
            if not parsed_date:
                logger.error(f"Could not parse date: {date_str}")
                return None
            
            # Handle different time formats
            time_formats = [
                "%H:%M",         # 14:30
                "%H:%M:%S",      # 14:30:00
                "%I:%M %p",      # 2:30 PM
                "%I:%M:%S %p",   # 2:30:00 PM
            ]
            
            parsed_time = None
            for fmt in time_formats:
                try:
                    parsed_time = datetime.strptime(time_str, fmt).time()
                    break
                except ValueError:
                    continue
            
            if not parsed_time:
                logger.error(f"Could not parse time: {time_str}")
                return None
            
            # Combine date and time
            combined_dt = datetime.combine(parsed_date, parsed_time)
            logger.debug(f"Parsed datetime: {combined_dt}")
            return combined_dt
            
        except Exception as e:
            logger.error(f"Error parsing user datetime: {e}")
            return None
    
    def is_datetime_match(self, sms_datetime: datetime, user_datetime: datetime, margin_minutes: int = 2) -> bool:
        """Check if SMS datetime matches user datetime within margin"""
        try:
            # Calculate time difference
            time_diff = abs((sms_datetime - user_datetime).total_seconds())
            margin_seconds = margin_minutes * 60
            
            is_match = time_diff <= margin_seconds
            logger.debug(f"Datetime match check: SMS={sms_datetime}, User={user_datetime}, Diff={time_diff}s, Match={is_match}")
            return is_match
            
        except Exception as e:
            logger.error(f"Error checking datetime match: {e}")
            return False
    
    def is_amount_match(self, sms_amount: float, user_amount: float) -> bool:
        """Check if SMS amount matches user amount (ignoring decimals if user didn't provide them)"""
        try:
            # Convert both to integers for comparison (ignore decimals)
            sms_int = int(sms_amount)
            user_int = int(user_amount)
            
            is_match = sms_int == user_int
            logger.debug(f"Amount match check: SMS={sms_amount}({sms_int}), User={user_amount}({user_int}), Match={is_match}")
            return is_match
            
        except Exception as e:
            logger.error(f"Error checking amount match: {e}")
            return False

# Global helper instance
sms_verifier = SMSVerificationHelper()
