// Afterglow night map - stargazing forecast grid, NOAA aurora oval, light pollution, hour slider.
// Leaflet (window.L) is bundled in front of this file by night_component.py.

const DIRS = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'];
const SCALE = [[80, 'Excellent', '#27ae60'], [60, 'Good', '#7dcf6b'], [40, 'Fair', '#f1c40f'],
               [20, 'Poor', '#e67e22'], [0, 'Bad', '#c0392b']];

function compass(az) { return DIRS[Math.round((((az % 360) + 360) % 360) / 22.5) % 16]; }
function lab(s) { for (const r of SCALE) if (s >= r[0]) return r; return SCALE[SCALE.length - 1]; }
function el(tag, cls, html) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html !== undefined) e.innerHTML = html;
  return e;
}
function fmtTime(ms, tz) {
  try {
    return new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: tz })
      .format(new Date(ms));
  } catch (e) { return new Date(ms).toISOString().slice(11, 16) + ' UTC'; }
}
function distAz(a, b) {
  const R = 6371.0, p1 = a[0] * Math.PI / 180, p2 = b[0] * Math.PI / 180, dl = (b[1] - a[1]) * Math.PI / 180;
  const d = R * Math.acos(Math.min(1, Math.max(-1, Math.sin(p1) * Math.sin(p2) + Math.cos(p1) * Math.cos(p2) * Math.cos(dl))));
  const y = Math.sin(dl) * Math.cos(p2), x = Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dl);
  return [d, (Math.atan2(y, x) * 180 / Math.PI + 360) % 360];
}
function auroraStyle(v) {
  if (v >= 50) return { color: '#e74c3c', fillOpacity: 0.55 };
  if (v >= 30) return { color: '#f1c40f', fillOpacity: 0.5 };
  if (v >= 10) return { color: '#2ecc71', fillOpacity: 0.45 };
  return { color: '#2ecc71', fillOpacity: 0.22 };
}

function locate(S, auto) {
  if (!('geolocation' in navigator)) {
    S.status.textContent = 'This browser cannot share its location. Search for a place or tap the map.';
    return;
  }
  S.status.textContent = auto ? 'Finding your location... (allow location if your browser asks)'
                              : 'Asking your device for its position...';
  navigator.geolocation.getCurrentPosition((p) => {
    const c = p.coords;
    S.status.textContent = `Found you (within ${Math.round(c.accuracy)} m). Loading...`;
    S.send('pick', { lat: c.latitude, lon: c.longitude, acc: c.accuracy, alt: c.altitude,
                     alt_acc: c.altitudeAccuracy, src: 'gps', ts: Date.now() });
  }, (err) => {
    if (err.code === 1 && window.top !== window.self) {
      S.status.textContent = 'The page frame blocked location. ';
      const a = el('a', 'ag-fulllink', 'Open full-screen');
      a.href = window.location.href; a.target = '_top';
      S.status.appendChild(a);
      return;
    }
    const why = err.code === 1 ? 'Location permission was refused; allow it in the browser settings.'
      : err.code === 3 ? 'The device took too long to find you.' : 'Your position is not available right now.';
    S.status.textContent = (auto ? 'Showing a starting place. ' : '') + why + ' Press "Use my location" to try again.';
  }, { enableHighAccuracy: true, timeout: 25000, maximumAge: 0 });
}

function autoLocate(S) {
  if (S.autoTried) return;
  S.autoTried = true;
  try {
    if (sessionStorage.getItem('afterglow-auto-located')) return;
    sessionStorage.setItem('afterglow-auto-located', '1');
  } catch (e) { /* storage blocked */ }
  const go = () => locate(S, true);
  if (navigator.permissions && navigator.permissions.query) {
    navigator.permissions.query({ name: 'geolocation' }).then((st) => { if (st.state !== 'denied') go(); }).catch(go);
  } else go();
}

// ------------------------------------------------------------------------------------------
function build(parent) {
  const S = {};
  const root = el('div', 'ag-root ag-night');
  root.innerHTML = `
    <div class="ag-bar">
      <button type="button" class="ag-btn ag-gps">Use my location</button>
      <span class="ag-status"></span>
    </div>
    <div class="ag-map"></div>
    <div class="ag-timebar">
      <button type="button" class="ag-btn ag-play" title="Play the night">Play</button>
      <input type="range" class="ag-slider" min="0" max="10" step="1" value="0" aria-label="Hour of the night">
      <span class="ag-clock">--:--</span>
    </div>
    <div class="ag-hours"></div>
    <div class="ag-readout"></div>
    <div class="ag-legend">
      <span><b>Sky quality:</b></span>
      ${SCALE.slice().reverse().map((r) => `<span><i style="background:${r[2]}"></i>${r[1]}</span>`).join('')}
      <span>&nbsp;<b>Aurora now:</b></span>
      <span><i style="background:#2ecc71"></i>possible</span><span><i style="background:#f1c40f"></i>likely</span>
      <span><i style="background:#e74c3c"></i>strong</span>
      <span>&#9733; clearest spot this hour</span>
    </div>`;
  parent.appendChild(root);
  S.root = root;
  S.status = root.querySelector('.ag-status');
  S.slider = root.querySelector('.ag-slider');
  S.clock = root.querySelector('.ag-clock');
  S.hoursBox = root.querySelector('.ag-hours');
  S.readout = root.querySelector('.ag-readout');

  const map = L.map(root.querySelector('.ag-map'), { zoomControl: true, worldCopyJump: true });
  S.map = map;
  const base = {
    'Dark map': L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
      maxZoom: 19, subdomains: 'abcd', attribution: '&copy; OpenStreetMap contributors &copy; CARTO' }),
    'Topographic': L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png', {
      maxZoom: 17, subdomains: 'abc',
      attribution: 'Map &copy; OpenStreetMap contributors, SRTM | Style &copy; OpenTopoMap (CC-BY-SA)' }),
    'Satellite photo': L.tileLayer(
      'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
      maxZoom: 19, attribution: 'Imagery &copy; Esri, Maxar, Earthstar Geographics' }),
  };
  base['Dark map'].addTo(map);
  const gibs = (layer, time, tms, ext, maxN, op) => L.tileLayer(
    `https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/${layer}/default/${time}/${tms}/{z}/{y}/{x}.${ext}`,
    { maxNativeZoom: maxN, maxZoom: 19, opacity: op, attribution: 'NASA GIBS / EOSDIS' });
  S.canvas = L.canvas({ padding: 0.3 });
  S.gridLayer = L.layerGroup().addTo(map);
  S.labelLayer = L.layerGroup().addTo(map);
  S.auroraLayer = L.layerGroup().addTo(map);
  S.me = L.layerGroup().addTo(map);
  S.bestLayer = L.layerGroup().addTo(map);
  const overlays = {
    'Stargazing forecast (selected hour)': S.gridLayer,
    'Aurora now (NOAA OVATION)': S.auroraLayer,
    'Light pollution (NASA Black Marble 2016)': gibs('VIIRS_Black_Marble', '2016-01-01', 'GoogleMapsCompatible_Level8', 'png', 8, 0.75),
    'Live clouds, infrared - Americas (GOES-East)': gibs('GOES-East_ABI_Band13_Clean_Infrared', 'default', 'GoogleMapsCompatible_Level6', 'png', 6, 0.6),
    'Live clouds, infrared - Pacific (GOES-West)': gibs('GOES-West_ABI_Band13_Clean_Infrared', 'default', 'GoogleMapsCompatible_Level6', 'png', 6, 0.6),
    'Live clouds, infrared - Asia & Australia (Himawari)': gibs('Himawari_AHI_Band13_Clean_Infrared', 'default', 'GoogleMapsCompatible_Level6', 'png', 6, 0.6),
  };
  L.control.layers(base, overlays, { collapsed: true, position: 'topright' }).addTo(map);
  L.control.scale({ imperial: true, metric: true }).addTo(map);
  map.on('zoomend', () => { if (S.d) drawLabels(S); });
  map.on('click', (ev) => {
    const lat = ev.latlng.lat, lon = ((ev.latlng.lng + 540) % 360) - 180;
    const box = el('div', 'ag-pop', `<div>${lat.toFixed(5)}, ${lon.toFixed(5)}</div>`);
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
  root.querySelector('.ag-gps').addEventListener('click', () => locate(S, false));
  S.slider.addEventListener('input', () => { stopPlay(S); render(S); });
  root.querySelector('.ag-play').addEventListener('click', () => {
    if (S.playing) { stopPlay(S); return; }
    root.querySelector('.ag-play').textContent = 'Pause';
    if (+S.slider.value >= +S.slider.max) S.slider.value = 0;
    S.playing = setInterval(() => {
      const v = +S.slider.value + 1;
      if (v > +S.slider.max) { stopPlay(S); return; }
      S.slider.value = v; render(S);
    }, 700);
  });
  if (window.ResizeObserver) {
    S.ro = new ResizeObserver(() => map.invalidateSize());
    S.ro.observe(root);
  }
  return S;
}

function stopPlay(S) {
  if (S.playing) { clearInterval(S.playing); S.playing = null; }
  const b = S.root.querySelector('.ag-play');
  if (b) b.textContent = 'Play';
}

function drawGrid(S) {
  const d = S.d;
  S.gridLayer.clearLayers();
  S.cells = d.pts.map((p) => L.rectangle([[p[0] - d.hlat, p[1] - d.hlon], [p[0] + d.hlat, p[1] + d.hlon]], {
    renderer: S.canvas, weight: 0, fillOpacity: 0.42, fillColor: '#555', interactive: true }).addTo(S.gridLayer));
}

function drawLabels(S) {
  const d = S.d, i = +S.slider.value;
  S.labelLayer.clearLayers();
  // label the squares only when they are big enough on screen to hold a number
  const a = S.map.latLngToContainerPoint([d.lat, d.lon - d.hlon]);
  const b = S.map.latLngToContainerPoint([d.lat, d.lon + d.hlon]);
  if (Math.abs(b.x - a.x) < 30) return;
  d.pts.forEach((p, k) => {
    const s = d.scores[i][k];
    if (s < 0) return;
    L.marker(p, { icon: L.divIcon({ className: 'ag-cell', html: `<span>${s}</span>`, iconSize: null }),
                  interactive: false }).addTo(S.labelLayer);
  });
}

function drawAurora(S) {
  const d = S.d;
  S.auroraLayer.clearLayers();
  for (const c of d.ovation) {
    const st = auroraStyle(c[2]);
    L.rectangle([[c[0] - 0.5, c[1] - 0.5], [c[0] + 0.5, c[1] + 0.5]], {
      renderer: S.canvas, weight: 0, fillColor: st.color, fillOpacity: st.fillOpacity, interactive: false })
      .addTo(S.auroraLayer);
  }
}

function drawMe(S) {
  const d = S.d;
  S.me.clearLayers();
  if (d.acc && d.acc > 0) L.circle([d.lat, d.lon], { radius: d.acc, color: '#ff4f7b', weight: 1, fillOpacity: 0.08,
                                                     interactive: false }).addTo(S.me);
  L.circleMarker([d.lat, d.lon], { radius: 7, color: '#fff', weight: 2, fillColor: '#ff4f7b', fillOpacity: 1 })
    .bindTooltip(d.place || 'You', { direction: 'top' }).addTo(S.me);
}

function render(S) {
  const d = S.d, i = +S.slider.value;
  S.clock.textContent = fmtTime(d.hours[i], d.tz);
  const sc = d.scores[i];
  S.cells.forEach((r, k) => {
    const s = sc[k];
    const [, name, col] = lab(Math.max(0, s));
    const cl = d.clouds[i][k];
    r.setStyle({ fillColor: s < 0 ? '#444' : col, fillOpacity: s < 0 ? 0.1 : 0.42 });
    r.bindTooltip(s < 0 ? 'no forecast' : `Sky ${s} (${name})<br>cloud low ${cl[0]}% · mid ${cl[1]}% · high ${cl[2]}%`,
                  { sticky: true });
  });
  drawLabels(S);
  // best cell this hour
  let best = -1, bk = -1;
  sc.forEach((s, k) => { if (s > best) { best = s; bk = k; } });
  S.bestLayer.clearLayers();
  const hi = d.hour_info[i];
  const here = sc[d.centre];
  const parts = [];
  if (here >= 0) {
    const [, name, col] = lab(here);
    const cl = d.clouds[i][d.centre];
    parts.push(`<span><b style="color:${col}">Your spot: ${here} ${name}</b> · cloud low ${cl[0]}%, mid ${cl[1]}%, high ${cl[2]}%</span>`);
  } else parts.push('<span><b>Your spot:</b> no forecast for this hour</span>');
  parts.push(`<span>Sun ${hi.sun.toFixed(0)}° · Moon ${hi.moon > 0 ? `up ${hi.moon.toFixed(0)}°` : 'down'}, ${Math.round(hi.illum * 100)}% lit · ${hi.steady}</span>`);
  if (bk >= 0 && best > here + 4) {
    const [km, az] = distAz([d.lat, d.lon], d.pts[bk]);
    const [, bname, bcol] = lab(best);
    parts.push(`<span><b style="color:${bcol}">Clearest nearby: ${best} ${bname}</b>, about ${Math.round(km)} km ${compass(az)}</span>`);
    L.marker(d.pts[bk], { icon: L.divIcon({ className: 'ag-star', html: '<span>&#9733;</span>', iconSize: null }), interactive: false })
      .addTo(S.bestLayer);
  }
  S.readout.innerHTML = parts.join('');
  S.hoursBox.querySelectorAll('.ag-hr').forEach((b, k) => b.classList.toggle('on', k === i));
}

function update(S, d) {
  const prev = S.d;
  S.d = d;
  const samePlace = prev && prev.lat === d.lat && prev.lon === d.lon;
  const sameNight = prev && prev.nonce === d.nonce;
  S.slider.max = d.hours.length - 1;
  if (!sameNight) S.slider.value = Math.max(0, Math.min(d.hours.length - 1, d.initial));
  drawGrid(S);
  drawAurora(S);
  drawMe(S);
  if (!samePlace) {
    const p0 = d.pts[0], p1 = d.pts[d.pts.length - 1];
    S.map.fitBounds([[p0[0] - d.hlat, p0[1] - d.hlon], [p1[0] + d.hlat, p1[1] + d.hlon]], { padding: [10, 10] });
  }
  // hour strip coloured by the forecast at your spot
  S.hoursBox.innerHTML = '';
  d.hours.forEach((ms, k) => {
    const s = d.scores[k][d.centre];
    const col = s < 0 ? '#333' : lab(s)[2];
    const b = el('button', 'ag-hr', `<i style="background:${col}"></i>${fmtTime(ms, d.tz).slice(0, 2)}`);
    b.type = 'button';
    b.title = s < 0 ? 'no forecast' : `${fmtTime(ms, d.tz)}: ${s} ${lab(s)[1]}`;
    b.addEventListener('click', () => { stopPlay(S); S.slider.value = k; render(S); });
    S.hoursBox.appendChild(b);
  });
  const src = d.src === 'gps' ? `your position${d.acc ? ` (within ${Math.round(d.acc)} m)` : ''}`
    : d.src === 'map' ? 'picked on the map' : d.src === 'search' ? 'from place search'
    : 'starting guess from your time zone';
  S.status.textContent = `${d.place || ''} · ${d.lat.toFixed(5)}, ${d.lon.toFixed(5)} · ${src}`;
  if (d.src === 'start') autoLocate(S);
  render(S);
  setTimeout(() => S.map.invalidateSize(), 120);
}

export default function (component) {
  const { data, parentElement, setTriggerValue } = component;
  if (!window.L) { parentElement.textContent = 'The map library did not load.'; return; }
  let S = parentElement.__afterglowNight;
  if (!S || !S.root.isConnected) { S = build(parentElement); parentElement.__afterglowNight = S; }
  S.send = setTriggerValue;
  if (data) update(S, data);
  return () => { stopPlay(S); if (S.ro) S.ro.disconnect(); };
}
