"""
Afterglow - sunrise, sunset, moonrise and moonset planner with terrain and cloud forecasts.

Run with:  streamlit run app.py
"""
import html
import os
import math
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import matplotlib.pyplot as plt
import streamlit as st

st.set_page_config(page_title='Afterglow', page_icon='assets/afterglow_icon.png', layout='wide',
                   initial_sidebar_state='collapsed')

import functools

import astro
import charts
import horizons_check as hc
import night_page
import places
import planner as pl
import planner_component as pc
import skycolor as sc
import terrain
import weather as wx

ss = st.session_state
N_DAYS = 7

# ------------------------------------------------------------------------------------------
# look
# ------------------------------------------------------------------------------------------
st.markdown("""
<style>
.block-container, [data-testid="stMainBlockContainer"] {padding-top: 4.6rem; max-width: 1250px;}
.ag-title {font-size: 2.1rem; font-weight: 800; margin: 0.4rem 0 0 0; line-height: 1.25; color: #ffcd9c; letter-spacing: .5px;}
.ag-sub {color: #c9d1e0; margin: 0 0 .6rem 0;}
.ag-cards, .ag-score, .ag-tab, .ag-wrap {color: #f4efe8;}
.ag-cards {display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin: 6px 0 10px;}
@media (max-width: 760px) {.ag-cards {grid-template-columns: repeat(2, minmax(0, 1fr));}}
.ag-card {background: #111927; border: 1px solid #2a3550; border-radius: 12px; padding: 10px 12px;}
.ag-card .k {font-size: .8rem; color: #aab4c6; text-transform: uppercase; letter-spacing: .6px;}
.ag-card .v {font-size: 1.7rem; font-weight: 800; color: #fff; font-variant-numeric: tabular-nums;}
.ag-card .s {font-size: .8rem; color: #c9d1e0; line-height: 1.35;}
.ag-sunrise {border-top: 3px solid #ffd25e;} .ag-sunset {border-top: 3px solid #ff7a3d;}
.ag-moonrise {border-top: 3px solid #a9dcff;} .ag-moonset {border-top: 3px solid #7aa7e0;}
.ag-light {font-size: .88rem; color: #dfe5ef; margin: 0 0 8px;}
.ag-light b {color: #ffcd9c;}
.ag-score {background: #111927; border: 1px solid #2a3550; border-radius: 12px; padding: 12px 14px; height: 100%;}
.ag-score .top {display: flex; align-items: baseline; gap: 12px;}
.ag-score .num {font-size: 2.6rem; font-weight: 800; line-height: 1;}
.ag-score .lab {font-size: 1.1rem; font-weight: 700;}
.ag-score .bar {height: 8px; background: #23304a; border-radius: 4px; margin: 8px 0;}
.ag-score .bar div {height: 8px; border-radius: 4px;}
.ag-score ul {margin: 4px 0 0 1.1rem; padding: 0; font-size: .9rem;}
.ag-score .when {font-size: .9rem; color: #ffcd9c; margin-top: 6px;}
table.ag-tab {border-collapse: collapse; width: 100%; font-size: .9rem;}
table.ag-tab th {text-align: left; color: #aab4c6; font-weight: 600; border-bottom: 1px solid #2a3550; padding: 5px 6px;}
table.ag-tab td {border-bottom: 1px solid #1c2638; padding: 5px 6px; vertical-align: middle;}
.ag-pill {display: inline-block; min-width: 2.3rem; text-align: center; border-radius: 10px; padding: 1px 7px;
          font-weight: 700; color: #0b111c;}
.ag-wrap {overflow-x: auto;}
</style>
""", unsafe_allow_html=True)

# Always dark, whatever the phone or computer is set to and even if .streamlit/config.toml is missing or wrong:
# page background, Streamlit's own text, and Streamlit's light-theme widgets (assets/light_mode.css).
_SCOPE = ':is([data-testid="stMain"], [data-testid="stDialog"], [data-testid="stPopoverBody"], [data-testid="stSidebar"])'
_TEXT = (':is(p, li, span, label, small, summary, b, strong, em, td, th, [data-testid="stMarkdownContainer"], '
         '[data-testid="stWidgetLabel"], [data-testid="stWidgetLabel"] *)')
# NB: no spaces between the :is(...) and :not(...) parts - a space would mean 'descendant of' and break the rule
_NOT = ''.join(':not(%s)' % x for x in (
    ':is(h1, h2, h3, h4, h5, h6) *', '[class^="ag-"]', '[class*=" ag-"]', '[class^="ag-"] *', '[class*=" ag-"] *',
    '.leaflet-container *', '[style*="color"]', '[style*="color"] *', 'a', 'a *', 'code', 'code *',
    '[data-testid="stBaseButton-primary"] *', '[data-testid="stCaptionContainer"] *'))
FORCE_TEXT_SELECTOR = 'body ' + _SCOPE + ' ' + _TEXT + _NOT
_FORCE_DARK = (
    '.stApp, [data-testid="stApp"], [data-testid="stAppViewContainer"], [data-testid="stMain"] '
    '{ background-color: #0b111c !important; }\n'
    '[data-testid="stHeader"] { background-color: rgba(11, 17, 28, 0.92) !important; }\n'
    '[data-testid="stSidebar"] > div:first-child { background-color: #111927 !important; }\n'
    + FORCE_TEXT_SELECTOR + ' { color: #f4efe8 !important; }\n'
    '[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] :is(p, span, li, b, strong, em) '
    '{ color: #dfe5ef !important; }\n'
    '[data-testid="stCaptionContainer"] a, [data-testid="stMarkdownContainer"] a { color: #6fd0dc !important; }\n'
    'h1, h2, h3, h4 { color: #ffcd9c !important; }\n')
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets', 'light_mode.css'), encoding='utf-8') as _f:
    st.markdown('<style>' + _FORCE_DARK + _f.read() + '</style>', unsafe_allow_html=True)


# ------------------------------------------------------------------------------------------
# cached data access
# ------------------------------------------------------------------------------------------
@st.cache_data(ttl=7 * 86400, max_entries=40, show_spinner=False)
def get_horizon(lat, lon, height, ground, max_km, near_m):
    return terrain.horizon(lat, lon, height_above_ground=height, ground_m=ground, max_km=max_km, near_m=near_m)


@st.cache_data(ttl=1800, max_entries=40, show_spinner=False)
def get_forecast(lat, lon, model):
    return wx.observer_forecast(lat, lon, model)


@st.cache_data(ttl=3600, max_entries=40, show_spinner=False)
def get_aerosol(lat, lon):
    return wx.aerosol(lat, lon)


@st.cache_data(ttl=900, max_entries=40, show_spinner=False)
def analyse(lat, lon, tz, day_iso, height, ground, max_km, near_m, model):
    msgs = []
    try:
        prof = get_horizon(lat, lon, height, ground, max_km, near_m)
        if prof['missing']:
            msgs.append(f"{prof['missing']} of {prof['tiles']} elevation tiles could not be downloaded; "
                        f"the skyline may be too low in places.")
    except Exception as e:
        prof = None
        msgs.append(f'Terrain could not be loaded ({e}). Times are for a flat horizon.')
    elev = prof['h_obs'] if prof else (ground or 0.0) + height
    ground_m = prof['ground_dem'] if prof else (ground or 0.0)
    try:
        fc = get_forecast(round(lat, 3), round(lon, 3), model)
    except wx.WeatherError as e:
        fc = None
        msgs.append(f'Weather forecast unavailable: {e}')
    try:
        aq = get_aerosol(round(lat, 2), round(lon, 2))
    except wx.WeatherError:
        aq = None
    day = date.fromisoformat(day_iso)
    days = pl.compute_days(lat, lon, tz, day, N_DAYS, prof, fc, elev=elev)
    days, err = pl.score_days(lat, lon, days, fc, aq, ground_m, model)
    if err:
        msgs.append(f'Cloud forecast along the Sun line unavailable: {err}')
    return dict(profile=prof, fc=fc, aq=aq, days=days, msgs=msgs, ground=ground_m, elev=elev)


@st.cache_data(ttl=6 * 3600, max_entries=20, show_spinner=False)
def jpl_check(lat, lon, tz, day_iso):
    day = date.fromisoformat(day_iso)
    res = astro.compute_day(lat, lon, 0.0, day, tz, None, astro.STD_T, astro.STD_P)
    return hc.compare(res['events'], lat, lon)


# ------------------------------------------------------------------------------------------
# location state
# ------------------------------------------------------------------------------------------
def set_location(lat, lon, src, name=None, acc=None, gps_alt=None):
    ss['loc'] = dict(lat=float(lat), lon=float(lon), src=src, name=name, acc=acc, gps_alt=gps_alt)
    # keep the 'Exact coordinates' boxes in step (allowed: this only runs inside callbacks)
    ss['in_lat'], ss['in_lon'] = round(float(lat), 5), round(float(lon), 5)


def default_location():
    tz = None
    try:
        tz = st.context.timezone
    except Exception:
        pass
    c = places.largest_in_tz(tz) if tz else None
    if c:
        return dict(lat=c['lat'], lon=c['lon'], src='start', name=c['name'], acc=None, gps_alt=None)
    return dict(lat=51.4779, lon=-0.0015, src='start', name='Greenwich, GB', acc=None, gps_alt=None)


def _on_pick(key='planner'):
    v = ss.get(key)
    p = v.get('pick') if hasattr(v, 'get') else None
    if not isinstance(p, dict) or 'lat' not in p:
        return
    try:
        lat, lon = float(p['lat']), float(p['lon'])
    except (TypeError, ValueError):
        return
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return
    acc = p.get('acc')
    set_location(lat, lon, 'gps' if p.get('src') == 'gps' else 'map', None,
                 float(acc) if isinstance(acc, (int, float)) else None,
                 p.get('alt') if isinstance(p.get('alt'), (int, float)) else None)


def _do_search():
    q = ss.get('q', '')
    ss['results'] = []
    ss.pop('search_error', None)
    if q and len(q.strip()) >= 2:
        try:
            ss['results'] = wx.search_places(q)
            if not ss['results']:
                ss['search_error'] = 'No place found with that name.'
        except wx.WeatherError as e:
            ss['search_error'] = f'Place search is unavailable: {e}'


def _choose():
    i = ss.get('match')
    res = ss.get('results') or []
    if i is not None and 0 <= i < len(res):
        r = res[i]
        set_location(r['lat'], r['lon'], 'search', r['label'])


def _use_coords():
    set_location(ss['in_lat'], ss['in_lon'], 'map', None)


def _today():
    ss['day'] = datetime.now(ZoneInfo(ss['tz'])).date()
    ss['day_auto'] = True


def _date_changed():
    ss['day_auto'] = False     # the user chose a date: stop following 'today' at the location


if 'loc' not in ss:
    ss['loc'] = default_location()
loc = ss['loc']
tz = places.tz_at(loc['lat'], loc['lon'])
ss['tz'] = tz
place_label = loc.get('name') or places.describe(loc['lat'], loc['lon'])
if 'day' not in ss or ss.get('day_auto', True):
    # until the user picks a date, show 'today' at the place shown (it changes when GPS moves the place)
    ss['day'] = datetime.now(ZoneInfo(tz)).date()
    ss['day_auto'] = True
if 'in_lat' not in ss:
    ss['in_lat'], ss['in_lon'] = round(loc['lat'], 5), round(loc['lon'], 5)

# ------------------------------------------------------------------------------------------
# header and inputs
# ------------------------------------------------------------------------------------------
st.markdown('<p class="ag-title">Afterglow</p>'
            '<p class="ag-sub">Sunrise, sunset, moonrise and moonset against your real skyline, '
            'with a forecast of how colourful the sky will be - and, after dark, the stars and the aurora.</p>',
            unsafe_allow_html=True)
PAGES = ['Sun & Moon', 'Night sky & aurora']
page = st.radio('Page', PAGES, horizontal=True, key='page', label_visibility='collapsed')

c1, c2, c3 = st.columns([2.2, 1.2, 0.6], vertical_alignment='bottom')
with c1:
    st.text_input('Search for a place', key='q', placeholder='Town, park or landmark - or tap "Use my location" below',
                  on_change=_do_search)
with c2:
    st.date_input('Date', key='day', min_value=date(1900, 1, 1), max_value=date(2100, 12, 31), format='YYYY-MM-DD',
                  on_change=_date_changed)
with c3:
    st.button('Today', on_click=_today, width='stretch')
if ss.get('search_error'):
    st.caption(ss['search_error'])
if ss.get('results'):
    st.selectbox('Matches', options=list(range(len(ss['results']))), index=None, key='match',
                 format_func=lambda i: ss['results'][i]['label'], placeholder='Choose the right place',
                 on_change=_choose)

with st.expander('Settings: height, terrain distance, weather model, exact coordinates'):
    s1, s2 = st.columns(2)
    with s1:
        height = st.number_input('Your eye or camera height above the ground (m)', 0.0, 2000.0, 1.7, 0.5,
                                 key='height', help='Add the height of a tower, building or drone here.')
        own_ground = st.checkbox('Set the ground elevation myself', key='own_ground')
        ground = None
        if own_ground:
            ground = st.number_input('Ground elevation above sea level (m)', -450.0, 8850.0,
                                     float(round(ss.get('last_ground', 0.0))), 1.0, key='ground')
        if loc.get('gps_alt') is not None:
            st.caption(f"Your device reported an altitude of {loc['gps_alt']:.0f} m. Phones give height above "
                       "the GPS ellipsoid, which can differ from sea-level height by tens of metres, so the "
                       "elevation model is used unless you set the ground yourself.")
    with s2:
        max_km = st.slider('Look for mountains up to (km away)', 20, 250, 150, 10, key='max_km')
        near_m = st.slider('Ignore terrain closer than (m)', 30, 1000, 200, 10, key='near_m',
                           help='The elevation model is coarse near you; a few metres of error close by '
                                'would look like a wall. Lower this if you stand right below a cliff.')
        model_name = st.selectbox('Weather model', list(wx.MODELS), key='model')
    st.markdown('**Exact coordinates**')
    k1, k2, k3 = st.columns([1, 1, 1], vertical_alignment='bottom')
    k1.number_input('Latitude', -89.9, 89.9, step=0.0001, format='%.5f', key='in_lat')
    k2.number_input('Longitude', -180.0, 180.0, step=0.0001, format='%.5f', key='in_lon')
    k3.button('Use these coordinates', on_click=_use_coords, width='stretch')

day = ss['day']
model = wx.MODELS[ss.get('model') or list(wx.MODELS)[0]]
height = float(ss.get('height', 1.7))
ground = float(ss['ground']) if ss.get('own_ground') and ss.get('ground') is not None else None

if page == PAGES[1]:
    st.subheader(f'Night of {day:%a %d %b %Y}: stars and aurora')
    night_page.render(loc, tz, day, place_label, model,
                      (ground if ground is not None else float(ss.get('last_ground', 0.0))) + height,
                      functools.partial(_on_pick, 'nightmap'))
    st.stop()

with st.spinner('Reading the terrain, the sky and the forecast...'):
    A = analyse(round(loc['lat'], 6), round(loc['lon'], 6), tz, day.isoformat(), height, ground,
                float(ss.get('max_km', 150)), float(ss.get('near_m', 200)), model)
for m in A['msgs']:
    st.warning(m)
ss['last_ground'] = A['ground']
D0 = A['days'][0]
res = D0['res']
ev = res['events']
z = ZoneInfo(tz)


def hm(e):
    return e['utc'].astimezone(z).strftime('%H:%M') if e else '--:--'


def flat_of(body, kind):
    hits = [e for e in ev if e['key'] == f'{body}{kind}_flat']
    return (hits[0] if kind == 'rise' else hits[-1]) if hits else None


# ------------------------------------------------------------------------------------------
# key times
# ------------------------------------------------------------------------------------------
cards = []
for body, kind, title in (('sun', 'rise', 'Sunrise'), ('sun', 'set', 'Sunset'),
                          ('moon', 'rise', 'Moonrise'), ('moon', 'set', 'Moonset')):
    e = pl.main_event(ev, body, kind)
    f = flat_of(body, kind)
    if e is None:
        sub = 'not on this date'
    else:
        terrain_ev = not e['flat']
        sub = f"{e['az']:.0f}° {charts.compass(e['az'])}"
        if terrain_ev and f:
            sub += f" · flat horizon {hm(f)}"
        elif terrain_ev:
            sub += ' · over terrain'
        if body == 'moon':
            sub += f" · {e.get('illum', res['info']['moon_illum']) * 100:.0f}% lit"
        vis = D0.get(f'moon{kind}', {}).get('visibility') if body == 'moon' else None
        if vis is not None and math.isfinite(vis):
            sub += f" · {vis * 100:.0f}% chance of a clear view"
    cards.append(f'<div class="ag-card ag-{body}{kind}"><div class="k">{title}</div>'
                 f'<div class="v">{hm(e)}</div><div class="s">{html.escape(sub)}</div></div>')
st.markdown('<div class="ag-cards">' + ''.join(cards) + '</div>', unsafe_allow_html=True)


def span(k1, k2):
    a = [e for e in ev if e['key'] == k1]
    b = [e for e in ev if e['key'] == k2]
    return f'{hm(a[0])}-{hm(b[0])}' if a and b else None


bits = []
for name, k1, k2 in (('Blue hour', 'dawn_civil', 'sun_m4_up'), ('Golden hour', 'sun_m4_up', 'sun_p6_up'),
                     ('Golden hour', 'sun_p6_down', 'sun_m4_down'), ('Blue hour', 'sun_m4_down', 'dusk_civil')):
    s = span(k1, k2)
    if s:
        bits.append(f'<b>{name}</b> {s}')
bits.append(f"<b>Moon</b> {res['info']['moon_phase_name'].lower()}, {res['info']['moon_illum'] * 100:.0f}% lit")
st.markdown('<p class="ag-light">' + ' &nbsp;·&nbsp; '.join(bits) + f' &nbsp;·&nbsp; times in {tz}</p>',
            unsafe_allow_html=True)

# ------------------------------------------------------------------------------------------
# the planner
# ------------------------------------------------------------------------------------------
data = pc.build_data(loc, tz, day, res, A['profile'], place_label)
pc.show(data, on_pick=_on_pick)
prof = A['profile']
if prof:
    st.caption(f"You: ground {prof['ground_dem']:.0f} m above sea level, eye level {prof['h_obs']:.0f} m. "
               f"Skyline from open elevation data out to {prof['max_km']:.0f} km. Tap the map and choose "
               f"'Plan from here' to move. Trees and buildings are not in the model.")


# ------------------------------------------------------------------------------------------
# colour forecast
# ------------------------------------------------------------------------------------------
def afterglow_text(kind, e, a):
    if not a:
        return ''
    h = a['canvas_km']
    dep = sc.depression_lit_deg(h)
    t = astro.sun_time_at_depression(loc['lat'], loc['lon'], A['elev'], e['utc'], dep, setting=(kind == 'sunset'))
    if not t:
        return ''
    when = t.astimezone(z).strftime('%H:%M')
    if kind == 'sunset':
        return (f"Best colour: from about 10 min before sunset to {when}, when clouds at "
                f"~{h:.1f} km ({a['canvas_km_source']}) fall into the Earth's shadow.")
    return (f"Best colour: clouds at ~{h:.1f} km ({a['canvas_km_source']}) catch the first light at about "
            f"{when}, until a few minutes after sunrise.")


def score_card(kind, entry):
    e, a = entry['event'], entry['assessment']
    title = 'Sunrise' if kind == 'sunrise' else 'Sunset'
    if e is None:
        return f'<div class="ag-score"><b>{title}</b><br>The Sun does not {kind[3:]} on this date.</div>'
    if a is None:
        return (f'<div class="ag-score"><b>{title} {hm(e)}</b><br>No cloud forecast for this date '
                f'(forecasts reach about {N_DAYS} days ahead).</div>')
    reasons = ''.join(f'<li>{html.escape(r)}</li>' for r in a['reasons'])
    return (f'<div class="ag-score"><div class="top"><span class="num" style="color:{a["colour"]}">{a["score"]}</span>'
            f'<span><span class="lab" style="color:{a["colour"]}">{a["label"]}</span><br>'
            f'{title} {hm(e)} · colour potential out of 100</span></div>'
            f'<div class="bar"><div style="width:{a["score"]}%;background:{a["colour"]}"></div></div>'
            f'<ul>{reasons}</ul><div class="when">{html.escape(afterglow_text(kind, e, a))}</div></div>')


st.subheader('Sky colour forecast')
f1, f2 = st.columns(2)
f1.markdown(score_card('sunrise', D0['sunrise']), unsafe_allow_html=True)
f2.markdown(score_card('sunset', D0['sunset']), unsafe_allow_html=True)

# ------------------------------------------------------------------------------------------
# details
# ------------------------------------------------------------------------------------------
t_out, t_cloud, t_windy, t_times, t_about = st.tabs(
    ['7-day outlook', 'Clouds toward the Sun', 'Weather layers (Windy)', 'All times & JPL check', 'About'])

with t_out:
    rows = []
    for d in A['days']:
        cells = [f"<td>{d['day']:%a %d %b}</td>"]
        for kind in ('sunrise', 'sunset'):
            e, a = d[kind]['event'], d[kind]['assessment']
            if e is None:
                cells.append('<td>-</td><td></td>')
                continue
            pill = (f'<span class="ag-pill" style="background:{a["colour"]}">{a["score"]}</span> {a["label"]}'
                    if a else '<span style="color:#a7b0bf">no forecast</span>')
            cells.append(f"<td>{hm(e)} <span style='color:#aab4c6'>({e['az']:.0f}°)</span></td><td>{pill}</td>")
        rows.append('<tr>' + ''.join(cells) + '</tr>')
    st.markdown('<div class="ag-wrap"><table class="ag-tab"><tr><th>Date</th><th>Sunrise</th><th>Colour</th>'
                '<th>Sunset</th><th>Colour</th></tr>' + ''.join(rows) + '</table></div>', unsafe_allow_html=True)
    st.caption('Colour potential: 0-20 poor, 20-40 fair, 40-60 good, 60-80 great, 80+ spectacular potential. '
               'A clear sky scores about 30: a clean glow with little cloud to light up. Forecast clouds become '
               'less reliable after 2-3 days.')

with t_cloud:
    choice = st.radio('Event', ['Sunset', 'Sunrise'], horizontal=True, key='cloud_event')
    entry = D0[choice.lower()]
    e, a = entry['event'], entry['assessment']
    if e is None or a is None:
        st.info('No cloud forecast for this event.')
    else:
        g1, g2 = st.columns([2, 1])
        with g1:
            fig = charts.cloud_section(a, choice.lower(), hm(e), e['az'], a['canvas_km'])
            st.pyplot(fig, width='stretch')
            plt.close(fig)
        with g2:
            tt = e['utc'].timestamp()
            lcl = wx.lcl_height_m(wx.at(A['fc'], 'temperature_2m', tt), wx.at(A['fc'], 'dew_point_2m', tt))
            fig = charts.cloud_layers(a['profile'], lcl, hm(e))
            st.pyplot(fig, width='stretch')
            plt.close(fig)
        st.caption('Left: forecast low, mid and high cloud at points along the direction of the Sun. The orange '
                   'curve is the path of the last (or first) sunlight that can reach a cloud above you; '
                   'low cloud where it skims the ground cuts the light off. Right: cloud cover on each '
                   'pressure level of the weather model above your position.')

WINDY_LAYERS = {
    'Clouds (total)': 'clouds', 'Low clouds': 'lclouds', 'Medium clouds': 'mclouds', 'High clouds': 'hclouds',
    'Cloud base': 'cbase', 'Cloud tops': 'cloudtop', 'Fog': 'fog', 'Visibility': 'visibility',
    'Rain and thunder': 'rain', 'Satellite': 'satellite', 'Radar': 'radar', 'Wind': 'wind',
    'Humidity': 'rh', 'Aerosol (AOD)': 'aod550',
}
with t_windy:
    w1, w2, w3 = st.columns([1.4, 1, 1])
    layer = WINDY_LAYERS[w1.selectbox('Layer', list(WINDY_LAYERS), key='windy_layer')]
    product = w2.selectbox('Model', ['ecmwf', 'gfs', 'icon', 'iconEu'], key='windy_model')
    zoom = w3.slider('Zoom', 3, 11, 7, key='windy_zoom')
    lat_s, lon_s = f"{loc['lat']:.3f}", f"{loc['lon']:.3f}"
    url = ('https://embed.windy.com/embed2.html?'
           f'lat={lat_s}&lon={lon_s}&detailLat={lat_s}&detailLon={lon_s}&zoom={zoom}&level=surface'
           f'&overlay={layer}&product={product}&menu=&message=true&marker=true&calendar=now&pressure=true'
           f'&type=map&location=coordinates&detail=&metricWind=default&metricTemp=default&radarRange=-1')
    st.iframe(url, height=540)
    st.caption(f"Weather map by [Windy.com](https://www.windy.com/?{layer},{lat_s},{lon_s},{zoom}). Use the "
               "timeline at the bottom of the map to move to the time of sunset. Some layers need a Windy "
               "account and are not shown in the embedded map.")

PRETTY = {
    'dawn_astronomical': 'Astronomical dawn (Sun -18°)', 'dawn_nautical': 'Nautical dawn (Sun -12°)',
    'dawn_civil': 'Civil dawn, blue hour begins (Sun -6°)', 'sun_m4_up': 'Golden hour begins (Sun -4°)',
    'sunrise_flat': 'Sunrise, flat horizon (almanac)', 'sunrise': 'Sun appears over the terrain',
    'sun_p6_up': 'Golden hour ends (Sun +6°)', 'sun_transit': 'Solar noon (Sun highest)',
    'sun_p6_down': 'Golden hour begins (Sun +6°)', 'sunset': 'Sun disappears behind the terrain',
    'sunset_flat': 'Sunset, flat horizon (almanac)', 'sun_m4_down': 'Golden hour ends, blue hour begins (Sun -4°)',
    'dusk_civil': 'Civil dusk, blue hour ends (Sun -6°)', 'dusk_nautical': 'Nautical dusk (Sun -12°)',
    'dusk_astronomical': 'Astronomical dusk (Sun -18°)', 'moonrise_flat': 'Moonrise, flat horizon (almanac)',
    'moonrise': 'Moon appears over the terrain', 'moonset': 'Moon disappears behind the terrain',
    'moonset_flat': 'Moonset, flat horizon (almanac)', 'moon_transit': 'Moon highest',
}
with t_times:
    trs = ''.join(f"<tr><td>{hm(e)}</td><td>{PRETTY.get(e['key'], e['key'])}</td><td>{e['az']:.1f}° "
                  f"{charts.compass(e['az'])}</td><td>{e['alt']:.2f}°</td></tr>" for e in ev)
    st.markdown('<div class="ag-wrap"><table class="ag-tab"><tr><th>Time</th><th>Event</th><th>Azimuth</th>'
                '<th>Altitude</th></tr>' + trs + '</table></div>', unsafe_allow_html=True)
    st.caption(f"Times in {tz}. Positions from NASA JPL DE440s. Altitudes include atmospheric refraction "
               f"for {res['info']['temp_c']:.0f} °C and {res['info']['pres_hpa']:.0f} hPa (forecast for this day "
               f"if available). Rise and set refer to the top edge of the disc.")
    st.markdown('**Independent check with NASA JPL Horizons**')
    st.caption('Asks the JPL Horizons service for the flat-horizon rise and set times at this place and date '
               '(sea-level site, standard refraction) and compares them with this app.')
    if st.button('Run the JPL Horizons check', key='jpl_btn'):
        with st.spinner('Asking JPL Horizons...'):
            out = jpl_check(round(loc['lat'], 5), round(loc['lon'], 5), tz, day.isoformat())
        rows = []
        for c in out:
            if c['jpl'] is None:
                rows.append(f"<tr><td>{c['event']}</td><td colspan=4>{html.escape(str(c['error']))}</td></tr>")
                continue
            rows.append(f"<tr><td>{c['event']}</td><td>{c['app'].astimezone(z):%H:%M:%S}</td>"
                        f"<td>{c['jpl'].astimezone(z):%H:%M:%S}</td><td>{c['diff_s']:+.1f} s</td>"
                        f"<td>{(c['app_az'] - c['jpl_az']) * 3600:+.0f}\"</td></tr>")
        st.markdown('<div class="ag-wrap"><table class="ag-tab"><tr><th>Event</th><th>This app</th>'
                    '<th>JPL Horizons</th><th>Time difference</th><th>Azimuth difference</th></tr>'
                    + ''.join(rows) + '</table></div>', unsafe_allow_html=True)

with t_about:
    st.markdown("""
**How Afterglow works**

1. **Where you are.** "Use my location" asks your phone or computer for its GPS position (nothing is stored).
   You can also search for a place, tap the map, or type coordinates.
2. **Your skyline.** The ground around you is read from open elevation data (AWS Terrain Tiles: SRTM, USGS 3DEP,
   GMTED2010 and others) out to 150 km. Earth's curvature and normal atmospheric bending of light are included,
   so a mountain range 60 km away or a sea horizon below you is placed correctly.
3. **Sun and Moon.** Positions come from NASA JPL's DE440s ephemeris, the same planetary model used by JPL
   Horizons, reduced to your exact spot with IAU standards (Skyfield). Rise and set are given both for a flat
   horizon (as in almanacs) and for your real skyline. A button compares the app with JPL Horizons itself.
4. **Clouds.** Forecast clouds come from Open-Meteo (ECMWF, NOAA GFS, DWD ICON and other national models):
   low, mid and high cloud over you and at points 30-350 km toward the Sun, cloud cover on 14 height levels,
   visibility and rain, plus CAMS aerosol forecasts. Live satellite cloud pictures (NASA GIBS) and Windy maps
   are in the map layers and the Windy tab.
5. **Colour potential.** Vivid skies need cloud to light up (best: broken mid or high cloud above you) and a
   clear path for the low sunlight (no thick low cloud 150-350 km toward the Sun, where that light skims the
   ground). The score combines these with rain, haze and smoke. It is a transparent rule of thumb, not a
   guarantee; the reasons under each score show what drives it.

**Limits.** Rise and set times can vary by about a minute from day to day with the air's temperature layers.
The elevation model does not contain trees or buildings, and may miss small rocks right next to you. Cloud
forecasts become uncertain after 2-3 days.
""")
    st.markdown("""
**Sources and credits**
- NASA JPL DE440s ephemeris (Park et al. 2021) and JPL Horizons API; Skyfield by Brandon Rhodes.
- Terrain Tiles, AWS Registry of Open Data (Mapzen/Tilezen): SRTM, USGS 3DEP/NED, GMTED2010, ETOPO1 and
  national models; see registry.opendata.aws/terrain-tiles.
- Weather data by Open-Meteo.com (CC BY 4.0), from ECMWF, NOAA, DWD, Météo-France, ECCC, JMA; aerosols from
  the Copernicus Atmosphere Monitoring Service (CAMS).
- Satellite images: NASA GIBS / EOSDIS, with NOAA GOES and JMA Himawari data.
- Maps: OpenStreetMap contributors, OpenTopoMap (CC BY-SA), Esri World Imagery; weather maps by Windy.com.
- Map library: Leaflet 1.9.4 (BSD-2-Clause); place names: GeoNames (CC BY 4.0).
""")
