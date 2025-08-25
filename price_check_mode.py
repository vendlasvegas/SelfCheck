# modes/price_check_mode.py
import time
import logging
import tkinter as tk
from PIL import Image, ImageTk, ImageDraw

from config import WINDOW_W, WINDOW_H, PRICE_BG_PATH, PC_BLUE_BOX, PC_GREEN_BOX
from config import PRICECHECK_TIMEOUT_MS, GS_CRED_PATH, GDRIVE_FOLDER_ID
from modes.base_mode import BaseMode
from models.image_loader import GoogleDriveImageLoader
from utils.google_services import load_inventory_by_upc
from utils.upc_helpers import upc_variants_from_scan
from ui.fonts import PC_FONT_TITLE, PC_FONT_SUB, PC_FONT_INFO, PC_FONT_LINE, PC_FONT_SMALL

class PriceCheckMode(BaseMode):
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
        super().__init__(root)
        
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
        
        # Callback to be set by main app
        self.on_timeout = None

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
        super().start()
        
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
        super().stop()
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

            if elapsed >= (PRICECHECK_TIMEOUT_MS/1000.0):
                logging.info(f"Admin mode timeout after {elapsed:.1f}s - returning to Idle")
                if hasattr(self, "on_timeout"):
                    self.on_timeout()
                return
            self.timeout_after = self.root.after(1000, check_timeout)

        self.timeout_after = self.root.after(1000, check_timeout)
