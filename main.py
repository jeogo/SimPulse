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
from core.sim_manager import sim_manager
from core.sms_poller import sms_poller
from core.group_manager import group_manager

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
            on_extraction_failed=self._on_extraction_failed
        )
        
        # SMS polling will be started after SIM extraction completes
    
    def start(self):
        """Start the SimPulse system"""
        try:
            logger.info("=" * 60)
            logger.info("STARTING SIMPULSE MODEM-SIM SYSTEM")
            logger.info("=" * 60)
            
            self.running = True
            self.stats['start_time'] = datetime.now()
            
            # Print system info
            self._print_system_info()
            
            # Start modem detection
            logger.info("[SCAN] Starting modem detection...")
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
            
            # Stop SMS polling
            logger.info("[SHUTDOWN] Stopping SMS polling...")
            sms_poller.stop_polling()
            
            # Stop modem detection
            logger.info("[SHUTDOWN] Stopping modem detection...")
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
        """Main system loop"""
        try:
            logger.info("[SYSTEM] Main loop started")
            
            while self.running and not self.shutdown_event.is_set():
                try:
                    # Print status every 30 seconds
                    if int(time.time()) % 30 == 0:
                        self._print_status_update()
                    
                    # Check for any maintenance tasks
                    self._perform_maintenance()
                    
                    # Small sleep to prevent busy waiting
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
            self.shutdown()
    
    def _signal_handler(self, signum, frame):
        """Handle system signals"""
        logger.info(f"Signal {signum} received, initiating shutdown")
        self.shutdown()
    
    def _on_modem_detected(self, modem_info: Dict):
        """Handle modem detection event - DO NOT CREATE SIM YET"""
        try:
            imei = modem_info['imei']
            port = modem_info['port']
            
            logger.info(f"📱 [MODEM] Detected: IMEI {imei} on port {port}")
            self.stats['total_modems_detected'] += 1
            
            logger.info(f"📱 [MODEM] Modem {imei} registered, will extract info after scan complete")
            
        except Exception as e:
            logger.error(f"Error handling modem detection: {e}")
    
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
    
    def _print_system_info(self):
        """Print system information"""
        try:
            logger.info("SYSTEM INFORMATION")
            logger.info(f"     Database: {db.db_path}")
            logger.info(f"     Log file: {LOG_FILE}")
            logger.info(f"     Max COM ports: {999}")
            
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
            logger.info(f"     Modems detected: {self.stats['total_modems_detected']}")
            logger.info(f"     Extractions: {self.stats['extraction_count']}")
            
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
