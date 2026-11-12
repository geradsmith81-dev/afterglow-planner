"""Afterglow - second page: night-sky quality for stargazing and the aurora."""
import html
import math
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import matplotlib.pyplot as plt
import numpy as np
import streamlit as st

import charts
import night_component as nc
import nightsky as ns
import space_weather as sw
import weather as wx


@st.cache_data(ttl=1800, max_entries=30, show_spinner=False)
def night_data(lat, lon, tz, day_iso, model, elev):
    day = date.fromisoformat(day_iso)
    win = ns.night_window(lat, lon, elev, day, tz)
    pts = ns.grid_points(lat, lon)
    msg = None
    try:
        grid = ns.fetch_grid(pts, win['hours'][0], win['hours'][-1], model)
    except wx.WeatherError as e:
        grid, msg = [None] * len(pts), (f'No cloud forecast for this night ({e}). Forecasts reach about '
                                         f'7 days ahead.')
    try:
        aq = wx.aerosol(round(lat, 2), round(lon, 2))
    except wx.WeatherError:
        aq = None
    scores, clouds, details = ns.score_grid(win, grid, aq)
    return dict(win=win, pts=pts, scores=scores, clouds=clouds, details=details, msg=msg)


@st.cache_data(ttl=600, show_spinner=False)
def get_ovation():
    return sw.ovation()


@st.cache_data(ttl=1800, show_spinner=False)
def get_kp():
    return sw.kp_series()


@st.cache_data(ttl=300, show_spinner=False)
def get_wind():
    return sw.solar_wind()


@st.cache_data(ttl=30 * 86400, max_entries=200, show_spinner=False)
def get_light(lat, lon):
    return ns.light_level(lat, lon)


def _hm(t, z):
    return t.astimezone(z).strftime('%H:%M') if t else '--:--'


def render(loc, tz, day, place_label, model, elev, on_pick):
    z = ZoneInfo(tz)
    lat, lon = round(loc['lat'], 5), round(loc['lon'], 5)
    with st.spinner('Reading the night forecast and the aurora data...'):
        N = night_data(lat, lon, tz, day.isoformat(), model, round(elev))
        aur_err = None
        try:
            ov = get_ovation()
        except sw.SpaceWeatherError as e:
            ov, aur_err = None, str(e)
        try:
            kp = get_kp()
        except sw.SpaceWeatherError as e:
            kp, aur_err = [], str(e)
        light = get_light(round(lat, 3), round(lon, 3))
    if N['msg']:
        st.warning(N['msg'])
    if aur_err:
        st.warning(f'Aurora data unavailable: {aur_err}')
    win, details = N['win'], N['details']

    # ---------------- summary cards
    dusk, dawn = win['astro_dark']
    if dusk and dawn and dusk['utc'] < dawn['utc']:
        dark_txt, dark_sub = f"{_hm(dusk['utc'], z)}-{_hm(dawn['utc'], z)}", 'fully dark (Sun below -18°)'
    else:
        lo = float(np.min(win['sun_alt'])) if len(win['sun_alt']) else 0.0
        dark_txt, dark_sub = 'no full dark', f'twilight all night (Sun lowest {lo:.0f}°)'
    mr = [e for e in win['events'] if e['key'] == 'moonrise_flat']
    ms = [e for e in win['events'] if e['key'] == 'moonset_flat']
    illum = win['info']['moon_illum']
    moon_up = [d for d in details if d.get('moon_alt', -1) > 0]
    moon_sub = (f"{win['info']['moon_phase_name'].lower()}, {illum * 100:.0f}% lit"
                + (f" · rises {_hm(mr[0]['utc'], z)}" if mr else '') + (f" · sets {_hm(ms[0]['utc'], z)}" if ms else ''))
    moon_txt = 'up all night' if len(moon_up) == len(details) else ('not up' if not moon_up else
                                                                    f'up {len(moon_up)} h')
    good = [d for d in details if d.get('score', -1) >= 0]
    if good:
        bd = max(good, key=lambda d: d['score'])
        bl, bc = ns.label_for(bd['score'])
        best_txt, best_sub = f"{bd['score']} {bl}", f"best hour at your spot: {_hm(bd['time'], z)}"
    else:
        best_txt, best_sub, bc = '--', 'no forecast', '#aab4c6'
    mlat = sw.geomagnetic_latitude(lat, lon)
    side = 'northern' if mlat >= 0 else 'southern'
    kp_over, kp_hor = sw.kp_needed(abs(mlat))
    night_kp = [k['kp'] for k in kp if win['start'] - timedelta(hours=3) <= k['time'] <= win['end']]
    kp_max = max(night_kp) if night_kp else None
    if kp_max is not None:
        outl = sw.outlook(abs(mlat), kp_max)
        aur_txt = {'overhead possible': 'Overhead possible', 'low on the horizon': f'Low in the {side[:-3]}',
                   'unlikely': 'Unlikely'}[outl]
        need = ('you live under the aurora zone' if kp_over < 1 else
                f'needs about Kp {kp_hor:.0f} (horizon) to {kp_over:.0f} (overhead)' if kp_over <= 9 else
                'needs an extreme storm here')
        aur_sub = f'tonight Kp up to {kp_max:.1f}; {need}'
    else:
        aur_txt, aur_sub = '--', 'Kp forecast unavailable'
    ov_here = sw.ovation_at(ov, lat, lon) if ov else None
    if ov_here:
        aur_sub += f" · NOAA now: {ov_here['visible']:.0f}% within sight"
    cards = [('Darkness', dark_txt, dark_sub, '#3d5ea8'), ('Moon', moon_txt, moon_sub, '#dcefff'),
             ('Stargazing', best_txt, best_sub, bc), ('Aurora', aur_txt, aur_sub, '#2ecc71')]
    st.markdown('<div class="ag-cards">' + ''.join(
        f'<div class="ag-card" style="border-top:3px solid {c}"><div class="k">{k}</div><div class="v" '
        f'style="font-size:1.35rem">{html.escape(v)}</div><div class="s">{html.escape(s)}</div></div>'
        for k, v, s, c in cards) + '</div>', unsafe_allow_html=True)
    sc_all = np.asarray(N['scores'])
    if sc_all.size and sc_all.max() >= 0:
        h, k = np.unravel_index(int(np.argmax(sc_all)), sc_all.shape)
        here_best = max([d['score'] for d in good], default=-1)
        if sc_all[h, k] > here_best + 10 and k != len(N['pts']) // 2:
            p0, p1 = (lat, lon), N['pts'][k]
            dy = (p1[0] - p0[0]) * 111.2
            dx = (p1[1] - p0[1]) * 111.32 * math.cos(math.radians(lat))
            bl, bcol = ns.label_for(int(sc_all[h, k]))
            st.markdown(f'<p class="ag-light"><b>Clearest sky within about 200 km tonight:</b> '
                        f'<span style="color:{bcol};font-weight:700">{int(sc_all[h, k])} {bl}</span> at '
                        f"{_hm(win['hours'][h], z)}, about {math.hypot(dx, dy):.0f} km "
                        f"{charts.compass(math.degrees(math.atan2(dx, dy)) % 360)} of you "
                        f'(the star on the map when the slider is at that hour).</p>', unsafe_allow_html=True)
    if light:
        st.markdown(f'<p class="ag-light"><b>Artificial light around you</b> (NASA Black Marble, rough guide): '
                    f'{html.escape(light[0])}. Turn on the "Light pollution" map layer to find darker places.</p>',
                    unsafe_allow_html=True)

    # ---------------- the map
    ov_cells = sw.ovation_cells(ov, lat, lon) if ov else []
    data = nc.build_data(loc, tz, day, place_label, win, N['pts'], N['scores'], N['clouds'], details, ov_cells,
                         ns.GRID_STEP_KM)
    nc.show(data, on_pick=on_pick)
    ov_time = f" NOAA aurora map valid {_hm(ov['forecast'], z)}." if ov else ''
    st.caption('Coloured squares: forecast sky quality for stargazing at the hour on the slider, on a 50 km grid '
               '(about 300 x 300 km around you). The star marks the clearest square that hour. Green/yellow/red '
               f'cells further out are NOAA\'s live aurora oval.{ov_time} Tap the map and "Plan from here" to move.')

    # ---------------- details
    t1, t2, t3 = st.tabs(['Tonight hour by hour', 'Aurora', 'How the night forecast works'])
    with t1:
        if good:
            fig = charts.tonight(details, tz, f'Night of {day:%a %d %b} at your spot: sky quality and clouds')
            st.pyplot(fig, width='stretch')
            plt.close(fig)
            rows = ''.join(
                f"<tr><td>{_hm(d['time'], z)}</td><td><span class='ag-pill' style='background:{ns.label_for(d['score'])[1]}'>"
                f"{d['score']}</span></td><td>{d['low']:.0f} / {d['mid']:.0f} / {d['high']:.0f}%</td>"
                f"<td>{d['sun_alt']:.0f}°</td><td>{'up ' + format(d['moon_alt'], '.0f') + '°' if d['moon_alt'] > 0 else 'down'}</td>"
                f"<td>{d['rh']:.0f}%</td><td>{html.escape(d['steadiness'])}</td></tr>"
                for d in details if d.get('score', -1) >= 0)
            st.markdown('<div class="ag-wrap"><table class="ag-tab"><tr><th>Hour</th><th>Quality</th>'
                        '<th>Cloud low / mid / high</th><th>Sun</th><th>Moon</th><th>Humidity</th>'
                        '<th>Steadiness</th></tr>' + rows + '</table></div>', unsafe_allow_html=True)
            st.caption('Steadiness comes from the jet-stream wind at about 10 km (250 hPa): strong wind makes stars '
                       'twinkle and blurs telescope views, but matters little for the naked eye or wide photos.')
        else:
            st.info('No hourly forecast for this night.')
    with t2:
        hemi = 'Aurora Borealis (northern lights)' if mlat >= 0 else 'Aurora Australis (southern lights)'
        st.markdown(f"**{hemi}.** Your geomagnetic latitude is **{abs(mlat):.1f}°**. With this rule of thumb the "
                    f"aurora reaches overhead from about **Kp {kp_over:.1f}** and shows low on the {side} horizon "
                    f"from about **Kp {kp_hor:.1f}**.")
        if kp:
            fig = charts.kp_chart(kp, tz, abs(mlat), kp_over, kp_hor)
            st.pyplot(fig, width='stretch')
            plt.close(fig)
        c1, c2 = st.columns(2)
        with c1:
            if ov_here:
                d_txt = (f" The nearest strong aurora is about {ov_here['dist_km']:.0f} km to the "
                         f"{charts.compass(ov_here['az'])}." if ov_here['az'] is not None and ov_here['dist_km'] > 50 else '')
                st.markdown(f"**NOAA aurora nowcast** (valid {_hm(ov['forecast'], z)}): chance overhead "
                            f"**{ov_here['overhead']:.0f}%**, chance of seeing it somewhere in your sky about "
                            f"**{ov_here['visible']:.0f}%**.{d_txt}")
        with c2:
            try:
                w = get_wind()
                bz_word = ('southward - good for aurora' if w['bz'] <= -5 else
                           'slightly southward' if w['bz'] < 0 else 'northward - aurora less likely')
                st.markdown(f"**Solar wind now** ({_hm(w['time'], z)}): speed **{w['speed']:.0f} km/s**"
                            f"{' (fast)' if w['speed'] >= 500 else ''}, magnetic field Bz **{w['bz']:+.0f} nT** "
                            f"({bz_word}).")
            except sw.SpaceWeatherError:
                st.markdown('Solar wind data unavailable.')
        st.caption('The aurora needs three things at once: geomagnetic activity reaching your latitude, darkness, and '
                   'clear sky toward the pole. Cameras pick it up more easily than eyes. Kp forecasts more than a day '
                   'ahead are uncertain; the NOAA nowcast covers only the next 30-90 minutes.')
    with t3:
        st.markdown("""
**Sky quality (0-100)** for each hour and each grid square multiplies three things:

1. **Clear sky**: forecast low, mid and high cloud (Open-Meteo). Low and mid cloud hide the stars; thin high
   cloud (cirrus) hides about 60 % of them.
2. **Darkness**: the Sun must be well below the horizon (fully dark after astronomical dusk, Sun at -18°),
   and a bright Moon above the horizon washes out faint stars.
3. **Transparency**: humid air (dew, haze), poor visibility and smoke or dust (CAMS aerosol forecast) dim the sky.

Light pollution is **not** in the score, because it does not change from night to night; use the
"Light pollution" map layer (NASA Black Marble night lights) to choose a dark site. Live infrared satellite
layers (GOES, Himawari) show where the clouds are right now, also at night.

**Aurora**: NOAA SWPC's OVATION model gives the live aurora oval (next 30-90 minutes); the Kp forecast covers
3 days. Geomagnetic latitude is from the IGRF-14 (2025) dipole. The Kp-to-latitude rule (oval edge about
66° - 2 x Kp) is an approximation of NOAA's maps.
""")
