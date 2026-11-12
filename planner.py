"""
Afterglow - puts astronomy, terrain and weather together for one place.
No Streamlit here, so it can be tested on its own.
"""
import math
from datetime import timedelta

import numpy as np

import astro
import skycolor as sc
import weather as wx


def _day_mean(fc, key, start, end):
    if fc is None or key not in fc:
        return float('nan')
    tt, v = fc['time'], fc[key]
    m = (tt >= start.timestamp()) & (tt <= end.timestamp()) & np.isfinite(v)
    return float(np.mean(v[m])) if m.any() else float('nan')


def main_event(events, body, kind):
    """Terrain event if there is one, else the flat-horizon event.  Rise = first, set = last."""
    keys = [f'{body}{kind}', f'{body}{kind}_flat']
    for k in keys:
        hits = [e for e in events if e['key'] == k]
        if hits:
            return hits[0] if kind == 'rise' else hits[-1]
    return None


def compute_days(lat, lon, tz, first_day, n_days, profile, obs_fc, elev=None):
    if elev is None:
        elev = profile['h_obs'] if profile else 0.0
    out = []
    for i in range(n_days):
        day = first_day + timedelta(days=i)
        a, b = astro.local_day_bounds(day, tz)
        T = _day_mean(obs_fc, 'temperature_2m', a, b)
        P = _day_mean(obs_fc, 'surface_pressure', a, b)
        T = T if math.isfinite(T) else None
        P = P if math.isfinite(P) else None
        out.append(dict(day=day, res=astro.compute_day(lat, lon, elev, day, tz, profile, T, P, light=i > 0)))
    return out


def score_days(lat, lon, days, obs_fc, aq, ground_m, model):
    """Adds 'sunrise'/'sunset' dicts with event + colour assessment to each day entry,
    and moonrise/moonset visibility to the first day."""
    jobs = []
    for i, d in enumerate(days):
        ev = d['res']['events']
        for kind, body, k in (('sunrise', 'sun', 'rise'), ('sunset', 'sun', 'set')):
            e = main_event(ev, body, k)
            d[kind] = dict(event=e, assessment=None)
            if e is not None:
                jobs.append((i, kind, e, sc.ray_points(lat, lon, e['az'])))
        if i == 0:
            for kind, body, k in (('moonrise', 'moon', 'rise'), ('moonset', 'moon', 'set')):
                e = main_event(ev, body, k)
                d[kind] = dict(event=e, visibility=None)
                if e is not None:
                    jobs.append((i, kind, e, sc.ray_points(lat, lon, e['az'])[:2]))
    if obs_fc is None:
        return days, None
    pts = [p for j in jobs for p in j[3]]
    err = None
    try:
        ray_fc = wx.ray_forecast(pts, model) if pts else []
    except wx.WeatherError as ex:
        ray_fc, err = [None] * len(pts), str(ex)
    k = 0
    for (i, kind, e, p) in jobs:
        series = ray_fc[k:k + len(p)]
        k += len(p)
        t = e['utc'].timestamp()
        if kind in ('sunrise', 'sunset'):
            prof = wx.cloud_profile(obs_fc, t, ground_m)
            h_km, src = sc.cloud_height_for_canvas(prof, wx.at(obs_fc, 'cloud_cover_mid', t),
                                                   wx.at(obs_fc, 'cloud_cover_high', t))
            a = sc.assess(kind, t, obs_fc, series, aq, ground_m, canvas_km=h_km)
            if a is not None:
                a['canvas_km_source'] = src
                a['profile'] = prof
                a['ray_points'] = p
            days[i][kind]['assessment'] = a
        else:
            days[i][kind]['visibility'] = sc.moon_visibility(t, obs_fc, series)
    return days, err
