"""
SimPulse Main System
Event-driven modem-SIM management system coordinator
"""

import sys
import os
import time
import logging
import signal
import threading
from datetime import datetime
from typing import Dict, List

# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.config import LOG_LEVEL, LOG_FORMAT, LOG_FILE
from core.database import db
from core.modem_detector import modem_detector
from core.device_monitor import device_monitor
from core.sim_manager import sim_manager
from core.sms_poller import sms_poller
from core.group_manager import group_manager
from telegram_bot.bot import SimPulseTelegramBot

# Setup logging
logging.basicConfig(
    level=LOG_LEVEL,
    format=LOG_FORMAT,
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class SimPulseSystem:
    """Main system coordinator for SimPulse modem-SIM management"""
    
    def __init__(self):
        self.running = False
        self.shutdown_event = threading.Event()
        self.stats = {
            'start_time': None,
            'total_modems_detected': 0,
            'extraction_count': 0
        }
        
        # Auto-restart system (DISABLED by default for stability)
        self.cycle_counter = 0
        self.max_cycles_before_restart = 1000  # Increased to prevent frequent restarts
        self.auto_restart_enabled = False  # Disabled auto-restart to fix conflicts
        
        # Initialize Telegram Bot
        self.telegram_bot = SimPulseTelegramBot()
        
        # Register telegram bot for SIM swap notifications
        from core.group_manager import register_telegram_bot
        register_telegram_bot(self.telegram_bot)
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        # Setup callbacks
        self._setup_callbacks()
        
        logger.info("SimPulse System initialized")
    
    def _setup_callbacks(self):
        """Setup callbacks for all components"""
        # Modem detector callbacks
        modem_detector.set_callbacks(
            on_modem_detected=self._on_modem_detected,
            on_modem_removed=self._on_modem_removed,
            on_scan_complete=self._on_scan_complete
        )
        
        # SIM manager callbacks
        sim_manager.set_callbacks(
            on_info_extracted=self._on_sim_info_extracted,
            on_extraction_failed=self._on_extraction_failed,
            on_sim_swap=self._on_sim_swap_detected
        )
        
        # SMS polling will be started after SIM extraction completes
    
    def start(self):
        """Start the SimPulse system"""
        try:
            logger.info("=" * 60)
            logger.info("STARTING SIMPULSE MODEM-SIM SYSTEM")
            logger.info("🚀 ENHANCED WITH REAL-TIME WMI MONITORING")
            logger.info("=" * 60)
            
            self.running = True
            self.stats['start_time'] = datetime.now()
            
            # Print system info
            self._print_system_info()
            
            # Start Telegram Bot
            logger.info("[BOT] Starting Telegram Bot...")
            self.telegram_bot.start_bot()
            
            # Start enhanced modem detection with real-time monitoring
            logger.info("[SCAN] Starting enhanced modem detection...")
            modem_detector.start_detection()
            
            # Start main loop
            self._main_loop()
            
        except Exception as e:
            logger.error(f"Failed to start SimPulse system: {e}")
            self.shutdown()
    
    def shutdown(self):
        """Shutdown the SimPulse system"""
        try:
            logger.info("=" * 60)
            logger.info("SHUTTING DOWN SIMPULSE SYSTEM")
            logger.info("=" * 60)
            
            self.running = False
            self.shutdown_event.set()
            
            # Stop Telegram Bot
            logger.info("[SHUTDOWN] Stopping Telegram Bot...")
            if hasattr(self, 'telegram_bot'):
                self.telegram_bot.stop_bot()
            
            # Stop SMS polling
            logger.info("[SHUTDOWN] Stopping SMS polling...")
            sms_poller.stop_polling()
            
            # Stop enhanced modem detection and device monitoring
            logger.info("[SHUTDOWN] Stopping enhanced modem detection...")
            modem_detector.stop_detection()
            
            # Cleanup groups
            logger.info("[SHUTDOWN] Cleaning up orphaned groups...")
            cleaned_count = group_manager.cleanup_orphaned_groups()
            if cleaned_count > 0:
                logger.info(f"[SHUTDOWN] Cleaned up {cleaned_count} orphaned groups")
            
            # Print final statistics
            self._print_final_stats()
            
            logger.info("SimPulse system shutdown complete")
            
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")
    
    def _main_loop(self):
        """Main system loop with optional auto-restart (disabled by default)"""
        try:
            logger.info("[SYSTEM] Main loop started")
            
            while self.running and not self.shutdown_event.is_set():
                try:
                    # Increment cycle counter
                    self.cycle_counter += 1
                    
                    # Check for auto-restart condition (DISABLED for stability - only on manual trigger)
                    # Auto-restart was causing conflicts, so it's now disabled by default
                    if self.auto_restart_enabled and self.cycle_counter >= self.max_cycles_before_restart:
                        logger.info("=" * 60)
                        logger.info(f"🔄 [AUTO-RESTART] Cycle {self.cycle_counter} reached - RESTARTING SYSTEM")
                        logger.info("=" * 60)
                        
                        # Initiate system restart
                        self._restart_system()
                        break  # Exit main loop to restart
                    
                    # Print status every 30 seconds
                    if int(time.time()) % 30 == 0:
                        self._print_status_update()
                    
                    # Check for any maintenance tasks
                    self._perform_maintenance()
                    
                    # Small sleep to prevent busy waiting (1 second per cycle)
                    time.sleep(1)
                    
                except KeyboardInterrupt:
                    logger.info("Keyboard interrupt received")
                    break
                except Exception as e:
                    logger.error(f"Error in main loop: {e}")
                    time.sleep(5)  # Wait before retrying
            
        except Exception as e:
            logger.error(f"Main loop error: {e}")
        finally:
            if self.cycle_counter < self.max_cycles_before_restart:
                # Normal shutdown (not auto-restart)
                self.shutdown()
    
    def _restart_system(self):
        """Restart the entire system - clean shutdown and fresh start (IMPROVED)"""
        try:
            logger.info("🔄 [RESTART] Starting system restart process...")
            
            # 1. Stop all current operations gracefully
            logger.info("🛑 [RESTART] Stopping all current operations...")
            
            # Stop Telegram Bot PROPERLY to avoid conflicts
            logger.info("🤖 [RESTART] Stopping Telegram Bot...")
            if hasattr(self, 'telegram_bot') and self.telegram_bot:
                self.telegram_bot.stop_bot()
                # Clear reference to prevent memory leaks
                self.telegram_bot = None
                
                # Give time for bot to fully shutdown
                time.sleep(5)
            
            # Stop SMS polling
            logger.info("📱 [RESTART] Stopping SMS polling...")
            sms_poller.stop_polling()
            
            # Stop modem detection and monitoring
            logger.info("📡 [RESTART] Stopping modem detection...")
            modem_detector.stop_detection()
            
            # Clear detection state
            logger.info("🧹 [RESTART] Clearing detection state...")
            if hasattr(self, '_initial_scan_complete'):
                delattr(self, '_initial_scan_complete')
            
            # Reset cycle counter for fresh start
            self.cycle_counter = 0
            
            # Longer delay to ensure clean shutdown
            logger.info("⏳ [RESTART] Waiting for clean shutdown...")
            time.sleep(8)
            
            # 2. Fresh restart of all components
            logger.info("🚀 [RESTART] Starting fresh system initialization...")
            
            # Restart Telegram Bot with NEW instance
            logger.info("🤖 [RESTART] Restarting Telegram Bot...")
            self.telegram_bot = SimPulseTelegramBot()
            from core.group_manager import register_telegram_bot
            register_telegram_bot(self.telegram_bot)
            self.telegram_bot.start_bot()
            
            # Restart modem detection
            logger.info("📡 [RESTART] Restarting modem detection...")
            modem_detector.start_detection()
            
            # Continue with main loop (SMS polling will start after scan complete)
            logger.info("✅ [RESTART] System restart completed - continuing with main loop...")
            
        except Exception as e:
            logger.error(f"❌ [RESTART] Error during system restart: {e}")
            # If restart fails, do normal shutdown
            self.shutdown()
    
    def _signal_handler(self, signum, frame):
        """Handle system signals"""
        logger.info(f"Signal {signum} received, initiating shutdown")
        self.shutdown()
    
    def _on_modem_detected(self, modem_info: Dict):
        """Handle modem detection event - Process new modems immediately"""
        try:
            imei = modem_info['imei']
            port = modem_info['port']
            
            logger.info(f"📱 [MODEM] Detected: IMEI {imei} on port {port}")
            self.stats['total_modems_detected'] += 1
            
            # Check if this is a brand new modem (detected during runtime)
            # If we're not in initial scan mode, process it immediately
            if self.running and hasattr(self, '_initial_scan_complete'):
                logger.info(f"🆕 [NEW MODEM] Processing new modem {imei} immediately")
                self._process_new_modem(modem_info)
            else:
                logger.info(f"📱 [MODEM] Modem {imei} registered, will extract info after scan complete")
            
        except Exception as e:
            logger.error(f"Error handling modem detection: {e}")
            
    def _process_new_modem(self, modem_info: Dict):
        """Process a newly detected modem immediately"""
        try:
            imei = modem_info['imei']
            port = modem_info['port']
            modem_id = modem_info['id']
            
            logger.info(f"🔄 [NEW MODEM] Starting immediate processing for IMEI {imei}")
            
            # Check if SIM already exists for this modem
            sim = db.get_sim_by_modem(modem_id)
            
            if sim:
                # SIM exists - re-extract to ensure fresh data
                logger.info(f"♻️ [NEW MODEM] SIM exists for IMEI {imei} - RE-EXTRACTING fresh data")
                sim_id = sim['id']
            else:
                # No SIM exists, create new one
                logger.info(f"➕ [NEW MODEM] Creating new SIM for IMEI {imei}")
                sim_id = db.add_sim(modem_id)
            
            # Extract SIM information immediately
            sim_info = {
                'imei': imei,
                'id': sim_id,
                'port': port
            }
            
            logger.info(f"🔍 [NEW MODEM] Starting info extraction for IMEI {imei} on port {port}")
            
            # Run extraction in separate thread to avoid blocking
            def extract_worker():
                try:
                    result = sim_manager.extract_sim_info_sequential(sim_info)
                    
                    if result:
                        logger.info(f"✅ [NEW MODEM] Extraction completed for IMEI {imei}")
                        
                        # Update group management - SMS polling will pick up automatically
                        logger.info(f"� [NEW MODEM] Assigning IMEI {imei} to group")
                        group_id = group_manager.assign_modem_to_group(imei)
                        
                        if group_id:
                            logger.info(f"🎉 [NEW MODEM] IMEI {imei} fully integrated into system!")
                        else:
                            logger.warning(f"⚠️ [NEW MODEM] IMEI {imei} processed but group assignment failed")
                        
                    else:
                        logger.error(f"❌ [NEW MODEM] Extraction failed for IMEI {imei}")
                        
                except Exception as e:
                    logger.error(f"❌ [NEW MODEM] Processing failed for IMEI {imei}: {e}")
            
            # Start extraction in background
            threading.Thread(target=extract_worker, daemon=True).start()
            
        except Exception as e:
            logger.error(f"Error processing new modem {modem_info.get('imei', 'Unknown')}: {e}")
    
    def _on_modem_removed(self, modem_info: Dict):
        """Handle modem removal event"""
        try:
            imei = modem_info['imei']
            logger.info(f"📱 [MODEM] Removed: IMEI {imei}")
            
            # SMS polling will handle modem removal automatically
            
        except Exception as e:
            logger.error(f"Error handling modem removal: {e}")
    
    def _on_scan_complete(self):
        """Handle scan completion event - Start processing modems one by one"""
        try:
            logger.info("[SCAN] ✅ Modem scan completed")
            
            # Get all detected modems
            modems = db.get_all_modems()
            
            if not modems:
                logger.info("[SCAN] No modems found")
                # Mark initial scan as complete even if no modems found
                self._initial_scan_complete = True
                return
            
            logger.info(f"[SCAN] Found {len(modems)} modems, starting sequential SIM extraction")
            
            # Process each modem one by one
            for i, modem in enumerate(modems):
                logger.info(f"[PROCESS] Processing modem {i+1}/{len(modems)}: IMEI {modem['imei']}")
                
                # Check if SIM already exists for this modem
                sim = db.get_sim_by_modem(modem['id'])
                
                if sim:
                    # SIM exists - ALWAYS re-extract to ensure fresh data
                    logger.info(f"[PROCESS] SIM exists for IMEI {modem['imei']} - RE-EXTRACTING fresh data")
                    self._extract_sim_info_for_modem(modem, sim['id'])
                else:
                    # No SIM exists, create and extract
                    logger.info(f"[PROCESS] Creating new SIM for IMEI {modem['imei']}")
                    sim_id = db.add_sim(modem['id'])
                    self._extract_sim_info_for_modem(modem, sim_id)
                
                # Wait between modems to avoid conflicts
                logger.info(f"⏱️  [PROCESS] Waiting 3 seconds before next modem...")
                time.sleep(3)
            
            logger.info("[PROCESS] ✅ All modems processed")
            
            # Mark initial scan as complete
            self._initial_scan_complete = True
            logger.info("[SYSTEM] 🎯 Initial scan complete - now will process new modems immediately")
            
            # **NEW: Initial Balance Check for All SIMs**
            logger.info("[BALANCE] 🚀 Starting initial balance check for all active SIMs...")
            from core.balance_checker import balance_checker
            balance_results = balance_checker.initial_balance_check_for_all_sims()
            
            checked = balance_results.get('checked', 0)
            updated = balance_results.get('updated', 0)
            failed = balance_results.get('failed', 0)
            total = balance_results.get('total_sims', 0)
            
            logger.info(f"[BALANCE] ✅ Initial balance check completed:")
            logger.info(f"          📊 Total SIMs: {total}")
            logger.info(f"          ✅ Successfully checked: {checked}")
            logger.info(f"          🔄 Updated balances: {updated}")
            logger.info(f"          ❌ Failed checks: {failed}")
            
            if failed > 0:
                logger.warning(f"[BALANCE] ⚠️  {failed} SIMs failed balance check - see details in logs")
            
            # Start SMS polling after all SIM info extraction is complete
            logger.info("[SMS] 🔄 Starting SMS polling system...")
            sms_poller.start_polling()
            logger.info("[SMS] ✅ SMS polling started")
            
            # Print group summary after everything is set up
            logger.info("[GROUP] 📁 Printing group summary...")
            group_manager.print_group_summary()
            
        except Exception as e:
            logger.error(f"Error handling scan completion: {e}")
    
    def _extract_sim_info_for_modem(self, modem: Dict, sim_id: int):
        """Extract SIM info for a specific modem"""
        try:
            # Find the working port for this modem
            working_port = self._find_working_port(modem['imei'])
            
            if not working_port:
                logger.error(f"❌ [SIM] No working port found for IMEI {modem['imei']}")
                return
            
            sim_info = {
                'imei': modem['imei'],
                'id': sim_id,
                'port': working_port
            }
            
            logger.info(f"🔍 [SIM] Starting info extraction for IMEI {modem['imei']} on port {working_port}")
            
            # Use sequential extraction with proper error handling
            try:
                result = sim_manager.extract_sim_info_sequential(sim_info)
                
                if result:
                    logger.info(f"✅ [SIM] Extraction completed for IMEI {modem['imei']}")
                else:
                    logger.error(f"❌ [SIM] Extraction failed for IMEI {modem['imei']}")
                    
            except Exception as e:
                logger.error(f"❌ [SIM] Extraction failed for IMEI {modem['imei']}: {e}")
            
        except Exception as e:
            logger.error(f"Error extracting SIM info for modem {modem['imei']}: {e}")
    
    def _find_working_port(self, imei: str) -> str:
        """Find the working port for a modem by IMEI"""
        try:
            # Check if we have the modem in our known modems
            if imei in modem_detector.known_modems:
                return modem_detector.known_modems[imei]['port']
            
            logger.warning(f"Modem {imei} not in known modems")
            return None
            
        except Exception as e:
            logger.error(f"Error finding working port for IMEI {imei}: {e}")
            return None
    
    def _on_sim_info_extracted(self, sim_info: Dict):
        """Handle SIM info extraction completion"""
        try:
            imei = sim_info['imei']
            phone_number = sim_info.get('phone_number', '')
            balance = sim_info.get('balance', '')
            
            logger.info(f"📞 [SIM] Info extracted for IMEI {imei}")
            logger.info(f"     Phone: {phone_number}")
            logger.info(f"     Balance: {balance}")
            
            self.stats['extraction_count'] += 1
            
            # Auto-create group for this modem
            try:
                modem = db.get_modem_by_imei(imei)
                if modem:
                    group_id = group_manager.auto_create_group_for_modem(modem['id'], imei)
                    if group_id:
                        logger.info(f"📁 [GROUP] Auto-created group for IMEI {imei}")
                    else:
                        logger.info(f"📁 [GROUP] Group already exists or auto-create disabled for IMEI {imei}")
                else:
                    logger.error(f"❌ [GROUP] Could not find modem for IMEI {imei}")
            except Exception as e:
                logger.error(f"❌ [GROUP] Failed to create group for IMEI {imei}: {e}")
            
            # SMS polling will start after all SIM extractions complete
            logger.info(f"✅ [SIM] Registration completed for IMEI {imei}")
            
        except Exception as e:
            logger.error(f"Error handling SIM info extraction: {e}")
    
    def _on_extraction_failed(self, sim_info: Dict):
        """Handle SIM extraction failure"""
        try:
            imei = sim_info['imei']
            error = sim_info.get('error', 'Unknown error')
            
            logger.error(f"❌ [SIM] Extraction failed for IMEI {imei}: {error}")
            
        except Exception as e:
            logger.error(f"Error handling extraction failure: {e}")
    
    def _on_sim_swap_detected(self, sim_swap_info: Dict):
        """Handle SIM swap detection and send notifications"""
        try:
            imei = sim_swap_info['imei']
            old_phone = sim_swap_info['old_phone_number']
            new_phone = sim_swap_info['new_phone_number']
            old_balance = sim_swap_info['old_balance']
            new_balance = sim_swap_info['new_balance']
            
            logger.info(f"🔄 [SIM SWAP] Detected for IMEI {imei}")
            logger.info(f"     Old: {old_phone} ({old_balance})")
            logger.info(f"     New: {new_phone} ({new_balance})")
            
            # Get group information for this modem
            modem_info = db.get_modem_by_imei(imei)
            if not modem_info:
                logger.error(f"❌ [SIM SWAP] Modem not found for IMEI {imei}")
                return
            
            # Get group name
            group_info = group_manager.get_group_by_modem_id(modem_info['id'])
            if not group_info:
                logger.error(f"❌ [SIM SWAP] No group assigned to modem {imei}")
                return
            
            group_name = group_info['group_name']
            
            # Send notifications via Telegram Bot
            if hasattr(self, 'telegram_bot') and self.telegram_bot:
                import asyncio
                
                # Get or create event loop for async notification
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                
                # Send notification
                loop.create_task(self.telegram_bot.admin_service.notify_sim_swap(
                    group_name=group_name,
                    imei=imei,
                    old_sim_number=old_phone,
                    new_sim_number=new_phone,
                    old_balance=old_balance,
                    new_balance=new_balance
                ))
                
                logger.info(f"✅ [SIM SWAP] Notification sent for group {group_name}")
            else:
                logger.warning("⚠️ [SIM SWAP] Telegram bot not available for notifications")
            
        except Exception as e:
            logger.error(f"Error handling SIM swap detection: {e}")

    def _print_system_info(self):
        """Print system information"""
        try:
            logger.info("SYSTEM INFORMATION")
            logger.info(f"     Database: {db.db_path}")
            logger.info(f"     Log file: {LOG_FILE}")
            logger.info(f"     Enhanced Detection: WMI + Initial Scan")
            logger.info(f"     Real-time Monitoring: Active")
            logger.info(f"     Auto-restart: {'DISABLED' if not self.auto_restart_enabled else f'Every {self.max_cycles_before_restart} cycles'} (fixed Telegram bot conflicts)")
            
            # Get device monitor status
            monitor_status = device_monitor.get_status()
            logger.info(f"     Device Monitor: {monitor_status}")
            
            # Get system stats
            stats = db.get_system_stats()
            logger.info(f"     Active modems: {stats.get('active_modems', 0)}")
            logger.info(f"     Active SIMs: {stats.get('active_sims', 0)}")
            logger.info(f"     Active groups: {stats.get('active_groups', 0)}")
            logger.info(f"     SIMs needing extraction: {stats.get('sims_needing_extraction', 0)}")
            logger.info(f"     Total SMS messages: {stats.get('total_sms', 0)}")
            logger.info(f"     SMS last 24h: {stats.get('sms_last_24h', 0)}")
            
        except Exception as e:
            logger.error(f"Error printing system info: {e}")
    
    def _print_status_update(self):
        """Print periodic status update"""
        try:
            uptime = datetime.now() - self.stats['start_time']
            logger.info("📈 STATUS UPDATE")
            logger.info(f"     Uptime: {uptime}")
            logger.info(f"     Cycle: {self.cycle_counter}/{self.max_cycles_before_restart}")
            logger.info(f"     Modems detected: {self.stats['total_modems_detected']}")
            logger.info(f"     Extractions: {self.stats['extraction_count']}")
            
            # Device monitor status
            monitor_status = device_monitor.get_status()
            logger.info(f"     Real-time monitoring: {'Active' if monitor_status['monitoring'] else 'Inactive'}")
            logger.info(f"     Tracked devices: {monitor_status['known_devices']}")
            logger.info(f"     Tracked COM ports: {monitor_status['known_com_ports']}")
            
            # SMS polling status
            sms_status = sms_poller.get_status()
            if sms_status['active']:
                sms_stats = sms_status['stats']
                logger.info(f"     SMS polling: Active ({sms_status['total_sims']} SIMs)")
                logger.info(f"     SMS found: {sms_stats['total_sms_found']}")
                logger.info(f"     SMS saved: {sms_stats['total_sms_saved']}")
                logger.info(f"     SMS deleted: {sms_stats['total_sms_deleted']}")
            else:
                logger.info(f"     SMS polling: Inactive")
            
        except Exception as e:
            logger.error(f"Error printing status update: {e}")
    
    def _print_final_stats(self):
        """Print final statistics"""
        try:
            if self.stats['start_time']:
                total_runtime = datetime.now() - self.stats['start_time']
                logger.info("FINAL STATISTICS")
                logger.info(f"     Total runtime: {total_runtime}")
                logger.info(f"     Modems detected: {self.stats['total_modems_detected']}")
                logger.info(f"     Extractions: {self.stats['extraction_count']}")
                
                # Final SMS stats
                sms_stats = sms_poller.get_stats()
                logger.info(f"     SMS polls: {sms_stats['total_polls']}")
                logger.info(f"     SMS found: {sms_stats['total_sms_found']}")
                logger.info(f"     SMS saved: {sms_stats['total_sms_saved']}")
                logger.info(f"     SMS deleted: {sms_stats['total_sms_deleted']}")
                
                # Final group stats
                group_stats = group_manager.get_stats()
                logger.info(f"     Total groups: {group_stats.get('total_groups', 0)}")
                logger.info(f"     Groups with SIM info: {group_stats.get('groups_with_sim_info', 0)}")
                
        except Exception as e:
            logger.error(f"Error printing final stats: {e}")
    
    def _perform_maintenance(self):
        """Perform periodic maintenance tasks"""
        try:
            # Placeholder for future maintenance tasks
            if int(time.time()) % 1800 == 0:  # Every 30 minutes
                pass
                
        except Exception as e:
            logger.error(f"Error performing maintenance: {e}")

def main():
    """Main entry point"""
    try:
        system = SimPulseSystem()
        system.start()
        
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
    finally:
        logger.info("System terminated")

if __name__ == "__main__":
    main()
