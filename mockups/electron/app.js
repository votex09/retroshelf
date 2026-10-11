// RetroShelf main window mock-up: two lists, details, flips, keyboard and gamepad. Sample data only.
"use strict";

const $ = (id) => document.getElementById(id);
const state = { keep: [], move: [], active: "keep", sel: { keep: 0, move: 0 }, marked: new Set(), undo: [], query: "" };
let library;

// ---------- placeholder box art (the real app shows ES-DE's scraped covers) ----------
const covers = new Map();
function hash(s) { let h = 2166136261; for (const c of s) { h ^= c.charCodeAt(0); h = Math.imul(h, 16777619); } return h >>> 0; }
function cover(name, w = 170, h = 230) {
  const key = `${name}|${w}`;
  if (covers.has(key)) return covers.get(key);
  const c = document.createElement("canvas");
  const s = 2; c.width = w * s; c.height = h * s;
  const g = c.getContext("2d"); g.scale(s, s);
  const hv = hash(name), h1 = hv % 360, h2 = (h1 + 40 + (hv >> 9) % 80) % 360;
  const grad = g.createLinearGradient(0, 0, w, h);
  grad.addColorStop(0, `hsl(${h1} 65% 48%)`); grad.addColorStop(1, `hsl(${h2} 70% 20%)`);
  g.fillStyle = grad; g.fillRect(0, 0, w, h);
  g.strokeStyle = "rgba(255,255,255,.07)"; g.lineWidth = w / 14;
  for (let x = -h; x < w; x += w / 5) { g.beginPath(); g.moveTo(x, h); g.lineTo(x + h, 0); g.stroke(); }
  g.fillStyle = "rgba(0,0,0,.45)"; g.fillRect(0, 0, w, h * .11);
  g.fillStyle = "rgba(255,255,255,.85)"; g.font = `800 ${h * .06}px sans-serif`; g.textBaseline = "middle";
  g.fillText("SNES", w * .07, h * .056);
  const words = name.replace(/^(The|A) /, "").split(/[\s-]+/).filter((x) => /^[A-Za-z0-9]/.test(x));
  const ini = words.slice(0, 2).map((x) => x[0]).join("").toUpperCase();
  g.fillStyle = "rgba(255,255,255,.92)"; g.font = `800 ${w * .36}px sans-serif`; g.textAlign = "center";
  g.shadowColor = "rgba(0,0,0,.4)"; g.shadowBlur = w / 12; g.fillText(ini, w / 2, h * .58);
  const url = c.toDataURL();
  covers.set(key, url);
  return url;
}

// ---------- data ----------
const game = (r, why) => ({ id: `${r[0]}|${r[1]}`, name: r[0], region: r[1], rating: r[2], genre: r[3], size: r[4],
  year: r[5], dev: r[6], pub: r[7], why: why ?? r[8] ?? null });
const byName = (a, b) => a.name.localeCompare(b.name) || a.region.localeCompare(b.region);
const shown = (list) => state[list].filter((g) => !state.query || g.name.toLowerCase().includes(state.query));
const stars = (r) => "★★★★★".slice(0, Math.round(r)) + "☆☆☆☆☆".slice(0, 5 - Math.round(r));
const mb = (n) => (n >= 1 ? `${n.toFixed(1)} MB` : `${Math.round(n * 1024)} KB`);

// ---------- rendering ----------
function rowHTML(g, list) {
  const sub = list === "move" && g.why ? `<span class="why">${g.why}</span> · ${g.region}` : `${g.region} · ${g.genre}`;
  return `<div class="row" data-id="${g.id}"><img src="${cover(g.name, 34, 46)}" alt="">
    <div><div class="name">${g.name}</div><div class="sub">${sub}</div></div>
    <div class="right"><div class="r">★ ${g.rating.toFixed(1)}</div><div>${mb(g.size)}</div></div></div>`;
}

function render(list) {
  const el = $(list), ring = el.querySelector(".ring");
  const items = shown(list);
  el.innerHTML = items.length ? items.map((g) => rowHTML(g, list)).join("")
    : `<div class="empty">${list === "keep" ? "Nothing kept" : "Nothing to move"}</div>`;
  el.prepend(ring);
  state.sel[list] = Math.max(0, Math.min(state.sel[list], items.length - 1));
  el.querySelectorAll(".row").forEach((row, i) => {
    if (state.marked.has(row.dataset.id)) row.classList.add("marked");
    row.onclick = () => { setActive(list); select(list, i); };
    row.ondblclick = () => { select(list, i); flipAndRecord(); };
  });
}

function rows(list) { return [...$(list).querySelectorAll(".row")]; }

function placeRing(list, animate = true) {
  const el = $(list), ring = el.querySelector(".ring"), row = rows(list)[state.sel[list]];
  if (!row) { ring.style.opacity = 0; return; }
  ring.style.opacity = "";
  if (!animate) ring.style.transition = "none";
  ring.style.transform = `translateY(${row.offsetTop}px)`;
  if (!animate) { ring.offsetHeight; ring.style.transition = ""; }
  rows(list).forEach((r, i) => r.classList.toggle("selected", i === state.sel[list]));
  const top = row.offsetTop - el.scrollTop;
  if (top < 0 || top + row.offsetHeight > el.clientHeight) row.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

function rollNumber(el, to, fmt = (v) => Math.round(v)) {
  const from = Number(el.dataset.v ?? to); el.dataset.v = to;
  const t0 = performance.now(), dur = 380;
  const step = (t) => {
    const k = Math.min(1, (t - t0) / dur), e = 1 - (1 - k) ** 3;
    el.textContent = fmt(from + (to - from) * e);
    if (k < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

function updateCounts() {
  for (const list of ["keep", "move"]) {
    rollNumber($(`${list}-count`), state[list].length);
    rollNumber($(`${list}-size`), state[list].reduce((s, g) => s + g.size, 0), (v) => `${v.toFixed(1)} MB`);
  }
  const marked = state.marked.size;
  const moveMB = state.move.reduce((s, g) => s + g.size, 0);
  $("move-btn").textContent = `Move ${state.move.length} games · ${moveMB.toFixed(1)} MB`;
  updateHints(marked);
}

function updateHints(marked) {
  const a = "Mark";
  const x = marked ? `Flip ${marked} marked` : state.active === "keep" ? "Move" : "Keep";
  const h = [["a", "A", a], ["x", "X", x], ["y", "Y", "Undo"], ["bumper", "LB/RB", "Switch list"], ["b", "B", "Close"]];
  $("hints").innerHTML = h.map(([c, g, t]) => `<span class="hint"><span class="glyph ${c}">${g}</span>${t}</span>`).join("");
}

function showDetails() {
  const g = shown(state.active)[state.sel[state.active]];
  if (!g) return;
  const body = $("details-body");
  if (body.dataset.id === g.id) return;
  body.dataset.id = g.id;
  body.classList.remove("swap"); body.offsetHeight; body.classList.add("swap");
  const big = cover(g.name);
  $("cover").src = big;
  $("backdrop").style.backgroundImage = `url(${big})`;
  $("title").textContent = g.name;
  $("meta").textContent = `${g.year} · ${g.dev} · ${g.pub}`;
  $("stars").textContent = stars(g.rating);
  $("rating-text").textContent = `${g.rating.toFixed(1)} · ${300 + (hash(g.name) % 900)} votes`;
  $("genres").innerHTML = g.genre.split(", ").map((x) => `<span>${x}</span>`).join("");
  $("desc").textContent = library.descriptions[g.name] ?? library.defaultDescription;
  $("file").textContent = `${g.name} (${g.region}).zip · ${mb(g.size)}`;
}

function setActive(list) {
  state.active = list;
  document.querySelectorAll(".column").forEach((c) => c.classList.toggle("active", c.dataset.list === list));
  placeRing(list); showDetails(); updateHints(state.marked.size);
}

function select(list, i) {
  const n = shown(list).length;
  state.sel[list] = Math.max(0, Math.min(i, n - 1));
  placeRing(list); showDetails();
}

// ---------- flipping, with the row flying across ----------
function rectsOf(list) { const m = new Map(); rows(list).forEach((r) => m.set(r.dataset.id, r.getBoundingClientRect())); return m; }

function slideRest(list, before) {  // FLIP: rows that shifted glide to their new places
  rows(list).forEach((r) => {
    const old = before.get(r.dataset.id); if (!old) return;
    const dy = old.top - r.getBoundingClientRect().top;
    if (dy) r.animate([{ transform: `translateY(${dy}px)` }, { transform: "none" }], { duration: 260, easing: "cubic-bezier(.2,.8,.2,1)" });
  });
}

function flip(ids, fromList = state.active, to = fromList === "keep" ? "move" : "keep") {
  const list = shown(fromList);
  if (!ids) ids = state.marked.size ? [...state.marked] : list[state.sel[fromList]] ? [list[state.sel[fromList]].id] : [];
  const src = state[fromList].filter((g) => ids.includes(g.id));
  if (!src.length) return null;
  const beforeA = rectsOf(fromList), beforeB = rectsOf(to);
  const ghosts = src.map((g) => ({ g, r: beforeA.get(g.id) })).filter((x) => x.r);
  state[fromList] = state[fromList].filter((g) => !ids.includes(g.id));
  state[to] = [...state[to], ...src.map((g) => ({ ...g, why: to === "move" ? g.why ?? "flipped by hand" : g.why }))].sort(byName);
  state.marked.clear();
  render("keep"); render("move");
  slideRest(fromList, beforeA); slideRest(to, beforeB);
  for (const { g, r } of ghosts) flyGhost(g, r, to);
  placeRing(state.active); showDetails(); updateCounts();
  return { ids: src.map((g) => g.id), from: fromList, to, names: src.map((g) => g.name) };
}

function flipAndRecord() {
  const done = flip();
  if (!done) return;
  state.undo.push(done);
  toast(done.names.length === 1 ? `${done.to === "move" ? "Moving" : "Keeping"} ${done.names[0]}` : `${done.names.length} games flipped`);
}

function flyGhost(g, r, to) {
  const target = rows(to).find((x) => x.dataset.id === g.id);
  if (!target) return;
  target.scrollIntoView({ block: "nearest" });
  const t = target.getBoundingClientRect();
  target.style.opacity = 0;
  const ghost = document.createElement("div");
  ghost.className = "row ghost-row";
  ghost.innerHTML = rowHTML(g, to).replace(/^<div class="row"[^>]*>|<\/div>$/g, "");
  Object.assign(ghost.style, { left: `${r.left}px`, top: `${r.top}px`, width: `${r.width}px` });
  document.body.appendChild(ghost);
  const dx = t.left - r.left, dy = t.top - r.top;
  ghost.animate([
    { transform: "translate(0,0) scale(1)", opacity: 1 },
    { transform: `translate(${dx / 2}px, ${dy / 2 - 30}px) scale(1.04)`, opacity: 1, offset: .5 },
    { transform: `translate(${dx}px, ${dy}px) scale(1)`, opacity: .9 },
  ], { duration: 420, easing: "cubic-bezier(.3,.7,.2,1)" }).onfinish = () => {
    ghost.remove(); target.style.opacity = ""; target.classList.add("glow");
  };
}

function undo() {
  const u = state.undo.pop(); if (!u) return;
  flip(u.ids, u.to, u.from);
  toast("Undone");
}

let toastTimer;
function toast(text) {
  const t = $("toast");
  t.innerHTML = `${text}<kbd>Y</kbd> Undo`;
  t.classList.add("show");
  clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove("show"), 2200);
}

function pulseRing() { const r = $(state.active).querySelector(".ring"); r.classList.remove("pulse"); r.offsetHeight; r.classList.add("pulse"); }

// ---------- input: keyboard, and gamepads mapped onto the same keys ----------
function handle(key, e = {}) {
  const list = state.active, n = shown(list).length, page = Math.floor($(list).clientHeight / 56);
  switch (key) {
    case "ArrowDown": select(list, state.sel[list] + 1); break;
    case "ArrowUp": select(list, state.sel[list] - 1); break;
    case "PageDown": select(list, state.sel[list] + page); break;
    case "PageUp": select(list, state.sel[list] - page); break;
    case "Home": select(list, 0); break;
    case "End": select(list, n - 1); break;
    case "ArrowRight": case "Delete": if (list === "keep") { pulseRing(); flipAndRecord(); } break;
    case "ArrowLeft": if (list === "move") { pulseRing(); flipAndRecord(); } break;
    case "Enter": pulseRing(); flipAndRecord(); break;
    case " ": {
      const g = shown(list)[state.sel[list]]; if (!g) break;
      state.marked.has(g.id) ? state.marked.delete(g.id) : state.marked.add(g.id);
      render(list); placeRing(list, false); pulseRing(); select(list, state.sel[list] + 1); updateHints(state.marked.size);
      break;
    }
    case "Tab": setActive(list === "keep" ? "move" : "keep"); break;
    case "z": if (e.ctrlKey) undo(); else return false; break;
    case "Backspace": undo(); break;
    default: return false;
  }
  return true;
}

document.addEventListener("keydown", (e) => {
  if (e.target === $("search")) {
    if (e.key === "Escape" || e.key === "ArrowDown" || e.key === "Enter") { e.target.blur(); e.preventDefault(); }
    return;
  }
  if (e.key === "/" || (e.ctrlKey && e.key === "f")) { $("search").focus(); e.preventDefault(); return; }
  if (handle(e.key, e)) e.preventDefault();
});

const PAD = { 12: "ArrowUp", 13: "ArrowDown", 14: "ArrowLeft", 15: "ArrowRight", 0: " ", 2: "Enter", 3: "Backspace",
  4: "Tab", 5: "Tab", 6: "PageUp", 7: "PageDown" };
const held = {};
function pollPads(now) {
  for (const pad of navigator.getGamepads()) {
    if (!pad) continue;
    const pressed = new Set(Object.keys(PAD).filter((b) => pad.buttons[b]?.pressed).map(Number));
    if (pad.axes[1] < -.55) pressed.add(12); if (pad.axes[1] > .55) pressed.add(13);
    if (pad.axes[0] < -.55) pressed.add(14); if (pad.axes[0] > .55) pressed.add(15);
    for (const b of pressed) {
      if (!(b in held)) { held[b] = now + 400; handle(PAD[b]); }
      else if (b >= 12 && now >= held[b]) { held[b] = now + 80; handle(PAD[b]); }
    }
    for (const b of Object.keys(held)) if (!pressed.has(Number(b))) delete held[b];
  }
  requestAnimationFrame(pollPads);
}

// ---------- start ----------
window.backend.library().then((lib) => {
  library = lib;
  state.keep = lib.keeping.map((r) => game(r, null)).sort(byName);
  state.move = lib.moving.map((r) => game(r)).sort(byName);
  state.sel.keep = state.keep.findIndex((g) => g.name === "Chrono Trigger");
  $("system-tag").textContent = lib.system;
  $("system-name").textContent = lib.systemName;
  $("free").textContent = `${lib.freeGB.toFixed(1)} GB free`;
  $("roms").textContent = lib.romsPath;
  $("chips").innerHTML = lib.filters.map((f) => `<button class="chip${f.on ? " on" : ""}">${f.label}</button>`).join("");
  $("chips").querySelectorAll(".chip").forEach((c) => (c.onclick = () => c.classList.toggle("on")));
  $("search").oninput = (e) => { state.query = e.target.value.toLowerCase(); render("keep"); render("move"); placeRing(state.active, false); showDetails(); };
  render("keep"); render("move");
  setActive("keep"); placeRing("keep", false);
  updateCounts();
  requestAnimationFrame(() => ($("space-ring").style.strokeDashoffset = 94.25 * (lib.freeGB / lib.totalGB)));
  requestAnimationFrame(pollPads);
});
