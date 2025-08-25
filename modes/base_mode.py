# modes/base_mode.py
import tkinter as tk
from PIL import Image, ImageTk
from config import WINDOW_W, WINDOW_H

class BaseMode:
    """Base class for all modes with common functionality."""
    
    def __init__(self, root: tk.Tk):
        self.root = root
        self.is_active = False
        self.label = tk.Label(root, bg="black")
        self.tk_img = None
    
    def start(self):
        """Start the mode - to be implemented by subclasses."""
        self.is_active = True
        self.label.place(x=0, y=0, width=WINDOW_W, height=WINDOW_H)
        self.label.lift()
    
    def stop(self):
        """Stop the mode - to be implemented by subclasses."""
        self.is_active = False
        self.label.place_forget()
    
    def _letterbox(self, im: Image.Image):
        """Force letterboxing by scaling to fit screen."""
        iw, ih = im.size
        scale = min(WINDOW_W/iw, WINDOW_H/ih)
        nw, nh = int(iw*scale), int(ih*scale)
        resized = im.resize((nw, nh), Image.LANCZOS)
        bg = Image.new("RGB", (WINDOW_W, WINDOW_H), (255,255,255))
        bg.paste(resized, ((WINDOW_W-nw)//2, (WINDOW_H-nh)//2))
        return bg
