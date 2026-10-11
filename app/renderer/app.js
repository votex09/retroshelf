// RetroShelf's main window: one system's games in Keeping and Moving, the filters that sort them, a game's details,
// and Move. The deciding, scanning and moving happen in the Python helper (app/helper/helper.py); this draws it.
"use strict";

const $ = (id) => document.getElementById(id);
const rs = window.retroshelf;
const LISTS = ["keep", "move"];

const S = {
  overview: null,   // startup(): roms folder, its systems, the holding folder, whether LaunchBox is downloaded
  sys: null,        // open_system(): the open system
  games: [], byKey: new Map(),
  st: null,         // the filters, as the helper saves them per system (flips: games flipped by hand)
  tabs: [0, 0, 0, 0],
  query: "",
  active: "keep",
  marked: new Set(),
  undo: [],
  pad: false,       // a gamepad was used: show its buttons in the hints
  opts: { play_videos: true, gamepad: true, animations: true, show_details: true },  // ☰ → Settings (settings.js)
};

// ---------- small things ----------
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
function human(n) {
  const u = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return `${i ? n.toFixed(n < 10 ? 1 : 0) : n} ${u[i]}`;
}
const stars = (r) => "★★★★★".slice(0, Math.round(r)) + "☆☆☆☆☆".slice(0, 5 - Math.round(r));
const titleOf = (key) => key.replace(/\s*[([][^)\]]*[)\]]/g, "").trim() || key;
const plural = (n, one, many = `${one}s`) => `${n.toLocaleString()} ${n === 1 ? one : many}`;
const KEEPERS = new Set(["played", "hidden in ES-DE", "manual"]);

async function call(method, params) {
  try {
    return await rs.call(method, params);
  } catch (e) {  // "Error invoking remote method 'helper:call': Error: <the helper's message>"
    throw new Error(String(e.message || e).replace(/^Error invoking remote method '[^']+': (\w*Error: )?/, ""));
  }
}

let toastTimer;
function toast(text, { undo = false, error = false } = {}) {
  const t = $("toast");
  t.innerHTML = esc(text) + (undo ? `<kbd>${S.pad ? "Y" : "Ctrl+Z"}</kbd> Undo` : "");
  t.classList.toggle("error", error);
  t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), error ? 5000 : 2400);
}
const oops = (e) => { console.error(e); toast(e.message || String(e), { error: true }); };

// A box over the window. buttons: [[label, fn, primary?]]; none: it can't be closed (busy).
function overlay(html, buttons = []) {
  $("overlay-box").innerHTML = html + (buttons.length ? `<div class="btns"></div>` : "");
  const btns = $("overlay-box").querySelector(".btns");
  buttons.forEach(([label, fn, primary]) => {
    const b = document.createElement("button");
    b.className = primary ? "primary" : "ghost";
    b.textContent = label;
    b.onclick = fn;
    btns.appendChild(b);
  });
  $("overlay").hidden = false;
  btns?.querySelector(".primary")?.focus();
}
const closeOverlay = () => ($("overlay").hidden = true);
const busy = (text) => overlay(`<div class="spinner"></div><h2>${esc(text)}</h2>`);

function rollNumber(el, to, fmt = (v) => Math.round(v).toLocaleString()) {
  const from = Number(el.dataset.v ?? to);
  el.dataset.v = to;
  const t0 = performance.now(), dur = 380;
  const step = (t) => {
    const k = Math.min(1, (t - t0) / dur), e = 1 - (1 - k) ** 3;
    el.textContent = fmt(from + (to - from) * e);
    if (k < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

// Pictures that fail to load fall back to stand-in art.
document.addEventListener("error", (e) => {
  const img = e.target;
  if (img.tagName === "IMG" && img.dataset.title != null && !img.dataset.failed) {
    img.dataset.failed = 1;
    img.src = img.closest(".row") ? Art.cover(img.dataset.title, S.sys?.system || "", 34, 46) : Art.cover(img.dataset.title, S.sys?.system || "");
  }
}, true);

// ---------- rows ----------
function rowHTML(g) {
  const sys = S.sys.system;
  const src = g.thumb ? Art.media(g.thumb) : Art.cover(g.title, sys, 34, 46);
  const tags = g.regions.filter((r) => r !== "(none)").join(", ");
  const bits = [];
  const why = g.why || (g.hidden ? "hidden in ES-DE" : "");
  if (why) bits.push(`<span class="why${g.move ? "" : " keeper"}">${esc(why === "manual" ? "by hand" : why)}</span>`);
  if (tags) bits.push(esc(tags));
  if (!g.move && g.genres.length) bits.push(esc(g.genres[0]));
  const r = g.rating != null ? `<div class="r">★ ${g.rating.toFixed(1)}</div>` : "";
  return `<img src="${src}" data-title="${esc(g.title)}" width="34" height="46" alt="">
    <div class="txt"><div class="name">${esc(g.key)}</div><div class="sub">${bits.join(" · ") || "&nbsp;"}</div></div>
    <div class="right">${r}<div>${human(g.size)}</div></div>`;
}

const lists = {};
for (const name of LISTS) {
  lists[name] = new GameList($(name), {
    rowHTML,
    onClick: (i) => { setActive(name); select(i); },
    onOpen: (i) => { setActive(name); select(i); flip(); },
    empty: () => (!S.sys ? "" : S.query ? "No matches" : name === "keep" ? "Nothing kept" :
      "Nothing to move yet.\nPick some filters above, or flip games across with → ."),
  });
  lists[name].marked = S.marked;
}
const L = () => lists[S.active];

// ---------- the lists ----------
function shown(g) {
  const q = S.query.toLowerCase();
  return !q || g.key.toLowerCase().includes(q) || g.label.toLowerCase().includes(q) || g.title.toLowerCase().includes(q);
}

function rebuild({ slide = true } = {}) {
  for (const name of LISTS) {
    const list = lists[name];
    const before = list.set(S.games.filter((g) => g.move === (name === "move") && shown(g)), list.current?.key);
    if (slide) list.slide(before);
  }
  counts();
  showDetails();
}

function counts() {
  for (const name of LISTS) {
    const games = S.games.filter((g) => g.move === (name === "move"));
    rollNumber($(`${name}-count`), games.length);
    rollNumber($(`${name}-size`), games.reduce((s, g) => s + g.size, 0), human);
  }
  const moving = S.games.filter((g) => g.move);
  const btn = $("move-btn");
  btn.disabled = !moving.length;
  btn.textContent = moving.length ? `Move ${plural(moving.length, "game")} · ${human(moving.reduce((s, g) => s + g.size, 0))}` : "Move files";
  $("hide-btn").disabled = !moving.length;
  const flips = S.st ? Object.keys(S.st.flips).length : 0;
  $("reset-flips").hidden = !flips;
  $("reset-flips").textContent = `Reset ${plural(flips, "flip")}`;
  hints();
}

function setActive(name) {
  if (S.active !== name) { S.marked.clear(); for (const l of LISTS) lists[l].refreshMarks(); }
  S.active = name;
  document.querySelectorAll(".column").forEach((c) => c.classList.toggle("active", c.dataset.list === name));
  L().placeRing(false);
  showDetails();
  hints();
}

function select(i, smooth = true) {
  L().select(i, smooth);
  showDetails();
  rememberCursor();
}

let cursorTimer;
function rememberCursor() {
  clearTimeout(cursorTimer);
  cursorTimer = setTimeout(() => { const g = L().current; if (g && S.sys) call("remember_cursor", { key: g.key }).catch(() => {}); }, 800);
}

// ---------- deciding (in the helper) ----------
let decideTimer = null, decideSeq = 0, deciding = null;
function scheduleDecide(delay = 250) {
  clearTimeout(decideTimer);
  decideTimer = setTimeout(() => { decideTimer = null; runDecide(); }, delay);
}
function runDecide() {
  const seq = ++decideSeq;
  deciding = call("decide", { state: S.st, cursor_key: L().current?.key ?? null })
    .then((dec) => { if (seq === decideSeq) applyDecision(dec); })
    .catch(oops);
  return deciding;
}
async function flushDecide() {  // before Move: the helper must have the latest filters
  if (decideTimer) { clearTimeout(decideTimer); decideTimer = null; await runDecide(); } else if (deciding) await deciding;
}

function applyDecision(dec, slide = true) {
  const moving = new Set(dec.move);
  let changed = false;
  for (const g of S.games) {
    const move = moving.has(g.key), why = dec.why[g.key] || "";
    if (g.move !== move || g.why !== why) { g.move = move; g.why = why; changed = true; }
  }
  S.tabs = dec.tabs;
  tabs();
  if (changed) rebuild({ slide });
}

// ---------- flipping a game across, by hand ----------
function flip(keys) {
  const list = L();
  if (!keys) {
    const marked = list.items.filter((g) => S.marked.has(g.key)).map((g) => g.key);
    keys = marked.length ? marked : list.current ? [list.current.key] : [];
  }
  if (!keys.length) return;
  const prev = {};
  for (const k of keys) {
    const g = S.byKey.get(k);
    prev[k] = S.st.flips[k];
    if (k in S.st.flips) { delete S.st.flips[k]; g.why = ""; } else { S.st.flips[k] = !g.move; g.why = "manual"; }
    g.move = !g.move;
  }
  S.undo.push({ keys, prev });
  if (S.undo.length > 200) S.undo.shift();
  S.marked.clear();
  animateFlip(keys);
  const to = S.byKey.get(keys[0]).move;
  toast(keys.length === 1 ? `${to ? "Moving" : "Keeping"} ${keys[0]}` : `${keys.length} games ${to ? "to Moving" : "to Keeping"}`, { undo: true });
  scheduleDecide(0);
}

function undo() {
  const u = S.undo.pop();
  if (!u) { toast("Nothing to undo"); return; }
  for (const k of u.keys) {
    const g = S.byKey.get(k);
    if (u.prev[k] === undefined) delete S.st.flips[k]; else S.st.flips[k] = u.prev[k];
    g.move = !g.move;
  }
  animateFlip(u.keys);
  toast("Undone");
  scheduleDecide(0);
}

// Rows that changed list fly across; the rest of both lists glide into place.
function animateFlip(keys) {
  const from = {};
  for (const name of LISTS) {
    lists[name].items.forEach((g, i) => { if (keys.includes(g.key) && lists[name].rows.has(g.key)) from[g.key] = { name, rect: lists[name].rectOf(i) }; });
  }
  rebuild();
  const fly = keys.filter((k) => from[k]).slice(0, 8);
  for (const k of fly) {
    const g = S.byKey.get(k), to = lists[g.move ? "move" : "keep"], i = to.indexOf(k);
    if (i < 0) continue;
    if (fly.length === 1) to.reveal(i, false);
    to.draw();
    const target = to.rows.get(k);
    if (!target) continue;
    const a = from[k].rect, b = to.rectOf(i);
    const ghost = document.createElement("div");
    ghost.className = "row ghost-row";
    ghost.innerHTML = rowHTML(g);
    Object.assign(ghost.style, { left: `${a.left}px`, top: `${a.top}px`, width: `${a.width}px`, right: "auto" });
    document.body.appendChild(ghost);
    target.style.opacity = 0;
    const dx = b.left - a.left, dy = b.top - a.top;
    ghost.animate([
      { transform: "translate(0,0) scale(1)", opacity: 1 },
      { transform: `translate(${dx / 2}px, ${dy / 2 - 30}px) scale(1.04)`, opacity: 1, offset: 0.5 },
      { transform: `translate(${dx}px, ${dy}px) scale(1)`, opacity: 0.9 },
    ], { duration: 420, easing: "cubic-bezier(.3,.7,.2,1)" }).onfinish = () => {
      ghost.remove();
      target.style.opacity = "";
      target.classList.remove("glow"); void target.offsetHeight; target.classList.add("glow");
    };
  }
}

function mark() {
  const g = L().current;
  if (!g) return;
  S.marked.has(g.key) ? S.marked.delete(g.key) : S.marked.add(g.key);
  L().refreshMarks();
  L().pulse();
  select(L().sel + 1);
  hints();
}

// ---------- details ----------
const det = { key: null, seq: 0, timer: null, videoTimer: null, data: null, image: 0 };

function showDetails() {
  const g = L().current;
  if (!g) {
    det.key = null; det.seq++;
    clearTimeout(det.timer);
    stopVideo();
    $("details-body").innerHTML = S.sys ? `<div class="details-empty">No game picked</div>` : "";
    $("backdrop").style.backgroundImage = "";
    return;
  }
  if (g.key === det.key) { stateLine(g); return; }
  det.key = g.key; det.data = null; det.image = 0;
  renderDetails(g, true);
  clearTimeout(det.timer);
  const seq = ++det.seq;
  det.timer = setTimeout(() => {
    call("details", { key: g.key }).then((d) => {
      if (seq !== det.seq) return;
      det.data = d;
      renderDetails(g, false);
      if (d.video && S.opts.play_videos) det.videoTimer = setTimeout(() => seq === det.seq && playVideo(true), 1500);
    }).catch(oops);
  }, 90);
}

function stopVideo() {
  clearTimeout(det.videoTimer);
  const v = document.querySelector("#details-body video");
  if (v) { v.pause(); v.removeAttribute("src"); v.load(); }
}

function renderDetails(g, fresh) {
  stopVideo();
  const d = det.data, body = $("details-body"), sys = S.sys.system;
  const images = d ? d.images : g.thumb ? [{ type: "covers", path: g.thumb }] : [];
  const meta = d ? [d.year, d.developer, d.publisher !== d.developer && d.publisher].filter(Boolean) : [];
  if (d?.players) meta.push(`${d.players} players`);
  const rating = g.rating != null
    ? `<span class="stars">${stars(g.rating)}</span>${g.rating.toFixed(1)} · ${plural(g.votes, "vote")}`
    : `<span>Not rated</span>`;
  const facts = d ? [
    ["File", d.file], ["Size", human(d.size)],
    ["Regions", g.regions.join(", ")],
    ["LaunchBox", d.match],
    ...(d.installed.length ? [["Installed data", d.installed.join("\n")]] : []),
  ] : [];
  const lbCard = S.overview && !S.overview.launchbox ? `<div class="lb-card">
      <p>Ratings, genres and descriptions come from LaunchBox's games database (about 110 MB, downloaded once).</p>
      <button class="ghost small" id="lb-download">Download LaunchBox data</button>
      <div class="progress" id="lb-progress"></div></div>` : "";
  body.innerHTML = `
    <div class="media" id="media"></div>
    <div class="thumbs" id="thumbs"></div>
    <h1>${esc(d?.title || g.title)}</h1>
    <div class="meta">${esc(meta.join(" · ") || (d?.console ?? S.sys.fullname))}</div>
    <div class="rating">${rating}</div>
    <div class="genres">${g.genres.map((x) => `<span>${esc(x)}</span>`).join("")}</div>
    <p class="state-line" id="state-line"></p>
    ${lbCard}
    ${d?.description ? `<div class="desc">${esc(d.description)}</div>` : ""}
    <div class="facts">${facts.map(([k, v]) => `<span>${esc(k)}</span><span>${esc(v)}</span>`).join("")}</div>`;
  stateLine(g);
  showImage(g, images, det.image);
  const thumbs = $("thumbs");
  if (images.length > 1 || d?.video) {
    images.forEach((im, i) => {
      const b = document.createElement("button");
      b.title = im.type;
      b.innerHTML = `<img src="${Art.media(im.path)}" data-title="${esc(g.title)}" alt="">`;
      b.onclick = () => { stopVideo(); det.image = i; showImage(g, images, i); };
      thumbs.appendChild(b);
    });
    if (d?.video) {
      const b = document.createElement("button");
      b.className = "vid"; b.title = "Video"; b.textContent = "▶";
      b.onclick = () => playVideo(false);
      thumbs.appendChild(b);
    }
    markThumb(det.image);
  }
  const bg = images[0] ? Art.media(images[0].path) : Art.cover(g.title, sys);
  $("backdrop").style.backgroundImage = `url("${bg}")`;
  $("lb-download")?.addEventListener("click", downloadLaunchbox);
  if (fresh) { body.classList.remove("swap"); void body.offsetHeight; body.classList.add("swap"); body.scrollTop = 0; }
}

function markThumb(i) { [...$("thumbs").children].forEach((b, j) => b.classList.toggle("on", j === i)); }

function showImage(g, images, i) {
  const media = $("media");
  const im = images[i];
  media.innerHTML = im ? `<img src="${Art.media(im.path)}" data-title="${esc(g.title)}" alt="">`
    : `<img class="placeholder" src="${Art.cover(g.title, S.sys.system)}" alt="">`;
  if ($("thumbs").children.length) markThumb(i);
}

function playVideo(quiet) {
  const d = det.data;
  if (!d?.video) return;
  clearTimeout(det.videoTimer);
  const media = $("media");
  media.innerHTML = `<video src="${Art.media(d.video)}" autoplay loop playsinline ${quiet ? "muted" : "controls"}></video>`
    + (quiet ? `<button class="unmute">🔇 Sound</button>` : "");
  media.querySelector(".unmute")?.addEventListener("click", (e) => {
    const v = media.querySelector("video");
    v.muted = false; v.controls = true; e.target.remove();
  });
  markThumb($("thumbs").children.length - 1);
}

function stateLine(g) {
  const el = $("state-line");
  if (!el) return;
  const why = g.why === "manual" ? "flipped by hand" : g.why || (g.hidden ? "hidden in ES-DE" : "");
  el.innerHTML = g.move ? `<b class="move">Moving</b>${why ? ` · ${esc(why)}` : ""}`
    : `<b class="keep">Keeping</b>${why ? ` · ${esc(why === "flipped by hand" ? why : `protected: ${why}`)}` : ""}`;
}

async function downloadLaunchbox() {
  const btn = $("lb-download");
  if (btn) btn.disabled = true;
  if (!btn) busy("Downloading LaunchBox data…");
  try {
    await call("download_launchbox");
    closeOverlay();
    S.overview.launchbox = true;
    if (S.sys) await openSystem(S.sys.system);
    toast("LaunchBox data downloaded");
  } catch (e) {
    closeOverlay();
    oops(e);
    if ($("lb-download")) $("lb-download").disabled = false;
  }
}

// ---------- filters ----------
function tabs() {
  document.querySelectorAll(".tab").forEach((t, i) => {
    t.querySelector(".n").textContent = S.tabs[i] || "";
    t.classList.toggle("on", S.tabs[i] > 0);
  });
}

function changed() { scheduleDecide(); }

function openPanel(name) {
  const pop = $("filters"), same = !pop.hidden && pop.dataset.panel === name;
  closePopovers();
  if (same) return;
  pop.dataset.panel = name;
  pop.hidden = false;
  document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("show", p.dataset.panel === name));
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("open", t.dataset.tab === name));
}

function closePopovers() {
  $("filters").hidden = true;
  $("systems-pop").hidden = true;
  $("menu").hidden = true;
  $("ctx").hidden = true;
  document.querySelectorAll(".tab").forEach((t) => t.classList.remove("open"));
}

function fillFilters() {
  const sys = S.sys, st = S.st;
  $("preset-list").innerHTML = "";
  for (const p of sys.presets) {
    const label = document.createElement("label");
    label.className = "check";
    label.innerHTML = `<input type="checkbox"> <span>${esc(p.label)}</span>`;
    const box = label.querySelector("input");
    box.checked = st.presets.includes(p.key);
    box.onchange = () => {
      st.presets = box.checked ? [...st.presets, p.key] : st.presets.filter((x) => x !== p.key);
      changed();
    };
    $("preset-list").appendChild(label);
  }
  $("use-rating").checked = st.use_rating;
  $("rating-max").value = st.rating_max;
  $("min-votes").value = st.min_votes;
  $("use-unrated").checked = st.use_unrated;
  $("protect-played").checked = st.protect_played;
  $("played-n").textContent = sys.played ? `(${sys.played.toLocaleString()} played)` : "";
  $("match-info").textContent = !sys.platform ? "LaunchBox has no platform for this system, so there are no ratings or genres."
    : !S.overview.launchbox ? "Download LaunchBox data (in the details panel) for ratings and genres."
      : `LaunchBox knows ${sys.matched.toLocaleString()} of ${plural(sys.games.length, "game")} here; ${sys.rated.toLocaleString()} have ratings.`;

  chips($("genre-chips"), sys.genres, "genres", "No genres: LaunchBox didn't match any games here.");
  chips($("region-chips"), sys.regions, "regions", "No region tags in these file names.");
  $("region-modes").innerHTML = "";
  for (const m of sys.region_modes) {
    const b = document.createElement("button");
    b.textContent = m;
    b.classList.toggle("on", st.region_mode === m);
    b.onclick = () => {
      st.region_mode = m;
      [...$("region-modes").children].forEach((x) => x.classList.toggle("on", x === b));
      regionHelp();
      changed();
    };
    $("region-modes").appendChild(b);
  }
  regionHelp();
  $("patterns").value = st.patterns;
  $("icase").checked = st.icase;
  $("filter-info").textContent = sys.warning;
}

function regionHelp() {
  $("region-help").textContent = S.st.region_mode === S.sys.region_modes[0]
    ? "Games whose regions are all picked move. Region dupes keeps another region's copy first."
    : "Games with none of the picked regions move. Region dupes keeps the picked regions' copy first.";
}

function chips(el, counts, field, none) {
  el.innerHTML = counts.length ? "" : `<span class="muted">${esc(none)}</span>`;
  for (const [name, n] of counts) {
    const c = document.createElement("button");
    c.className = "chip";
    c.innerHTML = `${esc(name)}<small>${n.toLocaleString()}</small>`;
    c.classList.toggle("on", S.st[field].includes(name));
    c.onclick = () => {
      const on = !S.st[field].includes(name);
      S.st[field] = on ? [...S.st[field], name] : S.st[field].filter((x) => x !== name);
      c.classList.toggle("on", on);
      changed();
    };
    el.appendChild(c);
  }
}

function wireFilters() {
  document.querySelectorAll(".tab").forEach((t) => (t.onclick = (e) => { e.stopPropagation(); openPanel(t.dataset.tab); }));
  const bind = (id, field, prop = "checked") => ($(id).oninput = () => { if (S.st) { S.st[field] = $(id)[prop]; changed(); } });
  bind("use-rating", "use_rating");
  bind("use-unrated", "use_unrated");
  bind("protect-played", "protect_played");
  bind("icase", "icase");
  bind("rating-max", "rating_max", "value");
  bind("min-votes", "min_votes", "value");
  bind("patterns", "patterns", "value");
  $("rating-max").addEventListener("input", () => { if (S.st && !S.st.use_rating) { S.st.use_rating = $("use-rating").checked = true; } });
  document.addEventListener("mousedown", (e) => {
    if (!e.target.closest(".popover, .tab, #system-btn, #menu-btn")) closePopovers();
  });
}

// ---------- systems and the ROMs folder ----------
function showOverview() {
  const ov = S.overview;
  $("roms-path").textContent = ov.roms || "No ROMs folder yet";
  $("roms-path").title = ov.roms;
  const list = $("systems-list");
  list.innerHTML = "";
  const systems = ov.systems.filter((s) => s.games > 0 || s.code === S.sys?.system);
  if (!systems.length) list.innerHTML = `<p class="muted" style="padding:10px">${ov.roms ? "No games in this folder yet." : "Pick your ROMs folder below."}</p>`;
  for (const s of systems) {
    const b = document.createElement("button");
    b.classList.toggle("cur", s.code === S.sys?.system);
    b.innerHTML = `<span class="code">${esc(s.code)}</span><span class="nm">${esc(s.name === "?" ? "" : s.name)}</span><span class="n">${s.games.toLocaleString()}</span>`;
    b.onclick = () => { closePopovers(); openSystem(s.code).catch(oops); };
    list.appendChild(b);
  }
}

function toggleSystems() {
  const pop = $("systems-pop"), open = pop.hidden;
  closePopovers();
  if (open) { showOverview(); pop.hidden = false; pop.querySelector(".cur")?.scrollIntoView({ block: "center" }); }
}

async function pickRoms() {
  const folder = await rs.pickFolder(S.overview?.roms);
  if (!folder) return false;
  S.overview = await call("set_roms", { path: folder });
  showOverview();
  return true;
}

function welcome() {
  overlay(`<h2>Where are your ROMs?</h2>
    <p>RetroShelf couldn't find RetroDECK's or ES-DE's ROMs folder. Pick the folder that has one folder per system
    in it (snes, psx, …). Don't have RetroDECK or ES-DE yet? RetroShelf can set it up.</p>`, [
    [`Set up ${SETUP_NAME}…`, () => { closeOverlay(); openSetup(); }],
    ["Pick folder…", async () => {
      try {
        if (await pickRoms()) { closeOverlay(); toggleSystems(); }
      } catch (e) { oops(e); }
    }, true]]);
}

async function openSystem(code) {
  $("system-tag").textContent = code;
  $("system-name").textContent = "Loading…";
  for (const name of LISTS) $(name).querySelector(".empty").textContent = "Loading…";
  const res = await call("open_system", { system: code });
  loadSystem(res);
}

// keep: the game to stay on (after a rescan), else the one saved for this system.
function loadSystem(res, keep) {
  S.sys = res;
  S.games = res.games.map((g) => ({ ...g, title: titleOf(g.key) }));
  S.byKey = new Map(S.games.map((g) => [g.key, g]));
  S.st = res.state;
  S.undo = [];
  S.marked.clear();
  S.query = $("search").value = "";
  det.key = null;
  $("system-tag").textContent = res.system;
  $("system-name").textContent = res.fullname;
  document.title = `RetroShelf · ${res.fullname}`;
  if (res.disk) {
    $("space").hidden = false;
    $("free").textContent = human(res.disk.free);
    requestAnimationFrame(() => ($("space-ring").style.strokeDashoffset = 94.25 * (res.disk.free / res.disk.total)));
  }
  fillFilters();
  for (const name of LISTS) lists[name].sel = 0;
  applyDecision(res.decision, false);
  rebuild({ slide: false });
  const g = S.byKey.get(keep) || (res.cursor && S.byKey.get(res.cursor));
  setActive(g?.move ? "move" : "keep");
  if (g) { const i = L().indexOf(g.key); if (i >= 0) { L().sel = i; L().draw(); L().reveal(i, false); } }
  showDetails();
}

// ---------- Move ----------
async function doMove() {
  try {
    await flushDecide();
    const dest = $("dest").value;
    const plan = await call("move_plan", { dest });
    if (!plan.games) return;
    const detail = [
      `They go to ${plan.dest_dir}, where you can move them back or delete them for good.`,
      plan.installed ? `${plural(plan.installed, "game has", "games have")} installed data that moves with them.` : "",
      plan.same_drive ? "" : "That folder is on another drive, so the files are copied across, which can take a while.",
    ].filter(Boolean).join("\n\n");
    const ok = await rs.confirm({ title: "Move games", ok: "Move",
      message: `Move ${plural(plan.games, "game")} (${plural(plan.files, "file")}, ${human(plan.size)}) out of ${S.sys.fullname}?`, detail });
    if (!ok) return;
    busy(`Moving ${plural(plan.games, "game")}…`);
    const res = await call("move", { dest });
    loadSystem(res);
    const m = res.moved;
    if (m.failed.length) {
      overlay(`<h2>Moved ${plural(m.files, "file")}; ${m.failed.length} couldn't be</h2>
        <ul>${m.failed.map((f) => `<li>${esc(f)}</li>`).join("")}</ul>`, [["Close", closeOverlay, true]]);
    } else {
      closeOverlay();
      toast(`Moved ${plural(m.files, "file")} to ${m.dest}`);
    }
  } catch (e) {
    closeOverlay();
    oops(e);
  }
}

// ---------- long jobs in the helper, with progress and Stop ----------
const jobListeners = new Map();
let jobCount = 0;
// -> { done: promise of the answer, stop() }; onProgress({message, done, total}) as it goes
function runJob(method, params, onProgress) {
  const job = `${method}-${Date.now()}-${++jobCount}`;
  jobListeners.set(job, onProgress);
  const done = call(method, { ...params, job }).finally(() => jobListeners.delete(job));
  return { done, stop: () => call("cancel", { job }) };
}

// ---------- the ☰ menu ----------
// Tool windows add themselves: registerTool({ cmd, label, sub, system: needs an open system, anywhere: needs no ROMs
// folder either, open })
const TOOLS = [];
function registerTool(t) { TOOLS.push(t); }

function openMenu() {
  const m = $("menu");
  $("menu-tools").innerHTML = TOOLS.map((t) => `<button data-cmd="${t.cmd}">${esc(t.label)}${t.sub ? `<small>${esc(t.sub)}</small>` : ""}</button>`).join("");
  for (const b of m.querySelectorAll("button[data-cmd]")) {
    b.disabled = ["priority", "export", "rescan", "review", "collection"].includes(b.dataset.cmd) && !S.sys ||
      b.dataset.cmd === "export" && !S.games.some((g) => g.move) || ["holding", "moves", "change-holding"].includes(b.dataset.cmd) && !S.overview?.roms;
  }
  for (const t of TOOLS) m.querySelector(`[data-cmd="${t.cmd}"]`).disabled = !t.anywhere && (t.system && !S.sys || !S.overview?.roms);
  m.querySelector('[data-cmd="launchbox"]').firstChild.textContent = S.overview?.launchbox ? "Update LaunchBox data" : "Download LaunchBox data";
  m.hidden = false;
}

function menuCommand(cmd) {
  const run = {
    holding: openHolding, moves: openMoves, priority: openPriority, export: exportMoves, rescan,
    review: openReview, collection: () => openCollection(),
    "change-holding": changeHolding, launchbox: downloadLaunchbox,
    "change-roms": () => pickRoms().then((ok) => ok && toggleSystems()),
    settings: () => openSettings(), keys: () => openKeys(),
  }[cmd] || TOOLS.find((t) => t.cmd === cmd)?.open;
  Promise.resolve().then(run).catch(oops);
}

async function rescan() {
  if (!S.sys) return;
  const keep = L().current?.key;
  await flushDecide();
  loadSystem(await call("rescan"), keep);
  toast("Rescanned");
}

async function exportMoves() {
  await flushDecide();
  const path = await rs.saveFile({ title: "Export move list", name: `${S.sys.system}_move.txt` });
  if (!path) return;
  const r = await call("export_moves", { path });
  toast(`Saved ${plural(r.games, "game")} to ${path}`);
}

async function changeHolding() {
  const folder = await rs.pickFolder(S.overview.holding, "Holding folder for moved games");
  if (!folder) return;
  S.overview = await call("set_holding", { path: folder });
  toast(`Moved games go to ${S.overview.holding}`);
}

function resetFlips() {
  const n = Object.keys(S.st.flips).length;
  S.st.flips = {};
  S.undo = [];
  toast(`Reset ${plural(n, "flip")}`);
  scheduleDecide(0);
}

// ---------- right-click on a game ----------
function rowMenu(name, e) {
  const row = e.target.closest(".row");
  if (!row) return;
  e.preventDefault();
  const list = lists[name], i = Number(row.dataset.i), g = list.items[i];
  setActive(name);
  const marked = list.items.filter((x) => S.marked.has(x.key));
  const games = S.marked.has(g.key) ? marked : [g];
  if (!S.marked.has(g.key)) select(i, false);
  const keys = games.map((x) => x.key);
  const canMatch = games.length === 1 && S.sys.platform && S.overview.launchbox;
  const items = [
    [games.length > 1 ? `Hide ${games.length} games in ES-DE` : "Hide in ES-DE", games.some((x) => !x.hidden), () => hideGames(keys, true)],
    ["Show in ES-DE again", games.some((x) => x.hidden), () => hideGames(keys, false)],
    null,
    ["Set LaunchBox match…", canMatch, () => openMatch(g.key)],
    ["Back to automatic match", games.length === 1 && g.manual_match, () => setMatch(g.key, null, true)],
    null,
    [games.length > 1 ? `Add ${games.length} games to an ES-DE collection…` : "Add to an ES-DE collection…", true, () => openCollection(keys)],
    ["Review from here…", true, () => openReview()],
  ];
  const ctx = $("ctx");
  ctx.innerHTML = "";
  for (const it of items) {
    if (!it) { ctx.appendChild(document.createElement("hr")); continue; }
    const b = document.createElement("button");
    b.textContent = it[0];
    b.disabled = !it[1];
    b.onclick = () => { closePopovers(); Promise.resolve().then(it[2]).catch(oops); };
    ctx.appendChild(b);
  }
  ctx.hidden = false;
  const w = ctx.offsetWidth, h = ctx.offsetHeight;
  ctx.style.left = `${Math.min(e.clientX, innerWidth - w - 8)}px`;
  ctx.style.top = `${Math.min(e.clientY, innerHeight - h - 8)}px`;
}

async function hideGames(keys, hide) {
  if (!keys.length) return;
  await flushDecide();
  const check = await call("hide_check", { keys, hide });
  if (!check.games) return;
  if (check.es_de_running) {
    overlay(`<h2>Close ES-DE first</h2><p>RetroDECK / ES-DE rewrites its gamelists when it quits, which would undo this.</p>`,
      [["OK", closeOverlay, true]]);
    return;
  }
  if (hide) {
    const ok = await rs.confirm({ title: "Hide in ES-DE", ok: "Hide",
      message: `Hide ${plural(check.games, "game")} in ES-DE?`,
      detail: "The files stay where they are; ES-DE just leaves them out of its menus. Hidden games stay in Keeping." +
        (check.shows_hidden ? "\n\nES-DE is set to show hidden games, so that's turned off too (ES-DE: Other settings → Show hidden games)." : "") });
    if (!ok) return;
  }
  const keep = L().current?.key;
  const res = await call("hide", { keys, hide });
  loadSystem(res, keep);
  toast(hide ? `Hid ${plural(res.hidden, "game")} in ES-DE. Right-click to show ${res.hidden === 1 ? "it" : "them"} again.`
    : `${plural(res.hidden, "game")} shown in ES-DE again`);
}

async function setMatch(key, gid, clear = false) {
  await flushDecide();
  loadSystem(await call("set_match", { key, gid, clear }), key);
  toast(clear ? "Back to the automatic match" : gid ? "LaunchBox match saved" : "Marked as not in LaunchBox");
}

// ---------- hints, keyboard and gamepads ----------
function hints() {
  document.body.classList.toggle("pad", S.pad);
  const marked = L().items.filter((g) => S.marked.has(g.key)).length;
  const verb = S.active === "keep" ? "Move" : "Keep";
  const act = marked ? `${verb} ${marked} marked` : verb;
  const h = S.pad
    ? [["a", "A", "Mark"], ["x", "X", act], ["y", "Y", "Undo"], ["bumper", "LB/RB", "Switch list"], ["b", "B", "Close"]]
    : [["key", S.active === "keep" ? "→" : "←", act], ["key", "Space", "Mark"], ["key", "Tab", "Switch list"],
      ["key", "Ctrl+Z", "Undo"], ["key", "/", "Search"]];
  $("hints").innerHTML = h.map(([c, g, t]) => `<span class="hint"><span class="glyph ${c}">${esc(g)}</span>${esc(t)}</span>`).join("");
}

function handle(key, e = {}) {
  if (key === "Escape") {
    if (!$("sheet-wrap").hidden) closeSheet();
    else if (!$("filters").hidden || !$("systems-pop").hidden || !$("menu").hidden || !$("ctx").hidden) closePopovers();
    else if (S.query) { $("search").value = ""; S.query = ""; rebuild({ slide: false }); }
    return true;
  }
  if (!$("sheet-wrap").hidden) return sheetKeys ? sheetKeys(key, e) : false;
  if (key === "F5") { rescan(); return true; }
  if (key === "r" && e.ctrlKey) { openReview(); return true; }
  if (!S.sys) return false;
  const list = L();
  switch (key) {
    case "ArrowDown": select(list.sel + 1); break;
    case "ArrowUp": select(list.sel - 1); break;
    case "PageDown": select(list.sel + list.page); break;
    case "PageUp": select(list.sel - list.page); break;
    case "Home": select(0, false); break;
    case "End": select(list.items.length - 1, false); break;
    case "ArrowRight": case "Delete": if (S.active === "keep") { list.pulse(); flip(); } break;
    case "ArrowLeft": if (S.active === "move") { list.pulse(); flip(); } break;
    case "Enter": list.pulse(); flip(); break;
    case " ": mark(); break;
    case "Tab": setActive(S.active === "keep" ? "move" : "keep"); break;
    case "Backspace": undo(); break;
    case "z": if (e.ctrlKey) undo(); else return false; break;
    case "s": toggleSystems(); break;
    default: return false;
  }
  return true;
}

document.addEventListener("keydown", (e) => {
  if (!$("overlay").hidden) return;
  if (e.target === $("search")) {
    if (e.key === "Escape" || e.key === "ArrowDown" || e.key === "Enter") { e.target.blur(); e.preventDefault(); }
    return;
  }
  if (e.target.closest("input, textarea, select")) {
    if (e.key === "Escape") { e.target.blur(); if ($("sheet-wrap").hidden) closePopovers(); else closeSheet(); }
    return;
  }
  if (!$("sheet-wrap").hidden) {
    if (e.key === "Escape") closeSheet();
    else if (sheetKeys && sheetKeys(e.key, e)) e.preventDefault();
    return;
  }
  if (e.key === "/" || (e.ctrlKey && e.key === "f")) { $("search").focus(); $("search").select(); e.preventDefault(); return; }
  if (S.pad) { S.pad = false; hints(); }
  if (handle(e.key, e)) e.preventDefault();
});

// Gamepads (Steam Deck, Xbox and the like) press the same keys: d-pad, A mark, X flip, Y undo, LB/RB switch list,
// LT/RT page, B close.
const BUTTONS = { 12: "ArrowUp", 13: "ArrowDown", 14: "ArrowLeft", 15: "ArrowRight", 0: " ", 2: "Enter", 3: "Backspace",
  4: "Tab", 5: "Tab", 6: "PageUp", 7: "PageDown", 1: "Escape" };
const held = {};
function pollPads(now) {
  if (!S.opts.gamepad) { requestAnimationFrame(pollPads); return; }
  for (const pad of navigator.getGamepads ? navigator.getGamepads() : []) {
    if (!pad) continue;
    const pressed = new Set(Object.keys(BUTTONS).filter((b) => pad.buttons[b]?.pressed).map(Number));
    if (pad.axes[1] < -0.55) pressed.add(12);
    if (pad.axes[1] > 0.55) pressed.add(13);
    for (const b of pressed) {
      if (!(b in held)) {
        held[b] = now + 400;
        if (!S.pad) { S.pad = true; hints(); }
        if ($("overlay").hidden && document.activeElement?.tagName !== "TEXTAREA") handle(BUTTONS[b]);
      } else if (b >= 12 && b <= 13 && now >= held[b]) { held[b] = now + 80; handle(BUTTONS[b]); }
    }
    for (const b of Object.keys(held)) if (!pressed.has(Number(b))) delete held[b];
  }
  requestAnimationFrame(pollPads);
}

// ---------- start ----------
async function start() {
  rs.version().then((v) => ($("version").textContent = `v${v} preview`));
  rs.onHelperExit((info) => overlay(`<h2>RetroShelf's helper stopped</h2>
    <p>Nothing can load or change until RetroShelf is restarted.</p><p class="error">${esc(info.error || info.stderr || "")}</p>`));
  rs.onHelperEvent((name, data) => {
    if (name === "progress") { jobListeners.get(data.job)?.(data); return; }
    if (name !== "launchbox") return;
    if ($("lb-progress")) $("lb-progress").textContent = data.message;
    const h2 = document.querySelector("#overlay-box h2");
    if (h2 && !$("overlay").hidden) h2.textContent = data.message;
  });
  $("system-btn").onclick = (e) => { e.stopPropagation(); toggleSystems(); };
  $("change-roms").onclick = () => { closePopovers(); pickRoms().then((ok) => ok && toggleSystems()).catch(oops); };
  $("search").oninput = (e) => {
    S.query = e.target.value;
    rebuild({ slide: false });
    const other = S.active === "keep" ? "move" : "keep";
    if (!L().items.length && lists[other].items.length) setActive(other);  // go where the matches are
  };
  $("move-btn").onclick = doMove;
  $("hide-btn").onclick = () => hideGames(S.games.filter((g) => g.move).map((g) => g.key), true);
  $("reset-flips").onclick = resetFlips;
  $("menu-btn").onclick = (e) => { e.stopPropagation(); const open = $("menu").hidden; closePopovers(); if (open) openMenu(); };
  $("menu").addEventListener("click", (e) => { const b = e.target.closest("button[data-cmd]"); if (b) { closePopovers(); menuCommand(b.dataset.cmd); } });
  for (const name of LISTS) $(name).addEventListener("contextmenu", (e) => rowMenu(name, e));
  wireFilters();
  hints();
  requestAnimationFrame(pollPads);

  const summary = { roms: "", systems: 0, system: "", games: 0 };
  try {
    const hello = await call("hello");
    Object.assign(summary, { python: hello.python, frozen: hello.frozen });
    S.overview = await call("startup");
    applyOptions(await call("settings"));
    showOverview();
    summary.roms = S.overview.roms;
    summary.systems = S.overview.systems.filter((s) => s.games > 0).length;
    const last = S.overview.systems.find((s) => s.code === S.overview.system && s.games > 0);
    if (!S.overview.roms) S.overview.setup_offered ? welcome() : openSetup();
    else if (last) await openSystem(last.code);
    else toggleSystems();
    summary.system = S.sys?.system || "";
    summary.games = S.games.length;
    summary.moving = S.games.filter((g) => g.move).length;
  } catch (e) {
    oops(e);
    summary.error = e.message;
  }
  rs.ready(summary);
}

document.addEventListener("DOMContentLoaded", start);  // once sheets.js, tools.js … have loaded too
