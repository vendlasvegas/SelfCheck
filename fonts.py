# ui/fonts.py
from PIL import ImageFont
from pathlib import Path

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
