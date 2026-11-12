// Afterglow planner - map, time slider and horizon panorama.
// Runs inside a Streamlit "components v2" element.  Leaflet (window.L) is bundled in front
// of this file by planner_component.py.  Everything here is drawn from the data that Python
// sends; the only messages sent back are a new location ('pick').

const DEG = Math.PI / 180;
const R_EARTH = 6371008.8;
const DIRS = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'];
const COL = { sunrise: '#ffd25e', sunset: '#ff7a3d', moonrise: '#a9dcff', moonset: '#7aa7e0',
              sun: '#ffe680', moon: '#dcefff', ridge: '#ff9f6b', me: '#ff4f7b' };

function compass(az) { return DIRS[Math.round((((az % 360) + 360) % 360) / 22.5) % 16]; }

function dest(lat, lon, az, m) {
  const p1 = lat * DEG, l1 = lon * DEG, th = az * DEG, d = m / R_EARTH;
  const p2 = Math.asin(Math.sin(p1) * Math.cos(d) + Math.cos(p1) * Math.sin(d) * Math.cos(th));
  const l2 = l1 + Math.atan2(Math.sin(th) * Math.sin(d) * Math.cos(p1), Math.cos(d) - Math.sin(p1) * Math.sin(p2));
  return [p2 / DEG, l2 / DEG];
}

function fmtTime(ms, tz) {
  try {
    return new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: tz })
      .format(new Date(ms));
  } catch (e) {
    return new Date(ms).toISOString().slice(11, 16) + ' UTC';
  }
}

function hzAt(d, az) {
  const n = d.hz.length;
  const x = ((((az % 360) + 360) % 360) / d.hz_step);
  const i = Math.floor(x) % n, j = (i + 1) % n, f = x - Math.floor(x);
  return d.hz[i] * (1 - f) + d.hz[j] * f;
}

function el(tag, cls, html) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html !== undefined) e.innerHTML = html;
  return e;
}

// ------------------------------------------------------------------------------------------
function build(parent) {
  const S = {};
  const root = el('div', 'ag-root');
  root.innerHTML = `
    <div class="ag-bar">
      <button type="button" class="ag-btn ag-gps">Use my location</button>
      <span class="ag-status"></span>
    </div>
    <div class="ag-map"></div>
    <div class="ag-timebar">
      <button type="button" class="ag-btn ag-play" title="Play the day">Play</button>
      <input type="range" class="ag-slider" min="0" max="1440" step="1" value="0" aria-label="Time of day">
      <span class="ag-clock">--:--</span>
    </div>
    <div class="ag-jumps"></div>
    <div class="ag-readout"></div>
    <div class="ag-panohead">
      <span class="ag-panotitle">Horizon view</span>
      <label><input type="radio" name="ag-focus" value="sun" checked> follow Sun</label>
      <label><input type="radio" name="ag-focus" value="moon"> follow Moon</label>
      <label><input type="radio" name="ag-focus" value="all"> all 360°</label>
    </div>
    <canvas class="ag-pano"></canvas>
    <div class="ag-legend">
      <span style="color:${COL.sunrise}">&#9644; sunrise direction</span>
      <span style="color:${COL.sunset}">&#9644; sunset direction</span>
      <span style="color:${COL.moonrise}">&#9476; moonrise</span>
      <span style="color:${COL.moonset}">&#9476; moonset</span>
      <span style="color:${COL.sun}">&#9644; Sun now</span>
      <span style="color:${COL.moon}">&#9644; Moon now</span>
      <span style="color:${COL.ridge}">&#9644; skyline ridge you see</span>
    </div>`;
  parent.appendChild(root);
  S.root = root;
  S.status = root.querySelector('.ag-status');
  S.slider = root.querySelector('.ag-slider');
  S.clock = root.querySelector('.ag-clock');
  S.jumps = root.querySelector('.ag-jumps');
  S.readout = root.querySelector('.ag-readout');
  S.canvas = root.querySelector('.ag-pano');
  S.focus = 'sun';
  S.playing = null;

  // ---- map
  const mapDiv = root.querySelector('.ag-map');
  const map = L.map(mapDiv, { zoomControl: true, preferCanvas: false, worldCopyJump: true });
  S.map = map;
  const base = {
    'Topographic': L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png', {
      maxZoom: 17, subdomains: 'abc',
      attribution: 'Map &copy; OpenStreetMap contributors, SRTM | Style &copy; OpenTopoMap (CC-BY-SA)' }),
    'Streets': L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19, attribution: '&copy; OpenStreetMap contributors' }),
    'Satellite photo': L.tileLayer(
      'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
      maxZoom: 19, attribution: 'Imagery &copy; Esri, Maxar, Earthstar Geographics' }),
  };
  base['Topographic'].addTo(map);
  const gibs = (layer, time, tms, ext, maxN) => L.tileLayer(
    `https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/${layer}/default/${time}/${tms}/{z}/{y}/{x}.${ext}`,
    { maxNativeZoom: maxN, maxZoom: 19, opacity: 0.8,
      attribution: 'Satellite: NASA GIBS / EOSDIS, NOAA, JMA' });
  S.ridge = L.layerGroup().addTo(map);
  S.gibsLayers = {
    goesE: gibs('GOES-East_ABI_GeoColor', 'default', 'GoogleMapsCompatible_Level7', 'png', 7),
    goesW: gibs('GOES-West_ABI_GeoColor', 'default', 'GoogleMapsCompatible_Level7', 'png', 7),
    hima: gibs('Himawari_AHI_Band3_Red_Visible_1km', 'default', 'GoogleMapsCompatible_Level7', 'png', 7),
  };
  const overlays = {
    'Skyline ridge you see': S.ridge,
    'Live clouds - Americas (GOES-East, ~10 min old)': S.gibsLayers.goesE,
    'Live clouds - Pacific (GOES-West)': S.gibsLayers.goesW,
    'Live clouds - Asia & Australia (Himawari)': S.gibsLayers.hima,
  };
  S.layerCtl = L.control.layers(base, overlays, { collapsed: true, position: 'topright' }).addTo(map);
  L.control.scale({ imperial: true, metric: true }).addTo(map);
  S.fixed = L.layerGroup().addTo(map);     // rise/set lines
  S.live = L.layerGroup().addTo(map);      // current Sun/Moon lines
  S.me = L.layerGroup().addTo(map);        // observer

  map.on('zoomend', () => { if (S.d) { drawFixed(S); drawLive(S); } });
  map.on('click', (ev) => {
    const lat = ev.latlng.lat, lon = ((ev.latlng.lng + 540) % 360) - 180;
    const box = el('div', 'ag-pop');
    box.innerHTML = `<div>${lat.toFixed(5)}, ${lon.toFixed(5)}</div>`;
    const b = el('button', 'ag-btn ag-btn-primary', 'Plan from here');
    b.type = 'button';
    b.addEventListener('click', () => {
      S.status.textContent = 'Loading the new place...';
      S.send('pick', { lat, lon, src: 'map', ts: Date.now() });
      map.closePopup();
    });
    box.appendChild(b);
    L.popup().setLatLng(ev.latlng).setContent(box).openOn(map);
  });

  // ---- controls
  root.querySelector('.ag-gps').addEventListener('click', () => {
    if (!('geolocation' in navigator)) {
      S.status.textContent = 'This browser cannot share its location.';
      return;
    }
    S.status.textContent = 'Asking your device for its position...';
    navigator.geolocation.getCurrentPosition((p) => {
      const c = p.coords;
      S.status.textContent = `Found you (within ${Math.round(c.accuracy)} m). Loading...`;
      S.send('pick', { lat: c.latitude, lon: c.longitude, acc: c.accuracy, alt: c.altitude,
                       alt_acc: c.altitudeAccuracy, src: 'gps', ts: Date.now() });
    }, (err) => {
      const why = err.code === 1 ? 'Permission was refused. Allow location for this site in the browser settings.'
        : err.code === 3 ? 'The device took too long. Try again outdoors.' : 'The position is not available.';
      S.status.textContent = why;
    }, { enableHighAccuracy: true, timeout: 25000, maximumAge: 0 });
  });
  S.slider.addEventListener('input', () => { stopPlay(S); render(S); });
  root.querySelector('.ag-play').addEventListener('click', () => {
    if (S.playing) { stopPlay(S); return; }
    const btn = root.querySelector('.ag-play');
    btn.textContent = 'Pause';
    if (+S.slider.value >= +S.slider.max) S.slider.value = 0;
    S.playing = setInterval(() => {
      const v = +S.slider.value + 2;
      if (v > +S.slider.max) { stopPlay(S); return; }
      S.slider.value = v;
      render(S);
    }, 60);
  });
  root.querySelectorAll('input[name="ag-focus"]').forEach((r) => r.addEventListener('change', () => {
    S.focus = r.value;
    drawPano(S, +S.slider.value);
  }));
  if (window.ResizeObserver) {
    S.ro = new ResizeObserver(() => { map.invalidateSize(); if (S.d) drawPano(S, +S.slider.value); });
    S.ro.observe(root);
  }
  return S;
}

function stopPlay(S) {
  if (S.playing) { clearInterval(S.playing); S.playing = null; }
  const b = S.root.querySelector('.ag-play');
  if (b) b.textContent = 'Play';
}

function lineLen(S) {
  // reach from the observer to near the edge of the visible map, so the labels stay on screen
  const b = S.map.getBounds(), c = b.getCenter();
  const halfH = S.map.distance(c, L.latLng(b.getNorth(), c.lng));
  const halfW = S.map.distance(c, L.latLng(c.lat, b.getEast()));
  return Math.max(300, Math.min(halfH, halfW) * 0.92);
}

function drawFixed(S) {
  const d = S.d;
  S.fixed.clearLayers();
  const len = lineLen(S);
  for (const ln of d.lines) {
    const end = dest(d.lat, d.lon, ln.az, len);
    const col = COL[ln.kind] || '#fff';
    const moon = ln.kind.startsWith('moon');
    L.polyline([[d.lat, d.lon], end], { color: col, weight: 3, opacity: 0.95,
      dashArray: moon ? '8 7' : null, interactive: false }).addTo(S.fixed);
    const lbl = L.divIcon({ className: 'ag-maplabel', html: `<span style="border-color:${col}">${ln.label}</span>`,
                            iconSize: null });
    L.marker(dest(d.lat, d.lon, ln.az, len * 0.7), { icon: lbl, interactive: false }).addTo(S.fixed);
  }
}

function drawLive(S) {
  const d = S.d, i = +S.slider.value;
  S.live.clearLayers();
  const len = lineLen(S) * 0.75;
  for (const b of ['sun', 'moon']) {
    const az = d[b + '_az'][i], alt = d[b + '_alt'][i];
    const up = alt + d[b + '_sd'] > hzAt(d, az);
    if (!up && alt < -18) continue;
    L.polyline([[d.lat, d.lon], dest(d.lat, d.lon, az, len)], {
      color: COL[b], weight: b === 'sun' ? 6 : 5, opacity: up ? 0.95 : 0.45,
      dashArray: up ? null : '4 9', interactive: false }).addTo(S.live);
  }
}

function drawRidge(S) {
  const d = S.d;
  S.ridge.clearLayers();
  if (!d.ridge || !d.ridge.length) return;
  let seg = [];
  const flush = () => { if (seg.length > 1) L.polyline(seg, { color: COL.ridge, weight: 2, opacity: 0.85,
                        interactive: false }).addTo(S.ridge); seg = []; };
  for (let k = 0; k <= d.ridge.length; k++) {
    const p = d.ridge[k % d.ridge.length];
    const prev = d.ridge[(k - 1 + d.ridge.length) % d.ridge.length];
    if (k > 0 && Math.abs(p[2] - prev[2]) > 0.25 * Math.max(p[2], prev[2]) + 0.3) flush();
    seg.push([p[0], p[1]]);
  }
  flush();
}

function drawMe(S) {
  const d = S.d;
  S.me.clearLayers();
  if (d.acc && d.acc > 0) L.circle([d.lat, d.lon], { radius: d.acc, color: COL.me, weight: 1, fillOpacity: 0.08,
                                                     interactive: false }).addTo(S.me);
  L.circleMarker([d.lat, d.lon], { radius: 7, color: '#fff', weight: 2, fillColor: COL.me, fillOpacity: 1 })
    .bindTooltip(d.place || 'You', { direction: 'top' }).addTo(S.me);
}

function render(S) {
  const d = S.d, i = +S.slider.value;
  const ms = d.t0 + i * d.step * 1000;
  S.clock.textContent = fmtTime(ms, d.tz);
  const parts = [];
  for (const b of ['sun', 'moon']) {
    const az = d[b + '_az'][i], alt = d[b + '_alt'][i], h = hzAt(d, az);
    const top = alt + d[b + '_sd'];
    let where;
    if (top > h) where = `${(alt - h).toFixed(1)}° above the skyline`;
    else if (top > 0 && h > 0) where = 'hidden behind terrain';
    else where = 'below the horizon';
    const name = b === 'sun' ? 'Sun' : 'Moon';
    const extra = b === 'moon' ? ` · ${Math.round(d.moon_illum * 100)}% lit` : '';
    parts.push(`<span class="ag-ro ag-ro-${b}"><b>${name}</b> ${az.toFixed(1)}° ${compass(az)} · ` +
               `altitude ${alt.toFixed(1)}° · ${where}${extra}</span>`);
  }
  S.readout.innerHTML = parts.join('');
  drawLive(S);
  drawPano(S, i);
}

// ------------------------------------------------------------------------------------------
function skyColours(sunAlt) {
  if (sunAlt > 10) return ['#2f5f9e', '#8fb8e2'];
  if (sunAlt > 6) return ['#2d5690', '#d9b98a'];
  if (sunAlt > -4) return ['#2a3f6e', '#f08a4b'];
  if (sunAlt > -6) return ['#14244d', '#3d5ea8'];
  if (sunAlt > -12) return ['#0b1430', '#1d2c57'];
  return ['#05080f', '#0c1324'];
}

function drawPano(S, i) {
  const d = S.d, c = S.canvas;
  const W = Math.max(280, c.clientWidth || S.root.clientWidth || 600);
  const H = W < 520 ? 190 : 240;
  const dpr = window.devicePixelRatio || 1;
  c.style.height = H + 'px';
  c.width = Math.round(W * dpr);
  c.height = Math.round(H * dpr);
  const g = c.getContext('2d');
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  const all = S.focus === 'all';
  const span = all ? 360 : (W < 520 ? 110 : 150);
  const center = all ? 180 : d[S.focus + '_az'][i];
  let hmin = 90, hmax = -90;
  for (let a = center - span / 2; a <= center + span / 2; a += d.hz_step) {
    const h = hzAt(d, a); hmin = Math.min(hmin, h); hmax = Math.max(hmax, h);
  }
  const yMin = Math.min(-2, Math.floor(hmin - 1));
  const yMax = Math.max(14, Math.ceil(hmax + 8));
  const bottom = 18;
  const X = (a) => W / 2 + ((((a - center) % 360) + 540) % 360 - 180) / span * W;
  const Y = (alt) => H - bottom - (alt - yMin) / (yMax - yMin) * (H - bottom - 6);

  const [top, low] = skyColours(d.sun_alt[i]);
  const grd = g.createLinearGradient(0, 0, 0, H - bottom);
  grd.addColorStop(0, top); grd.addColorStop(1, low);
  g.fillStyle = grd; g.fillRect(0, 0, W, H);

  // grid
  g.font = '11px system-ui, sans-serif';
  g.strokeStyle = 'rgba(255,255,255,0.15)'; g.fillStyle = 'rgba(255,255,255,0.7)'; g.lineWidth = 1;
  const stepAlt = (yMax - yMin) > 30 ? 10 : 5;
  for (let a = Math.ceil(yMin / stepAlt) * stepAlt; a <= yMax; a += stepAlt) {
    g.beginPath(); g.moveTo(0, Y(a)); g.lineTo(W, Y(a)); g.stroke();
    g.fillText(`${a}°`, 3, Y(a) - 2);
  }
  // flat horizon
  g.setLineDash([5, 5]); g.strokeStyle = 'rgba(255,255,255,0.45)';
  g.beginPath(); g.moveTo(0, Y(0)); g.lineTo(W, Y(0)); g.stroke(); g.setLineDash([]);

  // terrain silhouette
  g.beginPath(); g.moveTo(0, H);
  for (let px = 0; px <= W; px += 1) {
    const a = center + (px - W / 2) / W * span;
    g.lineTo(px, Y(hzAt(d, a)));
  }
  g.lineTo(W, H); g.closePath();
  g.fillStyle = '#121822'; g.fill();
  g.strokeStyle = COL.ridge; g.lineWidth = 1.5;
  g.beginPath();
  for (let px = 0; px <= W; px += 1) {
    const a = center + (px - W / 2) / W * span, y = Y(hzAt(d, a));
    if (px === 0) g.moveTo(px, y); else g.lineTo(px, y);
  }
  g.stroke();

  // azimuth ticks
  g.fillStyle = 'rgba(255,255,255,0.85)';
  const tick = span > 200 ? 45 : (span > 120 ? 15 : 10);
  for (let a = Math.ceil((center - span / 2) / tick) * tick; a <= center + span / 2; a += tick) {
    const x = X(a), aa = ((a % 360) + 360) % 360;
    const lab = aa % 45 === 0 ? `${compass(aa)} ${aa}°` : `${aa}°`;
    g.fillText(lab, x - g.measureText(lab).width / 2, H - 4);
  }

  // paths
  for (const b of ['moon', 'sun']) {
    const az = d[b + '_az'], alt = d[b + '_alt'];
    g.strokeStyle = b === 'sun' ? 'rgba(255,230,128,0.85)' : 'rgba(220,239,255,0.75)';
    g.lineWidth = 1.5;
    g.setLineDash(b === 'moon' ? [4, 4] : []);
    g.beginPath();
    let px = null;
    for (let k = 0; k < d.n; k += 2) {
      if (alt[k] < yMin - 3) { px = null; continue; }
      const x = X(az[k]), y = Y(alt[k]);
      if (px === null || Math.abs(x - px) > W / 2 || x < -50 || x > W + 50) g.moveTo(x, y); else g.lineTo(x, y);
      px = x;
    }
    g.stroke(); g.setLineDash([]);
    // hour marks
    g.fillStyle = g.strokeStyle;
    for (const k of S.hourIdx) {
      if (alt[k] < yMin || alt[k] > yMax) continue;
      const x = X(az[k]); if (x < 0 || x > W) continue;
      const y = Y(alt[k]);
      g.beginPath(); g.arc(x, y, 2.2, 0, 2 * Math.PI); g.fill();
      if (b === 'sun' || S.focus === 'moon') g.fillText(fmtTime(d.t0 + k * d.step * 1000, d.tz).slice(0, 2) + 'h', x + 4, Math.max(12, y - 4));
    }
  }
  // rise/set marks: a tick on the skyline and a boxed label below it (staggered so they never overlap)
  const placed = [];
  const marks = d.lines.map((ln) => ({ ln, x: X(ln.az) })).filter((m) => m.x >= 0 && m.x <= W)
    .sort((a, b) => a.x - b.x);
  for (const { ln, x } of marks) {
    const y = Y(hzAt(d, ln.az));
    g.strokeStyle = COL[ln.kind]; g.lineWidth = 2;
    g.beginPath(); g.moveTo(x, y - 8); g.lineTo(x, y + 8); g.stroke();
    const t = ln.label, tw = g.measureText(t).width + 8;
    let lx = Math.min(W - tw - 2, Math.max(2, x - tw / 2));
    let ly = Math.min(H - bottom - 18, y + 12);
    for (const p of placed) {
      if (lx < p.x + p.w + 4 && lx + tw + 4 > p.x && Math.abs(ly - p.y) < 16) ly = p.y - 18;
    }
    placed.push({ x: lx, y: ly, w: tw });
    g.fillStyle = 'rgba(11,17,28,0.85)'; g.fillRect(lx, ly, tw, 15);
    g.strokeStyle = COL[ln.kind]; g.lineWidth = 1; g.strokeRect(lx + 0.5, ly + 0.5, tw - 1, 14);
    g.fillStyle = '#fff'; g.fillText(t, lx + 4, ly + 11);
  }
  // discs now
  const pxPerDeg = (H - bottom - 6) / (yMax - yMin);
  for (const b of ['moon', 'sun']) {
    const az = d[b + '_az'][i], alt = d[b + '_alt'][i];
    if (alt < yMin - 1 || alt > yMax + 1) continue;
    const x = X(az); if (x < -10 || x > W + 10) continue;
    const r = Math.max(b === 'sun' ? 6 : 5, d[b + '_sd'] * pxPerDeg);
    const up = alt + d[b + '_sd'] > hzAt(d, az);
    g.globalAlpha = up ? 1 : 0.45;
    g.fillStyle = b === 'sun' ? '#ffd84d' : '#f2f6ff';
    g.beginPath(); g.arc(x, Y(alt), r, 0, 2 * Math.PI); g.fill();
    if (b === 'sun') { g.strokeStyle = 'rgba(255,200,80,0.5)'; g.lineWidth = 3; g.stroke(); }
    g.globalAlpha = 1;
  }
  if (!all) {
    const b = S.focus, alt = d[b + '_alt'][i];
    if (alt > yMax) { g.fillStyle = '#fff'; g.fillText(`${b === 'sun' ? 'Sun' : 'Moon'} is higher (${alt.toFixed(0)}°) ↑`, W / 2 - 50, 14); }
  }
}

// ------------------------------------------------------------------------------------------
function update(S, d) {
  const prev = S.d;
  S.d = d;
  const sameDay = prev && prev.nonce === d.nonce;
  const samePlace = prev && prev.lat === d.lat && prev.lon === d.lon;
  if (!samePlace) S.map.setView([d.lat, d.lon], prev ? S.map.getZoom() : (d.zoom || 11));
  S.slider.max = d.n - 1;
  // hours
  S.hourIdx = [];
  for (let k = 0; k < d.n; k++) {
    const ms = d.t0 + k * d.step * 1000;
    if (k % 15 === 0 && fmtTime(ms, d.tz).endsWith(':00')) S.hourIdx.push(k);
  }
  if (!sameDay) {
    const idx = Math.round((d.initial_ms - d.t0) / (d.step * 1000));
    S.slider.value = Math.max(0, Math.min(d.n - 1, idx));
  }
  // jump buttons
  S.jumps.innerHTML = '';
  for (const e of d.events) {
    const b = el('button', `ag-chip ag-chip-${e.body}`, `${e.short} <b>${fmtTime(e.ms, d.tz)}</b>`);
    b.type = 'button';
    b.addEventListener('click', () => {
      stopPlay(S);
      S.slider.value = Math.max(0, Math.min(d.n - 1, Math.round((e.ms - d.t0) / (d.step * 1000))));
      render(S);
    });
    S.jumps.appendChild(b);
  }
  if (d.now_ms && d.now_ms >= d.t0 && d.now_ms <= d.t0 + (d.n - 1) * d.step * 1000) {
    const b = el('button', 'ag-chip ag-chip-now', 'Now');
    b.type = 'button';
    b.addEventListener('click', () => {
      stopPlay(S);
      S.slider.value = Math.round((Date.now() - d.t0) / (d.step * 1000));
      render(S);
    });
    S.jumps.prepend(b);
  }
  const src = d.src === 'gps' ? `GPS fix${d.acc ? ` (within ${Math.round(d.acc)} m)` : ''}`
    : d.src === 'map' ? 'picked on the map' : d.src === 'search' ? 'from place search' : 'starting place';
  S.status.textContent = `${d.place || ''} · ${d.lat.toFixed(5)}, ${d.lon.toFixed(5)} · ${src}`;
  drawMe(S); drawFixed(S); drawRidge(S); render(S);
  setTimeout(() => { S.map.invalidateSize(); drawPano(S, +S.slider.value); }, 120);
}

export default function (component) {
  const { data, parentElement, setTriggerValue } = component;
  if (!window.L) {
    parentElement.textContent = 'The map library did not load.';
    return;
  }
  let S = parentElement.__afterglow;
  if (!S || !S.root.isConnected) {
    S = build(parentElement);
    parentElement.__afterglow = S;
  }
  S.send = setTriggerValue;
  if (data) update(S, data);
  return () => {
    stopPlay(S);
    if (S.ro) S.ro.disconnect();
  };
}
