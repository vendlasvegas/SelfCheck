# modes/cart_mode.py
# Complete file generated on August 26, 2025
import tkinter as tk
import logging
import json
import csv
import os
from pathlib import Path
from datetime import datetime
import time
from PIL import Image, ImageTk

from config import CRED_DIR, WINDOW_W, WINDOW_H
from utils.helpers import center_window, load_image
from utils.upc_helpers import lookup_upc, format_price

class CartMode:
    """Cart mode for self-checkout functionality."""
    
    def __init__(self, root: tk.Tk):
        self.root = root
        self.frame = None
        self.cart_items = []
        self.total = 0.0
        self.tax_total = 0.0
        self.grand_total = 0.0
        self.tax_rate = self._load_tax_rate()
        
        # Callbacks
        self.on_exit = None
        
        # State
        self.scanning_enabled = False
        self.payment_in_progress = False
        
        # UI elements
        self.cart_listbox = None
        self.total_label = None
        self.tax_label = None
        self.grand_total_label = None
        self.scan_label = None
        self.payment_frame = None
        
        # Bind barcode scanner input
        self.root.bind("<Key>", self._on_key_press)
        self.barcode_buffer = ""
        self.last_keypress_time = 0
        
    def _load_tax_rate(self):
        """Load tax rate from Tax.json."""
        try:
            tax_path = CRED_DIR / "Tax.json"
            if tax_path.exists():
                with open(tax_path, 'r') as f:
                    tax_data = json.load(f)
                    return tax_data.get("rate", 0.0) / 100.0  # Convert percentage to decimal
            return 0.0
        except Exception as e:
            logging.error(f"Error loading tax rate: {e}")
            return 0.0
    
    def _setup_ui(self):
        """Set up the cart mode UI."""
        logging.info("Setting up Cart Mode UI")
        
        # Main frame
        self.frame = tk.Frame(self.root, bg="#f5f5f5")
        self.frame.place(x=0, y=0, width=WINDOW_W, height=WINDOW_H)
        
        # Header
        header_frame = tk.Frame(self.frame, bg="#2c3e50", height=80)
        header_frame.pack(fill=tk.X)
        
        title_label = tk.Label(header_frame, text="Self Checkout", font=("Arial", 28, "bold"), 
                              bg="#2c3e50", fg="white")
        title_label.pack(side=tk.LEFT, padx=20, pady=15)
        
        exit_button = tk.Button(header_frame, text="Cancel & Exit", font=("Arial", 16),
                               bg="#e74c3c", fg="white", command=self._exit)
        exit_button.pack(side=tk.RIGHT, padx=20, pady=15)
        
        # Main content area
        content_frame = tk.Frame(self.frame, bg="#f5f5f5")
        content_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        # Left side - Cart items
        cart_frame = tk.Frame(content_frame, bg="white", bd=1, relief=tk.SOLID)
        cart_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
        
        cart_header = tk.Frame(cart_frame, bg="#3498db", height=40)
        cart_header.pack(fill=tk.X)
        
        cart_title = tk.Label(cart_header, text="Your Cart", font=("Arial", 18, "bold"),
                             bg="#3498db", fg="white")
        cart_title.pack(side=tk.LEFT, padx=15, pady=5)
        
        # Cart listbox with scrollbar
        cart_container = tk.Frame(cart_frame, bg="white")
        cart_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        scrollbar = tk.Scrollbar(cart_container)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.cart_listbox = tk.Listbox(cart_container, font=("Arial", 14), 
                                      selectbackground="#3498db", bd=0,
                                      yscrollcommand=scrollbar.set)
        self.cart_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.cart_listbox.yview)
        
        # Right side - Totals and payment
        right_frame = tk.Frame(content_frame, bg="#f5f5f5", width=400)
        right_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=(10, 0))
        right_frame.pack_propagate(False)
        
        # Scanning section
        scan_frame = tk.Frame(right_frame, bg="white", bd=1, relief=tk.SOLID)
        scan_frame.pack(fill=tk.X, pady=(0, 20))
        
        scan_header = tk.Frame(scan_frame, bg="#27ae60", height=40)
        scan_header.pack(fill=tk.X)
        
        scan_title = tk.Label(scan_header, text="Scan Items", font=("Arial", 18, "bold"),
                             bg="#27ae60", fg="white")
        scan_title.pack(side=tk.LEFT, padx=15, pady=5)
        
        scan_content = tk.Frame(scan_frame, bg="white")
        scan_content.pack(fill=tk.X, padx=15, pady=15)
        
        self.scan_label = tk.Label(scan_content, text="Ready to scan", font=("Arial", 16),
                                  bg="white", fg="#27ae60")
        self.scan_label.pack(pady=10)
        
        scan_button = tk.Button(scan_content, text="Start Scanning", font=("Arial", 14),
                               bg="#27ae60", fg="white", command=self._toggle_scanning)
        scan_button.pack(pady=10)
        
        # Totals section
        totals_frame = tk.Frame(right_frame, bg="white", bd=1, relief=tk.SOLID)
        totals_frame.pack(fill=tk.X, pady=(0, 20))
        
        totals_header = tk.Frame(totals_frame, bg="#f39c12", height=40)
        totals_header.pack(fill=tk.X)
        
        totals_title = tk.Label(totals_header, text="Order Summary", font=("Arial", 18, "bold"),
                               bg="#f39c12", fg="white")
        totals_title.pack(side=tk.LEFT, padx=15, pady=5)
        
        totals_content = tk.Frame(totals_frame, bg="white")
        totals_content.pack(fill=tk.X, padx=15, pady=15)
        
        # Subtotal
        subtotal_frame = tk.Frame(totals_content, bg="white")
        subtotal_frame.pack(fill=tk.X, pady=5)
        
        subtotal_label = tk.Label(subtotal_frame, text="Subtotal:", font=("Arial", 16),
                                 bg="white", fg="#333")
        subtotal_label.pack(side=tk.LEFT)
        
        self.total_label = tk.Label(subtotal_frame, text="$0.00", font=("Arial", 16, "bold"),
                                   bg="white", fg="#333")
        self.total_label.pack(side=tk.RIGHT)
        
        # Tax
        tax_frame = tk.Frame(totals_content, bg="white")
        tax_frame.pack(fill=tk.X, pady=5)
        
        tax_label = tk.Label(tax_frame, text=f"Tax ({self.tax_rate*100:.2f}%):", font=("Arial", 16),
                            bg="white", fg="#333")
        tax_label.pack(side=tk.LEFT)
        
        self.tax_label = tk.Label(tax_frame, text="$0.00", font=("Arial", 16, "bold"),
                                 bg="white", fg="#333")
        self.tax_label.pack(side=tk.RIGHT)
        
        # Separator
        separator = tk.Frame(totals_content, height=2, bg="#ddd")
        separator.pack(fill=tk.X, pady=10)
        
        # Grand total
        grand_total_frame = tk.Frame(totals_content, bg="white")
        grand_total_frame.pack(fill=tk.X, pady=5)
        
        grand_total_label = tk.Label(grand_total_frame, text="Total:", font=("Arial", 18, "bold"),
                                    bg="white", fg="#333")
        grand_total_label.pack(side=tk.LEFT)
        
        self.grand_total_label = tk.Label(grand_total_frame, text="$0.00", font=("Arial", 18, "bold"),
                                        bg="white", fg="#e74c3c")
        self.grand_total_label.pack(side=tk.RIGHT)
        
        # Payment section
        self.payment_frame = tk.Frame(right_frame, bg="white", bd=1, relief=tk.SOLID)
        self.payment_frame.pack(fill=tk.X)
        
        payment_header = tk.Frame(self.payment_frame, bg="#9b59b6", height=40)
        payment_header.pack(fill=tk.X)
        
        payment_title = tk.Label(payment_header, text="Payment", font=("Arial", 18, "bold"),
                                bg="#9b59b6", fg="white")
        payment_title.pack(side=tk.LEFT, padx=15, pady=5)
        
        payment_content = tk.Frame(self.payment_frame, bg="white")
        payment_content.pack(fill=tk.X, padx=15, pady=15)
        
        payment_label = tk.Label(payment_content, text="Select payment method:", 
                                font=("Arial", 16), bg="white", fg="#333")
        payment_label.pack(pady=(0, 15))
        
        # Payment buttons
        payment_buttons_frame = tk.Frame(payment_content, bg="white")
        payment_buttons_frame.pack(fill=tk.X)
        
        credit_button = tk.Button(payment_buttons_frame, text="Credit Card", font=("Arial", 14),
                                 bg="#3498db", fg="white", width=12, 
                                 command=lambda: self._process_payment("credit"))
        credit_button.pack(side=tk.LEFT, padx=5, pady=5)
        
        debit_button = tk.Button(payment_buttons_frame, text="Debit Card", font=("Arial", 14),
                                bg="#2ecc71", fg="white", width=12,
                                command=lambda: self._process_payment("debit"))
        debit_button.pack(side=tk.LEFT, padx=5, pady=5)
        
        cash_button = tk.Button(payment_buttons_frame, text="Cash", font=("Arial", 14),
                               bg="#f39c12", fg="white", width=12,
                               command=lambda: self._process_payment("cash"))
        cash_button.pack(side=tk.LEFT, padx=5, pady=5)
        
        # Initially disable payment
        self._update_payment_availability()
    
    def start(self):
        """Start cart mode."""
        logging.info("Starting Cart Mode")
        
        # Set up UI if not already done
        if not self.frame:
            self._setup_ui()
        else:
            self.frame.place(x=0, y=0, width=WINDOW_W, height=WINDOW_H)
        
        # Reset cart
        self.cart_items = []
        self.total = 0.0
        self.tax_total = 0.0
        self.grand_total = 0.0
        
        # Update UI
        self._update_cart_display()
        self._update_totals()
        self._update_payment_availability()
        
        # Reset scanning state
        self.scanning_enabled = False
        self.scan_label.config(text="Ready to scan")
        
        # Reset payment state
        self.payment_in_progress = False
    
    def stop(self):
        """Stop cart mode."""
        if self.frame:
            self.frame.place_forget()
        
        # Unbind barcode scanner temporarily
        # We'll rebind when we start again
    
    def _on_key_press(self, event):
        """Handle key press events for barcode scanning."""
        if not self.scanning_enabled or self.payment_in_progress:
            return
        
        # Check if this is part of a barcode scan
        current_time = time.time()
        
        # If there's a long pause, reset the buffer
        if current_time - self.last_keypress_time > 0.1 and self.barcode_buffer:
            self.barcode_buffer = ""
        
        self.last_keypress_time = current_time
        
        # Handle Enter key (end of barcode)
        if event.keysym == "Return" and self.barcode_buffer:
            self._process_barcode(self.barcode_buffer)
            self.barcode_buffer = ""
        # Handle printable characters
        elif event.char and event.char.isprintable():
            self.barcode_buffer += event.char
    
    def _process_barcode(self, barcode):
        """Process a scanned barcode."""
        logging.info(f"Processing barcode: {barcode}")
        self.scan_label.config(text=f"Scanning: {barcode}")
        
        # Look up the UPC
        product = lookup_upc(barcode)
        
        if product:
            # Add to cart
            self._add_to_cart(product)
            self.scan_label.config(text=f"Added: {product['Name']}")
        else:
            self.scan_label.config(text=f"Product not found: {barcode}")
            # Reset after a delay
            self.root.after(2000, lambda: self.scan_label.config(text="Ready to scan"))
    
    def _add_to_cart(self, product):
        """Add a product to the cart."""
        # Check if product is already in cart
        for item in self.cart_items:
            if item['UPC'] == product['UPC']:
                item['quantity'] += 1
                self._update_cart_display()
                self._update_totals()
                return
        
        # Add new product to cart
        cart_item = product.copy()
        cart_item['quantity'] = 1
        self.cart_items.append(cart_item)
        
        # Update display
        self._update_cart_display()
        self._update_totals()
        self._update_payment_availability()
    
    def _update_cart_display(self):
        """Update the cart listbox display."""
        self.cart_listbox.delete(0, tk.END)
        
        for item in self.cart_items:
            name = item.get('Name', 'Unknown')
            price = float(item.get('Price', 0))
            quantity = item.get('quantity', 1)
            total = price * quantity
            
            display_text = f"{quantity} x {name} - {format_price(price)} = {format_price(total)}"
            self.cart_listbox.insert(tk.END, display_text)
    
    def _update_totals(self):
        """Update the total, tax, and grand total displays."""
        # Calculate subtotal
        self.total = sum(float(item.get('Price', 0)) * item.get('quantity', 1) for item in self.cart_items)
        
        # Calculate tax
        self.tax_total = self.total * self.tax_rate
        
        # Calculate grand total
        self.grand_total = self.total + self.tax_total
        
        # Update labels
        self.total_label.config(text=format_price(self.total))
        self.tax_label.config(text=format_price(self.tax_total))
        self.grand_total_label.config(text=format_price(self.grand_total))
    
    def _update_payment_availability(self):
        """Enable or disable payment based on cart contents."""
        if self.cart_items:
            for widget in self.payment_frame.winfo_children():
                if isinstance(widget, tk.Frame):  # This is the header or content frame
                    for subwidget in widget.winfo_children():
                        if isinstance(subwidget, tk.Button):
                            subwidget.config(state=tk.NORMAL)
        else:
            for widget in self.payment_frame.winfo_children():
                if isinstance(widget, tk.Frame):  # This is the header or content frame
                    for subwidget in widget.winfo_children():
                        if isinstance(subwidget, tk.Button):
                            subwidget.config(state=tk.DISABLED)
    
    def _toggle_scanning(self):
        """Toggle barcode scanning on/off."""
        self.scanning_enabled = not self.scanning_enabled
        
        if self.scanning_enabled:
            self.scan_label.config(text="Ready to scan")
        else:
            self.scan_label.config(text="Scanning paused")
    
    def _process_payment(self, payment_method):
        """Process payment."""
        if not self.cart_items or self.payment_in_progress:
            return
        
        self.payment_in_progress = True
        
        # Show payment processing
        payment_window = tk.Toplevel(self.root)
        payment_window.title("Processing Payment")
        center_window(payment_window, 400, 300)
        payment_window.configure(bg="white")
        payment_window.grab_set()  # Make modal
        
        # Payment message
        message_label = tk.Label(payment_window, text=f"Processing {payment_method} payment...",
                                font=("Arial", 16), bg="white", fg="#333")
        message_label.pack(pady=(50, 20))
        
        # Animated progress bar (simple version)
        progress_frame = tk.Frame(payment_window, bg="white")
        progress_frame.pack(pady=20)
        
        progress_bar = tk.Canvas(progress_frame, width=300, height=20, bg="#eee", highlightthickness=0)
        progress_bar.pack()
        
        # Function to animate progress
        def animate_progress(step=0):
            progress_bar.delete("progress")
            width = step * 30  # 10 steps * 30 = 300 (full width)
            progress_bar.create_rectangle(0, 0, width, 20, fill="#3498db", tags="progress")
            
            if step < 10:
                payment_window.after(300, lambda: animate_progress(step + 1))
            else:
                # Payment complete
                message_label.config(text="Payment successful!")
                
                # Show receipt button
                receipt_button = tk.Button(payment_window, text="Print Receipt", font=("Arial", 14),
                                         bg="#27ae60", fg="white", 
                                         command=lambda: self._print_receipt(payment_method, payment_window))
                receipt_button.pack(pady=20)
        
        # Start animation
        animate_progress()
    
    def _print_receipt(self, payment_method, payment_window):
        """Print receipt and close payment window."""
        # Generate receipt
        receipt_data = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "items": self.cart_items,
            "subtotal": self.total,
            "tax": self.tax_total,
            "total": self.grand_total,
            "payment_method": payment_method
        }
        
        # Save receipt to file
        try:
            receipts_dir = CRED_DIR / "receipts"
            receipts_dir.mkdir(exist_ok=True)
            
            receipt_file = receipts_dir / f"receipt_{int(time.time())}.json"
            with open(receipt_file, 'w') as f:
                json.dump(receipt_data, f, indent=2)
            
            logging.info(f"Receipt saved to {receipt_file}")
        except Exception as e:
            logging.error(f"Error saving receipt: {e}")
        
        # Close payment window
        payment_window.destroy()
        
        # Return to idle mode
        if self.on_exit:
            self.on_exit()
    
    def _exit(self):
        """Exit cart mode."""
        if self.on_exit:
            self.on_exit()
