# modes/idle_mode.py
import random
import time
import logging
import tkinter as tk
import requests
import json
from datetime import datetime
from pathlib import Path
from PIL import Image, ImageTk, ImageDraw
import gspread
from google.oauth2.service_account import Credentials

from config import WINDOW_W, WINDOW_H, IDLE_DIR, IMAGE_EXTS, SLIDE_MS, WEATHER_UPDATE_INTERVAL
from config import GS_CRED_PATH, GS_SHEET_NAME, GS_CRED_TAB
from modes.base_mode import BaseMode
from ui.fonts import load_ttf

class IdleMode(BaseMode):
    """Fullscreen slideshow with weather, time, and hidden admin button."""
    
    def __init__(self, root: tk.Tk):
        super().__init__(root)
        
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
        
        self.slide_after = None
        self.overlay_timer = None
        self.order = []
        self.idx = 0
        
        # Weather data
        self.weather_data = None
        self.weather_last_update = 0
        self.zipcode = None
        self.weather_api_key = None
        
        # Callbacks to be set by the main app
        self.on_touch_action = None
        self.on_wifi_tap = None
        self.on_cart_action = None

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
        super().start()
        
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

    # modes/idle_mode.py (continued)
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
