"use strict";
/* clockinmetron — phone version (PWA). Same model as the desktop app:
 *   tags:      [{name, x, y}]           the chart (x: -1 indoor … +1 outdoor, y: -1 alone … +1 social)
 *   log:       [[t, name, x, y], …]     timeline; each row lasts until the next row's t (always sums to 24h/day)
 *   schedules: [{id, name, hhmm, days, on, last}]   auto clock-in, days "12345" = Mon–Fri
 * Colors are never stored: computed live from (x, y) and the theme. Editing tags never rewrites the log.
 */

// ---------------------------------------------------------------- storage
const KEY = "clockinmetron.v1";
const DEFAULT_TAGS = [
  ["Sleep", -0.90, -0.90], ["Shower", -0.75, -0.70], ["Skincare", -0.55, -0.85],
  ["YouTube", -0.85, -0.45], ["Engineering", -0.45, -0.35], ["Chores", -0.20, -0.60],
  ["Cooking & Eating", -0.35, 0.15], ["Dating Apps", -0.65, 0.45], ["Gym", 0.15, 0.20],
  ["Walk outside", 0.80, -0.40], ["Friends / Going out", 0.60, 0.80],
];
const nowS = () => Date.now() / 1000;
let S = load();

function load() {
  try {
    const d = JSON.parse(localStorage.getItem(KEY));
    if (d && Array.isArray(d.tags) && Array.isArray(d.log)) return Object.assign({schedules: [], settings: {}}, d);
  } catch (e) { /* fall through to a fresh start */ }
  return {
    tags: DEFAULT_TAGS.map(([name, x, y]) => ({name, x, y})),
    log: [[nowS(), "Sleep", -0.90, -0.90]],
    schedules: [], settings: {theme: "Nature"},
  };
}
const save = () => localStorage.setItem(KEY, JSON.stringify(S));
const tag = name => S.tags.find(t => t.name === name);
const current = () => S.log[S.log.length - 1];
const firstStart = () => (S.log.find(r => r[1] != null) || [nowS()])[0];

function compact() {
  S.log.sort((a, b) => a[0] - b[0]);
  S.log = S.log.filter((r, i, L) => {
    if (i === 0) return r[1] != null;
    const p = L[i - 1];
    return !(r[1] === p[1] && r[2] === p[2] && r[3] === p[3]);
  });
  save();
}

function clockIn(name, t = nowS()) {
  const g = tag(name), c = current();
  if (c && c[1] === name && c[2] === g.x && c[3] === g.y) return;
  if (c && t - c[0] < 1) { c[1] = name; c[2] = g.x; c[3] = g.y; }
  else S.log.push([t, name, g.x, g.y]);
  compact();
}

function logAt(name, t) {
  const g = tag(name);
  S.log = S.log.filter(r => r[0] !== t);
  S.log.push([t, name, g.x, g.y]);
  compact();
}

/** Overwrite [s, e) with name. e = null: from s until now and keep running. */
function logBlock(name, s, e) {
  const g = tag(name);
  if (e == null) {
    S.log = S.log.filter(r => r[0] < s);
  } else {
    let after = null;
    for (const r of S.log) if (r[0] <= e) after = r;
    S.log = S.log.filter(r => !(r[0] >= s && r[0] < e));
    if (!S.log.some(r => r[0] === e)) S.log.push([e, ...(after ? after.slice(1) : [null, null, null])]);
  }
  S.log.push([s, name, g.x, g.y]);
  compact();
}

/** [{name, x, y, a, b}] covering [s, e); the running entry ends at now. */
function segments(s, e, now = nowS()) {
  const L = S.log, out = [];
  let i = 0;
  while (i + 1 < L.length && L[i + 1][0] <= s) i++;
  for (; i < L.length && L[i][0] < e; i++) {
    const b = i + 1 < L.length ? L[i + 1][0] : now;
    if (L[i][1] != null && b > s) out.push({name: L[i][1], x: L[i][2], y: L[i][3], a: L[i][0], b});
  }
  return out;
}

const dayBounds = d => [new Date(d.getFullYear(), d.getMonth(), d.getDate()) / 1000,
                        new Date(d.getFullYear(), d.getMonth(), d.getDate() + 1) / 1000];

function daySummary(d, now = nowS()) {
  const [ds, de] = dayBounds(d);
  const byName = {}, xy = {}, quads = {"Outdoor·Social": 0, "Indoor·Social": 0, "Indoor·Alone": 0, "Outdoor·Alone": 0};
  let sx = 0, sy = 0;
  for (const g of segments(ds, de, now)) {
    const dur = Math.min(g.b, de, now) - Math.max(g.a, ds);
    if (dur <= 0) continue;
    byName[g.name] = (byName[g.name] || 0) + dur;
    xy[g.name] = [g.x, g.y];
    quads[(g.x >= 0 ? "Outdoor" : "Indoor") + "·" + (g.y >= 0 ? "Social" : "Alone")] += dur;
    sx += g.x * dur; sy += g.y * dur;
  }
  const tracked = Object.values(byName).reduce((a, b) => a + b, 0), span = de - ds;
  const future = Math.max(0, de - Math.max(now, ds));
  return {byName, xy, quads, span, future, untracked: span - tracked - future,
          center: tracked ? [sx / tracked, sy / tracked] : null};
}

/** Fire every schedule occurrence since its last run, at the exact time (back-fills if the app was closed). */
function applySchedules(now = nowS()) {
  const due = [];
  for (const sc of S.schedules) {
    if (!sc.on) continue;
    const last = sc.last || now;
    const [h, m] = sc.hhmm.split(":").map(Number);
    const d = new Date(last * 1000); d.setHours(0, 0, 0, 0);
    for (; d / 1000 <= now; d.setDate(d.getDate() + 1)) {
      const t = new Date(d.getFullYear(), d.getMonth(), d.getDate(), h, m) / 1000;
      const iso = (d.getDay() + 6) % 7 + 1;
      if (sc.days.includes(String(iso)) && last < t && t <= now && tag(sc.name)) due.push([t, sc.name]);
    }
    sc.last = now;
  }
  due.sort((a, b) => a[0] - b[0]).forEach(([t, n]) => logAt(n, t));
  return due.length;
}

// ---------------------------------------------------------------- colors (same math as desktop themes.py)
const THEMES = {
  Nature: {hue0: 85, dir: -1, light: 0.55, sat: 0.75},
  Pastel: {hue0: 85, dir: -1, light: 0.74, sat: 0.65},
  Deep:   {hue0: 85, dir: -1, light: 0.40, sat: 0.80},
  Sunset: {hue0: 30, dir: -1, light: 0.55, sat: 0.80},
};
function hsl(x, y) {
  const p = THEMES[S.settings.theme] || THEMES.Nature;
  const ang = Math.atan2(y, x) * 180 / Math.PI, r = Math.min(1, Math.hypot(x, y));
  return [((p.hue0 + p.dir * ang) % 360 + 360) % 360, 0.08 + (p.sat - 0.08) * r, p.light];
}
function hslToRgb(h, s, l) {
  const k = n => (n + h / 30) % 12, a = s * Math.min(l, 1 - l);
  const f = n => l - a * Math.max(-1, Math.min(k(n) - 3, 9 - k(n), 1));
  return [f(0) * 255, f(8) * 255, f(4) * 255];
}
const color = (x, y) => {
  if (x == null) return "#555555";
  const [h, s, l] = hsl(x, y);
  return `hsl(${h.toFixed(1)} ${(s * 100).toFixed(1)}% ${(l * 100).toFixed(1)}%)`;
};
const textOn = (x, y) => {
  const [r, g, b] = hslToRgb(...hsl(x, y));
  return 0.299 * r + 0.587 * g + 0.114 * b > 150 ? "#000" : "#fff";
};
const describe = (x, y) => `${Math.round(Math.abs(x) * 100)}% ${x >= 0 ? "Outdoor" : "Indoor"} · ` +
                           `${Math.round(Math.abs(y) * 100)}% ${y >= 0 ? "Social" : "Alone"}`;

// ---------------------------------------------------------------- sun (standard sunrise equation)
const RAD = Math.PI / 180, J1970 = 2440588, J2000 = 2451545, DAY_MS = 864e5, OBL = RAD * 23.4397;
function sunTimes(day) {
  const {lat, lon} = S.settings;
  if (lat == null || lon == null) return [null, null];
  const date = new Date(day.getFullYear(), day.getMonth(), day.getDate(), 12);
  const lw = RAD * -lon, phi = RAD * lat, d = date / DAY_MS - 0.5 + J1970 - J2000;
  const n = Math.round(d - 0.0009 - lw / (2 * Math.PI));
  const ds = 0.0009 + lw / (2 * Math.PI) + n;
  const M = RAD * (357.5291 + 0.98560028 * ds);
  const L = M + RAD * (1.9148 * Math.sin(M) + 0.02 * Math.sin(2 * M) + 0.0003 * Math.sin(3 * M)) + RAD * 102.9372 + Math.PI;
  const dec = Math.asin(Math.sin(OBL) * Math.sin(L));
  const noon = J2000 + ds + 0.0053 * Math.sin(M) - 0.0069 * Math.sin(2 * L);
  const cosw = (Math.sin(-0.833 * RAD) - Math.sin(phi) * Math.sin(dec)) / (Math.cos(phi) * Math.cos(dec));
  if (Math.abs(cosw) > 1) return [null, null];               // polar day / night
  const w = Math.acos(cosw);
  const set = J2000 + 0.0009 + (w + lw) / (2 * Math.PI) + n + 0.0053 * Math.sin(M) - 0.0069 * Math.sin(2 * L);
  const toS = j => (j + 0.5 - J1970) * DAY_MS / 1000;
  return [toS(noon - (set - noon)), toS(set)];
}
/** ["day"|"night", fraction, seconds to next sunrise/sunset] or null. */
function sunProgress(now = nowS()) {
  const ev = [];
  for (const k of [-1, 0, 1]) {
    const d = new Date(); d.setDate(d.getDate() + k);
    const [r, s] = sunTimes(d);
    if (r) ev.push([r, "day"]);
    if (s) ev.push([s, "night"]);
  }
  ev.sort((a, b) => a[0] - b[0]);
  for (let i = 0; i + 1 < ev.length; i++)
    if (ev[i][0] <= now && now < ev[i + 1][0])
      return [ev[i][1], (now - ev[i][0]) / (ev[i + 1][0] - ev[i][0]), ev[i + 1][0] - now];
  return null;
}

// ---------------------------------------------------------------- helpers
const $ = id => document.getElementById(id);
const pad = n => String(n).padStart(2, "0");
const fmt = sec => { sec = Math.round(sec); return `${pad(Math.floor(sec / 3600))}:${pad(Math.floor(sec % 3600 / 60))}:${pad(sec % 60)}`; };
const hm = t => { const d = new Date(t * 1000); return `${pad(d.getHours())}:${pad(d.getMinutes())}`; };
const hms = t => { const d = new Date(t * 1000); return `${hm(t)}:${pad(d.getSeconds())}`; };
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const clip = v => Math.max(-1, Math.min(1, Math.round(v * 1000) / 1000));
function fit(cv) {
  const dpr = window.devicePixelRatio || 1, w = cv.clientWidth, h = cv.clientHeight;
  if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) {
    cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
  }
  const ctx = cv.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return [ctx, w, h];
}
function label(ctx, text, x, y, fg, bg, align = "left", base = "top") {
  ctx.textAlign = align; ctx.textBaseline = base;
  const w = ctx.measureText(text).width, fs = parseInt(ctx.font) || 12;
  const lx = align === "left" ? x : align === "right" ? x - w : x - w / 2;
  const ly = base === "top" ? y : base === "bottom" ? y - fs : y - fs / 2;
  if (bg) { ctx.fillStyle = bg; ctx.fillRect(lx - 3, ly - 2, w + 6, fs + 4); }
  ctx.fillStyle = fg; ctx.fillText(text, x, y);
}

// ---------------------------------------------------------------- chart
const LIM = 1.12, MIN_HALF = 0.08, BG_ALPHA = 0.28, PANEL_RGB = [42, 44, 51];
const view = {cx: 0, cy: 0, half: LIM};
const chartEl = $("chart");
let picking = null;          // {prompt, cb} while choosing a task
let bgCache = {key: null, img: null};

function geom() {
  const w = chartEl.clientWidth, m = 24;
  return {ox: m, oy: m, side: w - 2 * m};
}
function toPx(x, y) {
  const {ox, oy, side} = geom(), s = side / (2 * view.half);
  return [ox + (x - view.cx + view.half) * s, oy + (view.cy + view.half - y) * s];
}
function toData(px, py) {
  const {ox, oy, side} = geom(), s = side / (2 * view.half);
  return [(px - ox) / s + view.cx - view.half, view.cy + view.half - (py - oy) / s];
}
function hit(px, py) {
  let best = null, bd = 22 * 22;
  S.tags.forEach((t, i) => {
    const [qx, qy] = toPx(t.x, t.y), d = (qx - px) ** 2 + (qy - py) ** 2;
    if (d < bd) { best = i; bd = d; }
  });
  return best;
}
function backdrop() {
  const key = [S.settings.theme, view.cx, view.cy, view.half].join();
  if (bgCache.key !== key) {
    const n = 72, c = document.createElement("canvas");
    c.width = c.height = n;
    const cx = c.getContext("2d"), img = cx.createImageData(n, n);
    for (let j = 0; j < n; j++) for (let i = 0; i < n; i++) {
      const x = view.cx - view.half + (i + 0.5) / n * 2 * view.half, y = view.cy + view.half - (j + 0.5) / n * 2 * view.half;
      const rgb = Math.abs(x) > 1 || Math.abs(y) > 1 ? PANEL_RGB
        : hslToRgb(...hsl(x, y)).map((v, k) => v * BG_ALPHA + PANEL_RGB[k] * (1 - BG_ALPHA));
      img.data.set([...rgb.map(Math.round), 255], (j * n + i) * 4);
    }
    cx.putImageData(img, 0, 0);
    bgCache = {key, img: c};
  }
  return bgCache.img;
}

function drawChart() {
  const [ctx, w, h] = fit(chartEl), {ox, oy, side} = geom();
  ctx.clearRect(0, 0, w, h);
  ctx.imageSmoothingEnabled = true;
  ctx.drawImage(backdrop(), ox, oy, side, side);
  const [x0, y0] = toPx(0, 0);
  ctx.strokeStyle = "#6a6c74"; ctx.lineWidth = 1;
  ctx.beginPath();
  if (x0 > ox && x0 < ox + side) { ctx.moveTo(x0, oy); ctx.lineTo(x0, oy + side); }
  if (y0 > oy && y0 < oy + side) { ctx.moveTo(ox, y0); ctx.lineTo(ox + side, y0); }
  ctx.stroke();
  ctx.font = "bold 11px system-ui"; ctx.fillStyle = "#e8e8ea"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
  ctx.fillText("▲ SOCIAL", ox + side / 2, oy / 2); ctx.fillText("▼ ALONE", ox + side / 2, oy + side + oy / 2);
  for (const [txt, x, a] of [["INDOOR", ox / 2, -Math.PI / 2], ["OUTDOOR", ox + side + ox / 2, Math.PI / 2]]) {
    ctx.save(); ctx.translate(x, oy + side / 2); ctx.rotate(a); ctx.fillText(txt, 0, 0); ctx.restore();
  }
  ctx.save();
  ctx.beginPath(); ctx.rect(ox, oy, side, side); ctx.clip();
  const sum = daySummary(selDay);
  if (sum.center) {
    const [px, py] = toPx(...sum.center);
    ctx.font = "18px system-ui"; ctx.fillStyle = "#fff"; ctx.fillText("★", px, py);
  }
  const cur = current()[1], placed = [];
  const dots = S.tags.map((t, i) => ({t, i, p: toPx(t.x, t.y)}));
  for (const {t, i, p: [px, py]} of dots) {
    const r = i === press?.idx && press.moved ? 11 : 8;
    if (t.name === cur) {
      ctx.strokeStyle = color(t.x, t.y); ctx.lineWidth = 3;
      ctx.beginPath(); ctx.arc(px, py, r + 6, 0, 7); ctx.stroke();
    }
    ctx.fillStyle = color(t.x, t.y); ctx.strokeStyle = "#fff"; ctx.lineWidth = 1.5;
    ctx.beginPath(); ctx.arc(px, py, r, 0, 7); ctx.fill(); ctx.stroke();
    placed.push([px - r, py - r, px + r, py + r]);
  }
  // labels: first free spot among 8 positions around the dot
  ctx.textBaseline = "top";
  const order = [...dots].sort((a, b) => (b.t.name === cur) - (a.t.name === cur));
  for (const {t, p: [px, py]} of order) {
    ctx.font = (t.name === cur ? "bold " : "") + "12px system-ui";
    const tw = ctx.measureText(t.name).width, th = 14, g = 11;
    const cands = [[px + g, py - th / 2], [px - g - tw, py - th / 2], [px - tw / 2, py - g - th], [px - tw / 2, py + g],
                   [px + g, py - g - th], [px - g - tw, py - g - th], [px + g, py + g], [px - g - tw, py + g]];
    const inside = c => c[0] >= ox + 2 && c[0] + tw <= ox + side - 2 && c[1] >= oy + 2 && c[1] + th <= oy + side - 2;
    const free = c => inside(c) && !placed.some(r => c[0] < r[2] && c[0] + tw > r[0] && c[1] < r[3] && c[1] + th > r[1]);
    const [lx, ly] = cands.find(free) || cands.find(inside) || cands[0];
    placed.push([lx - 2, ly - 1, lx + tw + 2, ly + th + 1]);
    ctx.fillStyle = "#1e1f24cc"; ctx.fillRect(lx - 2, ly - 1, tw + 4, th + 2);
    ctx.fillStyle = "#e8e8ea"; ctx.textAlign = "left"; ctx.fillText(t.name, lx, ly);
  }
  if (press?.moved && press.idx != null) {
    const t = S.tags[press.idx], [px, py] = toPx(t.x, t.y);
    ctx.font = "12px system-ui";
    label(ctx, describe(t.x, t.y), Math.min(Math.max(px, ox + 90), ox + side - 90), py - 38, "#fff", "#111216", "center");
  }
  ctx.restore();
  ctx.strokeStyle = "#3a3c44"; ctx.lineWidth = 1; ctx.strokeRect(ox, oy, side, side);
  $("zoomReset").hidden = view.half >= LIM - 1e-6;
  $("pickBanner").hidden = !picking;
  if (picking) $("pickText").textContent = picking.prompt;
}

function zoomAt(px, py, newHalf) {
  const [mx, my] = toData(px, py);
  newHalf = Math.max(MIN_HALF, Math.min(LIM, newHalf));
  const f = newHalf / view.half;
  view.cx = mx - (mx - view.cx) * f; view.cy = my - (my - view.cy) * f; view.half = newHalf;
  clampView();
}
function clampView() {
  const l = LIM - view.half;
  view.cx = Math.max(-l, Math.min(l, view.cx)); view.cy = Math.max(-l, Math.min(l, view.cy));
}

const ptrs = new Map();
let press = null, pinch = null;
const pos = e => { const r = chartEl.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
chartEl.addEventListener("pointerdown", e => {
  try { chartEl.setPointerCapture(e.pointerId); } catch {}
  const [x, y] = pos(e);
  ptrs.set(e.pointerId, [x, y]);
  if (ptrs.size === 2) {
    if (press) clearTimeout(press.long);
    press = null;
    const [a, b] = [...ptrs.values()];
    pinch = {d0: Math.hypot(a[0] - b[0], a[1] - b[1]), half0: view.half, view0: {...view}, mid: [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]};
    return;
  }
  const idx = hit(x, y);
  press = {idx, x, y, moved: false, view0: {...view}, done: false};
  if (idx != null) press.long = setTimeout(() => { if (press && !press.moved) { press.done = true; editTag(idx); } }, 600);
});
chartEl.addEventListener("pointermove", e => {
  if (!ptrs.has(e.pointerId)) return;
  const [x, y] = pos(e);
  ptrs.set(e.pointerId, [x, y]);
  if (pinch && ptrs.size === 2) {
    const [a, b] = [...ptrs.values()], d = Math.hypot(a[0] - b[0], a[1] - b[1]);
    Object.assign(view, pinch.view0);
    zoomAt(pinch.mid[0], pinch.mid[1], pinch.half0 * pinch.d0 / Math.max(d, 1));
    drawChart();
    return;
  }
  if (!press || press.done) return;
  if (!press.moved && Math.hypot(x - press.x, y - press.y) < 8) return;
  press.moved = true;
  clearTimeout(press.long);
  if (press.idx != null) {
    const [dx, dy] = toData(x, y), t = S.tags[press.idx];
    t.x = clip(dx); t.y = clip(dy);
  } else if (view.half < LIM) {
    const s = geom().side / (2 * view.half);
    view.cx = press.view0.cx - (x - press.x) / s; view.cy = press.view0.cy + (y - press.y) / s;
    clampView();
  }
  drawChart();
});
const endPointer = e => {
  ptrs.delete(e.pointerId);
  if (pinch) { if (ptrs.size < 2) pinch = null; return; }
  const p = press; press = null;
  if (!p) return;
  clearTimeout(p.long);
  if (p.done || e.type === "pointercancel") return drawChart();
  if (p.moved) { if (p.idx != null) { save(); renderAll(); } return; }
  if (p.idx != null) {
    const name = S.tags[p.idx].name;
    if (picking) { const cb = picking.cb; picking = null; cb(name); }
    else { clockIn(name); navigator.vibrate?.(15); }
    renderAll();
  } else if (!picking) addTask(...toData(p.x, p.y).map(clip));
};
chartEl.addEventListener("pointerup", endPointer);
chartEl.addEventListener("pointercancel", endPointer);
chartEl.addEventListener("wheel", e => {
  e.preventDefault();
  zoomAt(...pos(e), view.half * (e.deltaY < 0 ? 0.8 : 1.25));
  drawChart();
}, {passive: false});
$("zoomReset").onclick = () => { Object.assign(view, {cx: 0, cy: 0, half: LIM}); drawChart(); };

function addTask(x, y) {
  const name = prompt(`New task at ${describe(x, y)}:`);
  if (!name || !name.trim()) return;
  if (tag(name.trim())) return alert(`'${name.trim()}' already exists.`);
  S.tags.push({name: name.trim(), x, y});
  save(); renderAll();
}
function editTag(i) {
  const t = S.tags[i];
  navigator.vibrate?.(25);
  const n = prompt(`Rename '${t.name}' (applies from the next clock-in).\nClear the box to delete it.`, t.name);
  if (n === null) return drawChart();
  const name = n.trim();
  if (!name) {
    if (confirm(`Delete '${t.name}' from the chart?\nPast timeline entries keep their name and color.`)) S.tags.splice(i, 1);
  } else if (name !== t.name) {
    if (tag(name)) return alert(`'${name}' already exists.`);
    S.schedules.forEach(sc => { if (sc.name === t.name) sc.name = name; });
    t.name = name;
  }
  save(); renderAll();
}

// ---------------------------------------------------------------- pick flow (reassign / schedule)
let selection = null;         // [s, e] being reassigned
let returnScroll = 0;
function pick(prompt, cb) {
  cancelPick();
  picking = {prompt, cb};
  returnScroll = window.scrollY;
  window.scrollTo({top: 0, behavior: "smooth"});
  drawChart();
}
function cancelPick() {
  if (!picking) return;
  const cb = picking.cb; picking = null; cb(null);
  drawChart();
}
$("pickCancel").onclick = () => { cancelPick(); window.scrollTo({top: returnScroll, behavior: "smooth"}); };

function selectRange(s, e) {
  const now = nowS();
  [s, e] = [Math.min(s, e), Math.max(s, e)];
  cancelPick();
  if (s >= now - 1 || e - s < 1) { selection = null; return renderAll(); }
  selection = [s, e];
  const end = e >= now - 1 ? "now" : hm(e);
  pick(`Reassign ${DAYS[(new Date(s * 1000).getDay() + 6) % 7]} ${hm(s)} – ${end} to…`, name => {
    const sel = selection; selection = null;
    if (name && sel) {
      logBlock(name, sel[0], sel[1] >= nowS() - 1 ? null : sel[1]);
      setTimeout(() => window.scrollTo({top: returnScroll, behavior: "smooth"}), 250);
    }
    renderAll();
  });
  renderAll();
}

/** Shared touch logic for the day and live canvases.
 *  mouse: drag = select range.  touch: tap a block = select it; hold then drag = select range;
 *  a quick swipe still scrolls the page (touch-action: pan-y). */
function rangeSelect(cv, timeAt, snap, horizontal) {
  let st = null;
  cv.addEventListener("pointerdown", e => {
    const r = cv.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
    st = {x, y, id: e.pointerId, active: e.pointerType === "mouse" || horizontal, moved: false, t0: timeAt(x, y)};
    if (!st.active) st.hold = setTimeout(() => { if (st && !st.moved) { st.active = true; navigator.vibrate?.(20); } }, 350);
  });
  cv.addEventListener("touchmove", e => { if (st && (horizontal ? st.moved : st.active)) e.preventDefault(); }, {passive: false});
  cv.addEventListener("pointermove", e => {
    if (!st || e.pointerId !== st.id) return;
    const r = cv.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
    if (!st.moved && Math.hypot(x - st.x, y - st.y) < 8) return;
    if (horizontal && !st.moved && e.pointerType !== "mouse" && Math.abs(y - st.y) > Math.abs(x - st.x)) { st = null; return; }
    if (!st.active) { clearTimeout(st.hold); st = null; return; }   // it's a scroll
    if (!st.moved) { try { cv.setPointerCapture(e.pointerId); } catch {} cancelPick(); }
    st.moved = true;
    const t1 = timeAt(x, y);
    selection = [snap(Math.min(st.t0, t1)), snap(Math.max(st.t0, t1))];
    drawTab();
  });
  const end = e => {
    if (!st || e.pointerId !== st.id) return;
    const s = st; st = null;
    clearTimeout(s.hold);
    if (e.type === "pointercancel") return;
    if (s.moved) return selection && selectRange(...selection);
    const r = cv.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
    const b = cv._blocks.find(k => x >= k[0] && x <= k[2] && y >= k[1] && y <= k[3]);
    if (b) selectRange(b[4], b[5]);
    else { cancelPick(); selection = null; drawTab(); }
  };
  cv.addEventListener("pointerup", end);
  cv.addEventListener("pointercancel", end);
}

// ---------------------------------------------------------------- day view
let selDay = new Date();
const dayCv = $("dayCanvas");
dayCv._blocks = [];
const DAY_TOP = 10, GUT = 44;
function dayGeom() { return (dayCv.clientHeight - 2 * DAY_TOP) / 24; }

function drawDay() {
  const [ctx, w] = fit(dayCv), hh = dayGeom(), now = nowS(), [ds, de] = dayBounds(selDay);
  const yOf = t => DAY_TOP + (t - ds) / (de - ds) * 24 * hh;
  ctx.fillStyle = "#2a2c33"; ctx.fillRect(0, 0, w, dayCv.clientHeight);
  const [rise, set] = sunTimes(selDay);
  ctx.fillStyle = "#17181c";
  if (rise) ctx.fillRect(GUT, yOf(ds), w - GUT, yOf(rise) - yOf(ds));
  if (set) ctx.fillRect(GUT, yOf(set), w - GUT, yOf(de) - yOf(set));
  ctx.font = "11px system-ui"; ctx.textAlign = "right"; ctx.textBaseline = "middle";
  for (let hr = 0; hr <= 24; hr++) {
    const y = DAY_TOP + hr * hh;
    ctx.fillStyle = "#3a3c44"; ctx.fillRect(GUT, y, w - GUT, 1);
    if (hr < 24 && hr % 2 === 0) { ctx.fillStyle = "#8a8c96"; ctx.fillText(`${pad(hr)}:00`, GUT - 6, y); }
  }
  const first = firstStart();
  if (first > ds && ds < now) { ctx.fillStyle = "#33353c"; ctx.fillRect(GUT + 2, yOf(ds), w - GUT - 4, yOf(Math.min(first, de, now)) - yOf(ds)); }
  dayCv._blocks = [];
  for (const g of segments(ds, Math.min(de, now), now)) {
    const a = Math.max(g.a, ds), b = Math.min(g.b, de, now);
    if (b <= a) continue;
    const y0 = yOf(a), y1 = Math.max(yOf(b), y0 + 1);
    ctx.fillStyle = color(g.x, g.y); ctx.fillRect(GUT + 2, y0, w - GUT - 4, y1 - y0);
    ctx.fillStyle = "#1e1f24"; ctx.fillRect(GUT + 2, y0, w - GUT - 4, 1);
    dayCv._blocks.push([GUT, y0, w, y1, g.a, Math.min(g.b, now)]);
    if (y1 - y0 >= 14) {
      ctx.fillStyle = textOn(g.x, g.y); ctx.textAlign = "left"; ctx.textBaseline = "top"; ctx.font = "600 12px system-ui";
      ctx.fillText(`${g.name}  ${fmt(b - a).slice(0, 5)}`, GUT + 8, y0 + 2);
    }
  }
  ctx.font = "bold 11px system-ui";
  for (const [t, sym] of [[rise, "☀"], [set, "☾"]]) {
    if (!t) continue;
    const y = yOf(t);
    ctx.strokeStyle = "#ffb347"; ctx.setLineDash([4, 3]); ctx.beginPath(); ctx.moveTo(GUT, y); ctx.lineTo(w, y); ctx.stroke(); ctx.setLineDash([]);
    label(ctx, `${sym} ${hm(t)}`, w - 6, y, "#ffb347", "#1e1f24", "right", "middle");
  }
  if (ds <= now && now < de) { ctx.fillStyle = "#ff3b3b"; ctx.fillRect(GUT - 4, yOf(now) - 1, w - GUT + 4, 2.5); }
  if (selection) {
    const a = Math.max(selection[0], ds), b = Math.min(selection[1], de);
    if (b > a) {
      ctx.fillStyle = "#ffffff44"; ctx.fillRect(GUT + 1, yOf(a), w - GUT - 2, yOf(b) - yOf(a));
      ctx.strokeStyle = "#fff"; ctx.lineWidth = 2; ctx.setLineDash([5, 3]);
      ctx.strokeRect(GUT + 1, yOf(a), w - GUT - 2, yOf(b) - yOf(a)); ctx.setLineDash([]); ctx.lineWidth = 1;
      ctx.font = "bold 12px system-ui";
      label(ctx, `${hm(selection[0])} – ${hm(selection[1])}`, (GUT + w) / 2, yOf(a) + 4, "#111216", "#fff", "center", "top");
    }
  }
  const today = new Date().toDateString() === selDay.toDateString();
  $("dayLabel").textContent = selDay.toLocaleDateString(undefined, {weekday: "short", month: "short", day: "numeric"}) + (today ? " · today" : "");
}
rangeSelect(dayCv, (x, y) => {
  const [ds, de] = dayBounds(selDay);
  return ds + Math.min(Math.max((y - DAY_TOP) / (24 * dayGeom()), 0), 1) * (de - ds);
}, t => Math.round(t / 300) * 300, false);
const shiftDay = n => { selDay = n === 0 ? new Date() : new Date(selDay.getFullYear(), selDay.getMonth(), selDay.getDate() + n); renderAll(); };
$("dayPrev").onclick = () => shiftDay(-1);
$("dayNext").onclick = () => shiftDay(1);
$("dayToday").onclick = () => shiftDay(0);

function drawSummary() {
  const s = daySummary(selDay), span = s.span, rows = [];
  const row = (dot, name, sec, pct, cls = "") =>
    `<tr class="${cls}"><td>${dot ? `<span style="color:${dot}">■</span> ` : ""}${name}</td><td>${fmt(sec)}</td><td>${pct}</td></tr>`;
  Object.entries(s.byName).sort((a, b) => b[1] - a[1]).forEach(([n, sec]) =>
    rows.push(row(color(...s.xy[n]), escapeHtml(n), sec, (sec / span * 100).toFixed(1) + "%")));
  if (s.untracked > 0.5) rows.push(row(null, "Untracked", s.untracked, (s.untracked / span * 100).toFixed(1) + "%"));
  if (s.future > 0) rows.push(row(null, "Rest of day", s.future, (s.future / span * 100).toFixed(1) + "%"));
  rows.push(row(null, "TOTAL", span, "100%", "total"));
  rows.push(`<tr class="sect"><td colspan="3">Where the day went</td></tr>`);
  const tracked = Object.values(s.quads).reduce((a, b) => a + b, 0) || 1;
  const QXY = {"Outdoor·Social": [0.7, 0.7], "Indoor·Social": [-0.7, 0.7], "Indoor·Alone": [-0.7, -0.7], "Outdoor·Alone": [0.7, -0.7]};
  for (const [q, sec] of Object.entries(s.quads)) rows.push(row(color(...QXY[q]), q, sec, Math.round(sec / tracked * 100) + "%"));
  if (s.center) rows.push(`<tr class="sect"><td colspan="3" style="color:${color(...s.center)}">★ Day center: ${describe(...s.center)}</td></tr>`);
  $("sumTable").innerHTML = rows.join("");
}
const escapeHtml = s => s.replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));

// ---------------------------------------------------------------- live view
const liveCv = $("liveCanvas");
liveCv._blocks = [];
let liveSpan = 300;
const LIVE_ZOOMS = [["1 min", 60], ["5 min", 300], ["15 min", 900], ["1 hr", 3600], ["6 hr", 21600]];
$("liveZooms").innerHTML = LIVE_ZOOMS.map(([l, s]) => `<button data-span="${s}">${l}</button>`).join("");
$("liveZooms").onclick = e => { if (e.target.dataset.span) { liveSpan = +e.target.dataset.span; selection = null; cancelPick(); } };
const liveStart = now => now - 0.85 * liveSpan;

function drawLive() {
  const [ctx, w, h] = fit(liveCv), now = nowS(), vs = liveStart(now), ve = vs + liveSpan, pps = w / liveSpan;
  const xOf = t => (t - vs) * pps, top = 40, bot = h - 26;
  ctx.fillStyle = "#2a2c33"; ctx.fillRect(0, 0, w, h);
  ctx.fillStyle = "#24262c"; ctx.fillRect(xOf(now), top, w - xOf(now), bot - top);
  liveCv._blocks = [];
  for (const g of segments(vs, ve, now)) {
    const b = Math.min(g.b, now), x0 = Math.max(xOf(g.a), -2), x1 = Math.min(xOf(b), w + 2);
    if (x1 <= x0) continue;
    ctx.fillStyle = color(g.x, g.y); ctx.fillRect(x0, top, x1 - x0, bot - top);
    ctx.fillStyle = "#1e1f24"; ctx.fillRect(x0, top, 2, bot - top);
    liveCv._blocks.push([x0, top, x1, bot, g.a, b]);
    if (x1 - x0 > 60) {
      const tx = Math.min(Math.max(x0, 0) + 10, x1 - 50);
      ctx.fillStyle = textOn(g.x, g.y); ctx.textAlign = "left";
      ctx.font = "800 20px system-ui"; ctx.textBaseline = "bottom"; ctx.fillText(g.name, tx, (top + bot) / 2 - 2);
      ctx.font = "13px system-ui"; ctx.textBaseline = "top"; ctx.fillText(fmt(b - g.a), tx, (top + bot) / 2 + 2);
    }
  }
  // time ticks
  const steps = [5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 10800];
  const step = steps.find(s => s * pps >= 70) || 10800, [ds] = dayBounds(new Date(vs * 1000));
  ctx.font = "11px system-ui"; ctx.textAlign = "center"; ctx.textBaseline = "top";
  for (let t = ds + Math.ceil((vs - ds) / step) * step; t < ve; t += step) {
    ctx.fillStyle = "#3a3c44"; ctx.fillRect(xOf(t), bot, 1, 6);
    ctx.fillStyle = "#8a8c96"; ctx.fillText(step < 60 ? hms(t) : hm(t), xOf(t), bot + 8);
  }
  for (const k of [-1, 0]) {
    const d = new Date(); d.setDate(d.getDate() + k);
    sunTimes(d).forEach((t, i) => {
      if (!t || t < vs || t > ve) return;
      ctx.fillStyle = "#ffb347"; ctx.fillRect(xOf(t) - 1, top, 2, bot - top);
      ctx.font = "bold 12px system-ui";
      label(ctx, `${i ? "☾ Sunset" : "☀ Sunrise"} ${hm(t)}`, xOf(t) + 5, top + 6, "#ffb347", "#1e1f24");
    });
  }
  if (selection && selection[1] > vs && selection[0] < ve) {
    const x0 = Math.max(xOf(selection[0]), 0), x1 = Math.min(xOf(selection[1]), w);
    ctx.fillStyle = "#ffffff44"; ctx.fillRect(x0, top - 4, x1 - x0, bot - top + 8);
    ctx.strokeStyle = "#fff"; ctx.lineWidth = 2; ctx.setLineDash([5, 3]);
    ctx.strokeRect(x0, top - 4, x1 - x0, bot - top + 8); ctx.setLineDash([]); ctx.lineWidth = 1;
    ctx.font = "bold 12px system-ui";
    label(ctx, `${hms(selection[0])} – ${hms(selection[1])}`, (x0 + x1) / 2, top + 8, "#111216", "#fff", "center");
  }
  const c = current(), xn = xOf(now), pulse = 0.5 + 0.5 * Math.sin(now * 2 * Math.PI), glow = 3 + 5 * pulse;
  const [hh, ss, ll] = hsl(c[2], c[3]);
  ctx.fillStyle = `hsl(${hh} ${ss * 100}% ${(ll + (1 - ll) * (0.3 + 0.3 * pulse)) * 100}%)`;
  ctx.fillRect(xn - glow, top, glow, bot - top);
  ctx.fillStyle = "#ff3b3b"; ctx.fillRect(xn - 1, top - 10, 2, bot - top + 14);
  ctx.font = "bold 13px system-ui"; ctx.textAlign = "center"; ctx.textBaseline = "bottom"; ctx.fillStyle = "#ff6b6b";
  ctx.fillText(hms(now), Math.min(xn, w - 34), top - 12);
  for (const b of $("liveZooms").children) b.classList.toggle("on", +b.dataset.span === liveSpan);
}
rangeSelect(liveCv, x => liveStart(nowS()) + x / (liveCv.clientWidth / liveSpan),
  t => Math.round(t / (liveSpan <= 900 ? 1 : 60)) * (liveSpan <= 900 ? 1 : 60), true);

// ---------------------------------------------------------------- schedules
const PRESETS = {"12345": "Weekdays", "67": "Weekend", "1234567": "Every day"};
let schDays = "12345";
function drawSchedForm() {
  const sel = $("schTask"), keep = sel.value;
  sel.innerHTML = S.tags.map(t => `<option>${escapeHtml(t.name)}</option>`).join("");
  if (tag(keep)) sel.value = keep;
  $("schDays").innerHTML = DAYS.map((d, i) => `<button data-d="${i + 1}" class="${schDays.includes(i + 1) ? "on" : ""}">${d}</button>`).join("");
  $("schList").innerHTML = S.schedules.map(sc => {
    const t = tag(sc.name), days = PRESETS[sc.days] || [...sc.days].map(c => DAYS[c - 1]).join(", ");
    return `<li class="${sc.on ? "" : "off"}"><span class="dot" style="background:${t ? color(t.x, t.y) : "#555"}"></span>
      <span class="what">${escapeHtml(sc.name)}${t ? "" : " (task deleted)"}<small>${sc.hhmm} · ${days}</small></span>
      <button data-toggle="${sc.id}">${sc.on ? "On" : "Off"}</button><button data-del="${sc.id}">✕</button></li>`;
  }).join("") || `<li class="hint">No schedules yet.</li>`;
}
$("schDays").onclick = e => {
  const d = e.target.dataset.d;
  if (!d) return;
  schDays = schDays.includes(d) ? schDays.replace(d, "") : [...schDays + d].sort().join("");
  drawSchedForm();
};
$("schPresets").onclick = e => { if (e.target.dataset.days) { schDays = e.target.dataset.days; drawSchedForm(); } };
$("schPick").onclick = () => pick("Auto clock-in: which task?", name => {
  if (name) { $("schTask").value = name; setTimeout(() => $("tab-auto").scrollIntoView({behavior: "smooth"}), 200); }
});
$("schAdd").onclick = () => {
  const hhmm = $("schTime").value, name = $("schTask").value;
  if (!/^\d\d:\d\d$/.test(hhmm) || !schDays || !tag(name)) return alert("Pick a task, a time and at least one day.");
  S.schedules.push({id: Date.now(), name, hhmm, days: schDays, on: true, last: nowS()});
  save(); drawSchedForm();
};
$("schList").onclick = e => {
  const {toggle, del} = e.target.dataset;
  if (toggle) { const sc = S.schedules.find(s => s.id === +toggle); sc.on = !sc.on; sc.last = nowS(); }
  else if (del) S.schedules = S.schedules.filter(s => s.id !== +del);
  else return;
  save(); drawSchedForm();
};

// ---------------------------------------------------------------- settings
$("theme").innerHTML = Object.keys(THEMES).map(t => `<option>${t}</option>`).join("");
$("theme").onchange = e => { S.settings.theme = e.target.value; save(); renderAll(); };
function setLoc(lat, lon) { S.settings.lat = +(+lat).toFixed(3); S.settings.lon = +(+lon).toFixed(3); save(); renderAll(); }
$("geo").onclick = () => {
  if (!navigator.geolocation) return alert("Location isn't available in this browser.");
  $("locLabel").textContent = "locating…";
  navigator.geolocation.getCurrentPosition(p => setLoc(p.coords.latitude, p.coords.longitude),
    err => { $("locLabel").textContent = ""; alert("Couldn't get location: " + err.message); }, {timeout: 15000});
};
$("latlonSave").onclick = () => {
  const lat = parseFloat($("lat").value), lon = parseFloat($("lon").value);
  if (Math.abs(lat) <= 90 && Math.abs(lon) <= 180) setLoc(lat, lon); else alert("lat −90…90, lon −180…180");
};
function download(name, text, type) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], {type}));
  a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
const stamp = () => new Date().toISOString().slice(0, 10);
$("exportJson").onclick = () => download(`clockinmetron_${stamp()}.json`, JSON.stringify(S), "application/json");
$("exportCsv").onclick = () => {
  const now = nowS(), iso = t => new Date(t * 1000).toISOString();
  const lines = ["task,x_outdoor,y_social,start,end,duration_s"];
  S.log.forEach((r, i) => {
    if (r[1] == null) return;
    const e = S.log[i + 1]?.[0];
    lines.push([JSON.stringify(r[1]), r[2], r[3], iso(r[0]), e ? iso(e) : "", Math.round((e || now) - r[0])].join(","));
  });
  download(`clockinmetron_${stamp()}.csv`, lines.join("\n"), "text/csv");
};
$("importJson").onchange = async e => {
  const f = e.target.files[0];
  e.target.value = "";
  if (!f) return;
  try {
    const d = JSON.parse(await f.text());
    if (!Array.isArray(d.tags) || !Array.isArray(d.log)) throw new Error("not a clockinmetron backup");
    if (!confirm(`Replace everything on this phone with ${d.log.length} timeline entries and ${d.tags.length} tasks?`)) return;
    S = Object.assign({schedules: [], settings: {}}, d);
    save(); renderAll();
  } catch (err) { alert("Import failed: " + err.message); }
};

// ---------------------------------------------------------------- tabs + render loop
let tab = "day";
$("tabs").onclick = e => {
  const t = e.target.closest("button")?.dataset.tab;
  if (!t) return;
  tab = t;
  for (const b of $("tabs").children) b.classList.toggle("on", b.dataset.tab === t);
  for (const s of document.querySelectorAll(".tab")) s.hidden = s.id !== "tab-" + t;
  if (t !== "auto") selection = null;
  renderAll();
};
function drawTab() {
  if (tab === "day") drawDay();
  else if (tab === "live") drawLive();
}
function drawHeader() {
  const c = current(), now = nowS();
  $("swatch").style.background = color(c[2], c[3]);
  $("nowName").textContent = c[1] ?? "—";
  $("nowName").style.color = color(c[2], c[3]);
  $("nowTime").textContent = fmt(now - c[0]);
  const p = sunProgress(now);
  if (!p) {
    $("sunFill").style.width = "0";
    $("sunText").textContent = S.settings.lat == null ? "☀ tap to set location" : "☀ no sunrise/sunset today";
    return;
  }
  const [kind, f, left] = p, day = kind === "day";
  $("sunFill").style.width = (f * 100).toFixed(1) + "%";
  $("sunFill").style.background = day ? "#ffb347" : "#6c7bd1";
  $("sunText").style.color = day ? "#ffb347" : "#9aa6e8";
  $("sunText").textContent = `${day ? "☀" : "☾"} ${Math.round(f * 100)}% of ${day ? "daylight" : "night"} · ` +
    `${day ? "sunset" : "sunrise"} in ${Math.floor(left / 3600)}h ${pad(Math.floor(left % 3600 / 60))}m`;
}
$("sunText").onclick = () => { if (S.settings.lat == null) $("tabs").querySelector('[data-tab="more"]').click(); };
function renderAll() {
  drawHeader(); drawChart(); drawTab();
  if (tab === "day") drawSummary();
  if (tab === "auto") drawSchedForm();
  if (tab === "more") {
    $("theme").value = S.settings.theme || "Nature";
    $("lat").value = S.settings.lat ?? ""; $("lon").value = S.settings.lon ?? "";
    $("locLabel").textContent = S.settings.lat == null ? "not set" : `${S.settings.lat}, ${S.settings.lon}`;
  }
}

let lastSec = 0;
function loop() {
  const now = nowS();
  if (tab === "live" && !document.hidden) drawLive();
  if (Math.floor(now) !== lastSec) {
    lastSec = Math.floor(now);
    if (applySchedules(now)) renderAll();
    drawHeader();
    if (tab === "day") drawDay();
    if (lastSec % 30 === 0) { drawChart(); if (tab === "day") drawSummary(); }
  }
  requestAnimationFrame(loop);
}
document.addEventListener("visibilitychange", () => { if (!document.hidden) { applySchedules(); renderAll(); } });
window.addEventListener("resize", renderAll);
window.addEventListener("pagehide", save);

applySchedules();
renderAll();
requestAnimationFrame(loop);
if ("serviceWorker" in navigator && location.protocol.startsWith("http")) navigator.serviceWorker.register("sw.js");
