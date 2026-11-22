"""
Afterglow - eclipses, meteor showers and comets.

Solar eclipses
    Found at every new moon from NASA JPL DE440s (Skyfield).  The Moon's shadow axis is the
    line from the Sun through the Moon; "greatest eclipse" is when it passes closest to the
    Earth's centre (distance = gamma, in Earth radii).  An eclipse happens somewhere on Earth if
    the penumbra reaches the Earth.  Central eclipses are total, annular or hybrid depending on
    whether the Moon looks larger or smaller than the Sun where the axis meets the Earth.
    Checked against NASA's eclipse catalogue (F. Espenak, GSFC) for Aug 2026 - 2040: all 33 dates and
    types agree (including the 2031 Nov 14 hybrid), greatest eclipse within 2 s, magnitude within
    0.007, path widths within 1 % (2026 Aug 12: 296 vs 294 km; 2027 Aug 02: 259 vs 258 km).
    For your location the topocentric Sun-Moon separation gives the contact times, the magnitude
    (fraction of the Sun's diameter covered) and the obscuration (fraction of its area covered).

Lunar eclipses
    Skyfield's implementation of the Explanatory Supplement to the Astronomical Almanac (11.2.3).
    Checked against NASA's catalogue for 2027-2040: all 33 dates and types agree, greatest eclipse
    within 3 s, umbral magnitude within 0.003.

Meteor showers
    International Meteor Organization, 2026 Meteor Shower Calendar, Table 5 (Working List of
    Visual Meteor Showers).  Peaks are found from the solar longitude (J2000) each year; this
    reproduces the IMO's quoted 2026 peak times within a few minutes.
    Hourly rate seen by one observer:  HR = ZHR x sin(radiant altitude) x r^(LM - 6.5),
    where r is the population index and LM the faintest star visible (estimated here from
    twilight, moonlight and light pollution).

Comets
    Orbits and magnitude parameters from the IAU Minor Planet Center (CometEls.txt).  The
    brightness formula m = H + 5 log(delta) + 2.5 n log(r) is shown together with JPL Horizons'
    own prediction, because comet brightness forecasts often disagree by several magnitudes.
"""
import io
import math
import os
import re
import tempfile
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import requests
from skyfield import almanac, eclipselib
from skyfield.api import Star
from skyfield.framelib import itrs, ecliptic_J2000_frame
from skyfield.searchlib import find_discrete

import astro

ts, eph, EARTH, SUN, MOON = astro.ts, astro.eph, astro.EARTH, astro.SUN, astro.MOON
A_E = 6378.137                    # WGS84 equatorial radius, km
F_E = 1 / 298.257223563
E2 = F_E * (2 - F_E)
R_SUN = 695700.0                  # IAU 2015 nominal solar radius, km
# Lunar radii as in NASA's eclipse predictions (Espenak): k = 0.2725076 Earth radii for the outer
# (partial) contacts and magnitudes, k = 0.2722810 for the inner (total/annular) contacts and path limits.
R_MOON = 0.2725076 * A_E           # 1738.09 km
R_MOON_IN = 0.2722810 * A_E        # 1736.64 km
CACHE = os.environ.get('AFTERGLOW_DATA_CACHE') or os.path.join(tempfile.gettempdir(), 'afterglow_data')
_s = requests.Session()


def _ut(t):
    return t.utc_datetime()


def _jd(dt):
    return ts.from_datetime(dt).tt


# ==========================================================================================
# solar eclipses - global
# ==========================================================================================
def _geo(t):
    e = EARTH.at(t)
    return e.observe(SUN).apparent().position.km, e.observe(MOON).apparent().position.km


def _axis(S, M):
    u = (M - S) / np.linalg.norm(M - S, axis=0)
    P = M - np.sum(M * u, axis=0) * u
    return u, np.linalg.norm(P, axis=0) / A_E, P


def _axis_hit(M, u):
    """Where the shadow axis (through M along u) first meets the WGS84 ellipsoid (GCRS approx)."""
    sc = np.array([1.0, 1.0, 1.0 / (1.0 - F_E)])
    Mp, up = M * sc, u * sc
    a, b, c = up @ up, 2 * Mp @ up, Mp @ Mp - A_E ** 2
    disc = b * b - 4 * a * c
    if disc < 0:
        return None
    return M + (-b - math.sqrt(disc)) / (2 * a) * u


def _itrs_to_latlon(x, y, z):
    lon = math.degrees(math.atan2(y, x))
    lat = math.degrees(math.atan2(z, math.hypot(x, y) * (1 - E2)))
    return lat, lon


def _latlon_to_itrs(lat, lon, h=0.0):
    la, lo = np.radians(lat), np.radians(lon)
    N = A_E / np.sqrt(1 - E2 * np.sin(la) ** 2)
    return np.array([(N + h) * np.cos(la) * np.cos(lo), (N + h) * np.cos(la) * np.sin(lo),
                     (N * (1 - E2) + h) * np.sin(la)])


def _local_geom(S, M, X, r_moon=R_MOON):
    """Topocentric magnitude quantities for observer(s) X (3,P) given geocentric S, M (3,)."""
    s = S[:, None] - X
    m = M[:, None] - X
    ds, dm = np.linalg.norm(s, axis=0), np.linalg.norm(m, axis=0)
    sd_s, sd_m = np.arcsin(R_SUN / ds), np.arcsin(r_moon / dm)
    cosang = np.clip(np.sum(s * m, axis=0) / (ds * dm), -1, 1)
    return sd_s, sd_m, np.arccos(cosang), s / ds


def solar_eclipses(start_utc, end_utc):
    """All solar eclipses between two UTC datetimes."""
    tp, yp = almanac.find_discrete(ts.from_datetime(start_utc), ts.from_datetime(end_utc),
                                   almanac.moon_phases(eph))
    out = []
    for tn in tp[yp == 0]:
        jd = tn.tt + np.arange(-360, 361, 2) / 1440.0
        t = ts.tt_jd(jd)
        S, M = _geo(t)
        u, g, P = _axis(S, M)
        i = int(np.argmin(g))
        jd2 = jd[i] + np.arange(-150, 151, 2) / 86400.0          # refine to 2 s
        t2 = ts.tt_jd(jd2)
        S2, M2 = _geo(t2)
        u2, g2, P2 = _axis(S2, M2)
        k = int(np.argmin(g2))
        Sg, Mg, ug, gam = S2[:, k], M2[:, k], u2[:, k], float(g2[k])
        dSM = np.linalg.norm(Sg - Mg)
        zz = -float(Mg @ ug)
        f1 = math.asin((R_SUN + R_MOON) / dSM)
        l1 = (zz * math.tan(f1) + R_MOON / math.cos(f1)) / A_E
        if gam >= 1 + l1:
            continue
        tg = ts.tt_jd(jd2[k])
        # type along the central line
        kinds = set()
        cl_idx = np.where(g < 1.0)[0]
        for j in cl_idx:
            X = _axis_hit(M[:, j], u[:, j])
            if X is None:
                continue
            kinds.add('T' if R_MOON_IN / np.linalg.norm(M[:, j] - X) > R_SUN / np.linalg.norm(S[:, j] - X) else 'A')
        if not kinds:
            typ = 'Partial'
        elif kinds == {'T'}:
            typ = 'Total'
        elif kinds == {'A'}:
            typ = 'Annular'
        else:
            typ = 'Hybrid'
        # magnitude at greatest eclipse (NASA convention)
        if typ != 'Partial':
            X = _axis_hit(Mg, ug)
            mag = (R_MOON / np.linalg.norm(Mg - X)) / (R_SUN / np.linalg.norm(Sg - X))
        else:
            Pg = P2[:, k]
            Xs = A_E * Pg / np.linalg.norm(Pg)
            sd_s, sd_m, sep, _ = _local_geom(Sg, Mg, Xs[:, None])
            mag = float(((sd_s + sd_m - sep) / (2 * sd_s))[0])
        out.append(dict(id=f"SE{_ut(tg):%Y%m%d}", kind='solar', type=typ, greatest=_ut(tg),
                        gamma=gam, magnitude=float(mag)))
    return out


def central_line(ecl):
    """Central line [[lat, lon], ...] (1-minute steps) for a total/annular/hybrid eclipse."""
    if ecl['type'] == 'Partial':
        return []
    jd0 = _jd(ecl['greatest'])
    jd = jd0 + np.arange(-200, 201, 1) / 1440.0
    t = ts.tt_jd(jd)
    S, M = _geo(t)
    u, g, _ = _axis(S, M)
    R = itrs.rotation_at(t)
    pts = []
    for j in np.where(g < 1.0)[0]:
        X = _axis_hit(M[:, j], u[:, j])
        if X is None:
            continue
        x, y, z = R[:, :, j] @ X
        pts.append(list(_itrs_to_latlon(x, y, z)))
    return pts


def path_width_km(ecl):
    """Width of the band of totality/annularity at greatest eclipse (perpendicular to the track)."""
    if ecl['type'] == 'Partial':
        return None
    jd0 = _jd(ecl['greatest'])
    t = ts.tt_jd(np.array([jd0 - 1 / 1440, jd0, jd0 + 1 / 1440]))
    S, M = _geo(t)
    u, g, _ = _axis(S, M)
    R = itrs.rotation_at(t)
    hits = []
    for j in range(3):
        X = _axis_hit(M[:, j], u[:, j])
        if X is None:
            return None
        hits.append(_itrs_to_latlon(*(R[:, :, j] @ X)))
    from terrain import destination
    la0, lo0 = hits[1]
    # direction of travel
    p1, p2 = np.radians(hits[0]), np.radians(hits[2])
    y = math.sin(p2[1] - p1[1]) * math.cos(p2[0])
    x = math.cos(p1[0]) * math.sin(p2[0]) - math.sin(p1[0]) * math.cos(p2[0]) * math.cos(p2[1] - p1[1])
    track = math.degrees(math.atan2(y, x))
    Sg, Mg, Rg = S[:, 1], M[:, 1], R[:, :, 1]

    def inside(az, d_km):
        la, lo = destination(la0, lo0, az, d_km * 1000.0)
        X = Rg.T @ _latlon_to_itrs(float(la), float(lo))
        sd_s, sd_m, sep, _ = _local_geom(Sg, Mg, X[:, None], R_MOON_IN)
        return bool(sep[0] < abs(sd_m[0] - sd_s[0]))

    # outline of the shadow on the ground (radius in 72 directions), then its full extent across the
    # track: when the Sun is low the shadow is a tilted ellipse, so a slice through the centre is too narrow
    across = []
    for az in np.arange(0.0, 360.0, 5.0):
        lo_, hi_ = 0.0, 800.0
        if inside(az, hi_):
            return None
        for _ in range(26):
            mid = 0.5 * (lo_ + hi_)
            if inside(az, mid):
                lo_ = mid
            else:
                hi_ = mid
        across.append(lo_ * math.sin(math.radians(az - track)))
    return max(across) - min(across)


def solar_world_grid(ecl, step=3.0):
    """Max magnitude (Sun above the horizon) on a lat/lon grid: [[lat, lon, mag], ...]."""
    lats = np.arange(-81.0, 81.1, step)
    lons = np.arange(-180.0, 180.0, step)
    LA, LO = np.meshgrid(lats, lons, indexing='ij')
    la, lo = LA.ravel(), LO.ravel()
    X_itrs = _latlon_to_itrs(la, lo)
    up_itrs = np.array([np.cos(np.radians(la)) * np.cos(np.radians(lo)),
                        np.cos(np.radians(la)) * np.sin(np.radians(lo)), np.sin(np.radians(la))])
    jd0 = _jd(ecl['greatest'])
    jd = jd0 + np.arange(-225, 226, 4) / 1440.0
    t = ts.tt_jd(jd)
    S, M = _geo(t)
    R = itrs.rotation_at(t)
    best = np.zeros(la.size)
    for j in range(jd.size):
        X = R[:, :, j].T @ X_itrs
        up = R[:, :, j].T @ up_itrs
        sd_s, sd_m, sep, sdir = _local_geom(S[:, j], M[:, j], X)
        mag = (sd_s + sd_m - sep) / (2 * sd_s)
        sun_alt = np.degrees(np.arcsin(np.clip(np.sum(sdir * up, axis=0), -1, 1)))
        mag = np.where(sun_alt > -0.8, mag, 0.0)
        best = np.maximum(best, mag)
    keep = best > 0.001
    return [[float(a), float(b), round(float(c), 3)] for a, b, c in zip(la[keep], lo[keep], best[keep])]


def _overlap_fraction(R, r, d):
    """Fraction of the disc of radius R covered by a disc of radius r at centre distance d."""
    if d >= R + r:
        return 0.0
    if d <= abs(R - r):
        return min(1.0, (r / R) ** 2)
    a = r * r * math.acos((d * d + r * r - R * R) / (2 * d * r))
    b = R * R * math.acos((d * d + R * R - r * r) / (2 * d * R))
    c = 0.5 * math.sqrt(max(0.0, (-d + r + R) * (d + r - R) * (d - r + R) * (d + r + R)))
    return (a + b - c) / (math.pi * R * R)


def _crossings(t_jd, f, rising):
    out = []
    for i in range(len(f) - 1):
        if (f[i] <= 0 < f[i + 1]) if rising else (f[i] > 0 >= f[i + 1]):
            x = t_jd[i] + (t_jd[i + 1] - t_jd[i]) * f[i] / (f[i] - f[i + 1])
            out.append(x)
    return out


def solar_local(ecl, lat, lon, elev_m, hfn=None):
    """Local circumstances.  None if the eclipse is not seen anywhere near here."""
    jd0 = _jd(ecl['greatest'])
    jd = jd0 + np.arange(-300, 301, 0.5) / 1440.0
    t = ts.tt_jd(jd)
    obs = astro.observer(lat, lon, elev_m)
    s = obs.at(t).observe(SUN).apparent()
    m = obs.at(t).observe(MOON).apparent()
    sep = s.separation_from(m).radians
    sd_s = np.arcsin(R_SUN / s.distance().km)
    sd_m = np.arcsin(R_MOON / m.distance().km)
    sd_mi = np.arcsin(R_MOON_IN / m.distance().km)
    f = sd_s + sd_m - sep
    if f.max() <= 0:
        return None
    alt, az, _ = s.altaz()
    alt_app = alt.degrees + astro.refraction_deg(alt.degrees, astro.STD_T, astro.std_pressure(elev_m))
    sky = hfn(az.degrees) if hfn else np.zeros_like(alt_app)
    i = int(np.argmax(f / (2 * sd_s)))
    if 0 < i < len(jd) - 1:
        y0, y1, y2 = (f / (2 * sd_s))[i - 1:i + 2]
        den = y0 - 2 * y1 + y2
        off = 0.5 * (y0 - y2) / den if den != 0 else 0.0
    else:
        off = 0.0
    jmax = jd[i] + off * (jd[1] - jd[0])
    mag = float((f / (2 * sd_s))[i])
    obsc = _overlap_fraction(sd_s[i], sd_m[i], sep[i])
    inner = np.abs(sd_mi - sd_s) - sep
    c1 = _crossings(jd, f, True)
    c4 = _crossings(jd, f, False)
    c2 = _crossings(jd, inner, True)
    c3 = _crossings(jd, inner, False)
    local_type = 'Partial'
    if c2 and c3:
        local_type = 'Total' if sd_mi[i] > sd_s[i] else 'Annular'

    def info(x):
        if x is None:
            return None
        k = int(np.clip(round((x - jd[0]) / (jd[1] - jd[0])), 0, len(jd) - 1))
        return dict(utc=ts.tt_jd(x).utc_datetime(), alt=float(alt_app[k]), az=float(az.degrees[k]),
                    up=bool(alt_app[k] > sky[k]))

    contacts = dict(C1=info(c1[0] if c1 else None), C2=info(c2[0] if c2 else None),
                    MAX=info(jmax), C3=info(c3[0] if c3 else None), C4=info(c4[-1] if c4 else None))
    ecl_mask = f > 0
    seen = ecl_mask & (alt_app > sky)
    dur_central = ((c3[0] - c2[0]) * 86400.0) if (c2 and c3) else None
    if not seen.any():
        verdict = 'not visible (Sun below the horizon)'
    elif contacts['MAX']['up']:
        verdict = 'visible'
    else:
        verdict = 'partly visible (Sun rises or sets during it)'
    return dict(type=local_type, magnitude=mag, obscuration=obsc, contacts=contacts, central_s=dur_central,
                visible=bool(seen.any()), max_visible=bool(contacts['MAX']['up']), verdict=verdict,
                seen_from=_ut(ts.tt_jd(jd[seen][0])) if seen.any() else None,
                seen_to=_ut(ts.tt_jd(jd[seen][-1])) if seen.any() else None)


# ==========================================================================================
# lunar eclipses
# ==========================================================================================
LUNAR_TYPES = {0: 'Penumbral', 1: 'Partial', 2: 'Total'}


def lunar_eclipses(start_utc, end_utc):
    t, y, d = eclipselib.lunar_eclipses(ts.from_datetime(start_utc), ts.from_datetime(end_utc), eph)
    out = []
    for k, (ti, yi) in enumerate(zip(t, y)):
        out.append(dict(id=f"LE{_ut(ti):%Y%m%d}", kind='lunar', type=LUNAR_TYPES[int(yi)], greatest=_ut(ti),
                        magnitude=float(d['umbral_magnitude'][k]), pen_magnitude=float(d['penumbral_magnitude'][k]),
                        moon_r=float(d['moon_radius_radians'][k]), umbra_r=float(d['umbra_radius_radians'][k]),
                        pen_r=float(d['penumbra_radius_radians'][k]), closest=float(d['closest_approach_radians'][k])))
    return out


def _shadow_sep(t):
    e = EARTH.at(t)
    s = e.observe(SUN).apparent().position.km
    m = e.observe(MOON).apparent().position.km
    a = -s / np.linalg.norm(s, axis=0)
    b = m / np.linalg.norm(m, axis=0)
    return np.arccos(np.clip(np.sum(a * b, axis=0), -1, 1))


def lunar_contacts(ecl):
    jd0 = _jd(ecl['greatest'])
    jd = jd0 + np.arange(-300, 301, 0.5) / 1440.0
    sep = _shadow_sep(ts.tt_jd(jd))
    sep = sep + (ecl['closest'] - sep.min())            # match Skyfield's closest approach exactly
    mr, ur, pr = ecl['moon_r'], ecl['umbra_r'], ecl['pen_r']
    out = {}
    for name, rad in (('P', pr + mr), ('U', ur + mr), ('T', ur - mr)):
        f = rad - sep
        a, b = _crossings(jd, f, True), _crossings(jd, f, False)
        if a and b:
            out[name + '1'] = a[0]
            out[name + '4'] = b[-1]
    names = [('P1', 'Penumbral eclipse begins'), ('U1', 'Partial eclipse begins'), ('T1', 'Total eclipse begins'),
             ('MAX', 'Greatest eclipse'), ('T4', 'Total eclipse ends'), ('U4', 'Partial eclipse ends'),
             ('P4', 'Penumbral eclipse ends')]
    out['MAX'] = jd0
    return [(code, label, out[code]) for code, label in names if code in out]


def lunar_local(ecl, lat, lon, elev_m, hfn=None):
    obs = astro.observer(lat, lon, elev_m)
    rows = []
    for code, label, jdv in lunar_contacts(ecl):
        t = ts.tt_jd(jdv)
        a, z, _ = obs.at(t).observe(MOON).apparent().altaz()
        alt = a.degrees + float(astro.refraction_deg(a.degrees, astro.STD_T, astro.std_pressure(elev_m)))
        sky = float(hfn(z.degrees)) if hfn else 0.0
        sa, _, _ = obs.at(t).observe(SUN).apparent().altaz()
        rows.append(dict(code=code, label=label, utc=t.utc_datetime(), alt=float(alt), az=float(z.degrees),
                         up=bool(alt > sky), sun_alt=float(sa.degrees)))
    vis = [r for r in rows if r['up']]
    mx = next(r for r in rows if r['code'] == 'MAX')
    if not vis:
        verdict = 'not visible (Moon below the horizon)'
    elif len(vis) == len(rows):
        verdict = 'visible from start to end'
    elif mx['up']:
        verdict = 'greatest eclipse visible (Moon rises or sets during it)'
    else:
        verdict = 'partly visible (Moon rises or sets during it)'
    return dict(rows=rows, visible=bool(vis), max_visible=mx['up'], verdict=verdict)


def lunar_world_grid(ecl, step=3.0):
    """For each grid cell: 2 = whole eclipse visible, 1 = part visible (Moon up at some contact)."""
    lats = np.arange(-81.0, 81.1, step)
    lons = np.arange(-180.0, 180.0, step)
    LA, LO = np.meshgrid(lats, lons, indexing='ij')
    la, lo = LA.ravel(), LO.ravel()
    up_itrs = np.array([np.cos(np.radians(la)) * np.cos(np.radians(lo)),
                        np.cos(np.radians(la)) * np.sin(np.radians(lo)), np.sin(np.radians(la))])
    cts = [c for c in lunar_contacts(ecl) if c[0] in ('U1', 'U4', 'MAX', 'P1', 'P4')]
    if ecl['type'] != 'Penumbral':
        cts = [c for c in cts if c[0] in ('U1', 'MAX', 'U4')]
    jd = np.array([c[2] for c in cts] + [cts[0][2] + k * (cts[-1][2] - cts[0][2]) / 8 for k in range(1, 8)])
    t = ts.tt_jd(jd)
    m = EARTH.at(t).observe(MOON).apparent().position.km
    m = m / np.linalg.norm(m, axis=0)
    R = itrs.rotation_at(t)
    ups = []
    for j in range(jd.size):
        up = R[:, :, j].T @ up_itrs
        ups.append(np.degrees(np.arcsin(np.clip(m[:, j] @ up, -1, 1))) > 0.9)   # ~ topocentric alt > 0
    ups = np.array(ups)
    allv, anyv = ups.all(axis=0), ups.any(axis=0)
    val = np.where(allv, 2, np.where(anyv, 1, 0))
    keep = val > 0
    return [[float(a), float(b), int(c)] for a, b, c in zip(la[keep], lo[keep], val[keep])]


# ==========================================================================================
# meteor showers (IMO 2026 Meteor Shower Calendar, Table 5)
# ==========================================================================================
# code, name, active, solar longitude of maximum (J2000), radiant RA, Dec (deg), V (km/s), r, ZHR, parent
SHOWERS = [
    ('QUA', 'Quadrantids', 'Dec 28 - Jan 12', 283.15, 230, 49, 41, 2.1, 80, '(196256) 2003 EH1'),
    ('ACE', 'Alpha Centaurids', 'Jan 31 - Feb 20', 319.4, 211, -58, 58, 2.0, 6, ''),
    ('LYR', 'April Lyrids', 'Apr 14 - Apr 30', 32.32, 271, 34, 49, 2.1, 18, 'C/1861 G1 (Thatcher)'),
    ('ETA', 'Eta Aquariids', 'Apr 19 - May 28', 45.5, 338, -1, 66, 2.4, 50, '1P/Halley'),
    ('GDR', 'July Gamma Draconids', 'Jul 25 - Jul 31', 125.13, 280, 51, 27, 3.0, 5, ''),
    ('SDA', 'Southern Delta Aquariids', 'Jul 12 - Aug 23', 128.0, 340, -16, 41, 2.5, 25, ''),
    ('CAP', 'Alpha Capricornids', 'Jul 03 - Aug 15', 128.0, 307, -10, 23, 2.5, 5, '169P/NEAT'),
    ('PER', 'Perseids', 'Jul 17 - Aug 24', 140.0, 48, 58, 59, 2.2, 100, '109P/Swift-Tuttle'),
    ('AUR', 'Aurigids', 'Aug 28 - Sep 05', 158.6, 91, 39, 66, 2.5, 6, 'C/1911 N1 (Kiess)'),
    ('SPE', 'September Epsilon Perseids', 'Sep 05 - Sep 21', 166.7, 48, 40, 64, 2.5, 8, ''),
    ('DRA', 'Draconids', 'Oct 06 - Oct 10', 195.4, 262, 54, 20, 2.6, 5, '21P/Giacobini-Zinner'),
    ('ORI', 'Orionids', 'Oct 02 - Nov 07', 208.0, 95, 16, 66, 2.5, 20, '1P/Halley'),
    ('STA', 'Southern Taurids', 'Sep 20 - Nov 20', 223.0, 52, 15, 27, 2.3, 7, '2P/Encke'),
    ('NTA', 'Northern Taurids', 'Oct 20 - Dec 10', 230.0, 58, 22, 29, 2.3, 5, '2P/Encke'),
    ('LEO', 'Leonids', 'Nov 06 - Nov 30', 235.27, 152, 22, 71, 2.5, 15, '55P/Tempel-Tuttle'),
    ('HYD', 'Sigma Hydrids', 'Dec 03 - Dec 20', 257.0, 125, 2, 58, 3.0, 7, ''),
    ('GEM', 'Geminids', 'Dec 04 - Dec 20', 262.2, 112, 33, 35, 2.6, 150, '(3200) Phaethon'),
    ('URS', 'Ursids', 'Dec 17 - Dec 26', 270.7, 217, 76, 33, 2.8, 10, '8P/Tuttle'),
    ('COM', 'Comae Berenicids', 'Dec 04 - Jan 30', 271.0, 164, 29, 65, 3.0, 3, ''),
]
SHOWERS = [s for s in SHOWERS if s[8] >= 5]       # keep the regular showers with ZHR 5 or more


def solar_longitude(t):
    """Astrometric J2000 solar longitude (the IMO convention), degrees."""
    return EARTH.at(t).observe(SUN).frame_latlon(ecliptic_J2000_frame)[1].degrees


def time_of_solar_longitude(lam, start_utc, days=380):
    def f(t):
        return ((solar_longitude(t) - lam + 180.0) % 360.0 - 180.0) > 0
    f.step_days = 1.0
    t, v = find_discrete(ts.from_datetime(start_utc), ts.from_datetime(start_utc + timedelta(days=days)), f)
    hits = [ti.utc_datetime() for ti, vi in zip(t, v) if vi]
    return hits[0] if hits else None


def shower_peaks(start_utc, days=366):
    out = []
    for code, name, active, lam, ra, dec, v, r, zhr, parent in SHOWERS:
        pk = time_of_solar_longitude(lam, start_utc - timedelta(days=2), days + 2)
        if pk is None or pk > start_utc + timedelta(days=days):
            continue
        out.append(dict(code=code, name=name, active=active, lam=lam, ra=ra, dec=dec, v=v, r=r, zhr=zhr,
                        parent=parent, peak=pk))
    out.sort(key=lambda s: s['peak'])
    return out


def light_pollution_penalty(local_brightness):
    """Loss of limiting magnitude from artificial light (rough, from NASA Black Marble 0-255)."""
    if local_brightness is None:
        return 0.0
    if local_brightness < 25:
        return 0.0
    if local_brightness < 70:
        return 0.8
    if local_brightness < 150:
        return 1.6
    return 2.3


def shower_night(sh, lat, lon, elev_m, tz, lp_penalty=0.0):
    """Choose the night (evening date) nearest the peak and compute the hourly rate through it."""
    z = ZoneInfo(tz)
    peak_local = sh['peak'].astimezone(z)
    star = Star(ra_hours=sh['ra'] / 15.0, dec_degrees=sh['dec'])
    obs = astro.observer(lat, lon, elev_m)
    best = None
    for k in (-1, 0, 1):
        d0 = (peak_local + timedelta(days=k)).date()
        start = datetime(d0.year, d0.month, d0.day, 12, tzinfo=z).astimezone(timezone.utc)
        times = [start + timedelta(minutes=15 * i) for i in range(97)]
        t = ts.from_datetimes(times)
        sun_alt = obs.at(t).observe(SUN).apparent().altaz()[0].degrees
        mo = obs.at(t).observe(MOON).apparent()
        moon_alt = mo.altaz()[0].degrees
        illum = almanac.fraction_illuminated(eph, 'moon', t)
        rad_alt = obs.at(t).observe(star).apparent().altaz()[0].degrees
        lm_dark = 6.5 - np.where(sun_alt > -18, 2.0 * (sun_alt + 18) / 6.0, 0.0) \
            - np.where(moon_alt > -1, 1.5 * illum * np.clip((moon_alt + 5) / 30.0, 0, 1), 0.0)
        ok = (sun_alt < -12) & (rad_alt > 0)
        hr_dark = np.where(ok, sh['zhr'] * np.sin(np.radians(np.maximum(rad_alt, 0))) * sh['r'] ** (lm_dark - 6.5), 0.0)
        hr_here = np.where(ok, sh['zhr'] * np.sin(np.radians(np.maximum(rad_alt, 0)))
                           * sh['r'] ** (lm_dark - lp_penalty - 6.5), 0.0)
        dark = np.where(sun_alt < -12)[0]
        if len(dark):
            mid = times[int(dark[len(dark) // 2])]
            gap = abs((mid - sh['peak']).total_seconds())
        else:
            gap = 9e9
        cand = dict(evening=d0, times=times, sun_alt=sun_alt, moon_alt=moon_alt, illum=illum, rad_alt=rad_alt,
                    hr_dark=hr_dark, hr_here=hr_here, gap=gap)
        if best is None or (gap, -hr_dark.max()) < (best['gap'], -best['hr_dark'].max()):
            best = cand
    i = int(np.argmax(best['hr_dark']))
    best['best_time'] = best['times'][i] if best['hr_dark'][i] > 0 else None
    best['best_dark'] = float(best['hr_dark'][i])
    best['best_here'] = float(best['hr_here'].max())
    best['rad_max'] = float(np.max(np.where(best['sun_alt'] < -12, best['rad_alt'], -90)))
    best['moon_at_peak'] = float(almanac.fraction_illuminated(eph, 'moon', ts.from_datetime(sh['peak'])))
    return best


# ==========================================================================================
# comets
# ==========================================================================================
COMET_URL = "https://www.minorplanetcenter.net/iau/MPCORB/CometEls.txt"
MIN_ELONG = 25.0          # degrees from the Sun; closer than this a comet is lost in twilight


def _cached_file(url, name, max_age_h=12):
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, name)
    if os.path.exists(p) and time.time() - os.path.getmtime(p) < max_age_h * 3600:
        return open(p, 'rb').read()
    try:
        r = _s.get(url, timeout=60)
        r.raise_for_status()
        open(p, 'wb').write(r.content)
        return r.content
    except requests.RequestException:
        if os.path.exists(p):
            return open(p, 'rb').read()
        raise


def horizons_designation(name):
    m = re.match(r'^(\d+[PDI])(?:-[A-Z]+)?/', name)
    if m:
        return m.group(1)
    m = re.match(r'^([PCDXAI]/\d{4} [A-Z]{1,2}\d*)', name)
    return m.group(1) if m else name


def jpl_magnitudes(name, start_utc, end_utc, step_days=5):
    """JPL Horizons total-magnitude (T-mag) prediction: list of (utc, mag)."""
    q = dict(format='json', COMMAND=f"'DES={horizons_designation(name)};CAP;NOFRAG'", OBJ_DATA="'NO'",
             MAKE_EPHEM="'YES'", EPHEM_TYPE="'OBSERVER'", CENTER="'500@399'",
             START_TIME=f"'{start_utc:%Y-%m-%d}'", STOP_TIME=f"'{end_utc:%Y-%m-%d}'", STEP_SIZE=f"'{step_days}d'",
             QUANTITIES="'9'")
    try:
        r = _s.get("https://ssd.jpl.nasa.gov/api/horizons.api", params=q, timeout=60).json().get('result', '')
    except (requests.RequestException, ValueError):
        return []
    a, b = r.find('$$SOE'), r.find('$$EOE')
    out = []
    for ln in r[a + 5:b].strip().splitlines() if a >= 0 else []:
        m = re.match(r'\s*(\d{4}-\w{3}-\d{2} \d{2}:\d{2})(.*)$', ln)
        if not m:
            continue
        nums = re.findall(r'(?<![\w.])-?\d+(?:\.\d*)?(?![\w.])', m.group(2))   # T-mag is the first number
        if nums:
            out.append((datetime.strptime(m.group(1), '%Y-%b-%d %H:%M').replace(tzinfo=timezone.utc),
                        float(nums[0])))
    return out


def comet_candidates(start_utc, days=90, limit_mag=12.0):
    """Comets that the MPC or JPL predicts at magnitude <= limit_mag in the next `days` days."""
    from skyfield.data import mpc
    from skyfield.constants import GM_SUN_Pitjeva_2005_km3_s2 as GM_SUN
    raw = _cached_file(COMET_URL, 'CometEls.txt')
    df = mpc.load_comets_dataframe(io.BytesIO(raw))
    df = df.sort_values('reference').groupby('designation', as_index=False).last().set_index('designation', drop=False)
    sun = eph['sun']
    dates = [start_utc + timedelta(days=d) for d in range(0, days + 1, 5)]
    tt = ts.from_datetimes(dates)
    out = []
    for name, row in df.iterrows():
        H, n, q = row['magnitude_g'], row['magnitude_k'], row['perihelion_distance_au']
        if not (np.isfinite(H) and np.isfinite(n) and np.isfinite(q)):
            continue
        if n >= 0 and H + 2.5 * n * math.log10(max(q, 1e-3)) + 5 * math.log10(max(q - 1.017, 0.01)) > limit_mag + 3:
            continue                                   # cannot get anywhere near bright enough
        try:
            c = sun + mpc.comet_orbit(row, ts, GM_SUN)
            ec = EARTH.at(tt).observe(c)
            delta = ec.distance().au
            r = np.linalg.norm(c.at(tt).position.au - sun.at(tt).position.au, axis=0)
            elong = EARTH.at(tt).observe(sun).separation_from(ec).degrees
        except Exception:
            continue
        mag = H + 5 * np.log10(delta) + 2.5 * n * np.log10(r)
        seen = elong >= MIN_ELONG                     # too close to the Sun to be seen otherwise
        if seen.any() and np.nanmin(mag[seen]) <= limit_mag + 3:
            peri = datetime(int(row['perihelion_year']), int(row['perihelion_month']), 1, tzinfo=timezone.utc) + \
                timedelta(days=float(row['perihelion_day']) - 1)
            out.append(dict(name=name, H=float(H), n=float(n), q=float(q), e=float(row['eccentricity']),
                            perihelion=peri, dates=dates, mpc=[float(x) for x in mag], r=[float(x) for x in r],
                            delta=[float(x) for x in delta], elong=[float(x) for x in elong],
                            seen=[bool(x) for x in seen], row=row))
    for c in out:
        jm = jpl_magnitudes(c['name'], dates[0], dates[-1])
        c['jpl'] = [m for _, m in jm] if len(jm) == len(dates) else None
        c['mpc_best'] = min(m for m, ok in zip(c['mpc'], c['seen']) if ok)
        c['jpl_best'] = min(m for m, ok in zip(c['jpl'], c['seen']) if ok) if c['jpl'] else None
        c['best'] = min(x for x in (c['mpc_best'], c['jpl_best']) if x is not None)
    keep = [c for c in out if c['best'] <= limit_mag]
    keep.sort(key=lambda c: c['best'])
    return keep


def comet_tonight(c, lat, lon, elev_m, win):
    """Best altitude of the comet while the Sun is below -12 deg during the night window."""
    from skyfield.data import mpc
    from skyfield.constants import GM_SUN_Pitjeva_2005_km3_s2 as GM_SUN
    body = eph['sun'] + mpc.comet_orbit(c['row'], ts, GM_SUN)
    times = [win['start'] + timedelta(minutes=20 * i) for i in
             range(int((win['end'] - win['start']).total_seconds() // 1200) + 1)]
    t = ts.from_datetimes(times)
    obs = astro.observer(lat, lon, elev_m)
    sun_alt = obs.at(t).observe(SUN).apparent().altaz()[0].degrees
    ap = obs.at(t).observe(body).apparent()
    alt, az, _ = ap.altaz()
    ok = sun_alt < -12
    a = np.where(ok, alt.degrees, -90)
    i = int(np.argmax(a))
    elong = float(EARTH.at(t[i]).observe(SUN).apparent().separation_from(EARTH.at(t[i]).observe(body).apparent()).degrees)
    from skyfield.api import load_constellation_map
    const = load_constellation_map()(ap[i])
    return dict(best_alt=float(a[i]), best_time=times[i] if a[i] > -90 else None, az=float(az.degrees[i]),
                elongation=elong, constellation=str(const), visible=bool(a[i] > 10))


# ==========================================================================================
# sky: forecast within 16 days, typical cloudiness beyond
# ==========================================================================================
ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"


def cloud_history(lat, lon, years=10):
    end = datetime.now(timezone.utc).year - 1
    r = _s.get(ARCHIVE, params=dict(latitude=f'{lat:.2f}', longitude=f'{lon:.2f}', start_date=f'{end - years + 1}-01-01',
                                    end_date=f'{end}-12-31', hourly='cloud_cover', timezone='GMT',
                                    timeformat='unixtime'), timeout=120)
    r.raise_for_status()
    h = r.json()['hourly']
    t = np.array(h['time'], dtype=float)
    cc = np.array([np.nan if v is None else v for v in h['cloud_cover']], dtype=float)
    return dict(time=t, cc=cc, years=f'{end - years + 1}-{end}')


def typical_clear(hist, when_utc, window_days=10, window_h=1):
    """Share of past hours (same season, same time of day) with cloud cover <= 30 %."""
    if hist is None:
        return None
    dt = np.array(hist['time'], dtype='datetime64[s]')
    doy = (dt - dt.astype('datetime64[Y]')).astype('timedelta64[D]').astype(int)
    hour = (dt - dt.astype('datetime64[D]')).astype('timedelta64[h]').astype(int)
    tdoy = when_utc.timetuple().tm_yday - 1
    d = np.abs(doy - tdoy)
    d = np.minimum(d, 365 - d)
    hh = np.abs(hour - when_utc.hour)
    hh = np.minimum(hh, 24 - hh)
    m = (d <= window_days) & (hh <= window_h) & np.isfinite(hist['cc'])
    if m.sum() < 30:
        return None
    return dict(clear=float(np.mean(hist['cc'][m] <= 30)), mean_cloud=float(np.mean(hist['cc'][m])),
                n=int(m.sum()), years=hist['years'])


def forecast_clear(fc, when_utc):
    """Forecast chance of a clear view (0-1) from low/mid/high cloud at that hour."""
    import weather as wx
    tu = when_utc.timestamp()
    L, M, Hc = (wx.at(fc, k, tu) for k in ('cloud_cover_low', 'cloud_cover_mid', 'cloud_cover_high'))
    if not all(math.isfinite(x) for x in (L, M, Hc)):
        return None
    return dict(clear=(1 - L / 100) * (1 - M / 100) * (1 - 0.6 * Hc / 100), low=L, mid=M, high=Hc)
