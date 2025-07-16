"""
SimPulse Response Decoder
Converts HEX, UTF-8, and various encodings to human-readable text
"""

import re
import logging
import binascii
import codecs
from typing import Optional, List, Dict, Any
from config import ENCODING_PREFERENCES, HEX_DECODE_ENABLED, AUTO_DETECT_ENCODING

logger = logging.getLogger(__name__)

class ResponseDecoder:
    """Handles all response decoding operations"""
    
    def __init__(self):
        self.encoding_preferences = ENCODING_PREFERENCES
        self.hex_decode_enabled = HEX_DECODE_ENABLED
        self.auto_detect_encoding = AUTO_DETECT_ENCODING
    
    def decode_response(self, response: str) -> str:
        """Main decoding function - converts any response to human-readable text"""
        if not response:
            return ""
        
        try:
            # Remove common AT command prefixes and suffixes
            cleaned_response = self._clean_at_response(response)
            
            # Try HEX decoding first
            if self.hex_decode_enabled and self._is_hex_string(cleaned_response):
                hex_decoded = self._decode_hex_string(cleaned_response)
                if hex_decoded:
                    cleaned_response = hex_decoded
            
            # Try various encodings
            if self.auto_detect_encoding:
                final_response = self._auto_detect_encoding(cleaned_response)
            else:
                final_response = self._decode_with_preferences(cleaned_response)
            
            # Final cleanup
            return self._final_cleanup(final_response)
            
        except Exception as e:
            logger.error(f"Failed to decode response: {e}")
            return response  # Return original if decoding fails
    
    def _clean_at_response(self, response: str) -> str:
        """Clean AT command response from prefixes and suffixes"""
        try:
            # Remove common AT response patterns
            patterns_to_remove = [
                r'^\s*OK\s*$',
                r'^\s*ERROR\s*$',
                r'^\s*\+CMGL:\s*',
                r'^\s*\+CUSD:\s*',
                r'^\s*\+CGSN:\s*',
                r'^\s*\+CPIN:\s*',
                r'^\s*\+CSQ:\s*',
                r'^\s*AT\+.*?[\r\n]+'
            ]
            
            cleaned = response.strip()
            
            for pattern in patterns_to_remove:
                cleaned = re.sub(pattern, '', cleaned, flags=re.MULTILINE | re.IGNORECASE)
            
            # Remove extra whitespace and newlines
            cleaned = re.sub(r'\s+', ' ', cleaned).strip()
            
            return cleaned
            
        except Exception as e:
            logger.error(f"Failed to clean AT response: {e}")
            return response
    
    def _is_hex_string(self, text: str) -> bool:
        """Check if string is a valid HEX string"""
        try:
            # Remove spaces and common separators
            cleaned = text.replace(' ', '').replace('-', '').replace(':', '')
            
            # Check if it's a valid hex string
            if len(cleaned) % 2 != 0:
                return False
            
            # Try to convert to bytes
            bytes.fromhex(cleaned)
            return True
            
        except (ValueError, TypeError):
            return False
    
    def _decode_hex_string(self, hex_string: str) -> Optional[str]:
        """Decode HEX string to text"""
        try:
            # Clean hex string
            cleaned = hex_string.replace(' ', '').replace('-', '').replace(':', '')
            
            # Convert to bytes
            byte_data = bytes.fromhex(cleaned)
            
            # Try different encodings
            for encoding in self.encoding_preferences:
                try:
                    decoded = byte_data.decode(encoding)
                    if decoded.isprintable() or self._contains_valid_chars(decoded):
                        logger.debug(f"Successfully decoded HEX with {encoding}")
                        return decoded
                except (UnicodeDecodeError, LookupError):
                    continue
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to decode HEX string: {e}")
            return None
    
    def _auto_detect_encoding(self, text: str) -> str:
        """Auto-detect encoding and decode"""
        try:
            # If already UTF-8, return as-is
            if self._is_valid_utf8(text):
                return text
            
            # Try different encodings
            for encoding in self.encoding_preferences:
                try:
                    # Try to encode then decode
                    encoded = text.encode('latin-1')
                    decoded = encoded.decode(encoding)
                    if self._is_readable_text(decoded):
                        logger.debug(f"Auto-detected encoding: {encoding}")
                        return decoded
                except (UnicodeDecodeError, UnicodeEncodeError, LookupError):
                    continue
            
            # If nothing worked, return original
            return text
            
        except Exception as e:
            logger.error(f"Failed to auto-detect encoding: {e}")
            return text
    
    def _decode_with_preferences(self, text: str) -> str:
        """Decode using encoding preferences"""
        try:
            for encoding in self.encoding_preferences:
                try:
                    if isinstance(text, bytes):
                        decoded = text.decode(encoding)
                    else:
                        decoded = text.encode('latin-1').decode(encoding)
                    
                    if self._is_readable_text(decoded):
                        return decoded
                except (UnicodeDecodeError, UnicodeEncodeError, LookupError):
                    continue
            
            return text
            
        except Exception as e:
            logger.error(f"Failed to decode with preferences: {e}")
            return text
    
    def _is_valid_utf8(self, text: str) -> bool:
        """Check if text is valid UTF-8"""
        try:
            text.encode('utf-8').decode('utf-8')
            return True
        except UnicodeError:
            return False
    
    def _is_readable_text(self, text: str) -> bool:
        """Check if text is readable (contains valid characters)"""
        try:
            # Check for common readable characters
            if not text.strip():
                return False
            
            # Count printable characters
            printable_count = sum(1 for c in text if c.isprintable() or c.isspace())
            total_count = len(text)
            
            # At least 80% should be printable
            return (printable_count / total_count) >= 0.8
            
        except Exception:
            return False
    
    def _contains_valid_chars(self, text: str) -> bool:
        """Check if text contains valid characters for SMS/USSD"""
        try:
            # Check for Arabic, Latin, numbers, common symbols
            valid_patterns = [
                r'[\u0600-\u06FF]',  # Arabic
                r'[a-zA-Z0-9]',      # Latin and numbers
                r'[\s\.\,\!\?\:\;]', # Common punctuation
                r'[\+\-\*\#]',       # Phone/USSD symbols
                r'[\(\)\[\]]'        # Brackets
            ]
            
            for pattern in valid_patterns:
                if re.search(pattern, text):
                    return True
            
            return False
            
        except Exception:
            return False
    
    def _final_cleanup(self, text: str) -> str:
        """Final cleanup of decoded text"""
        try:
            # Remove control characters except newlines and tabs
            cleaned = ''.join(char for char in text if char.isprintable() or char in '\n\t\r')
            
            # Normalize whitespace
            cleaned = re.sub(r'\s+', ' ', cleaned).strip()
            
            # Remove empty lines
            lines = [line.strip() for line in cleaned.split('\n') if line.strip()]
            
            return '\n'.join(lines) if lines else cleaned
            
        except Exception as e:
            logger.error(f"Failed to cleanup text: {e}")
            return text
    
    def decode_sms_pdu(self, pdu: str) -> Dict[str, Any]:
        """Decode SMS PDU format"""
        try:
            # This is a simplified PDU decoder
            # In production, you might want to use a more robust SMS PDU library
            
            result = {
                'sender': '',
                'message': '',
                'timestamp': None,
                'encoding': 'unknown'
            }
            
            # Basic PDU structure parsing
            if len(pdu) < 20:
                return result
            
            # Extract message from PDU (simplified)
            # This is a basic implementation - you may need to enhance based on your needs
            try:
                # Convert hex to bytes
                pdu_bytes = bytes.fromhex(pdu)
                
                # Try to extract text portion
                for i in range(0, len(pdu_bytes), 2):
                    try:
                        text_portion = pdu_bytes[i:i+20]
                        decoded = text_portion.decode('utf-8', errors='ignore')
                        if self._is_readable_text(decoded):
                            result['message'] = decoded
                            break
                    except:
                        continue
                        
            except Exception as e:
                logger.error(f"Failed to decode PDU: {e}")
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to decode SMS PDU: {e}")
            return {'sender': '', 'message': '', 'timestamp': None, 'encoding': 'error'}
    
    def decode_ussd_response(self, response: str) -> str:
        """Decode USSD response (balance, phone number, etc.)"""
        try:
            logger.debug(f"Decoding USSD response: {response}")
            
            if not response:
                return ""
            
            # Look for +CUSD: response format
            # Format: +CUSD: <n>,<str>,<dcs>
            # where <str> is the actual message in quotes
            cusd_match = re.search(r'\+CUSD:\s*\d+,\s*"([^"]*)"', response)
            if cusd_match:
                message = cusd_match.group(1)
                logger.debug(f"Extracted USSD message from +CUSD: {message}")
                
                # Decode the message content
                decoded = self.decode_response(message)
                logger.debug(f"Final decoded USSD: {decoded}")
                return decoded
            
            # If no +CUSD format found, try to clean and decode
            cleaned = response.replace('+CUSD:', '').strip()
            
            # Try to extract quoted content
            quote_match = re.search(r'"([^"]*)"', cleaned)
            if quote_match:
                message = quote_match.group(1)
                logger.debug(f"Extracted quoted message: {message}")
                decoded = self.decode_response(message)
                logger.debug(f"Final decoded USSD: {decoded}")
                return decoded
            
            # Last resort: decode the cleaned response
            decoded = self.decode_response(cleaned)
            logger.debug(f"Decoded cleaned USSD: {decoded}")
            return decoded
            
        except Exception as e:
            logger.error(f"Failed to decode USSD response: {e}")
            return response
    
    def decode_balance_response(self, response: str) -> Dict[str, str]:
        """Decode balance response and extract amount and currency"""
        try:
            logger.debug(f"Decoding balance response: {response}")
            
            decoded = self.decode_ussd_response(response)
            logger.debug(f"Decoded balance: {decoded}")
            
            result = {
                'balance': decoded,
                'amount': '',
                'currency': ''
            }
            
            # Skip if decoded response is empty or contains USSD commands
            if not decoded or decoded.strip() in ['*222#', '*101#']:
                logger.debug("Balance response is empty or contains USSD command")
                return result
            
            # Try to extract amount and currency
            # Common patterns for balance responses
            patterns = [
                r'(\d+[\.,]?\d*)\s*(DZD|DA|دج|dinars?)',  # Algerian Dinar
                r'(\d+[\.,]?\d*)\s*(USD|EUR|GBP|dollars?|euros?)',  # Other currencies
                r'(\d+[\.,]?\d*)\s*([A-Z]{3})',     # Generic 3-letter currency
                r'balance.*?(\d+[\.,]?\d*)\s*([A-Z]{2,3})',  # Balance with currency
                r'solde.*?(\d+[\.,]?\d*)\s*(DZD|DA|دج)',  # French balance
                r'(\d+[\.,]?\d*)',                   # Just numbers
            ]
            
            for pattern in patterns:
                match = re.search(pattern, decoded, re.IGNORECASE)
                if match:
                    result['amount'] = match.group(1)
                    if len(match.groups()) > 1:
                        result['currency'] = match.group(2)
                    logger.debug(f"Balance extracted - Amount: {result['amount']}, Currency: {result['currency']}")
                    break
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to decode balance response: {e}")
            return {'balance': response, 'amount': '', 'currency': ''}

# Global decoder instance
decoder = ResponseDecoder()
