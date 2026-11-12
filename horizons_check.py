"""
Afterglow - independent check against NASA JPL Horizons (https://ssd.jpl.nasa.gov/horizons/).

The app computes everything locally from JPL's DE440s ephemeris.  This module asks the
Horizons service itself for the refracted apparent elevation and angular diameter of the
Sun or Moon minute by minute around each flat-horizon rise/set time, and interpolates the
moment the upper limb touches 0 deg.  The two answers normally agree within a few seconds;
the remaining difference comes from the two refraction formulas.
"""
import re
from datetime import datetime, timedelta, timezone

import requests

API = "https://ssd.jpl.nasa.gov/api/horizons.api"
BODY_ID = {'sun': '10', 'moon': '301'}
_LINE = re.compile(r'\s*(\d{4}-\w{3}-\d{2} \d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)\s(.{2})\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)')


def _query(body, lat, lon, elev_km, start, stop, step='1m'):
    q = dict(format='json', COMMAND=f"'{BODY_ID[body]}'", OBJ_DATA="'NO'", MAKE_EPHEM="'YES'",
             EPHEM_TYPE="'OBSERVER'", CENTER="'coord@399'", COORD_TYPE="'GEODETIC'",
             SITE_COORD=f"'{lon:.6f},{lat:.6f},{elev_km:.4f}'",
             START_TIME=f"'{start:%Y-%m-%d %H:%M}'", STOP_TIME=f"'{stop:%Y-%m-%d %H:%M}'",
             STEP_SIZE=f"'{step}'", QUANTITIES="'4,13'", APPARENT="'REFRACTED'",
             TIME_DIGITS="'SECONDS'", ANG_FORMAT="'DEG'", EXTRA_PREC="'YES'")
    r = requests.get(API, params=q, timeout=60)
    r.raise_for_status()
    res = r.json().get('result', '')
    a, b = res.find('$$SOE'), res.find('$$EOE')
    if a < 0:
        raise RuntimeError('JPL Horizons did not return an ephemeris: ' + res[:200])
    rows = []
    for ln in res[a + 5:b].strip().splitlines():
        m = _LINE.match(ln)
        if not m:
            continue
        ts = m.group(1)
        fmt = '%Y-%b-%d %H:%M:%S' if ts.count(':') == 2 else '%Y-%b-%d %H:%M'
        t = datetime.strptime(ts[:20], fmt).replace(tzinfo=timezone.utc)
        az, el, diam_arcsec = float(m.group(3)), float(m.group(4)), float(m.group(5))
        rows.append((t, az, el, diam_arcsec))
    return rows


def limb_crossing(body, lat, lon, around_utc, kind):
    """Horizons' own upper-limb rise/set time near `around_utc` (sea-level site,
    Horizons' standard refraction).  Returns (datetime UTC, azimuth deg) or None."""
    a = (around_utc - timedelta(minutes=6)).replace(second=0, microsecond=0)
    b = a + timedelta(minutes=13)
    rows = _query(body, lat, lon, 0.0, a, b)
    vals = [(t, az, el + d / 7200.0) for (t, az, el, d) in rows]     # el + radius (deg)
    for (t0, az0, v0), (t1, az1, v1) in zip(vals, vals[1:]):
        if (v0 <= 0 < v1 and kind == 'rise') or (v0 > 0 >= v1 and kind == 'set'):
            f = v0 / (v0 - v1)
            t = t0 + (t1 - t0) * f
            return t, az0 + (az1 - az0) * f
    return None


def compare(events, lat, lon):
    """events: astro flat-horizon events (computed for a sea-level site).
    Returns list of dicts with both times and the difference in seconds."""
    out = []
    for e in events:
        if not e['flat'] or e['kind'] not in ('rise', 'set'):
            continue
        try:
            hit = limb_crossing(e['body'], lat, lon, e['utc'], e['kind'])
        except Exception as ex:          # network or service problem
            out.append(dict(event=f"{e['body']}{e['kind']}", app=e['utc'], jpl=None, diff_s=None, error=str(ex)))
            continue
        if hit is None:
            out.append(dict(event=f"{e['body']}{e['kind']}", app=e['utc'], jpl=None, diff_s=None,
                            error='no crossing found'))
            continue
        out.append(dict(event=f"{e['body']}{e['kind']}", app=e['utc'], jpl=hit[0],
                        diff_s=(e['utc'] - hit[0]).total_seconds(), app_az=e['az'], jpl_az=hit[1], error=None))
    return out
