"""
Afterglow - data for the sky map and compass that point to a target (a meteor radiant or a comet).

Positions are apparent altitude/azimuth for the observer (NASA JPL DE440s via Skyfield, with standard
refraction), every 20 minutes through the night.  Background stars: magnitude 3.5 and brighter from
the Yale Bright Star Catalogue, 5th ed. (assets/bright_stars.csv, J2000).
"""
import csv
import os
from datetime import timedelta
from functools import lru_cache

import numpy as np
from skyfield.api import Star

import astro

HERE = os.path.dirname(os.path.abspath(__file__))
PLANETS = [('Moon', 'moon'), ('Venus', 'venus'), ('Mars', 'mars barycenter'), ('Jupiter', 'jupiter barycenter'),
           ('Saturn', 'saturn barycenter'), ('Mercury', 'mercury')]


@lru_cache(maxsize=1)
def stars():
    rows = []
    with open(os.path.join(HERE, 'assets', 'bright_stars.csv'), encoding='utf-8') as f:
        for r in csv.DictReader(line for line in f if not line.startswith('#')):
            rows.append((float(r['ra_deg']), float(r['dec_deg']), float(r['vmag']), r['name'], r['con']))
    ra = np.array([r[0] for r in rows])
    dec = np.array([r[1] for r in rows])
    return Star(ra_hours=ra / 15.0, dec_degrees=dec), np.array([r[2] for r in rows]), [r[3] for r in rows]


def _altaz(obs, t, body, elev):
    a, z, _ = obs.at(t).observe(body).apparent().altaz()
    alt = a.degrees
    return alt + astro.refraction_deg(alt, astro.STD_T, astro.std_pressure(elev)), z.degrees


def night_times(win, step_min=20):
    n = int((win['end'] - win['start']).total_seconds() // (step_min * 60)) + 1
    return [win['start'] + timedelta(minutes=step_min * i) for i in range(n)]


def build(lat, lon, elev, tz, times, target, label, initial_time=None, kind='comet', hint=''):
    """Everything the browser needs to draw the sky dome and the compass."""
    obs = astro.observer(lat, lon, elev)
    t = astro.ts.from_datetimes(times)
    talt, taz = _altaz(obs, t, target, elev)
    salt, _ = _altaz(obs, t, astro.SUN, elev)
    S, mags, names = stars()
    star_frames = []
    for i in range(len(times)):
        a, z = _altaz(obs, t[i], S, elev)
        keep = a > -1
        star_frames.append([[round(float(x), 1), round(float(y), 1), round(float(m), 1), int(i_)]
                            for x, y, m, i_ in zip(z[keep], a[keep], mags[keep], np.nonzero(keep)[0])])
    bodies = []
    for name, key in PLANETS:
        a, z = _altaz(obs, t, astro.eph[key], elev)
        bodies.append(dict(name=name, alt=np.round(a, 1).tolist(), az=np.round(z, 1).tolist()))
    illum = float(astro.moon_phase(t[len(times) // 2])[1])
    if initial_time is not None:
        initial = int(np.argmin([abs((x - initial_time).total_seconds()) for x in times]))
    else:
        initial = int(np.argmax(np.where(salt < -12, talt, -99)))
    return dict(tz=tz, label=label, kind=kind, hint=hint, times=[int(x.timestamp() * 1000) for x in times],
                alt=np.round(talt, 1).tolist(), az=np.round(taz, 1).tolist(), sun=np.round(salt, 1).tolist(),
                stars=star_frames, star_names=[n if (n and mags[i] <= 1.6) else '' for i, n in enumerate(names)],
                bodies=bodies, moon_illum=illum, initial=initial)
