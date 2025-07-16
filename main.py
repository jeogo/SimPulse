"""
SimPulse Main System
Event-driven modem-SIM management system coordinator
"""

import sys
import os
import time
import logging
import signal
impor    def _on_modem_detected(self, modem_info: Dict):
        """Handle modem detection event - DO NOT CREATE SIM YET"""
        try:
            imei = modem_info['imei']
            port = modem_info['port']
            
            logger.info(f"📱 [MODEM] Detected: IMEI {imei} on port {port}")
            self.stats['total_modems_detected'] += 1
            
            # DO NOT create SIM record yet - will be created after successful extraction
            logger.info(f"📱 [MODEM] Modem {imei} registered, will extract info after scan complete")
            
        except Exception as e:
            logger.error(f"Error handling modem detection: {e}")rom datetime import datetime
from typing import Dict, List

# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (
    LOG_LEVEL, 
    LOG_FORMAT, 
    LOG_FILE,
    CONSOLE_TIMESTAMPS,
    CONSOLE_COLORS,
    GRACEFUL_SHUTDOWN_TIMEOUT
)
from database import db
from modem_detector import modem_detector
from sim_manager import sim_manager

# Configure logging
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
            'total_sims_processed': 0,
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
        
        # NO SMS manager callbacks - SMS polling disabled
    
    def start(self):
        """Start the SimPulse system"""
        try:
            logger.info("=" * 60)
            logger.info("🚀 STARTING SIMPULSE MODEM-SIM SYSTEM")
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
            logger.info("🛑 SHUTTING DOWN SIMPULSE SYSTEM")
            logger.info("=" * 60)
            
            self.running = False
            self.shutdown_event.set()
            
            # Stop modem detection only (no SMS polling)
            logger.info("[SHUTDOWN] Stopping modem detection...")
            modem_detector.stop_detection()
            
            # Print final statistics
            self._print_final_stats()
            
            logger.info("✅ SimPulse system shutdown complete")
            
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
            primary_port = modem_info['primary_port']
            
            logger.info(f"📱 [MODEM] Detected: IMEI {imei} on port {primary_port}")
            self.stats['total_modems_detected'] += 1
            
            # DO NOT create SIM record yet - will be created after successful extraction
            logger.info(f"� [MODEM] Modem {imei} registered, will extract info after scan complete")
            
        except Exception as e:
            logger.error(f"Error handling modem detection: {e}")
    
    def _on_modem_removed(self, modem_info: Dict):
        """Handle modem removal event"""
        try:
            imei = modem_info['imei']
            logger.info(f"📱 [MODEM] Removed: IMEI {imei}")
            
            # No SMS polling to stop since it's disabled
            
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
            
        except Exception as e:
            logger.error(f"Error handling scan completion: {e}")
    
    def _extract_sim_info_for_modem(self, modem: Dict, sim_id: int):
        """Extract SIM info for a specific modem"""
        try:
            sim_info = {
                'imei': modem['imei'],
                'id': sim_id,
                'primary_port': modem['primary_port']
            }
            
            logger.info(f"🔍 [SIM] Starting info extraction for IMEI {modem['imei']}")
            
            # Use sequential extraction with proper error handling
            try:
                sim_manager.extract_sim_info_sequential(sim_info)
                logger.info(f"✅ [SIM] Extraction completed for IMEI {modem['imei']}")
            except Exception as e:
                logger.error(f"❌ [SIM] Extraction failed for IMEI {modem['imei']}: {e}")
                # Continue with next modem even if this one fails
            
        except Exception as e:
            logger.error(f"Error extracting SIM info for modem {modem['imei']}: {e}")
    
    def _on_sim_info_extracted(self, sim_info: Dict):
        """Handle SIM info extraction completion"""
        try:
            imei = sim_info['imei']
            phone_number = sim_info['phone_number']
            balance = sim_info['balance']
            
            logger.info(f"📞 [SIM] Info extracted for IMEI {imei}")
            logger.info(f"    Phone: {phone_number}")
            logger.info(f"    Balance: {balance}")
            
            self.stats['extraction_count'] += 1
            
            # NO SMS POLLING - as requested
            logger.info(f"✅ [SIM] Registration completed for IMEI {imei} - NO SMS POLLING")
            
        except Exception as e:
            logger.error(f"Error handling SIM info extraction: {e}")
    
    def _on_extraction_failed(self, error_info: Dict):
        """Handle SIM info extraction failure"""
        try:
            imei = error_info['imei']
            error = error_info['error']
            
            logger.error(f"❌ [SIM] Extraction failed for IMEI {imei}: {error}")
            
            # You might want to implement retry logic here
            
        except Exception as e:
            logger.error(f"Error handling extraction failure: {e}")
    
    def _print_system_info(self):
        """Print system information"""
        try:
            logger.info("📊 SYSTEM INFORMATION")
            logger.info(f"    Database: {db.db_path}")
            logger.info(f"    Log file: {LOG_FILE}")
            logger.info(f"    Max COM ports: {modem_detector.max_com_ports}")
            # SMS polling removed - system only does SIM extraction
            
            # Database stats
            db_stats = db.get_system_stats()
            logger.info(f"    Active modems: {db_stats.get('active_modems', 0)}")
            logger.info(f"    Active SIMs: {db_stats.get('active_sims', 0)}")
            logger.info(f"    SIMs needing extraction: {db_stats.get('sims_needing_extraction', 0)}")
            
        except Exception as e:
            logger.error(f"Error printing system info: {e}")
    
    def _print_status_update(self):
        """Print periodic status update"""
        try:
            uptime = datetime.now() - self.stats['start_time']
            
            logger.info("📈 STATUS UPDATE")
            logger.info(f"    Uptime: {uptime}")
            logger.info(f"    Modems detected: {self.stats['total_modems_detected']}")
            logger.info(f"    Extractions: {self.stats['extraction_count']}")
            # SMS polling removed - system only does SIM extraction
            
        except Exception as e:
            logger.error(f"Error printing status update: {e}")
    
    def _print_final_stats(self):
        """Print final statistics"""
        try:
            if self.stats['start_time']:
                total_runtime = datetime.now() - self.stats['start_time']
                
                logger.info("📊 FINAL STATISTICS")
                logger.info(f"    Total runtime: {total_runtime}")
                logger.info(f"    Modems detected: {self.stats['total_modems_detected']}")
                logger.info(f"    SIMs processed: {self.stats['total_sims_processed']}")
                logger.info(f"    Extractions: {self.stats['extraction_count']}")
            
        except Exception as e:
            logger.error(f"Error printing final stats: {e}")
    
    def _perform_maintenance(self):
        """Perform periodic maintenance tasks"""
        try:
            # Run maintenance every 5 minutes
            if int(time.time()) % 300 == 0:
                logger.debug("Running maintenance tasks...")
                
                # Clean up old SMS (optional)
                # db.cleanup_old_sms(30)
                
                # Check for failed extractions and potentially retry
                # (You can implement this based on your needs)
                
        except Exception as e:
            logger.error(f"Error in maintenance: {e}")
    
    def get_system_status(self) -> Dict:
        """Get current system status"""
        try:
            return {
                'running': self.running,
                'stats': self.stats.copy(),
                'modems': modem_detector.get_known_modems(),
                'extractions': sim_manager.get_all_extraction_status(),
                'database': db.get_system_stats()
            }
        except Exception as e:
            logger.error(f"Error getting system status: {e}")
            return {}

def main():
    """Main entry point"""
    try:
        # Create and start system
        system = SimPulseSystem()
        system.start()
        
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    except Exception as e:
        logger.error(f"System error: {e}")
    finally:
        logger.info("System terminated")

if __name__ == "__main__":
    main()
