"""
Afterglow - aurora data from NOAA's Space Weather Prediction Center (https://www.swpc.noaa.gov).

  * OVATION Prime aurora nowcast: probability (%) of visible aurora overhead on a 1 deg grid,
    valid about 30-90 minutes ahead (updated every few minutes);
  * planetary Kp index: observed values and the 3-day forecast in 3-hour blocks;
  * real-time solar wind at L1: magnetic field Bz (southward = negative favours aurora) and speed.

Geomagnetic latitude uses the IGRF-14 dipole for 2025 (pole about 80.8 N, 72.8 W).
The Kp rule of thumb (equatorward edge of the auroral oval at about 66 - 2 x Kp degrees
geomagnetic latitude, visible low on the horizon about 5 deg further away) is an
approximation of NOAA's Kp maps, not an exact law.
"""
import math
from datetime import datetime, timezone

import numpy as np
import requests

SWPC = "https://services.swpc.noaa.gov/"
_s = requests.Session()

# IGRF-14, epoch 2025.0, degree-1 Gauss coefficients (nT)
G10, G11, H11 = -29350.0, -1410.3, 4545.5
_B0 = math.sqrt(G10 ** 2 + G11 ** 2 + H11 ** 2)
POLE_LAT = 90.0 - math.degrees(math.acos(-G10 / _B0))
POLE_LON = math.degrees(math.atan2(-H11, -G11))


class SpaceWeatherError(RuntimeError):
    pass


def _get(path, timeout=30):
    try:
        r = _s.get(SWPC + path, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except (requests.RequestException, ValueError) as e:
        raise SpaceWeatherError(f'NOAA SWPC unavailable ({type(e).__name__}).')


def _t(s):
    s = s.replace('Z', '')
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def geomagnetic_latitude(lat, lon):
    p, l = math.radians(POLE_LAT), math.radians(POLE_LON)
    a, b = math.radians(lat), math.radians(lon)
    s = math.sin(a) * math.sin(p) + math.cos(a) * math.cos(p) * math.cos(b - l)
    return math.degrees(math.asin(max(-1.0, min(1.0, s))))


def oval_edge(kp):
    """Approximate geomagnetic latitude of the oval's equatorward edge for a Kp value."""
    return 66.0 - 2.0 * kp


def kp_needed(mlat_abs):
    """Kp at which aurora is overhead / low on the poleward horizon at |geomagnetic latitude|."""
    overhead = (66.0 - mlat_abs) / 2.0
    horizon = (66.0 - (mlat_abs + 5.0)) / 2.0
    return max(0.0, overhead), max(0.0, horizon)


def outlook(mlat_abs, kp):
    edge = oval_edge(kp)
    if mlat_abs >= edge:
        return 'overhead possible'
    if mlat_abs >= edge - 5.0:
        return 'low on the horizon'
    return 'unlikely'


def ovation():
    j = _get('json/ovation_aurora_latest.json')
    grid = np.zeros((181, 360), dtype=np.float32)
    for lon, lat, v in j['coordinates']:
        grid[int(lat) + 90, int(lon) % 360] = v
    return dict(grid=grid, observed=_t(j['Observation Time']), forecast=_t(j['Forecast Time']))


def ovation_at(ov, lat, lon, reach_km=1000.0):
    """Probability overhead at the place, and a 'can I see it somewhere in my sky' value:
    the strongest nearby aurora, weighted down linearly with distance (aurora at 100-300 km
    height is visible low on the horizon up to roughly 1000 km away)."""
    g = ov['grid']
    here = float(g[int(round(lat)) + 90, int(round(lon)) % 360])
    best, best_d, best_az = here, 0.0, None
    la = np.arange(-90, 91)
    lo = np.arange(0, 360)
    p1 = math.radians(lat)
    rows = np.where(np.abs(la - lat) <= reach_km / 111.0 + 1)[0]
    for i in rows:
        vals = g[i]
        idx = np.nonzero(vals >= 3)[0]
        if not len(idx):
            continue
        p2 = math.radians(la[i])
        dl = np.radians(lo[idx] - lon)
        d = 6371.0 * np.arccos(np.clip(math.sin(p1) * math.sin(p2) + math.cos(p1) * math.cos(p2) * np.cos(dl), -1, 1))
        w = np.clip(1.0 - np.maximum(d - 300.0, 0) / (reach_km - 300.0), 0, 1)
        eff = vals[idx] * w
        k = int(np.argmax(eff))
        if eff[k] > best:
            best, best_d = float(eff[k]), float(d[k])
            y = math.sin(dl[k]) * math.cos(p2)
            x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl[k])
            best_az = (math.degrees(math.atan2(y, x)) + 360) % 360
    return dict(overhead=here, visible=best, dist_km=best_d, az=best_az)


def ovation_cells(ov, lat, lon, radius_km=3500.0, min_val=3):
    """[[lat, lon, value], ...] for map drawing, limited to the region around the user."""
    g = ov['grid']
    out = []
    for i in range(181):
        la = i - 90
        if abs(la - lat) * 111.0 > radius_km:
            continue
        for j in np.nonzero(g[i] >= min_val)[0]:
            lo = ((int(j) + 180) % 360) - 180
            dlon = (lo - lon + 540) % 360 - 180
            if abs(dlon) * 111.0 * max(0.2, math.cos(math.radians(la))) > radius_km:
                continue
            out.append([la, lon + dlon, int(g[i, j])])
    return out


def kp_series():
    """Observed + estimated + predicted Kp (3-hour blocks)."""
    j = _get('products/noaa-planetary-k-index-forecast.json')
    out = []
    for row in j:
        if isinstance(row, dict):
            t, kp, kind = row.get('time_tag'), row.get('kp'), row.get('observed')
        else:                       # older array-of-arrays format
            if row[0] == 'time_tag':
                continue
            t, kp, kind = row[0], row[1], row[2]
        try:
            out.append(dict(time=_t(t), kp=float(kp), kind=str(kind)))
        except (TypeError, ValueError):
            continue
    return out


def solar_wind():
    m = _get('products/summary/solar-wind-mag-field.json')
    v = _get('products/summary/solar-wind-speed.json')
    m = m[0] if isinstance(m, list) else m
    v = v[0] if isinstance(v, list) else v
    return dict(bz=float(m.get('bz_gsm')), bt=float(m.get('bt')), time=_t(m.get('time_tag')),
                speed=float(v.get('proton_speed')))
