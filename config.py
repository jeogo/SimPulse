"""
SimPulse Modem System Configuration
Event-driven modem-SIM management system settings
"""

import os
import logging

# ============================================================================
# PORT DETECTION SETTINGS
# ============================================================================
MAX_COM_PORTS = 999
AT_TIMEOUT = 5
CONNECTION_TIMEOUT = 3
BAUD_RATE = 9600

# Port detection parameters
PORT_SCAN_DELAY = 0.1  # Delay between port checks
MAX_DETECTION_ATTEMPTS = 3

# ============================================================================
# AT COMMANDS
# ============================================================================

# Basic AT commands
AT_BASIC = "AT"
AT_IMEI = "AT+CGSN"
AT_SIM_STATUS = "AT+CPIN?"
AT_SIGNAL = "AT+CSQ"

# SIM info extraction commands (ONE TIME ONLY)
BALANCE_COMMAND = '*222#'
NUMBER_COMMAND = '*101#'

# ============================================================================
# DATABASE SETTINGS
# ============================================================================
DB_PATH = os.path.join(os.path.dirname(__file__), "modem_system.db")
DB_TIMEOUT = 30.0

# ============================================================================
# LOGGING SETTINGS
# ============================================================================
LOG_LEVEL = logging.INFO
LOG_FORMAT = "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
LOG_FILE = os.path.join(os.path.dirname(__file__), "modem_system.log")

# Console output settings
CONSOLE_TIMESTAMPS = True
CONSOLE_COLORS = True

# ============================================================================
# MODEM DETECTION SETTINGS
# ============================================================================

# Diagnostic port identifiers (to be filtered out)
DIAGNOSTIC_PORT_KEYWORDS = [
    "Diagnostic",
    "DIAG",
    "AT Command",
    "PC UI Interface",
    "Application Interface",
    "GPS",
    "AUX"
]

# Valid modem port identifiers
VALID_MODEM_KEYWORDS = [
    "Modem",
    "COM",
    "Serial",
    "AT Interface",
    "Data Interface"
]

# ============================================================================
# RESPONSE DECODING SETTINGS
# ============================================================================

# Encoding preferences (in order of preference)
ENCODING_PREFERENCES = [
    "utf-8",
    "utf-16",
    "latin-1",
    "ascii",
    "cp1252"
]

# HEX decoding settings
HEX_DECODE_ENABLED = True
AUTO_DETECT_ENCODING = True

# ============================================================================
# SYSTEM BEHAVIOR SETTINGS
# ============================================================================

# Event-driven behavior
STARTUP_FULL_SCAN = True
DEVICE_EVENT_MONITORING = False  # Disable continuous monitoring - ONE TIME ONLY
AUTO_RESTART_ON_ERROR = True

# Performance settings
MAX_CONCURRENT_MODEMS = 50
THREAD_POOL_SIZE = 10
MEMORY_LIMIT_MB = 30

# ============================================================================
# ERROR HANDLING
# ============================================================================
MAX_ERROR_RETRIES = 5
ERROR_RETRY_DELAY = 2.0
GRACEFUL_SHUTDOWN_TIMEOUT = 10.0

# ============================================================================
# DEVELOPMENT SETTINGS
# ============================================================================
DEBUG_MODE = False
VERBOSE_LOGGING = False
SIMULATION_MODE = False  # For testing without real modems
