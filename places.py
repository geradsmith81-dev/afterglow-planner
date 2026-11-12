"""Afterglow - time zones and an offline gazetteer (GeoNames cities, via geonamescache)."""
import math
from functools import lru_cache

import numpy as np


@lru_cache(maxsize=1)
def _tf():  # timezonefinder >= 8 (older releases break with h3 v4)
    try:
        from timezonefinder import TimezoneFinder
        return TimezoneFinder()
    except Exception:
        return None


@lru_cache(maxsize=256)
def tz_at(lat, lon):
    tf = _tf()
    if tf is not None:
        try:
            z = tf.timezone_at(lat=lat, lng=lon) or tf.certain_timezone_at(lat=lat, lng=lon)
            if z:
                return z
        except Exception:
            pass
    # second source: Open-Meteo answers with the IANA time zone of any coordinate
    try:
        import requests
        r = requests.get('https://api.open-meteo.com/v1/forecast',
                         params=dict(latitude=f'{lat:.4f}', longitude=f'{lon:.4f}', timezone='auto',
                                     current='temperature_2m'), timeout=15)
        z = r.json().get('timezone') if r.status_code == 200 else None
        if z and z not in ('GMT', 'UTC'):
            return z
    except Exception:
        pass
    # last resort: nautical time zone
    off = int(round(lon / 15.0))
    return 'UTC' if off == 0 else f'Etc/GMT{-off:+d}'


@lru_cache(maxsize=1)
def _cities():
    import geonamescache
    gc = geonamescache.GeonamesCache()
    rows = []
    for c in gc.get_cities().values():
        rows.append((c['name'], c.get('countrycode', ''), float(c['latitude']), float(c['longitude']),
                     int(c.get('population') or 0), c.get('timezone', '')))
    names = [r[0] for r in rows]
    cc = [r[1] for r in rows]
    lat = np.array([r[2] for r in rows])
    lon = np.array([r[3] for r in rows])
    pop = np.array([r[4] for r in rows])
    tzs = [r[5] for r in rows]
    return names, cc, lat, lon, pop, tzs


def nearest_town(lat, lon, max_km=60.0):
    try:
        names, cc, la, lo, pop, _ = _cities()
    except Exception:
        return None
    p1, p2 = np.radians(lat), np.radians(la)
    dl = np.radians(lo - lon)
    d = 6371.0 * np.arccos(np.clip(np.sin(p1) * np.sin(p2) + np.cos(p1) * np.cos(p2) * np.cos(dl), -1, 1))
    i = int(np.argmin(d))
    if d[i] > max_km:
        return None
    return dict(name=names[i], country=cc[i], km=float(d[i]))


def largest_in_tz(tz):
    """Most populous gazetteer city in a time zone, as a starting place."""
    if not tz:
        return None
    try:
        names, cc, la, lo, pop, tzs = _cities()
    except Exception:
        return None
    best = None
    for i, z in enumerate(tzs):
        if z == tz and (best is None or pop[i] > pop[best]):
            best = i
    if best is None:
        return None
    return dict(name=f'{names[best]}, {cc[best]}', lat=float(la[best]), lon=float(lo[best]))


def describe(lat, lon):
    t = nearest_town(lat, lon)
    if t is None:
        return f'{lat:.4f}, {lon:.4f}'
    if t['km'] < 2:
        return f"{t['name']}, {t['country']}"
    return f"{t['km']:.0f} km from {t['name']}, {t['country']}"
