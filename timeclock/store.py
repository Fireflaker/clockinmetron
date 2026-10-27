"""Storage: one SQLite file with plain tables.

    tags(name, x, y)        the palette shown on the chart (what you *can* clock into)
    log(t, name, x, y)      the timeline: "from time t on, I was doing <name> at (x, y)"
    schedules(id, name, hhmm, days, enabled, last_run)
                            auto clock-ins, e.g. Work at 09:00 on days "12345" (Mon=1 ? Sun=7)

A log row has no end time; it lasts until the next row's t (the last row runs until now).
So gaps/overlaps are impossible and every day always sums to 24h. name = NULL marks an
untracked stretch (only arises when back-filling before tracking began).
The timeline reads only `log`, and editing tags never rewrites it (changes apply from the
next clock-in), so deleting/renaming/moving a tag never touches past entries.
x: -1 indoor … +1 outdoor,  y: -1 alone … +1 social.
"""
import sqlite3
import time
from datetime import datetime, time as dtime, timedelta

DEFAULT_TAGS = [
    ("Sleep", -0.90, -0.90), ("Shower", -0.75, -0.70), ("Skincare", -0.55, -0.85),
    ("YouTube", -0.85, -0.45), ("Engineering", -0.45, -0.35), ("Chores", -0.20, -0.60),
    ("Cooking & Eating", -0.35, 0.15), ("Dating Apps", -0.65, 0.45), ("Gym", 0.15, 0.20),
    ("Walk outside", 0.80, -0.40), ("Friends / Going out", 0.60, 0.80),
]


def day_bounds(d):
    start = datetime.combine(d, dtime.min)
    return start.timestamp(), (start + timedelta(days=1)).timestamp()


class Store:
    def __init__(self, path, now=None):
        self.db = sqlite3.connect(path)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS tags (name TEXT PRIMARY KEY, x REAL NOT NULL, y REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS log  (t REAL PRIMARY KEY, name TEXT, x REAL, y REAL);
            CREATE TABLE IF NOT EXISTS schedules (id INTEGER PRIMARY KEY, name TEXT NOT NULL,
                hhmm TEXT NOT NULL, days TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, last_run REAL);
        """)
        if not self.db.execute("SELECT 1 FROM tags").fetchone():
            self.db.executemany("INSERT INTO tags VALUES (?,?,?)", DEFAULT_TAGS)
        if not self.current():
            name, x, y = self.tags()[0] if not self.tag("Sleep") else self.tag("Sleep")
            self.db.execute("INSERT INTO log VALUES (?,?,?,?)", (now or time.time(), name, x, y))
        self.db.commit()

    # ---------- tags (the chart) ----------
    def tags(self):
        return self.db.execute("SELECT name,x,y FROM tags ORDER BY name").fetchall()

    def tag(self, name):
        return self.db.execute("SELECT name,x,y FROM tags WHERE name=?", (name,)).fetchone()

    def add_tag(self, name, x, y):
        if self.tag(name):
            raise ValueError(f"'{name}' already exists.")
        self.db.execute("INSERT INTO tags VALUES (?,?,?)", (name, x, y))
        self.db.commit()

    # Tag edits touch only `tags`; the log is never rewritten, it applies from the next clock-in.
    def move_tag(self, name, x, y):
        self.db.execute("UPDATE tags SET x=?, y=? WHERE name=?", (x, y, name))
        self.db.commit()

    def rename_tag(self, old, new):
        if old != new and self.tag(new):
            raise ValueError(f"'{new}' already exists.")
        self.db.execute("UPDATE tags SET name=? WHERE name=?", (new, old))
        self.db.execute("UPDATE schedules SET name=? WHERE name=?", (new, old))
        self.db.commit()

    def delete_tag(self, name):
        self.db.execute("DELETE FROM tags WHERE name=?", (name,))
        self.db.commit()

    # ---------- log (the timeline) ----------
    def current(self):
        return self.db.execute("SELECT t,name,x,y FROM log ORDER BY t DESC LIMIT 1").fetchone()

    def first_start(self):
        return self.db.execute("SELECT MIN(t) FROM log WHERE name IS NOT NULL").fetchone()[0]

    def clock_in(self, name, now=None):
        _, x, y = self.tag(name)
        t, cur, cx, cy = self.current()
        if (cur, cx, cy) == (name, x, y):
            return
        now = now or time.time()
        if now - t < 1:
            self.db.execute("UPDATE log SET name=?, x=?, y=? WHERE t=?", (name, x, y, t))
        else:
            self.db.execute("INSERT INTO log VALUES (?,?,?,?)", (now, name, x, y))
        self._compact()

    def segments_between(self, s, e, now=None):
        """[(key_t, name, x, y, start, end)] covering [s, e); the running entry ends at now."""
        now = now or time.time()
        prev = self.db.execute("SELECT t,name,x,y FROM log WHERE t<=? ORDER BY t DESC LIMIT 1", (s,)).fetchall()
        mid = self.db.execute("SELECT t,name,x,y FROM log WHERE t>? AND t<? ORDER BY t", (s, e)).fetchall()
        nxt = self.db.execute("SELECT t FROM log WHERE t>=? ORDER BY t LIMIT 1", (e,)).fetchone()
        rows = prev + mid
        ends = [r[0] for r in rows[1:]] + [nxt[0] if nxt else now]
        return [(t, n, x, y, t, b) for (t, n, x, y), b in zip(rows, ends) if n is not None]

    def day_summary(self, d, now=None):
        """Seconds per task, quadrant split and time-weighted center of the day; parts sum to 24h."""
        now = now or time.time()
        ds, de = day_bounds(d)
        by_name, xy = {}, {}
        quads = {"Outdoor·Social": 0.0, "Indoor·Social": 0.0, "Indoor·Alone": 0.0, "Outdoor·Alone": 0.0}
        sx = sy = 0.0
        for _, name, x, y, a, b in self.segments_between(ds, de, now):
            dur = min(b, de, now) - max(a, ds)
            if dur <= 0:
                continue
            by_name[name] = by_name.get(name, 0) + dur
            xy[name] = (x, y)
            quads[("Outdoor" if x >= 0 else "Indoor") + "·" + ("Social" if y >= 0 else "Alone")] += dur
            sx, sy = sx + x * dur, sy + y * dur
        tracked = sum(by_name.values())
        span = de - ds
        future = max(0.0, de - max(now, ds))
        return dict(by_name=by_name, xy=xy, quadrants=quads, span=span, future=future,
                    untracked=span - tracked - future,
                    center=(sx / tracked, sy / tracked) if tracked else None)

    def log_block(self, name, s, e=None):
        """Overwrite [s, e) with <name>. e=None means 'from s until now, and keep running'."""
        _, x, y = self.tag(name)
        if e is None:
            self.db.execute("DELETE FROM log WHERE t>=?", (s,))
        else:
            after = self.db.execute("SELECT name,x,y FROM log WHERE t<=? ORDER BY t DESC LIMIT 1", (e,)).fetchone()
            self.db.execute("DELETE FROM log WHERE t>=? AND t<?", (s, e))
            self.db.execute("INSERT OR IGNORE INTO log VALUES (?,?,?,?)", (e, *(after or (None, None, None))))
        self.db.execute("INSERT INTO log VALUES (?,?,?,?)", (s, name, x, y))
        self._compact()

    def reassign(self, key_t, name):
        _, x, y = self.tag(name)
        self.db.execute("UPDATE log SET name=?, x=?, y=? WHERE t=?", (name, x, y, key_t))
        self._compact()

    def log_at(self, name, t):
        """Clock into <name> at time t (may be in the past; lasts until the next entry)."""
        _, x, y = self.tag(name)
        self.db.execute("INSERT OR REPLACE INTO log VALUES (?,?,?,?)", (t, name, x, y))
        self._compact()

    # ---------- schedules (auto clock-in) ----------
    def schedules(self):
        return self.db.execute("SELECT id,name,hhmm,days,enabled FROM schedules ORDER BY hhmm,name").fetchall()

    def add_schedule(self, name, hhmm, days, now=None):
        try:
            h, m = (int(v) for v in hhmm.split(":"))
        except ValueError:
            h = m = -1
        if not (0 <= h < 24 and 0 <= m < 60) or not days or set(days) - set("1234567"):
            raise ValueError("Use HH:MM (e.g. 09:00) and pick at least one day.")
        self.db.execute("INSERT INTO schedules (name,hhmm,days,enabled,last_run) VALUES (?,?,?,1,?)",
                        (name, f"{h:02d}:{m:02d}", "".join(sorted(set(days))), now or time.time()))
        self.db.commit()

    def set_schedule_enabled(self, sid, enabled, now=None):
        # Re-enabling never back-fills the time it was off.
        self.db.execute("UPDATE schedules SET enabled=?, last_run=? WHERE id=?",
                        (int(enabled), now or time.time(), sid))
        self.db.commit()

    def delete_schedule(self, sid):
        self.db.execute("DELETE FROM schedules WHERE id=?", (sid,))
        self.db.commit()

    def apply_schedules(self, now=None):
        """Fire every occurrence since each schedule's last run, at its exact time.
        Works lazily: if the app was closed at 09:00, the 09:00 clock-in is back-filled on next open.
        Returns the names clocked into, in order."""
        now = now or time.time()
        due = []
        rows = self.db.execute("SELECT id,name,hhmm,days,last_run FROM schedules WHERE enabled=1").fetchall()
        for sid, name, hhmm, days, last in rows:
            h, m = (int(v) for v in hhmm.split(":"))
            d = datetime.fromtimestamp(last or now).date()
            while d <= datetime.fromtimestamp(now).date():
                t = datetime.combine(d, dtime(h, m)).timestamp()
                if str(d.isoweekday()) in days and (last or now) < t <= now and self.tag(name):
                    due.append((t, name))
                d += timedelta(days=1)
            self.db.execute("UPDATE schedules SET last_run=? WHERE id=?", (now, sid))
        for t, name in sorted(due):
            self.log_at(name, t)
        self.db.commit()
        return [n for _, n in sorted(due)]

    def _compact(self):
        """Merge consecutive identical entries and drop leading 'untracked' markers."""
        self.db.execute("""
            DELETE FROM log WHERE t IN (
                SELECT t FROM (SELECT t, name, x, y,
                        LAG(t) OVER w AS pt, LAG(name) OVER w AS pn, LAG(x) OVER w AS px, LAG(y) OVER w AS py
                    FROM log WINDOW w AS (ORDER BY t))
                WHERE (pt IS NOT NULL AND name IS pn AND x IS px AND y IS py)
                   OR (pt IS NULL AND name IS NULL))""")
        self.db.commit()

    def export_rows(self, now=None):
        """[(name, x, y, start, end_or_None)] for CSV export."""
        now = now or time.time()
        rows = self.db.execute("SELECT t,name,x,y FROM log ORDER BY t").fetchall()
        ends = [r[0] for r in rows[1:]] + [None]
        return [(n, x, y, t, e) for (t, n, x, y), e in zip(rows, ends) if n is not None]

    # ---------- sync document (same JSON shape as the phone app) ----------
    def doc(self):
        return {
            "tags": [{"name": n, "x": x, "y": y} for n, x, y in self.tags()],
            "log": [list(r) for r in self.db.execute("SELECT t,name,x,y FROM log ORDER BY t")],
            "schedules": [{"id": i, "name": n, "hhmm": h, "days": d, "on": bool(e), "last": l}
                          for i, n, h, d, e, l in self.db.execute(
                              "SELECT id,name,hhmm,days,enabled,last_run FROM schedules ORDER BY id")],
        }

    def replace_doc(self, doc):
        """Replace tags, log and schedules with <doc> (used by sync). Keeps the later last_run per schedule."""
        last = dict(self.db.execute("SELECT id,last_run FROM schedules"))
        with self.db:
            self.db.execute("DELETE FROM tags")
            self.db.execute("DELETE FROM log")
            self.db.execute("DELETE FROM schedules")
            self.db.executemany("INSERT OR REPLACE INTO tags VALUES (?,?,?)",
                                [(t["name"], t["x"], t["y"]) for t in doc["tags"]])
            self.db.executemany("INSERT OR REPLACE INTO log VALUES (?,?,?,?)", [tuple(r) for r in doc["log"]])
            self.db.executemany("INSERT OR REPLACE INTO schedules VALUES (?,?,?,?,?,?)",
                                [(s["id"], s["name"], s["hhmm"], s["days"], int(bool(s["on"])),
                                  max(s.get("last") or 0, last.get(s["id"]) or 0) or None)
                                 for s in doc["schedules"]])
        self._compact()
