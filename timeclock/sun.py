"""Sunrise / sunset for the local area, via the `astral` library.

The location comes from data/settings.json "location" if set: a city name from astral's database
(e.g. "Boston") or {"lat": 42.36, "lon": -71.06}. Otherwise it's guessed from the system timezone
(America/New_York -> New York). Nothing is sent over the network.
"""
from datetime import date, datetime
from functools import lru_cache

from astral import LocationInfo, Observer
from astral.geocoder import all_locations, database, lookup
from astral.sun import sunrise, sunset
import tzlocal


def resolve_location(setting=None):
    """Return (label, Observer) or (None, None) if nothing matches."""
    try:
        if isinstance(setting, dict):
            return (setting.get("name") or f"{setting['lat']:.2f}, {setting['lon']:.2f}",
                    Observer(setting["lat"], setting["lon"]))
        db = database()
        if isinstance(setting, str) and setting.strip():
            loc = lookup(setting.strip(), db)
            return loc.name, loc.observer
        tz = tzlocal.get_localzone_name()
        city = tz.split("/")[-1].replace("_", " ")
        try:
            loc = lookup(city, db)
            if isinstance(loc, LocationInfo):
                return loc.name, loc.observer
        except KeyError:
            pass
        locs = list(all_locations(db))
        for loc in locs:
            if loc.timezone == tz:
                return loc.name, loc.observer
        offset = datetime.now().astimezone().utcoffset()
        for loc in locs:
            if datetime.now(loc.tzinfo).utcoffset() == offset:
                return f"{loc.name} (same timezone)", loc.observer
    except Exception:
        pass
    return None, None


class Sun:
    def __init__(self, setting=None):
        self.label, self.observer = resolve_location(setting)
        self.tz = tzlocal.get_localzone()

    @lru_cache(maxsize=64)
    def times(self, d: date):
        """(sunrise_ts, sunset_ts) for local date d; either may be None (polar day/night or unknown)."""
        if self.observer is None:
            return None, None
        out = []
        for fn in (sunrise, sunset):
            try:
                out.append(fn(self.observer, date=d, tzinfo=self.tz).timestamp())
            except ValueError:
                out.append(None)
        return tuple(out)
