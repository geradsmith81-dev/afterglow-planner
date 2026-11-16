// Afterglow sky pointer - a sky map (looking up) and a compass that point to a target
// (a meteor shower's radiant or a comet), with a time slider through the night.

const DIRS = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'];
function compass(az) { return DIRS[Math.round((((az % 360) + 360) % 360) / 22.5) % 16]; }
function fmtTime(ms, tz) {
  try {
    return new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: tz })
      .format(new Date(ms));
  } catch (e) { return new Date(ms).toISOString().slice(11, 16) + ' UTC'; }
}
function el(tag, cls, html) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html !== undefined) e.innerHTML = html;
  return e;
}
function canvasFor(c, w, h) {
  const dpr = window.devicePixelRatio || 1;
  c.style.width = w + 'px'; c.style.height = h + 'px';
  c.width = Math.round(w * dpr); c.height = Math.round(h * dpr);
  const g = c.getContext('2d');
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  return g;
}

function build(parent) {
  const S = { heading: null, live: false };
  const root = el('div', 'ag-root ag-sky');
  root.innerHTML = `
    <div class="ag-skyrow">
      <div class="ag-skybox"><canvas class="ag-dome"></canvas>
        <div class="ag-cap">Sky map, looking up: north at the top, <b>east on the left</b>, the edge is the horizon.</div></div>
      <div class="ag-skybox"><canvas class="ag-compass"></canvas>
        <div class="ag-point"></div>
        <button type="button" class="ag-btn ag-live">Use my phone's compass</button>
        <div class="ag-cap ag-livecap"></div></div>
    </div>
    <div class="ag-timebar">
      <input type="range" class="ag-slider" min="0" max="10" step="1" value="0" aria-label="Time of night">
      <span class="ag-clock">--:--</span>
    </div>
    <div class="ag-cap ag-hint"></div>`;
  parent.appendChild(root);
  S.root = root;
  S.dome = root.querySelector('.ag-dome');
  S.comp = root.querySelector('.ag-compass');
  S.point = root.querySelector('.ag-point');
  S.slider = root.querySelector('.ag-slider');
  S.clock = root.querySelector('.ag-clock');
  S.hint = root.querySelector('.ag-hint');
  S.livecap = root.querySelector('.ag-livecap');
  S.slider.addEventListener('input', () => draw(S));
  root.querySelector('.ag-live').addEventListener('click', () => startLive(S));
  if (window.ResizeObserver) { S.ro = new ResizeObserver(() => { if (S.d) draw(S); }); S.ro.observe(root); }
  return S;
}

// ---- phone compass ------------------------------------------------------------------------
function onOrient(S, e) {
  let h = null;
  if (typeof e.webkitCompassHeading === 'number') h = e.webkitCompassHeading;          // iPhone / iPad
  else if (e.absolute && typeof e.alpha === 'number') h = (360 - e.alpha) % 360;       // Android
  if (h === null) return;
  const so = (screen.orientation && typeof screen.orientation.angle === 'number') ? screen.orientation.angle
    : (typeof window.orientation === 'number' ? window.orientation : 0);
  S.heading = (h + so + 360) % 360;
  S.gotHeading = true;
  if (!S.raf) S.raf = requestAnimationFrame(() => { S.raf = null; drawCompass(S); });
}
async function startLive(S) {
  if (S.live) {                                             // second tap switches it off
    S.live = false; S.heading = null;
    window.removeEventListener('deviceorientationabsolute', S.handler, true);
    window.removeEventListener('deviceorientation', S.handler, true);
    S.root.querySelector('.ag-live').textContent = "Use my phone's compass";
    S.livecap.textContent = '';
    drawCompass(S);
    return;
  }
  if (typeof DeviceOrientationEvent === 'undefined') { S.livecap.textContent = 'This device has no compass.'; return; }
  try {
    if (typeof DeviceOrientationEvent.requestPermission === 'function') {      // iOS asks first
      const r = await DeviceOrientationEvent.requestPermission();
      if (r !== 'granted') { S.livecap.textContent = 'Compass permission was refused.'; return; }
    }
  } catch (err) { S.livecap.textContent = 'The compass could not be started.'; return; }
  S.handler = (e) => onOrient(S, e);
  window.addEventListener('deviceorientationabsolute', S.handler, true);
  window.addEventListener('deviceorientation', S.handler, true);
  S.live = true; S.gotHeading = false;
  S.root.querySelector('.ag-live').textContent = 'Stop using the compass';
  S.livecap.textContent = 'Hold the phone flat, top edge pointing ahead. Phone compasses can be off by 10-20° ' +
    '(magnetic north, nearby metal); check against a landmark.';
  setTimeout(() => { if (S.live && !S.gotHeading) S.livecap.textContent = 'No compass readings from this device.'; }, 3000);
}

// ---- drawing ------------------------------------------------------------------------------
function draw(S) {
  const d = S.d, i = +S.slider.value;
  S.clock.textContent = fmtTime(d.times[i], d.tz);
  drawDome(S, i);
  drawCompass(S);
}

function sizes(S) {
  const W = Math.max(280, S.root.clientWidth || 600);
  const wide = W >= 620;
  const dome = Math.min(wide ? Math.floor(W * 0.56) : W, 460);
  const comp = Math.min(wide ? Math.floor(W * 0.36) : W, 300);
  return { dome, comp };
}

function drawDome(S, i) {
  const d = S.d, { dome } = sizes(S);
  const g = canvasFor(S.dome, dome, dome);
  const cx = dome / 2, cy = dome / 2, R = dome / 2 - 18;
  const P = (alt, az) => {
    const r = (90 - Math.max(alt, -2)) / 90 * R, a = az * Math.PI / 180;
    return [cx - r * Math.sin(a), cy - r * Math.cos(a)];
  };
  const sun = d.sun[i];
  g.fillStyle = sun < -18 ? '#05080f' : (sun < -12 ? '#0b1430' : (sun < -6 ? '#14244d' : '#2a3f6e'));
  g.beginPath(); g.arc(cx, cy, R, 0, 2 * Math.PI); g.fill();
  g.strokeStyle = 'rgba(255,255,255,0.18)'; g.lineWidth = 1;
  for (const a of [30, 60]) { g.beginPath(); g.arc(cx, cy, (90 - a) / 90 * R, 0, 2 * Math.PI); g.stroke(); }
  g.strokeStyle = '#3b4a66'; g.lineWidth = 2; g.beginPath(); g.arc(cx, cy, R, 0, 2 * Math.PI); g.stroke();
  g.font = 'bold 13px system-ui, sans-serif'; g.fillStyle = '#ffcd9c'; g.textAlign = 'center'; g.textBaseline = 'middle';
  for (const [t, az] of [['N', 0], ['E', 90], ['S', 180], ['W', 270]]) {
    const [x, y] = P(-9, az); g.fillText(t, x, y);
  }
  g.font = '10px system-ui, sans-serif'; g.fillStyle = 'rgba(255,255,255,0.55)';
  g.fillText('60°', cx + 4, cy - (30 / 90) * R + 8); g.fillText('30°', cx + 4, cy - (60 / 90) * R + 8);
  // stars
  for (const s of d.stars[i]) {
    if (s[1] < 0) continue;
    const [x, y] = P(s[1], s[0]);
    g.fillStyle = '#f4efe8';
    g.beginPath(); g.arc(x, y, Math.max(0.8, 3.0 - 0.55 * s[2]), 0, 2 * Math.PI); g.fill();
    const nm = d.star_names[s[3]];
    if (nm) { g.fillStyle = 'rgba(244,239,232,0.75)'; g.textAlign = 'left'; g.fillText(nm, x + 5, y - 6); }
  }
  // Moon and planets
  for (const b of d.bodies) {
    if (b.alt[i] < 0) continue;
    const [x, y] = P(b.alt[i], b.az[i]);
    const moon = b.name === 'Moon';
    g.fillStyle = moon ? '#dcefff' : '#ffe680';
    g.beginPath(); g.arc(x, y, moon ? 7 : 3.5, 0, 2 * Math.PI); g.fill();
    g.font = '11px system-ui, sans-serif'; g.textAlign = 'left';
    g.fillText(moon ? `Moon ${Math.round(d.moon_illum * 100)}%` : b.name, x + 8, y + 4);
  }
  // the target's path through the night, with hour marks
  g.strokeStyle = 'rgba(255,159,107,0.85)'; g.lineWidth = 1.5; g.setLineDash([4, 4]); g.beginPath();
  let pen = false;
  for (let k = 0; k < d.times.length; k++) {
    if (d.alt[k] < 0) { pen = false; continue; }
    const [x, y] = P(d.alt[k], d.az[k]);
    if (!pen) { g.moveTo(x, y); pen = true; } else g.lineTo(x, y);
  }
  g.stroke(); g.setLineDash([]);
  g.font = '10px system-ui, sans-serif'; g.fillStyle = '#ffb38a'; g.textAlign = 'left';
  for (let k = 0; k < d.times.length; k++) {
    const t = fmtTime(d.times[k], d.tz);
    if (d.alt[k] >= 0 && t.endsWith(':00') || (d.alt[k] >= 0 && k > 0 && fmtTime(d.times[k - 1], d.tz).slice(0, 2) !== t.slice(0, 2))) {
      const [x, y] = P(d.alt[k], d.az[k]);
      g.beginPath(); g.arc(x, y, 2, 0, 2 * Math.PI); g.fill();
      g.fillText(t.slice(0, 2) + 'h', x + 4, y + 10);
    }
  }
  // the target now
  const up = d.alt[i] >= 0;
  const [tx, ty] = P(d.alt[i], d.az[i]);
  g.strokeStyle = '#ff4f7b'; g.lineWidth = 3;
  g.beginPath(); g.arc(tx, ty, 11, 0, 2 * Math.PI); g.stroke();
  g.beginPath(); g.moveTo(tx - 17, ty); g.lineTo(tx - 7, ty); g.moveTo(tx + 7, ty); g.lineTo(tx + 17, ty);
  g.moveTo(tx, ty - 17); g.lineTo(tx, ty - 7); g.moveTo(tx, ty + 7); g.lineTo(tx, ty + 17); g.stroke();
  g.font = 'bold 12px system-ui, sans-serif'; g.fillStyle = '#ffffff'; g.textAlign = tx > cx ? 'right' : 'left';
  g.fillText(d.label + (up ? '' : ' (below the horizon)'), tx + (tx > cx ? -16 : 16), ty - 16);
}

function drawCompass(S) {
  const d = S.d; if (!d) return;
  const i = +S.slider.value, { comp } = sizes(S);
  const g = canvasFor(S.comp, comp, comp);
  const cx = comp / 2, cy = comp / 2, R = comp / 2 - 22;
  const rot = S.heading === null ? 0 : -S.heading;          // dial turns with the phone
  const ang = (deg) => (deg + rot - 90) * Math.PI / 180;     // 0 deg = up
  g.fillStyle = '#111927'; g.beginPath(); g.arc(cx, cy, R + 14, 0, 2 * Math.PI); g.fill();
  g.strokeStyle = '#3b4a66'; g.lineWidth = 2; g.beginPath(); g.arc(cx, cy, R, 0, 2 * Math.PI); g.stroke();
  for (let a = 0; a < 360; a += 15) {
    const big = a % 90 === 0, mid = a % 45 === 0;
    const r1 = R - (big ? 14 : mid ? 10 : 6);
    g.strokeStyle = big ? '#ffcd9c' : 'rgba(255,255,255,0.45)'; g.lineWidth = big ? 2.5 : 1;
    g.beginPath(); g.moveTo(cx + r1 * Math.cos(ang(a)), cy + r1 * Math.sin(ang(a)));
    g.lineTo(cx + R * Math.cos(ang(a)), cy + R * Math.sin(ang(a))); g.stroke();
  }
  g.font = 'bold 15px system-ui, sans-serif'; g.textAlign = 'center'; g.textBaseline = 'middle';
  for (const [t, a] of [['N', 0], ['E', 90], ['S', 180], ['W', 270]]) {
    g.fillStyle = t === 'N' ? '#ff7f9f' : '#f4efe8';
    g.fillText(t, cx + (R + 1 - 26) * Math.cos(ang(a)), cy + (R + 1 - 26) * Math.sin(ang(a)));
  }
  // phone direction marker (top of the screen) in live mode
  if (S.heading !== null) {
    g.fillStyle = '#6fd0dc'; g.beginPath(); g.moveTo(cx, cy - R - 12); g.lineTo(cx - 7, cy - R + 2); g.lineTo(cx + 7, cy - R + 2);
    g.closePath(); g.fill();
  }
  // the arrow
  const az = d.az[i], alt = d.alt[i], up = alt >= 0;
  const a = ang(az), L = R - 58;  // tip stays inside the N/E/S/W letters
  g.strokeStyle = up ? '#ff4f7b' : 'rgba(255,79,123,0.45)'; g.fillStyle = g.strokeStyle; g.lineWidth = 6; g.lineCap = 'round';
  g.beginPath(); g.moveTo(cx - 14 * Math.cos(a), cy - 14 * Math.sin(a)); g.lineTo(cx + L * Math.cos(a), cy + L * Math.sin(a)); g.stroke();
  g.beginPath();
  g.moveTo(cx + (L + 14) * Math.cos(a), cy + (L + 14) * Math.sin(a));
  g.lineTo(cx + L * Math.cos(a) + 10 * Math.cos(a + Math.PI / 2), cy + L * Math.sin(a) + 10 * Math.sin(a + Math.PI / 2));
  g.lineTo(cx + L * Math.cos(a) - 10 * Math.cos(a + Math.PI / 2), cy + L * Math.sin(a) - 10 * Math.sin(a + Math.PI / 2));
  g.closePath(); g.fill();
  g.fillStyle = '#f4efe8'; g.beginPath(); g.arc(cx, cy, 5, 0, 2 * Math.PI); g.fill();
  // words
  let txt;
  if (up) {
    const fists = Math.round(alt / 10 * 2) / 2;
    txt = `<b>Face ${compass(az)} (${Math.round(az)}°)</b> and look up <b>${Math.round(alt)}°</b>` +
      (alt >= 5 ? ` - about ${fists} fist${fists === 1 ? '' : 's'} above the horizon at arm's length` : ' - just above the horizon');
  } else {
    let k = -1;
    for (let j = i + 1; j < d.alt.length; j++) if (d.alt[j] >= 0) { k = j; break; }
    txt = `<b>${d.label} is below the horizon at this time</b>` +
      (k >= 0 ? ` - it rises in the ${compass(d.az[k])} at about ${fmtTime(d.times[k], d.tz)}.` : ' for the rest of the night.');
  }
  if (S.heading !== null && up) {
    let turn = ((az - S.heading + 540) % 360) - 180;
    txt += `<br>Your phone points ${compass(S.heading)} (${Math.round(S.heading)}°): ` +
      (Math.abs(turn) < 8 ? '<b>you are facing it</b>' : `turn <b>${turn > 0 ? 'right' : 'left'} ${Math.abs(Math.round(turn))}°</b>`);
  }
  const sun = d.sun[i];
  txt += `<br><span class="ag-dim">${sun < -18 ? 'Fully dark' : sun < -12 ? 'Nautical twilight' : sun < -6 ? 'Civil twilight' : 'Sun up or just set'} at ${fmtTime(d.times[i], d.tz)}.</span>`;
  S.point.innerHTML = txt;
}

function update(S, d) {
  const prev = S.d;
  S.d = d;
  S.slider.max = d.times.length - 1;
  if (!prev || prev.nonce !== d.nonce) S.slider.value = d.initial;
  S.hint.innerHTML = d.hint || '';
  draw(S);
}

export default function (component) {
  const { data, parentElement } = component;
  let S = parentElement.__afterglowSky;
  if (!S || !S.root.isConnected) { S = build(parentElement); parentElement.__afterglowSky = S; }
  if (data) update(S, data);
  return () => {
    if (S.ro) S.ro.disconnect();
    if (S.handler) {
      window.removeEventListener('deviceorientationabsolute', S.handler, true);
      window.removeEventListener('deviceorientation', S.handler, true);
    }
  };
}
