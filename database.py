"""
SimPulse Modem System Database Operations
SQLite database management for modem-SIM system
"""

import sqlite3
import os
import logging
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from config import DB_PATH, DB_TIMEOUT

logger = logging.getLogger(__name__)

class DatabaseManager:
    """Handles all database operations for the modem system"""
    
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Initialize database with schema"""
        try:
            schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
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
        """Update SIM information and mark as extracted if we have ANY info"""
        try:
            with self.get_connection() as conn:
                # Mark as extracted if we have ANY info (phone OR balance)
                if phone_number or balance:
                    conn.execute(
                        "UPDATE sims SET phone_number = ?, balance = ?, info_extracted_at = ? WHERE id = ?",
                        (phone_number, balance, datetime.now(), sim_id)
                    )
                    logger.info(f"Updated SIM {sim_id} with info and marked as extracted")
                    logger.info(f"Phone: {phone_number}, Balance: {balance}")
                else:
                    # No info at all - don't mark as extracted
                    logger.warning(f"No info to update for SIM {sim_id}")
                
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
                
                return stats
        except Exception as e:
            logger.error(f"Failed to get system stats: {e}")
            return {}

# Global database instance
db = DatabaseManager()
