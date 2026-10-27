"""Auto clock-in tab: "clock into <task> at HH:MM on <days>". Applied by Store.apply_schedules()."""
import tkinter as tk
from tkinter import messagebox, ttk

BG, PANEL, FG, MUTED = "#1e1f24", "#2a2c33", "#e8e8ea", "#8a8c96"
DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
PRESETS = [("Weekdays", "12345"), ("Weekend", "67"), ("Every day", "1234567")]


def days_text(days):
    for label, d in PRESETS:
        if days == d:
            return label
    return ", ".join(DAY_NAMES[int(c) - 1] for c in days)


class SchedulesView(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=BG)
        self.app = app
        btn = dict(bg=PANEL, fg=FG, relief="flat", padx=10, pady=3, font=("Segoe UI", 10))

        tk.Label(self, text="Auto clock-in", bg=BG, fg=FG, font=("Segoe UI", 14, "bold")).pack(anchor="w", padx=10,
                                                                                            pady=(10, 0))
        tk.Label(self, bg=BG, fg=MUTED, justify="left", anchor="w",
                 text="Clocks you in automatically, e.g. Work at 09:00 Mon–Fri. No clock-out needed: the task runs\n"
                      "until you (or another schedule) clock into something else. If the app was closed at that\n"
                      "moment, the entry is back-filled at the exact time the next time it opens.").pack(
            fill="x", padx=10, pady=(2, 8))

        form = tk.Frame(self, bg=PANEL, padx=10, pady=8)
        form.pack(fill="x", padx=10)
        tk.Label(form, text="Clock in to", bg=PANEL, fg=FG).grid(row=0, column=0, sticky="w")
        self.task = ttk.Combobox(form, state="readonly", width=22)
        self.task.grid(row=0, column=1, sticky="w", padx=6)
        tk.Button(form, text="◎ pick on chart", command=self.pick_task, **btn).grid(row=0, column=2, sticky="w")
        tk.Label(form, text="at (HH:MM)", bg=PANEL, fg=FG).grid(row=1, column=0, sticky="w", pady=6)
        self.hhmm = ttk.Entry(form, width=8)
        self.hhmm.insert(0, "09:00")
        self.hhmm.grid(row=1, column=1, sticky="w", padx=6)
        tk.Label(form, text="on", bg=PANEL, fg=FG).grid(row=2, column=0, sticky="w")
        days = tk.Frame(form, bg=PANEL)
        days.grid(row=2, column=1, columnspan=3, sticky="w", padx=4)
        self.day_vars = []
        for i, n in enumerate(DAY_NAMES):
            v = tk.BooleanVar(value=i < 5)
            tk.Checkbutton(days, text=n, variable=v, bg=PANEL, fg=FG, selectcolor=BG, activebackground=PANEL,
                           activeforeground=FG).pack(side="left")
            self.day_vars.append(v)
        presets = tk.Frame(form, bg=PANEL)
        presets.grid(row=3, column=1, columnspan=3, sticky="w", padx=4, pady=(4, 0))
        for label, d in PRESETS:
            tk.Button(presets, text=label, command=lambda d=d: self.set_days(d), **btn).pack(side="left", padx=(0, 4))
        tk.Button(form, text="＋ Add", command=self.add, bg="#3fae6a", fg="white", relief="flat", padx=16,
                  font=("Segoe UI", 11, "bold")).grid(row=0, column=3, rowspan=2, padx=(16, 0))

        self.tree = ttk.Treeview(self, columns=("Time", "Days", "On"), height=8)
        for col, text, w, anchor in (("#0", "Task", 180, "w"), ("Time", "Time", 70, "center"),
                                     ("Days", "Days", 200, "w"), ("On", "On", 50, "center")):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=w, anchor=anchor)
        self.tree.pack(fill="both", expand=True, padx=10, pady=(10, 4))
        self.tree.bind("<Double-1>", lambda e: self.toggle())
        row = tk.Frame(self, bg=BG)
        row.pack(fill="x", padx=10, pady=(0, 10))
        tk.Button(row, text="Turn on / off", command=self.toggle, **btn).pack(side="left", padx=(0, 4))
        tk.Button(row, text="Delete", command=self.delete, **btn).pack(side="left")
        self.refresh()

    def set_days(self, days):
        for i, v in enumerate(self.day_vars):
            v.set(str(i + 1) in days)

    def pick_task(self):
        def done(name):
            if name:
                self.task.set(name)
        self.app.cancel_selection()
        self.app.chart.pick("Auto clock-in: which task?", done)

    def refresh(self):
        names = [n for n, _, _ in self.app.store.tags()]
        self.task.configure(values=names)
        if self.task.get() not in names:
            self.task.set(names[0] if names else "")
        self.tree.delete(*self.tree.get_children())
        for sid, name, hhmm, days, on in self.app.store.schedules():
            missing = self.app.store.tag(name) is None
            self.tree.insert("", "end", iid=str(sid), text=name + ("  (task deleted)" if missing else ""),
                             values=(hhmm, days_text(days), "✔" if on else "—"))

    def add(self):
        days = "".join(str(i + 1) for i, v in enumerate(self.day_vars) if v.get())
        try:
            if not self.task.get():
                raise ValueError("Choose a task.")
            self.app.store.add_schedule(self.task.get(), self.hhmm.get().strip(), days)
        except ValueError as ex:
            messagebox.showerror("Can't add", str(ex) or "Use HH:MM, e.g. 09:00.", parent=self)
            return
        self.refresh()

    def _selected(self):
        sel = self.tree.selection()
        return int(sel[0]) if sel else None

    def toggle(self):
        sid = self._selected()
        if sid is None:
            return
        on = next(r[4] for r in self.app.store.schedules() if r[0] == sid)
        self.app.store.set_schedule_enabled(sid, not on)
        self.refresh()
        self.tree.selection_set(str(sid))

    def delete(self):
        sid = self._selected()
        if sid is not None:
            self.app.store.delete_schedule(sid)
            self.refresh()
