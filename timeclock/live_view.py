"""Live view: a zoomed-in, scrollable horizontal timeline (default 5 min) where the
active task's color visibly fills in as time passes."""
import math
import time
import tkinter as tk
from datetime import datetime, timedelta

from .store import day_bounds
from .themes import text_on

SUN_COLOR = "#ffb347"

BG, PANEL, FG, MUTED = "#1e1f24", "#2a2c33", "#e8e8ea", "#8a8c96"
TICK_STEPS = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 10800, 21600]
FRAME_MS = 50


def lighten(hex_color, amt=0.45):
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % tuple(int(v + (255 - v) * amt) for v in (r, g, b))


def dur(sec):
    sec = int(sec)
    h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    return f"{h}h {m:02d}m {s:02d}s" if h else f"{m}m {s:02d}s" if m else f"{s}s"


class LiveView(tk.Frame):
    ZOOMS = [("1 min", 60), ("5 min", 300), ("15 min", 900), ("1 hr", 3600), ("6 hr", 21600)]
    MIN_SPAN, MAX_SPAN = 20, 2 * 86400

    def __init__(self, parent, app):
        super().__init__(parent, bg=PANEL)
        self.app = app
        self.span = 300.0
        self.follow = True
        self.smooth = tk.BooleanVar(value=False)
        self.view_start = time.time() - 0.1 * self.span
        self.items = {}
        self._drag = None

        bar = tk.Frame(self, bg=PANEL)
        bar.pack(fill="x", padx=8, pady=6)
        tk.Label(bar, text="Zoom:", bg=PANEL, fg=MUTED).pack(side="left")
        self.zoom_btns = {}
        for label, sec in self.ZOOMS:
            b = tk.Button(bar, text=label, relief="flat", padx=8, command=lambda s=sec: self.set_span(s))
            b.pack(side="left", padx=2)
            self.zoom_btns[sec] = b
        self.follow_btn = tk.Button(bar, relief="flat", padx=10, command=self.jump_now,
                                    font=("Segoe UI", 9, "bold"))
        self.follow_btn.pack(side="right", padx=2)
        tk.Checkbutton(bar, text="Smooth scroll", variable=self.smooth, bg=PANEL, fg=FG, selectcolor=BG,
                       activebackground=PANEL, activeforeground=FG,
                       command=self.jump_now).pack(side="right", padx=8)
        self.range_label = tk.Label(bar, text="", bg=PANEL, fg=FG, font=("Segoe UI", 10, "bold"))
        self.range_label.pack(side="left", padx=14)

        self.canvas = tk.Canvas(self, bg=PANEL, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.sb = tk.Scrollbar(self, orient="horizontal", command=self.on_scrollbar)
        self.sb.pack(fill="x")
        tk.Label(self, text="Drag over a range (or click a block), then click a task on the chart to reassign it · "
                            "wheel or right-drag = scroll · Ctrl+wheel = zoom", bg=PANEL, fg=MUTED).pack(anchor="w", padx=8, pady=2)

        c = self.canvas
        c.bind("<MouseWheel>", self.on_wheel)
        c.bind("<Shift-MouseWheel>", self.on_wheel)
        c.bind("<Control-MouseWheel>", self.on_zoom_wheel)
        c.bind("<ButtonPress-1>", self.on_sel_press)
        c.bind("<B1-Motion>", self.on_sel_drag)
        c.bind("<ButtonRelease-1>", self.on_sel_release)
        c.bind("<ButtonPress-3>", self.on_press)
        c.bind("<B3-Motion>", self.on_drag)
        c.bind("<ButtonRelease-3>", self.on_release)
        self._sel = None

        self._refresh_controls()
        self.animate()

    # ---------- view state ----------
    def _pps(self):
        return max(self.canvas.winfo_width(), 1) / self.span

    def _follow_start(self, now):
        return now - (0.85 if self.smooth.get() else 0.1) * self.span

    def _bounds(self):
        """Scrollable time range: from first record to the live-follow position."""
        now = time.time()
        first = self.app.store.first_start() or now
        return min(first, now - self.span) - 0.05 * self.span, self._follow_start(now) + self.span

    def _clamp(self):
        lo, hi = self._bounds()
        if self.view_start + self.span >= hi:
            self.view_start = hi - self.span
            self.follow = True
        self.view_start = max(self.view_start, lo)

    def _update_follow(self, now):
        if not self.follow:
            return
        if self.smooth.get():
            self.view_start = now - 0.85 * self.span
        elif not (self.view_start + 0.02 * self.span <= now <= self.view_start + 0.95 * self.span):
            # sweep: now-line travels left→right, then the page jumps forward
            self.view_start = now - 0.1 * self.span

    def set_span(self, sec):
        sec = min(max(sec, self.MIN_SPAN), self.MAX_SPAN)
        if self.follow:
            now = time.time()
            frac = (now - self.view_start) / self.span
            self.view_start = now - min(max(frac, 0.1), 0.85) * sec
        else:
            self.view_start += (self.span - sec) / 2
        self.span = float(sec)
        self._clamp()
        self._refresh_controls()

    def jump_now(self):
        self.follow = True
        self.view_start = self._follow_start(time.time())
        self._refresh_controls()

    def _unfollow(self):
        if self.follow:
            self.follow = False
            self._refresh_controls()

    def _refresh_controls(self):
        for sec, b in self.zoom_btns.items():
            sel = abs(sec - self.span) < 1
            b.configure(bg="#5a5e6b" if sel else BG, fg=FG)
        if self.follow:
            self.follow_btn.configure(text="● LIVE", bg="#c0392b", fg="white")
        else:
            self.follow_btn.configure(text="Jump to now ▶", bg=BG, fg=FG)

    # ---------- input ----------
    def on_wheel(self, ev):
        self._unfollow()
        self.view_start -= (ev.delta / 120) * 0.1 * self.span
        self._clamp()
        self._refresh_controls()

    def on_zoom_wheel(self, ev):
        t_mouse = self.view_start + ev.x / self._pps()
        new = min(max(self.span * (0.8 if ev.delta > 0 else 1.25), self.MIN_SPAN), self.MAX_SPAN)
        if not self.follow:
            self.view_start = t_mouse - ev.x / (max(self.canvas.winfo_width(), 1) / new)
            self.span = new
            self._clamp()
            self._refresh_controls()
        else:
            self.set_span(new)

    def on_scrollbar(self, *args):
        lo, hi = self._bounds()
        if args[0] == "moveto":
            self.view_start = lo + float(args[1]) * (hi - lo)
        elif args[0] == "scroll":
            self.view_start += int(args[1]) * self.span * (0.9 if args[2] == "pages" else 0.1)
        self._unfollow()
        self._clamp()
        self._refresh_controls()

    def on_press(self, ev):
        self._drag = (ev.x, self.view_start, False)

    def on_drag(self, ev):
        if not self._drag:
            return
        x0, vs0, moved = self._drag
        if moved or abs(ev.x - x0) > 3:
            self._drag = (x0, vs0, True)
            self._unfollow()
            self.view_start = vs0 - (ev.x - x0) / self._pps()
            self._clamp()
            self._refresh_controls()

    def on_release(self, ev):
        if self._drag and not self._drag[2]:
            self.app.cancel_selection()
        self._drag = None

    def _t_at(self, x):
        return self.view_start + x / self._pps()

    def _snap(self, t):
        step = 1 if self.span <= 900 else 60 if self.span <= 6 * 3600 else 300
        return round(t / step) * step

    def on_sel_press(self, ev):
        self._sel = (ev.x, False)

    def on_sel_drag(self, ev):
        if not self._sel:
            return
        x0, moved = self._sel
        if not moved and abs(ev.x - x0) <= 3:
            return
        if not moved:
            self.app.cancel_selection()
        self._sel = (x0, True)
        a, b = sorted((self._snap(self._t_at(x0)), self._snap(self._t_at(ev.x))))
        self.app.selection = (a, b)

    def on_sel_release(self, ev):
        p, self._sel = self._sel, None
        if not p:
            return
        if p[1]:
            if self.app.selection:
                self.app.select_range(*self.app.selection)
            return
        hit = [self.items[i] for i in self.canvas.find_overlapping(ev.x, ev.y, ev.x, ev.y) if i in self.items]
        if hit:
            self.app.select_range(*hit[-1])
        else:
            self.app.cancel_selection()

    def _sun_events(self, vs, ve):
        d, last = datetime.fromtimestamp(vs).date() - timedelta(days=1), datetime.fromtimestamp(ve).date()
        out = []
        while d <= last:
            rise, set_ = self.app.sun.times(d)
            out.append((rise, set_))
            d += timedelta(days=1)
        return out

    def _draw_night(self, c, vs, ve, x_of, top, bot, w):
        ev = self._sun_events(vs, ve)
        for (_, set_), (rise, _) in zip(ev, ev[1:]):
            if set_ and rise and rise > vs and set_ < ve:
                c.create_rectangle(max(x_of(set_), 0), top, min(x_of(rise), w), bot, fill="#17181c", outline="")

    def _draw_sun(self, c, vs, ve, x_of, top, bot, w):
        for rise, set_ in self._sun_events(vs, ve):
            for t, label in ((rise, "☀ Sunrise"), (set_, "☾ Sunset")):
                if t is None or not vs <= t <= ve:
                    continue
                x = x_of(t)
                c.create_line(x, top, x, bot, fill=BG, width=5)
                c.create_line(x, top, x, bot, fill=SUN_COLOR, width=2, dash=(6, 4))
                tag = c.create_text(x + 6, top + 8, anchor="nw", fill=SUN_COLOR, font=("Segoe UI", 10, "bold"),
                                    text=f"{label} {datetime.fromtimestamp(t):%H:%M:%S}")
                c.create_rectangle(c.bbox(tag), fill=BG, outline="")
                c.tag_raise(tag)

    # ---------- rendering ----------
    def animate(self):
        if self.winfo_ismapped():
            self.draw()
        self._after_id = self.after(FRAME_MS, self.animate)

    def destroy(self):
        if getattr(self, "_after_id", None):
            self.after_cancel(self._after_id)
        super().destroy()

    def draw(self):
        c = self.canvas
        w, h = c.winfo_width(), c.winfo_height()
        if w < 10 or h < 10:
            return
        now = time.time()
        self._update_follow(now)
        vs, span = self.view_start, self.span
        ve = vs + span
        pps = w / span

        def x_of(t):
            return (t - vs) * pps

        c.delete("all")
        self.items = {}
        top, bot = 64, h - 34

        self._draw_night(c, vs, ve, x_of, top, bot, w)
        # past/future background
        x_now = x_of(now)
        if x_now < w:
            c.create_rectangle(max(x_now, 0), top, w, bot, fill="#24262c", outline="", stipple="gray50")
            c.create_text(min(max(x_now + 14, 14), w - 4), bot - 10, text="future", anchor="sw",
                          fill="#4a4d57", font=("Segoe UI", 10, "italic"))
        first = self.app.store.first_start() or now
        if first > vs:
            c.create_rectangle(0, top, min(x_of(first), w), bot, fill="#33353c", outline="", stipple="gray25")

        # time grid
        step = next((s for s in TICK_STEPS if s * pps >= 80), TICK_STEPS[-1])
        ds, _ = day_bounds(datetime.fromtimestamp(vs).date())
        t = ds + math.ceil((vs - ds) / step) * step
        minor = step / 5 if step >= 5 else None
        if minor and minor * pps >= 8:
            mt = ds + math.ceil((vs - ds) / minor) * minor
            while mt < ve:
                c.create_line(x_of(mt), bot, x_of(mt), bot + 4, fill="#4a4d57")
                mt += minor
        while t < ve:
            x = x_of(t)
            dt = datetime.fromtimestamp(t)
            is_midnight = dt.hour == dt.minute == dt.second == 0
            c.create_line(x, top - 6, x, bot + 8, fill="#ffd166" if is_midnight else "#3a3c44",
                          width=2 if is_midnight else 1)
            label = f"{dt:%a %b %d}" if is_midnight else f"{dt:%H:%M:%S}" if step < 60 else f"{dt:%H:%M}"
            c.create_text(x, bot + 10, text=label, anchor="n", fill=MUTED, font=("Segoe UI", 9))
            t += step

        # segments
        for key, name, sx, sy, a, b in self.app.store.segments_between(vs, ve, now):
            b = min(b, now)
            if b <= a:
                continue
            color = self.app.color(sx, sy)
            x0, x1 = max(x_of(a), -2), min(x_of(b), w + 2)
            item = c.create_rectangle(x0, top, x1, bot, fill=color, outline="")
            self.items[item] = (a, b)
            c.create_line(x0, top, x0, bot, fill=BG, width=2)
            if x1 - x0 > 50:
                tx = min(max(x0, 0) + 10, x1 - 40)
                fg = text_on(color)
                t1 = c.create_text(tx, (top + bot) / 2 - 2, text=name, anchor="sw", fill=fg,
                                   font=("Segoe UI", 18 if bot - top > 120 else 12, "bold"))
                t2 = c.create_text(tx, (top + bot) / 2 + 2, text=dur(b - a), anchor="nw", fill=fg,
                                   font=("Segoe UI", 11))
                self.items[t1] = self.items[t2] = (a, b)

        sel = self.app.selection
        if sel and sel[1] > vs and sel[0] < ve:
            x0, x1 = max(x_of(sel[0]), -2), min(x_of(sel[1]), w + 2)
            c.create_rectangle(x0, top - 4, x1, bot + 4, fill="#ffffff", stipple="gray25",
                               outline="#ffffff", width=2, dash=(4, 2))
            f = "%H:%M:%S" if self.span <= 6 * 3600 else "%H:%M"
            lbl = c.create_text((max(x0, 0) + min(x1, w)) / 2, top + 6, anchor="n", fill="#111216",
                                font=("Segoe UI", 9, "bold"),
                                text=f"{datetime.fromtimestamp(sel[0]):{f}} – {datetime.fromtimestamp(sel[1]):{f}}")
            c.create_rectangle(c.bbox(lbl), fill="#ffffff", outline="")
            c.tag_raise(lbl)

        # glowing, pulsing leading edge of the active block
        self._draw_sun(c, vs, ve, x_of, top, bot, w)
        if 0 <= x_now <= w + 2:
            _, _, cx, cy = self.app.store.current()
            color = self.app.color(cx, cy)
            pulse = 0.5 + 0.5 * math.sin(now * 2 * math.pi)
            glow = 3 + 5 * pulse
            c.create_rectangle(x_now - glow, top, x_now, bot, fill=lighten(color, 0.3 + 0.3 * pulse), outline="")
            c.create_line(x_now, top - 14, x_now, bot + 4, fill="#ff3b3b", width=2)
            c.create_polygon(x_now - 6, top - 20, x_now + 6, top - 20, x_now, top - 12, fill="#ff3b3b")
            c.create_text(x_now, top - 22, text=datetime.fromtimestamp(now).strftime("%H:%M:%S"),
                          anchor="s", fill="#ff6b6b", font=("Segoe UI", 11, "bold"))

        self.range_label.configure(text=f"{datetime.fromtimestamp(vs):%a %b %d  %H:%M:%S}  →  "
                                        f"{datetime.fromtimestamp(ve):%H:%M:%S}")
        lo, hi = self._bounds()
        self.sb.set((vs - lo) / (hi - lo), (ve - lo) / (hi - lo))
