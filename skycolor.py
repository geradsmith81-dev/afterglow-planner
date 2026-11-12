"""
Afterglow - "colour potential" of a sunrise or sunset, from forecast clouds.

The model follows the meteorology of vivid twilight skies (the same reasoning used by
sunset-forecast services and storm chasers):

1. CANVAS.  Colour needs something for the low red sunlight to fall on.  The best canvas
   is broken mid-level (altocumulus/altostratus) or high (cirrus) cloud over the observer
   and toward the Sun: roughly 30-70 % cover.  A clear sky gives only a smooth glow;
   a solid overcast blocks the view of anything lit.
2. LIGHT PATH.  At sunset, a cloud at height H above you is lit by sunlight that skims
   the Earth about sqrt(2RH) away in the Sun's direction (~250 km for 5 km cloud,
   ~340 km for 9 km cloud).  At distance s toward the Sun that ray is (D - s)^2 / 2R
   above the ground, so the model checks, at 80, 150, 250 and 350 km, the cover of the
   cloud band (low/mid/high) the ray passes through.  Low cloud near the grazing point
   is the usual culprit that leaves the canvas grey.
3. VIEW.  Thick low cloud over the observer hides the canvas.
4. Rain, fog / poor visibility and heavy aerosol (smoke, dust) mute colours.

Score = 100 x canvas x (0.2 + 0.8 x light path) x view x rain x haze x aerosol.

This is a transparent rule of thumb built on forecast-model clouds, not a validated
statistical forecast: model clouds are themselves uncertain, especially beyond two days.
"""
import math

import numpy as np

from terrain import destination
import weather as wx

RAY_KM = [30, 80, 150, 250, 350]
R_KM = 6371.0

LABELS = [(80, 'Spectacular potential', '#ff7f9f'), (60, 'Great', '#ff7a3d'), (40, 'Good', '#f2b13d'),
          (20, 'Fair', '#c9b28a'), (0, 'Poor', '#a7b0bf')]


def ray_points(lat, lon, az):
    pts = []
    for d in RAY_KM:
        la, lo = destination(lat, lon, az, d * 1000.0)
        lo = (float(lo) + 540.0) % 360.0 - 180.0
        pts.append((round(float(la), 2), round(lo, 2)))
    return pts


def label_for(score):
    for lim, name, col in LABELS:
        if score >= lim:
            return name, col
    return LABELS[-1][1], LABELS[-1][2]


def _p(x):
    return x / 100.0 if x is not None and math.isfinite(x) else float('nan')


def _canvas_curve(c):
    xs = [0.0, 0.10, 0.30, 0.45, 0.70, 0.85, 1.0]
    ys = [0.30, 0.40, 0.85, 1.00, 1.00, 0.75, 0.45]
    return float(np.interp(c, xs, ys))


def _nanmean(v):
    v = [x for x in v if x is not None and math.isfinite(x)]
    return sum(v) / len(v) if v else float('nan')


def cloud_height_for_canvas(profile_rows, mid, high):
    """Height (km above ground) of the cloud that would carry the colour."""
    tops = [r for r in profile_rows if r['cover'] >= 20 and r['above_ground_m'] >= 2500]
    if tops:
        return max(r['above_ground_m'] for r in tops) / 1000.0, 'model levels'
    if math.isfinite(high) and math.isfinite(mid) and high > mid:
        return 9.0, 'typical high cloud'
    return 5.5, 'typical mid cloud'


def depression_lit_deg(h_km):
    """Sun depression (deg) at which a cloud h km up is still in sunlight (incl. ~0.5 deg refraction)."""
    return math.degrees(math.acos(R_KM / (R_KM + h_km))) + 0.5


def assess(kind, t_unix, obs_fc, ray, aq, ground_m, canvas_km=5.5, body_word='Sun'):
    """kind 'sunrise'/'sunset'.  ray: list of 5 hourly dicts for RAY_KM points (or None)."""
    g = lambda k: _p(wx.at(obs_fc, k, t_unix))
    L0, M0, H0 = g('cloud_cover_low'), g('cloud_cover_mid'), g('cloud_cover_high')
    if not all(math.isfinite(x) for x in (L0, M0, H0)):
        return None
    rp = []
    for d, series in zip(RAY_KM, ray or [None] * len(RAY_KM)):
        if series is None:
            rp.append((d, float('nan'), float('nan'), float('nan')))
            continue
        rp.append((d, _p(wx.at(series, 'cloud_cover_low', t_unix)), _p(wx.at(series, 'cloud_cover_mid', t_unix)),
                   _p(wx.at(series, 'cloud_cover_high', t_unix))))
    near = [(0, L0, M0, H0)] + [r for r in rp if r[0] <= 80]
    mh = _nanmean([1 - (1 - m) * (1 - h) for (_, l, m, h) in near])
    c_low = 0.5 * 4 * L0 * (1 - L0)                       # broken low cloud can glow too (max 0.5 at 50 %)
    canvas = 1 - (1 - mh) * (1 - c_low)
    f_canvas = _canvas_curve(canvas)

    # light path: the last (first) sunlight that reaches cloud canvas_km above you skims the
    # Earth sqrt(2 R H) away; at distance s it is (D - s)^2 / 2R km up.  Only the cloud band the
    # ray actually passes through can cut it off.
    D = math.sqrt(2 * R_KM * canvas_km)
    path = []
    for (dk, l, m, h) in rp:
        if dk < 60:
            continue                       # this close the ray is already inside the canvas itself
        hr = (D - dk) ** 2 / (2 * R_KM)
        if hr < 3:
            band, cov, w = 'low', l, 0.6
        elif hr < 8:
            band, cov, w = 'mid', m, 0.6
        elif hr < 12:
            band, cov, w = 'high', h, 0.3
        else:
            continue
        if math.isfinite(cov):
            path.append((dk, hr, band, cov, w))
    if path:
        light_far = 1.0
        for (_, _, _, cov, w) in path:
            light_far *= 1 - w * cov
        worst = max(path, key=lambda q: q[3] * q[4])
    else:
        light_far, worst = 0.7, None
    near_low = _nanmean([r[1] for r in rp if r[0] <= 80])
    light = light_far * (1 - 0.25 * (near_low if math.isfinite(near_low) else 0))

    view = 1 - 0.85 * min(1.0, max(0.0, (L0 - 0.4) / 0.6))
    rain = wx.at(obs_fc, 'precipitation', t_unix)
    f_rain = 1.0 if not math.isfinite(rain) or rain < 0.1 else (0.75 if rain < 0.5 else 0.45)
    vis = wx.at(obs_fc, 'visibility', t_unix)
    f_haze = 1.0 if not math.isfinite(vis) or vis >= 15000 else (0.85 if vis >= 5000 else (0.6 if vis >= 1000 else 0.35))
    aod = wx.at(aq, 'aod', t_unix) if aq else float('nan')
    f_aer = 1.0 if not math.isfinite(aod) or aod < 0.35 else (0.85 if aod < 0.6 else (0.7 if aod < 1.0 else 0.55))

    score = 100 * f_canvas * (0.2 + 0.8 * light) * view * f_rain * f_haze * f_aer
    score = int(round(min(100.0, max(0.0, score))))
    name, col = label_for(score)

    # ---- plain-English reasons
    side = 'west' if kind == 'sunset' else 'east'
    R = []
    pc = lambda x: f'{x * 100:.0f}%'
    if mh < 0.1:
        R.append(f'Hardly any mid or high cloud near you ({pc(mh)}): a clean glow along the horizon, '
                 f'but little cloud to catch colour.')
    elif mh <= 0.75:
        R.append(f'Mid/high cloud near you and toward the {body_word}: {pc(mh)}, a good canvas for colour.')
    else:
        R.append(f'Mid/high cloud near you is {pc(mh)}: the sky may be too solid unless light gets underneath.')
    if worst is not None:
        dk, hr, band, cov, w = worst
        if light_far >= 0.75:
            R.append(f'The path of the {"last" if kind == "sunset" else "first"} sunlight (orange curve under '
                     f'"Clouds toward the Sun") is mostly clear: clouds about {canvas_km:.0f} km up can light up.')
        elif light_far >= 0.4:
            R.append(f'Some {band} cloud ({pc(cov)}) about {dk} km to the {side} lies on the light path '
                     f'and will dim the colours.')
        else:
            R.append(f'{band.capitalize()} cloud ({pc(cov)}) about {dk} km to the {side} lies on the light '
                     f'path and will probably keep the clouds above you grey.')
    if L0 >= 0.6:
        R.append(f'Thick low cloud over you ({pc(L0)}) may hide the sky.')
    elif 0.15 <= L0 < 0.6:
        R.append(f'Broken low cloud over you ({pc(L0)}) can light up orange and red too.')
    if f_rain < 1:
        R.append(f'Rain expected ({rain:.1f} mm/h).')
    if f_haze < 1:
        R.append(f'Visibility only {vis / 1000:.0f} km (haze or fog) mutes colours.')
    if math.isfinite(aod):
        if aod >= 0.35:
            R.append(f'Heavy aerosol (smoke/dust, optical depth {aod:.2f}): a red sun, but duller clouds.')
        elif aod >= 0.12:
            R.append(f'Moderate aerosol (optical depth {aod:.2f}) can deepen the oranges.')

    return dict(score=score, label=name, colour=col, canvas=canvas, mh=mh, low_here=L0, mid_here=M0, high_here=H0,
                light=light, light_far=light_far, near_low=near_low, canvas_km=canvas_km, view=view, f_rain=f_rain, f_haze=f_haze,
                f_aer=f_aer, aod=aod, vis=vis, rain=rain, reasons=R,
                samples=[dict(km=0, low=L0, mid=M0, high=H0)] +
                        [dict(km=d, low=l, mid=m, high=h) for (d, l, m, h) in rp])


def moon_visibility(t_unix, obs_fc, ray):
    """Chance (0-1) of a clear line of sight to the Moon low on the horizon."""
    g = lambda s, k: _p(wx.at(s, k, t_unix))
    pts = [obs_fc] + [s for s in (ray or []) if s is not None][:2]
    vals = []
    for s in pts:
        l, m, h = g(s, 'cloud_cover_low'), g(s, 'cloud_cover_mid'), g(s, 'cloud_cover_high')
        if all(math.isfinite(x) for x in (l, m, h)):
            vals.append((1 - l) * (1 - 0.7 * m) * (1 - 0.35 * h))
    return sum(vals) / len(vals) if vals else float('nan')
