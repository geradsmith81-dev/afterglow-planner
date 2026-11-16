// Afterglow eclipse map - where an eclipse can be seen, the central line, and your position.
// Leaflet (window.L) is bundled in front of this file by events_component.py.

function el(tag, cls, html) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html !== undefined) e.innerHTML = html;
  return e;
}

function colourFor(d, v) {
  for (const b of d.breaks) if (v >= b[0]) return b[1];
  return d.breaks[d.breaks.length - 1][1];
}

function build(parent) {
  const S = {};
  const root = el('div', 'ag-root ag-events');
  root.innerHTML = `
    <div class="ag-bar"><span class="ag-status"></span></div>
    <div class="ag-map"></div>
    <div class="ag-legend"></div>`;
  parent.appendChild(root);
  S.root = root;
  S.status = root.querySelector('.ag-status');
  S.legend = root.querySelector('.ag-legend');
  const map = L.map(root.querySelector('.ag-map'), { zoomControl: true, worldCopyJump: true, minZoom: 1 });
  S.map = map;
  const base = {
    'Dark map': L.layerGroup([
      L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}', {
        maxZoom: 16, attribution: 'Base map &copy; Esri, HERE, Garmin, &copy; OpenStreetMap contributors' }),
      L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}', {
        maxZoom: 16 }),
    ]),
    'Satellite photo': L.tileLayer(
      'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
      maxZoom: 19, attribution: 'Imagery &copy; Esri, Maxar, Earthstar Geographics' }),
  };
  base['Dark map'].addTo(map);
  S.canvas = L.canvas({ padding: 0.3 });
  S.cells = L.layerGroup().addTo(map);
  S.line = L.layerGroup().addTo(map);
  S.me = L.layerGroup().addTo(map);
  L.control.layers(base, { 'Where it is seen': S.cells, 'Central line': S.line }, { collapsed: true, position: 'topright' })
    .addTo(map);
  L.control.scale({ imperial: true, metric: true }).addTo(map);
  map.on('click', (ev) => {
    const lat = ev.latlng.lat, lon = ((ev.latlng.lng + 540) % 360) - 180;
    const box = el('div', 'ag-pop', `<div>${lat.toFixed(4)}, ${lon.toFixed(4)}</div>`);
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
  if (window.ResizeObserver) {
    S.ro = new ResizeObserver(() => map.invalidateSize());
    S.ro.observe(root);
  }
  return S;
}

function update(S, d) {
  const prev = S.d;
  S.d = d;
  S.cells.clearLayers();
  const h = d.step / 2;
  for (const c of d.cells) {
    for (const shift of [-360, 0, 360]) {
      L.rectangle([[c[0] - h, c[1] - h + shift], [c[0] + h, c[1] + h + shift]], {
        renderer: S.canvas, weight: 0, fillColor: colourFor(d, c[2]), fillOpacity: 0.5, interactive: false,
      }).addTo(S.cells);
    }
  }
  S.line.clearLayers();
  if (d.line && d.line.length > 1) {
    // split where the line crosses the date line
    let seg = [d.line[0]];
    const segs = [];
    for (let k = 1; k < d.line.length; k++) {
      if (Math.abs(d.line[k][1] - d.line[k - 1][1]) > 180) { segs.push(seg); seg = []; }
      seg.push(d.line[k]);
    }
    segs.push(seg);
    for (const s of segs) {
      L.polyline(s, { color: d.line_colour || '#ffffff', weight: 4, opacity: 0.95, interactive: false }).addTo(S.line);
    }
  }
  S.me.clearLayers();
  L.circleMarker([d.lat, d.lon], { radius: 7, color: '#fff', weight: 2, fillColor: '#ff4f7b', fillOpacity: 1 })
    .bindTooltip(d.place || 'You', { direction: 'top' }).addTo(S.me);
  S.legend.innerHTML = `<span><b>${d.legend_title}</b></span>` +
    d.legend.map((r) => `<span><i style="background:${r[1]}"></i>${r[0]}</span>`).join('') +
    (d.line && d.line.length > 1 ? `<span><i style="background:${d.line_colour || '#fff'}"></i>${d.line_label}</span>` : '');
  S.status.textContent = d.title;
  if (!prev || prev.nonce !== d.nonce) S.map.setView([Math.max(-60, Math.min(70, d.view[0])), d.view[1]], d.zoom || 2);
  setTimeout(() => S.map.invalidateSize(), 120);
}

export default function (component) {
  const { data, parentElement, setTriggerValue } = component;
  if (!window.L) { parentElement.textContent = 'The map library did not load.'; return; }
  let S = parentElement.__afterglowEvents;
  if (!S || !S.root.isConnected) { S = build(parentElement); parentElement.__afterglowEvents = S; }
  S.send = setTriggerValue;
  if (data) update(S, data);
  return () => { if (S.ro) S.ro.disconnect(); };
}
