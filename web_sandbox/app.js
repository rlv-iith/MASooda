/* MASooda live demo — map-constrained multi-drone governance.
 * Streams frames from the local Python simulator (POST /api/runs, GET /api/runs/<id>/frames)
 * and renders: corridor map (IITH campus / Hyderabad), 2.5D view of the selected drone with its
 * own event feed, DTC + V2V network theory over time, STL safety, and governance KPIs.
 * No external dependencies. */
'use strict';
const $ = (s) => document.querySelector(s);
const COLORS = {EMERGENCY: '#e11d48', EVTOL: '#0891b2', DELIVERY: '#d97706'};
const TYPE_SHORT = {EMERGENCY: 'EMG', EVTOL: 'eVTOL', DELIVERY: 'DEL'};
const STATUS = ['queued', 'airborne', 'landed', 'crashed', 'forced landing'];
const BMS = ['NORMAL', 'WARNING', 'CRITICAL', 'FAULT'], BMS_COL = ['#059669', '#d97706', '#e11d48', '#e11d48'];
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
  {key: 'cover', label: 'DTC coverage', color: '#6d4fe0'},
  {key: 'trans', label: 'Transitivity', color: '#059669'},
  {key: 'deg', label: 'Avg degree (norm.)', color: '#0891b2'},
  {key: 'cent', label: 'Max degree centrality', color: '#d97706'},
  {key: 'giant', label: 'Largest component', color: '#0f172a'},
  {key: 'stale', label: 'Directive age (norm.)', color: '#e11d48'},
];

let baseConfig = null, LIMITS = null, MAP = null, MAPS = [], mapId = null, RUN = null, frames = [], done = false;
let lastReq = null;   // the last launch request, for Relaunch
// Download is built in the browser: the compact frames exactly as received (thinned like the
// server's store) plus the run header kept at launch, so it needs no server work and survives a restart.
let rawFrames = [], rawThinned = 0, runStart = null;
const RAW_LIST_KEYS = ['new_flights', 'reroutes'], RAW_CARRY_KEYS = ['stats', 'prio', 'h', 'console'];
let nextSeq = 0, lastStats = null, shownEvents = new WeakSet(), speedProbe = [];
let scene = 'normal', simT = 0, playing = true, speed = 2, lastTs = 0, selected = null, layerFilter = 'all', follow = false;
let view = {cx: 0, cy: 0, s: 0.2}, userMoved = false, dpr = 1, ctxPaths = null, backdropImg = null, logCursor = 0, logTotal = 0;
let droneEvents = {}, eventsIndexed = 0, netPositions = null, lastDroneFeedKey = '';
let negHist = {}, chosenSwitches = null, lastPrio = null, lastH = null, hselHist = {}, dTab = 'ov';
let selSet = new Set(), lastConsole = null, tfrRect = null, viaPick = false, viaPoint = null, boxSel = null, cmdHist = [], histAt = 0, tfrCount = 0;
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
function altOf(layer) { const L = RUN.limits; return Math.round((L.base_altitude ?? L.layer_height) + layer * L.layer_height); }
function fmt(v, d = 1) { return v === null || v === undefined || !Number.isFinite(Number(v)) ? '—' : Number(v).toFixed(d); }
function status(msg, kind = '') { const n = $('#status'); n.textContent = msg; n.className = `status ${kind}`; }
async function api(path, body) {
  const r = await fetch(path, body ? {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)} : {});
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw Object.assign(Error(data.message || data.error || `HTTP ${r.status}`), {status: r.status});
  return data;
}
function sizeCanvas(c) { const r = c.getBoundingClientRect(); c.width = Math.max(1, Math.round(r.width * dpr)); c.height = Math.max(1, Math.round(r.height * dpr)); }
function resize() { dpr = window.devicePixelRatio || 1; [canvas, chart, v25, netG, netC, admmC, hCellsC, hChartC, battC].forEach(sizeCanvas); if (!userMoved) fit(); }

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
  if (r.console) lastConsole = r.console;
  if (r.hsel) for (const [id, d] of Object.entries(r.hsel)) (hselHist[id] ??= []).push({t: r.t, d});
  if (r.reroutes?.length) applyReroutes(r.reroutes);
  return {
    v: r.v, n: r.n, k: r.k, t: r.t, rho: r.rho, link_up: r.link_up, attack: r.attack, net: r.net, dtc: r.dtc,
    events: r.events || [], edges: r.edges || [], edges_total: r.edges_total ?? (r.edges || []).length,
    x: r.x.map((v) => v / 10), y: r.y.map((v) => v / 10), speed: r.spd.map((v) => v / 10), progress: r.prog.map((v) => v / 1000),
    layer: ls.map((v) => v & 7), status: ls.map((v) => v >> 3), stats: lastStats,
    admm: r.admm || null, prio: lastPrio, h: lastH, console: lastConsole, merge: r.merge || null, spoof: r.spoof || {}, trust: r.trust || {},
  };
}
// last ADMM negotiation per drone, kept outside the frames so browser thinning never loses it
function indexNeg(r) { for (const [id, v] of Object.entries(r.neg || {})) (negHist[id] ??= []).push(v); }
function lastNeg(id) { const h = negHist[id]; if (!h) return null; for (let i = h.length - 1; i >= 0; i--) if (h[i].t <= simT + 1e-6) return h[i]; return null; }
// browser memory cap: drop every other frame in the older half; events move to the next kept frame
function thinFrames() {
  const cap = LIMITS?.max_frames_in_memory ?? 6000;
  if (frames.length <= cap) return;
  const half = frames.length >> 1, kept = [], keptRaw = [], withRaw = rawFrames.length === frames.length;
  let carry = [], newLog = 0, rc = {events: [], lists: {}, keys: {}};
  frames.forEach((f, i) => {
    const r = withRaw ? rawFrames[i] : null;
    if (i < half && i % 2 === 1) {
      carry.push(...f.events);
      if (r) {   // same rule as streaming.FrameStore._thin: events, injected flights, reroutes and carried keys move forward
        rc.events.push(...(r.events || []));
        for (const k of RAW_LIST_KEYS) if (r[k]?.length) (rc.lists[k] ??= []).push(...r[k]);
        for (const k of RAW_CARRY_KEYS) if (k in r) rc.keys[k] = r[k];
        rawThinned++;
      }
      return;
    }
    if (carry.length) { f.events = carry.concat(f.events); carry = []; }
    if (r) {
      let r2 = r;
      if (rc.events.length || Object.keys(rc.lists).length || Object.keys(rc.keys).length) {
        r2 = {...r, events: rc.events.concat(r.events || [])};
        for (const [k, v] of Object.entries(rc.lists)) r2[k] = v.concat(r[k] || []);
        for (const [k, v] of Object.entries(rc.keys)) if (!(k in r2)) r2[k] = v;
        rc = {events: [], lists: {}, keys: {}};
      }
      keptRaw.push(r2);
    }
    if (i < logCursor) newLog++;
    kept.push(f);
  });
  frames = kept; if (withRaw) rawFrames = keptRaw; logCursor = newLog; eventsIndexed = frames.length;  // all events were indexed on arrival
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
  screenTransform(); ctx.fillStyle = '#f8fafc'; ctx.fillRect(0, 0, w, h);
  if (!MAP) return;
  const s = RUN && frames.length ? frameAt(simT) : null;
  if (follow && s && selected !== null && s.f0.status[selected] === 1) { const p = posOf(s, selected); view.cx = p[0]; view.cy = p[1]; }
  const base = $('#tgContext').checked;
  if (base && backdropImg?.complete && MAP.backdrop) {
    const [x0, y0, x1, y1] = MAP.backdrop.bounds;
    ctx.globalAlpha = 0.9; ctx.drawImage(backdropImg, sx(x0), sy(y1), (x1 - x0) * view.s, (y1 - y0) * view.s); ctx.globalAlpha = 1;
    ctx.fillStyle = 'rgba(255,255,255,0.35)'; ctx.fillRect(0, 0, w, h);
  }
  // geofence
  ctx.strokeStyle = '#ea580cbb'; ctx.setLineDash([7, 5]); ctx.lineWidth = 1.5; ctx.beginPath();
  if (MAP.geofence) MAP.geofence.forEach((p, i) => i ? ctx.lineTo(sx(p[0]), sy(p[1])) : ctx.moveTo(sx(p[0]), sy(p[1])));
  else { const [x0, y0, x1, y1] = MAP.bounds; ctx.rect(sx(x0), sy(y1), (x1 - x0) * view.s, (y1 - y0) * view.s); }
  ctx.closePath(); ctx.stroke(); ctx.setLineDash([]);

  worldTransform(); ctx.lineCap = 'round'; ctx.lineJoin = 'round';
  if (base && !MAP.backdrop) { ctx.strokeStyle = '#cbd5e1'; ctx.lineWidth = 1 / view.s; ctx.stroke(ctxPaths.context); }
  const width = RUN?.limits.corridor_width ?? baseConfig?.corridors.width_meters ?? 20;
  ctx.strokeStyle = 'rgba(109,79,224,0.16)'; ctx.lineWidth = Math.max(width, 2.5 / view.s); ctx.stroke(ctxPaths.corridors);
  ctx.strokeStyle = 'rgba(109,79,224,0.6)'; ctx.lineWidth = 1 / view.s; ctx.stroke(ctxPaths.corridors);
  screenTransform();
  if ($('#tgSectors').checked) drawSectors();
  if (RUN && s && $('#tgRoutes').checked) { ctx.lineWidth = 1; RUN.flights.forEach((f, n) => { if (s.f0.status[n] !== 1) return; ctx.strokeStyle = COLORS[f.type] + '50'; drawRoute(f.route); }); }
  if (RUN && selected !== null) {
    const f = RUN.flights[selected];
    worldTransform(); ctx.strokeStyle = COLORS[f.type] + '40'; ctx.lineWidth = Math.max(RUN.limits.corridor_width, 3 / view.s); ctx.stroke(linesPath([f.route])); screenTransform();
    ctx.strokeStyle = '#0f172a'; ctx.lineWidth = 1.8; drawRoute(f.route);
  }
  drawVertiports(s);
  if (s) { drawJunctions(s); drawDrones(s); drawSpoof(s); }
  drawConsoleOverlay(s);
}
// P3: junctions where a merge is in progress this frame (amber = gap rule blocking, drone slows by 1 - k_v)
function drawJunctions(s) {
  const js = s.f0.merge?.junctions; if (!js?.length) return;
  for (const [x, y, blocked] of js) {
    const X = sx(x), Y = sy(y); ctx.lineWidth = blocked ? 2.4 : 1.4;
    ctx.strokeStyle = blocked ? '#d97706' : 'rgba(8,145,178,0.75)'; ctx.fillStyle = blocked ? 'rgba(217,119,6,0.16)' : 'rgba(8,145,178,0.08)';
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
    ctx.strokeStyle = '#9333ea'; ctx.lineWidth = 1.4; ctx.setLineDash([4, 3]);
    ctx.beginPath(); ctx.moveTo(...T); ctx.lineTo(...R); ctx.stroke();
    ctx.beginPath(); ctx.arc(R[0], R[1], 7, 0, 7); ctx.stroke(); ctx.setLineDash([]);
    const label = (txt, X, Y, col) => { ctx.font = '600 10px system-ui'; ctx.lineWidth = 3; ctx.strokeStyle = '#ffffff'; ctx.strokeText(txt, X, Y); ctx.fillStyle = col; ctx.fillText(txt, X, Y); };
    label(`D-${id} reported (${fmt(v.err_rep, 0)} m off)`, R[0] + 9, R[1] - 6, '#7e22ce');
    if (v.est) {
      const E = [sx(v.est[0]), sy(v.est[1])];
      ctx.strokeStyle = '#059669'; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(E[0] - 5, E[1] - 5); ctx.lineTo(E[0] + 5, E[1] + 5); ctx.moveTo(E[0] + 5, E[1] - 5); ctx.lineTo(E[0] - 5, E[1] + 5); ctx.stroke();
      ctx.setLineDash([2, 3]); ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(...E); ctx.lineTo(...T); ctx.stroke(); ctx.setLineDash([]);
      label(`W-MSR est. (${fmt(v.err_est, 1)} m off, ${v.n} rcv)`, E[0] + 9, E[1] + 12, '#059669');
    }
  }
}
function drawRoute(route) { ctx.beginPath(); route.forEach((p, i) => i ? ctx.lineTo(sx(p[0]), sy(p[1])) : ctx.moveTo(sx(p[0]), sy(p[1]))); ctx.stroke(); }
function drawSectors() {
  const [x0, y0, x1, y1] = MAP.bounds;
  ctx.strokeStyle = '#94a3b8'; ctx.lineWidth = 1; ctx.setLineDash([2, 6]);
  for (let c = 1; c < SECTOR_COLS; c++) { const x = x0 + (x1 - x0) * c / SECTOR_COLS; ctx.beginPath(); ctx.moveTo(sx(x), sy(y0)); ctx.lineTo(sx(x), sy(y1)); ctx.stroke(); }
  for (let r = 1; r < SECTOR_ROWS; r++) { const y = y0 + (y1 - y0) * r / SECTOR_ROWS; ctx.beginPath(); ctx.moveTo(sx(x0), sy(y)); ctx.lineTo(sx(x1), sy(y)); ctx.stroke(); }
  ctx.setLineDash([]); ctx.fillStyle = '#64748b'; ctx.font = '600 11px system-ui';
  for (let r = 0; r < SECTOR_ROWS; r++) for (let c = 0; c < SECTOR_COLS; c++)
    ctx.fillText(`S${r * SECTOR_COLS + c}`, sx(x0 + (x1 - x0) * c / SECTOR_COLS) + 6, sy(y0 + (y1 - y0) * (r + 1) / SECTOR_ROWS) + 14);
}
function drawVertiports(s) {
  const waiting = {}, landed = {};
  if (s && RUN) RUN.flights.forEach((f, n) => { const st = s.f0.status[n]; if (st === 0) waiting[f.origin] = (waiting[f.origin] || 0) + 1; if (st === 2) landed[f.destination] = (landed[f.destination] || 0) + 1; });
  for (const v of MAP.vertiports) {
    const px = sx(v.x), py = sy(v.y);
    ctx.strokeStyle = '#64748b'; ctx.setLineDash([3, 3]); ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(px, py); ctx.lineTo(sx(v.jx), sy(v.jy)); ctx.stroke(); ctx.setLineDash([]);
    const r = 9, col = v.role === 'hospital' ? '#e11d48' : v.role === 'depot' ? '#d97706' : '#0891b2';
    ctx.fillStyle = '#ffffff'; ctx.strokeStyle = col; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.rect(px - r, py - r, 2 * r, 2 * r); ctx.fill(); ctx.stroke();
    ctx.fillStyle = col; ctx.font = '700 11px system-ui'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText(v.role === 'hospital' ? '+' : v.role === 'depot' ? 'D' : 'H', px, py + 0.5);
    ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
    ctx.font = '600 11px system-ui'; ctx.lineWidth = 3; ctx.strokeStyle = '#ffffff'; ctx.strokeText(v.name, px + 13, py - 3); ctx.fillStyle = '#0f172a'; ctx.fillText(v.name, px + 13, py - 3);
    const q = waiting[v.id] || 0, l = landed[v.id] || 0;
    if (q || l) { const t = `${q ? q + ' queued' : ''}${q && l ? ' · ' : ''}${l ? l + ' landed' : ''}`; ctx.font = '10.5px system-ui'; ctx.strokeText(t, px + 13, py + 10); ctx.fillStyle = '#475569'; ctx.fillText(t, px + 13, py + 10); }
  }
}
function drawDrones(s) {
  const f0 = s.f0, n = RUN.flights.length, dmin = RUN.limits.d_min, mal = new Set(f0.attack ? RUN.attack.malicious_ids : []);
  const pos = []; for (let k = 0; k < n; k++) pos.push(f0.status[k] === 1 ? posOf(s, k) : null);
  if ($('#tgLinks').checked && f0.edges) { ctx.strokeStyle = 'rgba(8,145,178,0.35)'; ctx.lineWidth = 1; ctx.beginPath(); for (const [a, b] of f0.edges) { if (!pos[a] || !pos[b]) continue; ctx.moveTo(sx(pos[a][0]), sy(pos[a][1])); ctx.lineTo(sx(pos[b][0]), sy(pos[b][1])); } ctx.stroke(); }
  ctx.setLineDash([4, 3]); ctx.lineWidth = 1.6;
  for (let a = 0; a < n; a++) { if (!pos[a]) continue; for (let b = a + 1; b < n; b++) {
    if (!pos[b] || f0.layer[a] !== f0.layer[b]) continue;
    const d = Math.hypot(pos[a][0] - pos[b][0], pos[a][1] - pos[b][1]);
    if (d < 1.5 * dmin) { ctx.strokeStyle = d < dmin ? '#e11d48' : '#d97706cc'; ctx.beginPath(); ctx.moveTo(sx(pos[a][0]), sy(pos[a][1])); ctx.lineTo(sx(pos[b][0]), sy(pos[b][1])); ctx.stroke(); }
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
      const X = sx(f0.x[k]), Y = sy(f0.y[k]); ctx.strokeStyle = '#ea580c'; ctx.lineWidth = 2.2;
      ctx.beginPath(); ctx.arc(X, Y, 7, 0, 7); ctx.moveTo(X - 5, Y + 5); ctx.lineTo(X + 5, Y - 5); ctx.stroke();
      ctx.fillStyle = '#c2410c'; ctx.font = '700 10px system-ui'; ctx.fillText(`FORCED D-${RUN.flights[k].id}`, X + 9, Y - 6); continue;
    }
    if (st === 3) { // crash marker
      const X = sx(f0.x[k]), Y = sy(f0.y[k]); ctx.strokeStyle = '#dc2626'; ctx.lineWidth = 3;
      ctx.beginPath(); ctx.moveTo(X - 7, Y - 7); ctx.lineTo(X + 7, Y + 7); ctx.moveTo(X + 7, Y - 7); ctx.lineTo(X - 7, Y + 7); ctx.stroke();
      ctx.fillStyle = '#e11d48'; ctx.font = '700 10px system-ui'; ctx.fillText(`CRASH D-${RUN.flights[k].id}`, X + 9, Y - 6); continue;
    }
    if (!pos[k]) continue;
    const f = RUN.flights[k], L = f0.layer[k], dim = layerFilter !== 'all' && L !== Number(layerFilter);
    const X = sx(pos[k][0]), Y = sy(pos[k][1]), hd = headingOf(s, k), r = size * (0.85 + 0.12 * L);
    ctx.save(); ctx.translate(X, Y); ctx.rotate(-hd); ctx.globalAlpha = dim ? 0.18 : 1;
    ctx.fillStyle = COLORS[f.type]; ctx.strokeStyle = '#1e293b'; ctx.lineWidth = 1.2;
    ctx.beginPath(); ctx.moveTo(r * 1.35, 0); ctx.lineTo(-r * 0.8, r * 0.75); ctx.lineTo(-r * 0.35, 0); ctx.lineTo(-r * 0.8, -r * 0.75); ctx.closePath(); ctx.fill(); ctx.stroke();
    ctx.restore();
    if (!dim && view.s > 0.45) { ctx.font = '9.5px ui-monospace,monospace'; ctx.lineWidth = 3; ctx.strokeStyle = '#ffffff'; ctx.strokeText(`L${L}`, X + r + 2, Y - r); ctx.fillStyle = '#0f172a'; ctx.fillText(`L${L}`, X + r + 2, Y - r); }
    const hb = f0.h?.bms?.[k] ?? 0, hs = f0.h?.soc?.[k];
    if (!dim && hb > 0) { ctx.strokeStyle = BMS_COL[hb]; ctx.lineWidth = hb >= 2 ? 2.4 : 1.6; ctx.beginPath(); ctx.arc(X, Y, r + 3.5, 0, 7); ctx.stroke(); }
    if (!dim && hs !== undefined && hs < 30) { // low-battery glyph
      ctx.fillStyle = '#ffffff'; ctx.fillRect(X - r - 12, Y - 4, 9, 6); ctx.strokeStyle = hs < 15 ? '#e11d48' : '#d97706'; ctx.lineWidth = 1; ctx.strokeRect(X - r - 12, Y - 4, 9, 6);
      ctx.fillStyle = ctx.strokeStyle; ctx.fillRect(X - r - 11, Y - 3, Math.max(1, 7 * hs / 100), 4); ctx.fillRect(X - r - 3, Y - 2, 1.5, 2);
    }
    if (mal.has(f.id)) { ctx.strokeStyle = '#9333ea'; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(X, Y, r + 5 + 2 * Math.sin(performance.now() / 180), 0, 7); ctx.stroke(); }
    if (f.custom && !dim) { // scripted case-study drone: amber dashed halo + star label
      ctx.strokeStyle = '#f59e0b'; ctx.lineWidth = 2.5; ctx.setLineDash([4, 2]); ctx.beginPath(); ctx.arc(X, Y, r + 11, 0, 7); ctx.stroke(); ctx.setLineDash([]);
      if (k !== selected) { const t = `\u2605 D-${f.id}`; ctx.font = '700 11px system-ui'; ctx.lineWidth = 3; ctx.strokeStyle = '#ffffff'; ctx.strokeText(t, X + r + 12, Y + 4); ctx.fillStyle = '#b45309'; ctx.fillText(t, X + r + 12, Y + 4); }
    }
    if (k === selected) { ctx.strokeStyle = '#0f172a'; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(X, Y, r + 8, 0, 7); ctx.stroke();
      ctx.font = '700 11.5px system-ui'; ctx.lineWidth = 3; ctx.strokeStyle = '#ffffff'; ctx.strokeText(`D-${f.id} ${TYPE_SHORT[f.type]}`, X + r + 10, Y + 4); ctx.fillStyle = '#0f172a'; ctx.fillText(`D-${f.id} ${TYPE_SHORT[f.type]}`, X + r + 10, Y + 4); }
  }
}

// ------------------------------------------------------------------ 2.5D view of the selected drone
function draw25(s) {
  const w = v25.clientWidth, h = v25.clientHeight; screenTransform(vctx); vctx.clearRect(0, 0, w, h);
  if (w < 40 || h < 40) return;   // Health tab open: the 2.5D view is hidden
  if (!RUN || !s || selected === null) { vctx.fillStyle = '#64748b'; vctx.font = '12px system-ui'; vctx.fillText('Select a drone on the map or network graph.', 12, 24); return; }
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
  vctx.fillStyle = '#f1f5f9'; vctx.strokeStyle = '#cbd5e1'; vctx.lineWidth = 1; vctx.beginPath();
  [[-R, -R], [R, -R], [R, R], [-R, R]].forEach(([a, b], i) => { const p = corner(a, b); i ? vctx.lineTo(...p) : vctx.moveTo(...p); }); vctx.closePath(); vctx.fill(); vctx.stroke();
  vctx.strokeStyle = 'rgba(109,79,224,0.5)'; vctx.lineWidth = 1;
  for (const line of MAP.corridors) for (let i = 1; i < line.length; i++) {
    const a = line[i - 1], b = line[i]; if (!inWin(a[0], a[1]) && !inWin(b[0], b[1])) continue;
    vctx.beginPath(); vctx.moveTo(...G(Math.max(c[0] - R, Math.min(c[0] + R, a[0])), Math.max(c[1] - R, Math.min(c[1] + R, a[1])))); vctx.lineTo(...G(Math.max(c[0] - R, Math.min(c[0] + R, b[0])), Math.max(c[1] - R, Math.min(c[1] + R, b[1])))); vctx.stroke();
  }
  for (const v of MAP.vertiports) if (inWin(v.x, v.y)) { const p = G(v.x, v.y); vctx.fillStyle = '#334155'; vctx.fillRect(p[0] - 4, p[1] - 3, 8, 6); vctx.font = '9px system-ui'; vctx.fillText(v.name, p[0] + 6, p[1] + 3); }
  // layer planes
  for (let l = 0; l < L; l++) {
    vctx.fillStyle = l === RUN.limits.emergency_layer ? 'rgba(225,29,72,0.06)' : 'rgba(8,145,178,0.05)';
    vctx.strokeStyle = l === f0.layer[n] ? 'rgba(15,23,42,0.45)' : 'rgba(100,116,139,0.28)';
    vctx.beginPath(); [[-R, -R], [R, -R], [R, R], [-R, R]].forEach(([a, b], i) => { const p = P(c[0] + a, c[1] + b, l); i ? vctx.lineTo(...p) : vctx.moveTo(...p); }); vctx.closePath(); vctx.fill(); vctx.stroke();
    const lab = P(c[0] + R, c[1] - R, l); vctx.fillStyle = l === f0.layer[n] ? '#0f172a' : '#64748b'; vctx.font = '10px ui-monospace,monospace';
    vctx.fillText(`L${l} ${altOf(l)}m${l === RUN.limits.emergency_layer ? '⚕' : ''}`, lab[0] + 4, lab[1] + 3);
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
    vctx.strokeStyle = sel ? '#0f172aaa' : '#0f172a30'; vctx.lineWidth = 1; vctx.setLineDash([2, 3]); vctx.beginPath(); vctx.moveTo(...gr); vctx.lineTo(...top); vctx.stroke(); vctx.setLineDash([]);
    vctx.fillStyle = '#0f172a40'; vctx.beginPath(); vctx.ellipse(gr[0], gr[1], 4, 2, 0, 0, 7); vctx.fill();
    if (sel) { vctx.strokeStyle = '#0f172a70'; vctx.beginPath(); vctx.ellipse(top[0], top[1], RUN.limits.d_min * 0.99 * k, RUN.limits.d_min * 0.51 * k, 0, 0, 7); vctx.stroke(); }
    if (crashed) { vctx.strokeStyle = '#dc2626'; vctx.lineWidth = 2.5; vctx.beginPath(); vctx.moveTo(gr[0] - 6, gr[1] - 6); vctx.lineTo(gr[0] + 6, gr[1] + 6); vctx.moveTo(gr[0] + 6, gr[1] - 6); vctx.lineTo(gr[0] - 6, gr[1] + 6); vctx.stroke(); continue; }
    vctx.fillStyle = COLORS[g.type]; vctx.strokeStyle = sel ? '#0f172a' : '#1e293b'; vctx.lineWidth = sel ? 2 : 1;
    vctx.beginPath(); vctx.arc(top[0], top[1], sel ? 6.5 : 4.5, 0, 7); vctx.fill(); vctx.stroke();
    if (sel && f0.status[m] === 1) { const hd = headingOf(s, m), tip = P(p[0] + Math.cos(hd) * 22, p[1] + Math.sin(hd) * 22, lay); vctx.strokeStyle = '#0f172a'; vctx.lineWidth = 2; vctx.beginPath(); vctx.moveTo(...top); vctx.lineTo(...tip); vctx.stroke(); }
    vctx.fillStyle = sel ? '#0f172a' : '#475569'; vctx.font = sel ? '700 11px system-ui' : '9.5px system-ui'; vctx.fillText(`D-${g.id}`, top[0] + 7, top[1] - 6);
  }
  vctx.fillStyle = '#64748b'; vctx.font = '10px system-ui'; vctx.fillText(`${2 * R} m window · ring = d_min · stems to ground`, 8, h - 6);
  if (st !== 1) { vctx.fillStyle = st === 3 ? '#e11d48' : '#64748b'; vctx.font = '600 12px system-ui'; vctx.fillText(st === 3 ? 'CRASHED' : st === 0 ? 'On the pad — waiting to depart' : 'Landed', 10, 18); }
}

// ------------------------------------------------------------------ panels
function updatePanels() {
  if (!RUN || !frames.length) return;
  const s = frameAt(simT), f = s.f0, st = f.stats;
  const cnt = [0, 0, 0, 0, 0]; f.status.forEach((x) => cnt[x]++);
  $('#cntQueue').textContent = cnt[0]; $('#cntAir').textContent = cnt[1]; $('#cntLand').textContent = cnt[2]; $('#cntCrash').textContent = cnt[3]; $('#cntForced').textContent = cnt[4];
  if (st.delivered !== undefined) {
    $('#kEnergy').textContent = st.energy_per_delivered_wh === null || st.energy_per_delivered_wh === undefined ? '—' : `${fmt(st.energy_per_delivered_wh, 0)} Wh`;
    const bt = st.energy_per_delivered_by_type_wh || {};
    $('#kEnergySub').textContent = `per parcel delivery · eVTOL ${bt.EVTOL === undefined ? '—' : fmt(bt.EVTOL / 1000, 2) + ' kWh'} · EMG ${bt.EMERGENCY === undefined ? '—' : fmt(bt.EMERGENCY, 0) + ' Wh'} per mission · max pack ${fmt(st.max_pack_c, 0)} °C`;
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
    $('#kPrioSub').textContent = `${pr.count} EMG · delay ${pr.mean_delay_s === null ? '—' : fmt(pr.mean_delay_s) + ' s'} (${pr.arrived} landed) · on time ${pr.on_time_rate === null || pr.on_time_rate === undefined ? '—' : fmt(pr.on_time_rate * 100, 0) + '%'} · ground hold ${pr.mean_ground_hold_s === null || pr.mean_ground_hold_s === undefined ? '—' : fmt(pr.mean_ground_hold_s) + ' s'}`;
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
  $('#runState').textContent = RUN.replay ? 'LOADED' : done && simT >= frames.at(-1).t - 1e-6 ? (RUN.stopped ? 'STOPPED' : 'COMPLETE') : done ? 'REPLAY' : 'LIVE';
  updateOccupancy(s); updateDrone(s); pumpLog(); updateFleetHealth(s); if (dTab === 'hl') updateHealthTab(s); updateConsole(s); updateCompare();
  const canInject = !RUN.replay && !done; if ($('#cdNow').disabled === canInject) $('#cdNow').disabled = !canInject;
}
function updateOccupancy(s) {
  const L = RUN.limits.num_layers, cap = RUN.limits.capacity, occ = Array.from({length: SECTOR_COLS * SECTOR_ROWS}, () => Array(L).fill(0));
  RUN.flights.forEach((_, n) => { if (s.f0.status[n] === 1) occ[sectorOf(s.f0.x[n], s.f0.y[n])][s.f0.layer[n]]++; });
  let html = '<tr><th>Sector</th>' + Array.from({length: L}, (_, l) => `<th>L${l}${l === RUN.limits.emergency_layer ? ' ⚕' : ''}</th>`).join('') + '</tr>';
  occ.forEach((row, sid) => { html += `<tr><td>S${sid}</td>` + row.map((v) => { const u = v / cap, bg = v === 0 ? 'transparent' : u >= 1 ? '#fecdd3' : u > 0.6 ? '#fde68a' : '#cffafe'; return `<td style="background:${bg}">${v}</td>`; }).join('') + '</tr>'; });
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
  $('#dLayer').textContent = `L${fr.layer[n]} · ≈${altOf(fr.layer[n])} m AGL`;
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
function select(n, add = false) {
  if (n === null || n < 0 || !RUN) return;
  if (add) { if (selSet.has(n) && selSet.size > 1) selSet.delete(n); else selSet.add(n); } else selSet = new Set([n]);
  selected = n; lastDroneFeedKey = ''; renderSel();
}

// ------------------------------------------------------------------ STL chart
function drawChart() {
  const w = chart.clientWidth, h = chart.clientHeight; screenTransform(cctx); cctx.clearRect(0, 0, w, h);
  if (!RUN || !frames.length) { cctx.fillStyle = '#64748b'; cctx.font = '12px system-ui'; cctx.fillText('Launch a simulation to monitor G(d ≥ d_min).', 12, 24); return; }
  const L = 36, R = w - 10, T = 10, B = h - 22, lo = -RUN.limits.d_min, hi = 40;
  const X = (t) => L + (t / RUN.duration_s) * (R - L), Y = (v) => B - (Math.max(lo, Math.min(hi, v)) - lo) / (hi - lo) * (B - T);
  cctx.strokeStyle = '#e2e8f0'; cctx.lineWidth = 1; cctx.fillStyle = '#64748b'; cctx.font = '10px system-ui';
  for (const v of [lo, 0, 10, 20, 30, 40]) { cctx.beginPath(); cctx.moveTo(L, Y(v)); cctx.lineTo(R, Y(v)); cctx.stroke(); cctx.fillText(String(v), 6, Y(v) + 3); }
  cctx.fillStyle = 'rgba(225,29,72,0.07)'; cctx.fillRect(L, Y(0), R - L, B - Y(0));
  shadeEvents(cctx, X, T, B);
  cctx.strokeStyle = '#e11d48aa'; cctx.setLineDash([4, 4]); cctx.beginPath(); cctx.moveTo(L, Y(0)); cctx.lineTo(R, Y(0)); cctx.stroke(); cctx.setLineDash([]);
  cctx.lineWidth = 1.6; cctx.beginPath(); let pen = false, worst = Infinity;
  for (const f of frames) { if (f.rho === null) { pen = false; continue; } worst = Math.min(worst, f.rho); pen ? cctx.lineTo(X(f.t), Y(f.rho)) : cctx.moveTo(X(f.t), Y(f.rho)); pen = true; }
  cctx.strokeStyle = worst < 0 ? '#e11d48' : '#059669'; cctx.stroke();
  for (const f of frames) for (const e of f.events) if (e.kind === 'crash') { cctx.fillStyle = '#dc2626'; cctx.font = '700 12px system-ui'; cctx.fillText('✕', X(e.t) - 4, B - 2); }
  cctx.strokeStyle = '#0f172a'; cctx.lineWidth = 1; cctx.beginPath(); cctx.moveTo(X(simT), T); cctx.lineTo(X(simT), B); cctx.stroke();
  cctx.fillStyle = '#64748b'; cctx.fillText('0 s', L, h - 6); cctx.textAlign = 'right'; cctx.fillText(`${RUN.duration_s} s`, R, h - 6); cctx.textAlign = 'left';
}
function shadeEvents(c, X, T, B) {
  if (RUN.outage.enabled) { c.fillStyle = 'rgba(109,79,224,0.10)'; c.fillRect(X(RUN.outage.start_s), T, X(RUN.outage.end_s) - X(RUN.outage.start_s), B - T); c.fillStyle = '#6d4fe0'; c.font = '10px system-ui'; c.fillText('DTC link down', X(RUN.outage.start_s) + 4, T + 10); }
  if (RUN.attack.enabled) { c.strokeStyle = '#9333ea'; c.setLineDash([3, 3]); c.beginPath(); c.moveTo(X(RUN.attack.start_s), T); c.lineTo(X(RUN.attack.start_s), B); c.stroke(); c.setLineDash([]); c.fillStyle = '#9333ea'; c.font = '10px system-ui'; c.fillText('attack', X(RUN.attack.start_s) + 4, B - 4); }
}

// ------------------------------------------------------------------ network theory panel
function drawNetwork(s) {
  const w = netG.clientWidth, h = netG.clientHeight; screenTransform(nctx); nctx.clearRect(0, 0, w, h);
  netPositions = null;
  if (!RUN || !s) { nctx.fillStyle = '#64748b'; nctx.font = '12px system-ui'; nctx.fillText('Network appears once drones are airborne.', 12, 24); return; }
  const f0 = s.f0, [x0, y0, x1, y1] = MAP.bounds, pad = 16, top = 46;
  const k = Math.min((w - 2 * pad) / (x1 - x0), (h - top - pad) / (y1 - y0));
  const ox = (w - (x1 - x0) * k) / 2, oy = top + (h - top - pad - (y1 - y0) * k) / 2;
  const P = (x, y) => [ox + (x - x0) * k, oy + (y1 - y) * k];
  const hub = [w / 2, 20], dtc = f0.dtc || {}, linkUp = RUN.switches.use_overseer && dtc.link_up;
  const pos = RUN.flights.map((_, n) => f0.status[n] === 1 ? P(...posOf(s, n)) : null);
  netPositions = pos;
  // campus outline
  if (MAP.geofence) { nctx.strokeStyle = '#cbd5e1'; nctx.lineWidth = 1; nctx.beginPath(); MAP.geofence.forEach((p, i) => i ? nctx.lineTo(...P(p[0], p[1])) : nctx.moveTo(...P(p[0], p[1]))); nctx.closePath(); nctx.stroke(); }
  // DTC -> drone directive links
  if (RUN.switches.use_overseer) {
    nctx.lineWidth = 0.7; nctx.strokeStyle = linkUp ? 'rgba(109,79,224,0.22)' : 'rgba(225,29,72,0.28)'; if (!linkUp) nctx.setLineDash([3, 4]);
    nctx.beginPath(); for (const p of pos) if (p) { nctx.moveTo(...hub); nctx.lineTo(...p); } nctx.stroke(); nctx.setLineDash([]);
  }
  // V2V edges
  nctx.strokeStyle = 'rgba(8,145,178,0.8)'; nctx.lineWidth = 1.4; nctx.beginPath();
  for (const [a, b] of f0.edges || []) if (pos[a] && pos[b]) { nctx.moveTo(...pos[a]); nctx.lineTo(...pos[b]); } nctx.stroke();
  const deg = new Array(RUN.flights.length).fill(0); for (const [a, b] of f0.edges || []) { deg[a]++; deg[b]++; }
  pos.forEach((p, n) => { if (!p) return; const f = RUN.flights[n]; nctx.fillStyle = COLORS[f.type]; nctx.beginPath(); nctx.arc(p[0], p[1], 2.5 + Math.min(5, deg[n] * 1.2), 0, 7); nctx.fill();
    if (n === selected) { nctx.strokeStyle = '#0f172a'; nctx.lineWidth = 2; nctx.beginPath(); nctx.arc(p[0], p[1], 9, 0, 7); nctx.stroke(); }
    if (f0.net?.hub === f.id) { nctx.strokeStyle = '#d97706'; nctx.lineWidth = 1.5; nctx.beginPath(); nctx.arc(p[0], p[1], 12, 0, 7); nctx.stroke(); } });
  // DTC hub node
  nctx.fillStyle = !RUN.switches.use_overseer ? '#94a3b8' : linkUp ? '#6d4fe0' : '#e11d48';
  nctx.beginPath(); nctx.arc(hub[0], hub[1], 12, 0, 7); nctx.fill();
  nctx.fillStyle = '#ffffff'; nctx.font = '800 9px system-ui'; nctx.textAlign = 'center'; nctx.fillText('DTC', hub[0], hub[1] + 3); nctx.textAlign = 'left';
  nctx.fillStyle = '#475569'; nctx.font = '10.5px system-ui';
  nctx.fillText(!RUN.switches.use_overseer ? 'DTC disabled (decentralized)' : linkUp ? `DTC link UP · ${dtc.connected} drones under control` : `DTC link DOWN · drones on cached directive (${fmt(dtc.staleness_s, 0)} s old)`, hub[0] + 18, hub[1] + 4);
  // stats
  const m = f0.net || {};
  const row = (k, v) => `<dt>${k}</dt><dd>${v}</dd>`;
  $('#netStats').innerHTML = '<span class="hdr">V2V graph</span>' + row('Nodes · edges', `${m.nodes ?? 0} · ${m.edges ?? 0}`) + row('Avg degree', fmt(m.avg_degree, 2)) + row('Density', fmt(m.density, 3))
    + row('Transitivity', fmt(m.transitivity, 3)) + row('Max centrality', `${fmt(m.max_degree_centrality, 3)}${m.hub !== null && m.hub !== undefined ? ' · D-' + m.hub : ''}`)
    + row('Components', `${m.components ?? 0} (${m.isolated ?? 0} isolated)`) + row('Giant component', `${fmt((m.largest_component ?? 0) * 100, 0)}%`) + row('Alg. connectivity λ₂', `${fmt(m.algebraic_connectivity, 3)}${(m.components ?? 0) > 1 ? ` (disconnected; giant ${fmt(m.algebraic_connectivity_giant ?? 0, 3)})` : ''}`)
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
  ncctx.strokeStyle = '#e2e8f0'; ncctx.fillStyle = '#64748b'; ncctx.font = '10px system-ui';
  for (const v of [0, 0.5, 1]) { ncctx.beginPath(); ncctx.moveTo(L, Y(v)); ncctx.lineTo(R, Y(v)); ncctx.stroke(); ncctx.fillText(v.toFixed(1), 4, Y(v) + 3); }
  shadeEvents(ncctx, X, T, B);
  const rows = netRows(), maxDeg = netCache.maxDeg, step = Math.max(1, Math.floor(rows.length / 700));
  for (const ser of NET_SERIES) {
    ncctx.strokeStyle = ser.color; ncctx.lineWidth = ser.key === 'cover' ? 2.2 : 1.4; ncctx.beginPath(); let pen = false;
    for (let i = 0; i < rows.length; i += step) { const v = rows[i][ser.key]; if (v === null || v === undefined) { pen = false; continue; } pen ? ncctx.lineTo(X(rows[i].t), Y(v)) : ncctx.moveTo(X(rows[i].t), Y(v)); pen = true; }
    ncctx.stroke();
  }
  ncctx.strokeStyle = '#0f172a'; ncctx.lineWidth = 1; ncctx.beginPath(); ncctx.moveTo(X(simT), T); ncctx.lineTo(X(simT), B); ncctx.stroke();
  ncctx.fillStyle = '#64748b'; ncctx.fillText('0 s', L, h - 5); ncctx.textAlign = 'right'; ncctx.fillText(`${RUN.duration_s} s · max avg degree ${maxDeg.toFixed(1)}`, R, h - 5); ncctx.textAlign = 'left';
}

// ------------------------------------------------------------------ P2 ADMM convergence timer
function drawAdmm() {
  const w = admmC.clientWidth, h = admmC.clientHeight; screenTransform(actx); actx.clearRect(0, 0, w, h);
  const s = RUN && frames.length ? frameAt(simT) : null, run = s?.f0.admm?.run;
  const row = (k, v) => `<dt>${k}</dt><dd>${v}</dd>`;
  if (!RUN || !s) { $('#admmStats').innerHTML = ''; return; }
  if (!RUN.switches.use_admm) {
    actx.fillStyle = '#64748b'; actx.font = '12px system-ui'; actx.fillText(RUN.architecture === 'centralized' ? 'Centralized architecture: the DTC computes velocities, no ADMM.' : 'ADMM is switched off for this run.', 12, 24);
    $('#admmStats').innerHTML = ''; return;
  }
  const L = 30, R = w - 40, T = 8, B = h - 20, X = (t) => L + (t / RUN.duration_s) * (R - L);
  const step = Math.max(1, Math.floor(frames.length / 900));
  let itMax = 1, msMax = 0.05;
  for (const f of frames) { if (f.admm?.it_max) itMax = Math.max(itMax, f.admm.it_max); if (f.admm?.ms_mean) msMax = Math.max(msMax, f.admm.ms_mean); }
  itMax = Math.ceil(itMax * 1.15); msMax *= 1.15;
  const Yi = (v) => B - (v / itMax) * (B - T), Ym = (v) => B - (v / msMax) * (B - T);
  actx.strokeStyle = '#e2e8f0'; actx.fillStyle = '#64748b'; actx.font = '10px system-ui'; actx.lineWidth = 1;
  for (const v of [0, Math.round(itMax / 2), itMax]) { actx.beginPath(); actx.moveTo(L, Yi(v)); actx.lineTo(R, Yi(v)); actx.stroke(); actx.fillText(String(v), 6, Yi(v) + 3); }
  actx.textAlign = 'left'; for (const v of [0, msMax / 2, msMax]) actx.fillText(`${v.toFixed(2)}ms`, R + 4, Ym(v) + 3);
  const line = (get, Y, col, wd) => { actx.strokeStyle = col; actx.lineWidth = wd; actx.beginPath(); let pen = false;
    for (let i = 0; i < frames.length; i += step) { const v = get(frames[i]); if (v === null || v === undefined) { pen = false; continue; } pen ? actx.lineTo(X(frames[i].t), Y(v)) : actx.moveTo(X(frames[i].t), Y(v)); pen = true; } actx.stroke(); };
  line((f) => f.admm?.it_max, Yi, '#059669aa', 1);
  line((f) => f.admm?.it_mean, Yi, '#0891b2', 1.6);
  line((f) => f.admm?.ms_mean, Ym, '#d97706', 1.2);
  actx.fillStyle = '#e11d48'; for (const f of frames) if (f.admm?.fail) actx.fillRect(X(f.t) - 1, B - 6, 2, 6);
  actx.strokeStyle = '#0f172a'; actx.lineWidth = 1; actx.beginPath(); actx.moveTo(X(simT), T); actx.lineTo(X(simT), B); actx.stroke();
  actx.fillStyle = '#64748b'; actx.fillText('0 s', L, h - 5); actx.textAlign = 'right'; actx.fillText(`${RUN.duration_s} s`, R, h - 5); actx.textAlign = 'left';
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
  const wx = readWeather();
  if (wx) set(config, 'drone_health.ambient_c', wx.t), set(config, 'drone_health.wind_mps', wx.wind);
  if (wx?.profile) set(config, 'drone_health.weather_profile', profilePoints(wx.profile, wx.dir, duration));
  return {map: mapId, fleet, duration_s: duration, seed, departure_window_s: Math.min(win, duration), mix, config,
    architecture: $('#arch').value, junction_merge: $('#swMerge').checked, drones: customDrones,
    use_overseer: $('#swOverseer').checked, use_admm: $('#swAdmm').checked, defended: $('#swDefense').checked,
    attack: {enabled: $('#swAttack').checked, count: 2, start_s: Math.round(duration * 0.2)},
    outage: {enabled: $('#swOutage').checked, start_s: Math.round(duration * 0.25), end_s: Math.round(duration * 0.6)}};
}
async function launch(presetReq = null) {
  let req; try { req = presetReq || buildRequest(); } catch (e) { status(e.message, 'err'); return; }
  lastReq = req; $('#relaunchBtn').hidden = true;
  $('#runBtn').disabled = true; status('Planning routes on the corridor graph…');
  try {
    // `replaces`: this page's previous run is stopped once the new one is accepted; other people's runs are not touched
    const run = await api('/api/runs', {...req, ...(RUN && !RUN.replay && !done ? {replaces: RUN.run_id} : {})});
    const header = run.export_header; delete run.export_header;
    runStart = {manifest: structuredClone(run), header}; rawFrames = []; rawThinned = 0;   // manifest before the page edits it
    const names = Object.fromEntries(MAP.vertiports.map((v) => [v.id, v.name]));
    run.flights.forEach((f) => { f.origin_name = names[f.origin]; f.destination_name = names[f.destination]; });
    RUN = run; frames = []; done = false; simT = 0; playing = true; droneEvents = {}; eventsIndexed = 0;
    nextSeq = 0; lastStats = null; lastPrio = null; lastH = null; lastConsole = null; hselHist = {}; speedProbe = []; negHist = {}; selSet = new Set(); cmdHist = [];
    selected = Math.max(0, run.flights.findIndex((f) => f.type === 'EMERGENCY'));
    renderSel(); $('#ccHist').replaceChildren(); resetLog(); $('#playBtn').textContent = '❚❚'; $('#seedLabel').innerHTML = `seed ${run.seed} · ${ARCH[run.architecture]?.label ?? run.architecture} · <span class="ic" title="Initial-conditions hash: identical for the same seed, fleet and map in every architecture">IC ${run.ic_hash}</span>`; $('#tMax').textContent = `/ ${run.duration_s} s`;
    $('#sceneTitle').textContent = run.preset ? `Preset · ${run.preset.title}` : SCENES[scene].title; buildLayerSeg(); buildDronePick(); cmpAt = 0;
    if (run.preset?.names) for (const [nm, id] of Object.entries(run.preset.names)) { const f = run.flights.find((x) => x.id === id); if (f) f.task = `@${nm} · ${f.task}`; }
    status(`Run ${run.run_id}: ${run.flights.length} flights planned on ${MAP.label} corridors — streaming from the simulator.`, 'ok');
    poll(run.run_id);
  } catch (e) {
    status(e.message, 'err');
    if (e.status === 503) { $('#relaunchBtn').hidden = false; if (!RUN || done) $('#runState').textContent = 'BUSY'; }
    else $('#runState').textContent = 'ERROR';
  }
  finally { $('#runBtn').disabled = false; }
}
$('#relaunchBtn').onclick = () => launch(lastReq);
async function poll(id) {
  try {
    while (RUN && RUN.run_id === id) {
      const selId = selected !== null && RUN.flights[selected] ? `&sel=${RUN.flights[selected].id}` : '';
      const r = await api(`/api/runs/${id}/frames?from=${nextSeq}&view_t=${simT.toFixed(2)}${selId}`);
      if (!RUN || RUN.run_id !== id) break;
      nextSeq = r.next;
      if (r.frames.length) {
        rawFrames.push(...r.frames);
        frames.push(...r.frames.map((x) => { indexNeg(x); return decodeFrame(x); })); indexEvents(); thinFrames();
        speedProbe.push([performance.now(), frames.at(-1).t]); if (speedProbe.length > 20) speedProbe.shift();
      }
      if (r.error) { status(`Simulation error: ${r.error}`, 'err'); done = true; break; }
      if (r.done && r.stopped) {   // ended before its end time: say so instead of "complete"
        done = true; RUN.stopped = r.stopped; $('#relaunchBtn').hidden = false;
        status(`Run stopped at ${fmt(frames.at(-1)?.t ?? 0)} of ${RUN.duration_s} s — ${r.stopped}. Relaunch to start it again.`, 'err'); break;
      }
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
  buildMapSeg(); userMoved = false; fit(); cdFillSelects(); consoleFill();
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
const KPI_STATS = ['arrivals', 'crashes', 'near_misses', 'safety_violation_ticks', 'min_separation_m', 'admm_events',
  'admm_nonconverged', 'tactical_layer_shifts', 'dtc_directives', 'layer_changes', 'pad_holds',
  'reports_dropped', 'spoofed_reports_accepted', 'tube_corrections',
  'delivered', 'diversions', 'forced_landings', 'energy_depleted', 'grounded_preflight',
  'energy_used_wh', 'energy_per_delivered_wh', 'max_pack_c', 'max_motor_c', 'bms_alerts'];
function kpiRows(fr) {   // same rows as web_sandbox/run_export.py kpi_rows
  let stats = {}, prio = {};
  return fr.map((f) => {
    if ('stats' in f) stats = f.stats; prio = f.prio || prio;
    const admm = f.admm?.run ?? {}, merge = f.merge || {};
    return {t: f.t, rho: f.rho ?? null, airborne: (f.ls || []).filter((v) => v >> 3 === 1).length,
      ...Object.fromEntries(KPI_STATS.map((k) => [k, stats?.[k] ?? null])),
      admm_it_p95: admm.it_p95 ?? null, admm_ms_p95: admm.ms_p95 ?? null, admm_fallback: admm.fallback ?? null,
      priority_compliance: prio.rate ?? null, emergency_mean_delay_s: prio.mean_delay_s ?? null,
      merge_success_rate: merge.rate ?? null, platoons: merge.platoons ?? null};
  });
}
$('#dlBtn').onclick = async () => {
  if (!RUN || RUN.replay) { status(RUN?.replay ? 'This run was loaded from a file — it is already saved.' : 'Launch a run first.', 'err'); return; }
  if (!rawFrames.length || !runStart) { status('No frames received yet — wait a moment and try again.', 'err'); return; }
  status('Preparing the download in this browser…');
  let hdr = null;
  try { hdr = await api(`/api/runs/${RUN.run_id}/export?frames=0`); } catch { /* run gone (server restarted): use the header kept at launch */ }
  const h = runStart.header || {};
  const out = {
    format: 'masooda-run', version: 1,
    complete: done && !RUN.stopped && (hdr ? hdr.complete : true),   // the page must also hold the last frame
    frames_thinned: rawThinned, config_hash: hdr?.config_hash ?? h.config_hash,
    manifest: hdr?.manifest ?? runStart.manifest, request: hdr?.request ?? h.request, config: hdr?.config ?? h.config,
    commands: hdr?.commands ?? cmdHist,
    frames: rawFrames, kpis: kpiRows(rawFrames), events: rawFrames.flatMap((f) => f.events || []),
  };
  const url = URL.createObjectURL(new Blob([JSON.stringify(out)], {type: 'application/json'}));
  const a = document.createElement('a'); a.href = url; a.download = `masooda_run_${RUN.run_id}.json`;
  document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 60000);
  status(`${out.complete ? 'Run downloaded' : 'Partial run downloaded (frames received so far)'} — ${rawFrames.length} frames, `
    + `built in this browser${hdr ? '' : ' (simulator no longer has this run: header and command log kept by the page)'}.`, 'ok');
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
    RUN = {...m, run_id: `replay:${m.run_id}`, replay: true}; rawFrames = []; runStart = null; frames = []; done = true; simT = 0; playing = true; droneEvents = {}; eventsIndexed = 0;
    nextSeq = 0; lastStats = null; lastPrio = null; lastH = null; lastConsole = null; hselHist = {}; speedProbe = []; negHist = {}; selSet = new Set(); cmdHist = [];
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
  drawMap(); updatePanels(); updateSections(s);
  // only the open section's canvases are drawn (hidden ones are 1 px; drawing them is wasted work)
  if (shown('drone')) draw25(s);
  if (shown('network')) drawNetwork(s);
  if (RUN && frames.length) {
    if (shown('safety')) drawChart();
    if (shown('network')) drawNetChart();
    if (shown('admm')) drawAdmm();
    if (shown('health')) drawBatt(s);
  }
  requestAnimationFrame(tick);
}

// ------------------------------------------------------------------ interaction
function pick(px, py) {
  if (!RUN || !frames.length) return null; const s = frameAt(simT); let best = null, bd = 16;
  RUN.flights.forEach((_, n) => { const st = s.f0.status[n]; if (st !== 1 && st !== 3) return; const p = st === 1 ? posOf(s, n) : [s.f0.x[n], s.f0.y[n]], d = Math.hypot(sx(p[0]) - px, sy(p[1]) - py); if (d < bd) { bd = d; best = n; } });
  return best;
}
let drag = null;
canvas.addEventListener('pointerdown', (e) => {
  if (e.button === 2) return;
  const r = canvas.getBoundingClientRect();
  if (tfrRect) { const p = [wx(e.clientX - r.left), wy(e.clientY - r.top)]; tfrRect.a = p; tfrRect.b = p; canvas.setPointerCapture(e.pointerId); updateDrawHint(); return; }
  if (e.ctrlKey || e.metaKey || e.altKey) { boxSel = {x0: e.clientX - r.left, y0: e.clientY - r.top, x1: e.clientX - r.left, y1: e.clientY - r.top}; canvas.classList.add('boxing'); canvas.setPointerCapture(e.pointerId); return; }
  drag = {x: e.clientX, y: e.clientY, cx: view.cx, cy: view.cy, moved: false}; canvas.setPointerCapture(e.pointerId);
});
canvas.addEventListener('pointermove', (e) => {
  const r = canvas.getBoundingClientRect(), px = e.clientX - r.left, py = e.clientY - r.top;
  if (boxSel) { boxSel.x1 = px; boxSel.y1 = py; return; }
  if (tfrRect?.a) { tfrRect.b = [wx(px), wy(py)]; updateDrawHint(); return; }
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
  const px = e.clientX - r.left, py = e.clientY - r.top;
  if (boxSel) { finishBox(); boxSel = null; canvas.classList.remove('boxing'); return; }
  if (tfrRect?.a) { tfrRect.b = [wx(px), wy(py)]; finishRect(); return; }
  if (drag && !drag.moved && viaPick) { viaPoint = [wx(px), wy(py)]; viaPick = false; $('#ccVia').classList.add('on'); $('#ccVia').textContent = `◎ via (${viaPoint[0].toFixed(0)}, ${viaPoint[1].toFixed(0)})`; $('#drawHint').hidden = true; }
  else if (drag && !drag.moved && pickMode) { pickVertiport(px, py); }
  else if (drag && !drag.moved) { const n = pick(px, py); if (n !== null) select(n, e.shiftKey); }
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
$('#runBtn').onclick = () => launch();   // don't pass the click event as presetReq
window.addEventListener('keydown', (e) => {
  if (['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement.tagName)) return;
  if (e.code === 'Space' && document.activeElement.tagName !== 'BUTTON') { e.preventDefault(); $('#playBtn').click(); return; }
  const k = e.key.toLowerCase();
  if (k === 'escape') { if (tfrRect) { tfrRect = null; canvas.classList.remove('picking'); $('#drawHint').hidden = true; } else if (viaPick) { viaPick = false; $('#drawHint').hidden = true; } else { selSet = new Set(); renderSel(); } hideCtx(); return; }
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  const map = {h: 'hold', r: 'resume', g: 'ground_now', b: 'rtb', q: 'quarantine'};
  if (map[k]) { e.preventDefault(); runConsole(map[k]); }
  else if (k === '[' || k === ']') { e.preventDefault(); shiftLayer(k === ']' ? 1 : -1); }
});
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
  for (const k of low) { const li = document.createElement('li'), soc = h.soc[k], col = soc < 15 ? '#e11d48' : soc < 30 ? '#d97706' : '#059669';
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
  $('#hSocBar').style.background = soc < (th.soc_critical_pct ?? 15) ? '#e11d48' : soc < (th.soc_warning_pct ?? 30) ? '#d97706' : '#059669';
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
  hcctx.fillStyle = '#64748b'; hcctx.font = '9.5px system-ui'; hcctx.fillText('4.2 V', 0, 10); hcctx.fillText('3.0 V', 0, h - 4);
  const Y = (v) => h - 2 - (v - lo) / (hi - lo) * (h - 6);
  hcctx.strokeStyle = '#e11d4888'; hcctx.setLineDash([3, 3]); hcctx.beginPath(); hcctx.moveTo(30, Y(3000)); hcctx.lineTo(w, Y(3000)); hcctx.stroke(); hcctx.setLineDash([]);
  const mn = Math.min(...c);
  c.forEach((v, i) => { hcctx.fillStyle = v === mn ? '#d97706' : '#0891b2'; const y = Y(v); hcctx.fillRect(32 + i * bw, y, Math.max(1, bw - (n > 30 ? 0 : 2)), h - 2 - y); });
}
function drawHealthChart(k) {
  const w = hChartC.clientWidth, h = hChartC.clientHeight; screenTransform(hchctx); hchctx.clearRect(0, 0, w, h);
  if (!frames.length) return;
  const L = 26, R = w - 30, T = 6, B = h - 14, X = (t) => L + t / RUN.duration_s * (R - L);
  hchctx.strokeStyle = '#e2e8f0'; hchctx.fillStyle = '#64748b'; hchctx.font = '9.5px system-ui';
  for (const v of [0, 50, 100]) { const y = B - v / 100 * (B - T); hchctx.beginPath(); hchctx.moveTo(L, y); hchctx.lineTo(R, y); hchctx.stroke(); hchctx.fillText(`${v}%`, 0, y + 3); }
  const tMax = 100; hchctx.textAlign = 'left'; for (const v of [20, 60, 100]) hchctx.fillText(`${v}°`, R + 3, B - (v / tMax) * (B - T) + 3);
  const step = Math.max(1, Math.floor(frames.length / 500));
  const line = (get, scale, col) => { hchctx.strokeStyle = col; hchctx.lineWidth = 1.5; hchctx.beginPath(); let pen = false;
    for (let i = 0; i < frames.length; i += step) { const f = frames[i]; const v = f.h ? get(f.h) : undefined; if (v === undefined || f.status[k] === undefined || f.status[k] === 0 && v === undefined) { pen = false; continue; }
      const y = B - Math.min(1, v / scale) * (B - T); pen ? hchctx.lineTo(X(f.t), y) : hchctx.moveTo(X(f.t), y); pen = true; } hchctx.stroke(); };
  line((h) => h.soc[k], 100, '#059669'); line((h) => h.tmax[k], tMax, '#ea580c');
  hchctx.strokeStyle = '#0f172a'; hchctx.lineWidth = 1; hchctx.beginPath(); hchctx.moveTo(X(simT), T); hchctx.lineTo(X(simT), B); hchctx.stroke();
}
$('#dTabs').onclick = (e) => { const b = e.target.closest('button'); if (!b) return; dTab = b.dataset.tab;
  document.querySelectorAll('#dTabs button').forEach((x) => x.classList.toggle('on', x === b));
  $('#tabOv').hidden = dTab !== 'ov'; $('#tabHl').hidden = dTab !== 'hl'; resize(); };

// ------------------------------------------------------------------ weather controls
// Weather over time: points [t_s, °C, wind m/s] over 300 s (temperature 45 → 50 → 20 °C at 0/150/300 s,
// wind 4 → 0 → 5 → 2 m/s at 0/100/200/300 s, merged). Squeezed to the run duration when shorter.
const WX_PROFILES = {summer: {label: 'Summer day', span: 300,
  pts: [[0, 45, 4], [100, 48.33, 0], [150, 50, 2.5], [200, 40, 5], [300, 20, 2]]}};
let wxProfile = null;
function profilePoints(key, dir, duration) {
  const p = WX_PROFILES[key], k = Math.min(1, duration / p.span), to = (dir + 180) * Math.PI / 180;
  return p.pts.map(([t, c, w]) => [Math.round(t * k * 100) / 100, c,
    Math.round(w * Math.sin(to) * 100) / 100, Math.round(w * Math.cos(to) * 100) / 100]);
}
function readWeather() {
  if (!baseConfig?.drone_health) return null;
  const t = +$('#wxTemp').value, ws = +$('#wxWind').value, dir = +$('#wxDir').value;
  if (!(t >= -20 && t <= 55)) throw Error('Temperature must be between −20 and 55 °C.');
  if (!(ws >= 0 && ws <= 15)) throw Error('Wind speed must be 0–15 m/s.');
  const to = (dir + 180) * Math.PI / 180;   // wind FROM dir blows TOWARD dir + 180
  const wind = [Math.round(ws * Math.sin(to) * 100) / 100, Math.round(ws * Math.cos(to) * 100) / 100];
  if (wxProfile) return {t, wind, dir, profile: wxProfile};
  const base = baseConfig.drone_health;
  if (t === base.ambient_c && ws === 0 && !Math.hypot(...base.wind_mps)) return null;
  return {t, wind};
}
function airDensity(tc, h) { return 101325 * (1 - 2.25577e-5 * h) ** 5.25588 / (287.05 * (tc + 273.15)); }
function updateWeather() {
  const h = baseConfig?.drone_health?.site_elevation_m ?? 542, t = +$('#wxTemp').value;
  const rho = airDensity(t, h), ref = airDensity(15, h);
  $('#wxRho').textContent = Number.isFinite(rho) ? `${rho.toFixed(3)} kg/m³ · hover power ${((Math.sqrt(ref / rho) - 1) * 100).toFixed(1)}% vs 15 °C` : '—';
  document.querySelectorAll('#wxPresets button').forEach((b) => b.classList.toggle('on', wxProfile
    ? b.dataset.profile === wxProfile : !b.dataset.profile && +b.dataset.t === t && +b.dataset.w === +$('#wxWind').value));
  const note = $('#wxProfileNote'); note.hidden = !wxProfile;
  if (wxProfile) note.textContent = `${WX_PROFILES[wxProfile].label}: 45 → 50 → 20 °C and wind 4 → 0 → 5 → 2 m/s over 300 s (squeezed to the run if shorter). Wind keeps the "from" direction.`;
}
$('#wxPresets').onclick = (e) => { const b = e.target.closest('button'); if (!b) return; wxProfile = b.dataset.profile || null;
  $('#wxTemp').value = b.dataset.t; $('#wxWind').value = b.dataset.w; updateWeather(); };
for (const id of ['#wxTemp', '#wxWind']) $(id).addEventListener('input', () => { wxProfile = null; updateWeather(); });
$('#wxDir').addEventListener('input', updateWeather);

// ------------------------------------------------------------------ battery matrix (per-drone SoC graphs, Task-Manager style)
const battC = $('#battGrid'), bctx = battC.getContext('2d');
let battLayout = [], battAt = 0, battHistKey = null, battHist = [];
const socCol = (soc, bms) => (bms >= 2 || soc < 15) ? '#e11d48' : (bms === 1 || soc < 30) ? '#d97706' : '#059669';
function battHistory(i) {   // distinct once-per-second health snapshots in the last 120 s up to frame i
  const key = `${RUN.run_id}:${i}:${frames.length}`;
  if (battHistKey === key) return battHist;
  const out = [], tEnd = frames[i].t; let last = null;
  for (let j = i; j >= 0 && frames[j].t >= tEnd - 120; j--) { const h = frames[j].h; if (h && h !== last) { out.push({t: frames[j].t, h, st: frames[j].status}); last = h; } }
  battHistKey = key; battHist = out.reverse(); return battHist;
}
function drawBatt(s, force = false) {
  const now = performance.now(), dims = `${battC.width}x${battC.height}`;
  if (!force && now - battAt < 250 && dims === drawBatt.dims) return;   // a resize clears the canvas: redraw at once
  battAt = now;
  const card = $('#battCard'), on = RUN?.limits.health?.enabled;
  card.hidden = !on; if (!on || !s || !s.f0.h) { battLayout = []; return; }
  const f0 = s.f0, h = f0.h, n = RUN.flights.length, show = $('#battShow').value, sort = $('#battSort').value;
  let order = [...Array(n).keys()].filter((k) => h.soc[k] !== undefined && (show === 'all' || f0.status[k] === 1));
  if (sort === 'soc') order.sort((a, b) => h.soc[a] - h.soc[b] || a - b);
  else if (sort === 'bms') order.sort((a, b) => h.bms[b] - h.bms[a] || h.soc[a] - h.soc[b] || a - b);
  const W = battC.clientWidth, gap = 4;
  // tile size: as large as fits ~560 px of height, between 44×32 and 96×60 (Task Manager per-core look)
  let tw = 96;
  for (; tw > 44; tw -= 4) { const cols = Math.max(1, Math.floor((W + gap) / (tw + gap))); if (Math.ceil(order.length / cols) * (tw * 0.62 + gap) <= 560) break; }
  const th = Math.round(tw * 0.62), cols = Math.max(1, Math.floor((W + gap) / (tw + gap))), rows = Math.ceil(order.length / cols);
  const tw2 = Math.floor((W - gap * (cols - 1)) / cols), H = Math.max(60, rows * (th + gap) - gap);
  if (Math.abs(battC.clientHeight - H) > 1) { battC.style.height = `${H}px`; sizeCanvas(battC); }
  screenTransform(bctx); bctx.clearRect(0, 0, W, H);
  const hist = battHistory(s.i), tEnd = f0.t;
  const counts = [0, 0, 0, 0]; let low = 0;
  battLayout = [];
  order.forEach((k, idx) => {
    const x = (idx % cols) * (tw2 + gap), y = Math.floor(idx / cols) * (th + gap), soc = h.soc[k], bms = h.bms[k], st = f0.status[k];
    const air = st === 1, col = socCol(soc, bms);
    if (air) { counts[bms]++; if (soc < 30) low++; }
    battLayout.push([x, y, tw2, th, k]);
    bctx.globalAlpha = air ? 1 : 0.42;
    bctx.fillStyle = '#f8fafc'; bctx.fillRect(x, y, tw2, th);
    bctx.strokeStyle = 'rgba(100,116,139,0.18)'; bctx.lineWidth = 1;
    for (const g of [0.25, 0.5, 0.75]) { bctx.beginPath(); bctx.moveTo(x, y + th * g); bctx.lineTo(x + tw2, y + th * g); bctx.stroke(); }
    // SoC history graph (filled area), x = last 120 s
    const X = (t) => x + tw2 * (1 - (tEnd - t) / 120), Y = (v) => y + th - 2 - (v / 100) * (th - 4);
    const pts = hist.filter((r) => r.h.soc[k] !== undefined && r.st[k] !== undefined).map((r) => [X(r.t), Y(r.h.soc[k])]);
    if (pts.length) {
      pts.push([x + tw2, Y(soc)]);
      bctx.beginPath(); bctx.moveTo(pts[0][0], y + th); for (const [px, py] of pts) bctx.lineTo(px, py); bctx.lineTo(x + tw2, y + th); bctx.closePath();
      bctx.fillStyle = col + '40'; bctx.fill();
      bctx.beginPath(); pts.forEach(([px, py], i) => i ? bctx.lineTo(px, py) : bctx.moveTo(px, py)); bctx.strokeStyle = col; bctx.lineWidth = 1.3; bctx.stroke();
    }
    bctx.strokeStyle = k === selected ? '#0f172a' : bms >= 2 ? '#e11d48' : bms === 1 ? '#d97706' : '#cbd5e1';
    bctx.lineWidth = k === selected ? 2 : bms ? 1.6 : 1; bctx.strokeRect(x + 0.5, y + 0.5, tw2 - 1, th - 1);
    bctx.globalAlpha = air ? 1 : 0.7;
    const f = RUN.flights[k], fs = tw2 >= 70 ? 10.5 : 9;
    if (tw2 < 66) {   // compact tile: % on top, id at the bottom (hover for details)
      bctx.font = `700 ${fs + 1}px ui-monospace,monospace`; bctx.fillStyle = col; bctx.textBaseline = 'top'; bctx.fillText(`${soc}%`, x + 3, y + 2);
      bctx.font = `600 ${fs - 1}px ui-monospace,monospace`; bctx.fillStyle = COLORS[f.type]; bctx.textBaseline = 'bottom'; bctx.fillText(`${f.id}`, x + 3, y + th - 2);
      bctx.textBaseline = 'alphabetic'; bctx.globalAlpha = 1; return;
    }
    bctx.font = `600 ${fs}px ui-monospace,monospace`; bctx.fillStyle = COLORS[f.type]; bctx.textBaseline = 'top';
    bctx.fillText(`D-${f.id}`, x + 3, y + 2);
    bctx.textAlign = 'right'; bctx.fillStyle = col; bctx.fillText(`${soc}%`, x + tw2 - 3, y + 2); bctx.textAlign = 'left';
    if (!air) { bctx.fillStyle = '#64748b'; bctx.font = `600 ${fs - 1}px system-ui`; bctx.textBaseline = 'bottom';
      bctx.fillText(['queued', '', 'landed', 'CRASH', 'FORCED'][st] ?? '', x + 3, y + th - 2); }
    else if (bms) { bctx.fillStyle = col; bctx.font = `700 ${fs - 1}px system-ui`; bctx.textBaseline = 'bottom'; bctx.fillText(BMS[bms], x + 3, y + th - 2); }
    bctx.textBaseline = 'alphabetic'; bctx.globalAlpha = 1;
  });
  drawBatt.dims = `${battC.width}x${battC.height}`;
  $('#battSummary').textContent = `${order.length} shown · airborne: ${counts[0]} normal, ${counts[1]} warning, ${counts[2] + counts[3]} critical/fault · ${low} below 30 %`;
}
function battHit(e) {
  const r = battC.getBoundingClientRect(), px = e.clientX - r.left, py = e.clientY - r.top;
  return battLayout.find(([x, y, w, h]) => px >= x && px <= x + w && py >= y && py <= y + h) || null;
}
battC.addEventListener('click', (e) => { const hit = battHit(e); if (!hit) return; select(hit[4]); showSection('drone'); if (dTab !== 'hl') document.querySelector('#dTabs button[data-tab="hl"]').click(); });
battC.addEventListener('mousemove', (e) => {
  const hit = battHit(e), tip = $('#battTip');
  if (!hit || !frames.length) { tip.hidden = true; return; }
  const k = hit[4], f0 = frameAt(simT).f0, f = RUN.flights[k], r = battC.getBoundingClientRect(), card = $('#battCard').getBoundingClientRect();
  tip.hidden = false; tip.style.left = `${e.clientX - card.left + 12}px`; tip.style.top = `${e.clientY - card.top + 12}px`;
  tip.textContent = `D-${f.id} ${f.type} · SoC ${f0.h.soc[k]}% · BMS ${BMS[f0.h.bms[k]]} · max temp ${f0.h.tmax[k]} °C · ${STATUS[f0.status[k]]} · ${f.origin_name || f.origin} → ${f.destination_name || f.destination}`;
});
battC.addEventListener('mouseleave', () => { $('#battTip').hidden = true; });
$('#battSort').onchange = $('#battShow').onchange = () => { if (frames.length) drawBatt(frameAt(simT), true); };

// ------------------------------------------------------------------ Phase 4: DTC operator console
const MOVEMENT = new Set(['reroute', 'hold', 'rtb', 'change_layer', 'speed_limit', 'divert_charge']);
const live = () => RUN && !RUN.replay && !done;
const selIds = () => [...selSet].filter((n) => RUN?.flights[n]).map((n) => RUN.flights[n].id);
function renderSel() {
  const ids = [...selIds()].sort((a, b) => a - b);   // display order only; command targets are unchanged
  $('#ccSel').textContent = ids.length ? `Selected (${ids.length}): ${ids.slice(0, 8).map((i) => 'D-' + i).join(', ')}${ids.length > 8 ? ' …' : ''}` : 'No drones selected';
}
function consoleFill() {
  if (!MAP) return;
  const vps = MAP.vertiports.map((v) => `<option value="${v.id}">${v.id} · ${v.name}</option>`).join('');
  $('#ccDest').innerHTML = vps; $('#ccPad').innerHTML = vps;
  const L = RUN?.limits.num_layers ?? baseConfig?.airspace.num_layers ?? 3;
  $('#ccLayer').innerHTML = Array.from({length: L}, (_, l) => `<option value="${l}">L${l}</option>`).join('');
  $('#ccfLayer').innerHTML = '<option value="">any layer</option>' + Array.from({length: L}, (_, l) => `<option value="${l}">L${l}</option>`).join('');
  const secs = Array.from({length: SECTOR_COLS * SECTOR_ROWS}, (_, i) => `<option value="${i}">S${i}</option>`).join('');
  $('#ccfSector').innerHTML = '<option value="">any sector</option>' + secs; $('#ccGsSector').innerHTML = secs;
  $('#ccVSector').innerHTML = '<option value="">selected drones</option>' + secs.replace(/>S(\d)</g, '>sector S$1<');
}
function finishBox() {
  if (!RUN || !frames.length) return;
  const s = frameAt(simT), x0 = Math.min(boxSel.x0, boxSel.x1), x1 = Math.max(boxSel.x0, boxSel.x1), y0 = Math.min(boxSel.y0, boxSel.y1), y1 = Math.max(boxSel.y0, boxSel.y1);
  const hit = [];
  RUN.flights.forEach((_, n) => { const st = s.f0.status[n]; if (st !== 1 && st !== 0) return; const p = st === 1 ? posOf(s, n) : [s.f0.x[n], s.f0.y[n]];
    const X = sx(p[0]), Y = sy(p[1]); if (X >= x0 && X <= x1 && Y >= y0 && Y <= y1) hit.push(n); });
  selSet = new Set(hit); if (hit.length) selected = hit[0]; renderSel();
  status(`${hit.length} drone(s) selected by box.`, 'ok');
}
$('#ccClear').onclick = () => { selSet = new Set(); renderSel(); };
// Drone numbers like printer page ranges: "5", "1-10", "2, 4, 9-12", "D-7", "3..6", "8 to 11"
function parseIdRanges(text) {
  const ids = new Set(), bad = [];
  const norm = text.replace(/\s*(-|–|\.\.|\bto\b)\s*/gi, '$1');   // "7 - 12" / "8 to 11" -> one token
  for (const raw of norm.split(/[,;\s]+/).filter(Boolean)) {
    const tok = raw.replace(/d-?(?=\d)/gi, '');   // D-12 / d12 -> 12
    let m = tok.match(/^(\d+)$/);
    if (m) { ids.add(+m[1]); continue; }
    m = tok.match(/^(\d+)\s*(?:-|–|\.\.|to)\s*(\d+)$/i);
    if (m) {
      let [a, b] = [+m[1], +m[2]]; if (a > b) [a, b] = [b, a];
      if (b - a > 10000) { bad.push(raw); continue; }
      for (let i = a; i <= b; i++) ids.add(i);
      continue;
    }
    bad.push(raw);
  }
  return {ids, bad};
}
function applyFilter(add = false) {
  if (!RUN || !frames.length) return;
  const f0 = frameAt(simT).f0, ty = $('#ccfType').value, se = $('#ccfSector').value, la = $('#ccfLayer').value, st = $('#ccfStatus').value;
  const box = $('#ccfIds'), {ids, bad} = parseIdRanges(box.value);
  box.classList.toggle('bad', bad.length > 0);
  if (bad.length) { status(`Can't read drone numbers: ${bad.join(', ')} — use e.g. 3, 7-12, 20.`, 'err'); return; }
  const byId = new Map(RUN.flights.map((f, n) => [f.id, n]));
  const others = (n) => (!ty || RUN.flights[n].type === ty) && (st === '' || f0.status[n] === +st)
    && (la === '' || f0.layer[n] === +la) && (se === '' || sectorOf(f0.x[n], f0.y[n]) === +se);
  const pool = ids.size ? [...ids].filter((id) => byId.has(id)).map((id) => byId.get(id)).sort((a, b) => a - b) : RUN.flights.map((_, n) => n);
  const hit = pool.filter(others);
  selSet = add ? new Set([...selSet, ...hit]) : new Set(hit); if (hit.length) selected = hit[0]; renderSel();
  let msg = `${hit.length} drone(s) ${add ? 'added' : 'selected'}${add ? ` · ${selSet.size} in selection` : ''}.`;
  if (ids.size) {
    const missing = [...ids].filter((id) => !byId.has(id)), filtered = pool.filter((n) => !others(n)).map((n) => RUN.flights[n].id).sort((x, y) => x - y).map((i) => `D-${i}`);
    const list = (a) => a.length > 8 ? `${a.slice(0, 8).join(', ')} … (+${a.length - 8})` : a.join(', ');
    if (filtered.length) msg += ` Excluded by the type / sector / layer / status filters: ${list(filtered)}.`;
    if (missing.length) msg += ` No such drone: ${list(missing.map((i) => 'D-' + i))}.`;
  }
  status(msg, hit.length ? 'ok' : 'err');
}
$('#ccfApply').onclick = (e) => applyFilter(e.shiftKey);
$('#ccfIds').addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); applyFilter(e.shiftKey); } });
$('#ccfIds').addEventListener('input', () => $('#ccfIds').classList.remove('bad'));
async function dryRun(body) {
  const r = await api(`/api/runs/${RUN.run_id}/commands`, {...body, dry_run: true});
  for (let k = 0; k < 30; k++) {
    await new Promise((res) => setTimeout(res, 150));
    const c = (await api(`/api/runs/${RUN.run_id}/commands`)).commands.find((x) => x.command_id === r.command_id);
    if (c?.status === 'checked') return c;
  }
  return null;
}
function askConfirm(html, buttons) {
  const box = $('#ccConfirm'); box.innerHTML = html + '<div class="btns"></div>'; box.hidden = false;
  for (const [label, fn, cls] of buttons) { const b = document.createElement('button'); b.className = `ghost sm ${cls || ''}`; b.textContent = label; b.onclick = () => { box.hidden = true; fn?.(); }; box.lastChild.append(b); }
  showSection('console');   // commands from the map / keyboard need the console's confirm box on screen
  box.scrollIntoView({block: 'nearest'});
}
async function sendCmd(type, targets, params = {}, opts = {}) {
  if (!live()) { status(RUN?.replay ? 'This is a loaded replay — commands need a live run.' : 'Commands need a running simulation (launch one first).', 'err'); return; }
  const body = {type, targets, params, reason: opts.reason || 'operator'};
  if (opts.confirm && !opts.confirmed) {
    askConfirm(`<b>Confirm:</b> ${opts.confirm}`, [['Send', () => sendCmd(type, targets, params, {...opts, confirmed: true})], ['Cancel']]); return;
  }
  try {
    if (MOVEMENT.has(type) && targets.length && !opts.force) {
      const chk = await dryRun(body);
      const bad = chk ? Object.entries(chk.results || {}).filter(([, r]) => !r.feasible) : [];
      if (bad.length) {
        const alts = bad.filter(([, r]) => r.alternative);
        askConfirm(`<b>Energy check:</b> ${bad.length} of ${targets.length} drone(s) cannot complete this with the reserve margin.<ul>${bad.map(([id, r]) => `<li>D-${id}: ${r.detail}</li>`).join('')}</ul>`, [
          ...(alts.length ? [[`Send to the nearest reachable pad instead`, async () => {
            const okIds = targets.filter((i) => !bad.some(([id]) => +id === i));
            if (okIds.length) await sendCmd(type, okIds, params, {...opts, force: true});
            for (const [id, r] of alts) await sendCmd('reroute', [+id], {dest: r.alternative}, {force: true, reason: `feasible alternative to ${type}`});
          }]] : []),
          ['Send anyway', () => sendCmd(type, targets, params, {...opts, force: true}), 'warnbtn'], ['Cancel']]);
        return;
      }
    }
    const r = await api(`/api/runs/${RUN.run_id}/commands`, {...body, force: !!opts.force});
    status(`${r.command_id} ${type.replace(/_/g, ' ')} sent${targets.length ? ' to ' + targets.length + ' drone(s)' : ''} — applied at the simulator's next tick (≤ ${LIMITS?.interactive_lead_s ?? 5} s ahead of playback).`, 'ok');
    histAt = 0;
  } catch (e) { status(`Command refused: ${e.message}`, 'err'); }
}
function needSel() { const ids = selIds(); if (!ids.length) status('Select one or more drones first (click, Shift+click, Ctrl+drag, or the filter).', 'err'); return ids; }
function runConsole(cmd) {
  const ids = selIds(), many = ids.length > 5 ? `${ids.length} drones` : null;
  switch (cmd) {
    case 'hold': case 'resume': case 'ground_now': case 'rtb': case 'quarantine':
      if (!needSel().length) return;
      return sendCmd(cmd, ids, {}, {confirm: cmd === 'quarantine' ? `quarantine ${ids.map((i) => 'D-' + i).join(', ')} (reports ignored, ordered to land)` : many && `${cmd.replace('_', ' ')} for ${many}`});
    case 'promote': case 'demote':
      if (!needSel().length) return;
      return sendCmd('priority', ids, {level: cmd === 'promote' ? 0 : 2});
    case 'change_layer': if (!needSel().length) return; return sendCmd('change_layer', ids, {layer: +$('#ccLayer').value});
    case 'reroute': if (!needSel().length) return;
      return sendCmd('reroute', ids, {dest: $('#ccDest').value, ...(viaPoint ? {via: viaPoint} : {})}).then(() => { viaPoint = null; $('#ccVia').classList.remove('on'); $('#ccVia').textContent = '◎ via'; });
    case 'speed_limit': {
      const sec = $('#ccVSector').value, params = {v: +$('#ccV').value, expires_s: +$('#ccExp').value};
      if (sec !== '') return sendCmd('speed_limit', [], {...params, sector: +sec}, {confirm: `speed limit ${params.v} m/s in sector S${sec} for ${params.expires_s} s`});
      if (!needSel().length) return; return sendCmd('speed_limit', ids, params);
    }
    case 'divert_charge': if (!needSel().length) return; return sendCmd('divert_charge', ids, {pad: $('#ccPad').value, mode: $('#ccMode').value});
    case 'll_selected': if (!needSel().length) return; return sendCmd('lost_link_policy', ids, {policy: $('#ccLL').value});
    case 'll_fleet': return sendCmd('lost_link_policy', [], {policy: $('#ccLL').value}, {confirm: `fleet lost-link policy → ${$('#ccLL').value}`});
    case 'ground_stop': { const rel = $('#ccGsRel').value; return sendCmd('ground_stop', [], {sector: +$('#ccGsSector').value, ...(rel !== '' ? {release_s: +rel} : {})}, {confirm: `ground stop in sector S${$('#ccGsSector').value}`}); }
    case 'ground_stop_release': return sendCmd('ground_stop_release', [], {sector: +$('#ccGsSector').value});
    case 'fleet_ground_bms_critical': return sendCmd(cmd, [], {}, {confirm: 'ground every drone at BMS CRITICAL or worse'});
    case 'fleet_recall_below_soc': return sendCmd(cmd, [], {threshold_pct: +$('#ccRecall').value}, {confirm: `recall every drone below ${$('#ccRecall').value}% SoC to its base`});
  }
}
function shiftLayer(d) {
  const ids = needSel(); if (!ids.length || !frames.length) return;
  const f0 = frameAt(simT).f0, n = RUN.flights.findIndex((f) => f.id === ids[0]);
  const L = Math.max(0, Math.min((RUN.limits.num_layers ?? 3) - 1, f0.layer[n] + d));
  sendCmd('change_layer', ids, {layer: L});
}
document.querySelectorAll('#consoleCard [data-cmd]').forEach((b) => { b.onclick = () => runConsole(b.dataset.cmd); });
$('#ccVia').onclick = (e) => { e.preventDefault(); viaPick = true; viaPoint = null; const h = $('#drawHint'); h.textContent = 'Click the map point to fly via (Esc cancels).'; h.hidden = false; };
// restricted areas (TFR): press and drag a rectangle on the map, release to finish
const TFR_MIN_M = 10;   // smaller drags are treated as a mis-click
function rectSize() { const {a, b} = tfrRect; return [Math.abs(b[0] - a[0]), Math.abs(b[1] - a[1])]; }
function updateDrawHint() {
  const h = $('#drawHint'); h.hidden = false;
  if (!tfrRect.a) { h.textContent = 'Restricted area: press and drag a rectangle on the map (Esc cancels).'; return; }
  const [w, d] = rectSize(); h.textContent = `Restricted area: ${w.toFixed(0)} × ${d.toFixed(0)} m — release to finish, Esc to cancel.`;
}
$('#ccTfrDraw').onclick = () => { if (!live()) { status('Restricted areas need a running simulation.', 'err'); return; } tfrRect = {a: null, b: null}; canvas.classList.add('picking'); updateDrawHint(); };
function finishRect() {
  const r = tfrRect; tfrRect = null; canvas.classList.remove('picking'); $('#drawHint').hidden = true;
  const [w, d] = [Math.abs(r.b[0] - r.a[0]), Math.abs(r.b[1] - r.a[1])];
  if (w < TFR_MIN_M || d < TFR_MIN_M) { status(`Restricted area too small (${w.toFixed(0)} × ${d.toFixed(0)} m) — drag a larger rectangle.`, 'err'); return; }
  const xa = Math.min(r.a[0], r.b[0]), xb = Math.max(r.a[0], r.b[0]), ya = Math.min(r.a[1], r.b[1]), yb = Math.max(r.a[1], r.b[1]);
  const poly = [[xa, ya], [xb, ya], [xb, yb], [xa, yb]];
  const start = $('#ccTfrStart').value === '' ? 0 : +$('#ccTfrStart').value, end = $('#ccTfrEnd').value === '' ? RUN.duration_s : +$('#ccTfrEnd').value;
  const name = `TFR-${++tfrCount}`;
  sendCmd('tfr', [], {polygon: poly.map(([x, y]) => [Math.round(x), Math.round(y)]), start_s: start, end_s: end, name},
    {confirm: `restricted area ${name} (${w.toFixed(0)} × ${d.toFixed(0)} m rectangle) from ${start} s to ${end} s — drones inside are rerouted out or landed, departures inside are held`});
}
function renderTfrs(c) {
  const list = $('#ccTfrList'), key = JSON.stringify(c?.tfrs || []) + JSON.stringify(c?.ground_stops || {});
  if (renderTfrs.key === key) return; renderTfrs.key = key; list.replaceChildren();
  for (const z of c?.tfrs || []) { const li = document.createElement('li'); li.innerHTML = `<span style="color:${z.active ? '#e11d48' : '#d97706'}">${z.name}</span><span class="muted">${z.active ? 'ACTIVE' : 'scheduled/ended'} · ${fmt(z.start_s, 0)}–${fmt(z.end_s, 0)} s</span><button class="ghost sm">end</button>`;
    li.lastChild.onclick = (e) => { e.stopPropagation(); sendCmd('tfr_cancel', [], {name: z.name}); }; list.append(li); }
  for (const [sec, rel] of Object.entries(c?.ground_stops || {})) { const li = document.createElement('li'); li.innerHTML = `<span style="color:#d97706">Ground stop S${sec}</span><span class="muted">${rel === null ? 'until released' : 'until ' + fmt(rel, 0) + ' s'}</span>`; list.append(li); }
  if (!list.children.length) list.innerHTML = '<li class="empty">no restricted areas or ground stops</li>';
}
async function refreshHist() {
  if (!RUN || RUN.replay) return;
  try { cmdHist = (await api(`/api/runs/${RUN.run_id}/commands`)).commands; } catch { return; }
  const list = $('#ccHist'); list.replaceChildren();
  const shown = cmdHist.filter((c) => !c.dry_run).slice(-25).reverse();
  $('#ccHistCount').textContent = `${shown.length} command(s)`;
  for (const c of shown) {
    const li = document.createElement('li'), tgt = c.targets?.length ? ' → ' + c.targets.slice(0, 5).map((i) => 'D-' + i).join(', ') + (c.targets.length > 5 ? '…' : '') : c.drone_id !== undefined ? ` D-${c.drone_id}` : '';
    const when = c.t_received === null || c.t_received === undefined ? 'waiting for the simulator' : `received ${fmt(c.t_received)} s${c.t_delivered !== null && c.t_delivered !== undefined ? ' · delivered ' + fmt(c.t_delivered) + ' s' : ''}`;
    li.innerHTML = `<span class="st ${c.status}">${c.status}</span>${c.command_id} ${c.type.replace(/_/g, ' ')}${tgt}<small></small>`;
    li.lastChild.textContent = `${when}${c.outcome ? ' · ' + c.outcome : ''}${c.results ? ' · ' + Object.entries(c.results).slice(0, 3).map(([k, v]) => (/^\d+$/.test(k) ? 'D-' + k + ': ' : '') + (typeof v === 'string' ? v : v.detail)).join(' | ') : ''}`;
    list.append(li);
  }
}
function updateConsole(s) {
  const c = s?.f0.console, d = s?.f0.dtc;
  $('#ccLink').textContent = !RUN ? '—' : !RUN.switches.use_overseer ? 'no DTC in this architecture' : `link ${d?.link_up ? 'UP' : 'DOWN'}${c?.outage_queue ? ' · ' + c.outage_queue + ' queued' : ''} · lost-link: ${c?.lost_link_default ?? 'continue'}`;
  renderTfrs(c);
  const now = performance.now(); if (live() && now - histAt > 1000) { histAt = now; refreshHist(); }
}
function drawConsoleOverlay(s) {
  const c = s?.f0.console;
  for (const z of c?.tfrs || []) {
    if (!z.active && z.end_s <= simT) continue;
    ctx.beginPath(); z.polygon.forEach(([x, y], i) => i ? ctx.lineTo(sx(x), sy(y)) : ctx.moveTo(sx(x), sy(y))); ctx.closePath();
    ctx.fillStyle = z.active ? 'rgba(225,29,72,0.14)' : 'rgba(217,119,6,0.08)'; ctx.fill();
    ctx.strokeStyle = z.active ? '#e11d48' : '#d97706'; ctx.lineWidth = 2; ctx.setLineDash(z.active ? [] : [6, 4]); ctx.stroke(); ctx.setLineDash([]);
    const [x, y] = z.polygon[0]; ctx.fillStyle = ctx.strokeStyle; ctx.font = '700 11px system-ui'; ctx.fillText(`${z.name} ${z.active ? 'ACTIVE' : 'from ' + fmt(z.start_s, 0) + ' s'}`, sx(x) + 4, sy(y) - 4);
  }
  if (c?.ground_stops && MAP) for (const sec of Object.keys(c.ground_stops)) {
    const [x0, y0, x1, y1] = MAP.bounds, col = +sec % SECTOR_COLS, row = Math.floor(+sec / SECTOR_COLS);
    const ax = x0 + (x1 - x0) * col / SECTOR_COLS, bx = x0 + (x1 - x0) * (col + 1) / SECTOR_COLS, ay = y0 + (y1 - y0) * row / SECTOR_ROWS, by = y0 + (y1 - y0) * (row + 1) / SECTOR_ROWS;
    ctx.fillStyle = 'rgba(217,119,6,0.08)'; ctx.fillRect(sx(ax), sy(by), (bx - ax) * view.s, (by - ay) * view.s);
    ctx.fillStyle = '#d97706'; ctx.font = '700 11px system-ui'; ctx.fillText(`GROUND STOP S${sec}`, sx(ax) + 6, sy(by) + 28);
  }
  if (tfrRect?.a) {
    const x = Math.min(sx(tfrRect.a[0]), sx(tfrRect.b[0])), y = Math.min(sy(tfrRect.a[1]), sy(tfrRect.b[1]));
    const w = Math.abs(sx(tfrRect.b[0]) - sx(tfrRect.a[0])), h = Math.abs(sy(tfrRect.b[1]) - sy(tfrRect.a[1]));
    ctx.fillStyle = 'rgba(225,29,72,0.10)'; ctx.fillRect(x, y, w, h);
    ctx.strokeStyle = '#e11d48'; ctx.setLineDash([5, 3]); ctx.lineWidth = 2; ctx.strokeRect(x, y, w, h); ctx.setLineDash([]);
    const [mw, md] = rectSize(); ctx.fillStyle = '#e11d48'; ctx.font = '600 11px system-ui'; ctx.fillText(`${mw.toFixed(0)} × ${md.toFixed(0)} m`, x + 4, y - 5);
  }
  if (viaPoint) { ctx.strokeStyle = '#0891b2'; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(sx(viaPoint[0]), sy(viaPoint[1]), 7, 0, 7); ctx.stroke(); ctx.fillStyle = '#0891b2'; ctx.font = '600 10px system-ui'; ctx.fillText('via', sx(viaPoint[0]) + 9, sy(viaPoint[1]) + 3); }
  if (boxSel) { ctx.strokeStyle = '#0891b2'; ctx.setLineDash([4, 3]); ctx.lineWidth = 1.5; ctx.strokeRect(boxSel.x0, boxSel.y0, boxSel.x1 - boxSel.x0, boxSel.y1 - boxSel.y0); ctx.setLineDash([]); }
  if (!s || !RUN) return;
  const holds = new Set(c?.holds || []), quar = new Set(c?.quarantined || []), charging = c?.charging || {};
  RUN.flights.forEach((f, n) => {
    const st = s.f0.status[n]; if (st !== 1 && st !== 0) return;
    const p = st === 1 ? posOf(s, n) : [s.f0.x[n], s.f0.y[n]], X = sx(p[0]), Y = sy(p[1]);
    if (selSet.has(n) && n !== selected) { ctx.strokeStyle = '#0891b2'; ctx.lineWidth = 1.6; ctx.setLineDash([3, 2]); ctx.beginPath(); ctx.arc(X, Y, 12, 0, 7); ctx.stroke(); ctx.setLineDash([]); }
    const tag = (txt, col, dy) => { ctx.font = '700 10px system-ui'; ctx.lineWidth = 3; ctx.strokeStyle = '#ffffff'; ctx.strokeText(txt, X - 6, Y + dy); ctx.fillStyle = col; ctx.fillText(txt, X - 6, Y + dy); };
    if (holds.has(f.id)) tag(st === 1 ? '⏸ HOLD' : '⏸ held', '#d97706', 22);
    if (quar.has(f.id)) tag('⛔ QUARANTINED', '#9333ea', 34);
    if (charging[f.id]) tag(`⚡ ${charging[f.id].mode} until ${fmt(charging[f.id].until, 0)} s`, '#059669', 22);
  });
}
// right-click context menu on a drone
function hideCtx() { $('#ctxMenu').hidden = true; }
canvas.addEventListener('contextmenu', (e) => {
  e.preventDefault(); const r = canvas.getBoundingClientRect(), n = pick(e.clientX - r.left, e.clientY - r.top);
  if (n === null) { hideCtx(); return; }
  if (!selSet.has(n)) select(n);
  const ids = selIds(), m = $('#ctxMenu');
  const items = [['⏸ Hold', 'hold'], ['▶ Resume', 'resume'], ['⤓ Ground now', 'ground_now'], ['↩ Return to base', 'rtb'], ['▲ Climb one layer', 'up'], ['▼ Descend one layer', 'down'],
    ['⚕ Make EMERGENCY', 'promote'], ['⛔ Quarantine', 'quarantine'], ['♥ Show health', 'health']];
  m.innerHTML = `<div class="h">${ids.length > 1 ? ids.length + ' drones' : 'D-' + ids[0]}</div>` + items.map(([l, c]) => `<button data-c="${c}">${l}</button>`).join('');
  m.style.left = `${Math.min(e.clientX - r.left, r.width - 190)}px`; m.style.top = `${Math.min(e.clientY - r.top, r.height - 290)}px`; m.hidden = false;
  m.onclick = (ev) => { const b = ev.target.closest('button'); if (!b) return; hideCtx(); const c = b.dataset.c;
    if (c === 'up' || c === 'down') shiftLayer(c === 'up' ? 1 : -1);
    else if (c === 'health') { selected = n; document.querySelector('#dTabs button[data-tab="hl"]').click(); }
    else runConsole(c); };
});
document.addEventListener('pointerdown', (e) => { if (!e.target.closest('#ctxMenu')) hideCtx(); });

// ------------------------------------------------------------------ Phase 5: scenario presets + comparison
let PRESETS = [], cmpAt = 0;
function renderPreset() {
  const p = PRESETS.find((x) => x.id === $('#presetSel').value), box = $('#presetInfo');
  box.hidden = !p; if (!p) return;
  $('#presetDesc').textContent = p.description;
  $('#presetTimeline').innerHTML = p.timeline.map(([t, txt]) => `<li><time>${t} s</time><span></span></li>`).join('');
  [...$('#presetTimeline').children].forEach((li, i) => { li.lastChild.textContent = p.timeline[i][1]; });
  $('#presetMeta').textContent = `${p.map.toUpperCase()} · ${p.fleet} random drones${p.custom_drones ? ' + ' + p.custom_drones + ' scripted' : ''} · ${p.duration_s} s` +
    (p.variants.length ? ` · variants: ${p.variants.join(' / ')} (compared side by side)` : '') + ` · watch: ${p.kpi_focus.join(', ')}`;
}
$('#presetSel').onchange = renderPreset;
$('#presetRun').onclick = async () => {
  const id = $('#presetSel').value; if (!id) return;
  const p = PRESETS.find((x) => x.id === id);
  if (p.map !== mapId) await loadMap(p.map);
  await launch({preset: id});
};
const CMP_ROWS = [['delivered', 'Delivered', 'max'], ['arrivals', 'Landed', 'max'], ['crashes', 'Crashes', 'min'], ['near_misses', 'Near misses', 'min'],
  ['min_separation_m', 'Min separation (m)', 'max'], ['pad_holds', 'Ground holds', 'min'], ['emergency_mean_delay_s', 'Emergency delay (s)', 'min'],
  ['energy_used_wh', 'Fleet energy (Wh)', 'min'], ['energy_per_delivered_wh', 'Energy / parcel delivery (Wh)', 'min'], ['max_pack_c', 'Max pack °C', 'min'],
  ['max_motor_c', 'Max motor °C', 'min'], ['diversions', 'Diversions', 'min'], ['forced_landings', 'Forced landings', 'min'], ['energy_depleted', 'Depleted', 'min']];
async function updateCompare() {
  const card = $('#cmpCard'), pr = RUN?.preset;
  if (!pr || pr.variants.length < 2 || RUN.replay) { card.hidden = true; return; }
  card.hidden = false;
  const now = performance.now(); if (now - cmpAt < 2000) return; cmpAt = now;
  let data; try { data = await api(`/api/runs/${RUN.run_id}/compare`); } catch { return; }
  $('#cmpTitle').textContent = `Variant comparison · ${pr.title}`;
  const vs = data.variants;
  $('#cmpNote').textContent = `same seed and flights · ${vs.filter((v) => v.done).length}/${vs.length} finished · live: ${vs.find((v) => v.live)?.label}`;
  let html = `<tr><th>KPI</th>${vs.map((v) => `<th>${v.label}${v.live ? ' (live)' : ''}${v.done ? '' : v.error ? ' ⚠' : ' …'}</th>`).join('')}</tr>`;
  for (const [key, label, better] of CMP_ROWS) {
    const vals = vs.map((v) => v.kpis?.[key]), nums = vals.filter((x) => typeof x === 'number');
    const best = nums.length > 1 ? (better === 'max' ? Math.max(...nums) : Math.min(...nums)) : null, worst = nums.length > 1 ? (better === 'max' ? Math.min(...nums) : Math.max(...nums)) : null;
    html += `<tr><td>${label}</td>${vals.map((x, i) => { const done = vs[i].done; const cls = done && best !== worst ? (x === best ? 'best' : x === worst ? 'worst' : '') : '';
      return `<td class="${cls}">${x === null || x === undefined ? (vs[i].error ? 'error' : '…') : fmt(x, Number.isInteger(x) ? 0 : 1)}</td>`; }).join('')}</tr>`;
  }
  $('#cmpTable').innerHTML = html;
}

// ------------------------------------------------------------------ sections: nav, side panel, overview
// Default panel width per section (px); a width the user drags applies to every section until reset.
const SECT_W = {overview: 540, setup: 420, custom: 420, console: 440, drone: 420, health: 580, safety: 580, network: 620, admm: 580};
let section = 'overview', panelW = null, sectAt = 0;
try { panelW = +localStorage.getItem('masooda.panelW') || null; } catch { panelW = null; }
const layoutEl = $('#layout');
const shown = (name) => section === name && !layoutEl.classList.contains('collapsed');
function clampPanel(w) { return Math.round(Math.max(320, Math.min(w, 900, window.innerWidth - 76 - 380))); }
function applyPanelWidth() { layoutEl.style.setProperty('--panel-w', `${clampPanel(panelW || SECT_W[section] || 420)}px`); }
function setCollapsed(on) {
  layoutEl.classList.toggle('collapsed', on);
  const t = $('#panelToggle'); t.lastChild.textContent = on ? 'Show' : 'Hide';
  resize();
}
function showSection(name) {
  if (!SECT_W[name]) name = 'overview';
  section = name;
  document.querySelectorAll('#snav button[data-sect]').forEach((b) => b.classList.toggle('on', b.dataset.sect === name));
  let el = null;
  document.querySelectorAll('#spanelBody > .sect').forEach((s) => { const on = s.dataset.sect === name; s.hidden = !on; if (on) el = s; });
  $('#panelTitle').textContent = el.dataset.title; $('#panelSub').textContent = el.dataset.sub || '';
  $('#spanelBody').scrollTop = 0;
  applyPanelWidth();
  if (layoutEl.classList.contains('collapsed')) setCollapsed(false); else resize();
  try { history.replaceState(null, '', `${location.pathname}${location.search}#${name}`); } catch { /* file:// or sandboxed */ }
  sectAt = 0;   // refresh the overview / dots now
}
$('#snav').addEventListener('click', (e) => {
  const b = e.target.closest('button'); if (!b) return;
  if (b.id === 'panelToggle') { setCollapsed(!layoutEl.classList.contains('collapsed')); return; }
  if (b.dataset.sect === section && !layoutEl.classList.contains('collapsed') && window.innerWidth > 900) { setCollapsed(true); return; }   // click the open section again to hide the panel
  showSection(b.dataset.sect);
});
$('#panelClose').onclick = () => setCollapsed(true);
$('#ovGrid').addEventListener('click', (e) => { const t = e.target.closest('.tile'); if (t) showSection(t.dataset.go); });
$('#ovGrid').addEventListener('keydown', (e) => { const t = e.target.closest('.tile'); if (t && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); showSection(t.dataset.go); } });
window.addEventListener('hashchange', () => { const h = location.hash.slice(1); if (h && h !== section && SECT_W[h]) showSection(h); });
window.addEventListener('resize', applyPanelWidth);
if (window.ResizeObserver) new ResizeObserver(() => resize()).observe(document.querySelector('.map-wrap'));
// drag the panel's right edge to resize; double-click resets to the section default
(() => {
  const h = $('#panelResize'); let start = null;
  h.addEventListener('pointerdown', (e) => { start = [e.clientX, $('#spanel').getBoundingClientRect().width]; h.setPointerCapture(e.pointerId); h.classList.add('drag'); document.body.classList.add('resizing'); });
  h.addEventListener('pointermove', (e) => { if (!start) return; panelW = clampPanel(start[1] + e.clientX - start[0]); applyPanelWidth(); });
  const end = () => { if (!start) return; start = null; h.classList.remove('drag'); document.body.classList.remove('resizing'); try { localStorage.setItem('masooda.panelW', String(panelW)); } catch { /* storage blocked */ } resize(); };
  h.addEventListener('pointerup', end); h.addEventListener('pointercancel', end);
  h.addEventListener('dblclick', () => { panelW = null; try { localStorage.removeItem('masooda.panelW'); } catch { /* storage blocked */ } applyPanelWidth(); resize(); });
})();

// status dots on the nav (and on the overview tiles): '', 'ok', 'warn', 'bad'
function setDot(name, cls, text = '') {
  for (const d of document.querySelectorAll(`#snav button[data-sect="${name}"] .ndot, .ndot[data-dot="${name}"]`)) {
    d.className = `ndot ${cls}`; d.textContent = text;
  }
}
const kv = (rows) => rows.map(([k, v, c]) => `<dt>${k}</dt><dd${c ? ` class="${c}"` : ''}>${v}</dd>`).join('');
function latestAdmmRun(i) { for (let j = i, n = 0; j >= 0 && n < 400; j--, n++) if (frames[j].admm?.run) return frames[j].admm.run; return null; }
function bmsCounts(f) { const cnt = [0, 0, 0, 0], h = f.h; if (h) f.status.forEach((st, k) => { if (st === 1 && h.bms[k] !== undefined) cnt[h.bms[k]]++; }); return cnt; }

function updateSections(s) {
  const now = performance.now(); if (now - sectAt < 250) return; sectAt = now;
  setDot('custom', customDrones.length ? 'count' : '', customDrones.length ? String(customDrones.length) : '');
  if (!RUN || !s) { for (const n of ['console', 'health', 'safety', 'admm', 'drone']) setDot(n, ''); if (shown('overview')) updateOverview(null); return; }
  const f = s.f0, st = f.stats || {}, healthOn = RUN.limits.health?.enabled;
  setDot('console', !RUN.switches.use_overseer ? '' : f.link_up ? 'ok' : 'bad');
  const cnt = healthOn ? bmsCounts(f) : [0, 0, 0, 0];
  setDot('health', !healthOn ? '' : cnt[2] + cnt[3] ? 'bad' : cnt[1] ? 'warn' : 'ok');
  setDot('safety', st.crashes || st.safety_violation_ticks ? 'bad' : st.near_misses ? 'warn' : 'ok');
  setDot('admm', !RUN.switches.use_admm ? '' : st.admm_nonconverged ? 'warn' : 'ok');
  const sel = selected !== null && RUN.flights[selected] ? selected : null, sb = sel !== null && f.h ? f.h.bms[sel] : undefined;
  setDot('drone', sel === null ? '' : f.status[sel] === 3 || sb >= 2 ? 'bad' : sb === 1 ? 'warn' : '');
  if (shown('overview')) updateOverview(s);
}

function updateOverview(s) {
  $('#ovCustomBig').textContent = customDrones.length;
  $('#ovCustomSub').textContent = customDrones.length ? `custom drone${customDrones.length === 1 ? '' : 's'} in the next launch` : 'none added · random fleet only';
  if (!RUN || !s) { $('#ovRunBig').textContent = $('#runState').textContent; return; }
  const f = s.f0, st = f.stats || {}, L = RUN.limits;
  // Run
  const cnt = [0, 0, 0, 0, 0]; f.status.forEach((x) => cnt[x]++);
  const total = Math.max(1, f.status.length), cols = ['#cbd5e1', '#0891b2', '#059669', '#e11d48', '#d97706'], names = ['Queued', 'Airborne', 'Landed', 'Crashed', 'Forced landing'];   // STATUS order
  $('#ovRunBig').textContent = `${$('#runState').textContent} · ${fmt(simT)} / ${RUN.duration_s} s`;
  $('#ovRunMeta').textContent = `${RUN.preset ? 'Preset · ' + RUN.preset.title + ' · ' : ''}${MAP?.label ?? RUN.map} · ${ARCH[RUN.architecture]?.label ?? RUN.architecture} · seed ${RUN.seed} · ${RUN.flights.length} flights`;
  $('#ovRunStack').innerHTML = cnt.map((c, i) => c ? `<i style="width:${(100 * c / total).toFixed(2)}%;background:${cols[i]}" title="${names[i]}: ${c}"></i>` : '').join('');
  $('#ovRunLegend').innerHTML = cnt.map((c, i) => (i < 3 || c) ? `<span><i style="background:${cols[i]}"></i>${names[i]}<b>${c}</b></span>` : '').join('');
  // Safety
  const big = $('#ovSafeBig'); big.textContent = st.crashes ?? '—'; big.className = `tile-big ${st.crashes ? 'bad' : 'good'}`;
  $('#ovSafeSub').textContent = st.crashes ? `collisions · ${st.crashed_drones} drones lost` : 'collisions';
  $('#ovSafeKv').innerHTML = kv([
    ['Near misses', st.near_misses ?? '—', st.near_misses ? 'warn' : ''],
    ['Min separation', st.min_separation_m === null || st.min_separation_m === undefined ? '—' : `${fmt(st.min_separation_m, 2)} m / ${L.d_min} m`, st.min_separation_m !== null && st.min_separation_m < L.d_min ? 'bad' : ''],
    ['Separation now', f.rho === null || f.rho === undefined ? '—' : `${fmt(f.rho + L.d_min, 1)} m`],
    ['Violation ticks', st.safety_violation_ticks ?? '—', st.safety_violation_ticks ? 'bad' : '']]);
  drawSpark(s.i);
  // DTC
  const dtcOn = RUN.switches.use_overseer, d = f.dtc || {}, c = f.console || {};
  const db = $('#ovDtcBig'); db.textContent = !dtcOn ? 'OFF' : f.link_up ? 'LINK UP' : 'LINK DOWN'; db.className = `tile-big ${!dtcOn ? '' : f.link_up ? 'good' : 'bad'}`;
  $('#ovDtcSub').textContent = !dtcOn ? 'no DTC in this architecture' : `directive age ${fmt(d.staleness_s)} s`;
  const last = cmdHist.at(-1);
  $('#ovDtcKv').innerHTML = kv([
    ['Directives', st.dtc_directives ?? d.directives ?? 0],
    ['Layer changes · gated', `${st.layer_changes ?? 0} · ${st.layer_changes_deferred ?? 0}`],
    ['Operator commands', cmdHist.length ? `${cmdHist.length} · last ${last.type} (${last.status})` : 'none'],
    ['Selected drones', selSet.size || '—'],
    ...(c.outage_queue ? [['Queued for link', c.outage_queue, 'warn']] : [])]);
  // Fleet health
  const healthOn = L.health?.enabled;
  if (healthOn) {
    const bc = bmsCounts(f);
    $('#ovBms').innerHTML = BMS.map((b, i) => `<div><b style="color:${BMS_COL[i]}">${bc[i]}</b><small>${b}</small></div>`).join('');
    let low = null; if (f.h) f.status.forEach((x, k) => { if (x === 1 && (low === null || f.h.soc[k] < f.h.soc[low])) low = k; });
    $('#ovHealthKv').innerHTML = kv([
      ['Lowest SoC (airborne)', low === null ? '—' : `D-${RUN.flights[low].id} · ${f.h.soc[low]}%`, low !== null && f.h.soc[low] < 15 ? 'bad' : low !== null && f.h.soc[low] < 30 ? 'warn' : ''],
      ['Max pack temperature', st.max_pack_c === undefined ? '—' : `${fmt(st.max_pack_c, 0)} °C`],
      ['Diversions · forced', `${st.diversions ?? 0} · ${st.forced_landings ?? 0}`, st.forced_landings ? 'bad' : ''],
      ['Energy / parcel delivery', st.energy_per_delivered_wh === null || st.energy_per_delivered_wh === undefined ? '—' : `${fmt(st.energy_per_delivered_wh, 0)} Wh`]]);
  } else { $('#ovBms').innerHTML = ''; $('#ovHealthKv').innerHTML = kv([['Health model', 'off']]); }
  // Traffic & priority
  const pr = f.prio, mg = f.merge;
  $('#ovTrafBig').textContent = `${st.arrivals ?? 0} / ${RUN.flights.length}`;
  $('#ovTrafKv').innerHTML = kv([
    ['Emergency compliance', pr && pr.count ? (pr.rate === null ? '—' : `${fmt(pr.rate * 100, 0)}%`) : 'no EMG flights', pr && pr.rate !== null && pr.rate < 0.9 ? 'bad' : ''],
    ['EMG mean delay', pr && pr.mean_delay_s !== null && pr.mean_delay_s !== undefined ? `${fmt(pr.mean_delay_s)} s` : '—'],
    ['Junction merges', mg ? (mg.rate === null ? '—' : `${fmt(mg.rate * 100, 0)}% · ${mg.platoons} platoons`) : 'off'],
    ['Altitude shifts', st.tactical_layer_shifts ?? 0]]);
  // ADMM
  const ar = latestAdmmRun(s.i), ab = $('#ovAdmmBig');
  ab.textContent = RUN.switches.use_admm ? (st.admm_events ?? 0) : 'OFF'; ab.className = `tile-big ${RUN.switches.use_admm ? 'cyan' : ''}`;
  $('#ovAdmmSub').textContent = RUN.switches.use_admm ? 'conflict groups resolved' : (RUN.architecture === 'centralized' ? 'centralized: no ADMM' : 'ADMM disabled');
  $('#ovAdmmKv').innerHTML = RUN.switches.use_admm ? kv([
    ['Converged · fallback', `${ar?.converged ?? 0} · ${ar?.fallback ?? st.admm_nonconverged ?? 0}`, (ar?.fallback || st.admm_nonconverged) ? 'warn' : ''],
    ['Iterations p95', `${fmt(ar?.it_p95, 0)} / ${L.max_iterations ?? '—'}`],
    ['Solve time p95', `${fmt(ar?.ms_p95, 2)} ms`]]) : '';
  // Network
  const air = cnt[1], m = f.net || {};
  $('#ovNetBig').textContent = !dtcOn ? '—' : air ? `${fmt(100 * (d.connected || 0) / air, 0)}%` : '—';
  $('#ovNetSub').textContent = dtcOn ? 'of airborne drones reach the DTC' : 'no DTC · V2V only';
  $('#ovNetKv').innerHTML = kv([
    ['V2V avg degree', fmt(m.avg_degree, 2)],
    ['Giant component', air ? `${fmt((m.largest_component ?? 0) * 100, 0)}%` : '—'],
    ['Components (isolated)', `${m.components ?? 0} (${m.isolated ?? 0})`],
    ['Edges', m.edges ?? 0]]);
  // Selected drone
  const n = selected !== null && RUN.flights[selected] ? selected : null;
  if (n === null) { $('#ovDroneBig').textContent = '—'; $('#ovDroneSub').textContent = 'click a drone on the map'; $('#ovDroneKv').innerHTML = ''; }
  else {
    const fl = RUN.flights[n], stn = f.status[n];
    $('#ovDroneBig').textContent = `D-${fl.id}`; $('#ovDroneBig').style.color = COLORS[fl.type];
    $('#ovDroneSub').textContent = `${fl.type} · ${STATUS[stn]}`;
    $('#ovDroneKv').innerHTML = kv([
      ['Route', `${fl.origin_name ?? fl.origin} → ${fl.destination_name ?? fl.destination}`],
      ['Layer · speed', `L${f.layer[n]} · ${fmt(f.speed[n])} m/s`],
      ['Progress', `${fmt((f.progress[n] || 0) * 100, 0)}%`],
      ...(f.h ? [['SoC · BMS', `${f.h.soc[n]}% · ${BMS[f.h.bms[n]]}`, f.h.bms[n] >= 2 ? 'bad' : f.h.bms[n] === 1 ? 'warn' : '']] : [])]);
  }
}
// robustness ρ(t) sparkline up to the playback time (red dashed line = the d_min limit)
function drawSpark(i) {
  const svg = $('#ovSafeSpark'), pts = [], step = Math.max(1, Math.floor((i + 1) / 200));
  for (let j = 0; j <= i; j += step) if (frames[j].rho !== null && frames[j].rho !== undefined) pts.push([frames[j].t, frames[j].rho]);
  if (pts.length < 2) { svg.innerHTML = ''; return; }
  const T = Math.max(RUN.duration_s, 1), lo = Math.min(-1, ...pts.map((p) => p[1])), hi = Math.max(1, ...pts.map((p) => p[1]));
  const X = (t) => (200 * t / T).toFixed(1), Y = (v) => (38 - 36 * (v - lo) / (hi - lo)).toFixed(1);
  svg.innerHTML = `<line x1="0" x2="200" y1="${Y(0)}" y2="${Y(0)}" stroke="#e11d48" stroke-width="1" stroke-dasharray="3 3" vector-effect="non-scaling-stroke"/>`
    + `<polyline fill="none" stroke="#0891b2" stroke-width="1.5" vector-effect="non-scaling-stroke" points="${pts.map((p) => `${X(p[0])},${Y(p[1])}`).join(' ')}"/>`;
}

// ------------------------------------------------------------------ boot
async function boot() {
  showSection(location.hash.slice(1) || 'overview');
  resize(); requestAnimationFrame(tick);
  try {
    let maps;
    let presets;
    [baseConfig, maps, LIMITS, presets] = await Promise.all([api('/api/config'), api('/api/maps'), api('/api/limits'), api('/api/presets')]);
    PRESETS = presets.presets;
    $('#presetSel').innerHTML = '<option value="">— none: build your own below —</option>' + PRESETS.map((p) => `<option value="${p.id}">${p.order}. ${p.title}</option>`).join('');
    applyLimits();
    MAPS = maps.maps;
    await loadMap(new URLSearchParams(location.search).get('map') || maps.default);
    $('#advFields').innerHTML = ADVANCED.map(([p, label]) => `<label>${label}<input type="number" step="any" data-path="${p}" data-label="${label}" value="${get(baseConfig, p)}"></label>`).join('');
    $('#seed').value = baseConfig.simulation.random_seed;
    if (baseConfig.drone_health) { $('#wxTemp').value = baseConfig.drone_health.ambient_c; updateWeather(); } else document.querySelector('.weather').hidden = true;
    $('#sysStatus').textContent = 'ONLINE'; $('#sysDot').className = 'dot ok';
    buildLayerSeg(); selectScene('normal');
    await launch();
  } catch (e) {
    $('#sysStatus').textContent = 'OFFLINE'; $('#sysDot').className = 'dot bad';
    status(`Cannot reach the simulator (${e.message}). Start it with: python -m web_sandbox.server`, 'err');
  }
}
boot();
