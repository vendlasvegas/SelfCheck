# components/admin_login.py
# 8-26-25
import tkinter as tk
import logging
import gspread
from google.oauth2.service_account import Credentials

from config import GS_CRED_PATH, GS_SHEET_NAME, GS_LOGIN_TAB

class AdminLoginScreen:
    """Login screen for Admin mode with virtual keyboard."""
    def __init__(self, root: tk.Tk):
        self.root = root
        self.frame = tk.Frame(root, bg="#2c3e50")
        self.frame.place(x=0, y=0, width=root.winfo_width(), height=root.winfo_height())

        # Login variables
        self.username_var = tk.StringVar()
        self.password_var = tk.StringVar()
        self.current_field = None
        self.login_in_progress = False

        # Create login UI
        self._create_login_ui()
        
        # Callbacks to be set by admin mode
        self.on_login_success = None
        self.on_login_failed = None
        self.on_cancel = None

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
