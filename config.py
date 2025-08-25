# config.py
import os
import logging
from pathlib import Path
import RPi.GPIO as GPIO

# ==============================
#           LOGGING
# ==============================
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s')

# ==============================
#           CONFIG
# ==============================

# Window - Updated for 1280x1024 resolution
WINDOW_W, WINDOW_H = 1280, 1024

# Admin Mode
ADMIN_BG_PATH = Path.home() / "SelfCheck" / "SysPics" / "Admin.png"
CRED_DIR = Path.home() / "SelfCheck" / "Cred"
GS_CRED_TAB = "Credentials"  # Tab name for admin credentials
GS_LOGIN_TAB = "Login"       # Tab name for login credentials
ADMIN_TIMEOUT_MS = 90_000    # 90 seconds inactivity timeout

# Idle mode
IDLE_DIR = Path.home() / "SelfCheck" / "IdlePics"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"}
SLIDE_MS = 20_000  # 20s

# Weather update interval
WEATHER_UPDATE_INTERVAL = 30 * 60  # 30 minutes in seconds

# GPIO Configuration
GPIO.setmode(GPIO.BCM)

# Button pins
PIN_RED    = 5   # Exit PriceCheck -> Idle
PIN_GREEN  = 6   # Enter PriceCheck / Reset scan
PIN_YELLOW = 12  # Available
PIN_BLUE   = 13  # Available
PIN_CLEAR  = 16  # Enter Admin mode

# Setup with pull-up resistors
GPIO.setup(PIN_RED,    GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(PIN_GREEN,  GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(PIN_YELLOW, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(PIN_BLUE,   GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(PIN_CLEAR,  GPIO.IN, pull_up_down=GPIO.PUD_UP)

# PriceCheck assets & layout
SYSPICS_DIR   = Path.home() / "SelfCheck" / "SysPics"
PRICE_BG_PATH = SYSPICS_DIR / "PriceCheck.png"

# Google Drive folder ID for product images
GDRIVE_FOLDER_ID = "1lbYM1WBgqvPwiRwvluJnVyKRawQgl5LU"

GS_CRED_PATH  = Path.home() / "SelfCheck" / "Cred" / "credentials.json"
GS_SHEET_NAME = "Inventory1001"
GS_TAB        = "Inv"

# Updated layout boxes for 1280x1024 resolution
# Scaled up from original 800x480 resolution
PC_BLUE_BOX  = (32, 357, 704, 777)     # Scaled from (20, 170, 440, 370)
PC_GREEN_BOX = (736, 462, 1248, 882)   # Scaled from (460, 220, 780, 420)

# Inactivity timeout
PRICECHECK_TIMEOUT_MS = 30_000  # 30s
