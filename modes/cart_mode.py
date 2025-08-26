# modes/cart_mode.py
# 8-26-25 11:50
import time
import logging
import tkinter as tk
from tkinter import messagebox
import json
from pathlib import Path
from datetime import datetime
from PIL import Image, ImageTk
import gspread
from google.oauth2.service_account import Credentials

from config import WINDOW_W, WINDOW_H, GS_CRED_PATH, GS_SHEET_NAME, GS_TAB, CRED_DIR
from modes.base_mode import BaseMode
from utils.upc_helpers import upc_variants_from_scan, upc_variants_from_sheet

class CartMode(BaseMode):
    """
    Shopping cart mode for adding and managing items.
    Displays Cart.png as background with receipt recorder and totals.
    """
    def __init__(self, root, **kwargs):
        """Initialize the CartMode."""
        super().__init__(root)
        
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
        
        # Callback to be set by main app
        self.on_exit = None

    def _on_touch(self, event):
        # Touch handler for cart mode
        x, y = event.x, event.y
        logging.info(f"Touch in Cart mode at ({x}, {y})")
        self._on_activity()

    def _on_activity(self, event=None):
        # Reset inactivity timer
        self.last_activity_ts = time.time()
        
        # Cancel any existing timeout popup
        if hasattr(self, 'timeout_popup') and self.timeout_popup:
            self._cancel_timeout_popup()

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
            
    def start(self):
        logging.info("CartMode: Starting")
        super().start()
        """Start cart mode."""
        logging.info("Starting Cart Mode")
    
        # Debug information
        logging.info(f"Window dimensions: {self.root.winfo_width()}x{self.root.winfo_height()}")
        logging.info(f"Frame exists: {hasattr(self, 'frame')}")
        
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
        super().stop()
        
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
            
        if hasattr(self, 'timeout_popup') and self.timeout_popup:
            self.timeout_popup.destroy()
            self.timeout_popup = None

    # Simplified implementation - in a real implementation, these methods would be fully implemented
    def _create_ui(self):
            """Set up the cart mode UI."""
        logging.info("Setting up Cart Mode UI")
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
        self._create_buttons()
        
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
        # Implementation details omitted for brevity
        pass

    def _create_totals_area(self):
        """Create the totals display area."""
        # Implementation details omitted for brevity
        pass

    def _create_buttons(self):
        """Create the main action buttons."""
        # Implementation details omitted for brevity
        pass

    def _update_receipt(self):
        """Update the receipt display with current cart items."""
        # Implementation details omitted for brevity
        pass

    def _update_totals(self):
        """Update the totals display with current cart values."""
        # Implementation details omitted for brevity
        pass

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
            import time
            fallback_id = f"T{int(time.time())}"
            logging.info(f"Using fallback transaction ID: {fallback_id}")
            return fallback_id

    def _load_config_files(self):
        """Load configuration from JSON files."""
        # Implementation details omitted for brevity
        pass

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

    def _load_upc_catalog(self):
        """Load UPC catalog from CSV file and update Tax.json from spreadsheet."""
        # Implementation details omitted for brevity
        pass

    def _show_error(self, message):
        """Show an error message."""
        # Simple messagebox for now
        messagebox.showerror("Error", message)

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

    def test_sheet_access(self):
        """Test access to the Google Sheet."""
        # Implementation details omitted for brevity
        return True

    def check_spreadsheet_permissions(self):
        """Check and log permissions for the Google Sheet."""
        # Implementation details omitted for brevity
        pass
