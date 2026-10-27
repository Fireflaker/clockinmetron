"""Generate the PWA icons (android/icons/) from the same color map as the app. Run once: python android/make_icons.py"""
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
from timeclock import themes  # noqa: E402


def icon(size, maskable=False):
    bg = (30, 31, 36)
    img = Image.new("RGB", (size, size), bg)
    r = size * (0.36 if maskable else 0.46)
    c = size / 2
    vals = np.linspace(-1, 1, size)
    cm = np.array([[themes.color_rgb(x, -y) for x in vals] for y in vals])
    disk = Image.fromarray((cm * 255).astype("uint8"))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((c - r, c - r, c + r, c + r), fill=255)
    img.paste(disk, (0, 0), mask)
    d = ImageDraw.Draw(img)
    w = max(2, int(size * 0.035))
    d.line((c, c, c, c - r * 0.72), fill="white", width=w)                       # minute hand
    a = math.radians(-30)
    d.line((c, c, c + r * 0.5 * math.cos(a), c + r * 0.5 * math.sin(a)), fill="white", width=w)
    d.ellipse((c - w, c - w, c + w, c + w), fill="white")
    return img


(ROOT / "icons").mkdir(exist_ok=True)
icon(192).save(ROOT / "icons" / "icon-192.png")
icon(512).save(ROOT / "icons" / "icon-512.png")
icon(512, maskable=True).save(ROOT / "icons" / "maskable-512.png")
icon(180, maskable=True).save(ROOT / "icons" / "apple-touch-icon.png")     # iOS rounds the corners itself
print("icons written")
