"""
Afterglow - stargazing forecast for one night, on a grid of points around the observer.

For every hour between sunset and sunrise and every grid point (7 x 7, 50 km apart, so the
map covers about 300 x 300 km) a 0-100 "sky quality" is computed:

    quality = 100 x clearness^1.5 x darkness x transparency

  clearness    1 - opaque cloud, where low and mid cloud block fully and high (thin cirrus)
               cloud counts 60 %:  opaque = 1 - (1-L)(1-M)(1-0.6 H)
  darkness     from the Sun's depression (full only after astronomical dusk, Sun < -18 deg)
               and the Moon (brightness grows with its lit fraction and its altitude)
  transparency haze/dew from relative humidity, visibility, and CAMS aerosol optical depth

"Steadiness" (twinkling, important for telescopes) is shown separately from the jet-stream
wind at 250 hPa.  Light pollution is not in the score; it is shown from NASA's Black Marble
night-lights map, which is a rough guide (it measures light seen from space, not sky glow).
"""
import io
import math
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import requests
from PIL import Image

import astro
import weather as wx

GRID_N = 7
GRID_STEP_KM = 50.0
GRID_VARS = ["cloud_cover", "cloud_cover_low", "cloud_cover_mid", "cloud_cover_high",
             "relative_humidity_2m", "visibility", "wind_speed_250hPa"]
LABELS = [(80, 'Excellent', '#2fc46f'), (60, 'Good', '#7dcf6b'), (40, 'Fair', '#f1c40f'),
          (20, 'Poor', '#f0913a'), (0, 'Bad', '#f5847c')]


def label_for(score):
    for lim, name, col in LABELS:
        if score >= lim:
            return name, col
    return LABELS[-1][1], LABELS[-1][2]


# ------------------------------------------------------------------------------------------
def night_window(lat, lon, elev, day, tz):
    """Hours from sunset on `day` to sunrise the next morning (local), with the night's events."""
    z = ZoneInfo(tz)
    r0 = astro.compute_day(lat, lon, elev, day, tz)
    r1 = astro.compute_day(lat, lon, elev, day + timedelta(days=1), tz)
    ev0, ev1 = r0['events'], r1['events']
    pick = lambda ev, k, last=False: ([e for e in ev if e['key'] == k][-1 if last else 0]
                                      if any(e['key'] == k for e in ev) else None)
    sunset = pick(ev0, 'sunset_flat', True)
    sunrise = pick(ev1, 'sunrise_flat')
    start = sunset['utc'] if sunset else datetime(day.year, day.month, day.day, 17, tzinfo=z).astimezone(timezone.utc)
    nd = day + timedelta(days=1)
    end = sunrise['utc'] if sunrise else datetime(nd.year, nd.month, nd.day, 7, tzinfo=z).astimezone(timezone.utc)
    if end <= start:            # midnight sun: no real night
        start = datetime(day.year, day.month, day.day, 21, tzinfo=z).astimezone(timezone.utc)
        end = start + timedelta(hours=6)
    h0 = start.replace(minute=0, second=0, microsecond=0)
    h1 = end.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    hours = []
    t = h0
    while t <= h1 and len(hours) < 30:
        hours.append(t)
        t += timedelta(hours=1)
    # the night's events (twilights, moon) in order
    events = []
    for e in ev0 + ev1:
        if start - timedelta(minutes=1) <= e['utc'] <= end + timedelta(minutes=1) and e['key'] in (
                'sunset_flat', 'dusk_civil', 'dusk_nautical', 'dusk_astronomical', 'dawn_astronomical',
                'dawn_nautical', 'dawn_civil', 'sunrise_flat', 'moonrise_flat', 'moonset_flat'):
            events.append(e)
    events.sort(key=lambda e: e['utc'])
    # Sun / Moon each hour
    tt = astro.ts.from_datetimes(hours)
    obs = astro.observer(lat, lon, elev)
    sun_alt, _, _ = astro.positions(obs, 'sun', tt)
    moon_alt, moon_az, moon_dist = astro.positions(obs, 'moon', tt)
    illum = np.array([astro.moon_phase(t_)[1] for t_ in tt])
    dark = [e for e in events if e['key'] in ('dusk_astronomical', 'dawn_astronomical')]
    return dict(start=start, end=end, hours=hours, events=events, sun_alt=np.asarray(sun_alt),
                moon_alt=np.asarray(moon_alt), moon_az=np.asarray(moon_az), moon_illum=illum,
                sunset=sunset, sunrise=sunrise,
                astro_dark=(pick(ev0, 'dusk_astronomical', True), pick(ev1, 'dawn_astronomical')),
                info=r0['info'])


def grid_points(lat, lon, n=GRID_N, step_km=GRID_STEP_KM):
    half = (n - 1) // 2
    pts = []
    for iy in range(-half, half + 1):           # south -> north
        for ix in range(-half, half + 1):       # west -> east
            la = lat + iy * step_km / 111.2
            lo = lon + ix * step_km / (111.32 * max(0.05, math.cos(math.radians(lat))))
            pts.append((round(la, 3), round(((lo + 540) % 360) - 180, 3)))
    return pts


def fetch_grid(points, start, end, model='best_match'):
    """Hourly forecast for each grid point between start and end (UTC datetimes)."""
    out = []
    for i in range(0, len(points), 50):
        chunk = points[i:i + 50]
        j = wx._get(wx.FORECAST, dict(
            latitude=','.join(f'{p[0]:.3f}' for p in chunk), longitude=','.join(f'{p[1]:.3f}' for p in chunk),
            hourly=','.join(GRID_VARS), models=model, timezone='GMT', timeformat='unixtime',
            start_hour=start.strftime('%Y-%m-%dT%H:00'), end_hour=end.strftime('%Y-%m-%dT%H:00')), timeout=60)
        if isinstance(j, dict):
            j = [j]
        for item in j:
            h = item['hourly']
            d = {k: wx._arr(h[k]) for k in h if k != 'time'}
            d['time'] = np.array(h['time'], dtype=float)
            out.append(d)
    return out


# ------------------------------------------------------------------------------------------
def darkness(sun_alt, moon_alt, moon_illum):
    s = float(np.interp(sun_alt, [-18.0, -15.0, -12.0, -9.0, -6.0, 0.0], [1.0, 0.85, 0.6, 0.35, 0.12, 0.0]))
    if moon_alt <= -0.5:
        m = 0.0
    else:
        m = 0.55 * moon_illum ** 1.5 * min(1.0, 0.3 + max(moon_alt, 0.0) / 25.0)
    return s * (1.0 - m), s, m


def clearness(L, M, H):
    return (1 - L) * (1 - M) * (1 - 0.6 * H)


def transparency(rh, vis, aod):
    t = 1.0
    if math.isfinite(rh):
        t *= 0.6 if rh >= 97 else (0.8 if rh >= 90 else 1.0)
    if math.isfinite(vis):
        t *= 0.5 if vis < 5000 else (0.8 if vis < 15000 else 1.0)
    if math.isfinite(aod):
        t *= 1.0 if aod < 0.2 else (0.85 if aod < 0.4 else (0.7 if aod < 0.8 else 0.55))
    return t


def steadiness(jet_kmh):
    if not math.isfinite(jet_kmh):
        return 'unknown'
    return 'steady' if jet_kmh < 70 else ('average' if jet_kmh < 130 else 'turbulent (stars twinkle a lot)')


def score_grid(win, grid_fc, aq):
    """Returns scores[h][p] (int), clouds[h][p] = [L, M, H] (%), and per-hour centre details."""
    H, P = len(win['hours']), len(grid_fc)
    scores = np.zeros((H, P), dtype=int)
    clouds = np.zeros((H, P, 3), dtype=int)
    centre = P // 2
    details = []
    for h, t in enumerate(win['hours']):
        tu = t.timestamp()
        dk, s_f, m_f = darkness(float(win['sun_alt'][h]), float(win['moon_alt'][h]), float(win['moon_illum'][h]))
        aod = wx.at(aq, 'aod', tu) if aq else float('nan')
        for p, fc in enumerate(grid_fc):
            g = lambda k: wx.at(fc, k, tu)
            L, M, Hc = g('cloud_cover_low'), g('cloud_cover_mid'), g('cloud_cover_high')
            if not all(math.isfinite(x) for x in (L, M, Hc)):
                scores[h, p] = -1
                continue
            c = clearness(L / 100, M / 100, Hc / 100)
            tr = transparency(g('relative_humidity_2m'), g('visibility'), aod)
            scores[h, p] = int(round(100 * c ** 1.5 * dk * tr))
            clouds[h, p] = [round(L), round(M), round(Hc)]
            if p == centre:
                details.append(dict(time=t, score=int(scores[h, p]), low=L, mid=M, high=Hc, clear=c,
                                    dark=dk, sun_factor=s_f, moon_penalty=m_f, transp=tr,
                                    rh=g('relative_humidity_2m'), vis=g('visibility'),
                                    jet=g('wind_speed_250hPa'), steadiness=steadiness(g('wind_speed_250hPa')),
                                    sun_alt=float(win['sun_alt'][h]), moon_alt=float(win['moon_alt'][h]),
                                    moon_illum=float(win['moon_illum'][h]), aod=aod))
        if len(details) <= h:
            details.append(dict(time=t, score=-1))
    return scores, clouds, details


# ------------------------------------------------------------------------------------------
BLACK_MARBLE = ("https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/VIIRS_Black_Marble/default/2016-01-01/"
                "GoogleMapsCompatible_Level8/{z}/{y}/{x}.png")


def light_level(lat, lon):
    """Rough artificial-light level from NASA Black Marble 2016 (night lights seen from space).
    Returns (word, local brightness 0-255, brightest within ~25 km 0-255)."""
    from terrain import merc_px
    z = 8
    x, y = merc_px(np.array([lat]), np.array([lon]), z)
    x, y = float(x[0]), float(y[0])
    tx, ty = int(x // 256), int(y // 256)
    tiles = {}
    try:
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                r = requests.get(BLACK_MARBLE.format(z=z, x=(tx + dx) % 256, y=ty + dy), timeout=25)
                r.raise_for_status()
                tiles[(dx, dy)] = np.asarray(Image.open(io.BytesIO(r.content)).convert('L'), dtype=float)
    except Exception:
        return None
    big = np.block([[tiles[(dx, dy)] for dx in (-1, 0, 1)] for dy in (-1, 0, 1)])
    px, py = int(x - (tx - 1) * 256), int(y - (ty - 1) * 256)
    local = float(big[py - 2:py + 3, px - 2:px + 3].mean())               # ~3 km around you (z8 ~ 0.6 km/px * cos)
    near = float(big[py - 40:py + 41, px - 40:px + 41].max())             # brightest within ~25 km
    if local < 25 and near < 120:
        word = 'dark - little artificial light around'
    elif local < 25:
        word = 'fairly dark, with a town glow on the horizon'
    elif local < 70:
        word = 'some light pollution (village or suburb)'
    elif local < 150:
        word = 'bright (town) - only the brighter stars'
    else:
        word = 'very bright (city) - drive out for a dark sky'
    return word, local, near
