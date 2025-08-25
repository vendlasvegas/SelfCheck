# modes/admin_mode.py
import logging
import tkinter as tk
import subprocess
import json
from pathlib import Path
from PIL import Image, ImageTk, ImageDraw
import gspread
from google.oauth2.service_account import Credentials

from config import WINDOW_W, WINDOW_H, ADMIN_BG_PATH, ADMIN_TIMEOUT_MS
from config import GS_CRED_PATH, GS_SHEET_NAME, GS_CRED_TAB, CRED_DIR
from modes.base_mode import BaseMode
from components.admin_login import AdminLoginScreen
from ui.fonts import load_ttf

class AdminMode(BaseMode):
    """
    Admin mode for updating credentials and settings.
    Displays Admin.png with text overlay for options.
    """
    def __init__(self, root: tk.Tk):
        super().__init__(root)
        
        self.base_bg = None
        self.update_in_progress = False
        self.last_activity_ts = 0
        self.timeout_after = None
        self.web_view = None
        
        # Create login screen
        self.login_screen = None  # Will be created in start()
        
        # Add touch support
        self.label.bind("<Button-1>", self._on_touch)
        self.label.bind("<Motion>", self._on_activity)
        
        # Callbacks to be set by main app
        self.on_exit = None
        self.on_timeout = None

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
        # Implementation omitted for brevity - would include WiFi network scanning and connection UI
        self._render_status("WiFi settings feature not implemented in this version")
    
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
                import web
