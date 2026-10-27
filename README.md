# clockinmetron

"- I don't have time. - Shut up. - We all have 24hr a day"

Clock in to one task at a time, so every day adds up to exactly 24h.
Tasks sit on an **Indoor ↔ Outdoor × Alone ↔ Social** map, and their colors come from where they sit.
That makes the calendar readable at a glance: more orange and green means more outdoor and social time.

![screenshot](screenshot.png)

## Phone (Android & iPhone)

**https://fireflaker.github.io/clockinmetron/android/**

- **Android:** open the link in Chrome, then tap ⋮ → **Install app**.
- **iPhone / iPad:** open the link in **Safari**, then tap Share ⬆ → **Add to Home Screen**.

It runs full-screen, works offline and has the same features. Without Sync, each device keeps its own data.
Use **More → Export JSON** to back it up.

![android](screenshot_android.png)

## Sync (free, through a private GitHub Gist)

Phones and the PC can share one dataset stored in a secret gist on your GitHub account.

1. Open **[this pre-filled token page](https://github.com/settings/personal-access-tokens/new?name=clockinmetron+sync&description=Sync+clockinmetron+through+one+private+gist&expires_in=none&gists=write)**
   and click **Generate token**. It already has the only permission needed: **Gists: Read and write**.
   To do it by hand, go to Settings → Developer settings → Fine-grained tokens. In the permissions picker, open the
   **Account** tab (not Repository) and add **Gists** with Read and write.
   An existing token can be edited the same way and keeps its value.
2. Paste the token on each device:
   - Phone: **More → Sync**.
   - PC: the **☁ Sync…** button.
3. The first device creates the gist. Each later device asks whether to **use the synced data** (recommended for a
   new device) or **merge** both.

Syncing runs at startup, about 1 s after each change (clock-in, task move, edit), and every minute. Each sync is 2–3 API calls, far below GitHub's 5,000 requests/hour.
If only one side changed, that version wins. If both changed offline, they are merged: all tasks and timeline rows
are kept, and the device syncing at that moment wins ties.
The token is stored only on each device (`data/settings.json` on the PC, app storage on the phone) and is never
exported. Note that on iPhone the home-screen app has its own storage, separate from Safari, so set up Sync inside the
installed app.

## Run (Windows / desktop)

```powershell
python run.py
```

On first launch this creates a `.venv` and installs `requirements.txt` (numpy, Pillow, astral, tzlocal).
Python 3.10+ with tkinter is required.

## Use

| Action | Effect |
| --- | --- |
| **Click a dot** | Clock in |
| Drag a dot | Move the task (affects new entries only) |
| Click empty space | Add a task there |
| Right-click a dot | Rename / delete |
| Wheel / drag empty space | Zoom / pan; right-click empty space resets |
| **Drag over the calendar** (or click a block) | Pick the task that time range should be on the chart |

On the phone: tap a dot to clock in, drag to move it, hold to edit, tap empty space to add a task, pinch to zoom.
In the Day view, hold then drag to select a range.

- **Week calendar** and a **Live** tab where the current block fills in second by second. The Live strip is split:
  **top half** = drag (or click a block) to reassign; **bottom half** = drag to scroll, wheel / pinch to zoom.
  **● LIVE** jumps back to now.
- **Auto clock-in**: for example *Engineering at 09:00 Mon–Fri*. There is no clock-out. If the app was closed at that
  time, the entry is back-filled at the exact time when it next opens.
- Sunrise and sunset markers, plus a **% of day / night** bar. The desktop location is guessed from your timezone; you
  can override it in `data/settings.json` with `"location": "Boston"`. On the phone, set it under More.
- Themes, a quadrant split for each day, and CSV export.

## Data (`data/timeline.db`, SQLite)

```
tags(name, x, y)      -- the chart
log (t, name, x, y)   -- the timeline: "from time t on, doing <name> at (x, y)"
schedules(name, hhmm, days, enabled, last_run)   -- auto clock-in
```

Log rows have no end time, so gaps and overlaps are impossible. Colors are computed live from (x, y)
and the theme, never stored. Editing the chart never rewrites the timeline. The phone app keeps the same structure in
browser storage (`android/app.js`). Sync stores the same three lists as one JSON file (`timeclock/sync.py`).

Tests: `python -m unittest discover tests`
