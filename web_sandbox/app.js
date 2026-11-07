/* MASooda live demo — map-constrained multi-drone governance.
 * Streams frames from the local Python simulator (POST /api/runs, GET /api/runs/<id>/frames)
 * and renders: corridor map (IITH campus / Hyderabad), 2.5D view of the selected drone with its
 * own event feed, DTC + V2V network theory over time, STL safety, and governance KPIs.
 * No external dependencies. */
'use strict';
const $ = (s) => document.querySelector(s);
const COLORS = {EMERGENCY: '#ff5f72', EVTOL: '#37d7f2', DELIVERY: '#f6bd4b'};
const TYPE_SHORT = {EMERGENCY: 'EMG', EVTOL: 'eVTOL', DELIVERY: 'DEL'};
const STATUS = ['queued', 'airborne', 'landed', 'crashed', 'forced landing'];
const BMS = ['NORMAL', 'WARNING', 'CRITICAL', 'FAULT'], BMS_COL = ['#2fe0a0', '#f6bd4b', '#ff3b5c', '#ff3b5c'];
const SECTOR_COLS = 3, SECTOR_ROWS = 2;

const SCENES = {
  normal:     {title: 'Normal operations', mix: [10, 30, 60], arch: 'hierarchical', overseer: true, admm: true, defense: true, attack: false, outage: false},
  emergency:  {title: 'Emergency surge — priority & reserved layer', mix: [30, 30, 40], arch: 'hierarchical', overseer: true, admm: true, defense: true, attack: false, outage: false},
  outage:     {title: 'DTC link outage — drones hold last directive', mix: [10, 30, 60], arch: 'hierarchical', overseer: true, admm: true, defense: true, attack: false, outage: true},
  attack:     {title: 'GPS-spoofing attack — trusted-range + W-MSR defence', mix: [10, 30, 60], arch: 'hierarchical', overseer: true, admm: true, defense: true, attack: true, outage: false},
  undefended: {title: 'GPS-spoofing attack — defence disabled', mix: [10, 30, 60], arch: 'hierarchical', overseer: true, admm: true, defense: false, attack: true, outage: false},
  decentral:  {title: 'Decentralized baseline — no DTC', mix: [10, 30, 60], arch: 'decentralized', overseer: false, admm: true, defense: true, attack: false, outage: false},
};
// architecture -> fixed switches [DTC, ADMM, defence, junction merging] (null = as chosen); mirrors route_engine.ARCHITECTURES
const ARCH = {
  hierarchical: {label: 'Hierarchical', fixed: null},
  centralized: {label: 'Centralized', fixed: [true, false, false, false]},
  decentralized: {label: 'Decentralized', fixed: [false, true, true, null]},
  decentralized_undefended: {label: 'Decentralized · undefended', fixed: [false, true, false, null]},
};
const SWITCH_IDS = ['#swOverseer', '#swAdmm', '#swDefense', '#swMerge'];
const ADVANCED = [
  ['local_behavior.v_cruise', 'Cruise speed (m/s)'],
  ['safety.minimum_separation_meters', 'Min separation d_min (m)'],
  ['safety.maximum_velocity_meters_per_second', 'Max speed (m/s)'],
  ['corridors.width_meters', 'Corridor tube width (m)'],
  ['corridors.capacity', 'Capacity per sector-layer'],
  ['communication.radius_meters', 'V2V comm radius (m)'],
  ['admm.detection_radius_meters', 'ADMM detection radius (m)'],
  ['overseer.update_period_seconds', 'DTC update period (s)'],
  ['airspace.layer_height_meters', 'Layer spacing (m)'],
  ['simulation.timestep_seconds', 'Timestep (s)'],
];
const NET_SERIES = [
  {key: 'cover', label: 'DTC coverage', color: '#a98bff'},
  {key: 'trans', label: 'Transitivity', color: '#2fe0a0'},
  {key: 'deg', label: 'Avg degree (norm.)', color: '#37d7f2'},
  {key: 'cent', label: 'Max degree centrality', color: '#f6bd4b'},
  {key: 'giant', label: 'Largest component', color: '#e6f0fa'},
  {key: 'stale', label: 'Directive age (norm.)', color: '#ff5f72'},
];

let baseConfig = null, LIMITS = null, MAP = null, MAPS = [], mapId = null, RUN = null, frames = [], done = false;
let nextSeq = 0, lastStats = null, shownEvents = new WeakSet(), speedProbe = [];
let scene = 'normal', simT = 0, playing = true, speed = 2, lastTs = 0, selected = null, layerFilter = 'all', follow = false;
let view = {cx: 0, cy: 0, s: 0.2}, userMoved = false, dpr = 1, ctxPaths = null, backdropImg = null, logCursor = 0, logTotal = 0;
let droneEvents = {}, eventsIndexed = 0, netPositions = null, lastDroneFeedKey = '';
let negHist = {}, chosenSwitches = null, lastPrio = null, lastH = null, hselHist = {}, dTab = 'ov';
const hCellsC = $('#hCells'), hcctx = hCellsC.getContext('2d'), hChartC = $('#hChart'), hchctx = hChartC.getContext('2d');
const canvas = $('#map'), ctx = canvas.getContext('2d');
const chart = $('#chart'), cctx = chart.getContext('2d');
const v25 = $('#view25'), vctx = v25.getContext('2d');
const netG = $('#netGraph'), nctx = netG.getContext('2d');
const netC = $('#netChart'), ncctx = netC.getContext('2d');
const admmC = $('#admmChart'), actx = admmC.getContext('2d');

// ------------------------------------------------------------------ helpers
const get = (o, p) => p.split('.').reduce((v, k) => v?.[k], o);
function set(o, p, v) { const k = p.split('.'); let t = o; for (const x of k.slice(0, -1)) t = t[x] ??= {}; t[k.at(-1)] = v; }
function fmt(v, d = 1) { return v === null || v === undefined || !Number.isFinite(Number(v)) ? '—' : Number(v).toFixed(d); }
function status(msg, kind = '') { const n = $('#status'); n.textContent = msg; n.className = `status ${kind}`; }
async function api(path, body) {
  const r = await fetch(path, body ? {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)} : {});
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw Error(data.message || data.error || `HTTP ${r.status}`);
  return data;
}
function sizeCanvas(c) { const r = c.getBoundingClientRect(); c.width = Math.max(1, Math.round(r.width * dpr)); c.height = Math.max(1, Math.round(r.height * dpr)); }
function resize() { dpr = window.devicePixelRatio || 1; [canvas, chart, v25, netG, netC, admmC, hCellsC, hChartC].forEach(sizeCanvas); if (!userMoved) fit(); }

// ------------------------------------------------------------------ map transform
function fit() {
  if (!MAP) return;
  const [x0, y0, x1, y1] = MAP.bounds, w = canvas.clientWidth, h = canvas.clientHeight;
  view = {cx: (x0 + x1) / 2, cy: (y0 + y1) / 2, s: Math.min(w / (x1 - x0), h / (y1 - y0)) * 0.95};
}
const sx = (x) => canvas.clientWidth / 2 + (x - view.cx) * view.s;
const sy = (y) => canvas.clientHeight / 2 - (y - view.cy) * view.s;
const wx = (px) => view.cx + (px - canvas.clientWidth / 2) / view.s;
const wy = (py) => view.cy - (py - canvas.clientHeight / 2) / view.s;
function zoomAt(f, px = canvas.clientWidth / 2, py = canvas.clientHeight / 2) {
  userMoved = true;
  const ax = wx(px), ay = wy(py);
  view.s = Math.min(40, Math.max(0.03, view.s * f));
  view.cx = ax - (px - canvas.clientWidth / 2) / view.s;
  view.cy = ay + (py - canvas.clientHeight / 2) / view.s;
}
function worldTransform() { ctx.setTransform(dpr * view.s, 0, 0, -dpr * view.s, dpr * (canvas.clientWidth / 2 - view.cx * view.s), dpr * (canvas.clientHeight / 2 + view.cy * view.s)); }
function screenTransform(c = ctx) { c.setTransform(dpr, 0, 0, dpr, 0, 0); }
function linesPath(lines) { const p = new Path2D(); for (const l of lines) { p.moveTo(l[0][0], l[0][1]); for (let i = 1; i < l.length; i++) p.lineTo(l[i][0], l[i][1]); } return p; }

// ------------------------------------------------------------------ frame sampling
// frames may be unevenly spaced after thinning, so look them up by time
function indexAtTime(t) {
  let lo = 0, hi = frames.length - 1;
  if (t <= frames[0].t) return 0;
  if (t >= frames[hi].t) return hi;
  while (hi - lo > 1) { const m = (lo + hi) >> 1; if (frames[m].t <= t) lo = m; else hi = m; }
  return lo;
}
function frameAt(t) {
  if (!frames.length) return null;
  const i = indexAtTime(t), j = Math.min(frames.length - 1, i + 1);
  const span = frames[j].t - frames[i].t, a = span > 0 ? Math.min(1, Math.max(0, (t - frames[i].t) / span)) : 0;
  return {i, j, a, f0: frames[i], f1: frames[j]};
}
// compact v2 frame from the server -> the shape the renderer uses
function decodeFrame(r) {
  const ls = r.ls;
  if (r.new_flights?.length) appendFlights(r.new_flights);
  if (r.stats) lastStats = r.stats;
  if (r.prio) lastPrio = r.prio;
  if (r.h) lastH = r.h;
  if (r.hsel) for (const [id, d] of Object.entries(r.hsel)) (hselHist[id] ??= []).push({t: r.t, d});
  if (r.reroutes?.length) applyReroutes(r.reroutes);
  return {
    v: r.v, n: r.n, k: r.k, t: r.t, rho: r.rho, link_up: r.link_up, attack: r.attack, net: r.net, dtc: r.dtc,
    events: r.events || [], edges: r.edges || [], edges_total: r.edges_total ?? (r.edges || []).length,
    x: r.x.map((v) => v / 10), y: r.y.map((v) => v / 10), speed: r.spd.map((v) => v / 10), progress: r.prog.map((v) => v / 1000),
    layer: ls.map((v) => v & 7), status: ls.map((v) => v >> 3), stats: lastStats,
    admm: r.admm || null, prio: lastPrio, h: lastH, merge: r.merge || null, spoof: r.spoof || {}, trust: r.trust || {},
  };
}
// last ADMM negotiation per drone, kept outside the frames so browser thinning never loses it
function indexNeg(r) { for (const [id, v] of Object.entries(r.neg || {})) (negHist[id] ??= []).push(v); }
function lastNeg(id) { const h = negHist[id]; if (!h) return null; for (let i = h.length - 1; i >= 0; i--) if (h[i].t <= simT + 1e-6) return h[i]; return null; }
// browser memory cap: drop every other frame in the older half; events move to the next kept frame
function thinFrames() {
  const cap = LIMITS?.max_frames_in_memory ?? 6000;
  if (frames.length <= cap) return;
  const half = frames.length >> 1, kept = []; let carry = [], newLog = 0;
  frames.forEach((f, i) => {
    if (i < half && i % 2 === 1) { carry.push(...f.events); return; }
    if (carry.length) { f.events = carry.concat(f.events); carry = []; }
    if (i < logCursor) newLog++;
    kept.push(f);
  });
  frames = kept; logCursor = newLog; eventsIndexed = frames.length;  // all events were indexed on arrival
}
function posOf(s, n) {
  const {f0, f1, a} = s;
  if (f0.status[n] !== f1.status[n]) return [f0.x[n], f0.y[n]];
  return [f0.x[n] + (f1.x[n] - f0.x[n]) * a, f0.y[n] + (f1.y[n] - f0.y[n]) * a];
}
function headingOf(s, n) {
  const j = Math.min(frames.length - 1, s.i + 1), h = Math.max(0, s.i - 1);
  let dx = frames[j].x[n] - frames[h].x[n], dy = frames[j].y[n] - frames[h].y[n];
  if (Math.hypot(dx, dy) < 0.05) { const r = RUN.flights[n].route; dx = r.at(-1)[0] - r[0][0]; dy = r.at(-1)[1] - r[0][1]; }
  return Math.atan2(dy, dx);
}
function sectorOf(x, y) {
  const [x0, y0, x1, y1] = MAP.bounds;
  const c = Math.min(SECTOR_COLS - 1, Math.max(0, Math.floor((x - x0) / (x1 - x0) * SECTOR_COLS)));
  const r = Math.min(SECTOR_ROWS - 1, Math.max(0, Math.floor((y - y0) / (y1 - y0) * SECTOR_ROWS)));
  return r * SECTOR_COLS + c;
}
const idxOf = (id) => RUN.flights.findIndex((f) => f.id === id);

// ------------------------------------------------------------------ main map
function drawMap() {
  const w = canvas.clientWidth, h = canvas.clientHeight;
  screenTransform(); ctx.fillStyle = '#050c17'; ctx.fillRect(0, 0, w, h);
  if (!MAP) return;
  const s = RUN && frames.length ? frameAt(simT) : null;
  if (follow && s && selected !== null && s.f0.status[selected] === 1) { const p = posOf(s, selected); view.cx = p[0]; view.cy = p[1]; }
  const base = $('#tgContext').checked;
  if (base && backdropImg?.complete && MAP.backdrop) {
    const [x0, y0, x1, y1] = MAP.backdrop.bounds;
    ctx.globalAlpha = 0.9; ctx.drawImage(backdropImg, sx(x0), sy(y1), (x1 - x0) * view.s, (y1 - y0) * view.s); ctx.globalAlpha = 1;
    ctx.fillStyle = 'rgba(5,12,23,0.38)'; ctx.fillRect(0, 0, w, h);
  }
  // geofence
  ctx.strokeStyle = '#ff9f43aa'; ctx.setLineDash([7, 5]); ctx.lineWidth = 1.5; ctx.beginPath();
  if (MAP.geofence) MAP.geofence.forEach((p, i) => i ? ctx.lineTo(sx(p[0]), sy(p[1])) : ctx.moveTo(sx(p[0]), sy(p[1])));
  else { const [x0, y0, x1, y1] = MAP.bounds; ctx.rect(sx(x0), sy(y1), (x1 - x0) * view.s, (y1 - y0) * view.s); }
  ctx.closePath(); ctx.stroke(); ctx.setLineDash([]);

  worldTransform(); ctx.lineCap = 'round'; ctx.lineJoin = 'round';
  if (base && !MAP.backdrop) { ctx.strokeStyle = '#1d2f45'; ctx.lineWidth = 1 / view.s; ctx.stroke(ctxPaths.context); }
  const width = RUN?.limits.corridor_width ?? baseConfig?.corridors.width_meters ?? 20;
  ctx.strokeStyle = 'rgba(122,98,255,0.24)'; ctx.lineWidth = Math.max(width, 2.5 / view.s); ctx.stroke(ctxPaths.corridors);
  ctx.strokeStyle = 'rgba(190,165,255,0.75)'; ctx.lineWidth = 1 / view.s; ctx.stroke(ctxPaths.corridors);
  screenTransform();
  if ($('#tgSectors').checked) drawSectors();
  if (RUN && s && $('#tgRoutes').checked) { ctx.lineWidth = 1; RUN.flights.forEach((f, n) => { if (s.f0.status[n] !== 1) return; ctx.strokeStyle = COLORS[f.type] + '50'; drawRoute(f.route); }); }
  if (RUN && selected !== null) {
    const f = RUN.flights[selected];
    worldTransform(); ctx.strokeStyle = COLORS[f.type] + '40'; ctx.lineWidth = Math.max(RUN.limits.corridor_width, 3 / view.s); ctx.stroke(linesPath([f.route])); screenTransform();
    ctx.strokeStyle = '#ffffff'; ctx.lineWidth = 1.8; drawRoute(f.route);
  }
  drawVertiports(s);
  if (s) { drawJunctions(s); drawDrones(s); drawSpoof(s); }
}
// P3: junctions where a merge is in progress this frame (amber = gap rule blocking, drone slows by 1 - k_v)
function drawJunctions(s) {
  const js = s.f0.merge?.junctions; if (!js?.length) return;
  for (const [x, y, blocked] of js) {
    const X = sx(x), Y = sy(y); ctx.lineWidth = blocked ? 2.4 : 1.4;
    ctx.strokeStyle = blocked ? '#f6bd4b' : 'rgba(55,215,242,0.75)'; ctx.fillStyle = blocked ? 'rgba(246,189,75,0.18)' : 'rgba(55,215,242,0.08)';
    ctx.beginPath(); ctx.arc(X, Y, Math.max(7, 9 * Math.min(2, view.s)), 0, 7); ctx.fill(); ctx.stroke();
  }
}
// P5: for each airborne spoofer, the broadcast (false) position and the W-MSR estimate fused from the
// receivers' range-corrected positions; the drone glyph itself is the true position
function drawSpoof(s) {
  const sp = s.f0.spoof; if (!sp || !RUN) return;
  for (const [id, v] of Object.entries(sp)) {
    const n = idxOf(+id); if (n < 0 || s.f0.status[n] !== 1) continue;
    const t = posOf(s, n), T = [sx(t[0]), sy(t[1])], R = [sx(v.rep[0]), sy(v.rep[1])];
    ctx.strokeStyle = '#c084fc'; ctx.lineWidth = 1.4; ctx.setLineDash([4, 3]);
    ctx.beginPath(); ctx.moveTo(...T); ctx.lineTo(...R); ctx.stroke();
    ctx.beginPath(); ctx.arc(R[0], R[1], 7, 0, 7); ctx.stroke(); ctx.setLineDash([]);
    const label = (txt, X, Y, col) => { ctx.font = '600 10px system-ui'; ctx.lineWidth = 3; ctx.strokeStyle = '#050c17'; ctx.strokeText(txt, X, Y); ctx.fillStyle = col; ctx.fillText(txt, X, Y); };
    label(`D-${id} reported (${fmt(v.err_rep, 0)} m off)`, R[0] + 9, R[1] - 6, '#d8b4fe');
    if (v.est) {
      const E = [sx(v.est[0]), sy(v.est[1])];
      ctx.strokeStyle = '#2fe0a0'; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(E[0] - 5, E[1] - 5); ctx.lineTo(E[0] + 5, E[1] + 5); ctx.moveTo(E[0] + 5, E[1] - 5); ctx.lineTo(E[0] - 5, E[1] + 5); ctx.stroke();
      ctx.setLineDash([2, 3]); ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(...E); ctx.lineTo(...T); ctx.stroke(); ctx.setLineDash([]);
      label(`W-MSR est. (${fmt(v.err_est, 1)} m off, ${v.n} rcv)`, E[0] + 9, E[1] + 12, '#2fe0a0');
    }
  }
}
function drawRoute(route) { ctx.beginPath(); route.forEach((p, i) => i ? ctx.lineTo(sx(p[0]), sy(p[1])) : ctx.moveTo(sx(p[0]), sy(p[1]))); ctx.stroke(); }
function drawSectors() {
  const [x0, y0, x1, y1] = MAP.bounds;
  ctx.strokeStyle = '#3d6488'; ctx.lineWidth = 1; ctx.setLineDash([2, 6]);
  for (let c = 1; c < SECTOR_COLS; c++) { const x = x0 + (x1 - x0) * c / SECTOR_COLS; ctx.beginPath(); ctx.moveTo(sx(x), sy(y0)); ctx.lineTo(sx(x), sy(y1)); ctx.stroke(); }
  for (let r = 1; r < SECTOR_ROWS; r++) { const y = y0 + (y1 - y0) * r / SECTOR_ROWS; ctx.beginPath(); ctx.moveTo(sx(x0), sy(y)); ctx.lineTo(sx(x1), sy(y)); ctx.stroke(); }
  ctx.setLineDash([]); ctx.fillStyle = '#6f93b8'; ctx.font = '600 11px system-ui';
  for (let r = 0; r < SECTOR_ROWS; r++) for (let c = 0; c < SECTOR_COLS; c++)
    ctx.fillText(`S${r * SECTOR_COLS + c}`, sx(x0 + (x1 - x0) * c / SECTOR_COLS) + 6, sy(y0 + (y1 - y0) * (r + 1) / SECTOR_ROWS) + 14);
}
function drawVertiports(s) {
  const waiting = {}, landed = {};
  if (s && RUN) RUN.flights.forEach((f, n) => { const st = s.f0.status[n]; if (st === 0) waiting[f.origin] = (waiting[f.origin] || 0) + 1; if (st === 2) landed[f.destination] = (landed[f.destination] || 0) + 1; });
  for (const v of MAP.vertiports) {
    const px = sx(v.x), py = sy(v.y);
    ctx.strokeStyle = '#c9d8e8'; ctx.setLineDash([3, 3]); ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(px, py); ctx.lineTo(sx(v.jx), sy(v.jy)); ctx.stroke(); ctx.setLineDash([]);
    const r = 9, col = v.role === 'hospital' ? '#ff5f72' : v.role === 'depot' ? '#f6bd4b' : '#37d7f2';
    ctx.fillStyle = '#081525'; ctx.strokeStyle = col; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.rect(px - r, py - r, 2 * r, 2 * r); ctx.fill(); ctx.stroke();
    ctx.fillStyle = col; ctx.font = '700 11px system-ui'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText(v.role === 'hospital' ? '+' : v.role === 'depot' ? 'D' : 'H', px, py + 0.5);
    ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
    ctx.font = '600 11px system-ui'; ctx.lineWidth = 3; ctx.strokeStyle = '#050c17'; ctx.strokeText(v.name, px + 13, py - 3); ctx.fillStyle = '#eef5ff'; ctx.fillText(v.name, px + 13, py - 3);
    const q = waiting[v.id] || 0, l = landed[v.id] || 0;
    if (q || l) { const t = `${q ? q + ' queued' : ''}${q && l ? ' · ' : ''}${l ? l + ' landed' : ''}`; ctx.font = '10.5px system-ui'; ctx.strokeText(t, px + 13, py + 10); ctx.fillStyle = '#b8c7d8'; ctx.fillText(t, px + 13, py + 10); }
  }
}
function drawDrones(s) {
  const f0 = s.f0, n = RUN.flights.length, dmin = RUN.limits.d_min, mal = new Set(f0.attack ? RUN.attack.malicious_ids : []);
  const pos = []; for (let k = 0; k < n; k++) pos.push(f0.status[k] === 1 ? posOf(s, k) : null);
  if ($('#tgLinks').checked && f0.edges) { ctx.strokeStyle = 'rgba(55,215,242,0.35)'; ctx.lineWidth = 1; ctx.beginPath(); for (const [a, b] of f0.edges) { if (!pos[a] || !pos[b]) continue; ctx.moveTo(sx(pos[a][0]), sy(pos[a][1])); ctx.lineTo(sx(pos[b][0]), sy(pos[b][1])); } ctx.stroke(); }
  ctx.setLineDash([4, 3]); ctx.lineWidth = 1.6;
  for (let a = 0; a < n; a++) { if (!pos[a]) continue; for (let b = a + 1; b < n; b++) {
    if (!pos[b] || f0.layer[a] !== f0.layer[b]) continue;
    const d = Math.hypot(pos[a][0] - pos[b][0], pos[a][1] - pos[b][1]);
    if (d < 1.5 * dmin) { ctx.strokeStyle = d < dmin ? '#ff5f72' : '#f6bd4bcc'; ctx.beginPath(); ctx.moveTo(sx(pos[a][0]), sy(pos[a][1])); ctx.lineTo(sx(pos[b][0]), sy(pos[b][1])); ctx.stroke(); }
  } }
  ctx.setLineDash([]);
  const trailStart = indexAtTime(f0.t - 6);
  for (let k = 0; k < n; k++) {
    if (!pos[k]) continue; const dim = layerFilter !== 'all' && f0.layer[k] !== Number(layerFilter);
    ctx.strokeStyle = COLORS[RUN.flights[k].type] + (dim ? '18' : '70'); ctx.lineWidth = 1.3; ctx.beginPath(); let started = false;
    for (let i = trailStart; i <= s.i; i++) { if (frames[i].status[k] !== 1) continue; const X = sx(frames[i].x[k]), Y = sy(frames[i].y[k]); started ? ctx.lineTo(X, Y) : ctx.moveTo(X, Y); started = true; }
    if (started) { ctx.lineTo(sx(pos[k][0]), sy(pos[k][1])); ctx.stroke(); }
  }
  const size = Math.max(5, Math.min(10, 3.5 + view.s * 5));
  for (let k = 0; k < n; k++) {
    const st = f0.status[k];
    if (st === 4) { // forced landing in place
      const X = sx(f0.x[k]), Y = sy(f0.y[k]); ctx.strokeStyle = '#ff8a4c'; ctx.lineWidth = 2.2;
      ctx.beginPath(); ctx.arc(X, Y, 7, 0, 7); ctx.moveTo(X - 5, Y + 5); ctx.lineTo(X + 5, Y - 5); ctx.stroke();
      ctx.fillStyle = '#ffb38a'; ctx.font = '700 10px system-ui'; ctx.fillText(`FORCED D-${RUN.flights[k].id}`, X + 9, Y - 6); continue;
    }
    if (st === 3) { // crash marker
      const X = sx(f0.x[k]), Y = sy(f0.y[k]); ctx.strokeStyle = '#ff2f4a'; ctx.lineWidth = 3;
      ctx.beginPath(); ctx.moveTo(X - 7, Y - 7); ctx.lineTo(X + 7, Y + 7); ctx.moveTo(X + 7, Y - 7); ctx.lineTo(X - 7, Y + 7); ctx.stroke();
      ctx.fillStyle = '#ff5f72'; ctx.font = '700 10px system-ui'; ctx.fillText(`CRASH D-${RUN.flights[k].id}`, X + 9, Y - 6); continue;
    }
    if (!pos[k]) continue;
    const f = RUN.flights[k], L = f0.layer[k], dim = layerFilter !== 'all' && L !== Number(layerFilter);
    const X = sx(pos[k][0]), Y = sy(pos[k][1]), hd = headingOf(s, k), r = size * (0.85 + 0.12 * L);
    ctx.save(); ctx.translate(X, Y); ctx.rotate(-hd); ctx.globalAlpha = dim ? 0.18 : 1;
    ctx.fillStyle = COLORS[f.type]; ctx.strokeStyle = '#03070d'; ctx.lineWidth = 1.2;
    ctx.beginPath(); ctx.moveTo(r * 1.35, 0); ctx.lineTo(-r * 0.8, r * 0.75); ctx.lineTo(-r * 0.35, 0); ctx.lineTo(-r * 0.8, -r * 0.75); ctx.closePath(); ctx.fill(); ctx.stroke();
    ctx.restore();
    if (!dim && view.s > 0.45) { ctx.font = '9.5px ui-monospace,monospace'; ctx.lineWidth = 3; ctx.strokeStyle = '#050c17'; ctx.strokeText(`L${L}`, X + r + 2, Y - r); ctx.fillStyle = '#e6f0fa'; ctx.fillText(`L${L}`, X + r + 2, Y - r); }
    const hb = f0.h?.bms?.[k] ?? 0, hs = f0.h?.soc?.[k];
    if (!dim && hb > 0) { ctx.strokeStyle = BMS_COL[hb]; ctx.lineWidth = hb >= 2 ? 2.4 : 1.6; ctx.beginPath(); ctx.arc(X, Y, r + 3.5, 0, 7); ctx.stroke(); }
    if (!dim && hs !== undefined && hs < 30) { // low-battery glyph
      ctx.fillStyle = '#050c17'; ctx.fillRect(X - r - 12, Y - 4, 9, 6); ctx.strokeStyle = hs < 15 ? '#ff3b5c' : '#f6bd4b'; ctx.lineWidth = 1; ctx.strokeRect(X - r - 12, Y - 4, 9, 6);
      ctx.fillStyle = ctx.strokeStyle; ctx.fillRect(X - r - 11, Y - 3, Math.max(1, 7 * hs / 100), 4); ctx.fillRect(X - r - 3, Y - 2, 1.5, 2);
    }
    if (mal.has(f.id)) { ctx.strokeStyle = '#c084fc'; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(X, Y, r + 5 + 2 * Math.sin(performance.now() / 180), 0, 7); ctx.stroke(); }
    if (k === selected) { ctx.strokeStyle = '#fff'; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(X, Y, r + 8, 0, 7); ctx.stroke();
      ctx.font = '700 11.5px system-ui'; ctx.lineWidth = 3; ctx.strokeStyle = '#050c17'; ctx.strokeText(`D-${f.id} ${TYPE_SHORT[f.type]}`, X + r + 10, Y + 4); ctx.fillStyle = '#fff'; ctx.fillText(`D-${f.id} ${TYPE_SHORT[f.type]}`, X + r + 10, Y + 4); }
  }
}

// ------------------------------------------------------------------ 2.5D view of the selected drone
function draw25(s) {
  const w = v25.clientWidth, h = v25.clientHeight; screenTransform(vctx); vctx.clearRect(0, 0, w, h);
  if (w < 40 || h < 40) return;   // Health tab open: the 2.5D view is hidden
  if (!RUN || !s || selected === null) { vctx.fillStyle = '#5c7088'; vctx.font = '12px system-ui'; vctx.fillText('Select a drone on the map or network graph.', 12, 24); return; }
  const f0 = s.f0, n = selected, L = RUN.limits.num_layers, H = RUN.limits.layer_height, st = f0.status[n];
  const c = st === 1 ? posOf(s, n) : [f0.x[n], f0.y[n]];
  const R = 120, zk = Math.max(18, Math.min(34, (h * 0.42) / Math.max(1, L)));
  const k = Math.min((w - 70) / (2.8 * R), (h - 40 - L * zk) / (1.44 * R));
  const ox = w / 2 - 20, oy = h - 24 - 0.72 * R * k;
  const P = (x, y, layer) => { const dx = x - c[0], dy = y - c[1]; return [ox + (dx - dy) * 0.70 * k, oy - (dx + dy) * 0.36 * k - (layer + 1) * zk]; };
  const G = (x, y) => { const dx = x - c[0], dy = y - c[1]; return [ox + (dx - dy) * 0.70 * k, oy - (dx + dy) * 0.36 * k]; };
  const inWin = (x, y) => Math.abs(x - c[0]) < R && Math.abs(y - c[1]) < R;
  // ground diamond + corridor centrelines
  const corner = (dx, dy) => G(c[0] + dx, c[1] + dy);
  vctx.fillStyle = '#0a1726'; vctx.strokeStyle = '#1e3550'; vctx.lineWidth = 1; vctx.beginPath();
  [[-R, -R], [R, -R], [R, R], [-R, R]].forEach(([a, b], i) => { const p = corner(a, b); i ? vctx.lineTo(...p) : vctx.moveTo(...p); }); vctx.closePath(); vctx.fill(); vctx.stroke();
  vctx.strokeStyle = 'rgba(169,139,255,0.55)'; vctx.lineWidth = 1;
  for (const line of MAP.corridors) for (let i = 1; i < line.length; i++) {
    const a = line[i - 1], b = line[i]; if (!inWin(a[0], a[1]) && !inWin(b[0], b[1])) continue;
    vctx.beginPath(); vctx.moveTo(...G(Math.max(c[0] - R, Math.min(c[0] + R, a[0])), Math.max(c[1] - R, Math.min(c[1] + R, a[1])))); vctx.lineTo(...G(Math.max(c[0] - R, Math.min(c[0] + R, b[0])), Math.max(c[1] - R, Math.min(c[1] + R, b[1])))); vctx.stroke();
  }
  for (const v of MAP.vertiports) if (inWin(v.x, v.y)) { const p = G(v.x, v.y); vctx.fillStyle = '#e8f2ff'; vctx.fillRect(p[0] - 4, p[1] - 3, 8, 6); vctx.font = '9px system-ui'; vctx.fillText(v.name, p[0] + 6, p[1] + 3); }
  // layer planes
  for (let l = 0; l < L; l++) {
    vctx.fillStyle = l === RUN.limits.emergency_layer ? 'rgba(255,95,114,0.06)' : 'rgba(55,215,242,0.05)';
    vctx.strokeStyle = l === f0.layer[n] ? 'rgba(255,255,255,0.45)' : 'rgba(110,150,190,0.25)';
    vctx.beginPath(); [[-R, -R], [R, -R], [R, R], [-R, R]].forEach(([a, b], i) => { const p = P(c[0] + a, c[1] + b, l); i ? vctx.lineTo(...p) : vctx.moveTo(...p); }); vctx.closePath(); vctx.fill(); vctx.stroke();
    const lab = P(c[0] + R, c[1] - R, l); vctx.fillStyle = l === f0.layer[n] ? '#e6f0fa' : '#8fa3ba'; vctx.font = '10px ui-monospace,monospace';
    vctx.fillText(`L${l} ${(l + 1) * H}m${l === RUN.limits.emergency_layer ? '⚕' : ''}`, lab[0] + 4, lab[1] + 3);
  }
  // selected route on its layer
  const f = RUN.flights[n]; vctx.strokeStyle = COLORS[f.type] + 'aa'; vctx.lineWidth = 1.5; vctx.setLineDash([5, 4]); vctx.beginPath(); let on = false;
  for (const p of f.route) { if (!inWin(p[0], p[1])) { on = false; continue; } const q = P(p[0], p[1], f0.layer[n]); on ? vctx.lineTo(...q) : vctx.moveTo(...q); on = true; } vctx.stroke(); vctx.setLineDash([]);
  // drones in window (sorted back-to-front)
  const list = [];
  RUN.flights.forEach((g, m) => { const sm = f0.status[m]; if (sm !== 1 && sm !== 3 && m !== n) return; const p = sm === 1 ? posOf(s, m) : [f0.x[m], f0.y[m]]; if (inWin(p[0], p[1])) list.push([m, p]); });
  list.sort((a, b) => (b[1][0] + b[1][1]) - (a[1][0] + a[1][1]));
  for (const [m, p] of list) {
    const g = RUN.flights[m], lay = f0.layer[m], top = P(p[0], p[1], lay), gr = G(p[0], p[1]), sel = m === n, crashed = f0.status[m] === 3;
    vctx.strokeStyle = sel ? '#ffffffaa' : '#ffffff30'; vctx.lineWidth = 1; vctx.setLineDash([2, 3]); vctx.beginPath(); vctx.moveTo(...gr); vctx.lineTo(...top); vctx.stroke(); vctx.setLineDash([]);
    vctx.fillStyle = '#00000080'; vctx.beginPath(); vctx.ellipse(gr[0], gr[1], 4, 2, 0, 0, 7); vctx.fill();
    if (sel) { vctx.strokeStyle = '#ffffff70'; vctx.beginPath(); vctx.ellipse(top[0], top[1], RUN.limits.d_min * 0.99 * k, RUN.limits.d_min * 0.51 * k, 0, 0, 7); vctx.stroke(); }
    if (crashed) { vctx.strokeStyle = '#ff2f4a'; vctx.lineWidth = 2.5; vctx.beginPath(); vctx.moveTo(gr[0] - 6, gr[1] - 6); vctx.lineTo(gr[0] + 6, gr[1] + 6); vctx.moveTo(gr[0] + 6, gr[1] - 6); vctx.lineTo(gr[0] - 6, gr[1] + 6); vctx.stroke(); continue; }
    vctx.fillStyle = COLORS[g.type]; vctx.strokeStyle = sel ? '#fff' : '#03070d'; vctx.lineWidth = sel ? 2 : 1;
    vctx.beginPath(); vctx.arc(top[0], top[1], sel ? 6.5 : 4.5, 0, 7); vctx.fill(); vctx.stroke();
    if (sel && f0.status[m] === 1) { const hd = headingOf(s, m), tip = P(p[0] + Math.cos(hd) * 22, p[1] + Math.sin(hd) * 22, lay); vctx.strokeStyle = '#fff'; vctx.lineWidth = 2; vctx.beginPath(); vctx.moveTo(...top); vctx.lineTo(...tip); vctx.stroke(); }
    vctx.fillStyle = sel ? '#fff' : '#b8c7d8'; vctx.font = sel ? '700 11px system-ui' : '9.5px system-ui'; vctx.fillText(`D-${g.id}`, top[0] + 7, top[1] - 6);
  }
  vctx.fillStyle = '#5c7088'; vctx.font = '10px system-ui'; vctx.fillText(`${2 * R} m window · ring = d_min · stems to ground`, 8, h - 6);
  if (st !== 1) { vctx.fillStyle = st === 3 ? '#ff5f72' : '#8fa3ba'; vctx.font = '600 12px system-ui'; vctx.fillText(st === 3 ? 'CRASHED' : st === 0 ? 'On the pad — waiting to depart' : 'Landed', 10, 18); }
}

// ------------------------------------------------------------------ panels
function updatePanels() {
  if (!RUN || !frames.length) return;
  const s = frameAt(simT), f = s.f0, st = f.stats;
  const cnt = [0, 0, 0, 0, 0]; f.status.forEach((x) => cnt[x]++);
  $('#cntQueue').textContent = cnt[0]; $('#cntAir').textContent = cnt[1]; $('#cntLand').textContent = cnt[2]; $('#cntCrash').textContent = cnt[3]; $('#cntForced').textContent = cnt[4];
  if (st.delivered !== undefined) {
    $('#kEnergy').textContent = st.energy_per_delivered_wh === null ? '—' : `${fmt(st.energy_per_delivered_wh, 0)} Wh`;
    $('#kEnergySub').textContent = `${st.delivered} delivered · fleet ${fmt(st.energy_used_wh / 1000, 2)} kWh · max pack ${fmt(st.max_pack_c, 0)} °C`;
    $('#kBatt').textContent = `${st.diversions} · ${st.forced_landings}`;
    $('#kBattCard').classList.toggle('bad', st.energy_depleted > 0 || st.forced_landings > 0);
    $('#kBattSub').textContent = `diversions · forced · ${st.energy_depleted} depleted · ${st.grounded_preflight} grounded pre-flight`;
  }
  $('#clock').textContent = `${fmt(f.t)} s`; $('#tLabel').textContent = `t = ${fmt(simT)} s`;
  const scrub = $('#scrub'); scrub.max = String(RUN.duration_s); if (document.activeElement !== scrub) scrub.value = String(simT);
  const dtcOn = RUN.switches.use_overseer;
  $('#linkState').textContent = !dtcOn ? 'OFF' : f.link_up ? 'UP' : 'DOWN'; $('#linkChip').classList.toggle('bad', dtcOn && !f.link_up);
  $('#kCrash').textContent = st.crashes; $('#kCrashCard').classList.toggle('bad', st.crashes > 0); $('#kCrashCard').classList.toggle('good', st.crashes === 0);
  $('#kCrashSub').textContent = st.crashes ? `${st.crashed_drones} drones lost` : 'collisions (< 2 m)';
  $('#kLos').textContent = st.near_misses; $('#kLosCard').classList.toggle('bad', st.near_misses > 0);
  $('#kSep').textContent = st.min_separation_m === null ? '—' : `${fmt(st.min_separation_m, 2)} m`;
  $('#kSepSub').innerHTML = `required ≥ ${RUN.limits.d_min} m · now ${f.rho === null ? '—' : fmt(f.rho + RUN.limits.d_min, 1) + ' m'}`;
  $('#kViol').textContent = st.safety_violation_ticks; $('#kViolCard').classList.toggle('bad', st.safety_violation_ticks > 0); $('#kViolCard').classList.toggle('good', st.safety_violation_ticks === 0);
  const ar = f.admm?.run;
  $('#kAdmm').textContent = st.admm_events;
  $('#kAdmmSub').textContent = !RUN.switches.use_admm ? (RUN.architecture === 'centralized' ? 'centralized: no ADMM' : 'ADMM disabled')
    : `p95 ${fmt(ar?.it_p95, 0)} it · ${fmt(ar?.ms_p95, 2)} ms · ${st.admm_nonconverged} fallback`;
  const pr = f.prio;
  if (pr && pr.count) {
    $('#kPrio').textContent = pr.rate === null ? '—' : `${fmt(pr.rate * 100, 0)}%`;
    $('#kPrioCard').classList.toggle('good', pr.rate === 1); $('#kPrioCard').classList.toggle('bad', pr.rate !== null && pr.rate < 0.9);
    $('#kPrioSub').textContent = `${pr.count} EMG · delay ${pr.mean_delay_s === null ? '—' : fmt(pr.mean_delay_s) + ' s'} (${pr.arrived} landed) · ${pr.yields} yields`;
  } else { $('#kPrio').textContent = '—'; $('#kPrioSub').textContent = 'no emergency flights'; $('#kPrioCard').classList.remove('good', 'bad'); }
  const mg = f.merge;
  if (mg) {
    $('#kMerge').textContent = mg.rate === null ? '—' : `${fmt(mg.rate * 100, 0)}%`;
    $('#kMergeSub').textContent = `${mg.attempts} attempts · ${mg.yield_ticks} gap-yield ticks · ${mg.platoons} platoons${mg.headway_s !== null ? ' · headway ' + fmt(mg.headway_s) + ' s' : ''}`;
  } else { $('#kMerge').textContent = '—'; $('#kMergeSub').textContent = RUN.architecture === 'centralized' ? 'centralized: DTC commands velocities' : 'P3 merging off'; }
  $('#kShift').textContent = st.tactical_layer_shifts;
  $('#kLayer').textContent = st.dtc_directives; $('#kLayerSub').textContent = dtcOn ? `${st.layer_changes} layer changes · ${st.layer_changes_deferred} gated` : 'DTC disabled';
  $('#kTube').textContent = st.tube_corrections; $('#kTubeSub').textContent = `max lateral ${fmt(st.max_lateral_error_m)} / ${RUN.limits.corridor_width / 2} m · geofence ${st.geofence_corrections}`;
  const undefended = (RUN.attack.enabled || RUN.flights.some((x) => x.malicious)) && !RUN.switches.defended;
  $('#kRepLabel').textContent = undefended ? 'Spoofed reports accepted' : 'Spoofed reports filtered';
  $('#kRepCard').classList.toggle('bad', undefended && st.spoofed_reports_accepted > 0);
  $('#kRep').textContent = undefended ? st.spoofed_reports_accepted : st.reports_dropped;
  const spoofers = [...new Set([...(RUN.attack.enabled ? RUN.attack.malicious_ids : []), ...RUN.flights.filter((x) => x.malicious).map((x) => x.id)])];
  $('#kRepSub').textContent = spoofers.length ? (undefended ? 'defence OFF — fed into separation' : `${spoofers.map((i) => 'D-' + i).join(', ')} spoofing`) : 'no attack injected';
  $('#kArr').textContent = st.arrivals; $('#kArrSub').textContent = `of ${RUN.flights.length} flights`;
  $('#runState').textContent = RUN.replay ? 'LOADED' : done && simT >= frames.at(-1).t - 1e-6 ? 'COMPLETE' : done ? 'REPLAY' : 'LIVE';
  updateOccupancy(s); updateDrone(s); pumpLog(); updateFleetHealth(s); if (dTab === 'hl') updateHealthTab(s);
  const canInject = !RUN.replay && !done; if ($('#cdNow').disabled === canInject) $('#cdNow').disabled = !canInject;
}
function updateOccupancy(s) {
  const L = RUN.limits.num_layers, cap = RUN.limits.capacity, occ = Array.from({length: SECTOR_COLS * SECTOR_ROWS}, () => Array(L).fill(0));
  RUN.flights.forEach((_, n) => { if (s.f0.status[n] === 1) occ[sectorOf(s.f0.x[n], s.f0.y[n])][s.f0.layer[n]]++; });
  let html = '<tr><th>Sector</th>' + Array.from({length: L}, (_, l) => `<th>L${l}${l === RUN.limits.emergency_layer ? ' ⚕' : ''}</th>`).join('') + '</tr>';
  occ.forEach((row, sid) => { html += `<tr><td>S${sid}</td>` + row.map((v) => { const u = v / cap, bg = v === 0 ? 'transparent' : u >= 1 ? '#5a1a26' : u > 0.6 ? '#4a3a12' : '#103347'; return `<td style="background:${bg}">${v}</td>`; }).join('') + '</tr>'; });
  $('#occ').innerHTML = html; $('#capLabel').textContent = `capacity ${cap} per cell · ⚕ emergency`;
}
function updateDrone(s) {
  if (selected === null) return;
  const f = RUN.flights[selected], n = selected, fr = s.f0, st = fr.status[n] ?? 0;
  if (fr.status[n] === undefined) { $('#dName').textContent = `D-${f.id}`; $('#dStatus').textContent = 'NOT YET ADDED'; return; }
  if ($('#dronePick').value !== String(n)) $('#dronePick').value = String(n);
  $('#dBadge').textContent = f.type; $('#dBadge').style.color = COLORS[f.type];
  $('#dName').textContent = `D-${f.id}`;
  const hb = fr.h?.bms?.[n] ?? 0; $('#dHealthDot').className = `hdot s${hb}`;
  const pill = $('#dStatus'); pill.textContent = STATUS[st].toUpperCase(); pill.className = `pill ${['', 'air', 'landed', 'crashed', 'crashed'][st]}`;
  $('#dTask').textContent = `${f.task} · P${f.priority} · departs ${f.depart_s}s`;
  $('#dProg').style.width = `${Math.round(fr.progress[n] * 100)}%`; $('#dProg').style.background = COLORS[f.type];
  $('#dRoute').textContent = `${f.origin_name || f.origin} → ${f.destination_name || f.destination}`;
  $('#dLayer').textContent = `L${fr.layer[n]} · ≈${(fr.layer[n] + 1) * RUN.limits.layer_height} m AGL`;
  const hd = st === 1 ? ((90 - headingOf(s, n) * 180 / Math.PI) % 360 + 360) % 360 : null;
  $('#dSpeed').textContent = st === 1 ? `${fmt(fr.speed[n])} m/s · ${fmt(hd, 0)}°` : '—';
  const rem = f.route_length_m * (1 - fr.progress[n]);
  $('#dEta').textContent = st === 1 ? `${(rem / 1000).toFixed(2)} km · ${fr.speed[n] > 0.5 ? fmt(rem / Math.max(fr.speed[n], 1), 0) + ' s' : 'holding'}` : st === 2 ? 'arrived' : st === 3 ? 'lost' : `${(f.route_length_m / 1000).toFixed(2)} km planned`;
  let best = Infinity, who = null;
  if (st === 1) fr.status.forEach((x, k) => { if (x === 1 && k !== n && fr.layer[k] === fr.layer[n]) { const d = Math.hypot(fr.x[k] - fr.x[n], fr.y[k] - fr.y[n]); if (d < best) { best = d; who = k; } } });
  $('#dNear').textContent = Number.isFinite(best) ? `${fmt(best)} m · D-${RUN.flights[who].id}` : '—';
  const deg = (fr.edges || []).reduce((a, [p, q]) => a + (p === n || q === n), 0);
  $('#dDeg').textContent = st === 1 ? `${deg}${fr.net?.hub === f.id ? ' · network hub' : ''}` : '—';
  $('#dDtc').textContent = !RUN.switches.use_overseer ? 'no DTC' : st !== 1 ? '—' : fr.dtc?.link_up ? `connected · directive age ${fmt(fr.dtc.staleness_s)} s` : `LOST · holding directive from ${fmt(fr.dtc?.staleness_s)} s ago`;
  const ev = (droneEvents[f.id] || []).filter((e) => e.t <= simT + 1e-6);
  const c = (k) => ev.filter((e) => k.includes(e.kind)).length;
  $('#dCounts').textContent = `${c(['admm'])} · ${c(['shift'])} · ${c(['los', 'gate', 'wall', 'spoof', 'defend'])}`;
  const ng = lastNeg(f.id);
  $('#dNeg').textContent = !RUN.switches.use_admm ? 'ADMM off' : ng ? `t ${fmt(ng.t)} s · with ${ng.partners.slice(0, 4).map((x) => 'D-' + x).join(', ') || '—'} · ${ng.it ?? '?'} it · ${ng.ok ? 'converged' : 'fallback'}` : 'none yet';
  const ep = fr.prio?.per?.[f.id];
  $('#dPrioLbl').hidden = $('#dPrio').hidden = !ep;
  if (ep) {
    const elapsed = st === 1 ? fr.t - f.depart_s : null;
    const delay = ep.delay_s !== null ? `delay ${fmt(ep.delay_s)} s vs nominal ${fmt(ep.nominal_s)} s` : elapsed !== null ? `${fmt(elapsed, 0)} s elapsed · nominal ${fmt(ep.nominal_s)} s` : `nominal ${fmt(ep.nominal_s)} s`;
    $('#dPrio').textContent = `${delay} · ${ep.yields} yields (${ep.holds} hold, ${ep.shifts} shift, ${ep.gated} gated) · reserved layer ${ep.on_layer === null ? '—' : fmt(ep.on_layer * 100, 0) + '%'} · compliance ${ep.compliance === null ? '—' : fmt(ep.compliance * 100, 0) + '%'}`;
  }
  const tr = fr.trust?.[f.id], sp = fr.spoof?.[f.id];
  if (sp) $('#dTrust').textContent = `SPOOFER · broadcasts ${fmt(sp.err_rep, 0)} m off · W-MSR estimate ${sp.est ? fmt(sp.err_est, 1) + ' m off (' + sp.n + ' receivers)' : 'none (no same-layer receiver)'}`;
  else if (tr) $('#dTrust').textContent = tr.map(([id, k]) => `D-${id} ${k}`).join(' · ');
  else $('#dTrust').textContent = st !== 1 ? '—' : RUN.attack.enabled ? (RUN.switches.defended ? 'all kept (range-consistent)' : 'defence off — used as received') : 'all kept (no attack)';
  const key = `${f.id}:${ev.length}`;
  if (key !== lastDroneFeedKey) {
    lastDroneFeedKey = key; const list = $('#dEvents'); list.replaceChildren();
    if (!ev.length) { const li = document.createElement('li'); li.className = 'empty'; li.textContent = 'No events yet for this drone.'; list.append(li); }
    for (const e of ev.slice(-60).reverse()) { const li = document.createElement('li'); li.className = `${e.kind}${e.severity ? ' sev-' + e.severity : ''}`; li.innerHTML = `<time>${fmt(e.t)}s</time><span></span>`; li.lastChild.textContent = e.text; list.append(li); }
    $('#dEvCount').textContent = `${ev.length} event${ev.length === 1 ? '' : 's'}`;
  }
}
function pumpLog() {
  const list = $('#log'); let added = false;
  while (logCursor < frames.length && frames[logCursor].t <= simT + 1e-6) {
    for (const e of frames[logCursor].events) {
      if (e.scope !== 'global' || shownEvents.has(e)) continue;
      shownEvents.add(e);
      if ((e.kind === 'depart' || e.kind === 'hold' || e.kind === 'land') && RUN.flights.length > 40 && RUN.flights[idxOf(e.id)]?.type !== 'EMERGENCY') continue;
      const li = document.createElement('li'); li.className = `${e.kind}${e.severity ? ' sev-' + e.severity : ''}`;
      li.innerHTML = `<time>${fmt(e.t)}s</time><span></span>`; li.lastChild.textContent = e.text;
      if (e.ids?.length) { li.style.cursor = 'pointer'; li.onclick = () => select(idxOf(e.ids[0])); }
      list.prepend(li); logTotal++; added = true;
    }
    logCursor++;
  }
  while (list.children.length > 150) list.lastElementChild.remove();
  if (added) $('#logCount').textContent = `${logTotal} events`;
}
function resetLog() { $('#log').replaceChildren(); logCursor = 0; logTotal = 0; shownEvents = new WeakSet(); $('#logCount').textContent = '0 events'; lastDroneFeedKey = ''; }
function indexEvents() {
  for (; eventsIndexed < frames.length; eventsIndexed++) for (const e of frames[eventsIndexed].events) {
    if (e.scope === 'none') { (droneEvents[e.ids[0]] ??= []).push(e); continue; }
    const owners = e.scope === 'global' ? (e.ids || []) : (e.ids?.length ? [e.ids[0]] : []);
    for (const id of owners) (droneEvents[id] ??= []).push(e);
  }
}
function select(n) { if (n === null || n < 0 || !RUN) return; selected = n; lastDroneFeedKey = ''; }

// ------------------------------------------------------------------ STL chart
function drawChart() {
  const w = chart.clientWidth, h = chart.clientHeight; screenTransform(cctx); cctx.clearRect(0, 0, w, h);
  if (!RUN || !frames.length) { cctx.fillStyle = '#5c7088'; cctx.font = '12px system-ui'; cctx.fillText('Launch a simulation to monitor G(d ≥ d_min).', 12, 24); return; }
  const L = 36, R = w - 10, T = 10, B = h - 22, lo = -RUN.limits.d_min, hi = 40;
  const X = (t) => L + (t / RUN.duration_s) * (R - L), Y = (v) => B - (Math.max(lo, Math.min(hi, v)) - lo) / (hi - lo) * (B - T);
  cctx.strokeStyle = '#16283e'; cctx.lineWidth = 1; cctx.fillStyle = '#5c7088'; cctx.font = '10px system-ui';
  for (const v of [lo, 0, 10, 20, 30, 40]) { cctx.beginPath(); cctx.moveTo(L, Y(v)); cctx.lineTo(R, Y(v)); cctx.stroke(); cctx.fillText(String(v), 6, Y(v) + 3); }
  cctx.fillStyle = 'rgba(255,95,114,0.08)'; cctx.fillRect(L, Y(0), R - L, B - Y(0));
  shadeEvents(cctx, X, T, B);
  cctx.strokeStyle = '#ff5f72aa'; cctx.setLineDash([4, 4]); cctx.beginPath(); cctx.moveTo(L, Y(0)); cctx.lineTo(R, Y(0)); cctx.stroke(); cctx.setLineDash([]);
  cctx.lineWidth = 1.6; cctx.beginPath(); let pen = false, worst = Infinity;
  for (const f of frames) { if (f.rho === null) { pen = false; continue; } worst = Math.min(worst, f.rho); pen ? cctx.lineTo(X(f.t), Y(f.rho)) : cctx.moveTo(X(f.t), Y(f.rho)); pen = true; }
  cctx.strokeStyle = worst < 0 ? '#ff5f72' : '#2fe0a0'; cctx.stroke();
  for (const f of frames) for (const e of f.events) if (e.kind === 'crash') { cctx.fillStyle = '#ff2f4a'; cctx.font = '700 12px system-ui'; cctx.fillText('✕', X(e.t) - 4, B - 2); }
  cctx.strokeStyle = '#e6f0fa'; cctx.lineWidth = 1; cctx.beginPath(); cctx.moveTo(X(simT), T); cctx.lineTo(X(simT), B); cctx.stroke();
  cctx.fillStyle = '#5c7088'; cctx.fillText('0 s', L, h - 6); cctx.textAlign = 'right'; cctx.fillText(`${RUN.duration_s} s`, R, h - 6); cctx.textAlign = 'left';
}
function shadeEvents(c, X, T, B) {
  if (RUN.outage.enabled) { c.fillStyle = 'rgba(169,139,255,0.10)'; c.fillRect(X(RUN.outage.start_s), T, X(RUN.outage.end_s) - X(RUN.outage.start_s), B - T); c.fillStyle = '#a98bff'; c.font = '10px system-ui'; c.fillText('DTC link down', X(RUN.outage.start_s) + 4, T + 10); }
  if (RUN.attack.enabled) { c.strokeStyle = '#c084fc'; c.setLineDash([3, 3]); c.beginPath(); c.moveTo(X(RUN.attack.start_s), T); c.lineTo(X(RUN.attack.start_s), B); c.stroke(); c.setLineDash([]); c.fillStyle = '#c084fc'; c.font = '10px system-ui'; c.fillText('attack', X(RUN.attack.start_s) + 4, B - 4); }
}

// ------------------------------------------------------------------ network theory panel
function drawNetwork(s) {
  const w = netG.clientWidth, h = netG.clientHeight; screenTransform(nctx); nctx.clearRect(0, 0, w, h);
  netPositions = null;
  if (!RUN || !s) { nctx.fillStyle = '#5c7088'; nctx.font = '12px system-ui'; nctx.fillText('Network appears once drones are airborne.', 12, 24); return; }
  const f0 = s.f0, [x0, y0, x1, y1] = MAP.bounds, pad = 16, top = 46;
  const k = Math.min((w - 2 * pad) / (x1 - x0), (h - top - pad) / (y1 - y0));
  const ox = (w - (x1 - x0) * k) / 2, oy = top + (h - top - pad - (y1 - y0) * k) / 2;
  const P = (x, y) => [ox + (x - x0) * k, oy + (y1 - y) * k];
  const hub = [w / 2, 20], dtc = f0.dtc || {}, linkUp = RUN.switches.use_overseer && dtc.link_up;
  const pos = RUN.flights.map((_, n) => f0.status[n] === 1 ? P(...posOf(s, n)) : null);
  netPositions = pos;
  // campus outline
  if (MAP.geofence) { nctx.strokeStyle = '#1e3550'; nctx.lineWidth = 1; nctx.beginPath(); MAP.geofence.forEach((p, i) => i ? nctx.lineTo(...P(p[0], p[1])) : nctx.moveTo(...P(p[0], p[1]))); nctx.closePath(); nctx.stroke(); }
  // DTC -> drone directive links
  if (RUN.switches.use_overseer) {
    nctx.lineWidth = 0.7; nctx.strokeStyle = linkUp ? 'rgba(169,139,255,0.22)' : 'rgba(255,95,114,0.28)'; if (!linkUp) nctx.setLineDash([3, 4]);
    nctx.beginPath(); for (const p of pos) if (p) { nctx.moveTo(...hub); nctx.lineTo(...p); } nctx.stroke(); nctx.setLineDash([]);
  }
  // V2V edges
  nctx.strokeStyle = 'rgba(55,215,242,0.85)'; nctx.lineWidth = 1.4; nctx.beginPath();
  for (const [a, b] of f0.edges || []) if (pos[a] && pos[b]) { nctx.moveTo(...pos[a]); nctx.lineTo(...pos[b]); } nctx.stroke();
  const deg = new Array(RUN.flights.length).fill(0); for (const [a, b] of f0.edges || []) { deg[a]++; deg[b]++; }
  pos.forEach((p, n) => { if (!p) return; const f = RUN.flights[n]; nctx.fillStyle = COLORS[f.type]; nctx.beginPath(); nctx.arc(p[0], p[1], 2.5 + Math.min(5, deg[n] * 1.2), 0, 7); nctx.fill();
    if (n === selected) { nctx.strokeStyle = '#fff'; nctx.lineWidth = 2; nctx.beginPath(); nctx.arc(p[0], p[1], 9, 0, 7); nctx.stroke(); }
    if (f0.net?.hub === f.id) { nctx.strokeStyle = '#f6bd4b'; nctx.lineWidth = 1.5; nctx.beginPath(); nctx.arc(p[0], p[1], 12, 0, 7); nctx.stroke(); } });
  // DTC hub node
  nctx.fillStyle = !RUN.switches.use_overseer ? '#3a4656' : linkUp ? '#a98bff' : '#ff5f72';
  nctx.beginPath(); nctx.arc(hub[0], hub[1], 12, 0, 7); nctx.fill();
  nctx.fillStyle = '#04121c'; nctx.font = '800 9px system-ui'; nctx.textAlign = 'center'; nctx.fillText('DTC', hub[0], hub[1] + 3); nctx.textAlign = 'left';
  nctx.fillStyle = '#b8c7d8'; nctx.font = '10.5px system-ui';
  nctx.fillText(!RUN.switches.use_overseer ? 'DTC disabled (decentralized)' : linkUp ? `DTC link UP · ${dtc.connected} drones under control` : `DTC link DOWN · drones on cached directive (${fmt(dtc.staleness_s, 0)} s old)`, hub[0] + 18, hub[1] + 4);
  // stats
  const m = f0.net || {};
  const row = (k, v) => `<dt>${k}</dt><dd>${v}</dd>`;
  $('#netStats').innerHTML = '<span class="hdr">V2V graph</span>' + row('Nodes · edges', `${m.nodes ?? 0} · ${m.edges ?? 0}`) + row('Avg degree', fmt(m.avg_degree, 2)) + row('Density', fmt(m.density, 3))
    + row('Transitivity', fmt(m.transitivity, 3)) + row('Max centrality', `${fmt(m.max_degree_centrality, 3)}${m.hub !== null && m.hub !== undefined ? ' · D-' + m.hub : ''}`)
    + row('Components', `${m.components ?? 0} (${m.isolated ?? 0} isolated)`) + row('Giant component', `${fmt((m.largest_component ?? 0) * 100, 0)}%`) + row('Alg. connectivity λ₂', fmt(m.algebraic_connectivity, 3))
    + '<span class="hdr">DTC</span>' + row('Link', !RUN.switches.use_overseer ? 'OFF' : linkUp ? 'UP' : 'DOWN') + row('Directive age', `${fmt(dtc.staleness_s)} s`)
    + row('Directives issued', dtc.directives ?? 0) + row('Layer changes · gated', `${dtc.layer_changes ?? 0} · ${dtc.deferred ?? 0}`);
}
function netSeries(f, maxDeg, maxStale) {
  const air = f.status.reduce((a, x) => a + (x === 1), 0), m = f.net || {}, d = f.dtc || {};
  return {cover: air ? (d.connected || 0) / air : null, trans: air ? m.transitivity : null, deg: air ? (m.avg_degree || 0) / maxDeg : null,
    cent: air ? m.max_degree_centrality : null, giant: air ? m.largest_component : null, stale: d.staleness_s === null || d.staleness_s === undefined ? null : Math.min(1, d.staleness_s / maxStale)};
}
let netCache = {n: 0, rows: null};
function netRows() {  // per-frame series, smoothed with a 3 s moving average (cached per frame count)
  if (netCache.n === frames.length && netCache.run === RUN.run_id) return netCache.rows;
  const maxDeg = Math.max(1, ...frames.map((f) => f.net?.avg_degree || 0));
  const maxStale = Math.max(3 * baseConfig.overseer.update_period_seconds, ...frames.map((f) => f.dtc?.staleness_s || 0));
  const raw = frames.map((f) => netSeries(f, maxDeg, maxStale)), win = Math.max(1, Math.round(3 / RUN.dt)), rows = [];
  for (let i = 0; i < raw.length; i++) {
    const r = {t: frames[i].t};
    for (const {key} of NET_SERIES) {
      if (key === 'cover' || key === 'stale') { r[key] = raw[i][key]; continue; }
      let sum = 0, c = 0; for (let j = Math.max(0, i - win + 1); j <= i; j++) if (raw[j][key] !== null && raw[j][key] !== undefined) { sum += raw[j][key]; c++; }
      r[key] = c ? sum / c : null;
    }
    rows.push(r);
  }
  netCache = {n: frames.length, run: RUN.run_id, rows, maxDeg};
  return rows;
}
function drawNetChart() {
  const w = netC.clientWidth, h = netC.clientHeight; screenTransform(ncctx); ncctx.clearRect(0, 0, w, h);
  if (!RUN || !frames.length) return;
  const L = 30, R = w - 10, T = 8, B = h - 20, X = (t) => L + (t / RUN.duration_s) * (R - L), Y = (v) => B - v * (B - T);
  ncctx.strokeStyle = '#16283e'; ncctx.fillStyle = '#5c7088'; ncctx.font = '10px system-ui';
  for (const v of [0, 0.5, 1]) { ncctx.beginPath(); ncctx.moveTo(L, Y(v)); ncctx.lineTo(R, Y(v)); ncctx.stroke(); ncctx.fillText(v.toFixed(1), 4, Y(v) + 3); }
  shadeEvents(ncctx, X, T, B);
  const rows = netRows(), maxDeg = netCache.maxDeg, step = Math.max(1, Math.floor(rows.length / 700));
  for (const ser of NET_SERIES) {
    ncctx.strokeStyle = ser.color; ncctx.lineWidth = ser.key === 'cover' ? 2.2 : 1.4; ncctx.beginPath(); let pen = false;
    for (let i = 0; i < rows.length; i += step) { const v = rows[i][ser.key]; if (v === null || v === undefined) { pen = false; continue; } pen ? ncctx.lineTo(X(rows[i].t), Y(v)) : ncctx.moveTo(X(rows[i].t), Y(v)); pen = true; }
    ncctx.stroke();
  }
  ncctx.strokeStyle = '#e6f0fa'; ncctx.lineWidth = 1; ncctx.beginPath(); ncctx.moveTo(X(simT), T); ncctx.lineTo(X(simT), B); ncctx.stroke();
  ncctx.fillStyle = '#5c7088'; ncctx.fillText('0 s', L, h - 5); ncctx.textAlign = 'right'; ncctx.fillText(`${RUN.duration_s} s · max avg degree ${maxDeg.toFixed(1)}`, R, h - 5); ncctx.textAlign = 'left';
}

// ------------------------------------------------------------------ P2 ADMM convergence timer
function drawAdmm() {
  const w = admmC.clientWidth, h = admmC.clientHeight; screenTransform(actx); actx.clearRect(0, 0, w, h);
  const s = RUN && frames.length ? frameAt(simT) : null, run = s?.f0.admm?.run;
  const row = (k, v) => `<dt>${k}</dt><dd>${v}</dd>`;
  if (!RUN || !s) { $('#admmStats').innerHTML = ''; return; }
  if (!RUN.switches.use_admm) {
    actx.fillStyle = '#5c7088'; actx.font = '12px system-ui'; actx.fillText(RUN.architecture === 'centralized' ? 'Centralized architecture: the DTC computes velocities, no ADMM.' : 'ADMM is switched off for this run.', 12, 24);
    $('#admmStats').innerHTML = ''; return;
  }
  const L = 30, R = w - 40, T = 8, B = h - 20, X = (t) => L + (t / RUN.duration_s) * (R - L);
  const step = Math.max(1, Math.floor(frames.length / 900));
  let itMax = 1, msMax = 0.05;
  for (const f of frames) { if (f.admm?.it_max) itMax = Math.max(itMax, f.admm.it_max); if (f.admm?.ms_mean) msMax = Math.max(msMax, f.admm.ms_mean); }
  itMax = Math.ceil(itMax * 1.15); msMax *= 1.15;
  const Yi = (v) => B - (v / itMax) * (B - T), Ym = (v) => B - (v / msMax) * (B - T);
  actx.strokeStyle = '#16283e'; actx.fillStyle = '#5c7088'; actx.font = '10px system-ui'; actx.lineWidth = 1;
  for (const v of [0, Math.round(itMax / 2), itMax]) { actx.beginPath(); actx.moveTo(L, Yi(v)); actx.lineTo(R, Yi(v)); actx.stroke(); actx.fillText(String(v), 6, Yi(v) + 3); }
  actx.textAlign = 'left'; for (const v of [0, msMax / 2, msMax]) actx.fillText(`${v.toFixed(2)}ms`, R + 4, Ym(v) + 3);
  const line = (get, Y, col, wd) => { actx.strokeStyle = col; actx.lineWidth = wd; actx.beginPath(); let pen = false;
    for (let i = 0; i < frames.length; i += step) { const v = get(frames[i]); if (v === null || v === undefined) { pen = false; continue; } pen ? actx.lineTo(X(frames[i].t), Y(v)) : actx.moveTo(X(frames[i].t), Y(v)); pen = true; } actx.stroke(); };
  line((f) => f.admm?.it_max, Yi, '#2fe0a0aa', 1);
  line((f) => f.admm?.it_mean, Yi, '#37d7f2', 1.6);
  line((f) => f.admm?.ms_mean, Ym, '#f6bd4b', 1.2);
  actx.fillStyle = '#ff5f72'; for (const f of frames) if (f.admm?.fail) actx.fillRect(X(f.t) - 1, B - 6, 2, 6);
  actx.strokeStyle = '#e6f0fa'; actx.lineWidth = 1; actx.beginPath(); actx.moveTo(X(simT), T); actx.lineTo(X(simT), B); actx.stroke();
  actx.fillStyle = '#5c7088'; actx.fillText('0 s', L, h - 5); actx.textAlign = 'right'; actx.fillText(`${RUN.duration_s} s`, R, h - 5); actx.textAlign = 'left';
  const r = run || {};
  $('#admmStats').innerHTML = row('Conflict groups', r.groups ?? 0) + row('Converged · fallback', `${r.converged ?? 0} · ${r.fallback ?? 0}`)
    + row('Iterations mean · p95 · max', `${fmt(r.it_mean, 1)} · ${fmt(r.it_p95, 0)} · ${fmt(r.it_max, 0)} / ${RUN.limits.max_iterations ?? '—'}`)
    + row('Solve time mean · p95', `${fmt(r.ms_mean, 3)} · ${fmt(r.ms_p95, 3)} ms`)
    + row('This frame', s.f0.admm?.groups ? `${s.f0.admm.groups} group(s) · ${fmt(s.f0.admm.it_mean, 1)} it` : 'no conflict')
    + '<dt class="note">Solve time is wall-clock on this machine (not part of the deterministic replay).</dt>';
}

// ------------------------------------------------------------------ run control
function readMix() { return {EMERGENCY: +$('#mixE').value || 0, EVTOL: +$('#mixV').value || 0, DELIVERY: +$('#mixD').value || 0}; }
function buildRequest() {
  const fleet = +$('#fleet').value, duration = +$('#duration').value, seed = +$('#seed').value, win = +$('#window').value;
  const maxFleet = LIMITS?.max_fleet ?? 150, maxDur = LIMITS?.max_duration_s ?? 900;
  const minFleet = customDrones.length ? 0 : 1;
  if (!Number.isInteger(fleet) || fleet < minFleet || fleet > maxFleet) throw Error(`Fleet size must be a whole number from ${minFleet} to ${maxFleet}${minFleet ? ' (0 is allowed with custom drones)' : ''}.`);
  if (fleet + customDrones.length > maxFleet) throw Error(`Random fleet ${fleet} + ${customDrones.length} custom drones exceeds the limit of ${maxFleet}.`);
  if (!(duration >= 5 && duration <= maxDur)) throw Error(`Duration must be 5–${maxDur} s.`);
  if (!Number.isInteger(seed) || seed < 0) throw Error('Seed must be a non-negative whole number.');
  const mix = readMix(); if (Object.values(mix).reduce((a, b) => a + b, 0) <= 0) throw Error('Vehicle mix must not be all zero.');
  const config = {};
  for (const input of document.querySelectorAll('[data-path]')) {
    const base = get(baseConfig, input.dataset.path), v = Number(input.value);
    if (!Number.isFinite(v) || v <= 0) throw Error(`${input.dataset.label} must be a positive number.`);
    if (v !== base) set(config, input.dataset.path, Number.isInteger(base) ? Math.round(v) : v);
  }
  return {map: mapId, fleet, duration_s: duration, seed, departure_window_s: Math.min(win, duration), mix, config,
    architecture: $('#arch').value, junction_merge: $('#swMerge').checked, drones: customDrones,
    use_overseer: $('#swOverseer').checked, use_admm: $('#swAdmm').checked, defended: $('#swDefense').checked,
    attack: {enabled: $('#swAttack').checked, count: 2, start_s: Math.round(duration * 0.2)},
    outage: {enabled: $('#swOutage').checked, start_s: Math.round(duration * 0.25), end_s: Math.round(duration * 0.6)}};
}
async function launch() {
  let req; try { req = buildRequest(); } catch (e) { status(e.message, 'err'); return; }
  $('#runBtn').disabled = true; status('Planning routes on the corridor graph…');
  try {
    const run = await api('/api/runs', req);   // the server stops the previous run only once this one is accepted
    const names = Object.fromEntries(MAP.vertiports.map((v) => [v.id, v.name]));
    run.flights.forEach((f) => { f.origin_name = names[f.origin]; f.destination_name = names[f.destination]; });
    RUN = run; frames = []; done = false; simT = 0; playing = true; droneEvents = {}; eventsIndexed = 0;
    nextSeq = 0; lastStats = null; lastPrio = null; lastH = null; hselHist = {}; speedProbe = []; negHist = {};
    selected = Math.max(0, run.flights.findIndex((f) => f.type === 'EMERGENCY'));
    resetLog(); $('#playBtn').textContent = '❚❚'; $('#seedLabel').innerHTML = `seed ${run.seed} · ${ARCH[run.architecture]?.label ?? run.architecture} · <span class="ic" title="Initial-conditions hash: identical for the same seed, fleet and map in every architecture">IC ${run.ic_hash}</span>`; $('#tMax').textContent = `/ ${run.duration_s} s`;
    $('#sceneTitle').textContent = SCENES[scene].title; buildLayerSeg(); buildDronePick();
    status(`Run ${run.run_id}: ${run.flights.length} flights planned on ${MAP.label} corridors — streaming from the simulator.`, 'ok');
    poll(run.run_id);
  } catch (e) { status(e.message, 'err'); $('#runState').textContent = 'ERROR'; }
  finally { $('#runBtn').disabled = false; }
}
async function poll(id) {
  try {
    while (RUN && RUN.run_id === id) {
      const selId = selected !== null && RUN.flights[selected] ? `&sel=${RUN.flights[selected].id}` : '';
      const r = await api(`/api/runs/${id}/frames?from=${nextSeq}&view_t=${simT.toFixed(2)}${selId}`);
      if (!RUN || RUN.run_id !== id) break;
      nextSeq = r.next;
      if (r.frames.length) {
        frames.push(...r.frames.map((x) => { indexNeg(x); return decodeFrame(x); })); indexEvents(); thinFrames();
        speedProbe.push([performance.now(), frames.at(-1).t]); if (speedProbe.length > 20) speedProbe.shift();
      }
      if (r.error) { status(`Simulation error: ${r.error}`, 'err'); done = true; break; }
      if (r.done) { done = true; const st = frames.at(-1)?.stats; if (st) status(`Run complete · ${st.arrivals} arrivals · ${st.crashes} crashes · ${st.near_misses} near misses · min separation ${fmt(st.min_separation_m, 2)} m.`, st.crashes || st.safety_violation_ticks ? 'err' : 'ok'); break; }
      await new Promise((res) => setTimeout(res, r.frames.length >= (LIMITS?.poll_batch ?? 400) ? 0 : 250));
    }
  } catch (e) { if (RUN && RUN.run_id === id) status(`Lost connection to simulator: ${e.message}`, 'err'); }
}
function buildLayerSeg() {
  const seg = $('#layerSeg'), n = RUN?.limits.num_layers ?? baseConfig.airspace.num_layers;
  seg.innerHTML = `<button data-layer="all" class="${layerFilter === 'all' ? 'on' : ''}">All</button>` + Array.from({length: n}, (_, l) => `<button data-layer="${l}" class="${layerFilter === String(l) ? 'on' : ''}">L${l}</button>`).join('');
}
function buildDronePick() {
  $('#dronePick').innerHTML = RUN.flights.map((f, n) => `<option value="${n}">${f.custom ? '★ ' : ''}D-${f.id} · ${TYPE_SHORT[f.type]} · ${f.origin_name || f.origin}→${f.destination_name || f.destination}${f.cooperative === false ? ' · non-coop' : ''}${f.malicious ? ' · spoofer' : ''}</option>`).join('');
}
function buildMapSeg() { $('#mapSeg').innerHTML = MAPS.map((m) => `<button data-map="${m.id}" class="${m.id === mapId ? 'on' : ''}">${m.label}</button>`).join(''); }
async function loadMap(id) {
  MAP = await api(`/api/map?map=${encodeURIComponent(id)}`); mapId = MAP.id;
  ctxPaths = {context: linesPath(MAP.context.length ? MAP.context : [[[0, 0], [0, 0]]]), corridors: linesPath(MAP.corridors)};
  backdropImg = null;
  if (MAP.backdrop) { backdropImg = new Image(); backdropImg.src = MAP.backdrop.url; }
  $('#attrib').textContent = `${MAP.source}${MAP.backdrop?.attribution ? ' · ' + MAP.backdrop.attribution : ''} · ${MAP.graph.nodes} junctions · ${MAP.vertiports.length} vertiports`;
  $('#mapEyebrow').textContent = `Live airspace · ${MAP.label}`;
  buildMapSeg(); userMoved = false; fit(); cdFillSelects();
}
function selectScene(name) {
  scene = name; const sc = SCENES[name];
  document.querySelectorAll('#scenes button').forEach((b) => b.classList.toggle('on', b.dataset.scene === name));
  [$('#mixE').value, $('#mixV').value, $('#mixD').value] = sc.mix;
  $('#swOverseer').checked = sc.overseer; $('#swAdmm').checked = sc.admm; $('#swDefense').checked = sc.defense; $('#swAttack').checked = sc.attack; $('#swOutage').checked = sc.outage;
  $('#swMerge').checked = true; chosenSwitches = null; $('#arch').value = sc.arch; applyArch();
  $('#sceneTitle').textContent = sc.title;
}
// non-hierarchical architectures fix DTC / ADMM / defence (and merging for centralized); restore the
// user's own choices when switching back to hierarchical
function applyArch() {
  const fixed = ARCH[$('#arch').value].fixed;
  if (fixed && !chosenSwitches) chosenSwitches = SWITCH_IDS.map((id) => $(id).checked);
  if (!fixed && chosenSwitches) { SWITCH_IDS.forEach((id, k) => { $(id).checked = chosenSwitches[k]; }); chosenSwitches = null; }
  SWITCH_IDS.forEach((id, k) => {
    const v = fixed ? fixed[k] : null, input = $(id);
    if (v !== null && v !== undefined) input.checked = v;
    input.disabled = v !== null && v !== undefined; input.parentElement.classList.toggle('fixed', input.disabled);
  });
}
$('#arch').onchange = applyArch;

// ------------------------------------------------------------------ export / replay (2g)
$('#dlBtn').onclick = () => {
  if (!RUN || RUN.replay) { status(RUN?.replay ? 'This run was loaded from a file — it is already saved.' : 'Launch a run first.', 'err'); return; }
  const a = document.createElement('a'); a.href = `/api/runs/${RUN.run_id}/export`; a.download = `masooda_run_${RUN.run_id}.json`;
  document.body.append(a); a.click(); a.remove();
  status(done ? 'Run downloaded (manifest, resolved config, command log, per-frame KPIs, events, frames).' : 'Run still computing — the download holds the frames computed so far.', 'ok');
};
$('#loadRun').onchange = async (e) => {
  const file = e.target.files[0]; e.target.value = ''; if (!file) return;
  try {
    const data = JSON.parse(await file.text());
    if (data?.format !== 'masooda-run' || data.version !== 1) throw Error('not a MASooda run export (version 1)');
    const m = data.manifest; if (!m?.flights || !data.frames?.length) throw Error('export has no flights or frames');
    if (RUN && !done && !RUN.replay) api(`/api/runs/${RUN.run_id}/stop`, {}).catch(() => {});
    if (m.map !== mapId) await loadMap(m.map);
    const names = Object.fromEntries(MAP.vertiports.map((v) => [v.id, v.name]));
    m.flights.forEach((f) => { f.origin_name = names[f.origin]; f.destination_name = names[f.destination]; });
    RUN = {...m, run_id: `replay:${m.run_id}`, replay: true}; frames = []; done = true; simT = 0; playing = true; droneEvents = {}; eventsIndexed = 0;
    nextSeq = 0; lastStats = null; lastPrio = null; lastH = null; hselHist = {}; speedProbe = []; negHist = {};
    frames = data.frames.map((x) => { indexNeg(x); return decodeFrame(x); }); indexEvents();
    selected = Math.max(0, m.flights.findIndex((f) => f.type === 'EMERGENCY'));
    resetLog(); $('#playBtn').textContent = '❚❚'; $('#tMax').textContent = `/ ${m.duration_s} s`;
    $('#seedLabel').innerHTML = `seed ${m.seed} · ${ARCH[m.architecture]?.label ?? m.architecture} · <span class="ic">IC ${m.ic_hash}</span> · loaded`;
    $('#sceneTitle').textContent = `Replay · ${file.name}`; buildLayerSeg(); buildDronePick();
    status(`Loaded ${file.name}: ${frames.length} frames, ${m.flights.length} flights, config ${data.config_hash} — replaying without re-simulating${data.complete ? '' : ' (partial run)'}.`, 'ok');
  } catch (err) { status(`Cannot load run: ${err.message}`, 'err'); }
};

function simSpeed() {  // simulated seconds computed per wall-clock second (recent polls)
  if (speedProbe.length < 2) return NaN;
  const [w0, t0] = speedProbe[0], [w1, t1] = speedProbe.at(-1);
  return w1 > w0 ? (t1 - t0) / ((w1 - w0) / 1000) : NaN;
}
function applyLimits() {
  $('#fleet').max = String(LIMITS.max_fleet); $('#duration').max = String(LIMITS.max_duration_s); $('#window').max = String(LIMITS.max_duration_s);
  $('#fleetHint').textContent = `max ${LIMITS.max_fleet}`;
  checkFleetWarning();
}
function checkFleetWarning() {
  if (!LIMITS) return;
  const n = +$('#fleet').value, w = $('#fleetWarn');
  w.hidden = !(n > LIMITS.realtime_max_fleet);
  w.textContent = `Above ${LIMITS.realtime_max_fleet} drones this machine computes slower than real time — playback will pause while it buffers.`;
}
$('#fleet').addEventListener('input', checkFleetWarning);

// ------------------------------------------------------------------ main loop
function tick(ts) {
  const dt = lastTs ? Math.min(0.1, (ts - lastTs) / 1000) : 0; lastTs = ts;
  if (RUN && frames.length && playing) {
    const maxT = frames.at(-1).t;
    simT = Math.min(simT + dt * speed, maxT);
    const buffering = !done && simT >= maxT - 1e-6;
    $('#buffer').hidden = !buffering;
    if (buffering) $('#buffer').textContent = `computing ahead… simulator at ${fmt(simSpeed(), 1)}× real time`;
    if (done && simT >= maxT) { playing = false; $('#playBtn').textContent = '▶'; }
  } else $('#buffer').hidden = true;
  const s = RUN && frames.length ? frameAt(simT) : null;
  drawMap(); updatePanels(); draw25(s); drawNetwork(s);
  if (RUN && frames.length) { drawChart(); drawNetChart(); drawAdmm(); }
  requestAnimationFrame(tick);
}

// ------------------------------------------------------------------ interaction
function pick(px, py) {
  if (!RUN || !frames.length) return null; const s = frameAt(simT); let best = null, bd = 16;
  RUN.flights.forEach((_, n) => { const st = s.f0.status[n]; if (st !== 1 && st !== 3) return; const p = st === 1 ? posOf(s, n) : [s.f0.x[n], s.f0.y[n]], d = Math.hypot(sx(p[0]) - px, sy(p[1]) - py); if (d < bd) { bd = d; best = n; } });
  return best;
}
let drag = null;
canvas.addEventListener('pointerdown', (e) => { drag = {x: e.clientX, y: e.clientY, cx: view.cx, cy: view.cy, moved: false}; canvas.setPointerCapture(e.pointerId); });
canvas.addEventListener('pointermove', (e) => {
  const r = canvas.getBoundingClientRect(), px = e.clientX - r.left, py = e.clientY - r.top;
  if (drag) { const dx = e.clientX - drag.x, dy = e.clientY - drag.y; if (Math.hypot(dx, dy) > 3) { drag.moved = true; follow = false; userMoved = true; canvas.classList.add('drag'); } view.cx = drag.cx - dx / view.s; view.cy = drag.cy + dy / view.s; return; }
  const n = pick(px, py), tip = $('#tip');
  canvas.style.cursor = n === null ? '' : 'pointer';
  if (n === null) { tip.hidden = true; return; }
  const f = RUN.flights[n], fr = frameAt(simT).f0;
  tip.hidden = false; tip.style.left = `${px + 14}px`; tip.style.top = `${py + 10}px`;
  tip.textContent = `D-${f.id} ${f.type} · ${f.origin_name}→${f.destination_name} · L${fr.layer[n]} · ${fmt(fr.speed[n])} m/s · click to inspect`;
});
canvas.addEventListener('pointerup', (e) => {
  const r = canvas.getBoundingClientRect();
  if (drag && !drag.moved && pickMode) { pickVertiport(e.clientX - r.left, e.clientY - r.top); }
  else if (drag && !drag.moved) { const n = pick(e.clientX - r.left, e.clientY - r.top); if (n !== null) select(n); }
  drag = null; canvas.classList.remove('drag');
});
canvas.addEventListener('pointerleave', () => { $('#tip').hidden = true; });
canvas.addEventListener('wheel', (e) => { e.preventDefault(); const r = canvas.getBoundingClientRect(); zoomAt(Math.exp(-e.deltaY * 0.0015), e.clientX - r.left, e.clientY - r.top); }, {passive: false});
netG.addEventListener('click', (e) => {
  if (!netPositions) return; const r = netG.getBoundingClientRect(), px = e.clientX - r.left, py = e.clientY - r.top; let best = null, bd = 14;
  netPositions.forEach((p, n) => { if (!p) return; const d = Math.hypot(p[0] - px, p[1] - py); if (d < bd) { bd = d; best = n; } });
  if (best !== null) select(best);
});
$('#dronePick').onchange = (e) => select(+e.target.value);
$('#zIn').onclick = () => zoomAt(1.4); $('#zOut').onclick = () => zoomAt(1 / 1.4); $('#zFit').onclick = () => { follow = false; userMoved = false; fit(); };
$('#zFollow').onclick = () => { follow = !follow; if (follow && view.s < 1) view.s = 1.6; $('#zFollow').classList.toggle('on', follow); };
$('#playBtn').onclick = () => { if (!RUN) return; if (!playing && done && simT >= frames.at(-1).t) { simT = 0; resetLog(); } playing = !playing; $('#playBtn').textContent = playing ? '❚❚' : '▶'; };
$('#restartBtn').onclick = () => { if (!RUN) return; simT = 0; resetLog(); playing = true; $('#playBtn').textContent = '❚❚'; };
$('#speedSeg').onclick = (e) => { const b = e.target.closest('button'); if (!b) return; speed = +b.dataset.speed; document.querySelectorAll('#speedSeg button').forEach((x) => x.classList.toggle('on', x === b)); };
$('#layerSeg').onclick = (e) => { const b = e.target.closest('button'); if (!b) return; layerFilter = b.dataset.layer; buildLayerSeg(); };
$('#mapSeg').onclick = async (e) => { const b = e.target.closest('button'); if (!b || b.dataset.map === mapId) return; try { await loadMap(b.dataset.map); await launch(); } catch (err) { status(err.message, 'err'); } };
$('#scenes').onclick = (e) => { const b = e.target.closest('button'); if (b) selectScene(b.dataset.scene); };
$('#scrub').oninput = (e) => { if (!RUN) return; const t = Math.min(+e.target.value, frames.at(-1)?.t ?? 0); if (t < simT) resetLog(); simT = t; };
$('#runBtn').onclick = launch;
window.addEventListener('keydown', (e) => { if (e.code === 'Space' && !['INPUT', 'BUTTON', 'SELECT'].includes(document.activeElement.tagName)) { e.preventDefault(); $('#playBtn').click(); } });
window.addEventListener('resize', resize);
if (window.ResizeObserver) new ResizeObserver(() => resize()).observe(document.querySelector('.layout'));
$('#netLegend').innerHTML = NET_SERIES.map((s) => `<span><i style="background:${s.color}"></i>${s.label}</span>`).join('');

// ------------------------------------------------------------------ Phase 3: custom drones (scenario builder)
let customDrones = [], editIndex = null, pickMode = null;
function appendFlights(list) {  // drones injected mid-run arrive in frames as new_flights
  if (!RUN) return;
  const have = new Set(RUN.flights.map((f) => f.id)), names = Object.fromEntries(MAP.vertiports.map((v) => [v.id, v.name]));
  let added = 0;
  for (const f of list) { if (have.has(f.id)) continue; f.origin_name = names[f.origin]; f.destination_name = names[f.destination]; RUN.flights.push(f); added++; }
  if (added) buildDronePick();
}
function cdFillSelects() {
  if (!MAP) return;
  const opts = MAP.vertiports.map((v) => `<option value="${v.id}">${v.id} · ${v.name} (${v.role})</option>`).join('');
  for (const id of ['#cdOrigin', '#cdDest']) { const sel = $(id), keep = sel.value; sel.innerHTML = opts; if (keep && MAP.vertiports.some((v) => v.id === keep)) sel.value = keep; }
  if ($('#cdOrigin').value === $('#cdDest').value && MAP.vertiports.length > 1) $('#cdDest').selectedIndex = 1;
  const L = baseConfig?.airspace.num_layers ?? 3, em = baseConfig?.airspace.emergency_layer ?? L - 1;
  $('#cdLayer').innerHTML = '<option value="">auto (semicircular rule)</option>' + Array.from({length: L}, (_, l) => `<option value="${l}">L${l}${l === em ? ' (emergency only)' : ''}</option>`).join('');
  $('#cdSpeed').max = String(baseConfig?.safety.maximum_velocity_meters_per_second ?? 20);
  // drones made for another map no longer have valid vertiports
  const ok = new Set(MAP.vertiports.map((v) => v.id)), before = customDrones.length;
  customDrones = customDrones.filter((d) => ok.has(d.origin) && ok.has(d.destination));
  if (customDrones.length < before) cdMessage(`${before - customDrones.length} custom drone(s) removed: their vertiports are not on ${MAP.label}.`, 'err');
  cdRender();
}
const numOrNull = (id) => { const v = $(id).value.trim(); return v === '' ? null : Number(v); };
function cdReadForm() {
  const d = {type: $('#cdType').value, origin: $('#cdOrigin').value, destination: $('#cdDest').value, depart_s: numOrNull('#cdDep') ?? 0,
    cooperative: $('#cdCoop').checked, malicious: $('#cdMal').checked};
  const opt = {priority: numOrNull('#cdPrio'), cruise_speed_mps: numOrNull('#cdSpeed'), preferred_layer: $('#cdLayer').value === '' ? null : +$('#cdLayer').value,
    battery_wh: numOrNull('#cdWh'), soc_init_pct: numOrNull('#cdSoc'), soh_pct: numOrNull('#cdSoh'), payload_kg: numOrNull('#cdPay')};
  for (const [k, v] of Object.entries(opt)) if (v !== null) d[k] = v;
  if (d.malicious) d.spoof_offset_m = [numOrNull('#cdDx') ?? 25, numOrNull('#cdDy') ?? 0];
  if ($('#cdFault').value) d.fault = {type: $('#cdFault').value, t_s: numOrNull('#cdFaultT')};
  if (d.origin === d.destination) throw Error('Origin and destination must be different vertiports.');
  if (d.fault && d.fault.t_s === null) throw Error('Give the time of the scheduled fault.');
  return d;
}
function cdWriteForm(d) {
  $('#cdType').value = d.type; $('#cdOrigin').value = d.origin; $('#cdDest').value = d.destination; $('#cdDep').value = d.depart_s ?? 0;
  const put = (id, v) => { $(id).value = v ?? ''; };
  put('#cdPrio', d.priority); put('#cdSpeed', d.cruise_speed_mps); put('#cdLayer', d.preferred_layer); put('#cdWh', d.battery_wh); put('#cdSoc', d.soc_init_pct);
  put('#cdSoh', d.soh_pct); put('#cdPay', d.payload_kg); $('#cdCoop').checked = d.cooperative !== false; $('#cdMal').checked = !!d.malicious;
  put('#cdDx', d.spoof_offset_m?.[0] ?? 25); put('#cdDy', d.spoof_offset_m?.[1] ?? 0); put('#cdFault', d.fault?.type ?? ''); put('#cdFaultT', d.fault?.t_s);
}
function cdMessage(msg, kind = '') { const n = $('#cdMsg'); n.textContent = msg; n.className = `status ${kind}`; }
function cdRender() {
  $('#cdCount').textContent = `${customDrones.length} in scenario`;
  $('#cdFormTitle').textContent = editIndex === null ? 'New drone' : `Edit drone #${editIndex + 1}`;
  $('#cdAdd').textContent = editIndex === null ? '＋ Add to scenario' : '✓ Save changes';
  const list = $('#cdList'); list.replaceChildren();
  customDrones.forEach((d, i) => {
    const li = document.createElement('li'); if (i === editIndex) li.className = 'editing';
    const tags = [d.cooperative === false ? '<span class="tag">non-coop</span>' : '', d.malicious ? '<span class="tag bad">spoofer</span>' : '', d.fault ? `<span class="tag">${d.fault.type} @${d.fault.t_s}s</span>` : ''].join('');
    li.innerHTML = `<span class="t" style="color:${COLORS[d.type]}">${d.id !== undefined && d.id !== null ? 'D-' + d.id : '#' + (i + 1)} ${TYPE_SHORT[d.type]} ${d.origin}→${d.destination} @${d.depart_s ?? 0}s</span>${tags}<button data-edit="${i}" title="Edit">✎</button><button data-del="${i}" title="Delete">✕</button>`;
    list.append(li);
  });
  $('#cdNow').disabled = !(RUN && !RUN.replay && !done);
}
$('#cdAdd').onclick = () => {
  try {
    const d = cdReadForm();
    if (editIndex === null) customDrones.push(d); else { if (customDrones[editIndex].id !== undefined) d.id = customDrones[editIndex].id; customDrones[editIndex] = d; }
    cdMessage(editIndex === null ? `Added — it flies in the next launched run (${customDrones.length} custom).` : 'Saved.', 'ok');
    editIndex = null; cdRender();
  } catch (e) { cdMessage(e.message, 'err'); }
};
$('#cdClear').onclick = () => { editIndex = null; cdWriteForm({type: 'DELIVERY', origin: $('#cdOrigin').value, destination: $('#cdDest').value, depart_s: 0}); cdRender(); cdMessage(''); };
$('#cdList').onclick = (e) => {
  const b = e.target.closest('button'); if (!b) return;
  if (b.dataset.del !== undefined) { customDrones.splice(+b.dataset.del, 1); editIndex = null; }
  else { editIndex = +b.dataset.edit; cdWriteForm(customDrones[editIndex]); $('#cdForm').open = true; }
  cdRender();
};
$('#cdRemoveAll').onclick = () => { customDrones = []; editIndex = null; cdRender(); cdMessage('All custom drones removed.'); };
$('#cdNow').onclick = async () => {
  if (!RUN || RUN.replay || done) { cdMessage('Start a run first — "Add drone now" injects into the running simulation.', 'err'); return; }
  try {
    const d = cdReadForm(); delete d.depart_s;
    const r = await api(`/api/runs/${RUN.run_id}/commands`, {type: 'add_drone', drone: d, reason: 'operator: add drone now'});
    const ahead = frames.length ? frames.at(-1).t : simT;
    cdMessage(`Command ${r.command_id} sent: D-${r.drone_id} is added at the simulator's next tick (≈ t ${fmt(ahead, 0)} s; the simulator runs at most ${LIMITS?.interactive_lead_s ?? 5} s ahead of playback).`, 'ok');
  } catch (e) { cdMessage(e.message, 'err'); }
};
$('#cdImport').onchange = async (e) => {
  const file = e.target.files[0]; e.target.value = ''; if (!file) return;
  try {
    const text = await file.text(), format = /\.csv$/i.test(file.name) || /^\s*[a-z_]+\s*,/i.test(text) ? 'csv' : 'json';
    const r = await api('/api/drones/parse', {format, text, map: mapId, duration_s: +$('#duration').value || undefined});
    customDrones = r.drones.map((d) => { for (const k of Object.keys(d)) if (d[k] === null) delete d[k]; return d; });
    editIndex = null; cdRender(); cdMessage(`Imported ${customDrones.length} drone(s) from ${file.name}.`, 'ok');
  } catch (err) { cdMessage(`Import failed — ${err.message}`, 'err'); }
};
async function cdExport(format) {
  if (!customDrones.length) { cdMessage('No custom drones to export.', 'err'); return; }
  try {
    const r = await api('/api/drones/export', {format, drones: customDrones, map: mapId, duration_s: +$('#duration').value || undefined});
    const blob = new Blob([r.text], {type: format === 'csv' ? 'text/csv' : 'application/json'}), a = document.createElement('a');
    a.href = URL.createObjectURL(blob); a.download = r.filename; document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    cdMessage(`Exported ${customDrones.length} drone(s) as ${format.toUpperCase()}.`, 'ok');
  } catch (e) { cdMessage(`Export failed — ${e.message}`, 'err'); }
}
$('#cdExpJson').onclick = () => cdExport('json'); $('#cdExpCsv').onclick = () => cdExport('csv');
document.querySelectorAll('.pick').forEach((b) => b.onclick = (e) => {
  e.preventDefault(); pickMode = pickMode === b.dataset.pick ? null : b.dataset.pick;
  document.querySelectorAll('.pick').forEach((x) => x.classList.toggle('on', x.dataset.pick === pickMode)); canvas.classList.toggle('picking', !!pickMode);
  if (pickMode) cdMessage(`Click a vertiport on the map to set the ${pickMode === 'cdOrigin' ? 'origin' : 'destination'}.`);
});
function pickVertiport(px, py) {
  let best = null, bd = 18;
  for (const v of MAP.vertiports) { const d = Math.hypot(sx(v.x) - px, sy(v.y) - py); if (d < bd) { bd = d; best = v; } }
  if (!best) { cdMessage('No vertiport there — click one of the square pad markers.', 'err'); return; }
  $(`#${pickMode}`).value = best.id; cdMessage(`${pickMode === 'cdOrigin' ? 'Origin' : 'Destination'} set to ${best.id} · ${best.name}.`, 'ok');
  pickMode = null; document.querySelectorAll('.pick').forEach((x) => x.classList.remove('on')); canvas.classList.remove('picking');
}

// ------------------------------------------------------------------ Phase 3B: health views
function applyReroutes(list) {  // health diversions: the drone's route and destination change
  if (!RUN) return;
  const names = Object.fromEntries(MAP.vertiports.map((v) => [v.id, v.name]));
  for (const r of list) { const n = idxOf(r.id); if (n < 0) continue; const f = RUN.flights[n];
    f.route = r.route; f.route_length_m = r.route_length_m; f.destination = r.destination; f.destination_name = names[r.destination]; f.diverted = r.reason; }
}
function healthAt(id) { const h = hselHist[id]; if (!h) return null; for (let i = h.length - 1; i >= 0; i--) if (h[i].t <= simT + 1e-6) return h[i]; return h[0].t <= simT + 1e-6 ? h[0] : null; }
function updateFleetHealth(s) {
  const f = s.f0, h = f.h, card = $('#fleetHealth');
  const on = RUN.limits.health?.enabled; card.hidden = !on; if (!on) return;
  $('#fhAmb').textContent = `ambient ${RUN.limits.health.ambient_c} °C`;
  const cnt = [0, 0, 0, 0], air = [];
  if (h) f.status.forEach((st, k) => { if (st === 1 && h.bms[k] !== undefined) { cnt[h.bms[k]]++; air.push(k); } });
  $('#fhCounts').innerHTML = BMS.map((b, i) => `<div><b style="color:${BMS_COL[i]}">${cnt[i]}</b><small>${b}</small></div>`).join('');
  const key = `${frameAt(simT).i}:${selected}`; if (updateFleetHealth.key === key) return; updateFleetHealth.key = key;
  const low = air.sort((a, b) => h.soc[a] - h.soc[b]).slice(0, 6), lowEl = $('#fhLow'); lowEl.replaceChildren();
  for (const k of low) { const li = document.createElement('li'), soc = h.soc[k], col = soc < 15 ? '#ff3b5c' : soc < 30 ? '#f6bd4b' : '#2fe0a0';
    li.innerHTML = `<span style="color:${COLORS[RUN.flights[k].type]}">D-${RUN.flights[k].id}</span><span class="bar"><i style="width:${soc}%;background:${col}"></i></span><span>${soc}%</span><span class="muted">${BMS[h.bms[k]]} · ${h.tmax[k]} °C</span>`;
    li.onclick = () => select(k); lowEl.append(li); }
  if (!low.length) lowEl.innerHTML = '<li class="empty">no drones airborne</li>';
  const al = [], al$ = $('#fhAlerts'); al$.replaceChildren();
  for (let i = frameAt(simT).i; i >= 0 && frames[i].t > simT - 60; i--) for (const e of frames[i].events) if (e.severity === 'critical' || (e.severity === 'warning' && e.kind !== 'bms')) al.push(e);
  for (const e of al.slice(0, 8)) { const li = document.createElement('li'); li.className = `sev-${e.severity}`; li.innerHTML = `<time>${fmt(e.t)}s</time><span></span>`; li.lastChild.textContent = e.text; li.onclick = () => select(idxOf(e.ids[0])); al$.append(li); }
  if (!al.length) al$.innerHTML = '<li class="empty">no active alerts</li>';
}
function updateHealthTab(s) {
  if (selected === null) return;
  const f = RUN.flights[selected], k = selected, h = s.f0.h, rec = healthAt(f.id), d = rec?.d, th = RUN.limits.health?.thresholds || {};
  const soc = d?.soc ?? h?.soc?.[k], st = d ? BMS.indexOf(d.status) : h?.bms?.[k] ?? 0;
  $('#hSoc').textContent = soc === undefined ? '—' : `SoC ${fmt(soc, 0)} %`; $('#hSocBar').style.width = `${soc ?? 0}%`;
  $('#hSocBar').style.background = soc < (th.soc_critical_pct ?? 15) ? '#ff3b5c' : soc < (th.soc_warning_pct ?? 30) ? '#f6bd4b' : '#2fe0a0';
  const pill = $('#hStatus'); pill.textContent = BMS[st] ?? '—'; pill.className = `pill s${st}`;
  $('#hCodes').textContent = d?.codes?.join(' · ') || '';
  $('#hNote').textContent = d ? (simT - rec.t > 2 ? `detail from t = ${fmt(rec.t)} s` : '') : 'full detail streams once the drone is selected (live runs)';
  const set = (id, v) => { $(id).textContent = v; };
  if (d) {
    set('#hVip', `${fmt(d.v, 1)} V · ${fmt(d.i, 1)} A · ${fmt(d.p, 0)} W`);
    set('#hLeft', `${fmt(d.e_rem_wh, 0)} Wh · ${d.time_left_s === null ? '—' : fmt(d.time_left_s / 60, 1) + ' min'} · ${d.range_left_m === null ? '—' : fmt(d.range_left_m / 1000, 1) + ' km'}`);
    set('#hSoh', `${fmt(d.soh, 0)} % · ${fmt(d.capacity_wh, 0)} Wh`);
    set('#hTp', `${fmt(d.t_pack, 1)} °C (max ${fmt(d.t_pack_max, 0)}) · warn ${th.pack_warning_c} / crit ${th.pack_critical_c}`);
    set('#hTm', `${fmt(d.t_motor, 1)} °C (max ${fmt(d.t_motor_max, 0)}) · warn ${th.motor_warning_c} / crit ${th.motor_critical_c}`);
    set('#hCellTxt', `${fmt(d.min_cell_v, 3)} V · ${fmt(d.imbalance_mv, 0)} mV`);
    set('#hLink', d.rssi_dbm === null ? (d.packet_loss === 1 ? 'no link (outage)' : 'no DTC') : `${fmt(d.rssi_dbm, 0)} dBm · ${fmt(d.packet_loss * 100, 1)} %`);
    set('#hGnss', `${d.fix} · ${fmt(d.hdop, 2)}`);
    set('#hMotor', `${fmt(d.motor_health * 100, 0)} % · ${fmt(d.energy_used_wh, 1)} Wh`);
    set('#hFaults', [...(d.faults || []), d.pending_fault ? `${d.pending_fault.type} @ ${d.pending_fault.t_s} s (scheduled)` : ''].filter(Boolean).join(' · ') || (f.diverted ? '' : 'none') + (f.diverted ? `diverted: ${f.diverted}` : ''));
  } else for (const id of ['#hVip', '#hLeft', '#hSoh', '#hTp', '#hTm', '#hCellTxt', '#hLink', '#hGnss', '#hMotor', '#hFaults']) set(id, '—');
  drawCells(d); drawHealthChart(k);
}
function drawCells(d) {
  const w = hCellsC.clientWidth, h = hCellsC.clientHeight; screenTransform(hcctx); hcctx.clearRect(0, 0, w, h);
  if (!d?.cells_mv?.length) return;
  const c = d.cells_mv, lo = Math.min(3000, ...c) - 50, hi = 4250, n = c.length, bw = Math.max(1, (w - 34) / n);
  hcctx.fillStyle = '#5c7088'; hcctx.font = '9.5px system-ui'; hcctx.fillText('4.2 V', 0, 10); hcctx.fillText('3.0 V', 0, h - 4);
  const Y = (v) => h - 2 - (v - lo) / (hi - lo) * (h - 6);
  hcctx.strokeStyle = '#ff5f7288'; hcctx.setLineDash([3, 3]); hcctx.beginPath(); hcctx.moveTo(30, Y(3000)); hcctx.lineTo(w, Y(3000)); hcctx.stroke(); hcctx.setLineDash([]);
  const mn = Math.min(...c);
  c.forEach((v, i) => { hcctx.fillStyle = v === mn ? '#f6bd4b' : '#37d7f2'; const y = Y(v); hcctx.fillRect(32 + i * bw, y, Math.max(1, bw - (n > 30 ? 0 : 2)), h - 2 - y); });
}
function drawHealthChart(k) {
  const w = hChartC.clientWidth, h = hChartC.clientHeight; screenTransform(hchctx); hchctx.clearRect(0, 0, w, h);
  if (!frames.length) return;
  const L = 26, R = w - 30, T = 6, B = h - 14, X = (t) => L + t / RUN.duration_s * (R - L);
  hchctx.strokeStyle = '#16283e'; hchctx.fillStyle = '#5c7088'; hchctx.font = '9.5px system-ui';
  for (const v of [0, 50, 100]) { const y = B - v / 100 * (B - T); hchctx.beginPath(); hchctx.moveTo(L, y); hchctx.lineTo(R, y); hchctx.stroke(); hchctx.fillText(`${v}%`, 0, y + 3); }
  const tMax = 100; hchctx.textAlign = 'left'; for (const v of [20, 60, 100]) hchctx.fillText(`${v}°`, R + 3, B - (v / tMax) * (B - T) + 3);
  const step = Math.max(1, Math.floor(frames.length / 500));
  const line = (get, scale, col) => { hchctx.strokeStyle = col; hchctx.lineWidth = 1.5; hchctx.beginPath(); let pen = false;
    for (let i = 0; i < frames.length; i += step) { const f = frames[i]; const v = f.h ? get(f.h) : undefined; if (v === undefined || f.status[k] === undefined || f.status[k] === 0 && v === undefined) { pen = false; continue; }
      const y = B - Math.min(1, v / scale) * (B - T); pen ? hchctx.lineTo(X(f.t), y) : hchctx.moveTo(X(f.t), y); pen = true; } hchctx.stroke(); };
  line((h) => h.soc[k], 100, '#2fe0a0'); line((h) => h.tmax[k], tMax, '#ff8a4c');
  hchctx.strokeStyle = '#e6f0fa'; hchctx.lineWidth = 1; hchctx.beginPath(); hchctx.moveTo(X(simT), T); hchctx.lineTo(X(simT), B); hchctx.stroke();
}
$('#dTabs').onclick = (e) => { const b = e.target.closest('button'); if (!b) return; dTab = b.dataset.tab;
  document.querySelectorAll('#dTabs button').forEach((x) => x.classList.toggle('on', x === b));
  $('#tabOv').hidden = dTab !== 'ov'; $('#tabHl').hidden = dTab !== 'hl'; resize(); };

// ------------------------------------------------------------------ boot
async function boot() {
  resize(); requestAnimationFrame(tick);
  try {
    let maps;
    [baseConfig, maps, LIMITS] = await Promise.all([api('/api/config'), api('/api/maps'), api('/api/limits')]);
    applyLimits();
    MAPS = maps.maps;
    await loadMap(new URLSearchParams(location.search).get('map') || maps.default);
    $('#advFields').innerHTML = ADVANCED.map(([p, label]) => `<label>${label}<input type="number" step="any" data-path="${p}" data-label="${label}" value="${get(baseConfig, p)}"></label>`).join('');
    $('#seed').value = baseConfig.simulation.random_seed;
    $('#sysStatus').textContent = 'ONLINE'; $('#sysDot').className = 'dot ok';
    buildLayerSeg(); selectScene('normal');
    await launch();
  } catch (e) {
    $('#sysStatus').textContent = 'OFFLINE'; $('#sysDot').className = 'dot bad';
    status(`Cannot reach the simulator (${e.message}). Start it with: python -m web_sandbox.server`, 'err');
  }
}
boot();
