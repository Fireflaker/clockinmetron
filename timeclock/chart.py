"""Interactive Indoor↔Outdoor / Alone↔Social chart, drawn on a plain Tk Canvas (instant redraws).

click dot = clock in · drag dot = move it · right-click dot = rename/delete
click empty = add task there · drag empty = pan · wheel = zoom at cursor · right-click empty = reset view
"""
import tkinter as tk
from tkinter import messagebox, simpledialog

import numpy as np
from PIL import Image, ImageTk

from . import themes

BG, PANEL, FG, MUTED = "#1e1f24", "#2a2c33", "#e8e8ea", "#8a8c96"
LIM = 1.12          # full view spans [-LIM, LIM] on both axes
MIN_HALF = 0.08     # max zoom
BG_ALPHA = 0.28     # strength of the color-map backdrop
FONT = ("Segoe UI", 9)
FONT_B = ("Segoe UI", 9, "bold")
AXIS_FONT = ("Segoe UI", 10, "bold")


def describe(x, y):
    h = f"{abs(x) * 100:.0f}% {'Outdoor' if x >= 0 else 'Indoor'}"
    v = f"{abs(y) * 100:.0f}% {'Social' if y >= 0 else 'Alone'}"
    return f"{h} · {v}"


def _clip(v):
    return max(-1.0, min(1.0, round(v, 3)))


class Chart(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=BG)
        self.app = app
        k = self.winfo_fpixels("1i") / 96          # DPI scale (2.0 on a 200% display)
        self.R, self.R_HOVER, self.PICK, self.DRAG = 7 * k, 10 * k, 12 * k, 4 * k
        self.MARGIN = 26 * k
        self.cx = self.cy = 0.0                     # view center (data units)
        self.half = LIM                             # view half-width (data units)
        self.tags, self.hover, self._press = [], None, None
        self._bg_key, self._bg_img, self._cmap = None, None, {}

        self.cv = tk.Canvas(self, bg=BG, highlightthickness=0, cursor="crosshair")
        self.cv.pack(fill="both", expand=True)
        b = self.cv.bind
        b("<Configure>", lambda e: self.draw())
        b("<Motion>", self.on_move)
        b("<Leave>", lambda e: self._set_hover(None, None))
        b("<ButtonPress-1>", self.on_press)
        b("<B1-Motion>", self.on_drag)
        b("<ButtonRelease-1>", self.on_release)
        b("<Button-3>", self.on_right)
        b("<MouseWheel>", self.on_wheel)
        self.refresh()

    # ---------- coordinates ----------
    def _geom(self):
        w, h = max(self.cv.winfo_width(), 50), max(self.cv.winfo_height(), 50)
        side = max(min(w, h) - 2 * self.MARGIN, 20)
        return (w - side) / 2, (h - side) / 2, side

    def to_px(self, x, y):
        ox, oy, side = self._geom()
        s = side / (2 * self.half)
        return ox + (x - self.cx + self.half) * s, oy + (self.cy + self.half - y) * s

    def to_data(self, px, py):
        ox, oy, side = self._geom()
        s = side / (2 * self.half)
        return (px - ox) / s + self.cx - self.half, self.cy + self.half - (py - oy) / s

    def _inside(self, px, py):
        ox, oy, side = self._geom()
        return ox <= px <= ox + side and oy <= py <= oy + side

    def _hit(self, px, py):
        best, best_d = None, self.PICK ** 2
        for i, (_, x, y) in enumerate(self.tags):
            qx, qy = self.to_px(x, y)
            d = (qx - px) ** 2 + (qy - py) ** 2
            if d < best_d:
                best, best_d = i, d
        return best

    # ---------- public API used by the app ----------
    def refresh(self):
        self.tags = [list(t) for t in self.app.store.tags()]
        self.draw()

    def set_theme(self):
        self.refresh()

    def update_center(self):
        self.draw()

    # ---------- drawing ----------
    def _backdrop(self, ox, oy, side):
        """Color-map image for the current view (numpy lookup + Pillow bilinear resize, cached)."""
        th = self.app.theme
        key = (th, round(self.cx, 4), round(self.cy, 4), round(self.half, 4), int(side))
        if key != self._bg_key:
            if th not in self._cmap:
                panel = np.array([int(PANEL[i:i + 2], 16) for i in (1, 3, 5)]) / 255
                self._cmap[th] = (themes.colormap_image(th, 160) * BG_ALPHA + panel * (1 - BG_ALPHA), panel)
            cmap, panel = self._cmap[th]
            n, lo = 96, self.cx - self.half
            xs = np.linspace(lo, lo + 2 * self.half, n)
            ys = np.linspace(self.cy + self.half, self.cy - self.half, n)
            gx, gy = np.meshgrid(xs, ys)
            ix = np.clip(((gx + 1) / 2 * 159).round().astype(int), 0, 159)
            iy = np.clip(((gy + 1) / 2 * 159).round().astype(int), 0, 159)
            rgb = cmap[iy, ix]
            rgb[(np.abs(gx) > 1) | (np.abs(gy) > 1)] = panel
            img = Image.fromarray((rgb * 255).astype("uint8")).resize((int(side), int(side)), Image.BILINEAR)
            self._bg_img, self._bg_key = ImageTk.PhotoImage(img), key
        self.cv.create_image(ox, oy, image=self._bg_img, anchor="nw")

    def draw(self):
        cv, th = self.cv, self.app.theme
        cv.delete("all")
        ox, oy, side = self._geom()
        self._backdrop(ox, oy, side)
        x0, y0 = self.to_px(0, 0)
        if ox < x0 < ox + side:
            cv.create_line(x0, oy, x0, oy + side, fill="#6a6c74")
        if oy < y0 < oy + side:
            cv.create_line(ox, y0, ox + side, y0, fill="#6a6c74")
        cv.create_rectangle(ox, oy, ox + side, oy + side, outline="#3a3c44")
        m = self.MARGIN / 2
        cv.create_text(ox + side / 2, oy - m, text="▲ SOCIAL", fill=FG, font=AXIS_FONT)
        cv.create_text(ox + side / 2, oy + side + m, text="▼ ALONE", fill=FG, font=AXIS_FONT)
        cv.create_text(ox - m, oy + side / 2, text="INDOOR", fill=FG, font=AXIS_FONT, angle=90)
        cv.create_text(ox + side + m, oy + side / 2, text="OUTDOOR", fill=FG, font=AXIS_FONT, angle=-90)
        if self.half < LIM - 1e-6:
            cv.create_text(4, 4, anchor="nw", fill=MUTED, font=FONT,
                           text=f"{LIM / self.half:.1f}× zoom · right-click empty space to reset")

        cur = self.app.store.current()
        cur_name = cur[1]
        drag_i = self._press["idx"] if self._press and self._press["drag"] else None
        dots = []
        for i, (name, x, y) in enumerate(self.tags):
            px, py = self.to_px(x, y)
            if self._inside(px, py):
                dots.append((i, name, x, y, px, py))
        # day's time-weighted center
        s = self.app.store.day_summary(self.app.selected_day)
        if s["center"]:
            px, py = self.to_px(*s["center"])
            if self._inside(px, py):
                cv.create_text(px, py, text="★", fill="#ffffff", font=("Segoe UI", 16))
        for i, name, x, y, px, py in dots:
            col = themes.color(x, y, th)
            r = self.R_HOVER if i in (self.hover, drag_i) else self.R
            if name == cur_name:
                rr = r + 5 * self.R / 7
                cv.create_oval(px - rr, py - rr, px + rr, py + rr, outline=col, width=3)
            cv.create_oval(px - r, py - r, px + r, py + r, fill=col, outline="#ffffff",
                           dash=(3, 2) if i == drag_i else None)
        self._labels(dots, cur_name, ox, oy, side)
        self._ghost_and_tip()

    def _labels(self, dots, cur_name, ox, oy, side):
        """Greedy placement: try 8 spots around each dot; skip if every spot collides (name shows on hover)."""
        cv, taken = self.cv, []
        W, H = cv.winfo_width(), cv.winfo_height()
        for _, _, _, _, px, py in dots:
            taken.append((px - self.R, py - self.R, px + self.R, py + self.R))
        order = sorted(dots, key=lambda d: (d[1] != cur_name, d[0] != self.hover))
        gap = self.R + 3
        for i, name, x, y, px, py in order:
            font = FONT_B if name == cur_name else FONT
            tid = cv.create_text(0, 0, text=name, fill=FG, font=font)
            x1, y1, x2, y2 = cv.bbox(tid)
            w, h = x2 - x1, y2 - y1
            dx, dy = gap + w / 2, gap + h / 2
            for cx, cy in ((px, py - dy), (px, py + dy), (px + dx, py), (px - dx, py),
                           (px + dx - gap, py - dy), (px - dx + gap, py - dy),
                           (px + dx - gap, py + dy), (px - dx + gap, py + dy)):
                box = (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
                if (box[0] >= 0 and box[2] <= W and box[1] >= 0 and box[3] <= H
                        and not any(box[0] < b[2] and b[0] < box[2] and box[1] < b[3] and b[1] < box[3]
                                    for b in taken)):
                    cv.coords(tid, cx, cy)
                    bg = cv.create_rectangle(*box, fill=BG, outline="", stipple="gray50")
                    cv.tag_lower(bg, tid)
                    taken.append(box)
                    break
            else:
                cv.delete(tid)          # no room: name still shows on hover

    def _ghost_and_tip(self):
        cv = self.cv
        cv.delete("tip")
        if self.hover is None and self._hover_pt is None:
            return
        if self._press and self._press["drag"]:
            i = self._press["idx"]
            name, x, y = self.tags[i]
            text = f"{name}\n{describe(x, y)}"
        elif self.hover is not None:
            name, x, y = self.tags[self.hover]
            sec = self.app.store.day_summary(self.app.selected_day)["by_name"].get(name, 0)
            text = (f"{name}\n{describe(x, y)}\nToday: {int(sec // 3600)}h {int(sec % 3600 // 60):02d}m\n"
                    "click = clock in · drag = move · right-click = edit")
        else:
            x, y = self._hover_pt
            px, py = self.to_px(x, y)
            r = self.R
            cv.create_oval(px - r, py - r, px + r, py + r, fill=themes.color(x, y, self.app.theme),
                           outline="#ffffff", dash=(3, 2), tags="tip")
            text = f"{describe(x, y)}\nclick = add task here · drag = pan"
        px, py = self.to_px(x, y)
        ox, oy, side = self._geom()
        right, below = px < ox + side / 2, py < oy + side / 2
        off = self.R_HOVER + 6
        t = cv.create_text(px + (off if right else -off), py + (off if below else -off), text=text,
                           fill=FG, font=FONT, anchor=("n" if below else "s") + ("w" if right else "e"),
                           tags="tip")
        x1, y1, x2, y2 = cv.bbox(t)
        W, H = cv.winfo_width(), cv.winfo_height()
        sx = max(0, 8 - x1) - max(0, x2 + 8 - W)       # keep the tooltip on-screen
        sy = max(0, 6 - y1) - max(0, y2 + 6 - H)
        cv.move(t, sx, sy)
        x1, y1, x2, y2 = x1 + sx, y1 + sy, x2 + sx, y2 + sy
        bg = cv.create_rectangle(x1 - 6, y1 - 4, x2 + 6, y2 + 4, fill="#111216", outline="#5a5e6b", tags="tip")
        cv.tag_lower(bg, t)

    # ---------- events ----------
    _hover_pt = None

    def _set_hover(self, idx, pt):
        if (idx, pt) == (self.hover, self._hover_pt):
            return
        dot_changed = idx != self.hover
        self.hover, self._hover_pt = idx, pt
        if dot_changed:
            self.draw()
        else:                       # only the ghost/tip moved over empty space
            self._ghost_and_tip()

    def on_move(self, e):
        if not self._inside(e.x, e.y):
            return self._set_hover(None, None)
        i = self._hit(e.x, e.y)
        if i is not None:
            self.cv.configure(cursor="hand2")
            self._set_hover(i, None)
        else:
            self.cv.configure(cursor="crosshair")
            x, y = self.to_data(e.x, e.y)
            self._set_hover(None, (_clip(x), _clip(y)))

    def on_press(self, e):
        if not self._inside(e.x, e.y):
            return
        self._press = dict(idx=self._hit(e.x, e.y), px=(e.x, e.y), drag=False, pan=False,
                           view=(self.cx, self.cy), orig=None)

    def on_drag(self, e):
        p = self._press
        if not p:
            return
        dx, dy = e.x - p["px"][0], e.y - p["px"][1]
        if not (p["drag"] or p["pan"]) and dx * dx + dy * dy < self.DRAG ** 2:
            return
        if p["idx"] is not None:                   # move a dot
            if not p["drag"]:
                p["drag"], p["orig"] = True, tuple(self.tags[p["idx"]][1:])
            x, y = self.to_data(e.x, e.y)
            self.tags[p["idx"]][1:] = [_clip(x), _clip(y)]
            self.hover, self._hover_pt = p["idx"], None
            self.cv.configure(cursor="fleur")
        else:                                      # pan the view
            p["pan"] = True
            ox, oy, side = self._geom()
            s = side / (2 * self.half)
            self.cx, self.cy = p["view"][0] - dx / s, p["view"][1] + dy / s
            self._clamp_view()
            self._hover_pt = None
        self.draw()

    def on_release(self, e):
        p, self._press = self._press, None
        if not p or p["pan"]:
            return
        if p["idx"] is not None:
            name, x, y = self.tags[p["idx"]]
            if p["drag"]:
                if (x, y) != p["orig"]:
                    self.app.store.move_tag(name, x, y)
                    self.app.data_changed()
                else:
                    self.draw()
            else:
                self.app.clock_in(name)
        else:
            x, y = self.to_data(*p["px"])
            self._add_at(_clip(x), _clip(y))

    def on_right(self, e):
        i = self._hit(e.x, e.y)
        if i is not None:
            self._menu(self.tags[i][0], e)
        elif self.half < LIM:
            self.cx = self.cy = 0.0
            self.half = LIM
            self.draw()

    def on_wheel(self, e):
        if not self._inside(e.x, e.y):
            return
        f = 0.8 if e.delta > 0 else 1.25
        mx, my = self.to_data(e.x, e.y)
        new = max(MIN_HALF, min(LIM, self.half * f))
        f = new / self.half
        self.cx, self.cy, self.half = mx - (mx - self.cx) * f, my - (my - self.cy) * f, new
        self._clamp_view()
        self.hover = self._hover_pt = None
        self.draw()
        self.on_move(e)

    def _clamp_view(self):
        lim = LIM - self.half
        self.cx, self.cy = max(-lim, min(lim, self.cx)), max(-lim, min(lim, self.cy))

    # ---------- dialogs ----------
    def _add_at(self, x, y):
        self._set_hover(None, None)
        name = simpledialog.askstring("New task", f"Name for the task at\n{describe(x, y)}:", parent=self)
        if not name or not name.strip():
            return
        try:
            self.app.store.add_tag(name.strip(), x, y)
        except ValueError as ex:
            messagebox.showerror("Can't add", str(ex), parent=self)
            return
        self.app.data_changed()

    def _menu(self, name, e):
        self._set_hover(None, None)
        m = tk.Menu(self, tearoff=0)
        m.add_command(label=f"Clock in to '{name}'", command=lambda: self.app.clock_in(name))
        m.add_command(label="Rename…", command=lambda: self._rename(name))
        m.add_separator()
        m.add_command(label="Delete from chart", command=lambda: self._delete(name))
        m.tk_popup(e.x_root, e.y_root)

    def _rename(self, name):
        new = simpledialog.askstring("Rename", "New name (applies from the next clock-in):",
                                     initialvalue=name, parent=self)
        if not new or not new.strip() or new.strip() == name:
            return
        try:
            self.app.store.rename_tag(name, new.strip())
        except ValueError as ex:
            messagebox.showerror("Can't rename", str(ex), parent=self)
            return
        self.app.data_changed()

    def _delete(self, name):
        if messagebox.askyesno("Delete", f"Remove '{name}' from the chart?\n"
                                         "Past timeline entries stay as they are.", parent=self):
            self.app.store.delete_tag(name)
            self.app.data_changed()
