"""Afterglow - the night map (stargazing forecast grid, aurora oval, light pollution, hour slider).
Browser code: assets/nightmap.js with Leaflet 1.9.4 bundled in front of it."""
import os
from datetime import datetime, timezone

import numpy as np
import streamlit as st

HERE = os.path.dirname(os.path.abspath(__file__))


def _read(name):
    with open(os.path.join(HERE, 'assets', name), encoding='utf-8') as f:
        return f.read()


_COMPONENT = st.components.v2.component(
    'afterglow_nightmap',
    js=_read('leaflet.js') + '\n;\n' + _read('nightmap.js'),
    css=_read('leaflet.css') + '\n' + _read('planner.css') + '\n' + _read('nightmap.css'),
    isolate_styles=False,
)


def build_data(loc, tz, day, place_label, win, pts, scores, clouds, details, ov_cells, step_km):
    hours_ms = [int(t.timestamp() * 1000) for t in win['hours']]
    now = datetime.now(timezone.utc).timestamp() * 1000
    if hours_ms[0] <= now <= hours_ms[-1] + 3600_000:
        initial = int(np.argmin([abs(h - now) for h in hours_ms]))
    else:   # first hour of full darkness, or the middle of the night
        dark = [k for k, t in enumerate(win['hours']) if win['sun_alt'][k] <= -18]
        initial = dark[0] if dark else len(hours_ms) // 2
    lat0 = loc['lat']
    hlat = step_km / 2 / 111.2
    hlon = step_km / 2 / (111.32 * max(0.05, np.cos(np.radians(lat0))))
    info = []
    for k in range(len(hours_ms)):
        d = details[k] if k < len(details) else {}
        info.append(dict(sun=round(float(win['sun_alt'][k]), 1), moon=round(float(win['moon_alt'][k]), 1),
                         illum=round(float(win['moon_illum'][k]), 3), steady=d.get('steadiness', 'unknown')))
    return dict(lat=round(loc['lat'], 6), lon=round(loc['lon'], 6), acc=loc.get('acc'), src=loc.get('src'),
                place=place_label, tz=tz, pts=[[float(a), float(b)] for a, b in pts], hlat=hlat, hlon=hlon,
                hours=hours_ms, scores=np.asarray(scores).tolist(), clouds=np.asarray(clouds).tolist(),
                centre=len(pts) // 2, hour_info=info, ovation=ov_cells, initial=initial,
                nonce=f"{loc['lat']:.5f},{loc['lon']:.5f},{day.isoformat()}")


def show(data, on_pick, key='nightmap'):
    return _COMPONENT(data=data, key=key, on_pick_change=on_pick, width='stretch', height='content')
