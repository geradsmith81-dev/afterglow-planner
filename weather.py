"""
Afterglow - weather data from Open-Meteo (https://open-meteo.com, free, no key, CC BY 4.0).

  * forecast at the observer: total / low / mid / high cloud cover, cloud cover and
    geopotential height on 14 pressure levels (gives the height of each cloud layer),
    temperature, dew point, humidity, pressure (for refraction), visibility, rain;
  * low / mid / high cloud cover at points along the direction of the Sun or Moon
    (30 to 350 km away) - the clouds that decide whether sunlight reaches the sky above you;
  * CAMS aerosol optical depth and dust (air-quality API);
  * place search (geocoding API).

Open-Meteo's layers: low = surface to ~3 km, mid = ~3-8 km, high = above ~8 km.
"""
import math
from datetime import datetime, timezone

import numpy as np
import requests

FORECAST = "https://api.open-meteo.com/v1/forecast"
AIR = "https://air-quality-api.open-meteo.com/v1/air-quality"
GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"

LEVELS = [1000, 975, 950, 925, 900, 850, 800, 700, 600, 500, 400, 300, 250, 200]
SURFACE = ["temperature_2m", "dew_point_2m", "relative_humidity_2m", "surface_pressure", "cloud_cover",
           "cloud_cover_low", "cloud_cover_mid", "cloud_cover_high", "visibility", "precipitation",
           "precipitation_probability", "weather_code"]
RAY = ["cloud_cover", "cloud_cover_low", "cloud_cover_mid", "cloud_cover_high", "precipitation"]

MODELS = {
    'Best available (Open-Meteo picks)': 'best_match',
    'ECMWF IFS (Europe, global)': 'ecmwf_ifs025',
    'GFS (NOAA, global)': 'gfs_seamless',
    'ICON (DWD, global + Europe)': 'icon_seamless',
    'Météo-France (global + France)': 'meteofrance_seamless',
    'GEM (Canada)': 'gem_seamless',
    'JMA (Japan)': 'jma_seamless',
}

_s = requests.Session()


class WeatherError(RuntimeError):
    pass


def _arr(v):
    return np.array([np.nan if x is None else x for x in v], dtype=float)


def _get(url, params, timeout=40):
    try:
        r = _s.get(url, params=params, timeout=timeout)
    except requests.RequestException as e:
        raise WeatherError(f'Could not reach {url.split("/")[2]} ({type(e).__name__}).')
    if r.status_code != 200:
        try:
            msg = r.json().get('reason', r.text[:200])
        except Exception:
            msg = r.text[:200]
        raise WeatherError(f'{url.split("/")[2]} answered {r.status_code}: {msg}')
    return r.json()


def observer_forecast(lat, lon, model='best_match', days=7):
    hourly = SURFACE + [f"cloud_cover_{p}hPa" for p in LEVELS] + [f"geopotential_height_{p}hPa" for p in LEVELS]
    j = _get(FORECAST, dict(latitude=f'{lat:.4f}', longitude=f'{lon:.4f}', hourly=','.join(hourly),
                            models=model, timezone='GMT', timeformat='unixtime', past_days=1,
                            forecast_days=days))
    h = j['hourly']
    out = {k: _arr(h[k]) for k in h if k != 'time'}
    out['time'] = np.array(h['time'], dtype=float)
    out['model_elevation'] = j.get('elevation')
    return out


def ray_forecast(points, model='best_match', days=7):
    """points: list of (lat, lon).  Returns list of dicts (same order)."""
    res = []
    for i in range(0, len(points), 50):
        chunk = points[i:i + 50]
        j = _get(FORECAST, dict(latitude=','.join(f'{p[0]:.2f}' for p in chunk),
                                longitude=','.join(f'{p[1]:.2f}' for p in chunk),
                                hourly=','.join(RAY), models=model, timezone='GMT', timeformat='unixtime',
                                past_days=1, forecast_days=days), timeout=60)
        if isinstance(j, dict):
            j = [j]
        for item in j:
            h = item['hourly']
            d = {k: _arr(h[k]) for k in h if k != 'time'}
            d['time'] = np.array(h['time'], dtype=float)
            res.append(d)
    return res


def aerosol(lat, lon):
    j = _get(AIR, dict(latitude=f'{lat:.3f}', longitude=f'{lon:.3f}', hourly='aerosol_optical_depth,dust',
                       timezone='GMT', timeformat='unixtime', past_days=1, forecast_days=5))
    h = j['hourly']
    return dict(time=np.array(h['time'], dtype=float), aod=_arr(h['aerosol_optical_depth']), dust=_arr(h['dust']))


def search_places(name, count=8):
    if not name or len(name.strip()) < 2:
        return []
    j = _get(GEOCODE, dict(name=name.strip(), count=count, language='en', format='json'), timeout=20)
    out = []
    for r in j.get('results', []) or []:
        parts = [r.get('name'), r.get('admin1'), r.get('country')]
        out.append(dict(label=', '.join(p for p in parts if p), lat=r['latitude'], lon=r['longitude'],
                        elevation=r.get('elevation'), tz=r.get('timezone')))
    return out


# ------------------------------------------------------------------------------------------
def at(series, key, t_unix):
    """Linear interpolation of an hourly series at unix time t (NaN if outside)."""
    if series is None or key not in series:
        return float('nan')
    tt, v = series['time'], series[key]
    ok = np.isfinite(v)
    if ok.sum() < 2 or t_unix < tt[ok][0] or t_unix > tt[ok][-1]:
        return float('nan')
    return float(np.interp(t_unix, tt[ok], v[ok]))


def cloud_profile(fc, t_unix, ground_m):
    """Cloud cover (%) and height above ground (m) on each pressure level at time t."""
    rows = []
    for p in LEVELS:
        gh = at(fc, f'geopotential_height_{p}hPa', t_unix)
        cc = at(fc, f'cloud_cover_{p}hPa', t_unix)
        if not (math.isfinite(gh) and math.isfinite(cc)):
            continue
        if gh < ground_m - 50:          # level is below the ground here
            continue
        rows.append(dict(hpa=p, height_m=gh, above_ground_m=gh - ground_m, cover=cc))
    return rows


def lcl_height_m(temp_c, dew_c):
    """Lifting condensation level above ground (Espy): base of convective cloud."""
    if not (math.isfinite(temp_c) and math.isfinite(dew_c)):
        return float('nan')
    return max(0.0, 125.0 * (temp_c - dew_c))


def unix(dt_utc):
    return dt_utc.replace(tzinfo=timezone.utc).timestamp() if dt_utc.tzinfo is None else dt_utc.timestamp()
