"""Main window: quadrant chart (left), Week / Live timeline tabs (middle), day summary (right)."""
import csv
import json
import queue
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from datetime import date, datetime, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from . import sync, themes
from .chart import Chart, describe
from .live_view import LiveView
from .schedules_view import SchedulesView
from .store import Store, day_bounds
from .sun import Sun

SUN_COLOR = "#ffb347"

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "timeline.db"
SETTINGS_PATH = DATA_DIR / "settings.json"
BG, PANEL, FG, MUTED = "#1e1f24", "#2a2c33", "#e8e8ea", "#8a8c96"
QUAD_XY = {"Outdoor·Social": (0.7, 0.7), "Indoor·Social": (-0.7, 0.7),
           "Indoor·Alone": (-0.7, -0.7), "Outdoor·Alone": (0.7, -0.7)}


def fmt(sec):
    sec = int(round(sec))
    return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


class App(tk.Tk):
    HEADER, GUTTER = 34, 48

    def __init__(self, db_path=DB_PATH, settings_path=SETTINGS_PATH):
        super().__init__()
        self.title("TimeClock — every second accounted for")
        self.geometry("1600x900")
        self.configure(bg=BG)
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.settings_path = Path(settings_path)
        try:
            self.settings = json.loads(self.settings_path.read_text())
        except (OSError, ValueError):
            self.settings = {}
        self.theme = self.settings.get("theme", themes.DEFAULT_THEME)
        if self.theme not in themes.THEMES:
            self.theme = themes.DEFAULT_THEME
        self.sun = Sun(self.settings.get("location"))
        self.store = Store(db_path)
        self.selected_day = date.today()
        self.seg_items = {}
        self.selection = None          # (start_ts, end_ts) being reassigned
        self._cal_press = None
        self._last_cur = None
        self._sync_q, self._sync_busy, self._sync_due = queue.Queue(), False, 0.0

        style = ttk.Style(self)
        style.theme_use("clam")
        row_h = int(tkfont.Font(family="Segoe UI", size=10).metrics("linespace") * 1.4)
        style.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=FG,
                        rowheight=row_h, font=("Segoe UI", 10))
        style.configure("Treeview.Heading", background=BG, foreground=FG, font=("Segoe UI", 10, "bold"))
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=PANEL, foreground=MUTED, padding=(16, 6),
                        font=("Segoe UI", 10, "bold"))
        style.map("TNotebook.Tab", background=[("selected", "#40434d")], foreground=[("selected", FG)])

        self._build_layout()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Escape>", lambda e: self.cancel_selection())
        self.store.apply_schedules()
        self.tick()

    # ---------- layout ----------
    def _build_layout(self):
        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", padx=12, pady=(10, 4))
        self.now_swatch = tk.Label(top, text="  ", font=("Segoe UI", 22), bg=BG)
        self.now_swatch.pack(side="left", padx=(0, 10))
        self.now_label = tk.Label(top, text="", font=("Segoe UI", 22, "bold"), bg=BG, fg=FG)
        self.now_label.pack(side="left")
        self.sun_label = tk.Label(top, text="", font=("Segoe UI", 11), bg=BG, fg=SUN_COLOR)
        self.sun_label.pack(side="left", padx=(24, 0))
        sun_box = tk.Frame(top, bg=BG)
        sun_box.pack(side="left", padx=16)
        k = self.winfo_fpixels("1i") / 96
        self.sun_bar = tk.Canvas(sun_box, width=int(170 * k), height=int(10 * k), bg=PANEL, highlightthickness=0)
        self.sun_bar.pack(fill="x", pady=(2, 1))
        self.sun_pct = tk.Label(sun_box, text="", font=("Segoe UI", 9), bg=BG, fg=SUN_COLOR)
        self.sun_pct.pack(anchor="w")
        tk.Button(top, text="Export CSV", command=self.export_csv, bg=PANEL, fg=FG, relief="flat", padx=10, pady=4,
                  font=("Segoe UI", 10)).pack(side="right", padx=4)
        self.sync_btn = tk.Button(top, text="☁ Sync…", command=self.sync_menu, bg=PANEL, fg=FG, relief="flat",
                                  padx=10, pady=4, font=("Segoe UI", 10))
        self.sync_btn.pack(side="right", padx=4)
        self.theme_box = ttk.Combobox(top, values=list(themes.THEMES), state="readonly", width=10)
        self.theme_box.set(self.theme)
        self.theme_box.bind("<<ComboboxSelected>>", lambda e: self.set_theme(self.theme_box.get()))
        self.theme_box.pack(side="right", padx=4)
        tk.Label(top, text="Theme:", bg=BG, fg=MUTED).pack(side="right")

        body = tk.PanedWindow(self, bg=BG, sashwidth=6, sashrelief="flat", bd=0)
        body.pack(fill="both", expand=True, padx=12, pady=8)

        self.chart = Chart(body, self)
        body.add(self.chart, minsize=380, width=int(620 * self.winfo_fpixels("1i") / 96), stretch="always")

        self.tabs = ttk.Notebook(body)
        body.add(self.tabs, minsize=400, stretch="always")
        mid = tk.Frame(self.tabs, bg=BG)
        self.live = LiveView(self.tabs, self)
        self.tabs.add(mid, text="Week calendar")
        self.tabs.add(self.live, text="● Live (zoomed)")
        self.sched = SchedulesView(self.tabs, self)
        self.tabs.add(self.sched, text="⏰ Auto clock-in")
        self.tabs.bind("<<NotebookTabChanged>>", lambda e: self.redraw())
        nav = tk.Frame(mid, bg=BG)
        nav.pack(fill="x", pady=(6, 0))
        for txt, delta in [("◀ Week", -7), ("◀ Day", -1), ("Today", 0), ("Day ▶", 1), ("Week ▶", 7)]:
            tk.Button(nav, text=txt, command=lambda d=delta: self.shift_day(d), bg=PANEL, fg=FG,
                      relief="flat", padx=8).pack(side="left", padx=2)
        self.week_label = tk.Label(nav, text="", bg=BG, fg=FG, font=("Segoe UI", 12, "bold"))
        self.week_label.pack(side="left", padx=12)
        self.canvas = tk.Canvas(mid, bg=PANEL, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, pady=(6, 0))
        self.canvas.bind("<Configure>", lambda e: self.draw_calendar())
        self.canvas.bind("<ButtonPress-1>", self.on_cal_press)
        self.canvas.bind("<B1-Motion>", self.on_cal_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_cal_release)
        self.canvas.bind("<Button-3>", lambda e: self.cancel_selection())

        right = tk.Frame(body, bg=BG)
        body.add(right, minsize=280, width=320)
        self.day_label = tk.Label(right, text="", bg=BG, fg=FG, font=("Segoe UI", 12, "bold"), anchor="w")
        self.day_label.pack(fill="x", padx=6)
        self.sum_tree = self._tree(right, ("Task", 150), ("Time", 80), ("%", 55), height=13)
        tk.Label(right, text="Where the day went", bg=BG, fg=FG,
                 font=("Segoe UI", 12, "bold"), anchor="w").pack(fill="x", padx=6, pady=(8, 0))
        self.quad_tree = self._tree(right, ("Quadrant", 150), ("Time", 80), ("%", 55), height=4)
        self.center_label = tk.Label(right, text="", bg=BG, fg=FG, justify="left", anchor="w",
                                     font=("Segoe UI", 10))
        self.center_label.pack(fill="x", padx=6, pady=4)
        tk.Label(right, text="★ on the chart = the day's time-weighted center.\n\n"
                             "Fix the past: drag over a time range (or click a block) on the calendar, "
                             "then click the task it should be.",
                 bg=BG, fg=MUTED, justify="left", wraplength=int(270 * self.winfo_fpixels("1i") / 96)).pack(
            anchor="w", padx=6, pady=8)

    def _tree(self, parent, first, *cols, height):
        tv = ttk.Treeview(parent, columns=[c for c, _ in cols], height=height)
        tv.heading("#0", text=first[0])
        tv.column("#0", width=first[1])
        for c, w in cols:
            tv.heading(c, text=c)
            tv.column(c, width=w, anchor="e")
        tv.pack(fill="x", padx=6, pady=(4, 0))
        return tv

    # ---------- state changes ----------
    def color(self, x, y):
        return themes.color(x, y, self.theme)

    def set_theme(self, name):
        self.theme = name
        self.settings["theme"] = name
        self._save_settings()
        self.chart.set_theme()
        self.redraw()

    def _save_settings(self):
        try:
            self.settings_path.write_text(json.dumps(self.settings, indent=2))
        except OSError:
            pass

    def clock_in(self, name):
        self.store.clock_in(name)
        self.data_changed()

    def data_changed(self, kick=True):
        self.chart.refresh()
        self.sched.refresh()
        self.redraw()
        if kick:
            self.sync_kick(1)

    # ---------- sync through a private GitHub Gist (see sync.py) ----------
    def sync_kick(self, delay=0):
        self._sync_due = min(self._sync_due, time.time() + delay)

    def _sync_poll(self):
        cfg = self.settings.get("sync")
        try:
            msg = self._sync_q.get_nowait()
        except queue.Empty:
            msg = None
        if msg:
            self._sync_busy = False
            self._sync_due = time.time() + 60
            if msg[0] == "err":
                self.sync_btn.configure(text=f"☁ ⚠ {msg[1]}", fg="#ff9b6b")
            elif cfg:
                (adopt, new_base), snap, gist_id = msg[1:]
                cfg["gist"] = gist_id
                if adopt is not None and sync.digest(self.store.doc()) != sync.digest(snap):
                    self._sync_due = time.time() + 2      # changed meanwhile: merge on the next round
                else:
                    if adopt is not None:
                        self.store.replace_doc(adopt)
                        self.data_changed(kick=False)
                    cfg["base"] = new_base
                self._save_settings()
                self.sync_btn.configure(text=f"☁ synced {datetime.now():%H:%M}", fg=FG)
        if cfg and not self._sync_busy and time.time() >= self._sync_due:
            self._sync_busy = True
            snap, first = self.store.doc(), cfg.pop("first", "merge")
            gist = sync.Gist(cfg["token"], cfg.get("gist"))

            def run():
                try:
                    self._sync_q.put(("ok", sync.sync_once(gist, cfg.get("base"), snap, first), snap, gist.id))
                except sync.GistError as e:
                    self._sync_q.put(("err", str(e)))
            threading.Thread(target=run, daemon=True).start()

    def sync_menu(self):
        cfg = self.settings.get("sync")
        if cfg:
            m = tk.Menu(self, tearoff=0)
            m.add_command(label="Sync now", command=self.sync_kick)
            m.add_command(label="Disconnect this PC", command=self.sync_disconnect)
            m.tk_popup(self.sync_btn.winfo_rootx(), self.sync_btn.winfo_rooty() + self.sync_btn.winfo_height())
            return
        token = simpledialog.askstring(
            "Sync with GitHub",
            "Free sync between this PC and your phones through a private GitHub Gist.\n\n"
            "1. Open github.com/settings/personal-access-tokens/new\n"
            "2. Permissions → Account tab (not Repository) → add Gists: Read and write (nothing else)\n"
            "3. Paste the token here (it stays in data/settings.json on this PC):", parent=self, show="•")
        if not token:
            return
        gist = sync.Gist(token)
        try:
            found = gist.find()
        except sync.GistError as e:
            messagebox.showerror("Sync", f"Could not connect: {e}")
            return
        first = "merge"
        if found and messagebox.askyesno(
                "Sync", "Found synced data on GitHub.\n\nYes = use it on this PC (replaces this PC's data; "
                        "best for a new device)\nNo = merge both"):
            first = "replace"
        self.settings["sync"] = {"token": token.strip(), "gist": found, "base": None, "first": first}
        self._save_settings()
        self.sync_btn.configure(text="☁ syncing…")
        self.sync_kick()

    def sync_disconnect(self):
        if messagebox.askyesno("Sync", "Stop syncing this PC? Data stays here and on GitHub."):
            self.settings.pop("sync", None)
            self._save_settings()
            self.sync_btn.configure(text="☁ Sync…", fg=FG)

    # ---------- reassign a time range: select it, then pick a task on the chart ----------
    def select_range(self, s, e):
        now = time.time()
        s, e = min(s, e), max(s, e)
        self.cancel_selection()
        if s >= now - 1 or e - s < 1:
            return
        self.selection = (s, e)
        a, b = datetime.fromtimestamp(s), datetime.fromtimestamp(min(e, now))
        f = lambda d: f"{d:%H:%M}" if d.second == 0 else f"{d:%H:%M:%S}"
        end = "now" if e >= now - 1 else f(b) if a.date() == b.date() else f"{b:%a} {f(b)}"
        self.chart.pick(f"Reassign {a:%a} {f(a)} – {end} to…", self._apply_selection)
        self.redraw()

    def _apply_selection(self, name):
        sel, self.selection = self.selection, None
        if name and sel:
            s, e = sel
            self.store.log_block(name, s, None if e >= time.time() - 1 else e)
            self.data_changed()
        else:
            self.redraw()

    def cancel_selection(self):
        self.chart.cancel_pick()
        if self.selection:
            self.selection = None
            self.redraw()

    def shift_day(self, delta):
        self.selected_day = date.today() if delta == 0 else self.selected_day + timedelta(days=delta)
        self.chart.update_center()
        self.redraw()

    def tick(self):
        if self.store.apply_schedules():
            self.data_changed()
        self._sync_poll()
        self.redraw()
        cur = self.store.current()
        if int(time.time()) % 10 == 0 or cur != self._last_cur:
            self._last_cur = cur
            self.chart.update_center()
        self._tick_id = self.after(1000, self.tick)

    def _on_close(self):
        self.after_cancel(self._tick_id)
        self.destroy()

    def sun_text(self, d):
        if self.sun.label is None:
            return "☀ location unknown — set \"location\" in data/settings.json"
        rise, set_ = self.sun.times(d)
        f = lambda t: "—" if t is None else f"{datetime.fromtimestamp(t):%H:%M}"
        day = "" if None in (rise, set_) else f"   ({fmt(set_ - rise)[:5]} daylight)"
        return f"☀ {f(rise)}   ☾ {f(set_)}{day}   · {self.sun.label}"

    def draw_sun_progress(self):
        c = self.sun_bar
        c.delete("all")
        p = self.sun.progress(time.time())
        if p is None:
            self.sun_pct.configure(text="")
            return
        kind, frac, left = p
        day = kind == "day"
        w, h = int(c["width"]), int(c["height"])
        c.create_rectangle(0, 0, w * frac, h, fill=SUN_COLOR if day else "#6c7bd1", outline="")
        self.sun_pct.configure(text=f"{'☀' if day else '☾'} {frac:.0%} of {'daylight' if day else 'night'} · "
                                    f"{'sunset' if day else 'sunrise'} in {int(left // 3600)}h "
                                    f"{int(left % 3600 // 60):02d}m",
                               fg=SUN_COLOR if day else "#9aa6e8")

    def redraw(self):
        t, name, x, y = self.store.current()
        col = self.color(x, y)
        self.now_swatch.configure(bg=col)
        self.now_label.configure(text=f"Clocked in: {name}   {fmt(time.time() - t)}", fg=col)
        self.sun_label.configure(text=self.sun_text(self.selected_day))
        self.draw_sun_progress()
        if self.canvas.winfo_ismapped():
            self.draw_calendar()
        self.draw_summary()

    # ---------- week calendar ----------
    def week_days(self):
        monday = self.selected_day - timedelta(days=self.selected_day.weekday())
        return [monday + timedelta(days=i) for i in range(7)]

    def _geom(self):
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        return max((w - self.GUTTER) / 7, 10), max((h - self.HEADER) / 24, 5)

    def draw_calendar(self):
        c = self.canvas
        c.delete("all")
        self.seg_items = {}
        col_w, hour_h = self._geom()
        now = time.time()
        first = self.store.first_start() or now
        days = self.week_days()
        self.week_label.configure(text=f"{days[0]:%b %d} – {days[-1]:%b %d, %Y}")

        for h in range(25):
            y = self.HEADER + h * hour_h
            c.create_line(self.GUTTER, y, self.GUTTER + 7 * col_w, y, fill="#3a3c44")
            if h < 24:
                c.create_text(self.GUTTER - 6, y + 2, text=f"{h:02d}:00", anchor="ne", fill=MUTED,
                              font=("Segoe UI", 8))

        for i, d in enumerate(days):
            x0 = self.GUTTER + i * col_w
            ds, de = day_bounds(d)
            span = de - ds
            sel = d == self.selected_day
            c.create_rectangle(x0, 0, x0 + col_w, self.HEADER, fill="#40434d" if sel else BG, outline=PANEL)
            c.create_text(x0 + col_w / 2, self.HEADER / 2, text=f"{d:%a %d}",
                          fill="#ffd166" if d == date.today() else FG, font=("Segoe UI", 10, "bold"))

            def y_of(t, ds=ds, span=span):
                return self.HEADER + (t - ds) / span * 24 * hour_h

            rise, set_ = self.sun.times(d)
            for a, b in ((ds, rise), (set_, de)):
                if a is not None and b is not None and b > a:
                    c.create_rectangle(x0 + 1, y_of(a), x0 + col_w - 1, y_of(b), fill="#17181c", outline="")
            if first > ds and ds < now:
                c.create_rectangle(x0 + 2, y_of(ds), x0 + col_w - 2, y_of(min(first, de, now)),
                                   fill="#33353c", outline="", stipple="gray25")
            for key, name, sx, sy, seg_a, seg_b in self.store.segments_between(ds, min(de, now), now):
                a, b = max(seg_a, ds), min(seg_b, de, now)
                if b <= a:
                    continue
                color = self.color(sx, sy)
                y0, y1 = y_of(a), y_of(b)
                item = c.create_rectangle(x0 + 2, y0, x0 + col_w - 2, max(y1, y0 + 1), fill=color, outline="")
                self.seg_items[item] = (seg_a, min(seg_b, now))
                if y1 - y0 >= 13:
                    t = c.create_text(x0 + 6, y0 + 1, text=f"{name}  {fmt(b - a)[:5]}", anchor="nw",
                                      fill=themes.text_on(color), font=("Segoe UI", 8))
                    self.seg_items[t] = self.seg_items[item]
            for t, sym in ((rise, "☀"), (set_, "☾")):
                if t is None:
                    continue
                y = y_of(t)
                c.create_line(x0 + 1, y, x0 + col_w - 1, y, fill=SUN_COLOR, dash=(4, 3))
                tag = c.create_text(x0 + col_w - 4, y, text=f"{sym} {datetime.fromtimestamp(t):%H:%M}",
                                    anchor="e", fill=SUN_COLOR, font=("Segoe UI", 8, "bold"))
                c.create_rectangle(c.bbox(tag), fill=BG, outline="")
                c.tag_raise(tag)
            if ds <= now < de:
                y = y_of(now)
                c.create_line(x0, y, x0 + col_w, y, fill="#ff3b3b", width=2)
            if self.selection:
                a, b = max(self.selection[0], ds), min(self.selection[1], de)
                if b > a:
                    c.create_rectangle(x0 + 1, y_of(a), x0 + col_w - 1, y_of(b), fill="#ffffff",
                                       stipple="gray25", outline="#ffffff", width=2, dash=(4, 2))
                    if self.selection[0] >= ds:
                        lbl = c.create_text(x0 + col_w / 2, y_of(a) - 2, anchor="s", fill="#111216",
                                            font=("Segoe UI", 8, "bold"),
                                            text=f"{datetime.fromtimestamp(self.selection[0]):%H:%M}–"
                                                 f"{datetime.fromtimestamp(self.selection[1]):%H:%M}")
                        c.create_rectangle(c.bbox(lbl), fill="#ffffff", outline="")
                        c.tag_raise(lbl)

        for i in range(8):
            x = self.GUTTER + i * col_w
            c.create_line(x, 0, x, self.HEADER + 24 * hour_h, fill="#3a3c44")

    def _time_at(self, x, y, clamp=False):
        col_w, hour_h = self._geom()
        i = int((x - self.GUTTER) // col_w)
        if clamp:
            i = min(max(i, 0), 6)
        elif not 0 <= i < 7:
            return None, None
        d = self.week_days()[i]
        ds, de = day_bounds(d)
        frac = min(max((y - self.HEADER) / (24 * hour_h), 0), 1)
        return d, ds + frac * (de - ds)

    def on_cal_press(self, ev):
        d, _ = self._time_at(ev.x, ev.y)
        self._cal_press = None if d is None else (ev.x, ev.y, False)
        if d is not None and d != self.selected_day:
            self.selected_day = d
            self.chart.update_center()
            self.redraw()

    def on_cal_drag(self, ev):
        p = self._cal_press
        if not p or p[1] < self.HEADER:
            return
        if not p[2] and (ev.x - p[0]) ** 2 + (ev.y - p[1]) ** 2 < 36:
            return
        self._cal_press = (p[0], p[1], True)
        self.chart.cancel_pick()
        snap = lambda t: round(t / 300) * 300
        _, t0 = self._time_at(p[0], p[1])
        _, t1 = self._time_at(ev.x, ev.y, clamp=True)
        self.selection = (snap(min(t0, t1)), snap(max(t0, t1)))
        self.draw_calendar()

    def on_cal_release(self, ev):
        p, self._cal_press = self._cal_press, None
        if not p or p[1] < self.HEADER:
            return
        if p[2]:
            if self.selection:
                self.select_range(*self.selection)
            return
        hit = [self.seg_items[i] for i in self.canvas.find_overlapping(ev.x, ev.y, ev.x, ev.y)
               if i in self.seg_items]
        if hit:
            self.select_range(*hit[-1])
        else:
            self.cancel_selection()

    # ---------- summary ----------
    def draw_summary(self):
        s = self.store.day_summary(self.selected_day)
        span = s["span"]
        self.day_label.configure(text=f"{self.selected_day:%A %b %d}  —  Σ {fmt(span)}")

        tv = self.sum_tree
        tv.delete(*tv.get_children())
        for i, (name, sec) in enumerate(sorted(s["by_name"].items(), key=lambda kv: -kv[1])):
            tv.tag_configure(f"t{i}", foreground=self.color(*s["xy"][name]))
            tv.insert("", "end", text=f"■ {name}", values=(fmt(sec), f"{sec / span:.1%}"), tags=(f"t{i}",))
        if s["untracked"] > 0.5:
            tv.insert("", "end", text="Untracked", values=(fmt(s["untracked"]), f"{s['untracked'] / span:.1%}"))
        if s["future"] > 0:
            tv.insert("", "end", text="Rest of day", values=(fmt(s["future"]), f"{s['future'] / span:.1%}"))
        tv.insert("", "end", text="TOTAL", values=(fmt(span), "100%"))

        qt = self.quad_tree
        qt.delete(*qt.get_children())
        tracked = sum(s["quadrants"].values()) or 1
        for i, (q, sec) in enumerate(s["quadrants"].items()):
            qt.tag_configure(f"q{i}", foreground=self.color(*QUAD_XY[q]))
            qt.insert("", "end", text=f"■ {q}", values=(fmt(sec), f"{sec / tracked:.0%}"), tags=(f"q{i}",))
        c = s["center"]
        if c:
            self.center_label.configure(text=f"Day center:  {describe(*c)}", fg=self.color(*c))
        else:
            self.center_label.configure(text="Day center: —", fg=MUTED)

    def export_csv(self):
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")],
                                            initialfile=f"timeclock_{date.today()}.csv")
        if not path:
            return
        now = time.time()
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["task", "x_outdoor", "y_social", "start", "end", "duration_s"])
            for name, x, y, a, b in self.store.export_rows():
                w.writerow([name, x, y, datetime.fromtimestamp(a).isoformat(timespec="seconds"),
                            "" if b is None else datetime.fromtimestamp(b).isoformat(timespec="seconds"),
                            round((now if b is None else b) - a)])
        messagebox.showinfo("Exported", f"Saved to {path}")


def main():
    App().mainloop()
