#!/usr/bin/env python3
# SelfCheck.py
# Idle slideshow on HDMI + PriceCheck mode
# Target display: 1280x1024 (square format)
# Testing 
# Price Checker is Good
# Admin Login Screen Good / Secret button Top Left Passwords good
# Starting to test cart functions
# Manual Entry Added and working with image pull up
# Setting up Pay Now options
# 8/24/25

import os
import random
import threading
import time
import subprocess
import logging
from pathlib import Path
from datetime import datetime
import io
import json
import shutil
import requests
import csv
import uuid

import tkinter as tk
from tkinter import messagebox
from PIL import Image, ImageTk, ImageFont, ImageDraw

import RPi.GPIO as GPIO

# Google Sheets & Drive
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload


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


# ==============================
#        FONT HELPERS
# ==============================

def load_ttf(size):
    for p in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    ):
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()

# Updated font sizes for 1280x1024 resolution
PC_FONT_TITLE = load_ttf(56)   # was 40
PC_FONT_SUB   = load_ttf(34)   # was 24
PC_FONT_INFO  = load_ttf(25)   # was 18
PC_FONT_LINE  = load_ttf(39)   # was 28
PC_FONT_SMALL = load_ttf(22)   # was 16


# ==============================
#        GENERIC HELPERS
# ==============================

def run(cmd):
    try:
        out = subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL, timeout=1.5)
        return out.decode("utf-8", "ignore").strip()
    except Exception:
        return ""

def get_wifi_rssi_dbm():
    txt = run("iw dev wlan0 link")
    for line in txt.splitlines():
        if "signal:" in line.lower():
            try:
                return int(float(line.split("signal:")[1].split("dBm")[0].strip()))
            except Exception:
                return None
    return None

def rssi_to_bars(rssi):
    if rssi is None: return 0
    if rssi >= -55: return 4
    if rssi >= -65: return 3
    if rssi >= -75: return 2
    if rssi >= -85: return 1
    return 0


# ==============================
#           IDLE MODE
# ==============================

class IdleMode:
    """Fullscreen slideshow with weather, time, and hidden admin button."""
    def __init__(self, root: tk.Tk):
        self.root = root
        # Main image display
        self.label = tk.Label(root, bg="black")
        
        # Create overlay labels - but don't place them yet
        # Bottom text
        self.bottom_text = tk.Label(root, text="Tap Anywhere to Start", 
                                   font=("Arial", 36, "bold"), fg="white", bg="black")
        
        # Top time display
        self.time_label = tk.Label(root, text="", font=("Arial", 24), fg="white", bg="black")
        
        # Weather display
        self.weather_label = tk.Label(root, text="", font=("Arial", 24), fg="white", bg="black")
        
        # Hidden admin button (invisible but clickable)
        self.admin_button = tk.Label(root, text="", bg="black")
        
        # Selection screen elements
        self.selection_active = False
        self.selection_label = tk.Label(root, bg="black")
        self.cart_button = tk.Label(root, bg="black")
        self.pc_button = tk.Label(root, bg="black")
        self.selection_timeout = None
        
        # Load button images
        self.cart_img = None
        self.pc_img = None
        self._load_button_images()
        
        # Add touch support to all elements
        self.label.bind("<Button-1>", self._on_touch)
        self.bottom_text.bind("<Button-1>", self._on_touch)
        self.time_label.bind("<Button-1>", self._on_touch)
        self.weather_label.bind("<Button-1>", self._on_touch)
        self.admin_button.bind("<Button-1>", self._on_admin_button_click)
        
        # Selection screen bindings
        self.selection_label.bind("<Button-1>", self._on_selection_background_click)
        self.cart_button.bind("<Button-1>", self._on_cart_button_click)
        self.pc_button.bind("<Button-1>", self._on_pc_button_click)
        
        self.tk_img = None
        self.slide_after = None
        self.overlay_timer = None
        self.order = []
        self.idx = 0
        self.is_active = False
        
        # Weather data
        self.weather_data = None
        self.weather_last_update = 0
        self.zipcode = None
        self.weather_api_key = None

    def _load_button_images(self):
        """Load button images and resize them to 50%."""
        try:
            # Load cart button image
            cart_path = Path.home() / "SelfCheck" / "SysPics" / "CartButton.png"
            if cart_path.exists():
                with Image.open(cart_path) as img:
                    # Resize to 50% of original size
                    w, h = img.size
                    img = img.resize((w//2, h//2), Image.LANCZOS)
                    self.cart_img = ImageTk.PhotoImage(img)
            else:
                logging.error(f"Cart button image not found: {cart_path}")
                
            # Load price check button image
            pc_path = Path.home() / "SelfCheck" / "SysPics" / "PCButton.jpeg"
            if pc_path.exists():
                with Image.open(pc_path) as img:
                    # Resize to 50% of original size
                    w, h = img.size
                    img = img.resize((w//2, h//2), Image.LANCZOS)
                    self.pc_img = ImageTk.PhotoImage(img)
            else:
                logging.error(f"Price check button image not found: {pc_path}")
                
        except Exception as e:
            logging.error(f"Error loading button images: {e}")

    def _on_touch(self, event):
        # Touch handler for idle mode
        if not self.is_active:
            return
            
        x, y = event.x_root, event.y_root  # Use root coordinates
        logging.info(f"Touch in Idle mode at ({x}, {y})")
        
        # Show selection screen instead of directly going to PriceCheck
        self._show_selection_screen()

    def _on_admin_button_click(self, event):
        # Special handler for admin button
        if not self.is_active:
            return
            
        logging.info("Admin button clicked, entering Admin mode")
        if hasattr(self, "on_wifi_tap"):
            self.on_wifi_tap()
        return
        
    def _on_selection_background_click(self, event):
        # Clicking on the background does nothing
        pass
        
    def _on_cart_button_click(self, event):
        logging.info("Cart button clicked")
        self._hide_selection_screen()
        # Enter Cart mode
        if hasattr(self, "on_cart_action"):
            self.on_cart_action()
        
    def _on_pc_button_click(self, event):
        logging.info("Price Check button clicked")
        self._hide_selection_screen()
        # Enter PriceCheck mode
        if hasattr(self, "on_touch_action"):
            self.on_touch_action()

    def start(self):
        logging.info("IdleMode: Starting")
        self.is_active = True
        
        # Make sure all overlays are hidden first (in case they weren't properly cleaned up)
        self._hide_all_overlays()
        
        # Re-show label
        self.label.place(x=0, y=0, width=WINDOW_W, height=WINDOW_H)
        self.label.lift()
        
        # Load zipcode and API key from credentials
        self._load_weather_config()
        
        # Update weather data
        self._update_weather()
        
        self.order = self._load_images()
        logging.info("Idle: found %d image(s) in %s", len(self.order), IDLE_DIR)
        random.shuffle(self.order)
        self.idx = 0
        self._show_next()
        
        # Start overlay update timer
        self._update_overlays()

    def stop(self):
        logging.info("IdleMode: Stopping")
        self.is_active = False
        
        # Cancel timers
        if self.slide_after:
            self.root.after_cancel(self.slide_after)
            self.slide_after = None
            
        if self.overlay_timer:
            self.root.after_cancel(self.overlay_timer)
            self.overlay_timer = None
            
        if self.selection_timeout:
            self.root.after_cancel(self.selection_timeout)
            self.selection_timeout = None
        
        # Hide all overlays and main label
        self._hide_all_overlays()
        self._hide_selection_screen()
        
    def _hide_all_overlays(self):
        """Hide all overlay elements and main label"""
        # Explicitly hide all overlays to ensure they're removed
        for widget in [self.bottom_text, self.time_label, self.weather_label, self.admin_button]:
            widget.place_forget()
        
        self.label.place_forget()
        
    def _show_selection_screen(self):
        """Show selection screen with cart and price check buttons."""
        # Cancel slide show
        if self.slide_after:
            self.root.after_cancel(self.slide_after)
            self.slide_after = None
            
        # Hide overlays
        self.bottom_text.place_forget()
        self.time_label.place_forget()
        self.weather_label.place_forget()
        self.admin_button.place_forget()
        
        # Load default background
        default_bg_path = Path.home() / "SelfCheck" / "SysPics" / "Default.png"
        if default_bg_path.exists():
            try:
                with Image.open(default_bg_path) as img:
                    if img.mode in ("RGBA", "P"):
                        img = img.convert("RGB")
                    bg = self._letterbox(img)
                    self.tk_img = ImageTk.PhotoImage(bg)
                    self.selection_label.configure(image=self.tk_img)
            except Exception as e:
                logging.error(f"Error loading default background: {e}")
                # Fallback to black background
                self.selection_label.configure(bg="black")
        else:
            logging.error(f"Default background image not found: {default_bg_path}")
            self.selection_label.configure(bg="black")
            
        # Place selection screen elements
        self.selection_label.place(x=0, y=0, width=WINDOW_W, height=WINDOW_H)
        
        # Place buttons if images loaded successfully
        if self.cart_img:
            self.cart_button.configure(image=self.cart_img)
            # Position at middle height, left side
            cart_w = self.cart_img.width()
            cart_h = self.cart_img.height()
            self.cart_button.place(x=WINDOW_W//4 - cart_w//2, y=WINDOW_H//2 - cart_h//2)
            
        if self.pc_img:
            self.pc_button.configure(image=self.pc_img)
            # Position at middle height, right side
            pc_w = self.pc_img.width()
            pc_h = self.pc_img.height()
            self.pc_button.place(x=3*WINDOW_W//4 - pc_w//2, y=WINDOW_H//2 - pc_h//2)
            
        # Lift all elements
        self.selection_label.lift()
        self.cart_button.lift()
        self.pc_button.lift()
        
        self.selection_active = True
        
        # Set timeout to return to idle mode after 30 seconds
        self.selection_timeout = self.root.after(30000, self._hide_selection_screen)
        
    def _hide_selection_screen(self):
        """Hide selection screen and return to idle slideshow."""
        if self.selection_timeout:
            self.root.after_cancel(self.selection_timeout)
            self.selection_timeout = None
            
        self.selection_label.place_forget()
        self.cart_button.place_forget()
        self.pc_button.place_forget()
        
        self.selection_active = False
        
        # Only restart slideshow if still in idle mode
        if self.is_active:
            self._show_next()
            self._update_overlays()

    def _load_weather_config(self):
        """Load zipcode and API key from Google Sheet."""
        try:
            scopes = [
                "https://www.googleapis.com/auth/spreadsheets.readonly",
                "https://www.googleapis.com/auth/drive.readonly",
                "https://www.googleapis.com/auth/spreadsheets",
            ]
            creds = Credentials.from_service_account_file(str(GS_CRED_PATH), scopes=scopes)
            gc = gspread.authorize(creds)
            sheet = gc.open(GS_SHEET_NAME).worksheet(GS_CRED_TAB)
            self.zipcode = sheet.acell('B24').value
            self.weather_api_key = sheet.acell('B25').value
            logging.info(f"Loaded zipcode: {self.zipcode}, API key available: {bool(self.weather_api_key)}")
        except Exception as e:
            logging.error(f"Failed to load weather config: {e}")
            self.zipcode = None
            self.weather_api_key = None

    def _update_weather(self):
        """Update weather data if needed."""
        current_time = time.time()
        
        # Only update if we have a zipcode, API key and it's time to update
        if (not self.zipcode or not self.weather_api_key or 
            (current_time - self.weather_last_update) < WEATHER_UPDATE_INTERVAL):
            return
            
        try:
            url = f"https://api.openweathermap.org/data/2.5/weather?zip={self.zipcode},us&units=imperial&appid={self.weather_api_key}"
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                self.weather_data = response.json()
                self.weather_last_update = current_time
                logging.info(f"Updated weather data for {self.weather_data.get('name', 'Unknown')}")
            else:
                logging.error(f"Weather API error: {response.status_code}")
        except Exception as e:
            logging.error(f"Failed to update weather: {e}")

    def _load_images(self):
        IDLE_DIR.mkdir(parents=True, exist_ok=True)
        return [p for p in sorted(IDLE_DIR.iterdir())
                if p.is_file() and p.suffix.lower() in IMAGE_EXTS]

    def _letterbox(self, im: Image.Image):
        """Force letterboxing by scaling to 90% of screen height"""
        # Force some letterboxing by scaling to 90% of screen height
        target_height = int(WINDOW_H * 0.9)
        
        # Calculate width to maintain aspect ratio
        aspect_ratio = im.width / im.height
        target_width = int(target_height * aspect_ratio)
        
        # Ensure width doesn't exceed screen width
        if target_width > WINDOW_W:
            target_width = int(WINDOW_W * 0.9)
            target_height = int(target_width / aspect_ratio)
        
        # Resize image
        resized = im.resize((target_width, target_height), Image.LANCZOS)
        
        # Create black background
        bg = Image.new("RGB", (WINDOW_W, WINDOW_H), (0, 0, 0))
        
        # Paste resized image in center
        x_offset = (WINDOW_W - target_width) // 2
        y_offset = (WINDOW_H - target_height) // 2
        bg.paste(resized, (x_offset, y_offset))
        
        logging.info(f"Forced letterboxing - Image: {target_width}x{target_height}, " +
                    f"Letterbox top/bottom: {y_offset}px, left/right: {x_offset}px")
        
        return bg

    def _show_next(self):
        if not self.is_active:
            return
            
        if not self.order:
            frame = Image.new("RGB", (WINDOW_W, WINDOW_H), (0, 0, 0))
            d = ImageDraw.Draw(frame)
            msg = f"No images in {IDLE_DIR}"
            w, h = d.textbbox((0,0), msg, font=load_ttf(24))[2:]
            d.text(((WINDOW_W - w)//2, (WINDOW_H - h)//2), msg, font=load_ttf(24), fill=(255,255,255))
        else:
            path = self.order[self.idx]
            logging.info("Idle: showing %s", path.name)
            self.idx = (self.idx + 1) % len(self.order)
            try:
                with Image.open(path) as im:
                    if im.mode in ("RGBA", "P"):
                        im = im.convert("RGB")
                    frame = self._letterbox(im)
            except Exception as e:
                logging.error("Idle: failed to load %s: %s", path, e)
                frame = Image.new("RGB", (WINDOW_W, WINDOW_H), (0, 0, 0))

        if self.is_active:  # Check again in case mode changed during image loading
            self.tk_img = ImageTk.PhotoImage(frame)
            self.label.configure(image=self.tk_img)
            self.label.lift()
            
            # Schedule next slide
            self.slide_after = self.root.after(SLIDE_MS, self._show_next)

    def _update_overlays(self):
        """Update text overlays"""
        if not self.is_active:
            return
            
        # Position bottom text
        self.bottom_text.place(x=WINDOW_W//2, y=WINDOW_H-50, anchor="center")
        
        # Update and position time
        current_time = datetime.now().strftime("%I:%M %p")
        self.time_label.config(text=current_time)
        self.time_label.place(x=WINDOW_W-100, y=30, anchor="center")
        
        # Update and position weather
        if self.weather_data:
            try:
                temp = self.weather_data.get('main', {}).get('temp', 'N/A')
                city = self.weather_data.get('name', 'Unknown')
                weather_text = f"{city} {int(temp)}°F"
                self.weather_label.config(text=weather_text)
                self.weather_label.place(x=WINDOW_W//2, y=30, anchor="center")
            except Exception as e:
                logging.error(f"Error displaying weather: {e}")
        
        # Position hidden admin button in top-left corner
        # Reduced to 25% of original size (from 100x100 to 25x25)
        self.admin_button.place(x=0, y=0, width=25, height=25)
        
        # Ensure overlays stay on top
        self._lift_overlays()
        
        # Schedule next update only if still active
        if self.is_active:
            self.overlay_timer = self.root.after(1000, self._update_overlays)
        
    def _lift_overlays(self):
        """Ensure all overlay elements stay on top"""
        # Only lift elements that have been placed
        if self.is_active:  # Only lift if mode is active
            if self.bottom_text.winfo_ismapped():
                self.bottom_text.lift()
            if self.time_label.winfo_ismapped():
                self.time_label.lift()
            if self.weather_label.winfo_ismapped():
                self.weather_label.lift()
            if self.admin_button.winfo_ismapped():
                self.admin_button.lift()



# ==============================
#     UPC NORMALIZATION HELPERS
# ==============================

def _digits_only(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())

def upc_variants_from_sheet(value: str):
    """
    Generate all reasonable variants for a UPC stored in the sheet.
    Handles cells that lost leading zero or were formatted as numbers.
    Returns a list of unique strings.
    """
    variants = []
    raw = (value or "").strip()
    dig = _digits_only(raw)

    def add(v):
        if v and v not in variants:
            variants.append(v)

    # raw and digits-only
    add(raw)
    add(dig)

    # If the sheet lost a leading zero on a 12-digit UPC (now 11 digits)
    if len(dig) == 11:
        add("0" + dig)             # 12-digit with restored leading zero
    # If the sheet stored 12-digit UPC properly, also add 13-digit EAN with leading 0
    if len(dig) == 12:
        add("0" + dig)             # EAN-13 variant
        add(dig.lstrip("0"))       # also without leading zeros (defensive)
    # If sheet stored EAN-13 that starts with 0, add 12-digit UPC-A
    if len(dig) == 13 and dig.startswith("0"):
        add(dig[1:])
    # If GTIN-14 with leading zeros, add trimmed versions down to 12
    if len(dig) == 14:
        t = dig.lstrip("0")
        add(t)
        if len(t) == 13 and t.startswith("0"):
            add(t[1:])
        if len(t) == 12 and (not t.startswith("0")):
            add("0" + t)  # also add an EAN-13 with leading zero

    return variants

def upc_variants_from_scan(scan: str):
    """
    Generate variants for an incoming scan.
    Most scanners give 12-digit UPC-A or 13-digit EAN-13.
    """
    variants = []
    raw = (scan or "").strip()
    dig = _digits_only(raw)

    def add(v):
        if v and v not in variants:
            variants.append(v)

    add(raw)
    add(dig)

    # If 13 and starts with 0, also try 12
    if len(dig) == 13 and dig.startswith("0"):
        add(dig[1:])
    # If 12 and starts with 0, try without that zero (for sheets that lost it)
    if len(dig) == 12 and dig.startswith("0"):
        add(dig[1:])
    # If 11 (sheet lost zero scenario), try adding a leading zero
    if len(dig) == 11:
        add("0" + dig)
    # If 14, trim leading zeros down to 13/12
    if len(dig) == 14:
        t = dig.lstrip("0")
        add(t)
        if len(t) == 13 and t.startswith("0"):
            add(t[1:])

    return variants


# ==============================
#   GOOGLE DRIVE IMAGE LOADER
# ==============================

class GoogleDriveImageLoader:
    """Handles loading images from Google Drive folder with caching."""

    def __init__(self, credentials_path, folder_id):
        self.folder_id = folder_id
        self.cache_dir = Path.home() / "SelfCheck" / "ImageCache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.file_map = {}  # filename -> file_id mapping
        self.drive_service = None
        self._init_drive_service(credentials_path)

    def _init_drive_service(self, credentials_path):
        """Initialize Google Drive API service."""
        try:
            scopes = [
                "https://www.googleapis.com/auth/drive.readonly",
            ]
            creds = Credentials.from_service_account_file(str(credentials_path), scopes=scopes)
            self.drive_service = build('drive', 'v3', credentials=creds)
            self._build_file_map()
            logging.info("Google Drive service initialized successfully")
        except Exception as e:
            logging.error("Failed to initialize Google Drive service: %s", e)
            self.drive_service = None

    def _build_file_map(self):
        """Build a mapping of filename to file_id for the specified folder."""
        if not self.drive_service:
            return

        try:
            query = f"'{self.folder_id}' in parents and trashed=false"
            results = self.drive_service.files().list(
                q=query,
                fields="files(id, name)"
            ).execute()

            files = results.get('files', [])
            self.file_map = {file['name']: file['id'] for file in files}
            logging.info("Found %d files in Google Drive folder", len(self.file_map))

        except Exception as e:
            logging.error("Failed to build file map from Google Drive: %s", e)

    def get_image(self, filename):
        """
        Get image from Google Drive, with local caching.
        Returns PIL Image object or None if not found.
        """
        if not filename or not self.drive_service:
            return None

        # Check local cache first
        cache_path = self.cache_dir / filename
        if cache_path.exists():
            try:
                return Image.open(cache_path)
            except Exception as e:
                logging.warning("Failed to load cached image %s: %s", filename, e)
                # Remove corrupted cache file
                try:
                    cache_path.unlink()
                except:
                    pass

        # Download from Google Drive
        file_id = self.file_map.get(filename)
        if not file_id:
            logging.warning("File not found in Google Drive: %s", filename)
            return None

        try:
            # Download file content
            request = self.drive_service.files().get_media(fileId=file_id)
            file_content = io.BytesIO()

            import googleapiclient.http
            downloader = googleapiclient.http.MediaIoBaseDownload(file_content, request)
            done = False
            while done is False:
                status, done = downloader.next_chunk()

            # Save to cache
            file_content.seek(0)
            with open(cache_path, 'wb') as f:
                f.write(file_content.read())

            # Load as PIL Image
            file_content.seek(0)
            image = Image.open(file_content)
            logging.info("Downloaded and cached image: %s", filename)
            return image

        except Exception as e:
            logging.error("Failed to download image %s from Google Drive: %s", filename, e)
            return None


# ==============================
#   GOOGLE SHEETS LOADER (UPC)
# ==============================

def load_inventory_by_upc():
    """Build a dict of *many* UPC variants -> the same row list."""
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    creds = Credentials.from_service_account_file(str(GS_CRED_PATH), scopes=scopes)
    gc = gspread.authorize(creds)
    logging.info("Connecting to Google Sheet: %s / Tab: %s", GS_SHEET_NAME, GS_TAB)

    try:
        ws = gc.open(GS_SHEET_NAME).worksheet(GS_TAB)
        rows = ws.get_all_values()
    except Exception as e:
        logging.error("PriceCheck: sheet open/read error: %s", e)
        return {}

    logging.info("PriceCheck: loaded %d rows from sheet", len(rows))
    if not rows:
        return {}

    header = rows[0]
    logging.info("PriceCheck: header row: %s", header)

    index = {}
    collisions = 0
    for r in rows[1:]:
        if not r:
            continue
        raw_upc = (r[0] if len(r) > 0 else "").strip()
        if not raw_upc:
            continue
        for v in upc_variants_from_sheet(raw_upc):
            if v in index and index[v] is not r:
                collisions += 1
            index[v] = r

    logging.info("PriceCheck: indexed %d UPC keys (including variants), collisions=%d",
                 len(index), collisions)
    for i, k in enumerate(list(index.keys())[:5]):
        logging.info("PriceCheck: sample key %d: %r", i+1, k)
    return index


# ==============================
#        PRICECHECK MODE
# ==============================

class PriceCheckMode:
    """
    Background = PriceCheck.png.
    Waits for barcode scans (USB keyboard wedge).
    Looks up UPC in Google Sheet 'Inventory1001'/'Inv'.
    Overlays text in the blue box and product image (from Column L) in the green box.
    """
    # Column indices (0-based) for A..L:
    IDX_B = 1
    IDX_C = 2
    IDX_E = 4
    IDX_F = 5
    IDX_G = 6
    IDX_H = 7
    IDX_I = 8
    IDX_K = 10
    IDX_L = 11

    def __init__(self, root: tk.Tk):
        self.root = root
        self.label = tk.Label(root, bg="black")
        self.label.place(x=0, y=0, width=WINDOW_W, height=WINDOW_H)

        self.tk_img = None
        self.base_bg = None
        self.inv = {}
        self.last_activity_ts = time.time()
        self.timeout_after = None

        # Initialize Google Drive image loader
        self.image_loader = GoogleDriveImageLoader(GS_CRED_PATH, GDRIVE_FOLDER_ID)

        # Hidden entry to capture scanner input - create once and reuse
        self.scan_var = tk.StringVar()
        self.scan_entry = tk.Entry(root, textvariable=self.scan_var)
        # Keep it hidden initially
        self.scan_entry.place(x=-1000, y=-1000, width=10, height=10)

        # Bind events once during initialization
        self.scan_entry.bind("<Return>", self._on_scan_submit)
        self.scan_entry.bind("<KP_Enter>", self._on_scan_submit)

        # Add debugging - monitor when text changes
        self.scan_var.trace_add("write", self._on_scan_var_change)

        # Add touch support
        self.label.bind("<Button-1>", self._on_touch)

    def _on_touch(self, event):
        # Touch handler for PriceCheck mode
        x, y = event.x, event.y
        logging.info(f"Touch in PriceCheck mode at ({x}, {y})")

        # Example: Define a touch area for resetting scan
        reset_area = (WINDOW_W//2 - 150, WINDOW_H - 100, WINDOW_W//2 + 150, WINDOW_H - 20)
        if (reset_area[0] <= x <= reset_area[2] and
            reset_area[1] <= y <= reset_area[3]):
            self._reset_for_next_scan()

    def _on_scan_var_change(self, *args):
        """Debug callback to see when scanner input is received"""
        current_value = self.scan_var.get()
        if current_value:
            logging.info("Scanner input detected: %r", current_value)

    def start(self):
        logging.info("PriceCheck: Starting mode")
        # Make visible when entering PriceCheck
        self.label.place(x=0, y=0, width=WINDOW_W, height=WINDOW_H)
        self.label.lift()

        self.base_bg = self._load_bg()
        self._render_base()
        try:
            # Only reload inventory if we don't have it already
            if not self.inv:
                self.inv = load_inventory_by_upc()
        except Exception as e:
            self.inv = {}
            self._overlay_notice(f"Sheet error:\n{e}")

        self._reset_for_next_scan()
        self._arm_timeout()

    def stop(self):
        logging.info("PriceCheck: Stopping mode")
        if self.timeout_after:
            self.root.after_cancel(self.timeout_after)
            self.timeout_after = None
        # Hide when leaving PriceCheck
        self.label.place_forget()
        # Don't unbind events - keep them bound for reuse
        # Just move entry further off-screen
        self.scan_entry.place(x=-2000, y=-2000, width=1, height=1)

    # ---- UI helpers ----
    def _load_bg(self):
        if PRICE_BG_PATH.exists():
            try:
                with Image.open(PRICE_BG_PATH) as im:
                    if im.mode in ("RGBA", "P"):
                        im = im.convert("RGB")
                    return self._letterbox(im)
            except Exception:
                pass
        # fallback white
        return Image.new("RGB", (WINDOW_W, WINDOW_H), (255, 255, 255))

    def _letterbox(self, im: Image.Image):
        iw, ih = im.size
        scale = min(WINDOW_W/iw, WINDOW_H/ih)
        nw, nh = int(iw*scale), int(ih*scale)
        resized = im.resize((nw, nh), Image.LANCZOS)
        bg = Image.new("RGB", (WINDOW_W, WINDOW_H), (255,255,255))
        bg.paste(resized, ((WINDOW_W-nw)//2, (WINDOW_H-nh)//2))
        return bg

    def _render_base(self):
        self.tk_img = ImageTk.PhotoImage(self.base_bg)
        self.label.configure(image=self.tk_img)
        self.label.lift()

    def _overlay_notice(self, msg):
        frame = self.base_bg.copy()
        d = ImageDraw.Draw(frame)
        x1,y1,x2,y2 = PC_BLUE_BOX
        # No border rectangle
        w,h = d.textbbox((0,0), msg, font=PC_FONT_SUB)[2:]
        d.text((x1 + (x2-x1-w)//2, y1 + (y2-y1-h)//2), msg, font=PC_FONT_SUB, fill=(0,0,0))

        # Add a touch-friendly "Reset" button at the bottom
        button_text = "Tap here to scan another item"
        bw, bh = d.textbbox((0,0), button_text, font=PC_FONT_SUB)[2:]
        button_x = WINDOW_W//2 - bw//2
        button_y = WINDOW_H - 80
        d.rectangle([button_x-20, button_y-10, button_x+bw+20, button_y+bh+10],
                   fill=(0,120,200), outline=(0,0,0), width=2)
        d.text((button_x, button_y), button_text, font=PC_FONT_SUB, fill=(255,255,255))

        self.tk_img = ImageTk.PhotoImage(frame)
        self.label.configure(image=self.tk_img)
        self.label.lift()

    def _overlay_result(self, row_list):
        frame = self.base_bg.copy()
        d = ImageDraw.Draw(frame)
        bx1,by1,bx2,by2 = PC_BLUE_BOX

        # Move green box up by about 1 inch (96 pixels at 96 DPI, using 72 pixels for safety)
        gx1,gy1,gx2,gy2 = PC_GREEN_BOX
        gy1 -= 72  # Move up by ~1 inch
        gy2 -= 72  # Move up by ~1 inch

        def col(idx):
            return (row_list[idx] if len(row_list) > idx else "").strip()

        # Texts from columns
        title = col(self.IDX_B)
        sub   = col(self.IDX_C)
        size  = col(self.IDX_E)
        cal   = col(self.IDX_F)
        sug   = col(self.IDX_G)
        sod   = col(self.IDX_H)
        lineI = col(self.IDX_I)
        onhand= col(self.IDX_K)
        picnm = col(self.IDX_L)

        # Blue area content (no border)
        d.text((bx1+12, by1+10), title, font=PC_FONT_TITLE, fill=(0,0,0))
        d.text((bx1+12, by1+10 + 50), sub, font=PC_FONT_SUB, fill=(0,0,0))
        d.text((bx1+12, by1+10 + 50 + 30),
               f"Size: {size}  Calories: {cal}  Sugar: {sug}  Sodium: {sod}",
               font=PC_FONT_INFO, fill=(0,0,0))
        d.text((bx1+12, by1+10 + 50 + 30 + 26),
               lineI, font=PC_FONT_LINE, fill=(0,0,0))
        d.text((bx1+12, by2 - 28),
               f"Amount on hand: {onhand}", font=PC_FONT_SMALL, fill=(0,0,0))

        # Product image into green box from Google Drive (moved up 1 inch)
        if picnm:
            try:
                pim = self.image_loader.get_image(picnm)
                if pim:
                    if pim.mode in ("RGBA","P"):
                        pim = pim.convert("RGB")
                    gw, gh = gx2-gx1, gy2-gy1
                    scale = min(gw/pim.width, gh/pim.height)
                    nw, nh = max(1,int(pim.width*scale)), max(1,int(pim.height*scale))
                    pim = pim.resize((nw, nh), Image.LANCZOS)
                    ox = gx1 + (gw - nw)//2
                    oy = gy1 + (gh - nh)//2
                    frame.paste(pim, (ox, oy))
                    logging.info("Displayed product image: %s", picnm)
                else:
                    logging.warning("Could not load product image: %s", picnm)
            except Exception as e:
                logging.error("Error loading product image %s: %s", picnm, e)

        # Add a touch-friendly "Reset" button at the bottom
        button_text = "Tap here to scan another item"
        bw, bh = d.textbbox((0,0), button_text, font=PC_FONT_SUB)[2:]
        button_x = WINDOW_W//2 - bw//2
        button_y = WINDOW_H - 80
        d.rectangle([button_x-20, button_y-10, button_x+bw+20, button_y+bh+10],
                   fill=(0,120,200), outline=(0,0,0), width=2)
        d.text((button_x, button_y), button_text, font=PC_FONT_SUB, fill=(255,255,255))

        self.tk_img = ImageTk.PhotoImage(frame)
        self.label.configure(image=self.tk_img)
        self.label.lift()

    # ---- Scanner handling ----
    def _on_scan_submit(self, _event=None):
        upc = self.scan_var.get().strip()
        logging.info("Scan submit called with: %r", upc)
        self.scan_var.set("")
        self.last_activity_ts = time.time()
        if not upc:
            self._overlay_notice("No scan")
            return

        tried = upc_variants_from_scan(upc)
        logging.info("Scan received: %r -> trying variants: %s", upc, tried)

        row = None
        for v in tried:
            row = self.inv.get(v)
            if row:
                logging.info("Match on variant: %r", v)
                break

        if not row:
            self._overlay_notice(f"Not found:\n{upc}")
            return

        self._overlay_result(row)

    def _reset_for_next_scan(self):
        logging.info("PriceCheck: Resetting for next scan")
        self.last_activity_ts = time.time()
        self.scan_var.set("")

        # Multiple attempts to ensure focus
        self.scan_entry.place(x=-1000, y=-1000, width=10, height=10)
        self.root.update_idletasks()

        # Try multiple focus methods
        self.scan_entry.focus_set()
        self.root.after(50, lambda: self.scan_entry.focus_force())
        self.root.after(100, lambda: self.scan_entry.focus_set())

        # Log current focus for debugging
        self.root.after(200, self._debug_focus)

        self._overlay_notice("Scan an item")

    def _debug_focus(self):
        focused = self.root.focus_get()
        logging.info("Current focus widget: %s", focused)
        logging.info("Scan entry widget: %s", self.scan_entry)
        logging.info("Focus matches scan entry: %s", focused == self.scan_entry)

    def _arm_timeout(self):
        """Set up inactivity timeout for admin mode."""
        if self.timeout_after:
            self.root.after_cancel(self.timeout_after)

        def check_timeout():
            current_time = time.time()
            elapsed = current_time - self.last_activity_ts
            logging.debug(f"Admin timeout check: {elapsed:.1f}s elapsed")

            if elapsed >= (ADMIN_TIMEOUT_MS/1000.0):
                logging.info(f"Admin mode timeout after {elapsed:.1f}s - returning to Idle")
                if hasattr(self, "on_timeout"):
                    self.on_timeout()
                return
            self.timeout_after = self.root.after(1000, check_timeout)

        self.timeout_after = self.root.after(1000, check_timeout)



# ==============================
#          Admin Login Screen
# ==============================

class AdminLoginScreen:
    """Login screen for Admin mode with virtual keyboard."""
    def __init__(self, root: tk.Tk):
        self.root = root
        self.frame = tk.Frame(root, bg="#2c3e50")
        self.frame.place(x=0, y=0, width=WINDOW_W, height=WINDOW_H)

        # Login variables
        self.username_var = tk.StringVar()
        self.password_var = tk.StringVar()
        self.current_field = None
        self.login_in_progress = False

        # Create login UI
        self._create_login_ui()

    def _create_login_ui(self):
        # Title
        title_label = tk.Label(self.frame, text="Admin Login",
                              font=("Arial", 36, "bold"), bg="#2c3e50", fg="white")
        title_label.pack(pady=(100, 50))

        # Login form
        form_frame = tk.Frame(self.frame, bg="#2c3e50")
        form_frame.pack(pady=20)

        # Username
        username_label = tk.Label(form_frame, text="Username:",
                                 font=("Arial", 18), bg="#2c3e50", fg="white")
        username_label.grid(row=0, column=0, sticky="w", padx=10, pady=10)

        self.username_entry = tk.Entry(form_frame, textvariable=self.username_var,
                                     font=("Arial", 18), width=20)
        self.username_entry.grid(row=0, column=1, padx=10, pady=10)

        # Password
        password_label = tk.Label(form_frame, text="Password:",
                                 font=("Arial", 18), bg="#2c3e50", fg="white")
        password_label.grid(row=1, column=0, sticky="w", padx=10, pady=10)

        self.password_entry = tk.Entry(form_frame, textvariable=self.password_var,
                                     font=("Arial", 18), width=20, show="•")
        self.password_entry.grid(row=1, column=1, padx=10, pady=10)

        # Login button
        self.login_button = tk.Button(form_frame, text="Login", font=("Arial", 18),
                                    bg="#3498db", fg="white", width=10,
                                    command=self._login)
        self.login_button.grid(row=2, column=0, columnspan=2, pady=30)

        # Cancel button
        self.cancel_button = tk.Button(form_frame, text="Cancel", font=("Arial", 18),
                                     bg="#e74c3c", fg="white", width=10,
                                     command=self._cancel)
        self.cancel_button.grid(row=3, column=0, columnspan=2, pady=10)

        # Status message
        self.status_label = tk.Label(form_frame, text="", font=("Arial", 14),
                                   bg="#2c3e50", fg="#e74c3c")
        self.status_label.grid(row=4, column=0, columnspan=2, pady=10)

        # Create virtual keyboard
        self._create_keyboard()

        # Set focus to username field and bind click events
        self.username_entry.focus_set()
        self.current_field = self.username_entry

        self.username_entry.bind("<Button-1>", lambda e: self._set_current_field(self.username_entry))
        self.password_entry.bind("<Button-1>", lambda e: self._set_current_field(self.password_entry))

    def _create_keyboard(self):
        keyboard_frame = tk.Frame(self.frame, bg="#34495e")
        keyboard_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=20)

        # Track shift state
        self.shift_on = False

        # Define keyboard layouts
        self.keys_lower = [
            ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0'],
            ['q', 'w', 'e', 'r', 't', 'y', 'u', 'i', 'o', 'p'],
            ['a', 's', 'd', 'f', 'g', 'h', 'j', 'k', 'l'],
            ['z', 'x', 'c', 'v', 'b', 'n', 'm', '.', '@']
        ]

        self.keys_upper = [
            ['!', '@', '#', '$', '%', '^', '&', '*', '(', ')'],
            ['Q', 'W', 'E', 'R', 'T', 'Y', 'U', 'I', 'O', 'P'],
            ['A', 'S', 'D', 'F', 'G', 'H', 'J', 'K', 'L'],
            ['Z', 'X', 'C', 'V', 'B', 'N', 'M', ',', '_']
        ]

        # Create keyboard rows frames
        self.key_buttons = []
        self.row_frames = []

        for i in range(4):
            row_frame = tk.Frame(keyboard_frame, bg="#34495e")
            row_frame.pack(pady=5)
            self.row_frames.append(row_frame)
            self.key_buttons.append([])

        # Populate with initial lowercase keys
        self._update_keyboard_layout()

        # Special keys row
        special_frame = tk.Frame(keyboard_frame, bg="#34495e")
        special_frame.pack(pady=5)

        # Shift key
        self.shift_button = tk.Button(special_frame, text="Shift", font=("Arial", 18),
                                   width=6, height=1, bg="#9b59b6", fg="white",
                                   command=self._toggle_shift)
        self.shift_button.pack(side=tk.LEFT, padx=3)

        # Space
        space_button = tk.Button(special_frame, text="Space", font=("Arial", 18),
                               width=14, height=1, bg="#7f8c8d", fg="white",
                               command=lambda: self._key_press(" "))
        space_button.pack(side=tk.LEFT, padx=3)

        # Symbols
        symbols_button = tk.Button(special_frame, text="123", font=("Arial", 18),
                                 width=4, height=1, bg="#3498db", fg="white",
                                 command=self._show_symbols)
        symbols_button.pack(side=tk.LEFT, padx=3)

        # Backspace
        backspace_button = tk.Button(special_frame, text="←", font=("Arial", 18),
                                   width=4, height=1, bg="#e67e22", fg="white",
                                   command=self._backspace)
        backspace_button.pack(side=tk.LEFT, padx=3)

        # Clear
        clear_button = tk.Button(special_frame, text="Clear", font=("Arial", 18),
                               width=5, height=1, bg="#e74c3c", fg="white",
                               command=self._clear_field)
        clear_button.pack(side=tk.LEFT, padx=3)

    def _update_keyboard_layout(self):
        """Update keyboard buttons based on shift state"""
        keys = self.keys_upper if self.shift_on else self.keys_lower

        # Clear existing buttons
        for row in self.key_buttons:
            for btn in row:
                btn.destroy()
            row.clear()

        # Create new buttons
        for row_idx, row_keys in enumerate(keys):
            for key in row_keys:
                key_button = tk.Button(self.row_frames[row_idx], text=key, font=("Arial", 18),
                                     width=3, height=1, bg="#7f8c8d", fg="white",
                                     command=lambda k=key: self._key_press(k))
                key_button.pack(side=tk.LEFT, padx=3)
                self.key_buttons[row_idx].append(key_button)

    def _toggle_shift(self):
        """Toggle between uppercase and lowercase keyboard"""
        self.shift_on = not self.shift_on
        self.shift_button.config(bg="#9b59b6" if self.shift_on else "#7f8c8d")
        self._update_keyboard_layout()

    def _show_symbols(self):
        """Show symbol keyboard (could be expanded with a full symbol set)"""
        # For now, we'll just toggle shift as a simple implementation
        self._toggle_shift()

    def _set_current_field(self, field):
        self.current_field = field
        field.focus_set()

    def _key_press(self, key):
        if self.current_field:
            current_text = self.current_field.get()
            self.current_field.delete(0, tk.END)
            self.current_field.insert(0, current_text + key)

    def _backspace(self):
        if self.current_field:
            current_text = self.current_field.get()
            if current_text:
                self.current_field.delete(0, tk.END)
                self.current_field.insert(0, current_text[:-1])

    def _clear_field(self):
        if self.current_field:
            self.current_field.delete(0, tk.END)

    def _login(self):
        if self.login_in_progress:
            return

        self.login_in_progress = True
        self.status_label.config(text="Verifying...")
        self.login_button.config(state=tk.DISABLED)

        username = self.username_var.get().strip()
        password = self.password_var.get().strip()

        if not username or not password:
            self.status_label.config(text="Please enter both username and password")
            self.login_button.config(state=tk.NORMAL)
            self.login_in_progress = False
            return

        # Schedule the actual login check to allow UI to update
        self.root.after(100, lambda: self._verify_credentials(username, password))

    def _verify_credentials(self, username, password):
        try:
            # Connect to Google Sheet with expanded scopes
            scopes = [
                "https://www.googleapis.com/auth/spreadsheets.readonly",
                "https://www.googleapis.com/auth/drive.readonly",
                "https://www.googleapis.com/auth/spreadsheets",
            ]
            creds = Credentials.from_service_account_file(str(GS_CRED_PATH), scopes=scopes)
            gc = gspread.authorize(creds)

            # Get login tab
            sheet = gc.open(GS_SHEET_NAME).worksheet(GS_LOGIN_TAB)

            # Get all usernames and passwords (skip header row)
            users = sheet.col_values(1)[1:]  # Column A (usernames)
            passes = sheet.col_values(2)[1:]  # Column B (passwords)

            # Check credentials
            for i, user in enumerate(users):
                if user == username and i < len(passes) and passes[i] == password:
                    logging.info(f"Successful login for user: {username}")
                    if hasattr(self, "on_login_success"):
                        self.on_login_success()
                    return

            # If we get here, login failed
            logging.warning(f"Failed login attempt for user: {username}")
            self.status_label.config(text="Access denied. Contact your system administrator.")
            self.login_button.config(state=tk.NORMAL)
            self.login_in_progress = False

            # Return to idle mode after delay
            self.root.after(3000, self._login_failed)

        except Exception as e:
            logging.error(f"Login verification error: {e}")
            self.status_label.config(text=f"Login error: {str(e)}")
            self.login_button.config(state=tk.NORMAL)
            self.login_in_progress = False

    def _login_failed(self):
        if hasattr(self, "on_login_failed"):
            self.on_login_failed()

    def _cancel(self):
        if hasattr(self, "on_cancel"):
            self.on_cancel()

    def show(self):
        self.frame.lift()
        self.username_entry.focus_set()
        self.current_field = self.username_entry

    def hide(self):
        self.frame.place_forget()



# ==============================
#          Admin Mode
# ==============================

class AdminMode:
    """
    Admin mode for updating credentials and settings.
    Displays Admin.png with text overlay for options.
    """
    def __init__(self, root: tk.Tk):
        self.root = root
        self.label = tk.Label(root, bg="black")
        
        self.tk_img = None
        self.base_bg = None
        self.update_in_progress = False
        self.last_activity_ts = time.time()
        self.timeout_after = None
        self.web_view = None
        
        # Create login screen
        self.login_screen = None  # Will be created in start()
        
        # Add touch support
        self.label.bind("<Button-1>", self._on_touch)
        self.label.bind("<Motion>", self._on_activity)

    def _on_touch(self, event):
        # Touch handler for Admin mode
        x, y = event.x, event.y
        logging.info(f"Touch in Admin mode at ({x}, {y})")
        self._on_activity()
        
        # Moved down by ~1 inch (96 pixels)
        # Check for button areas
        # Update credentials button
        if 80 <= x <= 780 and 296 <= y <= 366:
            self.update_credentials()
            
        # Update location files button
        elif 80 <= x <= 780 and 396 <= y <= 466:
            self.update_location_files()
            
        # WiFi settings button
        elif 80 <= x <= 780 and 496 <= y <= 566:
            self.open_wifi_settings()
            
        # Load inventory portal button
        elif 80 <= x <= 780 and 596 <= y <= 666:
            self.load_inventory_portal()
            
        # Exit button
        elif 80 <= x <= 380 and 696 <= y <= 766:
            if hasattr(self, "on_exit"):
                self.on_exit()
        
        # Back button (in status screens)
        elif 80 <= x <= 480 and 500 <= y <= 570:
            # Only active in status screens
            if self.update_in_progress == False and hasattr(self, "back_to_menu"):
                self._render_menu()
    
    def _on_activity(self, event=None):
        # Reset inactivity timer
        self.last_activity_ts = time.time()

    def start(self):
        logging.info("Admin: Starting mode")
        
        # Hide the main label first
        self.label.place_forget()
        
        # Create a new login screen each time
        if self.login_screen:
            self.login_screen.hide()  # Hide any existing login screen
        
        # Create fresh login screen
        self.login_screen = AdminLoginScreen(self.root)
        self.login_screen.on_login_success = self._on_login_success
        self.login_screen.on_login_failed = self._on_login_failed
        self.login_screen.on_cancel = self._on_login_cancel
        
        # Show login screen
        self.login_screen.show()

    def _on_login_success(self):
        # Hide login screen
        self.login_screen.hide()
        
        # Reset activity timestamp
        self.last_activity_ts = time.time()
        
        # Show admin interface
        self.label.place(x=0, y=0, width=WINDOW_W, height=WINDOW_H)
        self.label.lift()

        self.base_bg = self._load_bg()
        self._render_menu()
        
        # Start inactivity timer
        self._arm_timeout()

    def _on_login_failed(self):
        if hasattr(self, "on_exit"):
            self.on_exit()
            
    def _on_login_cancel(self):
        if hasattr(self, "on_exit"):
            self.on_exit()

    def stop(self):
        logging.info("Admin: Stopping mode")
        # Hide admin interface
        self.label.place_forget()
        
        # Hide login screen if it exists
        if self.login_screen:
            self.login_screen.hide()
        
        # Close web view if open
        if self.web_view:
            self.web_view.destroy()
            self.web_view = None
        
        # Cancel timeout timer
        if self.timeout_after:
            self.root.after_cancel(self.timeout_after)
            self.timeout_after = None

    def _load_bg(self):
        if ADMIN_BG_PATH.exists():
            try:
                with Image.open(ADMIN_BG_PATH) as im:
                    if im.mode in ("RGBA", "P"):
                        im = im.convert("RGB")
                    return self._letterbox(im)
            except Exception as e:
                logging.error("Admin: Failed to load background: %s", e)
        # fallback white
        return Image.new("RGB", (WINDOW_W, WINDOW_H), (255, 255, 255))

    def _letterbox(self, im: Image.Image):
        iw, ih = im.size
        scale = min(WINDOW_W/iw, WINDOW_H/ih)
        nw, nh = int(iw*scale), int(ih*scale)
        resized = im.resize((nw, nh), Image.LANCZOS)
        bg = Image.new("RGB", (WINDOW_W, WINDOW_H), (255,255,255))
        bg.paste(resized, ((WINDOW_W-nw)//2, (WINDOW_H-nh)//2))
        return bg

    def _render_menu(self):
        frame = self.base_bg.copy()
        d = ImageDraw.Draw(frame)
        
        # Menu options - with touch-friendly buttons
        option_font = load_ttf(40)  # Increased for 1280x1024
        
        # Moved down by ~1 inch (96 pixels)
        buttons = [
            {"text": "Update Credentials", "y": 300, "color": (0,120,200)},
            {"text": "Update Location Files", "y": 400, "color": (0,150,100)},
            {"text": "WiFi Settings", "y": 500, "color": (100,100,200)},
            {"text": "Load Inventory Portal", "y": 600, "color": (150,100,150)},
            {"text": "Exit Admin Mode", "y": 700, "color": (200,60,60)}
        ]
        
        for btn in buttons:
            button_x, button_y = 100, btn["y"]
            text_w, text_h = d.textbbox((0,0), btn["text"], font=option_font)[2:]
            
            # Draw button
            d.rectangle([button_x-20, button_y-10, button_x+text_w+40, button_y+text_h+10], 
                       fill=btn["color"], outline=(0,0,0), width=2)
            d.text((button_x, button_y), btn["text"], font=option_font, fill=(255,255,255))

        self.tk_img = ImageTk.PhotoImage(frame)
        self.label.configure(image=self.tk_img)
        self.label.lift()

    def _render_status(self, message, is_error=False):
        frame = self.base_bg.copy()
        d = ImageDraw.Draw(frame)
        
        # Status message
        status_font = load_ttf(36)  # Increased for 1280x1024
        color = (255,0,0) if is_error else (0,128,0)
        sw, sh = d.textbbox((0,0), message, font=status_font)[2:]
        d.text(((WINDOW_W - sw)//2, 250), message, font=status_font, fill=color)

        # Back to Menu button
        button_x, button_y = 100, 500
        button_text = "Back to Menu"
        bw, bh = d.textbbox((0,0), button_text, font=status_font)[2:]
        d.rectangle([button_x-20, button_y-10, button_x+bw+40, button_y+bh+10], 
                   fill=(0,120,200), outline=(0,0,0), width=2)
        d.text((button_x, button_y), button_text, font=status_font, fill=(255,255,255))

        self.tk_img = ImageTk.PhotoImage(frame)
        self.label.configure(image=self.tk_img)
        self.label.lift()
        
        # Set flag to indicate we're in a status screen
        self.back_to_menu = True

    def update_credentials(self):
        """Update credential files from Google Sheet."""
        if self.update_in_progress:
            return

        self.update_in_progress = True
        self._render_status("Updating credentials...")

        try:
            # Connect to Google Sheet
            scopes = [
                "https://www.googleapis.com/auth/spreadsheets.readonly",
                "https://www.googleapis.com/auth/drive.readonly",
                "https://www.googleapis.com/auth/spreadsheets",
            ]
            creds = Credentials.from_service_account_file(str(GS_CRED_PATH), scopes=scopes)
            gc = gspread.authorize(creds)

            # Open sheet and get credentials tab
            sheet = gc.open(GS_SHEET_NAME).worksheet(GS_CRED_TAB)

            # Create credentials directory if it doesn't exist
            CRED_DIR.mkdir(parents=True, exist_ok=True)

            # Update Cloudflared_Host from cell B18
            cloudflared_host = sheet.acell('B18').value
            with open(CRED_DIR / "Cloudflared_Host", 'w') as f:
                f.write(cloudflared_host or "")

            # Update GoogleFolderID.txt from cell B12
            folder_id = sheet.acell('B12').value
            with open(CRED_DIR / "GoogleFolderID.txt", 'w') as f:
                f.write(folder_id or "")

            # Update MachineID.txt from cell B16
            machine_id = sheet.acell('B16').value
            with open(CRED_DIR / "MachineID.txt", 'w') as f:
                f.write(machine_id or "")

            # Update GoogleCredEmail.txt from cell B10
            cred_email = sheet.acell('B10').value
            with open(CRED_DIR / "GoogleCredEmail.txt", 'w') as f:
                f.write(cred_email or "")

            logging.info("Admin: Successfully updated credential files")
            self._render_status("Credentials updated successfully!")

        except Exception as e:
            logging.error("Admin: Failed to update credentials: %s", e)
            self._render_status(f"Error: {str(e)}", is_error=True)

        finally:
            self.update_in_progress = False
            
    def update_location_files(self):
        """Update location-related files (weather, UPC catalog, hours)."""
        if self.update_in_progress:
            return
            
        self.update_in_progress = True
        self._render_status("Updating location files...")
        
        try:
            # Connect to Google Sheet
            scopes = [
                "https://www.googleapis.com/auth/spreadsheets.readonly",
                "https://www.googleapis.com/auth/drive.readonly",
                "https://www.googleapis.com/auth/spreadsheets",
            ]
            creds = Credentials.from_service_account_file(str(GS_CRED_PATH), scopes=scopes)
            gc = gspread.authorize(creds)
            
            # Open sheet
            sheet = gc.open(GS_SHEET_NAME)
            
            # 1. Update weather zipcode
            cred_tab = sheet.worksheet(GS_CRED_TAB)
            zipcode = cred_tab.acell('B24').value
            weather_api_key = cred_tab.acell('B25').value
            
            # Save zipcode and API key
            with open(CRED_DIR / "WeatherZipcode.txt", 'w') as f:
                f.write(zipcode or "")
            with open(CRED_DIR / "WeatherAPIKey.txt", 'w') as f:
                f.write(weather_api_key or "")
                
            # 2. Download UPC catalog
            try:
                inv_tab = sheet.worksheet(GS_TAB)
                rows = inv_tab.get_all_values()
                
                # Save as CSV
                with open(CRED_DIR / "upc_catalog.csv", 'w', newline='') as f:
                    import csv
                    writer = csv.writer(f)
                    writer.writerows(rows)
                logging.info(f"Saved UPC catalog with {len(rows)} rows")
            except Exception as e:
                logging.error(f"Failed to download UPC catalog: {e}")
                
            # 3. Download schedule from Hours tab
            try:
                hours_tab = sheet.worksheet("Hours")
                hours_data = hours_tab.get_all_values()
                
                # Save as CSV
                with open(CRED_DIR / "store_hours.csv", 'w', newline='') as f:
                    import csv
                    writer = csv.writer(f)
                    writer.writerows(hours_data)
                logging.info(f"Saved store hours with {len(hours_data)} rows")
            except Exception as e:
                logging.error(f"Failed to download store hours: {e}")
            
            self._render_status("Location files updated successfully!")
            
        except Exception as e:
            logging.error(f"Failed to update location files: {e}")
            self._render_status(f"Error: {str(e)}", is_error=True)
            
        finally:
            self.update_in_progress = False
    
    def open_wifi_settings(self):
        """Open WiFi settings with virtual keyboard."""
        if self.update_in_progress:
            return
            
        self.update_in_progress = True
        
        try:
            # Create WiFi settings frame
            wifi_frame = tk.Frame(self.root, bg="#2c3e50")
            wifi_frame.place(x=0, y=0, width=WINDOW_W, height=WINDOW_H)
            
            # Title
            title_label = tk.Label(wifi_frame, text="WiFi Settings", 
                                  font=("Arial", 36, "bold"), bg="#2c3e50", fg="white")
            title_label.pack(pady=(50, 30))
            
            # Network selection
            networks_frame = tk.Frame(wifi_frame, bg="#2c3e50")
            networks_frame.pack(pady=20, fill=tk.X)
            
            networks_label = tk.Label(networks_frame, text="Available Networks:", 
                                     font=("Arial", 24), bg="#2c3e50", fg="white")
            networks_label.pack(anchor=tk.W, padx=50)
            
            # Get available networks
            networks = self._get_wifi_networks()
            
            # Network listbox
            network_listbox = tk.Listbox(networks_frame, font=("Arial", 18), height=6, width=40)
            network_listbox.pack(padx=50, pady=10, fill=tk.X)
            
            # Populate networks
            for network in networks:
                network_listbox.insert(tk.END, network)
            
            # Password entry
            password_frame = tk.Frame(wifi_frame, bg="#2c3e50")
            password_frame.pack(pady=20, fill=tk.X)
            
            password_label = tk.Label(password_frame, text="Password:", 
                                     font=("Arial", 24), bg="#2c3e50", fg="white")
            password_label.pack(anchor=tk.W, padx=50)
            
            password_var = tk.StringVar()
            password_entry = tk.Entry(password_frame, textvariable=password_var,
                                     font=("Arial", 18), width=30, show="•")
            password_entry.pack(padx=50, pady=10, fill=tk.X)
            
            # Buttons
            button_frame = tk.Frame(wifi_frame, bg="#2c3e50")
            button_frame.pack(pady=30)
            
            connect_button = tk.Button(button_frame, text="Connect", font=("Arial", 18),
                                     bg="#27ae60", fg="white", width=10,
                                     command=lambda: self._connect_wifi(network_listbox.get(tk.ACTIVE), password_var.get()))
            connect_button.pack(side=tk.LEFT, padx=20)
            
            back_button = tk.Button(button_frame, text="Back", font=("Arial", 18),
                                   bg="#e74c3c", fg="white", width=10,
                                   command=lambda: self._close_wifi_settings(wifi_frame))
            back_button.pack(side=tk.LEFT, padx=20)
            
            # Create virtual keyboard
            keyboard_frame = tk.Frame(wifi_frame, bg="#34495e")
            keyboard_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=20)
            
            # Define keyboard layout
            keys = [
                ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0'],
                ['q', 'w', 'e', 'r', 't', 'y', 'u', 'i', 'o', 'p'],
                ['a', 's', 'd', 'f', 'g', 'h', 'j', 'k', 'l'],
                ['z', 'x', 'c', 'v', 'b', 'n', 'm', '.', '@']
            ]
            
            # Create keyboard buttons
            for row_idx, row in enumerate(keys):
                row_frame = tk.Frame(keyboard_frame, bg="#34495e")
                row_frame.pack(pady=5)
                
                for key in row:
                    key_button = tk.Button(row_frame, text=key, font=("Arial", 18),
                                         width=3, height=1, bg="#7f8c8d", fg="white",
                                         command=lambda k=key: self._key_press(password_entry, k))
                    key_button.pack(side=tk.LEFT, padx=3)
            
            # Special keys row
            special_frame = tk.Frame(keyboard_frame, bg="#34495e")
            special_frame.pack(pady=5)
            
            # Space
            space_button = tk.Button(special_frame, text="Space", font=("Arial", 18),
                                   width=20, height=1, bg="#7f8c8d", fg="white",
                                   command=lambda: self._key_press(password_entry, " "))
            space_button.pack(side=tk.LEFT, padx=3)
            
            # Backspace
            backspace_button = tk.Button(special_frame, text="←", font=("Arial", 18),
                                       width=5, height=1, bg="#e67e22", fg="white",
                                       command=lambda: self._backspace(password_entry))
            backspace_button.pack(side=tk.LEFT, padx=3)
            
            # Clear
            clear_button = tk.Button(special_frame, text="Clear", font=("Arial", 18),
                                   width=5, height=1, bg="#e74c3c", fg="white",
                                   command=lambda: self._clear_field(password_entry))
            clear_button.pack(side=tk.LEFT, padx=3)
            
            # Focus password entry
            password_entry.focus_set()
            
        except Exception as e:
            logging.error(f"Failed to open WiFi settings: {e}")
            self._render_status(f"Error opening WiFi settings: {str(e)}", is_error=True)
            
        finally:
            self.update_in_progress = False
    
    def _get_wifi_networks(self):
        """Get list of available WiFi networks."""
        try:
            # Use iwlist to scan for networks
            output = subprocess.check_output("sudo iwlist wlan0 scan | grep ESSID", shell=True)
            networks = []
            for line in output.decode('utf-8').splitlines():
                if 'ESSID:' in line:
                    network = line.split('ESSID:"')[1].split('"')[0]
                    if network and network not in networks:
                        networks.append(network)
            return networks
        except Exception as e:
            logging.error(f"Failed to get WiFi networks: {e}")
            return ["WiFi 1", "WiFi 2", "WiFi 3"]  # Fallback for testing
    
    def _connect_wifi(self, network, password):
        """Connect to WiFi network."""
        if not network:
            return
            
        try:
            # Create wpa_supplicant entry
            config = f'''
network={{
    ssid="{network}"
    psk="{password}"
}}
'''
            # Write to temporary file
            with open("/tmp/wpa_supplicant.conf", "w") as f:
                f.write(config)
                
            # Apply configuration
            subprocess.run("sudo cp /tmp/wpa_supplicant.conf /etc/wpa_supplicant/wpa_supplicant.conf", shell=True)
            subprocess.run("sudo wpa_cli -i wlan0 reconfigure", shell=True)
            
            # Show status
            self._render_status(f"Connected to {network}")
            
        except Exception as e:
            logging.error(f"Failed to connect to WiFi: {e}")
            self._render_status(f"Error connecting to WiFi: {str(e)}", is_error=True)
    
    def _close_wifi_settings(self, wifi_frame):
        """Close WiFi settings and return to admin menu."""
        wifi_frame.destroy()
        self._render_menu()
    
    def _key_press(self, entry, key):
        """Handle key press on virtual keyboard."""
        current_text = entry.get()
        entry.delete(0, tk.END)
        entry.insert(0, current_text + key)
        
    def _backspace(self, entry):
        """Handle backspace on virtual keyboard."""
        current_text = entry.get()
        if current_text:
            entry.delete(0, tk.END)
            entry.insert(0, current_text[:-1])
            
    def _clear_field(self, entry):
        """Handle clear on virtual keyboard."""
        entry.delete(0, tk.END)
    
    def load_inventory_portal(self):
        """Load inventory portal from URL in spreadsheet."""
        if self.update_in_progress:
            return
            
        self.update_in_progress = True
        self._render_status("Loading inventory portal...")
        
        try:
            # Connect to Google Sheet
            scopes = [
                "https://www.googleapis.com/auth/spreadsheets.readonly",
                "https://www.googleapis.com/auth/drive.readonly",
                "https://www.googleapis.com/auth/spreadsheets",
            ]
            creds = Credentials.from_service_account_file(str(GS_CRED_PATH), scopes=scopes)
            gc = gspread.authorize(creds)
            
            # Get portal URL
            sheet = gc.open(GS_SHEET_NAME).worksheet(GS_CRED_TAB)
            portal_url = sheet.acell('B21').value
            
            if not portal_url:
                self._render_status("Inventory portal URL not found", is_error=True)
                return
                
            # Create web view frame
            self.web_view = tk.Toplevel(self.root)
            self.web_view.attributes("-fullscreen", True)
            self.web_view.title("Inventory Portal")
            
            # Try to use a web browser widget if available
            try:
                import webview
                webview.create_window("Inventory Portal", portal_url)
                webview.start()
            except ImportError:
                # Fallback to system browser
                import webbrowser
                webbrowser.open(portal_url)
                self._render_status("Opened in system browser")
            
        except Exception as e:
            logging.error(f"Failed to load inventory portal: {e}")
            self._render_status(f"Error loading portal: {str(e)}", is_error=True)
            
        finally:
            self.update_in_progress = False
            
    def _arm_timeout(self):
        """Set up inactivity timeout for admin mode."""
        if self.timeout_after:
            self.root.after_cancel(self.timeout_after)
            
        def check_timeout():
            current_time = time.time()
            elapsed = current_time - self.last_activity_ts
            logging.debug(f"Admin timeout check: {elapsed:.1f}s elapsed")
            
            if elapsed >= (ADMIN_TIMEOUT_MS/1000.0):
                logging.info(f"Admin mode timeout after {elapsed:.1f}s - returning to Idle")
                if hasattr(self, "on_timeout"):
                    self.on_timeout()
                return
            self.timeout_after = self.root.after(1000, check_timeout)
            
        self.timeout_after = self.root.after(1000, check_timeout)

# ==============================
#          Cart Mode
# ==============================

class CartMode:
    """
    Shopping cart mode for adding and managing items.
    Displays Cart.png as background with receipt recorder and totals.
    """
    def __init__(self, root, **kwargs):
        """Initialize the CartMode."""
        self.root = root
        self.label = tk.Label(root, bg="black")
        
        # Define cache directory
        self.cache_dir = Path.home() / "SelfCheck" / "Cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # Get drive service directly from root if available
        self.drive_service = getattr(root, 'drive_service', None)
        
        # Log drive service status
        if self.drive_service:
            logging.info("Drive service successfully accessed in CartMode")
        else:
            logging.warning("Drive service not found in CartMode initialization")
        
        # Cart data structures
        self.cart_items = {}  # UPC -> {data, qty}
        self.upc_catalog = {}  # UPC -> row data
        self.transaction_id = self._generate_transaction_id()
        self.current_payment_method = None
        
        # UI elements
        self.tk_img = None
        self.base_bg = None
        self.receipt_frame = None
        self.receipt_canvas = None
        self.receipt_scrollbar = None
        self.receipt_items_frame = None
        self.totals_frame = None
        self.item_frames = []
        self.popup_frame = None
        self.manual_entry_frame = None
        
        # Config data
        self.business_name = "Vend Las Vegas"
        self.location = "1234 Fake Street\nTest NV\n89921"
        self.machine_id = "Prototype1001"
        self.tax_rate = 0.0  # Will be loaded from Tax.json
        
        # Timeout handling
        self.last_activity_ts = time.time()
        self.timeout_after = None
        self.timeout_popup = None
        self.countdown_label = None
        self.countdown_after = None
        self.countdown_value = 30
        
        # Add touch support
        self.label.bind("<Button-1>", self._on_touch)
        self.label.bind("<Motion>", self._on_activity)
        
        # Barcode input handling
        self.barcode_buffer = ""
        self.root.bind("<Key>", self._on_key)
        
        # Load UPC catalog and config files
        self._load_upc_catalog()
        self._load_config_files()
        
        # Test Google Sheets access
        self.sheets_access_ok = self.test_sheet_access()
        if self.sheets_access_ok:
            logging.info("Google Sheets access test passed")
        else:
            logging.warning("Google Sheets access test failed - logging to Service tab may not work")
            # Check permissions to help diagnose the issue
            self.check_spreadsheet_permissions()



    def print_receipt(self, payment_method, total):
        """Print a receipt using direct device access."""
        try:
            # Calculate values needed for receipt
            subtotal = sum(item["price"] * item["qty"] for item in self.cart_items.values())
            taxable_subtotal = sum(
                item["price"] * item["qty"] 
                for item in self.cart_items.values() if item["taxable"]
            )
            tax_amount = taxable_subtotal * (self.tax_rate / 100)
            total_items = sum(item["qty"] for item in self.cart_items.values())
            
            # Format the receipt content
            receipt = []
            
            # Initialize printer
            receipt.append(b'\x1B@')
            
            # Center align for header
            receipt.append(b'\x1B\x61\x01')  # Center align
            
            # Business name - double height and width
            receipt.append(b'\x1D\x21\x11')  # Double height and width
            receipt.append(self.business_name.encode('ascii', 'replace') + b'\n')
            
            # Normal size for the rest
            receipt.append(b'\x1D\x21\x00')
            
            # Location
            receipt.append(self.location.encode('ascii', 'replace') + b'\n')
            
            # Left align for details
            receipt.append(b'\x1B\x61\x00')
            
            # Machine ID
            receipt.append(f"Machine: {self.machine_id}\n".encode('ascii', 'replace'))
            
            # Transaction ID
            receipt.append(f"Transaction: {self.transaction_id}\n".encode('ascii', 'replace'))
            
            # Date and time
            current_time = datetime.now().strftime('%m/%d/%Y %H:%M:%S')
            receipt.append(f"Date: {current_time}\n".encode('ascii', 'replace'))
            
            # Divider
            receipt.append(b'-' * 32 + b'\n')
            
            # Items
            for upc, item in self.cart_items.items():
                name = item["name"]
                price = item["price"]
                qty = item["qty"]
                item_total = price * qty
                
                # Format item line - truncate long names
                if len(name) > 30:
                    name = name[:27] + "..."
                
                receipt.append(f"{name}\n".encode('ascii', 'replace'))
                receipt.append(f"  {qty} @ ${price:.2f} = ${item_total:.2f}\n".encode('ascii', 'replace'))
            
            # Divider
            receipt.append(b'-' * 32 + b'\n')
            
            # Totals
            receipt.append(f"Items: {total_items}\n".encode('ascii', 'replace'))
            receipt.append(f"Subtotal: ${subtotal:.2f}\n".encode('ascii', 'replace'))
            receipt.append(f"Tax ({self.tax_rate}%): ${tax_amount:.2f}\n".encode('ascii', 'replace'))
            
            # Bold for total
            receipt.append(b'\x1B\x45\x01')  # Bold on
            receipt.append(f"Total: ${total:.2f}\n".encode('ascii', 'replace'))
            receipt.append(b'\x1B\x45\x00')  # Bold off
            
            receipt.append(f"Paid: {payment_method}\n".encode('ascii', 'replace'))
            
            # Divider
            receipt.append(b'-' * 32 + b'\n')
            
            # Custom message from RMessage.txt
            try:
                rmessage_path = Path.home() / "SelfCheck" / "Cred" / "RMessage.txt"
                if rmessage_path.exists():
                    with open(rmessage_path, 'r') as f:
                        rmessage = f.read().strip()
                        receipt.append(b'\x1B\x61\x01')  # Center align
                        receipt.append(rmessage.encode('ascii', 'replace') + b'\n')
                else:
                    # Create default RMessage.txt if it doesn't exist
                    rmessage = "Thank you for shopping with us!"
                    rmessage_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(rmessage_path, 'w') as f:
                        f.write(rmessage)
                    receipt.append(b'\x1B\x61\x01')  # Center align
                    receipt.append(rmessage.encode('ascii', 'replace') + b'\n')
            except Exception as e:
                logging.error(f"Error reading/writing RMessage.txt: {e}")
                # Add a default message
                receipt.append(b'\x1B\x61\x01')  # Center align
                receipt.append(b'Thank you for shopping with us!\n')
            
            # Feed and cut - REMOVE the duplicate thank you message
            receipt.append(b'\n\n\n\n')  # Just feed paper without additional message
            
            # Cut paper
            receipt.append(b'\x1D\x56\x00')
            
            # Combine all parts
            receipt_data = b''.join(receipt)
            
            # Save receipt to file
            receipt_path = Path.home() / "SelfCheck" / "Cred" / "last_receipt.txt"
            receipt_path.parent.mkdir(parents=True, exist_ok=True)
            with open(receipt_path, 'wb') as f:
                f.write(receipt_data)
            
            # Check if printer device exists
            if hasattr(self, 'printer_path') and self.printer_path:
                printer_path = self.printer_path
            else:
                printer_path = '/dev/usb/lp0'
                if not Path(printer_path).exists():
                    logging.error(f"Printer device not found: {printer_path}")
                    # Try alternative paths
                    alternative_paths = ['/dev/lp0', '/dev/usb/lp1', '/dev/lp1']
                    for alt_path in alternative_paths:
                        if Path(alt_path).exists():
                            logging.info(f"Found alternative printer device: {alt_path}")
                            printer_path = alt_path
                            break
                    else:
                        logging.error("No printer device found")
                        return False
            
            # Print using direct device access
            try:
                with open(printer_path, 'wb') as printer:
                    printer.write(receipt_data)
                logging.info(f"Receipt printed successfully to {printer_path}")
                return True
            except PermissionError:
                logging.error(f"Permission denied accessing printer at {printer_path}")
                messagebox.showerror("Printer Error", 
                                   f"Permission denied accessing printer.\n\n"
                                   f"Please run: sudo chmod 666 {printer_path}")
                return False
            
        except Exception as e:
            logging.error(f"Error printing receipt: {e}")
            import traceback
            logging.error(traceback.format_exc())
            return False


    def _receipt_option_selected(self, option):
        """Handle receipt option selection."""
        logging.info(f"Receipt option selected: {option}")
        
        if option == "print":
            logging.debug("Processing print receipt option")
            # Calculate the total
            subtotal = sum(item["price"] * item["qty"] for item in self.cart_items.values())
            taxable_subtotal = sum(
                item["price"] * item["qty"] 
                for item in self.cart_items.values() if item["taxable"]
            )
            tax_amount = taxable_subtotal * (self.tax_rate / 100)
            total = subtotal + tax_amount
            
            # Get payment method (default to "Unknown" if not set)
            payment_method = getattr(self, 'current_payment_method', "Unknown")
            
            # Try to print receipt
            logging.debug("Calling print_receipt method")
            success = self.print_receipt(payment_method, total)
            
            if success:
                logging.debug("Receipt printed successfully")
                messagebox.showinfo("Receipt", "Receipt printed successfully.")
            else:
                logging.debug("Receipt printing failed")
                # If printing fails, show a text-based receipt
                response = messagebox.askquestion("Printer Error", 
                                               "Failed to print receipt. Would you like to view it on screen instead?")
                if response == 'yes':
                    self._show_text_receipt(payment_method, total)
        
        elif option == "email":
            # Future implementation
            messagebox.showinfo("Receipt", "Email receipt option selected.\nThis feature will be implemented soon.")
        
        # Always complete the thank you process and return to idle mode
        logging.debug("Calling _thank_you_complete to return to idle mode")
        self._thank_you_complete()



    def generate_transaction_id(self):
        """Generate a unique transaction ID in format YYDDD###."""
        from datetime import datetime
        
        # Get current date components
        now = datetime.now()
        year_last_two = now.strftime("%y")  # Last two digits of year (e.g., "25" for 2025)
        day_of_year = now.strftime("%j")    # Day of year as 3 digits (e.g., "236" for Aug 24)
        
        # Get the current transaction count for today
        transaction_count_file = Path.home() / "SelfCheck" / "Logs" / f"transaction_count_{year_last_two}{day_of_year}.txt"
        
        # Create directory if it doesn't exist
        transaction_count_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Get current count or start at 0
        current_count = 0
        if transaction_count_file.exists():
            try:
                with open(transaction_count_file, 'r') as f:
                    current_count = int(f.read().strip())
            except (ValueError, IOError) as e:
                logging.error(f"Error reading transaction count: {e}")
        
        # Increment count
        new_count = current_count + 1
        
        # Save new count
        try:
            with open(transaction_count_file, 'w') as f:
                f.write(str(new_count))
        except IOError as e:
            logging.error(f"Error saving transaction count: {e}")
        
        # Format transaction ID: YYDDD### (e.g., 25236001)
        transaction_id = f"{year_last_two}{day_of_year:03d}{new_count:03d}"
        
        logging.info(f"Generated transaction ID: {transaction_id}")
        return transaction_id

    def get_venmo_username(self):
        """Get Venmo username from VenmoUser.txt."""
        venmo_user_path = Path.home() / "SelfCheck" / "Cred" / "VenmoUser.txt"
        
        if not venmo_user_path.exists():
            logging.error("VenmoUser.txt not found")
            return "YourVenmoUsername"  # Default fallback
        
        try:
            with open(venmo_user_path, 'r') as f:
                username = f.read().strip()
                if username:
                    return username
                else:
                    logging.error("VenmoUser.txt is empty")
                    return "YourVenmoUsername"  # Default fallback
        except IOError as e:
            logging.error(f"Error reading VenmoUser.txt: {e}")
            return "YourVenmoUsername"  # Default fallback


    def _update_totals(self):
        """Update the totals display with current cart values."""
        if not hasattr(self, 'totals_frame') or not self.totals_frame:
            return
        
        # Clear existing totals display
        for widget in self.totals_frame.winfo_children():
            widget.destroy()
        
        # Calculate totals
        subtotal = sum(item["price"] * item["qty"] for item in self.cart_items.values())
        taxable_subtotal = sum(
            item["price"] * item["qty"] 
            for item in self.cart_items.values() if item["taxable"]
        )
        tax_amount = taxable_subtotal * (self.tax_rate / 100)
        total = subtotal + tax_amount
        total_items = sum(item["qty"] for item in self.cart_items.values())
        
        # Title
        title_label = tk.Label(self.totals_frame, text="Order Summary", 
                              font=("Arial", 18, "bold"), bg="white")
        title_label.pack(pady=(10, 20))
        
        # Items count
        items_label = tk.Label(self.totals_frame, 
                              text=f"Items: {total_items}", 
                              font=("Arial", 16), bg="white")
        items_label.pack(pady=5)
        
        # Subtotal
        subtotal_label = tk.Label(self.totals_frame, 
                                 text=f"Subtotal: ${subtotal:.2f}", 
                                 font=("Arial", 16), bg="white")
        subtotal_label.pack(pady=5)
        
        # Tax
        tax_label = tk.Label(self.totals_frame, 
                            text=f"Tax ({self.tax_rate}%): ${tax_amount:.2f}", 
                            font=("Arial", 16), bg="white")
        tax_label.pack(pady=5)
        
        # Total (bold and larger)
        total_label = tk.Label(self.totals_frame, 
                              text=f"Total: ${total:.2f}", 
                              font=("Arial", 20, "bold"), bg="white")
        total_label.pack(pady=(10, 5))




    def _reload_tax_rate(self):
        """Reload the tax rate from Tax.json to ensure it's current."""
        tax_path = CRED_DIR / "Tax.json"
        if tax_path.exists():
            try:
                with open(tax_path, 'r') as f:
                    data = json.load(f)
                    self.tax_rate = float(data.get("rate", 2.9))
                    logging.info(f"Reloaded tax rate from Tax.json: {self.tax_rate}%")
            except (json.JSONDecodeError, ValueError) as e:
                logging.error(f"Error reloading tax rate: {e}")


    def _on_key(self, event):
        """Handle keyboard input for barcode scanning."""
        if event.char == '\r' or event.char == '\n':  # Enter key
            barcode = self.barcode_buffer.strip()
            self.barcode_buffer = ""
            
            if barcode:
                logging.info(f"CartMode: Barcode scanned: {barcode}")
                self.scan_item(barcode)
        elif event.char.isprintable():
            self.barcode_buffer += event.char

    def handle_barcode_input(self, barcode):
        """Process a barcode input from scanner."""
        logging.info(f"CartMode: Received barcode input: {barcode}")
        return self.scan_item(barcode)

    def _load_config_files(self):
        """Load configuration from JSON files."""
        try:
            # Business name
            business_path = CRED_DIR / "BusinessName.json"
            if business_path.exists():
                try:
                    with open(business_path, 'r') as f:
                        data = json.load(f)
                        self.business_name = data.get("name", self.business_name)
                except json.JSONDecodeError:
                    logging.error(f"Invalid JSON in BusinessName.json")
                    # Create a new file with default value
                    with open(business_path, 'w') as f:
                        json.dump({"name": self.business_name}, f)
            
            # Location
            location_path = CRED_DIR / "MachineLocation.json"
            if location_path.exists():
                try:
                    with open(location_path, 'r') as f:
                        data = json.load(f)
                        self.location = data.get("location", self.location)
                except json.JSONDecodeError:
                    logging.error(f"Invalid JSON in MachineLocation.json")
                    # Create a new file with default value
                    with open(location_path, 'w') as f:
                        json.dump({"location": self.location}, f)
            
            # Machine ID
            machine_id_path = CRED_DIR / "MachineID.txt"
            if machine_id_path.exists():
                with open(machine_id_path, 'r') as f:
                    self.machine_id = f.read().strip() or self.machine_id
            
            # Tax rate
            tax_path = CRED_DIR / "Tax.json"
            if tax_path.exists():
                try:
                    with open(tax_path, 'r') as f:
                        data = json.load(f)
                        old_rate = self.tax_rate
                        self.tax_rate = float(data.get("rate", 2.9))  # Default to 2.9% if not specified
                        logging.info(f"Loaded tax rate from Tax.json: {self.tax_rate}% (was {old_rate}%)")
                except (json.JSONDecodeError, ValueError):
                    # If Tax.json is malformed, create a new one with default value
                    logging.warning(f"Tax.json is malformed, creating new file with default rate")
                    self.tax_rate = 2.9  # Default tax rate
                    with open(tax_path, 'w') as f:
                        json.dump({"rate": self.tax_rate}, f)
                    logging.info(f"Created new Tax.json with rate: {self.tax_rate}%")
            else:
                # If Tax.json doesn't exist, create it
                logging.warning(f"Tax.json not found, creating new file with default rate")
                self.tax_rate = 2.9  # Default tax rate
                with open(tax_path, 'w') as f:
                    json.dump({"rate": self.tax_rate}, f)
                logging.info(f"Created new Tax.json with rate: {self.tax_rate}%")
                
        except Exception as e:
            logging.error(f"Error loading config files: {e}")
            import traceback
            logging.error(traceback.format_exc())
            # Set default tax rate if there was an error
            self.tax_rate = 0.0


    def _generate_venmo_qr_code(self, total):
        """Generate a Venmo QR code for payment."""
        import qrcode
        import urllib.parse
        
        # Generate a unique transaction ID
        if not hasattr(self, 'current_transaction_id'):
            self.current_transaction_id = self.generate_transaction_id()
        
        # Format the amount with 2 decimal places
        formatted_total = "{:.2f}".format(total)
        
        # Get Venmo username
        venmo_username = self.get_venmo_username()
        
        # Create a detailed note with machine ID and transaction ID
        note = f"Payment #{self.current_transaction_id} - Machine: {self.machine_id}"
        
        # Create the Venmo URL - use URL encoding for the note
        encoded_note = urllib.parse.quote(note)
        
        venmo_url = f"venmo://paycharge?txn=pay&recipients={venmo_username}&amount={formatted_total}&note={encoded_note}"
        
        # Also create a web URL for devices that don't have Venmo app
        web_url = f"https://venmo.com/{venmo_username}?txn=pay&amount={formatted_total}&note={encoded_note}"
        
        logging.info(f"Generated Venmo payment URL: {venmo_url}")
        logging.info(f"Generated Venmo web URL: {web_url}")
        
        # Create QR code for the Venmo URL
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(venmo_url)
        qr.make(fit=True)
        
        # Create an image from the QR Code
        img = qr.make_image(fill_color="black", back_color="white")
        
        # Return the PIL Image and transaction ID
        return img, self.current_transaction_id




    def _show_venmo_qr_code(self, total):
        """Show QR code for Venmo payment."""
        # Close the current payment popup
        if hasattr(self, 'payment_popup') and self.payment_popup:
            self.payment_popup.destroy()
        
        # Create a new popup for the QR code
        self.payment_popup = tk.Frame(self.root, bg="white", bd=3, relief=tk.RAISED)
        self.payment_popup.place(relx=0.5, rely=0.5, width=600, height=700, anchor=tk.CENTER)
        
        # Title
        title_label = tk.Label(self.payment_popup, 
                             text="Pay with Venmo", 
                             font=("Arial", 24, "bold"), 
                             bg="white")
        title_label.pack(pady=(20, 10))
        
        try:
            # Generate QR code and get transaction ID
            qr_img, transaction_id = self._generate_venmo_qr_code(total)
            
            # Store transaction ID for reference
            self.current_transaction_id = transaction_id
            
            # Amount and transaction ID
            details_frame = tk.Frame(self.payment_popup, bg="white")
            details_frame.pack(pady=(0, 10))
            
            amount_label = tk.Label(details_frame, 
                                  text=f"Amount: ${total:.2f}", 
                                  font=("Arial", 18), 
                                  bg="white")
            amount_label.pack(pady=5)
            
            # Resize QR for display
            qr_img = qr_img.resize((300, 300), Image.LANCZOS)
            
            # Convert to PhotoImage
            qr_photo = ImageTk.PhotoImage(qr_img)
            
            # Display QR code
            qr_label = tk.Label(self.payment_popup, image=qr_photo, bg="white")
            qr_label.image = qr_photo  # Keep a reference
            qr_label.pack(pady=10)
            
            # Instructions
            instructions = (
                "1. Open your phone's camera app\n"
                "2. Scan this QR code\n"
                "3. Follow the link to the Venmo app\n"
                "4. Complete payment in the Venmo app\n"
                "5. After payment, click 'Record Payment' below\n"
                "   and enter the last 4 digits of your transaction ID"
            )
            
            instructions_label = tk.Label(self.payment_popup, 
                                        text=instructions, 
                                        font=("Arial", 14), 
                                        bg="white",
                                        justify=tk.LEFT)
            instructions_label.pack(pady=10)
            
        except Exception as e:
            logging.error(f"Error generating Venmo QR code: {e}")
            import traceback
            logging.error(traceback.format_exc())
            
            # Show error message instead of QR code
            error_label = tk.Label(self.payment_popup, 
                                 text=f"Error generating QR code:\n{str(e)}", 
                                 font=("Arial", 16), 
                                 bg="white",
                                 fg="#e74c3c")  # Red color
            error_label.pack(pady=20)
        
        # Button frame
        button_frame = tk.Frame(self.payment_popup, bg="white")
        button_frame.pack(pady=(20, 20), fill=tk.X, padx=20)
        
        # Record Payment button
        record_btn = tk.Button(button_frame, 
                             text="Record Payment", 
                             font=("Arial", 16), 
                             command=self._show_transaction_id_entry,
                             bg="#27ae60", fg="white",
                             height=1)
        record_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        
        # Return to Cart button
        return_btn = tk.Button(button_frame, 
                             text="Return to Cart", 
                             font=("Arial", 16), 
                             command=self._close_payment_popup,
                             bg="#3498db", fg="white",
                             height=1)
        return_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        
        # Cancel Order button
        cancel_btn = tk.Button(button_frame, 
                             text="Cancel Order", 
                             font=("Arial", 16), 
                             command=self._cancel_from_payment,
                             bg="#e74c3c", fg="white",
                             height=1)
        cancel_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        
        # Start timeout for payment popup - 60 seconds
        self._start_payment_timeout(timeout_seconds=60)

    def _thank_you_timeout(self):
        """Handle timeout on the thank you screen."""
        logging.info("Thank you screen timed out")
        self._thank_you_complete()


    def _show_idle_screen(self):
        """Show the idle screen and hide the cart screen."""
        logging.debug("Showing idle screen")
        
        # Hide cart container if it exists
        if hasattr(self, 'cart_container'):
            self.cart_container.pack_forget()
        
        # Show welcome message
        welcome_frame = tk.Frame(self.root, bg="white")
        welcome_frame.pack(fill=tk.BOTH, expand=True)
        
        # Store reference to welcome frame
        self.welcome_frame = welcome_frame
        
        # Welcome message
        welcome_label = tk.Label(welcome_frame, 
                               text="Welcome to Self-Checkout", 
                               font=("Arial", 36, "bold"), 
                               bg="white")
        welcome_label.pack(pady=(100, 20))
        
        # Instructions
        instructions = tk.Label(welcome_frame, 
                              text="Scan an item to begin", 
                              font=("Arial", 24), 
                              bg="white")
        instructions.pack(pady=20)
        
        # Logo or image if available
        try:
            logo_path = Path.home() / "SelfCheck" / "logo.png"
            if logo_path.exists():
                logo_img = Image.open(logo_path)
                logo_img = logo_img.resize((300, 300), Image.LANCZOS)
                logo_photo = ImageTk.PhotoImage(logo_img)
                
                logo_label = tk.Label(welcome_frame, image=logo_photo, bg="white")
                logo_label.image = logo_photo  # Keep a reference
                logo_label.pack(pady=20)
        except Exception as e:
            logging.error(f"Error loading logo: {e}")
        
        # Set mode to idle
        self.mode = "idle"
        
        # Generate a new transaction ID for the next customer
        self.transaction_id = self._generate_transaction_id()
        logging.info(f"New transaction ID generated: {self.transaction_id}")

    def update_cart_display(self):
        """Update the cart display with current items and totals."""
        logging.debug("Updating cart display")
        
        # If cart frame doesn't exist yet, create it
        if not hasattr(self, 'cart_frame'):
            logging.warning("Cart frame doesn't exist, can't update display")
            return
        
        # Clear existing items
        for widget in self.cart_frame.winfo_children():
            widget.destroy()
        
        # If cart is empty, show message
        if not self.cart_items:
            empty_label = tk.Label(self.cart_frame, text="Cart is empty", 
                                 font=("Arial", 14), bg="white")
            empty_label.pack(pady=20)
            
            # Update totals
            self.update_totals_display(0, 0, 0)
            return
        
        # Add header
        header_frame = tk.Frame(self.cart_frame, bg="white")
        header_frame.pack(fill=tk.X, padx=10, pady=(10, 5))
        
        # Header labels
        tk.Label(header_frame, text="Item", font=("Arial", 12, "bold"), 
               bg="white", width=20, anchor="w").pack(side=tk.LEFT)
        tk.Label(header_frame, text="Price", font=("Arial", 12, "bold"), 
               bg="white", width=8, anchor="e").pack(side=tk.LEFT)
        tk.Label(header_frame, text="Qty", font=("Arial", 12, "bold"), 
               bg="white", width=5, anchor="e").pack(side=tk.LEFT)
        tk.Label(header_frame, text="Total", font=("Arial", 12, "bold"), 
               bg="white", width=8, anchor="e").pack(side=tk.LEFT)
        
        # Add separator
        separator = tk.Frame(self.cart_frame, height=2, bg="#ddd")
        separator.pack(fill=tk.X, padx=10, pady=5)
        
        # Add items
        for upc, item in self.cart_items.items():
            item_frame = tk.Frame(self.cart_frame, bg="white")
            item_frame.pack(fill=tk.X, padx=10, pady=2)
            
            # Truncate long names
            name = item["name"]
            if len(name) > 25:
                name = name[:22] + "..."
            
            # Item details
            tk.Label(item_frame, text=name, font=("Arial", 12), 
                   bg="white", width=20, anchor="w").pack(side=tk.LEFT)
            tk.Label(item_frame, text=f"${item['price']:.2f}", font=("Arial", 12), 
                   bg="white", width=8, anchor="e").pack(side=tk.LEFT)
            
            # Quantity with +/- buttons
            qty_frame = tk.Frame(item_frame, bg="white")
            qty_frame.pack(side=tk.LEFT, padx=5)
            
            minus_btn = tk.Button(qty_frame, text="-", font=("Arial", 10), 
                                command=lambda u=upc: self.decrease_quantity(u),
                                width=1, height=1)
            minus_btn.pack(side=tk.LEFT)
            
            tk.Label(qty_frame, text=str(item["qty"]), font=("Arial", 12), 
                   bg="white", width=2).pack(side=tk.LEFT, padx=2)
            
            plus_btn = tk.Button(qty_frame, text="+", font=("Arial", 10), 
                               command=lambda u=upc: self.increase_quantity(u),
                               width=1, height=1)
            plus_btn.pack(side=tk.LEFT)
            
            # Total for this item
            item_total = item["price"] * item["qty"]
            tk.Label(item_frame, text=f"${item_total:.2f}", font=("Arial", 12), 
                   bg="white", width=8, anchor="e").pack(side=tk.LEFT)
            
            # Remove button
            remove_btn = tk.Button(item_frame, text="×", font=("Arial", 12, "bold"), 
                                 command=lambda u=upc: self.remove_item(u),
                                 bg="#ff6b6b", fg="white", width=2)
            remove_btn.pack(side=tk.LEFT, padx=(5, 0))
        
        # Calculate totals
        subtotal = sum(item["price"] * item["qty"] for item in self.cart_items.values())
        taxable_subtotal = sum(
            item["price"] * item["qty"] 
            for item in self.cart_items.values() if item["taxable"]
        )
        tax_amount = taxable_subtotal * (self.tax_rate / 100)
        total = subtotal + tax_amount
        
        # Update totals display
        self.update_totals_display(subtotal, tax_amount, total)


    def _thank_you_complete(self):
        """Complete the thank you process and return to idle mode."""
        logging.debug("Entering _thank_you_complete method")
        
        # Cancel timeout if it exists
        if hasattr(self, 'thank_you_timeout') and self.thank_you_timeout:
            logging.debug("Canceling thank you timeout")
            self.root.after_cancel(self.thank_you_timeout)
            self.thank_you_timeout = None
        
        # Close thank you popup if it exists
        if hasattr(self, 'thank_you_popup') and self.thank_you_popup:
            logging.debug("Destroying thank you popup")
            self.thank_you_popup.destroy()
            self.thank_you_popup = None
        
        # Reset cart
        logging.debug("Resetting cart")
        self._reset_cart()
        
        # Clean up any existing screens - be more careful about what we destroy
        for widget in self.root.winfo_children():
            # Only destroy widgets that belong to CartMode, preserve system widgets
            if hasattr(widget, 'winfo_class') and widget.winfo_class() in ['Frame', 'Label', 'Button']:
                try:
                    widget.destroy()
                except:
                    pass  # Ignore errors during cleanup
        
        # Call the exit callback to return to idle mode
        if hasattr(self, 'on_exit') and callable(self.on_exit):
            logging.info("Transaction complete, calling exit callback to return to idle mode")
            self.on_exit()
        else:
            logging.warning("No exit callback found, cannot return to idle mode")



    def _generate_transaction_id(self):
        """Generate a unique transaction ID in format YYDDD###."""
        try:
            from datetime import datetime
            
            # Get current date components
            now = datetime.now()
            year_last_two = int(now.strftime("%y"))  # Convert to int first
            day_of_year = int(now.strftime("%j"))    # Convert to int first
            
            # Get the current transaction count for today
            transaction_count_file = Path.home() / "SelfCheck" / "Logs" / f"transaction_count_{year_last_two:02d}{day_of_year:03d}.txt"
            
            # Create directory if it doesn't exist
            transaction_count_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Get current count or start at 0
            current_count = 0
            if transaction_count_file.exists():
                try:
                    with open(transaction_count_file, 'r') as f:
                        current_count = int(f.read().strip())
                except (ValueError, IOError) as e:
                    logging.error(f"Error reading transaction count: {e}")
            
            # Increment count
            new_count = current_count + 1
            
            # Save new count
            try:
                with open(transaction_count_file, 'w') as f:
                    f.write(str(new_count))
            except IOError as e:
                logging.error(f"Error saving transaction count: {e}")
            
            # Format transaction ID: YYDDD### (e.g., 25236001)
            transaction_id = f"{year_last_two:02d}{day_of_year:03d}{new_count:03d}"
            
            logging.info(f"Generated transaction ID: {transaction_id}")
            return transaction_id
            
        except Exception as e:
            logging.error(f"Error generating transaction ID: {e}")
            # Fallback to a simple timestamp-based ID
            fallback_id = f"T{int(time.time())}"
            logging.info(f"Using fallback transaction ID: {fallback_id}")
            return fallback_id




    def _reset_cart(self):
        """Reset the cart and related variables."""
        # Clear cart items
        self.cart_items = {}
        
        # Generate a new transaction ID
        self.transaction_id = self._generate_transaction_id()
        logging.info(f"New transaction ID generated: {self.transaction_id}")
        
        # Reset payment method
        self.current_payment_method = None
        
        logging.info("Cart reset")



    def _show_transaction_id_entry(self):
        """Show transaction ID entry popup with number pad."""
        # Close any existing transaction ID entry popup
        if hasattr(self, 'transaction_id_popup') and self.transaction_id_popup:
            self.transaction_id_popup.destroy()
        
        # Create transaction ID entry popup
        self.transaction_id_popup = tk.Frame(self.root, bg="white", bd=3, relief=tk.RAISED)
        self.transaction_id_popup.place(relx=0.5, rely=0.5, width=500, height=600, anchor=tk.CENTER)
        
        # Title
        title_label = tk.Label(self.transaction_id_popup, 
                             text="Enter last 4 digits of Venmo Transaction ID", 
                             font=("Arial", 18, "bold"), 
                             bg="white",
                             wraplength=450)
        title_label.pack(pady=(20, 10))
        
        # Entry field
        self.transaction_id_var = tk.StringVar()
        entry_frame = tk.Frame(self.transaction_id_popup, bg="white")
        entry_frame.pack(pady=20)
        
        entry_field = tk.Entry(entry_frame, 
                             textvariable=self.transaction_id_var, 
                             font=("Arial", 24), 
                             width=6, 
                             justify=tk.CENTER)
        entry_field.pack(side=tk.LEFT, padx=10)
        entry_field.focus_set()  # Set focus to the entry field
        
        # Number pad frame
        numpad_frame = tk.Frame(self.transaction_id_popup, bg="white")
        numpad_frame.pack(pady=20)
        
        # Create number buttons
        buttons = [
            ['1', '2', '3'],
            ['4', '5', '6'],
            ['7', '8', '9'],
            ['Backspace', '0', 'Enter']
        ]
        
        for row_idx, row in enumerate(buttons):
            for col_idx, btn_text in enumerate(row):
                if btn_text == 'Backspace':
                    # Backspace button
                    btn = tk.Button(numpad_frame, 
                                  text=btn_text, 
                                  font=("Arial", 16), 
                                  bg="#e74c3c", fg="white",
                                  width=8, height=2,
                                  command=lambda: self._transaction_id_backspace())
                elif btn_text == 'Enter':
                    # Enter button
                    btn = tk.Button(numpad_frame, 
                                  text=btn_text, 
                                  font=("Arial", 16), 
                                  bg="#27ae60", fg="white",
                                  width=8, height=2,
                                  command=self._process_transaction_id)
                else:
                    # Number button
                    btn = tk.Button(numpad_frame, 
                                  text=btn_text, 
                                  font=("Arial", 20), 
                                  bg="#3498db", fg="white",
                                  width=4, height=2,
                                  command=lambda b=btn_text: self._transaction_id_add_digit(b))
                
                btn.grid(row=row_idx, column=col_idx, padx=5, pady=5)
        
        # Bind keyboard events
        self.root.bind("<Key>", self._transaction_id_key_press)
        
        # Start timeout - 60 seconds
        self.transaction_id_timeout = self.root.after(60000, self._transaction_id_timeout)
    
    def _transaction_id_add_digit(self, digit):
        """Add a digit to the transaction ID entry."""
        current = self.transaction_id_var.get()
        if len(current) < 4:  # Limit to 4 digits
            self.transaction_id_var.set(current + digit)
    
    def _transaction_id_backspace(self):
        """Remove the last digit from the transaction ID entry."""
        current = self.transaction_id_var.get()
        self.transaction_id_var.set(current[:-1])
    
    def _transaction_id_key_press(self, event):
        """Handle keyboard input for transaction ID entry."""
        if not hasattr(self, 'transaction_id_popup') or not self.transaction_id_popup:
            return
            
        if event.char.isdigit() and len(self.transaction_id_var.get()) < 4:
            # Add digit
            self.transaction_id_var.set(self.transaction_id_var.get() + event.char)
        elif event.keysym == 'BackSpace':
            # Backspace
            self.transaction_id_backspace()
        elif event.keysym == 'Return':
            # Enter
            self._process_transaction_id()
    
    def _transaction_id_timeout(self):
        """Handle timeout for transaction ID entry."""
        if hasattr(self, 'transaction_id_popup') and self.transaction_id_popup:
            self.transaction_id_popup.destroy()
            self.transaction_id_popup = None
            
        # Unbind keyboard events
        self.root.unbind("<Key>")
        self.root.bind("<Key>", self._on_key)  # Restore original key binding
        
        # Return to payment popup
        messagebox.showinfo("Timeout", "Transaction ID entry timed out.")
    

    def _process_transaction_id(self):
        """Process the entered transaction ID."""
        # Cancel timeout
        if hasattr(self, 'transaction_id_timeout') and self.transaction_id_timeout:
            self.root.after_cancel(self.transaction_id_timeout)
            self.transaction_id_timeout = None
        
        # Get entered ID
        entered_id = self.transaction_id_var.get().strip()
        
        # Log the entered ID
        logging.info(f"Transaction ID entered: {entered_id}")
        
        # Close transaction ID popup
        if hasattr(self, 'transaction_id_popup') and self.transaction_id_popup:
            self.transaction_id_popup.destroy()
            self.transaction_id_popup = None
        
        # Unbind keyboard events
        self.root.unbind("<Key>")
        self.root.bind("<Key>", self._on_key)  # Restore original key binding
        
        # Calculate the total for processing
        subtotal = sum(item["price"] * item["qty"] for item in self.cart_items.values())
        taxable_subtotal = sum(
            item["price"] * item["qty"] 
            for item in self.cart_items.values() if item["taxable"]
        )
        tax_amount = taxable_subtotal * (self.tax_rate / 100)
        total = subtotal + tax_amount
        
        # Store the payment method for receipt printing
        self.current_payment_method = "Venmo"
        
        # Log the transaction with the entered ID
        self._log_successful_transaction("Venmo", total, entered_id)
        
        # Show thank you popup
        self._show_thank_you_popup()

    def _show_thank_you_popup(self):
        """Show thank you popup with receipt options."""
        # Close any existing popups
        self._close_all_payment_popups()
        
        # Create thank you popup
        self.thank_you_popup = tk.Frame(self.root, bg="white", bd=3, relief=tk.RAISED)
        self.thank_you_popup.place(relx=0.5, rely=0.5, width=500, height=400, anchor=tk.CENTER)
        
        # Title
        title_label = tk.Label(self.thank_you_popup, 
                             text="Thank you for your payment", 
                             font=("Arial", 24, "bold"), 
                             bg="white")
        title_label.pack(pady=(40, 20))
        
        # Receipt text
        receipt_label = tk.Label(self.thank_you_popup, 
                               text="Would you like a receipt?", 
                               font=("Arial", 20), 
                               bg="white")
        receipt_label.pack(pady=(0, 40))
        
        # Button frame
        button_frame = tk.Frame(self.thank_you_popup, bg="white")
        button_frame.pack(pady=20, fill=tk.X, padx=40)
        
        # Print button - make it more prominent
        print_btn = tk.Button(button_frame, 
                            text="Print", 
                            font=("Arial", 18, "bold"), 
                            bg="#3498db", fg="white",
                            command=lambda: self._receipt_option_selected("print"),
                            width=8, height=2)
        print_btn.pack(side=tk.LEFT, padx=10, expand=True)
        
        # Email button
        email_btn = tk.Button(button_frame, 
                            text="Email", 
                            font=("Arial", 18), 
                            bg="#2ecc71", fg="white",
                            command=lambda: self._receipt_option_selected("email"),
                            width=8, height=2)
        email_btn.pack(side=tk.LEFT, padx=10, expand=True)
        
        # None button
        none_btn = tk.Button(button_frame, 
                           text="None", 
                           font=("Arial", 18), 
                           bg="#7f8c8d", fg="white",
                           command=self._thank_you_complete,
                           width=8, height=2)
        none_btn.pack(side=tk.LEFT, padx=10, expand=True)
        
        # Start timeout - 20 seconds
        self.thank_you_timeout = self.root.after(20000, self._thank_you_timeout)


    def _receipt_option_selected(self, option):
        """Handle receipt option selection."""
        logging.info(f"Receipt option selected: {option}")
        
        if option == "print":
            # Calculate the total
            subtotal = sum(item["price"] * item["qty"] for item in self.cart_items.values())
            taxable_subtotal = sum(
                item["price"] * item["qty"] 
                for item in self.cart_items.values() if item["taxable"]
            )
            tax_amount = taxable_subtotal * (self.tax_rate / 100)
            total = subtotal + tax_amount
            
            # Get payment method (default to "Unknown" if not set)
            payment_method = getattr(self, 'current_payment_method', "Unknown")
            
            # Try to print receipt
            success = self.print_receipt(payment_method, total)
            
            if success:
                messagebox.showinfo("Receipt", "Receipt printed successfully.")
            else:
                # If printing fails, show a text-based receipt
                response = messagebox.askquestion("Printer Error", 
                                               "Failed to print receipt. Would you like to view it on screen instead?")
                if response == 'yes':
                    self._show_text_receipt(payment_method, total)
        
        elif option == "email":
            # Future implementation
            messagebox.showinfo("Receipt", "Email receipt option selected.\nThis feature will be implemented soon.")
        
        # Always complete the thank you process and return to idle mode
        self._thank_you_complete()
    
 
    def _verify_venmo_transaction(self, scanned_code):
        """Verify the scanned Venmo transaction code."""
        if not hasattr(self, 'expected_transaction_id'):
            logging.error("No expected transaction ID found")
            self.verification_label.config(text="Error: No transaction to verify", fg="#e74c3c")  # Red
            return
        
        # Clean up the scanned code - extract just the transaction ID if needed
        # This might need adjustment based on what exactly gets scanned from the phone
        # For now, we'll just check if the expected ID is contained in the scanned code
        if self.expected_transaction_id in scanned_code:
            logging.info(f"Venmo payment verified! Transaction ID: {self.expected_transaction_id}")
            self.verification_label.config(text="Payment Verified! Processing...", fg="#27ae60")  # Green
            
            # Calculate the total for logging
            subtotal = sum(item["price"] * item["qty"] for item in self.cart_items.values())
            taxable_subtotal = sum(
                item["price"] * item["qty"] 
                for item in self.cart_items.values() if item["taxable"]
            )
            tax_amount = taxable_subtotal * (self.tax_rate / 100)
            total = subtotal + tax_amount
            
            # Process successful payment after a short delay
            self.root.after(2000, lambda: self._process_successful_payment("Venmo", total))
        else:
            logging.warning(f"Venmo verification failed. Expected: {self.expected_transaction_id}, Got: {scanned_code}")
            self.verification_label.config(text="Verification Failed - Try Again", fg="#e74c3c")  # Red

    def _process_successful_payment(self, method, total):
        """Process a successful payment."""
        from tkinter import messagebox
        
        # Close all payment popups
        self._close_all_payment_popups()
        
        # Disable Venmo verification mode
        # self._disable_venmo_verification()
        
        # Show success message
        messagebox.showinfo("Payment Successful", 
                          f"${total:.2f} payment with {method} was successful.\n\n" +
                          "Thank you for your purchase!")
        
        # Log the successful transaction
        self._log_successful_transaction(method, total)
        
        # Clear the cart and return to idle mode
        self.cart_items = {}
        if hasattr(self, "on_exit"):
            self.on_exit()


    def _test_qr_generation(self):
        """Test QR code generation without UI."""
        try:
            import qrcode
            from PIL import Image
            
            # Create a simple QR code
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=10,
                border=4,
            )
            qr.add_data("https://example.com")
            qr.make(fit=True)
            
            # Create an image
            img = qr.make_image(fill_color="black", back_color="white")
            
            # Save to a file for inspection
            test_path = Path.home() / "SelfCheck" / "Logs" / "test_qr.png"
            img.save(test_path)
            
            logging.info(f"Test QR code saved to {test_path}")
            return True
        except Exception as e:
            logging.error(f"QR test failed: {e}")
            import traceback
            logging.error(traceback.format_exc())
            return False




    def _log_cancelled_cart(self, reason):
        """Log a cancelled cart to the Service tab."""
        try:
            # Use more comprehensive scopes
            scopes = [
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive",
            ]
            creds = Credentials.from_service_account_file(str(GS_CRED_PATH), scopes=scopes)
            gc = gspread.authorize(creds)
            
            # Open the spreadsheet and worksheet
            sheet = gc.open(GS_SHEET_NAME).worksheet("Service")
            
            # Calculate cart value for logging
            subtotal = sum(item["price"] * item["qty"] for item in self.cart_items.values())
            
            # Prepare row data
            timestamp = datetime.now().strftime("%m/%d/%Y %H:%M:%S")
            user = self.machine_id
            action = f"Cart Cancelled - {reason} - ${subtotal:.2f} - {len(self.cart_items)} items"
            
            # Create row with the correct format
            row = [timestamp, user, action]
            
            # Log locally first
            logging.info(f"Logging cancelled cart: {timestamp}, {user}, {action}")
            
            try:
                # Try to append to sheet
                sheet.append_row(row)
                logging.info(f"Successfully logged cancelled cart to Service tab")
            except Exception as api_error:
                logging.error(f"Error logging to Service tab: {api_error}")
                # Create a local log file as fallback
                log_dir = Path.home() / "SelfCheck" / "Logs"
                log_dir.mkdir(parents=True, exist_ok=True)
                log_file = log_dir / "transaction_log.csv"
                
                # Append to local log file
                with open(log_file, 'a') as f:
                    f.write(f"{timestamp},{user},{action}\n")
                logging.info(f"Logged cancelled cart to local file instead: {log_file}")
                
        except Exception as e:
            logging.error(f"Failed to log cancelled cart: {e}")
            import traceback
            logging.error(traceback.format_exc())


    def _load_upc_catalog(self):
        """Load UPC catalog from CSV file and update Tax.json from spreadsheet."""
        try:
            # Connect to Google Sheet to get latest data
            scopes = [
                "https://www.googleapis.com/auth/spreadsheets.readonly",
                "https://www.googleapis.com/auth/drive.readonly",
                "https://www.googleapis.com/auth/spreadsheets",
            ]
            creds = Credentials.from_service_account_file(str(GS_CRED_PATH), scopes=scopes)
            gc = gspread.authorize(creds)
            
            # First, update the tax rate from the spreadsheet
            try:
                sheet = gc.open(GS_SHEET_NAME).worksheet(GS_CRED_TAB)
                tax_rate_str = sheet.acell('B27').value
                
                # Parse tax rate (remove % sign if present)
                if tax_rate_str:
                    tax_rate_str = tax_rate_str.replace('%', '').strip()
                    tax_rate = float(tax_rate_str)
                    
                    # Update Tax.json file
                    tax_path = CRED_DIR / "Tax.json"
                    with open(tax_path, 'w') as f:
                        json.dump({"rate": tax_rate}, f)
                    logging.info(f"Updated Tax.json with rate {tax_rate}% from spreadsheet")
                    
                    # Update the instance variable
                    self.tax_rate = tax_rate
                else:
                    logging.warning("Tax rate not found in spreadsheet cell B27")
            except Exception as e:
                logging.error(f"Failed to update tax rate from spreadsheet: {e}")
            
            # Now load the UPC catalog
            catalog_path = CRED_DIR / "upc_catalog.csv"
            if not catalog_path.exists():
                logging.error(f"UPC catalog not found: {catalog_path}")
                return
            
            # Define column mappings (same as standalone script)
            headers = [
                "UPC", "Brand", "Name", "Size", "Calories", "Sugar", "Sodium",
                "Price", "Tax %", "QTY", "Image"
            ]
            
            import csv
            with open(catalog_path, 'r', newline='') as f:
                reader = csv.DictReader(f)
                
                # Process each row
                for row in reader:
                    upc = row["UPC"].strip()
                    if not upc:
                        continue
                    
                    # Convert row dict to list for compatibility with existing code
                    row_list = [
                        upc,                   # A: UPC
                        row["Brand"],          # B: Brand
                        row["Name"],           # C: Name
                        "",                    # D: (hidden column)
                        row["Size"],           # E: Size
                        row["Calories"],       # F: Calories
                        row["Sugar"],          # G: Sugar
                        row["Sodium"],         # H: Sodium
                        row["Price"],          # I: Price
                        row["Tax %"],          # J: Tax %
                        row["QTY"],            # K: QTY
                        row["Image"]           # L: Image
                    ]
                    
                    # Store the row list for this UPC
                    self.upc_catalog[upc] = row_list
                    
                    # Also store variants
                    for variant in upc_variants_from_sheet(upc):
                        if variant != upc:
                            self.upc_catalog[variant] = row_list
                
            logging.info(f"Loaded {len(self.upc_catalog)} UPC entries from catalog")
            
        except Exception as e:
            logging.error(f"Error loading UPC catalog: {e}")




    def check_spreadsheet_permissions(self):
        """Check and log permissions for the Google Sheet."""
        try:
            scopes = ["https://www.googleapis.com/auth/spreadsheets"]
            creds = Credentials.from_service_account_file(str(GS_CRED_PATH), scopes=scopes)
            gc = gspread.authorize(creds)
            
            # Get service account email
            service_account_info = json.loads(Path(GS_CRED_PATH).read_text())
            service_account_email = service_account_info.get('client_email', 'Unknown')
            
            logging.info(f"Service account email: {service_account_email}")
            
            # Try to open the sheet
            sheet = gc.open(GS_SHEET_NAME)
            
            # Get permissions
            permissions = sheet.list_permissions()
            
            # Log permissions
            for perm in permissions:
                role = perm.get('role', 'Unknown')
                email = perm.get('emailAddress', 'Unknown')
                perm_type = perm.get('type', 'Unknown')
                logging.info(f"Permission: {email} has {role} access (type: {perm_type})")
                
            # Check if service account has edit access
            service_account_has_access = False
            for perm in permissions:
                if perm.get('emailAddress') == service_account_email:
                    if perm.get('role') in ['writer', 'owner']:
                        service_account_has_access = True
                        break
            
            if service_account_has_access:
                logging.info("Service account has write access to the spreadsheet")
            else:
                logging.warning("Service account does NOT have write access to the spreadsheet")
                logging.warning(f"Please share the spreadsheet with {service_account_email} as an Editor")
                
            return service_account_has_access
            
        except Exception as e:
            logging.error(f"Error checking spreadsheet permissions: {e}")
            return False

    def _load_product_image(self, image_name, target_label, size=(225, 225)):
        """
        Load a product image from cache or Google Drive.
        
        Args:
            image_name: Name of the image file
            target_label: The tk.Label widget to display the image in
            size: Tuple of (width, height) for resizing
        """
        if not image_name:
            target_label.config(image="", text="No image available")
            return
            
        # Import necessary modules
        import io
        from googleapiclient.http import MediaIoBaseDownload
        
        # Store the image reference as an attribute of the label to prevent garbage collection
        if not hasattr(target_label, 'image_ref'):
            target_label.image_ref = None
        
        try:
            # Ensure cache directory exists
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            
            # Check local cache first
            image_path = self.cache_dir / image_name
            logging.info(f"Looking for image: {image_name} at path: {image_path}")
            
            if image_path.exists():
                logging.info(f"Loading image from cache: {image_path}")
                with Image.open(image_path) as img:
                    img = img.resize(size, Image.LANCZOS)
                    photo_image = ImageTk.PhotoImage(img)
                    target_label.image_ref = photo_image  # Prevent garbage collection
                    target_label.config(image=photo_image, text="")
                    return True
            
            # If not in cache, try to download from Google Drive
            if self.drive_service:
                logging.info(f"Searching for image in Google Drive: {image_name}")
                query = f"name = '{image_name}' and trashed = false"
                results = self.drive_service.files().list(
                    q=query, spaces='drive', fields='files(id, name)').execute()
                items = results.get('files', [])
                
                if items:
                    file_id = items[0]['id']
                    logging.info(f"Found image in Drive with ID: {file_id}")
                    
                    # Download file
                    request = self.drive_service.files().get_media(fileId=file_id)
                    fh = io.BytesIO()
                    downloader = MediaIoBaseDownload(fh, request)
                    done = False
                    while not done:
                        status, done = downloader.next_chunk()
                    
                    # Save to cache
                    fh.seek(0)
                    with open(image_path, 'wb') as f:
                        f.write(fh.read())
                    logging.info(f"Saved image to cache: {image_path}")
                    
                    # Display image
                    with Image.open(image_path) as img:
                        img = img.resize(size, Image.LANCZOS)
                        photo_image = ImageTk.PhotoImage(img)
                        target_label.image_ref = photo_image  # Prevent garbage collection
                        target_label.config(image=photo_image, text="")
                        return True
                else:
                    logging.warning(f"Image not found in Drive: {image_name}")
                    target_label.config(image="", text="Image not found in Drive")
                    return False
            else:
                logging.warning("Drive service not available")
                target_label.config(image="", text="Drive service not available")
                return False
        except Exception as e:
            logging.error(f"Error loading image {image_name}: {e}")
            import traceback
            logging.error(traceback.format_exc())
            target_label.config(image="", text=f"Error loading image")
            return False

    def _on_touch(self, event):
        # Touch handler for cart mode
        x, y = event.x, event.y
        logging.info(f"Touch in Cart mode at ({x}, {y})")
        self._on_activity()

    def _on_activity(self, event=None):
        # Reset inactivity timer
        self.last_activity_ts = time.time()
        
        # Cancel any existing timeout popup
        if self.timeout_popup:
            self._cancel_timeout_popup()

    def start(self):
        logging.info("CartMode: Starting")
        
        # Generate a new transaction ID
        self.transaction_id = self._generate_transaction_id()
        
        # Clear any existing cart data
        self.cart_items = {}
        
        # Clear barcode buffer
        self.barcode_buffer = ""
        
        # Reload tax rate from Tax.json to ensure it's current
        self._reload_tax_rate()
        
        # Create fresh UI
        self._create_ui()
        
        # Start timeout timer
        self._arm_timeout()

 

    def stop(self):
        logging.info("CartMode: Stopping")
        
        # Cancel timers
        if self.timeout_after:
            self.root.after_cancel(self.timeout_after)
            self.timeout_after = None
            
        if self.countdown_after:
            self.root.after_cancel(self.countdown_after)
            self.countdown_after = None
            
        # Hide all UI elements
        if self.label:
            self.label.place_forget()
            
        if self.receipt_frame:
            self.receipt_frame.place_forget()
            
        if self.totals_frame:
            self.totals_frame.place_forget()
            
        if self.popup_frame:
            self.popup_frame.destroy()
            self.popup_frame = None
            
        if self.manual_entry_frame:
            self.manual_entry_frame.destroy()
            self.manual_entry_frame = None
            
        if self.timeout_popup:
            self.timeout_popup.destroy()
            self.timeout_popup = None

    def _create_ui(self):
        """Create the cart UI elements."""
        # Show main background
        self.label.place(x=0, y=0, width=WINDOW_W, height=WINDOW_H)
        
        # Load background image
        self.base_bg = self._load_bg()
        self._render_base()
        
        # Create receipt area (left side, 2 inches down)
        self._create_receipt_area()
        
        # Create totals area (lower right)
        self._create_totals_area()
        
        # Create buttons (Cancel Order, Manual Entry, Pay Now)
        self._create_cancel_button()
        
        # Update UI with current cart items
        self._update_receipt()
        self._update_totals()

        # Reset activity timestamp to ensure full 45 seconds
        self.last_activity_ts = time.time()

    def _load_bg(self):
        """Load the cart background image."""
        bg_path = Path.home() / "SelfCheck" / "SysPics" / "Cart.png"
        if bg_path.exists():
            try:
                with Image.open(bg_path) as im:
                    if im.mode in ("RGBA", "P"):
                        im = im.convert("RGB")
                    # Full screen - no letterboxing
                    return im.resize((WINDOW_W, WINDOW_H), Image.LANCZOS)
            except Exception as e:
                logging.error(f"Error loading cart background: {e}")
        
        # Fallback to white background
        return Image.new("RGB", (WINDOW_W, WINDOW_H), (255, 255, 255))

    def _render_base(self):
        """Display the background image."""
        self.tk_img = ImageTk.PhotoImage(self.base_bg)
        self.label.configure(image=self.tk_img)
        self.label.lift()

    def _create_receipt_area(self):
        """Create the scrollable receipt area."""
        # Add "Tap Item for Edits" label above receipt area
        tap_label = tk.Label(self.root, text="Tap Item for Edits", 
                           font=("Arial", 14, "bold"), bg="#3498db", fg="white")
        tap_label.place(x=50, y=248, width=WINDOW_W//4, height=30)
        
        # Main frame for receipt area (left side, 2 inches down + 1 inch)
        # Original width=WINDOW_W//2, reducing by half makes it width=WINDOW_W//4
        self.receipt_frame = tk.Frame(self.root, bg="white", bd=2, relief=tk.GROOVE)
        self.receipt_frame.place(x=50, y=288, width=WINDOW_W//4, height=WINDOW_H-400)
        
        # Canvas for scrolling
        self.receipt_canvas = tk.Canvas(self.receipt_frame, bg="white", highlightthickness=0)
        self.receipt_scrollbar = tk.Scrollbar(self.receipt_frame, orient=tk.VERTICAL, 
                                            command=self.receipt_canvas.yview)
        self.receipt_canvas.configure(yscrollcommand=self.receipt_scrollbar.set)
        
        # Layout
        self.receipt_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.receipt_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # Frame to hold receipt items
        self.receipt_items_frame = tk.Frame(self.receipt_canvas, bg="white")
        self.receipt_canvas.create_window((0, 0), window=self.receipt_items_frame, anchor=tk.NW)
        
        # Configure canvas scrolling
        self.receipt_items_frame.bind("<Configure>", 
                                     lambda e: self.receipt_canvas.configure(
                                         scrollregion=self.receipt_canvas.bbox("all")))

    def _create_totals_area(self):
        """Create the totals display area."""
        # Frame for totals (lower right, raised by 1 inch and moved up more to make room for Pay Now button)
        # Original y=WINDOW_H-496, moving up by another 50 pixels makes it y=WINDOW_H-546
        self.totals_frame = tk.Frame(self.root, bg="white", bd=2, relief=tk.GROOVE)
        self.totals_frame.place(x=WINDOW_W//2 + 100, y=WINDOW_H-546, 
                          width=WINDOW_W//2 - 150, height=396)
        
        # Will be populated in _update_totals()

    def _create_cancel_button(self):
        """Create the cancel order button."""
        # Align with left side of totals frame and move up
        cancel_button = tk.Button(self.root, text="Cancel Order", font=("Arial", 20, "bold"),
                                bg="#e74c3c", fg="white", bd=2, relief=tk.RAISED,
                                command=self._cancel_order)
        cancel_button.place(x=WINDOW_W//2 + 100, y=WINDOW_H-596, width=200, height=50)
    
        # Add Manual Entry button above Cancel Order
        manual_entry_button = tk.Button(self.root, text="Manual Entry", font=("Arial", 20, "bold"),
                                      bg="#3498db", fg="white", bd=2, relief=tk.RAISED,
                                      command=self._show_manual_entry)
        manual_entry_button.place(x=WINDOW_W//2 + 100, y=WINDOW_H-646, width=200, height=50)
    
        # Add Pay Now button at the bottom
        pay_now_button = tk.Button(self.root, text="Pay Now", font=("Arial", 24, "bold"),
                                 bg="#27ae60", fg="white", bd=2, relief=tk.RAISED,
                                 command=self._pay_now)
        pay_now_button.place(x=WINDOW_W//2 + 100, y=WINDOW_H-150, width=WINDOW_W//2 - 150, height=70)

    def generate_transaction_id(self):
        """Generate a unique transaction ID in format YYDDD###."""
        try:
            from datetime import datetime
            
            # Get current date components
            now = datetime.now()
            year_last_two = now.strftime("%y")  # Last two digits of year (e.g., "25" for 2025)
            day_of_year = now.strftime("%j")    # Day of year as 3 digits (e.g., "236" for Aug 24)
            
            # Get the current transaction count for today
            transaction_count_file = Path.home() / "SelfCheck" / "Logs" / f"transaction_count_{year_last_two}{day_of_year}.txt"
            
            # Create directory if it doesn't exist
            transaction_count_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Get current count or start at 0
            current_count = 0
            if transaction_count_file.exists():
                try:
                    with open(transaction_count_file, 'r') as f:
                        current_count = int(f.read().strip())
                except (ValueError, IOError) as e:
                    logging.error(f"Error reading transaction count: {e}")
            
            # Increment count
            new_count = current_count + 1
            
            # Save new count
            try:
                with open(transaction_count_file, 'w') as f:
                    f.write(str(new_count))
            except IOError as e:
                logging.error(f"Error saving transaction count: {e}")
            
            # Format transaction ID: YYDDD### (e.g., 25236001)
            transaction_id = f"{year_last_two}{day_of_year:03d}{new_count:03d}"
            
            logging.info(f"Generated transaction ID: {transaction_id}")
            return transaction_id
            
        except Exception as e:
            logging.error(f"Error generating transaction ID: {e}")
            # Fallback to a simple timestamp-based ID
            import time
            simple_id = f"T{int(time.time())}"
            logging.info(f"Using fallback transaction ID: {simple_id}")
            return simple_id


    def scan_item(self, upc):
        """Process a scanned item and add to cart."""
        logging.info(f"Cart: Scanning item {upc}")
        self._on_activity()
        
        # Check if we've reached the maximum number of different items
        if len(self.cart_items) >= 15 and upc not in self.cart_items:
            self._show_error("Maximum number of different items reached (15)")
            return False
            
        # Look up UPC in catalog
        row = self.upc_catalog.get(upc)
        if not row:
            # Try variants
            for variant in upc_variants_from_scan(upc):
                row = self.upc_catalog.get(variant)
                if row:
                    break
                    
        if not row:
            self._show_error(f"Item not found: {upc}")
            return False
            
        # Check if item is already in cart
        if upc in self.cart_items:
            # Check if we've reached the maximum quantity for this item
            if self.cart_items[upc]["qty"] >= 10:
                self._show_error(f"Maximum quantity reached for this item (10)")
                return False
                
            # Increment quantity
            self.cart_items[upc]["qty"] += 1
        else:
            # Add new item to cart
            try:
                # Extract relevant data from row
                name = f"{row[1]} {row[2]} {row[4]}"  # Brand (B=1), Name (C=2), Size (E=4)
                price = float(row[8].replace('$', '').strip())  # Price (I=8)
                taxable = row[9].strip().lower() == 'yes'  # Taxable (J=9)
                image = row[11] if len(row) > 11 else ""  # Image (L=11)
                
                self.cart_items[upc] = {
                    "name": name,
                    "price": price,
                    "taxable": taxable,
                    "image": image,
                    "qty": 1,
                    "row": row
                }
            except (IndexError, ValueError) as e:
                logging.error(f"Error processing item data: {e}")
                self._show_error(f"Error processing item data")
                return False
                
        # Update UI
        self._update_receipt()
        self._update_totals()
        return True

    def _update_receipt(self):
        """Update the receipt display with current cart items."""
        if not hasattr(self, 'receipt_items_frame') or not self.receipt_items_frame:
            return
        
        # Clear existing items
        for widget in self.receipt_items_frame.winfo_children():
            widget.destroy()
        
        if not self.cart_items:
            # Show empty cart message
            empty_label = tk.Label(self.receipt_items_frame, 
                                  text="Cart is empty\nScan items to begin", 
                                  font=("Arial", 14), bg="white", fg="gray")
            empty_label.pack(pady=20)
            return
        
        # Add items to receipt
        for upc, item in self.cart_items.items():
            item_frame = tk.Frame(self.receipt_items_frame, bg="white", bd=1, relief=tk.SOLID)
            item_frame.pack(fill=tk.X, padx=5, pady=2)
            
            # Make item frame clickable for editing
            item_frame.bind("<Button-1>", lambda e, u=upc: self._edit_item(u))
            
            # Item name (truncate if too long)
            name = item["name"]
            if len(name) > 20:
                name = name[:17] + "..."
            
            name_label = tk.Label(item_frame, text=name, font=("Arial", 12, "bold"), 
                                 bg="white", anchor="w")
            name_label.pack(fill=tk.X, padx=5, pady=2)
            name_label.bind("<Button-1>", lambda e, u=upc: self._edit_item(u))
            
            # Price and quantity info
            info_text = f"${item['price']:.2f} x {item['qty']} = ${item['price'] * item['qty']:.2f}"
            info_label = tk.Label(item_frame, text=info_text, font=("Arial", 10), 
                                 bg="white", anchor="w")
            info_label.pack(fill=tk.X, padx=5, pady=(0, 2))
            info_label.bind("<Button-1>", lambda e, u=upc: self._edit_item(u))
        
        # Update scroll region
        self.receipt_items_frame.update_idletasks()
        self.receipt_canvas.configure(scrollregion=self.receipt_canvas.bbox("all"))


    def _edit_item(self, upc):
        """Show edit options for an item."""
        if upc not in self.cart_items:
            return
        
        item = self.cart_items[upc]
        
        # Create edit popup
        edit_popup = tk.Toplevel(self.root)
        edit_popup.title("Edit Item")
        edit_popup.geometry("300x200")
        edit_popup.configure(bg="white")
        
        # Center the popup
        edit_popup.transient(self.root)
        edit_popup.grab_set()
        
        # Item name
        name_label = tk.Label(edit_popup, text=item["name"], 
                             font=("Arial", 14, "bold"), bg="white")
        name_label.pack(pady=10)
        
        # Quantity controls
        qty_frame = tk.Frame(edit_popup, bg="white")
        qty_frame.pack(pady=10)
        
        tk.Label(qty_frame, text="Quantity:", font=("Arial", 12), bg="white").pack(side=tk.LEFT)
        
        minus_btn = tk.Button(qty_frame, text="-", font=("Arial", 14), 
                             command=lambda: self._change_quantity(upc, -1, edit_popup))
        minus_btn.pack(side=tk.LEFT, padx=5)
        
        qty_var = tk.StringVar(value=str(item["qty"]))
        qty_label = tk.Label(qty_frame, textvariable=qty_var, font=("Arial", 14), bg="white")
        qty_label.pack(side=tk.LEFT, padx=10)
        
        plus_btn = tk.Button(qty_frame, text="+", font=("Arial", 14), 
                            command=lambda: self._change_quantity(upc, 1, edit_popup))
        plus_btn.pack(side=tk.LEFT, padx=5)
        
        # Remove button
        remove_btn = tk.Button(edit_popup, text="Remove Item", font=("Arial", 12), 
                              bg="#e74c3c", fg="white",
                              command=lambda: self._remove_item_from_edit(upc, edit_popup))
        remove_btn.pack(pady=10)
        
        # Close button
        close_btn = tk.Button(edit_popup, text="Close", font=("Arial", 12), 
                             command=edit_popup.destroy)
        close_btn.pack(pady=5)


    def _change_quantity(self, upc, change, popup):
        """Change the quantity of an item."""
        if upc in self.cart_items:
            new_qty = self.cart_items[upc]["qty"] + change
            if new_qty <= 0:
                del self.cart_items[upc]
                popup.destroy()
            else:
                self.cart_items[upc]["qty"] = new_qty
            
            self._update_receipt()
            self._update_totals()

    def _remove_item_from_edit(self, upc, popup):
        """Remove an item from the cart."""
        if upc in self.cart_items:
            del self.cart_items[upc]
            popup.destroy()
            self._update_receipt()
            self._update_totals()


    def update_totals_display(self, subtotal, tax, total):
        """Update the totals section of the display."""
        logging.debug("Updating totals display")
        
        # If totals frame doesn't exist yet, create it
        if not hasattr(self, 'totals_frame'):
            logging.warning("Totals frame doesn't exist, can't update display")
            return
        
        # Clear existing widgets
        for widget in self.totals_frame.winfo_children():
            widget.destroy()
        
        # Transaction ID
        trans_frame = tk.Frame(self.totals_frame, bg="white")
        trans_frame.pack(fill=tk.X, padx=10, pady=5)
        
        tk.Label(trans_frame, text="Transaction ID:", font=("Arial", 12), 
               bg="white", anchor="w").pack(side=tk.LEFT)
        
        # Display transaction ID if it exists
        trans_id = getattr(self, 'transaction_id', 'Unknown')
        tk.Label(trans_frame, text=trans_id, font=("Arial", 12), 
               bg="white", anchor="e").pack(side=tk.RIGHT)
        
        # Subtotal
        subtotal_frame = tk.Frame(self.totals_frame, bg="white")
        subtotal_frame.pack(fill=tk.X, padx=10, pady=5)
        
        tk.Label(subtotal_frame, text="Subtotal:", font=("Arial", 12), 
               bg="white", anchor="w").pack(side=tk.LEFT)
        tk.Label(subtotal_frame, text=f"${subtotal:.2f}", font=("Arial", 12), 
               bg="white", anchor="e").pack(side=tk.RIGHT)
        
        # Tax
        tax_frame = tk.Frame(self.totals_frame, bg="white")
        tax_frame.pack(fill=tk.X, padx=10, pady=5)
        
        tk.Label(tax_frame, text=f"Tax ({self.tax_rate}%):", font=("Arial", 12), 
               bg="white", anchor="w").pack(side=tk.LEFT)
        tk.Label(tax_frame, text=f"${tax:.2f}", font=("Arial", 12), 
               bg="white", anchor="e").pack(side=tk.RIGHT)
        
        # Total
        total_frame = tk.Frame(self.totals_frame, bg="white")
        total_frame.pack(fill=tk.X, padx=10, pady=5)
        
        tk.Label(total_frame, text="Total:", font=("Arial", 14, "bold"), 
               bg="white", anchor="w").pack(side=tk.LEFT)
        tk.Label(total_frame, text=f"${total:.2f}", font=("Arial", 14, "bold"), 
               bg="white", anchor="e").pack(side=tk.RIGHT)
        
        # Update checkout button state
        if hasattr(self, 'checkout_btn'):
            if self.cart_items:
                self.checkout_btn.config(state=tk.NORMAL)
            else:
                self.checkout_btn.config(state=tk.DISABLED)



    def _show_manual_entry(self):
        """Show manual entry popup with numeric keypad."""
        # Reset activity timestamp to prevent timeout during manual entry
        self._on_activity()
        
        # Create popup frame - now using full screen height but reduced width
        popup_width = int(WINDOW_W * 0.6)  # 60% of screen width
        self.manual_entry_frame = tk.Frame(self.root, bg="white", bd=3, relief=tk.RAISED)
        self.manual_entry_frame.place(relx=0.5, rely=0.5, width=popup_width, height=WINDOW_H-50, anchor=tk.CENTER)
        
        # Use a main container with grid layout for better control
        main_container = tk.Frame(self.manual_entry_frame, bg="white")
        main_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        main_container.grid_columnconfigure(0, weight=1)
        
        # Define row weights - this is crucial for proper layout
        main_container.grid_rowconfigure(0, weight=0)  # Title - fixed size
        main_container.grid_rowconfigure(1, weight=0)  # Entry field - fixed size
        main_container.grid_rowconfigure(2, weight=1)  # Item display - expandable
        main_container.grid_rowconfigure(3, weight=2)  # Keypad - expandable, more space
        main_container.grid_rowconfigure(4, weight=0)  # Enter/Cancel buttons - fixed size
        main_container.grid_rowconfigure(5, weight=0)  # Action buttons - fixed size
        
        # Title
        title_label = tk.Label(main_container, text="Manual Entry", 
                             font=("Arial", 24, "bold"), bg="white")
        title_label.grid(row=0, column=0, pady=(10, 10), sticky="ew")
        
        # Entry field for UPC/PLU
        entry_frame = tk.Frame(main_container, bg="white")
        entry_frame.grid(row=1, column=0, pady=(5, 10), sticky="ew")
        entry_frame.columnconfigure(1, weight=1)
        
        entry_label = tk.Label(entry_frame, text="Enter UPC/PLU:", font=("Arial", 18), bg="white")
        entry_label.grid(row=0, column=0, padx=10)
        
        self.manual_entry_var = tk.StringVar()
        entry_field = tk.Entry(entry_frame, textvariable=self.manual_entry_var, 
                             font=("Arial", 24), width=20, justify=tk.RIGHT)
        entry_field.grid(row=0, column=1, padx=10, sticky="ew")
        
        # Item display area - will be populated when an item is found
        self.item_display_frame = tk.Frame(main_container, bg="white", bd=1, relief=tk.GROOVE)
        self.item_display_frame.grid(row=2, column=0, pady=10, sticky="nsew")
        
        # Initially show a placeholder
        placeholder_label = tk.Label(self.item_display_frame, text="Enter a UPC and press Enter to search", 
                                   font=("Arial", 14), bg="white", fg="#888888")
        placeholder_label.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # These will be created when an item is found
        self.item_name_label = None
        self.item_details_label = None
        self.item_image_label = None
        self.manual_qty_var = tk.IntVar(value=1)
        
        # Numeric keypad - smaller buttons
        keypad_frame = tk.Frame(main_container, bg="#f0f0f0")
        keypad_frame.grid(row=3, column=0, pady=10, sticky="nsew")
        
        # Configure keypad grid
        for i in range(4):  # 4 rows
            keypad_frame.grid_rowconfigure(i, weight=1)
        for i in range(3):  # 3 columns
            keypad_frame.grid_columnconfigure(i, weight=1)
        
        # Create keypad buttons with backspace
        keys = [
            ['7', '8', '9'],
            ['4', '5', '6'],
            ['1', '2', '3'],
            ['0', 'Clear', 'Backspace']
        ]
        
        # Function to handle backspace
        def backspace():
            current = self.manual_entry_var.get()
            self.manual_entry_var.set(current[:-1])
        
        # Calculate button size - make them half the previous size
        button_width = int(popup_width * 0.15)  # 15% of popup width
        button_height = int((WINDOW_H-50) * 0.06)  # 6% of popup height
        
        for row_idx, row in enumerate(keys):
            for col_idx, key in enumerate(row):
                # Determine button color and command
                if key == 'Clear':
                    bg_color = "#e74c3c"  # Red
                    command = lambda: self.manual_entry_var.set("")
                elif key == 'Backspace':
                    bg_color = "#f39c12"  # Orange
                    command = backspace
                else:
                    bg_color = "#3498db"  # Blue
                    command = lambda k=key: self.manual_entry_var.set(self.manual_entry_var.get() + k)
                
                # Create button with smaller size
                btn = tk.Button(keypad_frame, text=key, font=("Arial", 14, "bold"),
                              bg=bg_color, fg="white", command=command,
                              width=5, height=1)  # Fixed size for smaller buttons
                btn.grid(row=row_idx, column=col_idx, sticky="nsew", padx=10, pady=10)
        
        # Enter and Cancel buttons
        button_frame = tk.Frame(main_container, bg="#f0f0f0", height=60)
        button_frame.grid(row=4, column=0, pady=5, sticky="ew")
        button_frame.grid_columnconfigure(0, weight=1)
        button_frame.grid_columnconfigure(1, weight=1)
        
        # Cancel button
        cancel_btn = tk.Button(button_frame, text="Cancel", font=("Arial", 16, "bold"),
                             bg="#e74c3c", fg="white", command=self._close_manual_entry)
        cancel_btn.grid(row=0, column=0, padx=5, pady=5, sticky="nsew")
        
        # Enter button
        enter_btn = tk.Button(button_frame, text="Enter", font=("Arial", 16, "bold"),
                            bg="#27ae60", fg="white", command=self._manual_entry_lookup)
        enter_btn.grid(row=0, column=1, padx=5, pady=5, sticky="nsew")
        
        # Action buttons frame (initially empty, will be populated when item is found)
        self.action_buttons_frame = tk.Frame(main_container, bg="#f0f0f0", height=60)
        self.action_buttons_frame.grid(row=5, column=0, pady=5, sticky="ew")
        self.action_buttons_frame.grid_columnconfigure(0, weight=1)
        self.action_buttons_frame.grid_columnconfigure(1, weight=1)
        
        # Hide action buttons initially
        self.action_buttons_frame.grid_remove()
        
        # Set focus to entry field
        entry_field.focus_set()
        
        # Bind Enter key to lookup
        entry_field.bind("<Return>", lambda e: self._manual_entry_lookup())
        
        # Store reference to main container for later use
        self.manual_entry_container = main_container

    def _manual_entry_lookup(self):
        """Look up the entered UPC/PLU."""
        upc = self.manual_entry_var.get().strip()
        logging.info(f"Manual entry lookup for UPC: {upc}")
        
        if not upc:
            logging.warning("Empty UPC entered")
            return
            
        # Look up UPC in catalog
        row = self.upc_catalog.get(upc)
        if not row:
            logging.info(f"UPC {upc} not found directly, trying variants")
            # Try variants
            for variant in upc_variants_from_scan(upc):
                row = self.upc_catalog.get(variant)
                if row:
                    upc = variant  # Use the matched variant
                    logging.info(f"Found variant: {variant}")
                    break
                    
        if not row:
            logging.warning(f"Item not found: {upc}")
            messagebox.showerror("Error", f"Item not found: {upc}")
            return
            
        # Log the row data for debugging
        logging.info(f"Found row data: {row}")
        
        # Extract item data
        try:
            name = f"{row[1]} {row[2]} {row[4]}"  # Brand (B=1), Name (C=2), Size (E=4)
            price = float(row[8].replace('$', '').strip())  # Price (I=8)
            taxable = row[9].strip().lower() == 'yes'  # Taxable (J=9)
            image_name = row[11] if len(row) > 11 else ""  # Image (L=11)
            
            # Debug log
            logging.info(f"Found item: {name}, Price: ${price}, Taxable: {taxable}, Image: {image_name}")
            
            # Display the item
            self._display_manual_item(name, price, taxable, image_name, upc)
            
        except Exception as e:
            logging.error(f"Error processing item data: {e}")
            import traceback
            logging.error(traceback.format_exc())
            messagebox.showerror("Error", f"Error processing item data: {str(e)}")

    def _display_manual_item(self, name, price, taxable, image_name, upc):
        """Display item details in the manual entry popup."""
        # Log for debugging
        logging.info("Displaying manual item details")
        
        # Clear the item display frame
        for widget in self.item_display_frame.winfo_children():
            widget.destroy()
        
        # Create scrollable frame for item details
        canvas = tk.Canvas(self.item_display_frame, bg="white", highlightthickness=0)
        scrollbar = tk.Scrollbar(self.item_display_frame, orient=tk.VERTICAL, command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg="white")
        
        # Configure canvas
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Create window in canvas for scrollable frame
        canvas.create_window((0, 0), window=scrollable_frame, anchor=tk.NW)
        
        # Configure scrollable frame to update canvas scroll region
        def configure_scroll_region(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
            # Also set the width of the window to match the canvas width
            canvas.itemconfig(canvas_window, width=canvas.winfo_width())
            
        scrollable_frame.bind("<Configure>", configure_scroll_region)
        canvas_window = canvas.create_window((0, 0), window=scrollable_frame, anchor=tk.NW)
        
        # Item name
        self.item_name_label = tk.Label(scrollable_frame, text=name, 
                                      font=("Arial", 16, "bold"), bg="white", 
                                      wraplength=400, justify=tk.LEFT)
        self.item_name_label.pack(fill=tk.X, padx=10, pady=(10, 5))
        
        # Item details
        self.item_details_label = tk.Label(scrollable_frame, 
                                         text=f"Price: ${price:.2f}  Taxable: {'Yes' if taxable else 'No'}", 
                                         font=("Arial", 14), bg="white")
        self.item_details_label.pack(fill=tk.X, padx=10, pady=5)
        
        # Quantity control - moved above the image as requested
        qty_frame = tk.Frame(scrollable_frame, bg="white")
        qty_frame.pack(pady=10)
        
        qty_label = tk.Label(qty_frame, text="QTY:", font=("Arial", 16), bg="white")
        qty_label.pack(side=tk.LEFT, padx=5)
        
        self.manual_qty_var.set(1)  # Reset to 1
        qty_display = tk.Label(qty_frame, textvariable=self.manual_qty_var, 
                             font=("Arial", 16, "bold"), bg="white", width=2)
        qty_display.pack(side=tk.LEFT, padx=5)
        
        def decrease_qty():
            if self.manual_qty_var.get() > 1:
                self.manual_qty_var.set(self.manual_qty_var.get() - 1)
                
        def increase_qty():
            if self.manual_qty_var.get() < 10:
                self.manual_qty_var.set(self.manual_qty_var.get() + 1)
                
        down_btn = tk.Button(qty_frame, text="▼", font=("Arial", 16), command=decrease_qty)
        down_btn.pack(side=tk.LEFT, padx=5)
        
        up_btn = tk.Button(qty_frame, text="▲", font=("Arial", 16), command=increase_qty)
        up_btn.pack(side=tk.LEFT, padx=5)
        
        # Image display - now below the quantity controls
        self.item_image_label = tk.Label(scrollable_frame, bg="white")
        self.item_image_label.pack(pady=10)
        
        # Load image - reduced size to 75% of original (225x225 instead of 300x300)
        if image_name:
            self.item_image_label.config(text="Loading image...")
            self._load_product_image(image_name, self.item_image_label, size=(225, 225))
        else:
            self.item_image_label.config(text="No image available")
        
        # Clear action buttons frame
        for widget in self.action_buttons_frame.winfo_children():
            widget.destroy()
        
        # Create action buttons
        add_btn = tk.Button(self.action_buttons_frame, text="Add to Order", 
                          font=("Arial", 16, "bold"), bg="#27ae60", fg="white", 
                          command=self._manual_entry_add)
        add_btn.grid(row=0, column=0, padx=5, pady=5, sticky="nsew")
        
        cancel_btn = tk.Button(self.action_buttons_frame, text="Cancel", 
                             font=("Arial", 16, "bold"), bg="#e74c3c", fg="white", 
                             command=self._close_manual_entry)
        cancel_btn.grid(row=0, column=1, padx=5, pady=5, sticky="nsew")
        
        # Make action buttons visible
        self.action_buttons_frame.grid()
        
        # Store the current UPC for later use
        self.current_manual_upc = upc
        
        # Log for debugging
        logging.info("Action buttons created and displayed")

    def _manual_entry_add(self):
        """Add manually entered item to cart."""
        if not hasattr(self, 'current_manual_upc'):
            logging.warning("No current UPC to add to cart")
            return
            
        upc = self.current_manual_upc
        qty = self.manual_qty_var.get()
        
        logging.info(f"Adding item to cart: UPC={upc}, QTY={qty}")
        
        # Add to cart
        row = self.upc_catalog.get(upc)
        if not row:
            logging.warning(f"UPC {upc} not found in catalog")
            return
            
        # Check if we've reached the maximum number of different items
        if len(self.cart_items) >= 15 and upc not in self.cart_items:
            messagebox.showerror("Error", "Maximum number of different items reached (15)")
            return
            
        # Check if item is already in cart
        if upc in self.cart_items:
            # Check if adding would exceed the maximum quantity
            current_qty = self.cart_items[upc]["qty"]
            if current_qty + qty > 10:
                messagebox.showerror("Error", f"Maximum quantity reached for this item (10)")
                return
                
            # Update quantity
            self.cart_items[upc]["qty"] = current_qty + qty
            logging.info(f"Updated quantity for {upc} to {current_qty + qty}")
        else:
            # Add new item to cart
            try:
                # Extract relevant data from row
                name = f"{row[1]} {row[2]} {row[4]}"  # Brand (B=1), Name (C=2), Size (E=4)
                price = float(row[8].replace('$', '').strip())  # Price (I=8)
                taxable = row[9].strip().lower() == 'yes'  # Taxable (J=9)
                image = row[11] if len(row) > 11 else ""  # Image (L=11)
                
                self.cart_items[upc] = {
                    "name": name,
                    "price": price,
                    "taxable": taxable,
                    "image": image,
                    "qty": qty,
                    "row": row
                }
                logging.info(f"Added new item to cart: {name}")
            except (IndexError, ValueError) as e:
                logging.error(f"Error processing item data: {e}")
                messagebox.showerror("Error", f"Error processing item data")
                return
                
        # Update UI
        self._update_receipt()
        self._update_totals()
        
        # Close manual entry popup
        self._close_manual_entry()
        
        # Show confirmation
        messagebox.showinfo("Success", "Item added to cart")

    def _close_manual_entry(self):
        """Close the manual entry popup."""
        if hasattr(self, 'manual_entry_frame') and self.manual_entry_frame:
            self.manual_entry_frame.destroy()
            self.manual_entry_frame = None
        
        # Reset activity timestamp
        self._on_activity()

    def _pay_now(self):
        """Handle Pay Now button click."""
        # Calculate the total for display
        subtotal = sum(item["price"] * item["qty"] for item in self.cart_items.values())
        taxable_subtotal = sum(
            item["price"] * item["qty"] 
            for item in self.cart_items.values() if item["taxable"]
        )
        tax_amount = taxable_subtotal * (self.tax_rate / 100)
        total = subtotal + tax_amount
        
        # Create payment popup
        self._show_payment_popup(total)

    def _pay_now(self):
        """Handle Pay Now button click."""
        # First, ensure any existing payment popups are destroyed
        self._close_all_payment_popups()
        
        # Calculate the total for display
        subtotal = sum(item["price"] * item["qty"] for item in self.cart_items.values())
        taxable_subtotal = sum(
            item["price"] * item["qty"] 
            for item in self.cart_items.values() if item["taxable"]
        )
        tax_amount = taxable_subtotal * (self.tax_rate / 100)
        total = subtotal + tax_amount
        
        # Create payment popup
        self._show_payment_popup(total)

    def _close_all_payment_popups(self):
        """Close all payment-related popups."""
        # Log what we're doing
        logging.info("Closing all payment popups")
        
        # Cancel all payment-related timers
        for timer_attr in ['payment_timeout', 'payment_countdown_after', 
                          'transaction_id_timeout', 'thank_you_timeout']:
            if hasattr(self, timer_attr) and getattr(self, timer_attr):
                try:
                    self.root.after_cancel(getattr(self, timer_attr))
                    setattr(self, timer_attr, None)
                    logging.info(f"Cancelled timer: {timer_attr}")
                except Exception as e:
                    logging.error(f"Error cancelling timer {timer_attr}: {e}")
        
        # Destroy all payment-related popups
        for popup_attr in ['payment_popup', 'payment_timeout_popup', 
                          'transaction_id_popup', 'thank_you_popup']:
            if hasattr(self, popup_attr) and getattr(self, popup_attr):
                try:
                    getattr(self, popup_attr).destroy()
                    setattr(self, popup_attr, None)
                    logging.info(f"Destroyed popup: {popup_attr}")
                except Exception as e:
                    logging.error(f"Error destroying popup {popup_attr}: {e}")
        
        # Reset activity timestamp
        self._on_activity()
        
        # Restore original key binding
        self.root.unbind("<Key>")
        self.root.bind("<Key>", self._on_key)


    def _show_payment_popup(self, total):
        """Show payment options popup."""
        # Cancel any existing timeout
        self._on_activity()
    
        # Debug: Check if payment popup already exists
        if hasattr(self, 'payment_popup') and self.payment_popup:
            logging.info("Payment popup already exists - destroying it first")
            self.payment_popup.destroy()
        
        # Create popup frame - ensure we're starting fresh
        self.payment_popup = tk.Frame(self.root, bg="white", bd=3, relief=tk.RAISED)
        self.payment_popup.place(relx=0.5, rely=0.5, width=600, height=500, anchor=tk.CENTER)
    
        # Display total at the top
        total_label = tk.Label(self.payment_popup, 
                             text=f"Total: ${total:.2f}", 
                             font=("Arial", 24, "bold"), 
                             bg="white")
        total_label.pack(pady=(30, 20))
    
        # Load payment method images
        payment_images_dir = Path.home() / "SelfCheck" / "SysPics"
    
        # Stripe button
        stripe_path = payment_images_dir / "stripe.png"
        if stripe_path.exists():
            try:
                with Image.open(stripe_path) as img:
                    # Resize to appropriate size
                    img = img.resize((400, 100), Image.LANCZOS)
                    stripe_img = ImageTk.PhotoImage(img)
                
                    # Create button with image
                    stripe_btn = tk.Button(self.payment_popup, 
                                         image=stripe_img, 
                                         command=lambda: self._process_payment("Stripe"),
                                         bd=0)
                    stripe_btn.image = stripe_img  # Keep reference to prevent garbage collection
                    stripe_btn.pack(pady=10)
            except Exception as e:
                logging.error(f"Error loading Stripe image: {e}")
                # Fallback to text button
                stripe_btn = tk.Button(self.payment_popup, 
                                     text="Pay with Stripe", 
                                     font=("Arial", 16), 
                                     command=lambda: self._process_payment("Stripe"),
                                     bg="#6772E5", fg="white",
                                     height=2, width=20)
                stripe_btn.pack(pady=10)
    
        # Frame for Venmo and Cash App buttons (side by side)
        mobile_frame = tk.Frame(self.payment_popup, bg="white")
        mobile_frame.pack(pady=10)
    
        # Venmo button
        venmo_path = payment_images_dir / "Venmo.png"
        if venmo_path.exists():
            try:
                with Image.open(venmo_path) as img:
                    # Resize to appropriate size
                    img = img.resize((200, 80), Image.LANCZOS)
                    venmo_img = ImageTk.PhotoImage(img)
                
                    # Create button with image
                    venmo_btn = tk.Button(mobile_frame, 
                                        image=venmo_img, 
                                        command=lambda: self._process_payment("Venmo"),
                                        bd=0)
                    venmo_btn.image = venmo_img  # Keep reference
                    venmo_btn.pack(side=tk.LEFT, padx=10)
            except Exception as e:
                logging.error(f"Error loading Venmo image: {e}")
                # Fallback to text button
                venmo_btn = tk.Button(mobile_frame, 
                                    text="Venmo", 
                                    font=("Arial", 16), 
                                    command=lambda: self._process_payment("Venmo"),
                                    bg="#3D95CE", fg="white",
                                    height=2, width=10)
                venmo_btn.pack(side=tk.LEFT, padx=10)
    
        # Cash App button
        cashapp_path = payment_images_dir / "cashapp.png"
        if cashapp_path.exists():
            try:
                with Image.open(cashapp_path) as img:
                    # Resize to same size as Venmo button
                    img = img.resize((200, 80), Image.LANCZOS)
                    cashapp_img = ImageTk.PhotoImage(img)
                
                    # Create button with image
                    cashapp_btn = tk.Button(mobile_frame, 
                                          image=cashapp_img, 
                                          command=lambda: self._process_payment("Cash App"),
                                          bd=0)
                    cashapp_btn.image = cashapp_img  # Keep reference
                    cashapp_btn.pack(side=tk.LEFT, padx=10)
            except Exception as e:
                logging.error(f"Error loading Cash App image: {e}")
                # Fallback to text button
                cashapp_btn = tk.Button(mobile_frame, 
                                      text="Cash App", 
                                      font=("Arial", 16), 
                                      command=lambda: self._process_payment("Cash App"),
                                      bg="#00D632", fg="white",
                                      height=2, width=10)
                cashapp_btn.pack(side=tk.LEFT, padx=10)
    
        # Button frame for Return and Cancel buttons
        button_frame = tk.Frame(self.payment_popup, bg="white")
        button_frame.pack(pady=(30, 20), fill=tk.X, padx=20)
    
        # Return to Cart button
        return_btn = tk.Button(button_frame, 
                             text="Return to Cart", 
                             font=("Arial", 16), 
                             command=self._close_payment_popup,
                             bg="#3498db", fg="white",
                             height=2)
        return_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)
    
        # Cancel Order button
        cancel_btn = tk.Button(button_frame, 
                             text="Cancel Order", 
                             font=("Arial", 16), 
                             command=self._cancel_from_payment,
                             bg="#e74c3c", fg="white",
                             height=2)
        cancel_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)
    
        # Start timeout for payment popup
        self._start_payment_timeout()
    
        # Debug: Log that we've created the payment popup
        logging.info("Payment popup created with all buttons")



    def _close_payment_popup(self):
        """Close the payment popup."""
        self._close_all_payment_popups()

    def _cancel_from_payment(self):
        """Cancel order from payment popup."""
        from tkinter import messagebox
        logging.info("Cancel from payment initiated")
    
        if messagebox.askyesno("Cancel Order", "Are you sure you want to cancel this order?"):
            logging.info("User confirmed order cancellation from payment popup")
            self._close_all_payment_popups()
            self._log_cancelled_cart("Customer")
            if hasattr(self, "on_exit"):
                self.on_exit()
        else:
            logging.info("User declined order cancellation from payment popup")


    def _process_payment(self, method):
        """Process payment with selected method."""
        # Calculate the total
        subtotal = sum(item["price"] * item["qty"] for item in self.cart_items.values())
        taxable_subtotal = sum(
            item["price"] * item["qty"] 
            for item in self.cart_items.values() if item["taxable"]
        )
        tax_amount = taxable_subtotal * (self.tax_rate / 100)
        total = subtotal + tax_amount
        
        # Log the payment attempt
        logging.info(f"Processing payment of ${total:.2f} with {method}")


        # Store the payment method for receipt printing
        self.current_payment_method = method
        
        if method == "Venmo":
            # Show QR code for Venmo payment
            self._show_venmo_qr_code(total)
        else:
            # For other payment methods (temporary)
            self._close_payment_popup()
            
            # Log the transaction
            self._log_successful_transaction(method, total)
            
            # Show thank you popup
            self._show_thank_you_popup()


        
    def _finish_payment(self, method, total):
        """Complete the payment process after simulated delay."""
        from tkinter import messagebox
        
        # Close the payment popup
        self._close_payment_popup()
        
        # Show success message
        messagebox.showinfo("Payment Successful", 
                          f"${total:.2f} payment with {method} was successful.\n\n" +
                          "Thank you for your purchase!")
        
        # Log the successful transaction
        self._log_successful_transaction(method, total)
        
        # Clear the cart and return to idle mode
        self.cart_items = {}
        if hasattr(self, "on_exit"):
            self.on_exit()
            
    def _log_successful_transaction(self, method, total, verification_code=None):
        """Log a successful transaction to the Service tab."""
        try:
            # Use more comprehensive scopes
            scopes = [
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive",
            ]
            creds = Credentials.from_service_account_file(str(GS_CRED_PATH), scopes=scopes)
            gc = gspread.authorize(creds)
            
            # Open the spreadsheet and worksheet
            sheet = gc.open(GS_SHEET_NAME).worksheet("Service")
            
            # Prepare row data
            timestamp = datetime.now().strftime("%m/%d/%Y %H:%M:%S")
            user = self.machine_id
            
            # Include verification code in the log if provided
            if verification_code:
                action = f"Payment - {method} - ${total:.2f} - Verification: {verification_code}"
            else:
                action = f"Payment - {method} - ${total:.2f}"
            
            # Create row with the correct format
            row = [timestamp, user, action]
            
            # Log locally first
            logging.info(f"Logging successful transaction: {timestamp}, {user}, {action}")
            
            try:
                # Try to append to sheet
                sheet.append_row(row)
                logging.info(f"Successfully logged transaction to Service tab")
            except Exception as api_error:
                logging.error(f"Error logging to Service tab: {api_error}")
                # Create a local log file as fallback
                log_dir = Path.home() / "SelfCheck" / "Logs"
                log_dir.mkdir(parents=True, exist_ok=True)
                log_file = log_dir / "transaction_log.csv"
                
                # Append to local log file
                with open(log_file, 'a') as f:
                    f.write(f"{timestamp},{user},{action}\n")
                logging.info(f"Logged transaction to local file instead: {log_file}")
                
        except Exception as e:
            logging.error(f"Failed to log transaction: {e}")
            import traceback
            logging.error(traceback.format_exc())



    def _start_payment_timeout(self, timeout_seconds=45):
        """Start timeout for payment popup."""
        self.payment_last_activity = time.time()
        self.payment_timeout = None
        self.payment_timeout_seconds = timeout_seconds
        
        def check_payment_timeout():
            if not hasattr(self, 'payment_popup') or not self.payment_popup:
                return
                
            current_time = time.time()
            elapsed = current_time - self.payment_last_activity
            
            if elapsed >= self.payment_timeout_seconds:
                self._show_payment_timeout_popup()
                return
                
            self.payment_timeout = self.root.after(1000, check_payment_timeout)
            
        self.payment_timeout = self.root.after(1000, check_payment_timeout)


    def _show_payment_timeout_popup(self):
        """Show timeout popup for payment screen."""
        if hasattr(self, 'payment_timeout_popup') and self.payment_timeout_popup:
            return
            
        # Create popup
        self.payment_timeout_popup = tk.Frame(self.root, bg="white", bd=3, relief=tk.RAISED)
        self.payment_timeout_popup.place(relx=0.5, rely=0.5, width=500, height=300, anchor=tk.CENTER)
        
        # Message
        message = tk.Label(self.payment_timeout_popup, text="Do you need more time?", 
                         font=("Arial", 24, "bold"), bg="white")
        message.pack(pady=(40, 20))
        
        # Countdown
        self.payment_countdown_value = 30
        self.payment_countdown_label = tk.Label(self.payment_timeout_popup, 
                                             text=f"Returning to main menu in {self.payment_countdown_value} seconds", 
                                             font=("Arial", 18), bg="white")
        self.payment_countdown_label.pack(pady=20)
        
        # Buttons
        btn_frame = tk.Frame(self.payment_timeout_popup, bg="white")
        btn_frame.pack(pady=20, fill=tk.X)
        
        # Yes button
        yes_btn = tk.Button(btn_frame, text="Yes", font=("Arial", 18), bg="#27ae60", fg="white",
                          command=self._cancel_payment_timeout_popup)
        yes_btn.pack(side=tk.LEFT, padx=20, pady=10, fill=tk.X, expand=True)
        
        # No button
        no_btn = tk.Button(btn_frame, text="No", font=("Arial", 18), bg="#e74c3c", fg="white",
                         command=self._payment_timeout_no_response)
        no_btn.pack(side=tk.LEFT, padx=20, pady=10, fill=tk.X, expand=True)
        
        # Start countdown
        self._update_payment_countdown()

    def _update_payment_countdown(self):
        """Update the payment timeout countdown timer."""
        if not hasattr(self, 'payment_timeout_popup') or not self.payment_timeout_popup or not hasattr(self, 'payment_countdown_label'):
            return
            
        self.payment_countdown_value -= 1
        self.payment_countdown_label.config(text=f"Returning to main menu in {self.payment_countdown_value} seconds")
        
        if self.payment_countdown_value <= 0:
            self._payment_timeout_expired()
            return
            
        self.payment_countdown_after = self.root.after(1000, self._update_payment_countdown)

    def _cancel_payment_timeout_popup(self):
        """Cancel the payment timeout popup and continue."""
        if hasattr(self, 'payment_countdown_after') and self.payment_countdown_after:
            self.root.after_cancel(self.payment_countdown_after)
            self.payment_countdown_after = None
            
        if hasattr(self, 'payment_timeout_popup') and self.payment_timeout_popup:
            self.payment_timeout_popup.destroy()
            self.payment_timeout_popup = None
            
        # Reset activity timestamp
        self.payment_last_activity = time.time()
        
        # Restart timeout timer
        self._start_payment_timeout()

    def _payment_timeout_no_response(self):
        """Handle 'No' response to payment timeout popup."""
        self._close_all_payment_popups()
        self._log_cancelled_cart("Customer")
        if hasattr(self, "on_exit"):
            self.on_exit()

    def _payment_timeout_expired(self):
        """Handle payment timeout expiration."""
        self._close_all_payment_popups()
        self._log_cancelled_cart("Customer")
        if hasattr(self, "on_exit"):
            self.on_exit()



    def _show_item_popup(self, upc):
        """Show popup for editing an item."""
        if self.popup_frame:
            self.popup_frame.destroy()
            
        item = self.cart_items.get(upc)
        if not item:
            return
            
        # Create popup frame
        self.popup_frame = tk.Frame(self.root, bg="white", bd=3, relief=tk.RAISED)
        self.popup_frame.place(relx=0.5, rely=0.5, width=600, height=300, anchor=tk.CENTER)
        
        # Item name
        name_label = tk.Label(self.popup_frame, text=item["name"], font=("Arial", 18, "bold"),
                            bg="white", wraplength=550)
        name_label.pack(pady=(20, 10))
        
        # Price and taxable info
        details = f"Price: ${item['price']:.2f}  Taxable: {'Yes' if item['taxable'] else 'No'}"
        details_label = tk.Label(self.popup_frame, text=details, font=("Arial", 14),
                               bg="white")
        details_label.pack(pady=5)
        
        # Quantity controls
        qty_frame = tk.Frame(self.popup_frame, bg="white")
        qty_frame.pack(pady=10)
        
        qty_label = tk.Label(qty_frame, text="QTY:", font=("Arial", 16), bg="white")
        qty_label.pack(side=tk.LEFT, padx=5)
        
        qty_var = tk.IntVar(value=item["qty"])
        qty_display = tk.Label(qty_frame, textvariable=qty_var, font=("Arial", 16, "bold"),
                             bg="white", width=2)
        qty_display.pack(side=tk.LEFT, padx=5)
        
        def decrease_qty():
            if qty_var.get() > 1:
                qty_var.set(qty_var.get() - 1)
                
        def increase_qty():
            if qty_var.get() < 10:
                qty_var.set(qty_var.get() + 1)
                
        down_btn = tk.Button(qty_frame, text="▼", font=("Arial", 16), command=decrease_qty)
        down_btn.pack(side=tk.LEFT, padx=5)
        
        up_btn = tk.Button(qty_frame, text="▲", font=("Arial", 16), command=increase_qty)
        up_btn.pack(side=tk.LEFT, padx=5)
        
        # Subtotal (updates with quantity)
        subtotal_var = tk.StringVar()
        
        def update_subtotal(*args):
            qty = qty_var.get()
            subtotal = item["price"] * qty
            subtotal_var.set(f"Sub Total: ${subtotal:.2f}")
            
        qty_var.trace_add("write", update_subtotal)
        update_subtotal()  # Initial update
        
        subtotal_label = tk.Label(self.popup_frame, textvariable=subtotal_var, 
                                font=("Arial", 16), bg="white")
        subtotal_label.pack(pady=10)
        
        # Buttons
        btn_frame = tk.Frame(self.popup_frame, bg="white")
        btn_frame.pack(pady=20, fill=tk.X)
        
        # Save button
        save_btn = tk.Button(btn_frame, text="Save", font=("Arial", 14), bg="#27ae60", fg="white",
                           command=lambda: self._save_item_changes(upc, qty_var.get()))
        save_btn.pack(side=tk.LEFT, padx=20, pady=10, fill=tk.X, expand=True)
        
        # Delete button
        delete_btn = tk.Button(btn_frame, text="Delete", font=("Arial", 14), bg="#e74c3c", fg="white",
                             command=lambda: self._delete_item(upc))
        delete_btn.pack(side=tk.LEFT, padx=20, pady=10, fill=tk.X, expand=True)
        
        # Cancel button
        cancel_btn = tk.Button(btn_frame, text="Cancel", font=("Arial", 14), bg="#7f8c8d", fg="white",
                             command=lambda: self.popup_frame.destroy())
        cancel_btn.pack(side=tk.LEFT, padx=20, pady=10, fill=tk.X, expand=True)

    def _save_item_changes(self, upc, new_qty):
        """Save changes to an item."""
        if upc in self.cart_items:
            self.cart_items[upc]["qty"] = new_qty
            self._update_receipt()
            self._update_totals()
            
        if self.popup_frame:
            self.popup_frame.destroy()
            self.popup_frame = None

    def _delete_item(self, upc):
        """Delete an item from the cart."""
        if upc in self.cart_items:
            del self.cart_items[upc]
            self._update_receipt()
            self._update_totals()
            
        if self.popup_frame:
            self.popup_frame.destroy()
            self.popup_frame = None

    def _show_error(self, message):
        """Show an error message."""
        # Simple messagebox for now
        from tkinter import messagebox
        messagebox.showerror("Error", message)

    def _cancel_order(self):
        """Cancel the current order."""
        if not self.cart_items:
            # Nothing to cancel
            if hasattr(self, "on_exit"):
                self.on_exit()
            return
            
        # Confirm cancellation
        from tkinter import messagebox
        if messagebox.askyesno("Cancel Order", "Are you sure you want to cancel this order?"):
            # Log the cancelled cart
            self._log_cancelled_cart("Customer")
            
            # Exit to main menu
            if hasattr(self, "on_exit"):
                self.on_exit()

    def _log_cancelled_cart(self, reason):
        """Log a cancelled cart to the Service tab."""
        try:
            # Use more comprehensive scopes
            scopes = [
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive",
            ]
            creds = Credentials.from_service_account_file(str(GS_CRED_PATH), scopes=scopes)
            gc = gspread.authorize(creds)
            
            # Open the spreadsheet and worksheet
            sheet = gc.open(GS_SHEET_NAME).worksheet("Service")
            
            # Prepare row data - match the format in the screenshot
            timestamp = datetime.now().strftime("%m/%d/%Y %H:%M:%S")
            user = self.machine_id  # Use machine ID as user
            action = f"Cancelled Cart - {reason}"
            
            # Create row with the correct format
            row = [timestamp, user, action]
            
            # Log locally first
            logging.info(f"Attempting to log to Service tab: {timestamp}, {user}, {action}")
            
            try:
                # Try to append to sheet
                sheet.append_row(row)
                logging.info(f"Successfully logged to Service tab: {timestamp}, {user}, {action}")
            except Exception as api_error:
                logging.error(f"Error logging to Service tab: {api_error}")
                # Create a local log file as fallback
                log_dir = Path.home() / "SelfCheck" / "Logs"
                log_dir.mkdir(parents=True, exist_ok=True)
                log_file = log_dir / "service_log.csv"
                
                # Append to local log file
                with open(log_file, 'a') as f:
                    f.write(f"{timestamp},{user},{action}\n")
                logging.info(f"Logged to local file instead: {log_file}")
                
                # Try to diagnose the issue
                try:
                    # Check if we can at least read the sheet
                    values = sheet.get_all_values()
                    logging.info(f"Could read Service tab, found {len(values)} rows")
                    
                    # Check permissions
                    spreadsheet = gc.open(GS_SHEET_NAME)
                    permissions = spreadsheet.list_permissions()
                    logging.info(f"Spreadsheet permissions: {permissions}")
                except Exception as diag_error:
                    logging.error(f"Diagnostic error: {diag_error}")
            
        except Exception as e:
            logging.error(f"Failed to log cancelled cart: {e}")
            import traceback
            logging.error(traceback.format_exc())
            
            # Try to create a local log file as fallback
            try:
                log_dir = Path.home() / "SelfCheck" / "Logs"
                log_dir.mkdir(parents=True, exist_ok=True)
                log_file = log_dir / "service_log.csv"
                
                timestamp = datetime.now().strftime("%m/%d/%Y %H:%M:%S")
                user = self.machine_id
                action = f"Cancelled Cart - {reason}"
                
                with open(log_file, 'a') as f:
                    f.write(f"{timestamp},{user},{action}\n")
                logging.info(f"Logged to local file: {log_file}")
            except Exception as log_error:
                logging.error(f"Failed to create local log: {log_error}")

    def _arm_timeout(self):
        """Set up inactivity timeout."""
        if self.timeout_after:
            self.root.after_cancel(self.timeout_after)

        # Reset activity timestamp to ensure full 45 seconds
        self.last_activity_ts = time.time()
            
        def check_timeout():
            current_time = time.time()
            elapsed = current_time - self.last_activity_ts
            
            if elapsed >= 45.0:  # 45 seconds
                self._show_timeout_popup()
                return
                
            self.timeout_after = self.root.after(1000, check_timeout)
            
        self.timeout_after = self.root.after(1000, check_timeout)

    def _show_timeout_popup(self):
        """Show timeout popup with countdown."""
        if self.timeout_popup:
            return
            
        # Create popup
        self.timeout_popup = tk.Frame(self.root, bg="white", bd=3, relief=tk.RAISED)
        self.timeout_popup.place(relx=0.5, rely=0.5, width=500, height=300, anchor=tk.CENTER)
        
        # Message
        message = tk.Label(self.timeout_popup, text="Do you need more time?", 
                         font=("Arial", 24, "bold"), bg="white")
        message.pack(pady=(40, 20))
        
        # Countdown
        self.countdown_value = 30
        self.countdown_label = tk.Label(self.timeout_popup, 
                                      text=f"Returning to main menu in {self.countdown_value} seconds", 
                                      font=("Arial", 18), bg="white")
        self.countdown_label.pack(pady=20)
        
        # Buttons
        btn_frame = tk.Frame(self.timeout_popup, bg="white")
        btn_frame.pack(pady=20, fill=tk.X)
        

        # Yes button
        yes_btn = tk.Button(btn_frame, text="Yes", font=("Arial", 18), bg="#27ae60", fg="white",
                          command=self._cancel_timeout_popup)
        yes_btn.pack(side=tk.LEFT, padx=20, pady=10, fill=tk.X, expand=True)
        
        # No button
        no_btn = tk.Button(btn_frame, text="No", font=("Arial", 18), bg="#e74c3c", fg="white",
                         command=self._timeout_no_response)
        no_btn.pack(side=tk.LEFT, padx=20, pady=10, fill=tk.X, expand=True)
        
        # Start countdown
        self._update_countdown()

    def _update_countdown(self):
        """Update the countdown timer."""
        if not self.timeout_popup or not self.countdown_label:
            return
            
        self.countdown_value -= 1
        self.countdown_label.config(text=f"Returning to main menu in {self.countdown_value} seconds")
        
        if self.countdown_value <= 0:
            self._timeout_expired()
            return
            
        self.countdown_after = self.root.after(1000, self._update_countdown)

    def _cancel_timeout_popup(self):
        """Cancel the timeout popup and continue shopping."""
        if self.countdown_after:
            self.root.after_cancel(self.countdown_after)
            self.countdown_after = None
            
        if self.timeout_popup:
            self.timeout_popup.destroy()
            self.timeout_popup = None
            
        # Reset activity timestamp
        self._on_activity()
        
        # Restart timeout timer
        self._arm_timeout()

    def _timeout_no_response(self):
        """Handle 'No' response to timeout popup."""
        self._log_cancelled_cart("Customer")
        if hasattr(self, "on_exit"):
            self.on_exit()

    def _timeout_expired(self):
        """Handle timeout expiration."""
        self._log_cancelled_cart("SelfCheck")
        if hasattr(self, "on_exit"):
            self.on_exit()



    def _process_successful_payment(self, method, total):
        """Process a successful payment."""
        # Close payment popup
        self._close_all_payment_popups()
        
        # Restore original barcode handler if needed
        if hasattr(self, 'original_barcode_handler'):
            self.root.bind("<Key>", self.original_barcode_handler)
        
        # Show success message
        from tkinter import messagebox
        messagebox.showinfo("Payment Successful", 
                          f"Thank you for your payment of ${total:.2f}.")
        
        # Clear the cart and return to idle mode
        self.cart_items = {}
        if hasattr(self, "on_exit"):
            self.on_exit()

    def test_sheet_access(self):
        """Test access to the Google Sheet."""
        try:
            # Use more comprehensive scopes
            scopes = [
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive",
            ]
            creds = Credentials.from_service_account_file(str(GS_CRED_PATH), scopes=scopes)
            gc = gspread.authorize(creds)
            
            # Try to open the sheet
            sheet = gc.open(GS_SHEET_NAME)
            service_tab = sheet.worksheet("Service")
            
            # Try to read
            values = service_tab.get_all_values()
            logging.info(f"Successfully read {len(values)} rows from Service tab")
            
            # Try to write a test row
            test_row = [datetime.now().strftime("%m/%d/%Y %H:%M:%S"), 
                        self.machine_id, 
                        "Test access - please ignore"]
            service_tab.append_row(test_row)
            logging.info("Successfully wrote test row to Service tab")
            
            return True
        except Exception as e:
            logging.error(f"Sheet access test failed: {e}")
            return False




# ==============================
#              APP
# ==============================

class App:
    def __init__(self):
        # GUI
        self.root = tk.Tk()
        self.root.attributes("-fullscreen", True)
        # Enable cursor for touch development
        self.root.config(cursor="arrow")  # Show cursor during development
        self.root.configure(bg="black")
        self.root.bind("<Escape>", lambda e: self.shutdown())

        # Initialize Google Drive service
        self.drive_service = None
        self.sheets_service = None
        self.init_google_services()
        
        # Attach services to root for access by all modes
        self.root.drive_service = self.drive_service
        self.root.sheets_service = self.sheets_service
        
        # Download UPC catalog and update tax rate at startup
        self.update_upc_catalog_and_tax_rate()

        # Hide the cursor
        self.hide_cursor()

        # Modes
        self.idle = IdleMode(self.root)
        self.price = PriceCheckMode(self.root)
        self.admin = AdminMode(self.root)
        self.mode = None
        self.cart = CartMode(self.root)

        # Buttons -> callbacks
        GPIO.setmode(GPIO.BCM)

        # Button pins
        self.PIN_RED = 5     # exit modes -> Idle
        self.PIN_GREEN = 6   # enter PriceCheck / reset for new scan / update credentials
        self.PIN_YELLOW = 12 # Available
        self.PIN_BLUE = 13   # Available
        self.PIN_CLEAR = 16  # Enter Admin mode

        # Setup with pull-up resistors
        GPIO.setup(self.PIN_RED, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(self.PIN_GREEN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(self.PIN_YELLOW, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(self.PIN_BLUE, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(self.PIN_CLEAR, GPIO.IN, pull_up_down=GPIO.PUD_UP)

        # Add event detection for all buttons
        GPIO.add_event_detect(self.PIN_RED, GPIO.FALLING, callback=self._on_red, bouncetime=300)
        GPIO.add_event_detect(self.PIN_GREEN, GPIO.FALLING, callback=self._on_green, bouncetime=300)
        GPIO.add_event_detect(self.PIN_CLEAR, GPIO.FALLING, callback=self._on_clear, bouncetime=300)

        # Hook timeout from PriceCheck
        self.price.on_timeout = lambda: self.set_mode("Idle")

        # Hook admin mode timeouts and events
        self.admin.on_exit = lambda: self.set_mode("Idle")
        self.admin.on_timeout = lambda: self.set_mode("Idle")

        # Hook touch actions
        self.idle.on_touch_action = lambda: self.set_mode("PriceCheck")
        self.idle.on_wifi_tap = lambda: self.set_mode("Admin")
        self.idle.on_cart_action = lambda: self.set_mode("Cart")
        self.cart.on_exit = lambda: self.set_mode("Idle")

    # Button handlers
    def _on_red(self, ch):
        if self.mode == "PriceCheck" or self.mode == "Admin" or self.mode == "Cart":
            self.set_mode("Idle")

    def _on_green(self, ch):
        if self.mode == "Idle":
            self.set_mode("PriceCheck")
        elif self.mode == "PriceCheck":
            self.price._reset_for_next_scan()
        elif self.mode == "Admin":
            self.admin.update_credentials()

    def _on_clear(self, ch):
        if self.mode != "Admin":
            self.set_mode("Admin")

    def init_google_services(self):
        """Initialize Google Drive and Sheets services."""
        try:
            # Set up Google Drive API client with comprehensive scopes
            scopes = [
                'https://www.googleapis.com/auth/drive.readonly',
                'https://www.googleapis.com/auth/spreadsheets',
                'https://www.googleapis.com/auth/drive',
            ]
            
            creds = Credentials.from_service_account_file(str(GS_CRED_PATH), scopes=scopes)
            
            # Initialize Drive service
            drive_service = build('drive', 'v3', credentials=creds)
            self.drive_service = drive_service
            
            # Initialize Sheets service
            sheets_service = build('sheets', 'v4', credentials=creds)
            self.sheets_service = sheets_service
            
            # Test Drive connection by listing files
            results = drive_service.files().list(pageSize=10, fields="nextPageToken, files(id, name)").execute()
            items = results.get('files', [])
            logging.info(f"Found {len(items)} files in Google Drive folder")
            
            # Log a few file names for debugging
            if items:
                file_names = [item['name'] for item in items[:5]]
                logging.info(f"Sample files in Drive: {', '.join(file_names)}")
            
            # Test Sheets connection by getting spreadsheet info
            try:
                # Use gspread for easier sheet access
                gc = gspread.authorize(creds)
                sheet = gc.open(GS_SHEET_NAME)
                worksheets = sheet.worksheets()
                worksheet_names = [ws.title for ws in worksheets]
                logging.info(f"Found worksheets in {GS_SHEET_NAME}: {', '.join(worksheet_names)}")
                
                # Check if Service tab exists
                if "Service" in worksheet_names:
                    service_tab = sheet.worksheet("Service")
                    values = service_tab.get_all_values()
                    logging.info(f"Service tab contains {len(values)} rows")
                else:
                    logging.warning(f"Service tab not found in {GS_SHEET_NAME}")
                
                # Check permissions
                permissions = sheet.list_permissions()
                service_account_info = json.loads(Path(GS_CRED_PATH).read_text())
                service_account_email = service_account_info.get('client_email', 'Unknown')
                
                logging.info(f"Service account email: {service_account_email}")
                
                # Check if service account has edit access
                service_account_has_access = False
                for perm in permissions:
                    if perm.get('emailAddress') == service_account_email:
                        role = perm.get('role', 'Unknown')
                        logging.info(f"Service account has {role} access")
                        if role in ['writer', 'owner']:
                            service_account_has_access = True
                        break
                
                if not service_account_has_access:
                    logging.warning(f"Service account does NOT have write access to the spreadsheet")
                    logging.warning(f"Please share the spreadsheet with {service_account_email} as an Editor")
                
            except Exception as sheets_error:
                logging.error(f"Error testing Sheets access: {sheets_error}")
                
            logging.info("Google services initialized successfully")
            return True
            
        except Exception as e:
            logging.error(f"Failed to initialize Google services: {e}")
            import traceback
            logging.error(traceback.format_exc())
            self.drive_service = None
            self.sheets_service = None
            return False

    # Mode switcher
    def set_mode(self, mode_name: str):
        # stop current
        if self.mode == "Idle":
            self.idle.stop()
        elif self.mode == "PriceCheck":
            self.price.stop()
        elif self.mode == "Admin":
            self.admin.stop()
        elif self.mode == "Cart":
            self.cart.stop()

        self.mode = mode_name

        # start new
        if mode_name == "Idle":
            self.idle.start()
        elif mode_name == "PriceCheck":
            self.price.start()
        elif mode_name == "Admin":
            self.admin.start()
        elif mode_name == "Cart":
            self.cart.start()

    def run(self):
        self.set_mode("Idle")
        self.root.mainloop()
        self.shutdown()

    def hide_cursor(self):
        """Hide the mouse cursor."""
        # Create a blank/empty cursor
        blank_cursor = "none"  # This is a special name for no cursor
    
        # Apply the blank cursor to the root window
        self.root.config(cursor=blank_cursor)
    
        # Also apply to all child widgets for consistency
        for widget in self.root.winfo_children():
            widget.config(cursor=blank_cursor)

    def update_upc_catalog_and_tax_rate(self):
        """Update UPC catalog and tax rate from Google Sheet."""
        try:
            # Connect to Google Sheet
            scopes = [
                "https://www.googleapis.com/auth/spreadsheets.readonly",
                "https://www.googleapis.com/auth/drive.readonly",
            ]
            creds = Credentials.from_service_account_file(str(GS_CRED_PATH), scopes=scopes)
            gc = gspread.authorize(creds)
            
            # Get tax rate from Credentials tab, cell B27
            sheet = gc.open(GS_SHEET_NAME).worksheet(GS_CRED_TAB)
            tax_rate_str = sheet.acell('B27').value
            
            # Parse tax rate (remove % sign if present)
            if tax_rate_str:
                tax_rate_str = tax_rate_str.replace('%', '').strip()
                try:
                    tax_rate = float(tax_rate_str)
                    
                    # Save to Tax.json
                    tax_path = CRED_DIR / "Tax.json"
                    with open(tax_path, 'w') as f:
                        json.dump({"rate": tax_rate}, f)
                    logging.info(f"Updated Tax.json with rate: {tax_rate}% from spreadsheet")
                except ValueError:
                    logging.error(f"Invalid tax rate in spreadsheet: {tax_rate_str}")
            else:
                logging.warning("Tax rate not found in spreadsheet")
            
            # Get inventory data from Inv tab
            sheet = gc.open(GS_SHEET_NAME).worksheet(GS_TAB)
            rows = sheet.get_all_values()
            
            if not rows:
                logging.error("Sheet returned no rows")
                return
                
            # Define output headers and source column indexes (0-based) for A,B,C,E,F,G,H,I,J,K,L
            out_headers = [
                "UPC", "Brand", "Name", "Size", "Calories", "Sugar", "Sodium",
                "Price", "Tax %", "QTY", "Image"
            ]
            col_idxs = [0, 1, 2, 4, 5, 6, 7, 8, 9, 10, 11]
            
            # Map rows to records
            import csv
            records = []
            for r in rows[1:]:  # Skip header row
                if not r:  # Skip blanks
                    continue
                upc = (r[0] if len(r) > 0 else "").strip()
                if not upc:
                    continue
                vals = [(r[i].strip() if len(r) > i else "") for i in col_idxs]
                records.append(dict(zip(out_headers, vals)))
            
            # Write CSV
            CRED_DIR.mkdir(parents=True, exist_ok=True)
            catalog_path = CRED_DIR / "upc_catalog.csv"
            with open(catalog_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=out_headers)
                writer.writeheader()
                writer.writerows(records)
                
            logging.info(f"Downloaded UPC catalog with {len(records)} rows")
            
        except Exception as e:
            logging.error(f"Failed to update UPC catalog and tax rate: {e}")

    def shutdown(self):
        try:
            if self.mode == "Idle":
                self.idle.stop()
            elif self.mode == "PriceCheck":
                self.price.stop()
            elif self.mode == "Admin":
                self.admin.stop()
            elif self.mode == "Cart":
                self.cart.stop()
        finally:
            GPIO.cleanup()
            try:
                self.root.destroy()
            except:
                pass




if __name__ == "__main__":
    App().run()
