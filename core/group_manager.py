"""
SimPulse Group Manager
Automatically creates and manages groups for modems
Groups are auto-generated when modems are registered and SIM info is extracted
"""

import logging
from typing import Dict, List, Optional
from datetime import datetime
from .database import db

logger = logging.getLogger(__name__)

class GroupManager:
    """Handles automatic group creation and management for modems"""
    
    def __init__(self):
        self.group_prefix = "GROUP_"
        self.auto_create_enabled = True
        
        logger.info("Group Manager initialized")
    
    def auto_create_group_for_modem(self, modem_id: int, imei: str) -> Optional[int]:
        """Automatically create a group for a modem when SIM info is extracted"""
        try:
            # Check if modem already has a group
            existing_group = self.get_group_by_modem_id(modem_id)
            if existing_group:
                logger.info(f"📁 Modem {imei} already has group: {existing_group['group_name']}")
                
                # Check if this is a SIM swap (different phone number)
                self._handle_potential_sim_swap(modem_id, imei, existing_group['id'])
                
                return existing_group['id']
            
            if not self.auto_create_enabled:
                logger.info(f"Auto-create disabled, skipping group creation for modem {imei}")
                return None
            
            # Generate unique group name based on IMEI
            group_name = self._generate_group_name(imei)
            
            # Create the group
            group_id = self.add_group(group_name, modem_id)
            
            logger.info(f"✅ Auto-created group '{group_name}' for modem {imei} (ID: {group_id})")
            return group_id
            
        except Exception as e:
            logger.error(f"Failed to auto-create group for modem {imei}: {e}")
            return None
    
    def add_group(self, group_name: str, modem_id: int) -> int:
        """Add new group to database"""
        try:
            with db.get_connection() as conn:
                cursor = conn.execute(
                    "INSERT INTO groups (group_name, modem_id) VALUES (?, ?)",
                    (group_name, modem_id)
                )
                group_id = cursor.lastrowid
                conn.commit()
                logger.info(f"Added group '{group_name}' for modem {modem_id}")
                return group_id
        except Exception as e:
            logger.error(f"Failed to add group '{group_name}' for modem {modem_id}: {e}")
            raise
    
    def get_group_by_id(self, group_id: int) -> Optional[Dict]:
        """Get group by ID"""
        try:
            with db.get_connection() as conn:
                cursor = conn.execute(
                    """SELECT g.*, m.imei, s.phone_number, s.balance 
                       FROM groups g 
                       JOIN modems m ON g.modem_id = m.id 
                       LEFT JOIN sims s ON m.id = s.modem_id AND s.status = 'active'
                       WHERE g.id = ? AND g.status = 'active'""",
                    (group_id,)
                )
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Failed to get group {group_id}: {e}")
            return None
    
    def get_group_by_name(self, group_name: str) -> Optional[Dict]:
        """Get group by name"""
        try:
            with db.get_connection() as conn:
                cursor = conn.execute(
                    """SELECT g.*, m.imei, s.phone_number, s.balance 
                       FROM groups g 
                       JOIN modems m ON g.modem_id = m.id 
                       LEFT JOIN sims s ON m.id = s.modem_id AND s.status = 'active'
                       WHERE g.group_name = ? AND g.status = 'active'""",
                    (group_name,)
                )
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Failed to get group '{group_name}': {e}")
            return None
    
    def get_group_by_modem_id(self, modem_id: int) -> Optional[Dict]:
        """Get group by modem ID"""
        try:
            with db.get_connection() as conn:
                cursor = conn.execute(
                    """SELECT g.*, m.imei, s.phone_number, s.balance 
                       FROM groups g 
                       JOIN modems m ON g.modem_id = m.id 
                       LEFT JOIN sims s ON m.id = s.modem_id AND s.status = 'active'
                       WHERE g.modem_id = ? AND g.status = 'active'""",
                    (modem_id,)
                )
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Failed to get group for modem {modem_id}: {e}")
            return None
    
    def get_group_by_imei(self, imei: str) -> Optional[Dict]:
        """Get group by modem IMEI"""
        try:
            with db.get_connection() as conn:
                cursor = conn.execute(
                    """SELECT g.*, m.imei, s.phone_number, s.balance 
                       FROM groups g 
                       JOIN modems m ON g.modem_id = m.id 
                       LEFT JOIN sims s ON m.id = s.modem_id AND s.status = 'active'
                       WHERE m.imei = ? AND g.status = 'active' AND m.status = 'active'""",
                    (imei,)
                )
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Failed to get group for IMEI {imei}: {e}")
            return None
    
    def get_all_groups(self) -> List[Dict]:
        """Get all active groups with modem and SIM info"""
        try:
            with db.get_connection() as conn:
                cursor = conn.execute(
                    """SELECT g.*, m.imei, s.phone_number, s.balance 
                       FROM groups g 
                       JOIN modems m ON g.modem_id = m.id 
                       LEFT JOIN sims s ON m.id = s.modem_id AND s.status = 'active'
                       WHERE g.status = 'active' AND m.status = 'active'
                       ORDER BY g.created_at"""
                )
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get all groups: {e}")
            return []
    
    def update_group_name(self, group_id: int, new_name: str) -> bool:
        """Update group name"""
        try:
            with db.get_connection() as conn:
                cursor = conn.execute(
                    "UPDATE groups SET group_name = ? WHERE id = ? AND status = 'active'",
                    (new_name, group_id)
                )
                conn.commit()
                success = cursor.rowcount > 0
                if success:
                    logger.info(f"Updated group {group_id} name to '{new_name}'")
                return success
        except Exception as e:
            logger.error(f"Failed to update group {group_id} name: {e}")
            return False
    
    def reassign_group_modem(self, group_id: int, new_modem_id: int) -> bool:
        """Reassign group to different modem (for SIM swapping)"""
        try:
            with db.get_connection() as conn:
                cursor = conn.execute(
                    "UPDATE groups SET modem_id = ? WHERE id = ? AND status = 'active'",
                    (new_modem_id, group_id)
                )
                conn.commit()
                success = cursor.rowcount > 0
                if success:
                    logger.info(f"Reassigned group {group_id} to modem {new_modem_id}")
                return success
        except Exception as e:
            logger.error(f"Failed to reassign group {group_id} to modem {new_modem_id}: {e}")
            return False
    
    def delete_group(self, group_id: int) -> bool:
        """Mark group as inactive"""
        try:
            with db.get_connection() as conn:
                cursor = conn.execute(
                    "UPDATE groups SET status = 'inactive' WHERE id = ?",
                    (group_id,)
                )
                conn.commit()
                success = cursor.rowcount > 0
                if success:
                    logger.info(f"Deleted group {group_id}")
                return success
        except Exception as e:
            logger.error(f"Failed to delete group {group_id}: {e}")
            return False
    
    def enable_auto_create(self):
        """Enable automatic group creation"""
        self.auto_create_enabled = True
        logger.info("Group auto-creation enabled")
    
    def disable_auto_create(self):
        """Disable automatic group creation"""
        self.auto_create_enabled = False
        logger.info("Group auto-creation disabled")
    
    def get_stats(self) -> Dict:
        """Get group statistics"""
        try:
            with db.get_connection() as conn:
                stats = {}
                
                # Count total groups
                cursor = conn.execute("SELECT COUNT(*) FROM groups WHERE status = 'active'")
                stats['total_groups'] = cursor.fetchone()[0]
                
                # Count groups with extracted SIM info
                cursor = conn.execute("""
                    SELECT COUNT(*) FROM groups g 
                    JOIN modems m ON g.modem_id = m.id 
                    JOIN sims s ON m.id = s.modem_id 
                    WHERE g.status = 'active' AND m.status = 'active' 
                    AND s.status = 'active' AND s.info_extracted_at IS NOT NULL
                """)
                stats['groups_with_sim_info'] = cursor.fetchone()[0]
                
                # Count groups without SIM info
                stats['groups_without_sim_info'] = stats['total_groups'] - stats['groups_with_sim_info']
                
                return stats
        except Exception as e:
            logger.error(f"Failed to get group stats: {e}")
            return {}
    
    def _generate_group_name(self, imei: str) -> str:
        """Generate unique group name based on IMEI"""
        try:
            # Use last 6 digits of IMEI for readability
            imei_suffix = imei[-6:] if len(imei) >= 6 else imei
            base_name = f"{self.group_prefix}{imei_suffix}"
            
            # Check if name already exists
            counter = 1
            group_name = base_name
            
            while self.get_group_by_name(group_name):
                group_name = f"{base_name}_{counter}"
                counter += 1
                
                # Safety check to prevent infinite loop
                if counter > 100:
                    # Fallback to timestamp
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    group_name = f"{self.group_prefix}{timestamp}"
                    break
            
            return group_name
            
        except Exception as e:
            logger.error(f"Failed to generate group name for IMEI {imei}: {e}")
            # Fallback to timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            return f"{self.group_prefix}{timestamp}"
    
    def _handle_potential_sim_swap(self, modem_id: int, imei: str, group_id: int):
        """Handle potential SIM swap detection"""
        try:
            # Get current SIM info for this modem
            with db.get_connection() as conn:
                cursor = conn.execute("""
                    SELECT phone_number, balance, created_at 
                    FROM sims 
                    WHERE modem_id = ? AND status = 'active'
                    ORDER BY created_at DESC LIMIT 2
                """, (modem_id,))
                sims = cursor.fetchall()
            
            if len(sims) > 1:
                current_sim = sims[0]
                previous_sim = sims[1]
                
                # Check if phone number changed (indicating SIM swap)
                current_phone = current_sim['phone_number']
                previous_phone = previous_sim['phone_number']
                
                if current_phone and previous_phone and current_phone != previous_phone:
                    logger.info(f"🔄 SIM SWAP detected for IMEI {imei}:")
                    logger.info(f"   Previous SIM: {previous_phone}")
                    logger.info(f"   New SIM: {current_phone}")
                    logger.info(f"   Group '{group_id}' maintained - no duplicate created")
                    
                    # Log this event for tracking
                    self._log_sim_swap_event(group_id, modem_id, previous_phone, current_phone)
                    
        except Exception as e:
            logger.error(f"Error handling potential SIM swap for IMEI {imei}: {e}")
    
    def _log_sim_swap_event(self, group_id: int, modem_id: int, old_phone: str, new_phone: str):
        """Log SIM swap event for future reference"""
        try:
            # You could add a sim_swap_history table or log to file
            logger.info(f"📊 SIM_SWAP_LOG: Group {group_id}, Modem {modem_id}, {old_phone} → {new_phone}")
            
            # Optional: Could store this in database for historical tracking
            # with db.get_connection() as conn:
            #     conn.execute("""
            #         INSERT INTO sim_swap_history (group_id, modem_id, old_phone, new_phone, swap_date)
            #         VALUES (?, ?, ?, ?, ?)
            #     """, (group_id, modem_id, old_phone, new_phone, datetime.now()))
            #     conn.commit()
            
        except Exception as e:
            logger.error(f"Error logging SIM swap event: {e}")
    
    def cleanup_orphaned_groups(self) -> int:
        """Remove groups that reference non-existent or inactive modems"""
        try:
            with db.get_connection() as conn:
                cursor = conn.execute("""
                    UPDATE groups SET status = 'inactive' 
                    WHERE modem_id NOT IN (
                        SELECT id FROM modems WHERE status = 'active'
                    ) AND status = 'active'
                """)
                conn.commit()
                cleaned_count = cursor.rowcount
                
                if cleaned_count > 0:
                    logger.info(f"Cleaned up {cleaned_count} orphaned groups")
                
                return cleaned_count
                
        except Exception as e:
            logger.error(f"Failed to cleanup orphaned groups: {e}")
            return 0
    
    def print_group_summary(self):
        """Print summary of all groups"""
        try:
            groups = self.get_all_groups()
            stats = self.get_stats()
            
            logger.info("=" * 50)
            logger.info("GROUP MANAGER SUMMARY")
            logger.info("=" * 50)
            logger.info(f"Total Groups: {stats.get('total_groups', 0)}")
            logger.info(f"Groups with SIM Info: {stats.get('groups_with_sim_info', 0)}")
            logger.info(f"Groups without SIM Info: {stats.get('groups_without_sim_info', 0)}")
            logger.info(f"Auto-create: {'Enabled' if self.auto_create_enabled else 'Disabled'}")
            
            if groups:
                logger.info("\nACTIVE GROUPS:")
                for group in groups:
                    sim_info = f"{group.get('phone_number', 'N/A')} | {group.get('balance', 'N/A')}"
                    logger.info(f"  {group['group_name']} -> IMEI: {group['imei']} | SIM: {sim_info}")
            else:
                logger.info("\nNo active groups found")
            
            logger.info("=" * 50)
            
        except Exception as e:
            logger.error(f"Failed to print group summary: {e}")
    
    def get_group_with_modem_info(self, group_id: int) -> Optional[Dict]:
        """Get comprehensive group info including modem and SIM details"""
        try:
            with db.get_connection() as conn:
                cursor = conn.execute("""
                    SELECT 
                        g.*,
                        m.imei,
                        m.status as modem_status,
                        s.phone_number,
                        s.balance,
                        s.info_extracted_at,
                        s.status as sim_status,
                        COUNT(sms.id) as total_sms
                    FROM groups g
                    JOIN modems m ON g.modem_id = m.id
                    LEFT JOIN sims s ON m.id = s.modem_id AND s.status = 'active'
                    LEFT JOIN sms ON s.id = sms.sim_id
                    WHERE g.id = ? AND g.status = 'active'
                    GROUP BY g.id, m.id, s.id
                """, (group_id,))
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Failed to get comprehensive group info for {group_id}: {e}")
            return None
    
    def find_groups_by_phone_number(self, phone_number: str) -> List[Dict]:
        """Find groups by SIM phone number (useful for tracking SIM movements)"""
        try:
            with db.get_connection() as conn:
                cursor = conn.execute("""
                    SELECT g.*, m.imei, s.phone_number, s.balance 
                    FROM groups g 
                    JOIN modems m ON g.modem_id = m.id 
                    JOIN sims s ON m.id = s.modem_id 
                    WHERE s.phone_number = ? AND g.status = 'active' 
                    AND m.status = 'active' AND s.status = 'active'
                    ORDER BY s.created_at DESC
                """, (phone_number,))
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to find groups for phone number {phone_number}: {e}")
            return []

# Global group manager instance
group_manager = GroupManager()
