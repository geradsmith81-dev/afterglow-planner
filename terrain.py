"""
Afterglow - terrain horizon from an open digital elevation model.

Elevation data: "Terrain Tiles" on the AWS Registry of Open Data (Mapzen/Tilezen,
Terrarium PNG encoding: metres = R*256 + G + B/256 - 32768).  The tiles merge SRTM
(~30 m), USGS 3DEP/NED (US, up to 10 m), GMTED2010, ETOPO1 and several national
models.  See https://registry.opendata.aws/terrain-tiles/ for the source list.

For each azimuth (every 0.5 deg) a ray is walked outwards from the observer and the
apparent elevation angle of the ground is computed with earth curvature and standard
terrestrial refraction (k = 0.13):

    angle = atan( (h - h_obs - d^2 (1 - k) / 2R) / d )

The skyline is the highest angle along the ray.  Near the observer the model uses
finer tiles (zoom 13, ~15 m) and further out coarser ones (down to zoom 8, ~500 m).
Terrain closer than `near_m` (default 200 m) is ignored, because DEM noise of a few
metres right next to the observer would otherwise produce a false wall.  Trees and
buildings are only partly present in the model, so a nearby wood or house can still
hide the sun when the app says it is visible.
"""
import io
import math
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import requests
from PIL import Image

TILE_URL = "https://elevation-tiles-prod.s3.amazonaws.com/terrarium/{z}/{x}/{y}.png"
CACHE_DIR = os.environ.get('AFTERGLOW_TILE_CACHE') or os.path.join(tempfile.gettempdir(), 'afterglow_tiles')
R_EARTH = 6371008.8
K_REFRACTION = 0.13
# (start m, end m, zoom, step m)
BANDS = [(0, 3000, 13, 15.0), (3000, 20000, 11, 50.0), (20000, 70000, 9, 150.0), (70000, 250000, 8, 400.0)]

_session = requests.Session()


class TerrainError(RuntimeError):
    pass


def _tile_path(z, x, y):
    return os.path.join(CACHE_DIR, str(z), str(x), f'{y}.png')


def fetch_tile(z, x, y):
    """Elevation (m, float32 256x256) of one tile, or None if it cannot be had."""
    n = 2 ** z
    x %= n
    if y < 0 or y >= n:
        return None
    p = _tile_path(z, x, y)
    raw = None
    if os.path.exists(p):
        try:
            with open(p, 'rb') as f:
                raw = f.read()
        except OSError:
            raw = None
    if raw is None:
        try:
            r = _session.get(TILE_URL.format(z=z, x=x, y=y), timeout=25)
            if r.status_code != 200:
                return None
            raw = r.content
            try:
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, 'wb') as f:
                    f.write(raw)
            except OSError:
                pass
        except requests.RequestException:
            return None
    try:
        a = np.asarray(Image.open(io.BytesIO(raw)).convert('RGB'), dtype=np.float32)
    except Exception:
        return None
    return a[..., 0] * 256.0 + a[..., 1] + a[..., 2] / 256.0 - 32768.0


def merc_px(lat, lon, z):
    """Global Web-Mercator pixel coordinates at zoom z (256-px tiles)."""
    s = 256.0 * 2 ** z
    lat = np.clip(lat, -85.05, 85.05)
    x = (np.asarray(lon) + 180.0) / 360.0 * s
    phi = np.radians(lat)
    y = (1.0 - np.log(np.tan(phi) + 1.0 / np.cos(phi)) / math.pi) / 2.0 * s
    return x, y


class Mosaic:
    """Tiles of one zoom level covering a lat/lon box, sampled bilinearly."""

    def __init__(self, z, lat_min, lat_max, lon_min, lon_max, workers=12):
        self.z = z
        x0, y1 = merc_px(lat_min, lon_min, z)
        x1, y0 = merc_px(lat_max, lon_max, z)
        self.tx0, self.tx1 = int(math.floor(x0 / 256)) - 0, int(math.floor(x1 / 256))
        self.ty0, self.ty1 = int(math.floor(y0 / 256)), int(math.floor(y1 / 256))
        nx, ny = self.tx1 - self.tx0 + 1, self.ty1 - self.ty0 + 1
        self.arr = np.full((ny * 256, nx * 256), np.nan, dtype=np.float32)
        jobs = [(tx, ty) for ty in range(self.ty0, self.ty1 + 1) for tx in range(self.tx0, self.tx1 + 1)]
        with ThreadPoolExecutor(max_workers=workers) as ex:
            tiles = list(ex.map(lambda j: fetch_tile(z, j[0], j[1]), jobs))
        self.n_tiles = len(jobs)
        self.n_missing = 0
        for (tx, ty), t in zip(jobs, tiles):
            if t is None:
                self.n_missing += 1
                continue
            r0, c0 = (ty - self.ty0) * 256, (tx - self.tx0) * 256
            self.arr[r0:r0 + 256, c0:c0 + 256] = t

    def sample(self, lat, lon):
        x, y = merc_px(lat, lon, self.z)
        u = x - self.tx0 * 256 - 0.5
        v = y - self.ty0 * 256 - 0.5
        H, W = self.arr.shape
        u = np.clip(u, 0, W - 1.001)
        v = np.clip(v, 0, H - 1.001)
        i0, j0 = np.floor(v).astype(int), np.floor(u).astype(int)
        fv, fu = v - i0, u - j0
        a = self.arr
        return ((a[i0, j0] * (1 - fu) + a[i0, j0 + 1] * fu) * (1 - fv)
                + (a[i0 + 1, j0] * (1 - fu) + a[i0 + 1, j0 + 1] * fu) * fv)


def destination(lat, lon, az_deg, dist_m):
    """Great-circle destination points (broadcasts az and dist)."""
    phi1, lam1 = math.radians(lat), math.radians(lon)
    th = np.radians(az_deg)
    dl = np.asarray(dist_m) / R_EARTH
    phi2 = np.arcsin(np.sin(phi1) * np.cos(dl) + np.cos(phi1) * np.sin(dl) * np.cos(th))
    lam2 = lam1 + np.arctan2(np.sin(th) * np.sin(dl) * np.cos(phi1), np.cos(dl) - np.sin(phi1) * np.sin(phi2))
    return np.degrees(phi2), np.degrees(lam2)      # longitude NOT wrapped (keeps tiles contiguous)


def point_elevation(lat, lon, z=13):
    m = Mosaic(z, lat - 0.001, lat + 0.001, lon - 0.001, lon + 0.001)
    v = float(m.sample(np.array([lat]), np.array([lon]))[0])
    if not np.isfinite(v):
        raise TerrainError('No elevation data could be downloaded for this place.')
    return v


def horizon(lat, lon, height_above_ground=1.7, ground_m=None, max_km=150.0, near_m=200.0, az_step=0.5,
            k=K_REFRACTION):
    """Skyline seen from (lat, lon).

    Returns dict: az (deg), angle (apparent elevation, deg), dist_km and ridge lat/lon of
    the point that forms the skyline, ground_dem (m), h_obs (m, eye level used),
    tiles, missing (tiles that could not be downloaded)."""
    az = np.arange(0.0, 360.0, az_step)
    max_m = max_km * 1000.0
    best = np.full(az.size, -90.0)
    best_d = np.zeros(az.size)
    best_lat = np.full(az.size, lat)
    best_lon = np.full(az.size, lon)
    tiles = missing = 0
    ground_dem = None
    h0 = floor = None
    for (d0, d1, z, step) in BANDS:
        if d0 >= max_m:
            break
        d1 = min(d1, max_m)
        start = max(d0, near_m) + step / 2.0
        if start >= d1:
            continue
        d = np.arange(start, d1, step)
        la, lo = destination(lat, lon, az[:, None], d[None, :])
        m = Mosaic(z, min(la.min(), lat) - 0.002, max(la.max(), lat) + 0.002,
                   min(lo.min(), lon) - 0.002, max(lo.max(), lon) + 0.002)
        tiles += m.n_tiles
        missing += m.n_missing
        if ground_dem is None:
            ground_dem = float(m.sample(np.array([lat]), np.array([lon]))[0])
            if not np.isfinite(ground_dem):
                raise TerrainError('No elevation data could be downloaded for this place '
                                   '(check the internet connection).')
            h0 = (ground_dem if ground_m is None else float(ground_m)) + float(height_above_ground)
            # Terrain Tiles hold sea-floor depths in the oceans; the sea surface is what is seen.
            floor = min(0.0, ground_dem)
        h = m.sample(la, lo)
        h = np.where(np.isfinite(h), np.maximum(h, floor), floor)
        drop = d ** 2 * (1.0 - k) / (2.0 * R_EARTH)
        ang = np.degrees(np.arctan2(h - h0 - drop[None, :], d[None, :]))
        j = np.argmax(ang, axis=1)
        a = ang[np.arange(az.size), j]
        better = a > best
        best = np.where(better, a, best)
        best_d = np.where(better, d[j], best_d)
        best_lat = np.where(better, la[np.arange(az.size), j], best_lat)
        best_lon = np.where(better, lo[np.arange(az.size), j], best_lon)
    if ground_dem is None:
        raise TerrainError('Terrain distance is too short.')
    return dict(az=az, angle=best, dist_km=best_d / 1000.0, lat=best_lat, lon=best_lon,
                ground_dem=ground_dem, h_obs=h0, tiles=tiles, missing=missing,
                max_km=max_km, near_m=near_m, k=k)


def sea_horizon_dip_deg(h_m, k=K_REFRACTION):
    """Apparent dip of a sea horizon seen from height h (deg) - used for self-checks."""
    return math.degrees(math.sqrt(2.0 * h_m * (1.0 - k) / R_EARTH))
