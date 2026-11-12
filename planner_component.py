"""Afterglow - the interactive planner (map + time slider + horizon panorama).

The browser part lives in assets/planner.js (with Leaflet 1.9.4, BSD-2 licence, bundled
in assets/leaflet.js so no outside script is loaded).  It runs in the app page itself
(isolate_styles=False), which the browser requires for 'Use my location' to work.
"""
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import streamlit as st

HERE = os.path.dirname(os.path.abspath(__file__))


def _read(name):
    with open(os.path.join(HERE, 'assets', name), encoding='utf-8') as f:
        return f.read()


_COMPONENT = st.components.v2.component(
    'afterglow_planner',
    js=_read('leaflet.js') + '\n;\n' + _read('planner.js'),
    css=_read('leaflet.css') + '\n' + _read('planner.css'),
    isolate_styles=False,
)

CHIPS = [  # event key, chip text, body
    ('dawn_civil', 'Blue hour', 'sun'),
    ('sun_m4_up', 'Golden hour', 'sun'),
    ('sunrise*', 'Sunrise', 'sun'),
    ('sun_p6_down', 'Golden hour', 'sun'),
    ('sunset*', 'Sunset', 'sun'),
    ('sun_m4_down', 'Blue hour', 'sun'),
    ('moonrise*', 'Moonrise', 'moon'),
    ('moonset*', 'Moonset', 'moon'),
]


def _main(events, body, kind):
    for k in (f'{body}{kind}', f'{body}{kind}_flat'):
        hits = [e for e in events if e['key'] == k]
        if hits:
            return hits[0] if kind == 'rise' else hits[-1]
    return None


def _ms(dt):
    return int(dt.timestamp() * 1000)


def build_data(loc, tz, day, day_res, profile, place_label):
    tr = day_res['track']
    ev = day_res['events']
    z = ZoneInfo(tz)
    r = lambda a, k=2: np.round(np.asarray(a, dtype=float), k).tolist()

    chips = []
    for key, text, body in CHIPS:
        if key.endswith('*'):
            b, kind = ('sun', key[3:-1]) if key.startswith('sun') else ('moon', key[4:-1])
            e = _main(ev, b, kind)
            es = [e] if e else []
        else:
            es = [e for e in ev if e['key'] == key]
        for e in es:
            chips.append(dict(short=text, body=body, ms=_ms(e['utc'])))
    chips.sort(key=lambda c: c['ms'])

    lines = []
    for body, kind, word in (('sun', 'rise', 'Sunrise'), ('sun', 'set', 'Sunset'),
                             ('moon', 'rise', 'Moonrise'), ('moon', 'set', 'Moonset')):
        e = _main(ev, body, kind)
        if e:
            lines.append(dict(kind=body + kind, az=round(e['az'], 2),
                              label=f"{word} {e['utc'].astimezone(z):%H:%M}"))

    now = datetime.now(timezone.utc)
    t0 = tr['t0_ms']
    t_end = t0 + (tr['n'] - 1) * tr['step_s'] * 1000
    now_ms = _ms(now) if t0 <= _ms(now) <= t_end else None
    sunset = _main(ev, 'sun', 'set')
    initial = now_ms or (_ms(sunset['utc']) if sunset else (t0 + t_end) // 2)

    if profile is not None:
        hz = r(profile['angle'], 2)
        ridge = [[round(float(a), 5), round(((float(b) + 540) % 360) - 180, 5), round(float(c), 2)]
                 for a, b, c in zip(profile['lat'], profile['lon'], profile['dist_km'])]
        hz_step = float(profile['az'][1] - profile['az'][0])
    else:
        hz, ridge, hz_step = [0.0] * 720, [], 0.5

    return dict(
        lat=round(loc['lat'], 6), lon=round(loc['lon'], 6), acc=loc.get('acc'), src=loc.get('src'),
        place=place_label, tz=tz, zoom=11,
        t0=t0, step=tr['step_s'], n=tr['n'],
        sun_az=r(tr['sun_az']), sun_alt=r(tr['sun_alt']), moon_az=r(tr['moon_az']), moon_alt=r(tr['moon_alt']),
        sun_sd=round(tr['sun_sd'], 4), moon_sd=round(tr['moon_sd'], 4),
        moon_illum=round(day_res['info']['moon_illum'], 3),
        hz_step=hz_step, hz=hz, ridge=ridge, events=chips, lines=lines,
        initial_ms=initial, now_ms=now_ms,
        nonce=f"{loc['lat']:.5f},{loc['lon']:.5f},{day.isoformat()}",
    )


def show(data, on_pick, key='planner'):
    return _COMPONENT(data=data, key=key, on_pick_change=on_pick,
                      width='stretch', height='content')
