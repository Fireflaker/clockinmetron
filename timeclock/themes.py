"""Live color mapping: (x, y) on the Indoor↔Outdoor / Alone↔Social chart -> color.

Colors are never stored; change the theme and the chart + timelines recolor instantly.
Hue follows the angle around the chart, saturation grows with distance from center:
    outdoor+social = warm orange   indoor+social = pink/magenta
    indoor+alone   = cool blue     outdoor+alone = green
"""
import colorsys
import math

import numpy as np

THEMES = {
    #           hue at 0°, direction, lightness, max saturation
    "Nature":  dict(hue0=85, direction=-1, light=0.55, sat=0.75),
    "Pastel":  dict(hue0=85, direction=-1, light=0.74, sat=0.65),
    "Deep":    dict(hue0=85, direction=-1, light=0.40, sat=0.80),
    "Sunset":  dict(hue0=30, direction=-1, light=0.55, sat=0.80),
}
DEFAULT_THEME = "Nature"


def color_rgb(x, y, theme=DEFAULT_THEME):
    p = THEMES.get(theme, THEMES[DEFAULT_THEME])
    angle = math.degrees(math.atan2(y, x))
    r = min(1.0, math.hypot(x, y))
    hue = (p["hue0"] + p["direction"] * angle) % 360
    return colorsys.hls_to_rgb(hue / 360, p["light"], 0.08 + (p["sat"] - 0.08) * r)


def color(x, y, theme=DEFAULT_THEME):
    if x is None or y is None:
        return "#555555"
    return "#%02x%02x%02x" % tuple(round(v * 255) for v in color_rgb(x, y, theme))


def text_on(hex_color):
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return "#000000" if (0.299 * r + 0.587 * g + 0.114 * b) > 150 else "#ffffff"


def colormap_image(theme=DEFAULT_THEME, n=120):
    """(n, n, 3) RGB array covering x, y in [-1, 1] (row 0 = y=-1), for a chart background."""
    vals = np.linspace(-1, 1, n)
    return np.array([[color_rgb(x, y, theme) for x in vals] for y in vals])
