#!/usr/bin/env python3
# main.py
# Main entry point for SelfCheck application

import os
import logging
import tkinter as tk
import json
import csv
from pathlib import Path
import RPi.GPIO as GPIO
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import gspread

from config import WINDOW_W, WINDOW_H, PIN_RED, PIN_GREEN, PIN_CLEAR
from config import GS_CRED_PATH, GS_SHEET_NAME, GS_TAB, CRED_DIR
from modes.idle_mode import IdleMode
from modes.price_check_mode import PriceCheckMode
from modes.admin_mode import AdminMode
from modes.cart_mode import CartMode

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
        self.PIN_RED = PIN_RED     # exit modes -> Idle
        self.PIN_GREEN = PIN_GREEN   # enter PriceCheck / reset for new scan / update credentials
        self.PIN_CLEAR = PIN_CLEAR  # Enter Admin mode

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
                writer = csv.DictWriter(f, fieldnames=
# main.py (continued)
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
