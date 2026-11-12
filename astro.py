"""
Afterglow - astronomy engine.

Sun and Moon positions come from NASA JPL's DE440s planetary ephemeris, reduced to
apparent topocentric altitude/azimuth by Skyfield (IAU 2000A/2006 precession-nutation,
aberration, light-time, polar motion ignored).  On top of that this module finds:

  * standard ("flat horizon") rise and set times, as printed in almanacs:
    upper limb on a sea-level horizon, standard refraction (10 C, 1010 hPa);
  * terrain rise and set times: upper limb crossing the real skyline computed by
    terrain.py from a digital elevation model, with refraction from the forecast
    temperature and pressure;
  * civil / nautical / astronomical twilight, golden hour (sun -4 to +6 deg) and
    blue hour (sun -6 to -4 deg), solar noon, moon phase and illumination.

All times are found on a 1-minute grid and then refined by bisection to < 0.1 s.
The physical uncertainty of a rise/set time near the horizon (refraction varies
from day to day) is about +-1 minute, so the app shows times to the minute.
"""
import os
import math
from datetime import datetime, timedelta, timezone, date as _date
from zoneinfo import ZoneInfo

import numpy as np
from skyfield.api import Loader, wgs84
from skyfield import almanac

HERE = os.path.dirname(os.path.abspath(__file__))
_load = Loader(os.path.join(HERE, 'ephem'), verbose=False)
ts = _load.timescale(builtin=True)
eph = _load('de440s.bsp')          # downloads from JPL on first start if the file is absent
EARTH, SUN, MOON = eph['earth'], eph['sun'], eph['moon']
BODY = {'sun': SUN, 'moon': MOON}
RADIUS_KM = {'sun': 695700.0, 'moon': 1737.4}    # IAU 2015 nominal solar radius; IAU lunar mean radius
STD_T, STD_P = 10.0, 1010.0                     # the almanac convention

STEP_S = 60


def std_pressure(elev_m):
    """Rough station pressure (hPa) for an elevation, used when no forecast is available."""
    return 1013.25 * math.exp(-max(elev_m, -500.0) / 8434.0)


def refraction_deg(true_alt_deg, temp_c=STD_T, pres_hpa=STD_P):
    """Atmospheric refraction (deg) for a TRUE (geometric) altitude - Saemundsson (1986),
    the formula used in the Astronomical Almanac, scaled for temperature and pressure.
    Below -2 deg (an observer high above the surrounding land looking down) it is held at
    its -2 deg value instead of being switched off, which avoids a jump in the curve."""
    h = np.maximum(np.asarray(true_alt_deg, dtype=float), -2.0)
    r_arcmin = 1.02 / np.tan(np.radians(h + 10.3 / (h + 5.11)))
    return r_arcmin / 60.0 * (pres_hpa / 1010.0) * (283.0 / (273.0 + temp_c))


# ----------------------------------------------------------------------------------------
# time grid
# ----------------------------------------------------------------------------------------
def local_day_bounds(day, tz):
    """UTC datetimes of local midnight at the start and end of `day` (handles DST)."""
    z = ZoneInfo(tz)
    a = datetime(day.year, day.month, day.day, tzinfo=z).astimezone(timezone.utc)
    nxt = day + timedelta(days=1)
    b = datetime(nxt.year, nxt.month, nxt.day, tzinfo=z).astimezone(timezone.utc)
    return a, b


def grid(start_utc, end_utc, step_s=STEP_S):
    n = int(round((end_utc - start_utc).total_seconds() / step_s)) + 1
    secs = start_utc.second + np.arange(n) * float(step_s)
    t = ts.utc(start_utc.year, start_utc.month, start_utc.day, start_utc.hour, start_utc.minute, secs)
    return t, n


def observer(lat, lon, elev_m):
    return EARTH + wgs84.latlon(lat, lon, elevation_m=float(elev_m))


def positions(obs, body, t):
    """Geometric (unrefracted) altitude, azimuth (deg) and distance (km)."""
    app = obs.at(t).observe(BODY[body]).apparent()
    alt, az, dist = app.altaz()
    return alt.degrees, az.degrees, dist.km


def semidiameter_deg(body, dist_km):
    return np.degrees(np.arcsin(RADIUS_KM[body] / np.asarray(dist_km)))


# ----------------------------------------------------------------------------------------
# horizon helpers
# ----------------------------------------------------------------------------------------
def horizon_fn(profile):
    """Return f(az_deg) -> apparent skyline altitude (deg), from a terrain.horizon() dict.
    None gives the flat sea-level horizon (0 deg)."""
    if profile is None:
        return lambda az: np.zeros_like(np.asarray(az, dtype=float))
    az0 = np.asarray(profile['az'], dtype=float)
    ang = np.asarray(profile['angle'], dtype=float)
    azx = np.concatenate([az0 - 360.0, az0, az0 + 360.0])
    angx = np.concatenate([ang, ang, ang])
    return lambda az: np.interp(np.mod(np.asarray(az, dtype=float), 360.0), azx, angx)


# ----------------------------------------------------------------------------------------
# root finding
# ----------------------------------------------------------------------------------------
def _refine(fun, jd_lo, jd_hi, iters=4):
    """Vectorised regula falsi (Illinois variant) inside 1-minute brackets.
    The functions are smooth on that scale, so 4 iterations give < 1 ms."""
    lo = np.array(jd_lo, dtype=float)
    hi = np.array(jd_hi, dtype=float)
    f_lo = fun(lo)
    f_hi = fun(hi)
    x = lo
    for _ in range(iters):
        den = np.where(f_hi - f_lo == 0, 1e-30, f_hi - f_lo)
        x = hi - f_hi * (hi - lo) / den
        x = np.clip(x, np.minimum(lo, hi), np.maximum(lo, hi))
        fx = fun(x)
        same_lo = np.sign(fx) == np.sign(f_lo)
        # keep the bracket; halve the stale end's value (Illinois) to avoid stagnation
        lo, f_lo, f_hi = (np.where(same_lo, x, lo), np.where(same_lo, fx, f_lo),
                          np.where(same_lo, f_hi * 0.5, f_hi))
        hi2 = np.where(same_lo, hi, x)
        f_hi = np.where(same_lo, f_hi, fx)
        f_lo = np.where(same_lo, f_lo, f_lo * 0.5)
        hi = hi2
    return x


def _crossings(values):
    v = np.asarray(values)
    s = np.sign(v)
    s[s == 0] = 1
    idx = np.where(s[:-1] != s[1:])[0]
    rising = v[idx + 1] > v[idx]
    return idx, rising


def _limb_fn(obs, body, hfn, temp_c, pres_hpa, limb=+1, refract=True, target=None):
    """fun(jd) = apparent altitude of the limb (or centre) minus the skyline altitude
    (or minus a fixed target altitude)."""
    def fun(jd):
        t = ts.tt_jd(jd)
        alt, az, dist = positions(obs, body, t)
        a = alt + (refraction_deg(alt, temp_c, pres_hpa) if refract else 0.0)
        a = a + limb * semidiameter_deg(body, dist)
        return a - (hfn(az) if target is None else target)
    return fun


# ----------------------------------------------------------------------------------------
# the day
# ----------------------------------------------------------------------------------------
PHASES = [(0, 'New Moon'), (22.5, 'Waxing crescent'), (67.5, 'First quarter'), (112.5, 'Waxing gibbous'),
          (157.5, 'Full Moon'), (202.5, 'Waning gibbous'), (247.5, 'Last quarter'), (292.5, 'Waning crescent'),
          (337.5, 'New Moon')]


def phase_name(angle_deg):
    name = PHASES[0][1]
    for a, n in PHASES:
        if angle_deg % 360 >= a:
            name = n
    return name


def moon_phase(t):
    ang = almanac.moon_phase(eph, t).degrees
    frac = almanac.fraction_illuminated(eph, 'moon', t)
    return float(ang), float(frac)


def compute_day(lat, lon, elev_m, day, tz, profile=None, temp_c=None, pres_hpa=None, light=False):
    """Everything the app needs for one local calendar day at one place.

    Returns dict with
      track: per-minute arrays (UTC ms, sun/moon apparent alt & az, distances)
      events: list of dicts {key, label, body, kind, utc (datetime), az, alt, flat(bool)}
      info: moon phase etc.
    light=True computes only sunrise/sunset (used for the multi-day outlook).
    """
    if temp_c is None:
        temp_c = STD_T
    if pres_hpa is None:
        pres_hpa = std_pressure(elev_m)
    start, end = local_day_bounds(day, tz)
    t, n = grid(start, end)
    jd = t.tt
    obs = observer(lat, lon, elev_m)
    obs_flat = observer(lat, lon, 0.0)
    hfn_terrain = horizon_fn(profile)
    hfn_flat = horizon_fn(None)

    track = {'t0_ms': int(start.timestamp() * 1000), 'step_s': STEP_S, 'n': n}
    geo = {}
    bodies = ('sun',) if light else ('sun', 'moon')
    for b in bodies:
        alt, az, dist = positions(obs, b, t)
        geo[b] = (alt, az, dist)
        track[b + '_alt'] = alt + refraction_deg(alt, temp_c, pres_hpa)
        track[b + '_az'] = az
        track[b + '_sd'] = float(np.mean(semidiameter_deg(b, dist)))
    events = []

    def add(key, label, body, kind, jds, flat):
        if len(jds) == 0:
            return
        tt = ts.tt_jd(np.atleast_1d(jds))
        alt, az, dist = positions(obs, body, tt)
        alt_app = alt + refraction_deg(alt, temp_c, pres_hpa)
        for k, ti in enumerate(tt):
            events.append(dict(key=key, label=label, body=body, kind=kind,
                               utc=ti.utc_datetime(),
                               az=float(az[k]), alt=float(alt_app[k]), flat=flat))

    # --- rise / set: flat (almanac standard) and terrain
    for b in bodies:
        # standard: sea-level horizon, observer at the place (parallax) but no dip, std refraction
        alt_f, az_f, dist_f = positions(obs_flat, b, t)
        v = alt_f + refraction_deg(alt_f, STD_T, STD_P) + semidiameter_deg(b, dist_f)
        idx, rising = _crossings(v)
        fun = _limb_fn(obs_flat, b, hfn_flat, STD_T, STD_P)
        if len(idx):
            roots = _refine(fun, jd[idx], jd[idx + 1])
            add(f'{b}rise_flat', 'rise (flat horizon)', b, 'rise', roots[rising], True)
            add(f'{b}set_flat', 'set (flat horizon)', b, 'set', roots[~rising], True)
        if profile is not None:
            alt, az, dist = geo[b]
            v = alt + refraction_deg(alt, temp_c, pres_hpa) + semidiameter_deg(b, dist) - hfn_terrain(az)
            idx, rising = _crossings(v)
            fun = _limb_fn(obs, b, hfn_terrain, temp_c, pres_hpa)
            if len(idx):
                roots = _refine(fun, jd[idx], jd[idx + 1])
                add(f'{b}rise', 'rise over terrain', b, 'rise', roots[rising], False)
                add(f'{b}set', 'set behind terrain', b, 'set', roots[~rising], False)

    # --- twilight (geometric centre, no refraction - the official definition)
    alt_s = geo['sun'][0]
    for deg, name in () if light else ((-6, 'civil'), (-12, 'nautical'), (-18, 'astronomical')):
        idx, rising = _crossings(alt_s - deg)
        if len(idx):
            fun = _limb_fn(obs, 'sun', hfn_flat, temp_c, pres_hpa, limb=0, refract=False, target=deg)
            roots = _refine(fun, jd[idx], jd[idx + 1])
            add(f'dawn_{name}', f'{name} dawn', 'sun', 'twilight', roots[rising], True)
            add(f'dusk_{name}', f'{name} dusk', 'sun', 'twilight', roots[~rising], True)

    # --- golden hour (+6..-4) and blue hour (-4..-6), apparent centre, as PhotoPills defines them
    alt_app_s = track['sun_alt']
    for deg in (() if light else (6.0, -4.0)):
        idx, rising = _crossings(alt_app_s - deg)
        if len(idx):
            fun = _limb_fn(obs, 'sun', hfn_flat, temp_c, pres_hpa, limb=0, refract=True, target=deg)
            roots = _refine(fun, jd[idx], jd[idx + 1])
            tag = 'p6' if deg > 0 else 'm4'
            add(f'sun_{tag}_up', f'sun at {deg:+.0f} deg (rising)', 'sun', 'light', roots[rising], True)
            add(f'sun_{tag}_down', f'sun at {deg:+.0f} deg (setting)', 'sun', 'light', roots[~rising], True)

    # --- transits (highest point): sign change of the altitude derivative from + to -
    for b in bodies:
        alt = geo[b][0]
        d = np.diff(alt)
        k = np.where((d[:-1] > 0) & (d[1:] <= 0))[0] + 1
        for i in k:
            # parabola through three samples
            y0, y1, y2 = alt[i - 1], alt[i], alt[i + 1]
            den = (y0 - 2 * y1 + y2)
            off = 0.5 * (y0 - y2) / den if den != 0 else 0.0
            add(f'{b}_transit', 'highest point', b, 'transit', [jd[i] + off * STEP_S / 86400.0], True)

    events.sort(key=lambda e: e['utc'])

    # moon phase at local noon and at each moon event
    noon = start + (end - start) / 2
    tn = ts.from_datetime(noon)
    ang, frac = moon_phase(tn)
    for e in events:
        if e['body'] == 'moon':
            e['illum'] = moon_phase(ts.from_datetime(e['utc']))[1]
    info = dict(moon_phase_deg=ang, moon_illum=frac, moon_phase_name=phase_name(ang),
                temp_c=temp_c, pres_hpa=pres_hpa, elev_m=elev_m)
    return dict(track=track, events=events, info=info, start=start, end=end)


def first(events, key):
    for e in events:
        if e['key'] == key:
            return e
    return None


def last(events, key):
    found = None
    for e in events:
        if e['key'] == key:
            found = e
    return found


def sun_time_at_depression(obs_lat, obs_lon, elev_m, after_utc, depression_deg, setting=True, hours=3):
    """Time when the sun's geometric centre reaches -depression after (sunset) or before
    (sunrise) `after_utc`.  Used for the afterglow window of high clouds."""
    if setting:
        a, b = after_utc, after_utc + timedelta(hours=hours)
    else:
        a, b = after_utc - timedelta(hours=hours), after_utc
    t, n = grid(a, b, 30)
    obs = observer(obs_lat, obs_lon, elev_m)
    alt, az, dist = positions(obs, 'sun', t)
    v = alt + depression_deg
    idx, rising = _crossings(v)
    if not len(idx):
        return None
    fun = _limb_fn(obs, 'sun', horizon_fn(None), STD_T, STD_P, limb=0, refract=False, target=-depression_deg)
    roots = _refine(fun, t.tt[idx], t.tt[idx + 1])
    pick = roots[~rising] if setting else roots[rising]
    if not len(pick):
        return None
    j = pick[0] if setting else pick[-1]
    return ts.tt_jd(j).utc_datetime()


def sun_azimuth_at(lat, lon, elev_m, when_utc):
    obs = observer(lat, lon, elev_m)
    alt, az, dist = positions(obs, 'sun', ts.from_datetime(when_utc))
    return float(az)
