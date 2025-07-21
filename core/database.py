"""
SimPulse Modem System Database Operations
SQLite database management for modem-SIM system
"""

import sqlite3
import os
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from .config import DB_PATH, DB_TIMEOUT

logger = logging.getLogger(__name__)

class DatabaseManager:
    """Handles all database operations for the modem system"""
    
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Initialize database with schema"""
        try:
            schema_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "schema.sql")
            with open(schema_path, 'r', encoding='utf-8') as f:
                schema_sql = f.read()
            
            with sqlite3.connect(self.db_path, timeout=DB_TIMEOUT) as conn:
                conn.executescript(schema_sql)
                conn.commit()
            
            logger.info(f"Database initialized at {self.db_path}")
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            raise
    
    def get_connection(self) -> sqlite3.Connection:
        """Get database connection with row factory"""
        conn = sqlite3.connect(self.db_path, timeout=DB_TIMEOUT)
        conn.row_factory = sqlite3.Row
        return conn
    
    # ========================================================================
    # MODEM OPERATIONS
    # ========================================================================
    
    def add_modem(self, imei: str) -> int:
        """Add new modem to database"""
        try:
            with self.get_connection() as conn:
                cursor = conn.execute(
                    "INSERT INTO modems (imei) VALUES (?)",
                    (imei,)
                )
                modem_id = cursor.lastrowid
                conn.commit()
                logger.info(f"Added modem {imei}")
                return modem_id
        except sqlite3.IntegrityError:
            # Modem already exists, get existing ID
            existing_modem = self.get_modem_by_imei(imei)
            if existing_modem:
                logger.info(f"Modem {imei} already exists with ID {existing_modem['id']}")
                return existing_modem['id']
            else:
                raise Exception(f"Failed to get existing modem {imei}")
        except Exception as e:
            logger.error(f"Failed to add modem {imei}: {e}")
            raise
    
    # Remove port update method since we no longer track ports
    # def update_modem_ports(self, imei: str, primary_port: str, all_ports: str) -> int:
    #     """Update existing modem's port information - REMOVED"""
    #     pass
    
    def get_modem_by_imei(self, imei: str) -> Optional[Dict]:
        """Get modem by IMEI"""
        try:
            with self.get_connection() as conn:
                cursor = conn.execute(
                    "SELECT * FROM modems WHERE imei = ? AND status = 'active'",
                    (imei,)
                )
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Failed to get modem {imei}: {e}")
            return None
    
    def get_modem_by_id(self, modem_id: int) -> Optional[Dict]:
        """Get modem by ID"""
        try:
            with self.get_connection() as conn:
                cursor = conn.execute(
                    "SELECT * FROM modems WHERE id = ? AND status = 'active'",
                    (modem_id,)
                )
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Failed to get modem {modem_id}: {e}")
            return None
    
    def get_all_modems(self) -> List[Dict]:
        """Get all active modems"""
        try:
            with self.get_connection() as conn:
                cursor = conn.execute(
                    "SELECT * FROM modems WHERE status = 'active' ORDER BY created_at"
                )
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get all modems: {e}")
            return []
    
    def get_all_sims(self) -> List[Dict]:
        """Get all active SIMs"""
        try:
            with self.get_connection() as conn:
                cursor = conn.execute(
                    """SELECT s.*, m.imei 
                       FROM sims s 
                       JOIN modems m ON s.modem_id = m.id 
                       WHERE s.status = 'active' AND m.status = 'active'
                       ORDER BY s.created_at"""
                )
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get all SIMs: {e}")
            return []
    
    def delete_modem(self, modem_id: int) -> bool:
        """Mark modem as inactive"""
        try:
            with self.get_connection() as conn:
                cursor = conn.execute(
                    "UPDATE modems SET status = 'inactive' WHERE id = ?",
                    (modem_id,)
                )
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Failed to delete modem {modem_id}: {e}")
            return False
    
    # ========================================================================
    # SIM OPERATIONS
    # ========================================================================
    
    def add_sim(self, modem_id: int, phone_number: str = None, balance: str = None) -> int:
        """Add new SIM to database"""
        try:
            with self.get_connection() as conn:
                cursor = conn.execute(
                    "INSERT INTO sims (modem_id, phone_number, balance) VALUES (?, ?, ?)",
                    (modem_id, phone_number, balance)
                )
                sim_id = cursor.lastrowid
                conn.commit()
                logger.info(f"Added SIM for modem {modem_id}")
                return sim_id
        except Exception as e:
            logger.error(f"Failed to add SIM for modem {modem_id}: {e}")
            raise
    
    def update_sim_info(self, sim_id: int, phone_number: str = None, balance: str = None):
        """Update SIM information SAFELY - preserve existing data when new data is None"""
        try:
            with self.get_connection() as conn:
                # Get current data to avoid overwriting with None
                current_sim = self.get_sim_by_id(sim_id)
                if not current_sim:
                    logger.error(f"SIM {sim_id} not found for update")
                    return
                
                current_phone = current_sim.get('phone_number')
                current_balance = current_sim.get('balance')
                
                # Use new data if provided, otherwise keep existing data
                final_phone = phone_number if phone_number is not None else current_phone
                final_balance = balance if balance is not None else current_balance
                
                logger.info(f"SIM {sim_id} update - Current: Phone={current_phone}, Balance={current_balance}")
                logger.info(f"SIM {sim_id} update - New: Phone={phone_number}, Balance={balance}")
                logger.info(f"SIM {sim_id} update - Final: Phone={final_phone}, Balance={final_balance}")
                
                # Only update if we have at least some info
                if final_phone or final_balance:
                    conn.execute(
                        "UPDATE sims SET phone_number = ?, balance = ?, info_extracted_at = ? WHERE id = ?",
                        (final_phone, final_balance, datetime.now(), sim_id)
                    )
                    logger.info(f"✅ Updated SIM {sim_id} safely - Phone: {final_phone}, Balance: {final_balance}")
                else:
                    logger.warning(f"⚠️ No info to update for SIM {sim_id}")
                
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to update SIM {sim_id}: {e}")
            raise
    
    def get_sim_by_modem(self, modem_id: int) -> Optional[Dict]:
        """Get SIM by modem ID"""
        try:
            with self.get_connection() as conn:
                cursor = conn.execute(
                    "SELECT * FROM sims WHERE modem_id = ? AND status = 'active'",
                    (modem_id,)
                )
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Failed to get SIM for modem {modem_id}: {e}")
            return None
    
    def get_sim_by_id(self, sim_id: int) -> Optional[Dict]:
        """Get SIM by SIM ID"""
        try:
            with self.get_connection() as conn:
                cursor = conn.execute(
                    "SELECT * FROM sims WHERE id = ?",
                    (sim_id,)
                )
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Failed to get SIM {sim_id}: {e}")
            return None
    
    def get_sims_needing_extraction(self) -> List[Dict]:
        """Get SIMs that need info extraction - either no extraction timestamp OR missing phone/balance"""
        try:
            with self.get_connection() as conn:
                cursor = conn.execute(
                    """SELECT s.*, m.imei 
                       FROM sims s 
                       JOIN modems m ON s.modem_id = m.id 
                       WHERE (s.info_extracted_at IS NULL 
                              OR s.phone_number IS NULL 
                              OR s.balance IS NULL
                              OR s.phone_number = ''
                              OR s.balance = '')
                       AND s.status = 'active' 
                       AND m.status = 'active'"""
                )
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get SIMs needing extraction: {e}")
            return []
    
    def mark_sim_extracted(self, sim_id: int):
        """Mark SIM as info extracted"""
        try:
            with self.get_connection() as conn:
                conn.execute(
                    "UPDATE sims SET info_extracted_at = ? WHERE id = ?",
                    (datetime.now(), sim_id)
                )
                conn.commit()
                logger.info(f"Marked SIM {sim_id} as extracted")
        except Exception as e:
            logger.error(f"Failed to mark SIM {sim_id} as extracted: {e}")
            raise
    
    def delete_sim(self, sim_id: int) -> bool:
        """Mark SIM as inactive"""
        try:
            with self.get_connection() as conn:
                cursor = conn.execute(
                    "UPDATE sims SET status = 'inactive' WHERE id = ?",
                    (sim_id,)
                )
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Failed to delete SIM {sim_id}: {e}")
            return False
    
    # ========================================================================
    # SMS OPERATIONS
    # ========================================================================
    
    def add_sms(self, sim_id: int, sender: str, message: str, received_at: datetime) -> int:
        """Add new SMS message to database"""
        try:
            with self.get_connection() as conn:
                cursor = conn.execute(
                    "INSERT INTO sms (sim_id, sender, message, received_at) VALUES (?, ?, ?, ?)",
                    (sim_id, sender, message, received_at)
                )
                sms_id = cursor.lastrowid
                conn.commit()
                logger.debug(f"Added SMS from {sender} to SIM {sim_id}")
                return sms_id
        except Exception as e:
            logger.error(f"Failed to add SMS: {e}")
            raise
    
    def get_sms_by_sim(self, sim_id: int, limit: int = 100) -> List[Dict]:
        """Get SMS messages for a SIM"""
        try:
            with self.get_connection() as conn:
                cursor = conn.execute(
                    "SELECT * FROM sms WHERE sim_id = ? ORDER BY received_at DESC LIMIT ?",
                    (sim_id, limit)
                )
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get SMS for SIM {sim_id}: {e}")
            return []
    
    def get_all_sms(self, limit: int = 1000) -> List[Dict]:
        """Get all SMS messages"""
        try:
            with self.get_connection() as conn:
                cursor = conn.execute(
                    """SELECT s.*, sim.phone_number, m.imei 
                       FROM sms s 
                       JOIN sims sim ON s.sim_id = sim.id 
                       JOIN modems m ON sim.modem_id = m.id 
                       ORDER BY s.received_at DESC LIMIT ?""",
                    (limit,)
                )
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get all SMS: {e}")
            return []
    
    def delete_old_sms(self, days: int = 30) -> int:
        """Delete SMS messages older than specified days"""
        try:
            cutoff_date = datetime.now() - timedelta(days=days)
            with self.get_connection() as conn:
                cursor = conn.execute(
                    "DELETE FROM sms WHERE received_at < ?",
                    (cutoff_date,)
                )
                conn.commit()
                deleted_count = cursor.rowcount
                logger.info(f"Deleted {deleted_count} old SMS messages")
                return deleted_count
        except Exception as e:
            logger.error(f"Failed to delete old SMS: {e}")
            return 0
    
    # ========================================================================
    # BALANCE HISTORY OPERATIONS
    # ========================================================================
    
    def add_balance_history(self, sim_id: int, old_balance: str, new_balance: str, 
                           change_amount: str, recharge_amount: str = None, 
                           change_type: str = 'recharge', detected_from_sms: bool = False,
                           sms_sender: str = None, sms_content: str = None) -> int:
        """Add balance change record"""
        try:
            with self.get_connection() as conn:
                cursor = conn.execute("""
                    INSERT INTO balance_history 
                    (sim_id, old_balance, new_balance, change_amount, recharge_amount, 
                     change_type, detected_from_sms, sms_sender, sms_content)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (sim_id, old_balance, new_balance, change_amount, recharge_amount,
                      change_type, detected_from_sms, sms_sender, sms_content))
                history_id = cursor.lastrowid
                conn.commit()
                logger.info(f"Added balance history for SIM {sim_id}: {old_balance} → {new_balance}")
                return history_id
        except Exception as e:
            logger.error(f"Failed to add balance history: {e}")
            raise
    
    def get_balance_history(self, sim_id: int = None, limit: int = 100) -> List[Dict]:
        """Get balance history records"""
        try:
            with self.get_connection() as conn:
                if sim_id:
                    cursor = conn.execute("""
                        SELECT bh.*, s.phone_number, m.imei
                        FROM balance_history bh
                        JOIN sims s ON bh.sim_id = s.id
                        JOIN modems m ON s.modem_id = m.id
                        WHERE bh.sim_id = ?
                        ORDER BY bh.created_at DESC LIMIT ?
                    """, (sim_id, limit))
                else:
                    cursor = conn.execute("""
                        SELECT bh.*, s.phone_number, m.imei
                        FROM balance_history bh
                        JOIN sims s ON bh.sim_id = s.id
                        JOIN modems m ON s.modem_id = m.id
                        ORDER BY bh.created_at DESC LIMIT ?
                    """, (limit,))
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get balance history: {e}")
            return []
    
    def get_current_balance(self, sim_id: int) -> str:
        """Get current balance for a SIM"""
        try:
            with self.get_connection() as conn:
                cursor = conn.execute(
                    "SELECT balance FROM sims WHERE id = ? AND status = 'active'",
                    (sim_id,)
                )
                row = cursor.fetchone()
                return row[0] if row and row[0] else "0.00"
        except Exception as e:
            logger.error(f"Failed to get current balance for SIM {sim_id}: {e}")
            return "0.00"

    # ========================================================================
    # UTILITY OPERATIONS
    # ========================================================================
    
    def get_system_stats(self) -> Dict:
        """Get system statistics"""
        try:
            with self.get_connection() as conn:
                stats = {}
                
                # Count modems
                cursor = conn.execute("SELECT COUNT(*) FROM modems WHERE status = 'active'")
                stats['active_modems'] = cursor.fetchone()[0]
                
                # Count SIMs
                cursor = conn.execute("SELECT COUNT(*) FROM sims WHERE status = 'active'")
                stats['active_sims'] = cursor.fetchone()[0]
                
                # Count SIMs needing extraction
                cursor = conn.execute("SELECT COUNT(*) FROM sims WHERE info_extracted_at IS NULL AND status = 'active'")
                stats['sims_needing_extraction'] = cursor.fetchone()[0]
                
                # Count SMS messages
                cursor = conn.execute("SELECT COUNT(*) FROM sms")
                stats['total_sms'] = cursor.fetchone()[0]
                
                # Count SMS from last 24 hours
                yesterday = datetime.now() - timedelta(days=1)
                cursor = conn.execute("SELECT COUNT(*) FROM sms WHERE received_at > ?", (yesterday,))
                stats['sms_last_24h'] = cursor.fetchone()[0]
                
                # Count groups
                cursor = conn.execute("SELECT COUNT(*) FROM groups WHERE status = 'active'")
                stats['active_groups'] = cursor.fetchone()[0]
                
                return stats
        except Exception as e:
            logger.error(f"Failed to get system stats: {e}")
            return {}

    # ========================================================================
    # TELEGRAM BOT OPERATIONS
    # ========================================================================

    def add_telegram_user(self, telegram_id: int, full_name: str, phone_number: str) -> int:
        """Add new telegram user"""
        try:
            with self.get_connection() as conn:
                cursor = conn.execute(
                    "INSERT INTO telegram_users (telegram_id, full_name, phone_number, status) VALUES (?, ?, ?, 'pending')",
                    (telegram_id, full_name, phone_number)
                )
                user_id = cursor.lastrowid
                conn.commit()
                logger.info(f"Added telegram user: {full_name} (ID: {telegram_id})")
                return user_id
        except Exception as e:
            logger.error(f"Failed to add telegram user: {e}")
            raise

    def get_telegram_user_by_id(self, telegram_id: int) -> Optional[Dict]:
        """Get telegram user by telegram ID"""
        try:
            with self.get_connection() as conn:
                cursor = conn.execute(
                    "SELECT * FROM telegram_users WHERE telegram_id = ?",
                    (telegram_id,)
                )
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Failed to get telegram user {telegram_id}: {e}")
            return None

    def update_telegram_user_status(self, telegram_id: int, status: str, group_id: int = None) -> bool:
        """Update telegram user status and optionally assign to group"""
        try:
            with self.get_connection() as conn:
                if group_id:
                    conn.execute(
                        "UPDATE telegram_users SET status = ?, group_id = ? WHERE telegram_id = ?",
                        (status, group_id, telegram_id)
                    )
                else:
                    conn.execute(
                        "UPDATE telegram_users SET status = ? WHERE telegram_id = ?",
                        (status, telegram_id)
                    )
                conn.commit()
                logger.info(f"Updated telegram user {telegram_id} status to {status}")
                return True
        except Exception as e:
            logger.error(f"Failed to update telegram user status: {e}")
            return False

    def delete_telegram_user(self, telegram_id: int) -> bool:
        """Delete telegram user from database"""
        try:
            with self.get_connection() as conn:
                cursor = conn.execute(
                    "DELETE FROM telegram_users WHERE telegram_id = ?",
                    (telegram_id,)
                )
                conn.commit()
                success = cursor.rowcount > 0
                if success:
                    logger.info(f"Deleted telegram user {telegram_id}")
                return success
        except Exception as e:
            logger.error(f"Failed to delete telegram user: {e}")
            return False

    def get_pending_telegram_users(self) -> List[Dict]:
        """Get all pending telegram users"""
        try:
            with self.get_connection() as conn:
                cursor = conn.execute(
                    "SELECT * FROM telegram_users WHERE status = 'pending' ORDER BY created_at"
                )
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get pending telegram users: {e}")
            return []

    def get_approved_telegram_users(self) -> List[Dict]:
        """Get all approved telegram users with group info"""
        try:
            with self.get_connection() as conn:
                cursor = conn.execute(
                    """SELECT tu.*, g.group_name, s.phone_number as sim_phone, s.balance 
                       FROM telegram_users tu
                       LEFT JOIN groups g ON tu.group_id = g.id
                       LEFT JOIN modems m ON g.modem_id = m.id
                       LEFT JOIN sims s ON m.id = s.modem_id AND s.status = 'active'
                       WHERE tu.status = 'approved'
                       ORDER BY tu.created_at"""
                )
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get approved telegram users: {e}")
            return []

    def get_rejected_telegram_users(self) -> List[Dict]:
        """Get all rejected telegram users"""
        try:
            with self.get_connection() as conn:
                cursor = conn.execute(
                    """SELECT * FROM telegram_users 
                       WHERE status = 'rejected'
                       ORDER BY created_at DESC"""
                )
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get rejected telegram users: {e}")
            return []

    def get_all_telegram_users(self) -> List[Dict]:
        """Get all telegram users with group info"""
        try:
            with self.get_connection() as conn:
                cursor = conn.execute(
                    """SELECT tu.*, g.group_name, s.phone_number as sim_phone, s.balance 
                       FROM telegram_users tu
                       LEFT JOIN groups g ON tu.group_id = g.id
                       LEFT JOIN modems m ON g.modem_id = m.id
                       LEFT JOIN sims s ON m.id = s.modem_id AND s.status = 'active'
                       ORDER BY tu.created_at DESC"""
                )
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get all telegram users: {e}")
            return []

    def get_telegram_user_by_phone(self, phone_number: str) -> Optional[Dict]:
        """Get telegram user by phone number"""
        try:
            with self.get_connection() as conn:
                cursor = conn.execute(
                    "SELECT * FROM telegram_users WHERE phone_number = ?",
                    (phone_number,)
                )
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Failed to get telegram user by phone: {e}")
            return None

    def get_users_by_group_id(self, group_id: int) -> List[Dict]:
        """Get all users assigned to a specific group"""
        try:
            with self.get_connection() as conn:
                cursor = conn.execute(
                    "SELECT * FROM telegram_users WHERE group_id = ? AND status = 'approved'",
                    (group_id,)
                )
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get users by group ID: {e}")
            return []
    
    def get_group_users(self, group_name: str) -> List[Dict]:
        """Get all users assigned to a specific group by group name"""
        try:
            with self.get_connection() as conn:
                cursor = conn.execute("""
                    SELECT u.*, g.group_name 
                    FROM telegram_users u
                    JOIN groups g ON u.group_id = g.id  
                    WHERE g.group_name = ? AND u.status = 'approved' AND g.status = 'active'
                    ORDER BY u.created_at DESC
                """, (group_name,))
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get users for group '{group_name}': {e}")
            return []

    def get_group_by_id(self, group_id: int) -> Optional[Dict]:
        """Get group by ID"""
        try:
            with self.get_connection() as conn:
                cursor = conn.execute(
                    "SELECT * FROM groups WHERE id = ?",
                    (group_id,)
                )
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Failed to get group {group_id}: {e}")
            return None

    def add_balance_verification(self, telegram_user_id: int, amount: float, requested_date: str, 
                               requested_time: str, result: str, details: str = None) -> int:
        """Add balance verification record"""
        try:
            with self.get_connection() as conn:
                cursor = conn.execute(
                    """INSERT INTO balance_verifications 
                       (telegram_user_id, amount, requested_date, requested_time, result, details) 
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (telegram_user_id, amount, requested_date, requested_time, result, details)
                )
                verification_id = cursor.lastrowid
                conn.commit()
                logger.info(f"Added balance verification for user {telegram_user_id}: {result}")
                return verification_id
        except Exception as e:
            logger.error(f"Failed to add balance verification: {e}")
            raise

    def get_user_verifications(self, telegram_user_id: int, limit: int = 10) -> List[Dict]:
        """Get verification history for a user"""
        try:
            with self.get_connection() as conn:
                cursor = conn.execute(
                    """SELECT * FROM balance_verifications 
                       WHERE telegram_user_id = ? 
                       ORDER BY created_at DESC LIMIT ?""",
                    (telegram_user_id, limit)
                )
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get user verifications: {e}")
            return []

    def update_user_verified_balance(self, telegram_id: int, new_balance: float) -> bool:
        """Update user's verified balance"""
        try:
            with self.get_connection() as conn:
                conn.execute(
                    "UPDATE telegram_users SET verified_balance = ? WHERE telegram_id = ?",
                    (new_balance, telegram_id)
                )
                conn.commit()
                logger.info(f"Updated verified balance for user {telegram_id}: {new_balance}")
                return True
        except Exception as e:
            logger.error(f"Failed to update verified balance: {e}")
            return False

    def get_user_sim_by_telegram_id(self, telegram_id: int) -> Optional[Dict]:
        """Get SIM information for a telegram user"""
        try:
            with self.get_connection() as conn:
                cursor = conn.execute(
                    """SELECT s.*, g.group_name, m.imei
                       FROM telegram_users tu
                       JOIN groups g ON tu.group_id = g.id
                       JOIN modems m ON g.modem_id = m.id
                       JOIN sims s ON m.id = s.modem_id AND s.status = 'active'
                       WHERE tu.telegram_id = ? AND tu.status = 'approved'""",
                    (telegram_id,)
                )
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Failed to get sim for telegram user {telegram_id}: {e}")
            return None

    def get_sms_for_verification(self, sim_id: int, amount: str, date_time: datetime, 
                               margin_minutes: int = 2) -> List[Dict]:
        """Get SMS messages for balance verification within time margin"""
        try:
            start_time = date_time - timedelta(minutes=margin_minutes)
            end_time = date_time + timedelta(minutes=margin_minutes)
            
            with self.get_connection() as conn:
                cursor = conn.execute(
                    """SELECT * FROM sms 
                       WHERE sim_id = ? 
                       AND sender = '7711198105108105115'
                       AND received_at BETWEEN ? AND ?
                       ORDER BY received_at DESC""",
                    (sim_id, start_time, end_time)
                )
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get SMS for verification: {e}")
            return []

    # ========================================================================
    # SETTLEMENT OPERATIONS
    # ========================================================================

    def get_user_unsettled_verifications(self, telegram_user_id: int) -> List[Dict]:
        """Get all successful verifications that haven't been settled yet"""
        try:
            with self.get_connection() as conn:
                cursor = conn.execute(
                    """SELECT * FROM balance_verifications 
                       WHERE telegram_user_id = ? 
                       AND result = 'success' 
                       AND settlement_id IS NULL
                       ORDER BY created_at ASC""",
                    (telegram_user_id,)
                )
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get unsettled verifications for user {telegram_user_id}: {e}")
            return []

    def get_last_settlement_date(self, telegram_user_id: int) -> Optional[str]:
        """Get the date of the last settlement for a user"""
        try:
            with self.get_connection() as conn:
                cursor = conn.execute(
                    """SELECT MAX(settlement_date) FROM user_settlements 
                       WHERE telegram_user_id = ?""",
                    (telegram_user_id,)
                )
                row = cursor.fetchone()
                return row[0] if row and row[0] else None
        except Exception as e:
            logger.error(f"Failed to get last settlement date for user {telegram_user_id}: {e}")
            return None

    def create_user_settlement(self, telegram_user_id: int, period_start: str, period_end: str,
                              total_verifications: int, total_amount: float, 
                              admin_telegram_id: int, pdf_file_path: str = None) -> int:
        """Create a new settlement record"""
        try:
            with self.get_connection() as conn:
                cursor = conn.execute(
                    """INSERT INTO user_settlements 
                       (telegram_user_id, period_start_date, period_end_date, 
                        total_verifications, total_amount, admin_telegram_id, pdf_file_path)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (telegram_user_id, period_start, period_end, total_verifications, 
                     total_amount, admin_telegram_id, pdf_file_path)
                )
                settlement_id = cursor.lastrowid
                conn.commit()
                logger.info(f"Created settlement {settlement_id} for user {telegram_user_id}")
                return settlement_id
        except Exception as e:
            logger.error(f"Failed to create settlement: {e}")
            raise

    def link_verifications_to_settlement(self, verification_ids: List[int], settlement_id: int) -> bool:
        """Link verification records to a settlement"""
        try:
            with self.get_connection() as conn:
                placeholders = ','.join(['?' for _ in verification_ids])
                conn.execute(
                    f"""UPDATE balance_verifications 
                        SET settlement_id = ? 
                        WHERE id IN ({placeholders})""",
                    [settlement_id] + verification_ids
                )
                conn.commit()
                logger.info(f"Linked {len(verification_ids)} verifications to settlement {settlement_id}")
                return True
        except Exception as e:
            logger.error(f"Failed to link verifications to settlement: {e}")
            return False

    def reset_user_verified_balance(self, telegram_user_id: int) -> bool:
        """Reset user's verified balance to 0"""
        try:
            with self.get_connection() as conn:
                conn.execute(
                    "UPDATE telegram_users SET verified_balance = 0.0 WHERE telegram_id = ?",
                    (telegram_user_id,)
                )
                conn.commit()
                logger.info(f"Reset verified balance for user {telegram_user_id}")
                return True
        except Exception as e:
            logger.error(f"Failed to reset verified balance for user {telegram_user_id}: {e}")
            return False

    def get_user_settlements_history(self, telegram_user_id: int, limit: int = 10) -> List[Dict]:
        """Get settlement history for a user"""
        try:
            with self.get_connection() as conn:
                cursor = conn.execute(
                    """SELECT * FROM user_settlements 
                       WHERE telegram_user_id = ? 
                       ORDER BY settlement_date DESC LIMIT ?""",
                    (telegram_user_id, limit)
                )
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get settlement history for user {telegram_user_id}: {e}")
            return []

    def get_settlement_by_id(self, settlement_id: int) -> Optional[Dict]:
        """Get settlement details by ID"""
        try:
            with self.get_connection() as conn:
                cursor = conn.execute(
                    "SELECT * FROM user_settlements WHERE id = ?",
                    (settlement_id,)
                )
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Failed to get settlement {settlement_id}: {e}")
            return None

    def get_verifications_by_settlement(self, settlement_id: int) -> List[Dict]:
        """Get all verifications linked to a settlement"""
        try:
            with self.get_connection() as conn:
                cursor = conn.execute(
                    """SELECT * FROM balance_verifications 
                       WHERE settlement_id = ? 
                       ORDER BY created_at ASC""",
                    (settlement_id,)
                )
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get verifications for settlement {settlement_id}: {e}")
            return []

    def get_user_verifications_count(self, telegram_user_id: int) -> int:
        """Get count of unsettled verifications for a user"""
        try:
            with self.get_connection() as conn:
                cursor = conn.execute(
                    """SELECT COUNT(*) as count 
                       FROM balance_verifications 
                       WHERE telegram_user_id = ? AND result = 'success' AND settlement_id IS NULL""",
                    (telegram_user_id,)
                )
                row = cursor.fetchone()
                return row['count'] if row else 0
        except Exception as e:
            logger.error(f"Failed to get verification count for user {telegram_user_id}: {e}")
            return 0

    def update_user_group(self, telegram_user_id: int, group_id: int = None) -> bool:
        """Update user's group assignment"""
        try:
            with self.get_connection() as conn:
                cursor = conn.execute(
                    "UPDATE telegram_users SET group_id = ? WHERE id = ?",
                    (group_id, telegram_user_id)
                )
                conn.commit()
                logger.info(f"Updated user {telegram_user_id} group to {group_id}")
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Failed to update user group: {e}")
            return False

    def update_settlement_pdf_path(self, settlement_id: int, pdf_path: str) -> bool:
        """Update settlement with PDF file path"""
        try:
            with self.get_connection() as conn:
                cursor = conn.execute(
                    "UPDATE user_settlements SET pdf_file_path = ? WHERE id = ?",
                    (pdf_path, settlement_id)
                )
                conn.commit()
                logger.info(f"Updated settlement {settlement_id} with PDF path: {pdf_path}")
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Failed to update settlement PDF path: {e}")
            return False

    def get_group_users(self, group_name: str) -> List[Dict]:
        """Get all users in a specific group by group name"""
        try:
            with self.get_connection() as conn:
                cursor = conn.execute("""
                    SELECT tu.id, tu.telegram_id, tu.full_name, tu.phone_number, 
                           tu.status, tu.created_at, g.group_name
                    FROM telegram_users tu
                    JOIN groups g ON tu.group_id = g.id
                    WHERE g.group_name = ? AND tu.status = 'approved'
                """, (group_name,))
                
                users = [dict(row) for row in cursor.fetchall()]
                logger.info(f"Found {len(users)} users in group '{group_name}'")
                return users
        except Exception as e:
            logger.error(f"Failed to get group users for '{group_name}': {e}")
            return []

    def get_all_admin_users(self) -> List[Dict]:
        """Get all admin users from telegram_users table"""
        try:
            with self.get_connection() as conn:
                cursor = conn.execute("""
                    SELECT id, telegram_id, full_name, phone_number, status, created_at
                    FROM telegram_users 
                    WHERE is_admin = 1
                """)
                
                admins = [dict(row) for row in cursor.fetchall()]
                logger.info(f"Found {len(admins)} admin users")
                return admins
        except Exception as e:
            logger.error(f"Failed to get admin users: {e}")
            return []
    
    def get_group_users_by_group_id(self, group_id: int) -> List[Dict]:
        """Get all approved users in a specific group by group ID"""
        try:
            with self.get_connection() as conn:
                cursor = conn.execute("""
                    SELECT tu.id, tu.telegram_id, tu.full_name, tu.phone_number, 
                           tu.status, tu.created_at, g.group_name
                    FROM telegram_users tu
                    JOIN groups g ON tu.group_id = g.id
                    WHERE g.id = ? AND tu.status = 'approved'
                """, (group_id,))
                
                users = [dict(row) for row in cursor.fetchall()]
                logger.info(f"Found {len(users)} users in group ID {group_id}")
                return users
        except Exception as e:
            logger.error(f"Failed to get group users for group ID {group_id}: {e}")
            return []

# Global database instance
db = DatabaseManager()
