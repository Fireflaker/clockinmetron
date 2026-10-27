# clockinmetron

"- I don't have time. - Shut up. - We all have 24hr a day"

Clock in to one task at a time, so every day adds up to exactly 24h.
Tasks sit on an **Indoor ↔ Outdoor × Alone ↔ Social** map, and their colors come from where they sit.
That makes the calendar readable at a glance: more orange and green means more outdoor and social time.

![screenshot](screenshot.png)

## Run

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

- **Week calendar** and a **Live** tab where the current block fills in second by second.
- Sunrise and sunset markers, based on a location guessed from your timezone.
  You can override it in `data/settings.json` with `"location": "Boston"`.
- Themes, a quadrant split for each day, back-filling past blocks, and CSV export.

## Data (`data/timeline.db`, SQLite)

```
tags(name, x, y)      -- the chart
log (t, name, x, y)   -- the timeline: "from time t on, doing <name> at (x, y)"
```

Log rows have no end time, so gaps and overlaps are impossible. Colors are computed live from (x, y)
and the theme, never stored. Editing the chart never rewrites the timeline.

Tests: `python -m unittest discover tests`
