"""Afterglow - third page: solar and lunar eclipses, meteor showers and comets, with a sky outlook."""
import html
import math
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import matplotlib.pyplot as plt
import numpy as np
import streamlit as st

import astro
import charts
import events as ev
import events_component as ec
import night_component as nc
import night_page
import nightsky as ns
import skymap
import weather as wx

FORECAST_DAYS = 15.5


# ------------------------------------------------------------------------------------------
# cached data
# ------------------------------------------------------------------------------------------
@st.cache_data(ttl=86400, show_spinner=False)
def eclipse_lists(start_iso, years):
    s = datetime.fromisoformat(start_iso)
    e = s + timedelta(days=365.25 * years)
    return ev.solar_eclipses(s, e), ev.lunar_eclipses(s, e)


@st.cache_data(ttl=86400, max_entries=200, show_spinner=False)
def solar_local(ecl, lat, lon, elev, hz_key):
    return ev.solar_local(ecl, lat, lon, elev, _hfn(hz_key))


@st.cache_data(ttl=86400, max_entries=200, show_spinner=False)
def lunar_local(ecl, lat, lon, elev, hz_key):
    return ev.lunar_local(ecl, lat, lon, elev, _hfn(hz_key))


@st.cache_data(ttl=7 * 86400, max_entries=40, show_spinner=False)
def world(ecl):
    if ecl['kind'] == 'solar':
        return ev.solar_world_grid(ecl), ev.central_line(ecl), ev.path_width_km(ecl)
    return ev.lunar_world_grid(ecl), [], None


@st.cache_data(ttl=86400, show_spinner=False)
def peaks(start_iso):
    return ev.shower_peaks(datetime.fromisoformat(start_iso))


@st.cache_data(ttl=86400, max_entries=100, show_spinner=False)
def shower_night(sh, lat, lon, elev, tz, lp):
    return ev.shower_night(sh, lat, lon, elev, tz, lp)


@st.cache_data(ttl=12 * 3600, show_spinner=False)
def comets(start_iso):
    out = ev.comet_candidates(datetime.fromisoformat(start_iso))
    for c in out:
        c.pop('row', None)                        # keep the cache small; the orbit is rebuilt when needed
    return out


@st.cache_data(ttl=12 * 3600, show_spinner=False)
def comet_rows():
    from skyfield.data import mpc
    import io
    df = mpc.load_comets_dataframe(io.BytesIO(ev._cached_file(ev.COMET_URL, 'CometEls.txt')))
    return df.sort_values('reference').groupby('designation', as_index=False).last().set_index('designation', drop=False)


@st.cache_data(ttl=3600, max_entries=60, show_spinner=False)
def radiant_sky(sh, lat, lon, elev, tz, evening_iso, best_time):
    from skyfield.api import Star
    win = ns.night_window(lat, lon, elev, date.fromisoformat(evening_iso), tz)
    target = Star(ra_hours=sh['ra'] / 15.0, dec_degrees=sh['dec'])
    hint = ('Meteors can appear anywhere in the sky; their trails point back to this spot (the radiant). '
            'Face this way, lie back and look about halfway up the sky, a little to one side of the radiant: '
            'meteors there show longer trails. The higher the radiant, the more meteors you see.')
    return skymap.build(lat, lon, elev, tz, skymap.night_times(win), target, f"{sh['name']} radiant",
                        best_time, 'radiant', hint)


@st.cache_data(ttl=3600, max_entries=60, show_spinner=False)
def comet_sky(name, lat, lon, elev, tz, day_iso, best_time, mag_txt):
    from skyfield.data import mpc
    from skyfield.constants import GM_SUN_Pitjeva_2005_km3_s2 as GM_SUN
    row = comet_rows().loc[name]
    body = astro.eph['sun'] + mpc.comet_orbit(row, astro.ts, GM_SUN)
    win = ns.night_window(lat, lon, elev, date.fromisoformat(day_iso), tz)
    hint = (f'Predicted magnitude now {mag_txt} (MPC / JPL). Brighter than 6 is a naked-eye object under a dark sky, '
            f'up to 9 needs binoculars, up to 12 a small telescope. Use the bright stars on the map to find the spot, '
            f'then sweep slowly with binoculars.')
    return skymap.build(lat, lon, elev, tz, skymap.night_times(win), body, name, best_time, 'comet', hint)


@st.cache_data(ttl=30 * 86400, max_entries=40, show_spinner=False)
def history(lat, lon):
    try:
        return ev.cloud_history(lat, lon)
    except Exception:
        return None


@st.cache_data(ttl=1800, max_entries=40, show_spinner=False)
def forecast16(lat, lon, model):
    for days in (16, 7):
        try:
            return wx.observer_forecast(lat, lon, model, days)
        except wx.WeatherError:
            continue
    return None


_HZ = {}


def _hfn(key):
    prof = _HZ.get(key)
    return astro.horizon_fn(prof) if prof is not None else None


# ------------------------------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------------------------------
def _hm(t, z, fmt='%H:%M'):
    return t.astimezone(z).strftime(fmt) if t else '--'


def _pill(text, colour):
    return f"<span class='ag-pill' style='background:{colour}'>{html.escape(text)}</span>"


def sky_outlook(when, fc, hist):
    """(short html, long text) for the sky at a moment: forecast within ~15 days, typical beyond."""
    now = datetime.now(timezone.utc)
    if when is None:
        return '-', ''
    if now - timedelta(hours=1) <= when <= now + timedelta(days=FORECAST_DAYS) and fc is not None:
        f = ev.forecast_clear(fc, when)
        if f:
            pct = round(f['clear'] * 100)
            name, col = ns.label_for(pct)
            return (_pill(f'{pct}%', col) + ' forecast',
                    f"Forecast for that hour: {pct}% chance of a clear view (cloud low {f['low']:.0f}%, "
                    f"mid {f['mid']:.0f}%, high {f['high']:.0f}%).")
    t = ev.typical_clear(hist, when)
    if t:
        pct = round(t['clear'] * 100)
        name, col = ns.label_for(pct)
        return (_pill(f'{pct}%', col) + ' typical',
                f"Typical for this place, season and hour: {pct}% of hours had a mostly clear sky (cloud 30% or less) "
                f"in {t['years']}; average cloud {t['mean_cloud']:.0f}%. This is history, not a forecast; a forecast "
                f"appears about two weeks before.")
    return '-', 'No sky outlook available.'


def _table(head, rows):
    return ('<div class="ag-wrap"><table class="ag-tab"><tr>' + ''.join(f'<th>{h}</th>' for h in head) + '</tr>'
            + ''.join('<tr>' + ''.join(f'<td>{c}</td>' for c in r) + '</tr>' for r in rows) + '</table></div>')


def _table_ids(head, rows, ids):
    return ('<div class="ag-wrap"><table class="ag-tab"><tr>' + ''.join(f'<th>{h}</th>' for h in head) + '</tr>'
            + ''.join(f'<tr data-id="{html.escape(i)}">' + ''.join(f'<td>{c}</td>' for c in r) + '</tr>'
                      for i, r in zip(ids, rows)) + '</table></div>')


def _dur(sec):
    if sec is None:
        return ''
    m, s = divmod(int(round(sec)), 60)
    return f'{m} min {s:02d} s'


def _night_map(loc, tz, day, place_label, model, elev, on_pick, key, hour_utc=None):
    """The night page's sky-quality map for a given night (only within the forecast range)."""
    N = night_page.night_data(round(loc['lat'], 5), round(loc['lon'], 5), tz, day.isoformat(), model, round(elev))
    if N['msg']:
        st.caption(N['msg'])
        return
    data = nc.build_data(loc, tz, day, place_label, N['win'], N['pts'], N['scores'], N['clouds'], N['details'], [],
                         ns.GRID_STEP_KM)
    if hour_utc is not None:
        hrs = [h.timestamp() for h in N['win']['hours']]
        data['initial'] = int(np.argmin([abs(h - hour_utc.timestamp()) for h in hrs]))
    data['nonce'] = data['nonce'] + key
    nc.show(data, on_pick=on_pick, key=key)


# ------------------------------------------------------------------------------------------
def render(loc, tz, day, place_label, model, elev, pick_for, profile=None):
    z = ZoneInfo(tz)
    lat, lon = round(loc['lat'], 5), round(loc['lon'], 5)
    hz_key = f'{lat},{lon}'
    _HZ[hz_key] = profile
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    fc = forecast16(round(lat, 3), round(lon, 3), model)
    section = st.radio('Show', ['Eclipses', 'Meteor showers', 'Comets'], horizontal=True, key='ev_section',
                       label_visibility='collapsed')
    with st.spinner('Reading 10 years of cloud history for this place...'):
        hist = history(round(lat, 2), round(lon, 2))

    st.caption('Sources: Sun and Moon from NASA JPL DE440s (Skyfield); eclipses checked against NASA\'s eclipse '
               'catalogue (F. Espenak, GSFC); meteor showers from the International Meteor Organization 2026 calendar; '
               'comet orbits from the IAU Minor Planet Center and magnitudes also from JPL Horizons; forecast and '
               'cloud history (ERA5 reanalysis) from Open-Meteo.')

    # ======================================================================================
    if section == 'Eclipses':
        c1, c2 = st.columns([2, 1], vertical_alignment='bottom')
        years = c1.slider('Years ahead', 2, 14, 10, key='ev_years')
        only = c2.checkbox('Only eclipses visible from here', value=True, key='ev_only')
        with st.spinner('Finding eclipses (NASA JPL ephemeris)...'):
            se, le = eclipse_lists(now.replace(hour=0).isoformat(), years)
        items = []
        for e in se:
            L = solar_local(e, lat, lon, round(elev), hz_key)
            items.append((e, L))
        for e in le:
            items.append((e, lunar_local(e, lat, lon, round(elev), hz_key)))
        items.sort(key=lambda x: x[0]['greatest'])
        rows, choices = [], []
        for e, L in items:
            vis = bool(L and L['visible'])
            if only and not vis:
                continue
            when = None
            if e['kind'] == 'solar':
                what = f"{e['type']} solar"
                if L is None:
                    here = 'not seen from here'
                elif L['type'] in ('Total', 'Annular') and L['central_s']:
                    here = f"<b>{L['type'].lower()}</b> for {_dur(L['central_s'])}" + ('' if L['max_visible'] else ' (Sun low or down)')
                    when = L['contacts']['MAX']['utc']
                else:
                    here = f"partial, {L['obscuration'] * 100:.0f}% of the Sun covered" + ('' if L['visible'] else ' - Sun below the horizon')
                    when = L['contacts']['MAX']['utc']
                    if not L['visible']:
                        here = 'not visible (Sun below the horizon)'
            else:
                what = f"{e['type']} lunar"
                mx = next(r for r in L['rows'] if r['code'] == 'MAX')
                here = L['verdict'] + (f", Moon {mx['alt']:.0f}° high at greatest" if mx['up'] else '')
                when = mx['utc']
            sky = sky_outlook(when, fc, hist)[0] if (vis and when) else ''
            t_local = (when or e['greatest']).astimezone(z)
            rows.append([f"{t_local:%a %d %b %Y}", what, here, f"{t_local:%H:%M}" if vis else '', sky])
            choices.append((e, L))
        if not rows:
            st.info('No eclipse is visible from here in this period. Untick "Only eclipses visible from here" '
                    'to see all of them, or look further ahead.')
            return
        ids = [e['id'] for e, _ in choices]
        prev = st.session_state.get('ev_rowpick')
        prev = prev.get('row') if hasattr(prev, 'get') else None
        sel = prev if prev in ids else ids[0]
        st.markdown('**Tap an eclipse in the table to show it on the map below.**')
        chosen = ec.row_picker(_table_ids(['Date', 'Eclipse', 'From your location', 'Best moment', 'Sky'], rows, ids),
                               sel, 'ev_rowpick')
        if chosen in ids:
            sel = chosen
        st.caption('Sky: forecast chance of a clear view when the eclipse is within about two weeks; beyond that, how '
                   'often the sky was mostly clear at this place, season and hour in the past 10 years.')
        e, L = choices[ids.index(sel)]
        _eclipse_details(e, L, loc, tz, place_label, fc, hist, pick_for('evmap'))

    # ======================================================================================
    elif section == 'Meteor showers':
        light = night_page.get_light(round(lat, 3), round(lon, 3))
        lp = ev.light_pollution_penalty(light[1] if light else None)
        with st.spinner('Working out the meteor showers for the next 12 months...'):
            pk = peaks(now.isoformat())
        rows, nights = [], []
        for sh in pk:
            n = shower_night(sh, lat, lon, round(elev), tz, lp)
            nights.append(n)
            bt = n['best_time']
            sky = sky_outlook(bt, fc, hist)[0] if bt else ''
            rate = (f"{n['best_dark']:.0f} / {n['best_here']:.0f}" if bt else 'radiant not up in the dark')
            rows.append([f"<b>{html.escape(sh['name'])}</b>", f"{sh['peak'].astimezone(z):%a %d %b %H:%M}",
                         str(sh['zhr']), f"{n['moon_at_peak'] * 100:.0f}%",
                         (f"{bt.astimezone(z):%a %d %b %H:%M}" if bt else f"night of {n['evening']:%d %b}"),
                         rate, f"{max(n['rad_max'], 0):.0f}°", sky])
        st.markdown(_table(['Shower', 'Peak (your time)', 'ZHR', 'Moon lit', 'Best hour', 'Meteors per hour: dark sky / '
                                                                                         'your sky', 'Radiant highest',
                            'Sky'], rows), unsafe_allow_html=True)
        lp_word = light[0] if light else 'unknown'
        st.caption(f'ZHR: the rate under ideal conditions with the radiant overhead (IMO 2026 calendar). Meteors per '
                   f'hour are an estimate for one observer from the radiant height, twilight and moonlight; "your sky" '
                   f'also allows for the artificial light around you ({lp_word}). Rates fall off on nights away from the '
                   f'peak; the Quadrantid peak lasts only a few hours.')
        names = [f"{sh['name']} - peak {sh['peak'].astimezone(z):%d %b}" for sh in pk]
        k = st.selectbox('Shower details', range(len(names)), format_func=lambda i: names[i], key='ev_shower')
        sh, n = pk[k], nights[k]
        fig = charts.meteor_night(n, sh['name'], tz)
        st.pyplot(fig, width='stretch')
        plt.close(fig)
        bt = n['best_time']
        long = sky_outlook(bt, fc, hist)[1] if bt else ''
        st.markdown(f"**{sh['name']}** - active {sh['active']}; radiant RA {sh['ra']}°, Dec {sh['dec']:+d}°; meteors "
                    f"enter at {sh['v']} km/s" + (f"; debris of **{sh['parent']}**" if sh['parent'] else '') + '. '
                    + html.escape(long))
        st.markdown(f"**Where to look: the radiant of the {sh['name']}**")
        sky = radiant_sky(sh, lat, lon, round(elev), tz, n['evening'].isoformat(), bt)
        ec.show_sky(sky, key='ev_sky_shower')
        if bt and now <= bt <= now + timedelta(days=FORECAST_DAYS):
            st.markdown('**Sky-quality map for that night** (move the slider to the best hour):')
            _night_map(loc, tz, n['evening'], place_label, model, elev, pick_for('ev_night_shower'),
                       'ev_night_shower', bt)

    # ======================================================================================
    else:
        st.caption('Predicted comet brightness is uncertain: the Minor Planet Center and JPL fit different formulas '
                   'and often disagree by several magnitudes, and comets can flare or fade. Both predictions are shown. '
                   'Magnitude 6 is about the faintest a naked eye sees under a dark sky, 9 needs binoculars, 12 a small '
                   'telescope.')
        with st.spinner('Checking about 1,000 comet orbits from the Minor Planet Center (once a day)...'):
            try:
                cl = comets(now.replace(hour=0).isoformat())
            except Exception as e:
                st.warning(f'Comet data unavailable ({type(e).__name__}).')
                return
        if not cl:
            st.info('No comet is predicted to be brighter than magnitude 12 in the next 90 days.')
            return
        cl = sorted(cl, key=lambda c: max(c['mpc_best'], c['jpl_best'] if c['jpl_best'] is not None else c['mpc_best']))
        win = ns.night_window(lat, lon, round(elev), day, tz)
        rows_df = comet_rows()
        rows = []
        tonight = []
        for c in cl:
            c = dict(c, row=rows_df.loc[c['name']])
            tn = ev.comet_tonight(c, lat, lon, round(elev), win)
            tonight.append(tn)
            i_m = int(np.argmin(c['mpc']))
            jp = f"{c['jpl_best']:.1f}" if c['jpl_best'] is not None else 'n/a'
            now_rng = f"{c['mpc'][0]:.1f} / {c['jpl'][0]:.1f}" if c['jpl'] else f"{c['mpc'][0]:.1f} / n/a"
            if tn['visible']:
                tt = (f"{tn['best_alt']:.0f}° high at {_hm(tn['best_time'], z)}, {charts.compass(tn['az'])}, "
                      f"in {tn['constellation']}")
            else:
                tt = 'not well placed' + (f" (only {max(tn['best_alt'], 0):.0f}° up)" if tn['best_alt'] > -90 else '')
            sky = sky_outlook(tn['best_time'], fc, hist)[0] if tn['visible'] else ''
            rows.append([f"<b>{html.escape(c['name'])}</b>", now_rng,
                         f"{c['mpc_best']:.1f} / {jp}", f"{c['perihelion']:%d %b %Y}, {c['q']:.2f} au", tt, sky])
        ids = [c['name'] for c in cl]
        prev = st.session_state.get('ev_cometpick')
        prev = prev.get('row') if hasattr(prev, 'get') else None
        sel = prev if prev in ids else ids[0]
        st.markdown('**Tap a comet in the table to show where to find it.**')
        chosen = ec.row_picker(_table_ids(['Comet', 'Magnitude now (MPC / JPL)',
                                           'Brightest in 90 days, away from the Sun (MPC / JPL)',
                                           'Closest to the Sun', f'Tonight ({day:%d %b})', 'Sky tonight'], rows, ids),
                               sel, 'ev_cometpick')
        if chosen in ids:
            sel = chosen
        k = ids.index(sel)
        st.subheader(cl[k]['name'])
        st.markdown(f"**Where to find {html.escape(cl[k]['name'])} tonight**")
        sky = comet_sky(cl[k]['name'], lat, lon, round(elev), tz, day.isoformat(),
                        tonight[k]['best_time'] if tonight[k]['visible'] else None,
                        f"{cl[k]['mpc'][0]:.1f}" + (f" / {cl[k]['jpl'][0]:.1f}" if cl[k]['jpl'] else ''))
        ec.show_sky(sky, key='ev_sky_comet')
        fig = charts.comet_brightness(cl[k], tz)
        st.pyplot(fig, width='stretch')
        plt.close(fig)
        tn = tonight[k]
        if tn['visible']:
            st.markdown(f"Tonight it is highest in the dark at **{_hm(tn['best_time'], z)}**, {tn['best_alt']:.0f}° "
                        f"above the {charts.compass(tn['az'])} horizon in {tn['constellation']}, "
                        f"{tn['elongation']:.0f}° from the Sun. " + html.escape(sky_outlook(tn['best_time'], fc, hist)[1]))
            if tn['best_time'] and tn['best_time'] <= now + timedelta(days=FORECAST_DAYS):
                st.markdown("**Tonight's sky-quality map:**")
                _night_map(loc, tz, day, place_label, model, elev, pick_for('ev_night_comet'), 'ev_night_comet',
                           tn['best_time'])
        else:
            st.markdown(f"Not well placed tonight: it is {tn['elongation']:.0f}° from the Sun and at best "
                        f"{max(tn['best_alt'], 0):.0f}° up while it is dark.")


# ------------------------------------------------------------------------------------------
def _eclipse_details(e, L, loc, tz, place_label, fc, hist, on_pick):
    z = ZoneInfo(tz)
    st.subheader(f"{e['type']} {e['kind']} eclipse, {e['greatest'].astimezone(z):%A %d %B %Y}")
    if e['kind'] == 'solar':
        st.warning('Never look at the Sun, even when it is mostly covered, without certified eclipse glasses '
                   '(ISO 12312-2) or a proper solar filter on binoculars and cameras. Only during totality itself '
                   'is it safe to look without them.')
    map_box = st.container()          # the map goes here, above the timetable
    if e['kind'] == 'solar':
        if L:
            rows = []
            for code, label in (('C1', 'Eclipse begins (first contact)'), ('C2', f"{L['type']} phase begins"),
                                ('MAX', 'Greatest eclipse'), ('C3', f"{L['type']} phase ends"),
                                ('C4', 'Eclipse ends (last contact)')):
                c = L['contacts'].get(code)
                if not c:
                    continue
                rows.append([_hm(c['utc'], z, '%H:%M:%S'), label, f"{c['alt']:.0f}°", f"{c['az']:.0f}° {charts.compass(c['az'])}",
                             'yes' if c['up'] else 'no (below the horizon)'])
            st.markdown(_table(['Time', 'Event', 'Sun altitude', 'Direction', 'Sun above your skyline?'], rows),
                        unsafe_allow_html=True)
            mx = L['contacts']['MAX']['utc']
            st.markdown(f"From here: **{L['type'].lower()}**, magnitude {L['magnitude']:.3f}, "
                        f"**{L['obscuration'] * 100:.1f}%** of the Sun's area covered at greatest eclipse"
                        + (f", {L['type'].lower()} for **{_dur(L['central_s'])}**" if L['central_s'] else '') + '. '
                        + html.escape(sky_outlook(mx, fc, hist)[1]))
        else:
            st.markdown('This eclipse is not seen from your location; the map shows where it is.')
        cells, line, width = world(e)
        breaks = [[0.8, '#ff4f7b'], [0.6, '#ff7a3d'], [0.4, '#f2b13d'], [0.2, '#c9b28a'], [0.0, '#7d8799']]
        legend = [['20% or less', '#7d8799'], ['20-40%', '#c9b28a'], ['40-60%', '#f2b13d'], ['60-80%', '#ff7a3d'],
                  ['80% or more', '#ff4f7b']]
        title = (f"{e['type']} solar eclipse, {e['greatest'].astimezone(z):%d %b %Y}: coloured areas see the Sun partly covered "
                 f"(share of its diameter)")
        line_label = (f"central line ({e['type'].lower()}" + (f", band about {width:.0f} km wide" if width else '') + ')')
        data = dict(lat=loc['lat'], lon=loc['lon'], place=place_label, cells=cells, step=3.0, breaks=breaks,
                    legend=legend, legend_title='Sun covered:', line=line, line_colour='#ffffff', line_label=line_label,
                    title=title, zoom=2, nonce=e['id'])
    else:
        rows = [[_hm(r['utc'], z, '%H:%M'), r['label'], f"{r['alt']:.0f}°", f"{r['az']:.0f}° {charts.compass(r['az'])}",
                 'yes' if r['up'] else 'no'] for r in L['rows']]
        st.markdown(_table(['Time', 'Event', 'Moon altitude', 'Direction', 'Moon above your skyline?'], rows),
                    unsafe_allow_html=True)
        mx = next(r for r in L['rows'] if r['code'] == 'MAX')
        mag = (f"umbral magnitude {e['magnitude']:.3f}" if e['type'] != 'Penumbral'
               else f"penumbral magnitude {e['pen_magnitude']:.3f} (only a faint shading)")
        st.markdown(f"**{e['type']} lunar eclipse**, {mag}; from here: {L['verdict']}. Lunar eclipses are safe to watch "
                    f"with the naked eye. " + html.escape(sky_outlook(mx['utc'], fc, hist)[1]))
        cells, line, width = world(e)
        data = dict(lat=loc['lat'], lon=loc['lon'], place=place_label, cells=cells, step=3.0,
                    breaks=[[2, '#6fd0dc'], [1, '#2f6f86']], legend=[['whole eclipse', '#6fd0dc'],
                                                                     ['part of it (Moon rises or sets)', '#2f6f86']],
                    legend_title='Moon up:', line=[], title=f"{e['type']} lunar eclipse, {e['greatest'].astimezone(z):%d %b %Y}: "
                                                            f"where the Moon is above the horizon", zoom=2,
                    nonce=e['id'])
    # centre on you if the eclipse is seen here, otherwise on the area where it is best seen
    here = any(abs(c[0] - loc['lat']) <= 1.5 and abs(((c[1] - loc['lon'] + 180) % 360) - 180) <= 1.5 for c in cells)
    if here or not cells:
        data['view'] = [loc['lat'], loc['lon']]
    else:
        top = max(c[2] for c in cells)
        best = [c for c in cells if c[2] >= top - (0.05 if e['kind'] == 'solar' else 0)]
        lo0 = best[0][1]
        data['view'] = [float(np.mean([c[0] for c in best])),
                        float(lo0 + np.mean([((c[1] - lo0 + 180) % 360) - 180 for c in best]))]
    with map_box:
        ec.show(data, on_pick=on_pick, key='evmap')
