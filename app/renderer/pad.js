// Getting around everything that isn't the game lists, with a gamepad or the keyboard: the header, the filter tabs,
// the footer, the details panel, the ☰ menu, popovers, sheets and boxes. (Uses app.js, sheets.js and settings.js.)
//   A cursor (an accent ring, .pad-cur) sits on one control; the d-pad or the arrow keys move it to the nearest
// control that way, A / Enter / Space presses it and B / Esc goes back: out of a text box, out of a submenu, closes
// the popover or sheet, then back to the lists. In the lists themselves the keys are app.js's handle(). Everywhere in
// the main window L1 / R1 (F6) go round its parts (header, filter tabs, Keeping, Moving, details, footer), View (/)
// searches, Menu (F10) opens ☰, and R3, the Menu key or Shift+F10 opens the game's menu. Every button has a key
// that does the same (settings.js's CONTROLS). A in a text box opens an
// on-screen keyboard (osk below). The hints along the bottom always list what the buttons do right there (uiHints),
// and a ring flies to wherever the cursor lands (glide).
"use strict";

const NAV = { ArrowUp: "up", ArrowDown: "down", ArrowLeft: "left", ArrowRight: "right" };
const FOCUSABLE = "button, input:not([type=hidden]), select, textarea, a[href], .trow[data-id], .trow[data-key], " +
  ".trow[data-code], .trow[data-all], .list";
const TEXTY = "input:not([type=checkbox]):not([type=radio]):not([type=number]), textarea";
const P = { cur: null, layer: null, saved: new Map(), sig: null, index: -1 };  // saved: the last control per layer

// ---------- layers: what's on top takes the keys ----------
function topLayer() {
  return picker.shown() ? $("picker") : topLayerBelow();
}

function topLayerBelow() {  // (what's under a list being picked from)
  if (!$("overlay").hidden) return $("overlay-box");
  if (!$("sheet-wrap").hidden) return $("sheet");
  for (const id of ["ctx", "menu", "systems-pop", "filters"]) if (!$(id).hidden) return $(id);
  return document.body;
}

function shownEl(el) {
  if (el.disabled || !el.getClientRects().length || el.closest("[hidden]")) return false;
  return getComputedStyle(el).visibility !== "hidden";
}

function focusables(layer = topLayer()) {
  const main = layer === document.body;
  return [...layer.querySelectorAll(FOCUSABLE)].filter((el) => shownEl(el)
    && !(el.tagName === "INPUT" && el.closest(".trow"))  // (a table row's tick box: the row is what's pressed)
    && !(main && (el.closest(".popover, #sheet-wrap, #overlay") || el.parentElement.closest(".list")))
    && !el.closest("#osk"));
}

const LAYERS = "#picker, #overlay-box, #sheet, #ctx, #menu, #systems-pop, #filters";
const layerOf = (el) => el.closest(LAYERS) || document.body;

// Where a control is, for the purposes of moving: a tick box is its whole label.
const box = (el) => (el.matches("input[type=checkbox], input[type=radio]") && el.closest("label") || el);

function rectOf(el) {
  if (el?.classList?.contains("list")) {  // a game list: its selected row
    const list = lists[el.id], row = list.current && list.rows.get(list.current.key);
    if (row) return row.getBoundingClientRect();
  }
  return box(el).getBoundingClientRect();
}

// The nearest control from `from` (an element, or a rect) in a direction. Left and right stay on the same line
// unless `loose` (leaving the game lists for the details panel).
function nearest(from, dir, els, loose = false) {
  const a = from.getBoundingClientRect ? rectOf(from) : from;
  const ax = (a.left + a.right) / 2, ay = (a.top + a.bottom) / 2;
  let best = null, score = Infinity;
  for (const el of els) {
    if (el === from) continue;
    const b = rectOf(el), bx = (b.left + b.right) / 2, by = (b.top + b.bottom) / 2;
    let gap, cross;
    if (dir === "down" || dir === "up") {
      if (dir === "down" ? by <= ay + 1 || b.bottom <= a.bottom : by >= ay - 1 || b.top >= a.top) continue;
      gap = Math.max(0, dir === "down" ? b.top - a.bottom : a.top - b.bottom);
      cross = Math.max(0, b.left - a.right, a.left - b.right);
    } else {
      if (dir === "right" ? bx <= ax + 1 || b.right <= a.right : bx >= ax - 1 || b.left >= a.left) continue;
      gap = Math.max(0, dir === "right" ? b.left - a.right : a.left - b.right);
      cross = Math.max(0, b.top - a.bottom, a.top - b.bottom);
      if (cross > 0 && !loose) continue;
    }
    const s = gap + cross * 3 + Math.abs(dir === "up" || dir === "down" ? bx - ax : by - ay) * 0.05;
    if (s < score) { score = s; best = el; }
  }
  return best;
}

// ---------- showing where the cursor went ----------
// A ring flies from where the cursor was to where it lands, then pulses there, so a jump (L1 / R1, a sheet opening,
// back to the lists) is easy to follow. Not with ☰ → Settings → Animations off or the system's reduced motion.
const glideOff = matchMedia("(prefers-reduced-motion: reduce)");
let glideEl = null;
function glide(from, to) {
  if (!to || !(S.pad || document.body.classList.contains("kbd")) || !S.opts.animations || glideOff.matches) return;
  if (!to.width || !to.height || to.bottom < 0 || to.top > innerHeight) return;
  const same = from && Math.abs(from.left - to.left) < 2 && Math.abs(from.top - to.top) < 2 && Math.abs(from.width - to.width) < 2;
  if (!glideEl) {
    glideEl = document.createElement("div");
    glideEl.className = "focus-glide";
    document.body.appendChild(glideEl);
  }
  const at = (r, extra = {}) => ({ left: `${r.left - 4}px`, top: `${r.top - 4}px`, width: `${r.width + 8}px`,
    height: `${r.height + 8}px`, ...extra });
  const start = from && from.width && !same ? from : null;
  glideEl.getAnimations().forEach((a) => a.cancel());
  const travel = start ? Math.min(260, 120 + Math.hypot(to.left - start.left, to.top - start.top) / 6) : 0;
  glideEl.animate([
    ...(start ? [at(start, { opacity: 0.9, offset: 0 })] : [at(to, { opacity: 0, transform: "scale(1.15)", offset: 0 })]),
    at(to, { opacity: 1, transform: "scale(1)", offset: (travel / (travel + 380)) || 0.3 }),
    at(to, { opacity: 0.8, transform: "scale(1.04)", offset: Math.min(0.9, (travel + 140) / (travel + 380)) }),
    at(to, { opacity: 0, transform: "scale(1)", offset: 1 }),
  ], { duration: travel + 380, easing: "cubic-bezier(.2,.8,.2,1)" });
}
const cursorRect = () => (P.cur ? rectOf(P.cur) : topLayer() === document.body && S.sys ? rectOf($(S.active)) : null);

// ---------- the cursor ----------
function sig(el) {  // enough to find a control again after its sheet redraws
  const holder = el.closest("[id]");
  const data = Object.entries(el.dataset || {})
    .map(([k, v]) => `[data-${k.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`)}="${CSS.escape(v)}"]`).join("");
  return el.id ? `#${CSS.escape(el.id)}` : data && holder ? `#${CSS.escape(holder.id)} ${el.tagName.toLowerCase()}${data}` : null;
}

function setCursor(el, { focus = true } = {}) {
  const from = el !== P.cur ? cursorRect() : null;
  if (P.cur && P.cur !== el) box(P.cur).classList.remove("pad-cur");
  P.cur = el;
  P.sig = el ? sig(el) : null;
  if (el && !el.classList.contains("list")) P.saved.set(layerOf(el), el);
  P.index = el ? focusables(P.layer || topLayer()).indexOf(el) : -1;
  if (!el) {
    P.saved.delete(document.body);
    if (document.activeElement && document.activeElement !== document.body) document.activeElement.blur();
    hints();
    return;
  }
  box(el).classList.add("pad-cur");
  if (el.classList.contains("list")) { box(el).classList.remove("pad-cur"); enterList(el.id); return; }
  if (focus && !el.matches(TEXTY)) {
    if (el.tabIndex < 0 && !el.matches("button, input, select, a[href]")) el.tabIndex = -1;
    if (document.activeElement !== el) el.focus({ preventScroll: true });
  } else if (document.activeElement && document.activeElement !== el && document.activeElement !== document.body) {
    document.activeElement.blur();
  }
  box(el).scrollIntoView({ block: "nearest", inline: "nearest" });
  if (from) glide(from, rectOf(el));
  hints();
  if (pickRow(el)) { el.click(); syncCursor(); }  // (it may redraw: the cursor finds the row again)
}

// In a sheet with its own keys (its table has a selection: NoPayStation, the stores, Storage), the row the cursor is on
// is the picked one, so moving the cursor down a table picks as it goes.
const pickRow = (el) => el.matches(".trow[data-key], .trow[data-code]") && !el.classList.contains("on") && sheetKeys
  && layerOf(el) === $("sheet") && (S.pad || document.body.classList.contains("kbd"));

function enterList(name) {
  const from = P.cur || name !== S.active ? cursorRect() : null;
  if (P.cur) box(P.cur).classList.remove("pad-cur");
  P.saved.delete(document.body);
  P.cur = null; P.sig = null;
  if (document.activeElement && document.activeElement !== document.body) document.activeElement.blur();
  if (S.sys) setActive(name);
  if (from && S.sys) glide(from, rectOf($(name)));
  hints();
}

// The control to start on in a layer that just opened (or redrew under the cursor).
function landing(layer) {
  const els = focusables(layer);
  if (!els.length) return null;
  if (P.sig) {  // the same control, redrawn
    const again = layer.querySelector(P.sig);
    if (again && els.includes(again)) return again;
  }
  const saved = P.saved.get(layer);
  if (saved?.isConnected && els.includes(saved)) return saved;
  if (layer === $("overlay-box")) return layer.querySelector(".btns .primary") || els[0];
  return els.find((el) => el.matches(".cur, .trow.on")) || els.find((el) => !el.matches(".menu-back")) || els[0];
}

// Called on every key or button and every frame: keep the cursor in the top layer.
function syncCursor(force = false) {
  const layer = topLayer();
  if (ownsAll()) {  // (Review: every button has its own job, nothing to move between)
    if (P.cur) box(P.cur).classList.remove("pad-cur");
    if (P.layer !== layer || P.cur) { P.layer = layer; P.cur = null; P.sig = null; hints(); }
    return;
  }
  if (layer !== P.layer) {
    const from = P.layer;
    P.layer = layer;
    P.sig = null;
    if (layer === document.body) {  // back to the main window: where it was, or the lists
      const saved = P.saved.get(document.body);
      P.saved.delete(document.body);
      if (from && saved?.isConnected && shownEl(saved) && (S.pad || document.body.classList.contains("kbd"))) setCursor(saved);
      else { if (P.cur) box(P.cur).classList.remove("pad-cur"); P.cur = null; hints(); }
      return;
    }
    if (P.cur) box(P.cur).classList.remove("pad-cur");
    P.cur = null;
    const focused = document.activeElement;
    if (focused !== document.body && layer.contains(focused) && focused.matches(FOCUSABLE)) {  // it focused its own box
      setCursor(focused, { focus: false });
      return;
    }
    if (!(layer === $("sheet") && sheetKeys) || force) {
      const el = (S.pad || document.body.classList.contains("kbd")) && landing(layer);
      if (el) setCursor(el); else hints();
    } else hints();
    return;
  }
  const using = S.pad || document.body.classList.contains("kbd");
  if (!P.cur && using && layer !== document.body && !(layer === $("sheet") && sheetKeys)) {  // a sheet that filled in late
    const el = landing(layer);
    if (el) setCursor(el);
    return;
  }
  if (P.cur && (!P.cur.isConnected || !shownEl(P.cur))) {  // redrawn or hidden under the cursor
    const el = P.cur.isConnected ? null : landing(layer);
    if (el) setCursor(el);
    else if (layer === document.body) enterList(S.active);
    else {
      const els = focusables(layer);
      setCursor(els[Math.min(Math.max(P.index, 0), els.length - 1)] || null);
    }
  }
}

function move(dir) {
  syncCursor(true);
  const layer = topLayer(), els = focusables(layer);
  let from = P.cur;
  if (!from) {
    if (layer !== document.body) { setCursor(landing(layer)); return; }
    from = $(S.active);  // from the lists
  }
  let to = nearest(from, dir, els.filter((el) => el !== from), from.classList.contains("list") || from.matches(".trow"));
  if (!to && (dir === "up" || dir === "down") && ["menu", "ctx", "systems-pop", "picker"].includes(layer.id)) {  // a menu goes round
    to = dir === "down" ? els[0] : els[els.length - 1];
  }
  if (!to && dir === "down" && layer !== document.body && !from.closest(".sheet-foot, .btns")) {  // the bottom: its buttons
    const foot = els.filter((el) => el.closest(".sheet-foot, .btns"));
    to = foot.find((el) => el.matches(".primary")) || foot[foot.length - 1];
  }
  if (to) setCursor(to);
}

// L2 / R2 (PgUp / PgDn) on a table row: a screenful of rows up or down; Home / End: the first or last row.
function pageRows(step) {
  const table = P.cur.closest(".table, [id]");
  const rows = focusables().filter((el) => el.matches(".trow") && table.contains(el));
  const per = Math.max(1, Math.floor(table.clientHeight / Math.max(1, P.cur.offsetHeight)) - 1);
  const i = Math.max(0, Math.min(rows.length - 1, rows.indexOf(P.cur) + (Number.isFinite(step) ? step * per : step > 0 ? rows.length : -rows.length)));
  if (rows[i]) setCursor(rows[i]);
}
const onRow = () => Boolean(P.cur?.matches(".trow") && topLayer() !== document.body);

// A sheet moved its own selection (its arrow keys): a cursor on its table goes along.
function followSelection(table) {
  const on = table?.querySelector(".trow.on");
  if (on) setCursor(on); else syncCursor();
}
const tableOf = () => (P.cur?.matches(".trow") ? P.cur.closest("[id]") : null);

// ---------- pressing ----------
function press(el = P.cur) {
  if (!el) return;
  if (el.matches(TEXTY) || el.matches("input[type=number]")) {
    el.focus();
    if (S.pad) osk.open(el);
    return;
  }
  if (el.tagName === "SELECT") { picker.open(el); return; }
  el.click();
  setTimeout(() => syncCursor(), 0);
}

// B / Esc: back one step.
function back() {
  const layer = topLayer();
  if (layer === $("picker")) { picker.close(); return; }
  if (layer === $("overlay-box")) {  // a question: cancel it; a message with one button: that button
    const btns = layer.querySelectorAll(".btns button");
    if (overlayCancel) overlayCancel(); else if (btns.length === 1) btns[0].click();
    return;
  }
  if (layer === $("sheet")) { closeSheet(); return; }
  if (layer === $("menu") && $("menu").dataset.group) {
    const group = $("menu").dataset.group;
    openMenu();
    setCursor($("menu").querySelector(`[data-group="${group}"]`));
    return;
  }
  if (layer !== document.body) { closePopovers(); return; }
  if (P.cur) { enterList(S.active); return; }
  handle("Escape");
}

function gameMenu() {
  if (!S.sys || !L().current) return;
  const row = L().rows.get(L().current.key);
  const r = row ? row.getBoundingClientRect() : $(S.active).getBoundingClientRect();
  rowMenu(S.active, { target: row || $(S.active), clientX: r.left + 40, clientY: r.top + r.height / 2, preventDefault() {} });
}

function startMenu() {
  if (!$("menu").hidden) { closePopovers(); return; }
  closePopovers();
  if (!P.cur) P.saved.delete(document.body);
  openMenu();
}

// L1 / R1 (F6 / Shift+F6): the next or previous part of the main window, round and round: the header, the filter
// tabs, the game lists (one stop: the d-pad ◀ ▶, the right stick or Tab go between Keeping and Moving), the details
// panel and the footer. Each part remembers where the cursor was in it; parts with nothing to press right now (a footer whose
// buttons are off) are skipped.
const AREAS = [".topbar", "#filterbar", "lists", "#details", "footer"];
const areaSaved = new Map();
const isList = (area) => area === "lists";
const areaOf = (el) => (el ? AREAS.findIndex((a) => !isList(a) && el.closest(a)) : AREAS.indexOf("lists"));
function nextZone(step) {
  closePopovers();
  const els = focusables(document.body);
  const at = areaOf(P.cur);
  if (at >= 0 && P.cur) areaSaved.set(AREAS[at], P.cur);
  for (let i = 1; i <= AREAS.length; i++) {
    const area = AREAS[((at < 0 ? 0 : at) + step * i + AREAS.length * 2) % AREAS.length];
    if (isList(area)) {
      if (S.sys) { enterList(S.active); return; }
      continue;
    }
    const inside = els.filter((x) => x.closest(area));
    if (!inside.length) continue;
    const saved = areaSaved.get(area);
    setCursor(inside.includes(saved) ? saved : inside.find((x) => x.matches(".primary")) || inside[0]);
    return;
  }
}

// L1 / R1 (F6) in a window or box: its parts in turn (the filters along the top, a table, the panel beside it, the
// buttons along the bottom …), each remembering where the cursor was in it.
const SHEET_AREAS = ".sheet-head, .sheet-tools, .table, .nps-side, .store-details, .store-status, .sheet-foot, .form, .prio, "
  + ".browse-places, .browse-list, .btns";
const sheetAreaSaved = new WeakMap();
function sheetAreas(layer = topLayer()) {
  const groups = [];
  for (const el of focusables(layer)) {
    const area = el.closest(SHEET_AREAS) || [...layer.children].find((c) => c.contains(el)) || layer;
    let g = groups.find((x) => x.area === area);
    if (!g) groups.push(g = { area, els: [] });
    g.els.push(el);
  }
  return groups;
}
function nextArea(step) {
  const groups = sheetAreas();
  if (groups.length < 2) return;
  const at = P.cur ? groups.findIndex((g) => g.els.includes(P.cur)) : -1;
  if (at >= 0) sheetAreaSaved.set(groups[at].area, P.cur);
  const g = groups[at < 0 ? (step > 0 ? 0 : groups.length - 1) : (at + step + groups.length) % groups.length];
  const saved = sheetAreaSaved.get(g.area);
  setCursor(g.els.includes(saved) ? saved : g.els.find((el) => el.matches(".trow.on, .cur")) || g.els.find((el) => el.matches(".primary"))
    || g.els.find((el) => el.matches(".trow:not([data-all])")) || g.els[0]);
}
const inBox = (layer = topLayer()) => layer === $("sheet") || layer === $("overlay-box");
const ownsAll = () => Boolean(sheetKeys?.all) && topLayer() === $("sheet");

// A window that takes every button itself (Review): what each one is, as keys for its handler. The d-pad ▲ ▼, the
// right stick and L2 / R2 scroll it; B closes.
const OWN_KEYS = { 0: " ", 2: "Enter", 3: "Backspace", 14: "ArrowLeft", 15: "ArrowRight" };
function ownButton(b) {
  if (b === 1) { back(); return; }
  if (b === 9) { startMenu(); return; }
  if (b === 12 || b === 13) { padScroll(b === 13 ? 60 : -60); return; }
  if (b === 6 || b === 7) { padScroll(b === 7 ? 1 : -1, true); return; }
  if (OWN_KEYS[b]) sheetKeys(OWN_KEYS[b], {});
}

// View: search, with the on-screen keyboard.
function openSearch() {
  closePopovers();
  setCursor($("search"), { focus: false });
  press($("search"));
}

// ---------- the keyboard ----------
// The mouse or the keyboard after the gamepad: the hints go back to keys (a real move, not a nudge or a redraw).
let mouseTravel = 0;
function leavePad() {
  if (!S.pad) return;
  S.pad = false;
  mouseTravel = 0;
  hints();
}
document.addEventListener("mousemove", (e) => {
  if (!S.pad) return;
  mouseTravel += Math.abs(e.movementX) + Math.abs(e.movementY);
  if (mouseTravel > 24) leavePad();
}, { passive: true });
document.addEventListener("wheel", leavePad, { passive: true });

document.addEventListener("mousedown", (e) => {
  leavePad();
  document.body.classList.remove("kbd");
  if (picker.shown() && !e.target.closest("#picker")) picker.close();
  if (P.cur) { box(P.cur).classList.remove("pad-cur"); if (topLayer() === document.body) P.cur = null; }
}, true);

document.addEventListener("focusout", () => setTimeout(hints, 0));  // (out of a text box: the hints stop saying typing)
document.addEventListener("focusin", (e) => {  // Tab, a click, a sheet focusing its own box: the cursor follows
  const el = e.target;
  hints();
  if (el === P.cur || !el.matches?.(FOCUSABLE) || el.closest(".list, #osk")) return;
  const top = topLayer();
  if (top !== document.body && layerOf(el) !== top) {  // Tab out of a sheet or box: back into it
    el.blur();
    const inside = landing(top);
    if (inside) setCursor(inside);
    return;
  }
  const from = cursorRect();
  if (P.cur) box(P.cur).classList.remove("pad-cur");
  P.cur = el; P.sig = sig(el);
  P.saved.set(layerOf(el), el);
  if (document.body.classList.contains("kbd") || S.pad) { box(el).classList.add("pad-cur"); if (from) glide(from, rectOf(el)); }
});

document.addEventListener("keydown", (e) => {
  document.body.classList.add("kbd");
  if (osk.shown()) osk.close();
  leavePad();
  const t = e.target;
  if (t === $("search")) {
    if (e.key === "Escape" || e.key === "ArrowDown" || e.key === "Enter") { t.blur(); setCursor(null); e.preventDefault(); }
    return;
  }
  if (t.matches?.(TEXTY) || t.matches?.("input[type=number]")) {  // typing: Esc stops (the cursor stays on the box), ↑ ↓ leave it
    const leave = (e.key === "ArrowUp" || e.key === "ArrowDown") && t.matches(TEXTY) && t.tagName !== "TEXTAREA";  // (↑ ↓ step a number)
    if (e.key === "Escape" || leave) {
      e.preventDefault(); e.stopPropagation();
      t.blur();
      setCursor(t, { focus: false });
      if (leave) move(NAV[e.key]);
    }
    return;
  }
  syncCursor();
  const layer = topLayer(), dir = NAV[e.key];
  if (e.key === "Escape") { e.preventDefault(); back(); return; }
  if (e.key === "F10" && !e.shiftKey) { e.preventDefault(); startMenu(); return; }  // (Menu on a pad)
  if (ownsAll()) {
    e.preventDefault();
    if (e.key === "PageUp" || e.key === "PageDown") padScroll(e.key === "PageDown" ? 1 : -1, true);
    else if (e.key === "ArrowUp" || e.key === "ArrowDown") padScroll(e.key === "ArrowDown" ? 60 : -60);
    else if (!sheetKeys(e.key, e)) return;
    return;
  }
  if (inBox(layer) && e.key === "F6") { e.preventDefault(); nextArea(e.shiftKey ? -1 : 1); return; }
  const navKey = dir || e.key === "Enter" || e.key === " ";
  const table = tableOf();
  if (onRow() && ["PageUp", "PageDown", "Home", "End"].includes(e.key)) {
    e.preventDefault();
    pageRows({ PageUp: -1, PageDown: 1, Home: -Infinity, End: Infinity }[e.key]);
    return;
  }
  if (layer === $("sheet") && sheetKeys && (!navKey || !P.cur || (P.cur.matches(".trow") && !dir)) && sheetKeys(e.key, e)) {
    e.preventDefault();
    followSelection(table);
    return;
  }

  if (layer === document.body && !P.cur) {  // the lists
    if (e.key === "F6") { e.preventDefault(); nextZone(e.shiftKey ? -1 : 1); return; }
    if (e.key === "ContextMenu" || (e.key === "F10" && e.shiftKey)) { e.preventDefault(); gameMenu(); return; }
    if (e.key === "/" || (e.ctrlKey && e.key === "f")) { $("search").focus(); $("search").select(); e.preventDefault(); return; }
    if (e.key === "ArrowUp" && !e.repeat && S.sys && L().sel === 0 && !e.shiftKey) { e.preventDefault(); move("up"); return; }
    if (e.key === "ArrowDown" && !e.repeat && S.sys && L().sel >= L().items.length - 1) { e.preventDefault(); move("down"); return; }
    if (e.key === "ArrowRight" && !e.repeat && S.active === "move") { e.preventDefault(); move("right"); return; }
    if ((e.key === "ArrowLeft" || e.key === "ArrowRight") && S.sys) {  // ← → go between Keeping and Moving, as on a pad
      e.preventDefault();
      if (!e.repeat && (e.key === "ArrowLeft") === (S.active === "move")) enterList(e.key === "ArrowLeft" ? "keep" : "move");
      return;
    }
    if (handle(e.key, e)) e.preventDefault();
    return;
  }
  // a control has the cursor
  if (layer === document.body && (e.key === "F5" || (e.ctrlKey && (e.key === "r" || e.key === "i")))) {
    if (handle(e.key, e)) e.preventDefault();
    return;
  }
  if (layer === document.body && e.key === "F6") { e.preventDefault(); nextZone(e.shiftKey ? -1 : 1); return; }
  if (layer === document.body && e.key === "/") { e.preventDefault(); openSearch(); return; }
  if ((layer === $("sheet") || layer === document.body) && (e.key === "PageUp" || e.key === "PageDown")) {  // (L2 / R2)
    e.preventDefault();
    padScroll(e.key === "PageDown" ? 1 : -1, true);
    return;
  }
  if (dir) {
    e.preventDefault();
    move(dir);
    return;
  }
  if ((e.key === "Enter" || e.key === " ") && P.cur) {
    e.preventDefault();
    press();
  }
}, true);

// ---------- gamepads ----------
// Standard mapping: 0 A, 1 B, 2 X, 3 Y, 4 LB, 5 RB, 6 LT, 7 RT, 8 View / Select, 9 Start / Menu, 10 L3, 11 R3, 12-15 d-pad.
const DIRS = { 12: "up", 13: "down", 14: "left", 15: "right" };
const LIST_KEYS = { 12: "ArrowUp", 13: "ArrowDown", 14: "ArrowLeft", 15: "ArrowRight", 0: " ", 2: "Enter", 3: "Backspace",
  4: "Tab", 5: "Tab", 6: "PageUp", 7: "PageDown" };
const REPEATS = new Set([12, 13, 14, 15, 6, 7]);
const STICK_LEFT = 101, STICK_RIGHT = 102;  // (not real buttons: the right stick pushed left / right)
const held = {};

function padButton(b, repeat) {
  if (osk.shown()) { osk.pad(b); return; }
  const typing = document.activeElement;
  if (typing?.matches?.(`${TEXTY}, input[type=number]`)) {  // a text box someone's typing in with a keyboard
    if (b === 0) { osk.open(typing); return; }
    if (b !== 1 && !DIRS[b]) return;
    typing.blur();
    if (typing === $("search")) { setCursor(null); return; }
    setCursor(typing, { focus: false });
    if (b === 1) return;
  }
  syncCursor(!repeat);
  const layer = topLayer(), dir = DIRS[b];
  if (ownsAll()) { ownButton(b); return; }
  if (b === 9) { startMenu(); return; }
  if ((b === 4 || b === 5) && inBox(layer)) { nextArea(b === 5 ? 1 : -1); return; }
  if (layer === document.body && !P.cur) {  // the lists
    if (b === 1) { back(); return; }
    if (b === 8) { openSearch(); return; }
    if (b === 11) { gameMenu(); return; }
    if (b === 4 || b === 5) { nextZone(b === 5 ? 1 : -1); return; }
    if (b === STICK_LEFT || b === STICK_RIGHT) { if (S.sys) enterList(b === STICK_LEFT ? "keep" : "move"); return; }
    // ◀ ▶ go between Keeping and Moving (X flips the game); ▶ from Moving leaves for what's right of it
    if (S.sys && ((b === 14 && S.active === "move") || (b === 15 && S.active === "keep"))) {
      if (!repeat) enterList(b === 14 ? "keep" : "move");
      return;
    }
    if (S.sys && b === 14) return;
    const last = S.sys && L().sel >= L().items.length - 1;
    const leave = (b === 12 && S.sys && L().sel === 0) || (b === 13 && last) || (b === 15 && S.active === "move") || (!S.sys && dir);
    if (!repeat && leave) {
      move(dir);
      return;
    }
    if (LIST_KEYS[b]) handle(LIST_KEYS[b]);
    return;
  }
  if ((b === 6 || b === 7) && onRow()) { pageRows(b === 7 ? 1 : -1); return; }
  if (layer === $("sheet") && sheetKeys && (!P.cur || (P.cur.matches(".trow") && !dir)) && b !== 1) {
    const key = { ...LIST_KEYS, 1: "Escape" }[b];
    const table = tableOf();
    if (key && sheetKeys(key, {})) { followSelection(table); return; }
  }
  if ((b === STICK_LEFT || b === STICK_RIGHT) && layer === document.body && S.sys) {  // back to the lists, that one
    enterList(b === STICK_LEFT ? "keep" : "move");
    return;
  }
  if (dir) { move(dir); return; }
  if (b === 0) { if (P.cur) press(); else move("down"); return; }
  if (b === 1) { back(); return; }
  if (b === 8 && layer === document.body) { openSearch(); return; }
  if ((b === 4 || b === 5) && layer === document.body) { nextZone(b === 5 ? 1 : -1); return; }
  if (b === 6 || b === 7) padScroll(b === 7 ? 1 : -1, true);
}

// Something in the layer that scrolls (for the Scroll hint: no hint when there's nothing to scroll)
const scrollsIn = (layer) => [...layer.querySelectorAll(".table, .form, .r-info, .store-details, .help-rows, .controls, .sheet > div")]
  .some((x) => x.scrollHeight > x.clientHeight + 2 && /auto|scroll/.test(getComputedStyle(x).overflowY));

// The right stick (and LT / RT in sheets) scrolls what's under the cursor: the details panel in the main window.
function padScroll(amount, page = false) {
  const scrolls = (x) => x.scrollHeight > x.clientHeight + 2 && /auto|scroll/.test(getComputedStyle(x).overflowY);
  let el = P.cur && P.cur.parentElement;
  while (el && el !== document.body && !scrolls(el)) el = el.parentElement;
  if (!el || el === document.body) {
    el = topLayer() === document.body ? $("details-body") : topLayer().querySelector(".table, .form, .r-info") || topLayer();
  }
  el.scrollBy({ top: page ? amount * el.clientHeight * 0.85 : amount, behavior: page ? "smooth" : "auto" });
}

function pollPads(now) {
  requestAnimationFrame(pollPads);
  if (!S.opts.gamepad || !document.hasFocus()) return;  // (not while another app, ES-DE say, has the pad)
  for (const pad of navigator.getGamepads ? navigator.getGamepads() : []) {
    if (!pad) continue;
    const pressed = new Set();
    pad.buttons.forEach((btn, i) => { if (btn?.pressed && i <= 15) pressed.add(i); });
    if (pad.axes[1] < -0.55) pressed.add(12);
    if (pad.axes[1] > 0.55) pressed.add(13);
    if (pad.axes[0] < -0.65) pressed.add(14);
    if (pad.axes[0] > 0.65) pressed.add(15);
    const stick = pad.axes[3] || 0;
    if (Math.abs(stick) > 0.25 && $("overlay").hidden) padScroll(stick * 18);
    if ((pad.axes[2] || 0) < -0.6) pressed.add(STICK_LEFT);  // the right stick across: the other game list
    if ((pad.axes[2] || 0) > 0.6) pressed.add(STICK_RIGHT);
    for (const b of pressed) {
      if (!(b in held)) {
        held[b] = now + 400;
        if (!S.pad) { S.pad = true; mouseTravel = 0; document.body.classList.remove("kbd"); if (P.cur) box(P.cur).classList.add("pad-cur"); hints(); }
        padButton(b, false);
      } else if (REPEATS.has(b) && now >= held[b]) { held[b] = now + 80; padButton(b, true); }
    }
    for (const b of Object.keys(held)) if (!pressed.has(Number(b))) delete held[b];
  }
  syncCursor();
}

// ---------- Steam Deck button glyphs, drawn here (not Valve's artwork) ----------
// padGlyph("a") -> an inline SVG of that button: a b x y, l1 r1 (bumpers), l2 r2 (triggers), view, menu, dpad,
// dpad-lr, dpad-ud (the d-pad, those arms lit), rs, r3, rs-lr, rs-ud (the right stick, clicked or pushed that way).
// "l1/r1" draws both.
const GLYPH_ON = "#e6e9ef", GLYPH_INK = "#14171d", GLYPH_OFF = "#5f6678";
const GLYPHS = (() => {
  const svg = (w, h, body, label) => `<svg class="pg${h > 24 ? " tall" : ""}" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" role="img" `
    + `aria-label="${label}">${body}</svg>`;
  const text = (x, y, t, size = 12) => `<text x="${x}" y="${y}" text-anchor="middle" font-size="${size}" `
    + `font-weight="800" fill="${GLYPH_INK}">${t}</text>`;
  const face = (t) => svg(24, 24, `<circle cx="12" cy="12" r="11" fill="${GLYPH_ON}"/>${text(12, 16.3, t)}`, t);
  // a bumper: long and flat, its outer top corner well rounded; a trigger: tall, its top an arch
  const bumper = (t, left) => svg(32, 24, `<path d="${left ? "M3 20V12Q3 4 12 4H27Q29 4 29 6V18Q29 20 27 20Z"
    : "M29 20V12Q29 4 20 4H5Q3 4 3 6V18Q3 20 5 20Z"}" fill="${GLYPH_ON}"/>${text(left ? 17 : 15, 16, t, 10.5)}`, t);
  const trigger = (t) => svg(26, 24, `<path d="M3 21V11Q3 2 13 2Q23 2 23 11V21Q23 23 21 23H5Q3 23 3 21Z" fill="${GLYPH_ON}"/>`
    + text(13, 17.5, t, 10.5), t);
  const pill = (body, label) => svg(30, 24, `<rect x="1" y="3" width="28" height="18" rx="9" fill="${GLYPH_ON}"/>${body}`, label);
  const ink = `fill="none" stroke="${GLYPH_INK}" stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round"`;
  const tri = (pts, fill) => `<path d="M${pts}Z" fill="${fill}"/>`;
  function dpad(lit, label) {  // lit: which arms ("u", "d", "l", "r")
    const arm = { u: [8.5, 1, 7, 9], d: [8.5, 14, 7, 9], l: [1, 8.5, 9, 7], r: [14, 8.5, 9, 7] };
    const point = { u: "12 3.2 14.3 6.4 9.7 6.4", d: "12 20.8 14.3 17.6 9.7 17.6", l: "3.2 12 6.4 9.7 6.4 14.3",
      r: "20.8 12 17.6 9.7 17.6 14.3" };
    const body = Object.keys(arm).map((a) => `<rect x="${arm[a][0]}" y="${arm[a][1]}" width="${arm[a][2]}" `
      + `height="${arm[a][3]}" rx="2" fill="${lit.includes(a) ? GLYPH_ON : GLYPH_OFF}"/>`
      + (lit.includes(a) ? tri(point[a], GLYPH_INK) : "")).join("");
    return svg(24, 24, `${body}<rect x="8" y="8" width="8" height="8" fill="${lit === "udlr" ? GLYPH_ON : GLYPH_OFF}"/>`, label);
  }
  const stick = (t, cx, cy) => `<circle cx="${cx}" cy="${cy}" r="10" fill="${GLYPH_ON}"/>`
    + `<circle cx="${cx}" cy="${cy}" r="6.6" ${ink}/>${text(cx, cy + (t.length > 1 ? 2.6 : 3.3), t, t.length > 1 ? 7 : 9)}`;
  return {
    a: face("A"), b: face("B"), x: face("X"), y: face("Y"),
    l1: bumper("L1", true), r1: bumper("R1", false), l2: trigger("L2"), r2: trigger("R2"),
    view: pill(`<rect x="9" y="7" width="8" height="7" rx="1.5" ${ink}/><rect x="13" y="10" width="8" height="7" rx="1.5" `
      + `fill="${GLYPH_INK}"/>`, "View"),
    menu: pill(`<path d="M9.5 8h11M9.5 12h11M9.5 16h11" ${ink}/>`, "Menu"),
    dpad: dpad("udlr", "D-pad"), "dpad-lr": dpad("lr", "D-pad left and right"), "dpad-ud": dpad("ud", "D-pad up and down"),
    rs: svg(24, 24, stick("R", 12, 12), "Right stick"), r3: svg(24, 24, stick("R3", 12, 12), "R3"),
    "rs-lr": svg(36, 24, stick("R", 18, 12) + tri("1 12 5.5 8 5.5 16", GLYPH_ON) + tri("35 12 30.5 8 30.5 16", GLYPH_ON),
      "Right stick left and right"),
    "rs-ud": svg(24, 32, stick("R", 12, 16) + tri("12 0.5 8 4.6 16 4.6", GLYPH_ON) + tri("12 31.5 8 27.4 16 27.4", GLYPH_ON),
      "Right stick up and down"),
  };
})();

function padGlyph(id) {
  return `<span class="glyph pad">${id.split("/").map((g) => GLYPHS[g]).join("")}</span>`;
}

// Everything the keys or buttons do right now, for the hints along the bottom (app.js's hints()): a button and what
// it does (["a", "Mark"], with padGlyph's names) or ["key", key, text]. A sheet can add its own (its keys handler's
// .hints = { pad: [...], keys: [...] }, or a function of the control under the cursor returning that), shown while its
// table or its own keys have the cursor.
const typingIn = () => (document.activeElement?.matches?.(`${TEXTY}, input[type=number]`) ? document.activeElement : null);

function uiHints() {
  const layer = topLayer(), pad = S.pad, main = layer === document.body;
  const k = (key, text) => ["key", key, text];
  if (osk.shown()) {
    return [["dpad", "Keys"], ["a", "Type"], ["x", "Space"], ["y", "Delete"], ["l1", "Shift"], ["b", "Done"]];
  }
  if (typingIn()) {  // a text box with the keyboard in it
    return pad ? [["a", "On-screen keyboard"], ["dpad", "Leave the box"], ["b", "Done typing"]]
      : typingIn().type === "number" ? [k("↑ ↓", "Change"), k("Tab", "Leave the box"), k("Esc", "Done typing")]
        : [k(typingIn().tagName === "TEXTAREA" ? "Tab" : typingIn() === $("search") ? "↓" : "↑ ↓", "Leave the box"), k("Esc", "Done typing")];
  }
  const around = pad ? [["l1/r1", "Next area"], ["view", "Search"], ["menu", "Menu"]]
    : [k("F6", "Next area"), k("/", "Search"), k("F10", "Menu")];
  if (main && !P.cur) {  // the lists
    if (!S.sys) return [pad ? ["dpad", "Move"] : k("↑ ↓ ← →", "Move"), ...around];
    const marked = L().items.filter((g) => S.marked.has(g.key)).length;
    const verb = S.active === "keep" ? "Move" : "Keep", act = marked ? `${verb} ${marked} marked` : verb;
    const b = marked ? "Unmark all" : S.query ? "Clear search" : "";
    return pad
      ? [["dpad-ud", "Choose"], ["dpad-lr", "Other list"], ["a", "Mark"], ["x", act], ["y", "Undo"], ["r3", "Game options"],
        ...(b ? [["b", b]] : []), ...around, ["rs-ud", "Scroll details"]]
      : [k("↑ ↓", "Choose"), k("← →", "Other list"), k("Space", "Mark"), k("Enter", act), k("Ctrl+Z", "Undo"),
        k("Shift+F10", "Game options"), ...(b ? [k("Esc", b)] : []), ...around];
  }
  const what = layer === $("picker") ? "Pick" : P.cur?.tagName === "SELECT" ? "Change"
    : P.cur?.matches(`${TEXTY}, input[type=number]`) ? "Type" : "Select";
  const lone = layer === $("overlay-box") && layer.querySelectorAll(".btns button").length === 1;
  const backText = layer === $("picker") ? "Cancel" : main ? "Back to the lists" : layer === $("sheet") ? "Close"
    : layer === $("overlay-box") ? (overlayCancel ? "Cancel" : lone ? "OK" : "") : layer.id === "menu" && layer.dataset.group
      ? "Back" : "Close";
  const backHint = backText ? [pad ? ["b", backText] : k("Esc", backText)] : [];
  const sheetHints = typeof sheetKeys?.hints === "function" ? sheetKeys.hints(P.cur) : sheetKeys?.hints;
  const own = layer === $("sheet") && sheetHints && (!P.cur || P.cur.matches(".trow")) ? sheetHints[pad ? "pad" : "keys"] : null;
  const lone1 = !main && focusables(layer).length < 2;  // (one button: nothing to move to)
  const h = own ? [...own, ...backHint]
    : [...(lone1 ? [] : [pad ? ["dpad", "Move"] : k("↑ ↓ ← →", "Move")]), ...(P.cur ? [pad ? ["a", what] : k("Enter", what)] : []), ...backHint];
  if (main) {
    h.push(...around);
    if (P.cur?.closest("#details")) h.push(pad ? ["rs-ud", "Scroll"] : k("PgUp PgDn", "Scroll"));
  }
  if (inBox(layer) && !ownsAll() && sheetAreas(layer).length > 1) h.push(pad ? ["l1/r1", "Next area"] : k("F6", "Next area"));
  if (ownsAll()) h.push(pad ? ["l2/r2", "Scroll details"] : k("PgUp PgDn", "Scroll details"));
  else if (onRow()) h.push(pad ? ["l2/r2", "Page"] : k("PgUp PgDn", "Page"));
  else if (layer === $("sheet") && scrollsIn(layer)) h.push(pad ? ["l2/r2", "Scroll"] : k("PgUp PgDn", "Scroll"));
  return h;
}

// ---------- picking from a list (a <select>): its options as a menu the cursor can go through ----------
const picker = (() => {
  let el = null, sel = null;
  function open(target) {
    if (!el) {
      el = document.createElement("div");
      el.id = "picker";
      el.className = "popover choices";
      el.addEventListener("click", (e) => {
        const b = e.target.closest("button[data-i]");
        if (!b) return;
        const s = sel;
        close();
        if (s.selectedIndex !== Number(b.dataset.i)) {
          s.selectedIndex = Number(b.dataset.i);
          s.dispatchEvent(new Event("input", { bubbles: true }));
          s.dispatchEvent(new Event("change", { bubbles: true }));
        }
      });
      el.addEventListener("mousedown", (e) => e.stopPropagation());
      document.body.appendChild(el);
    }
    sel = target;
    el.innerHTML = [...target.options].map((o, i) => `<button data-i="${i}"${o.disabled ? " disabled" : ""}`
      + `${i === target.selectedIndex ? ' class="cur"' : ""}>${esc(o.textContent)}</button>`).join("");
    el.hidden = false;
    const r = target.getBoundingClientRect(), h = el.offsetHeight;
    el.style.minWidth = `${Math.max(180, r.width)}px`;
    el.style.left = `${Math.min(r.left, innerWidth - el.offsetWidth - 8)}px`;
    el.style.top = `${r.bottom + 6 + h < innerHeight ? r.bottom + 6 : Math.max(8, r.top - 6 - h)}px`;
    syncCursor(true);
  }
  function close() {
    if (!el || el.hidden) return;
    el.hidden = true;
    const s = sel;
    sel = null;
    if (s?.isConnected) setCursor(s);
  }
  return { open, close, shown: () => Boolean(el && !el.hidden) };
})();

// ---------- folders and files, without the desktop's dialog (a gamepad can't work that one) ----------
// -> the folder's path (files: [paths], save: the folder joined to that name), or null / [] when cancelled.
function browseBox({ start = null, title = "Your ROMs folder", files = false, save = null } = {}) {
  return new Promise((resolve) => {
    const picked = new Set();
    let here = null;
    const done = (answer) => { closeOverlay(); resolve(answer); };
    async function show(path, land = null) {  // land: the entry to put the cursor on (the folder just left)
      try { here = await call("browse", { path, files }); } catch (e) { oops(e); done(files ? [] : null); return; }
      const join = (name) => here.path.replace(/[\\/]$/, "") + here.sep + name;
      const entries = here.entries.map((e) => `<button class="${e.dir ? "dir" : "file"}${picked.has(join(e.name)) ? " on" : ""}"
        data-name="${esc(e.name)}">${e.dir ? "📁" : "📄"} ${esc(e.name)}</button>`).join("");
      overlay(`<h2>${esc(title)}</h2>
        <div class="browse-places">${here.places.map((p, i) => `<button class="chip" data-place="${i}">${esc(p.label)}</button>`).join("")}</div>
        <p class="browse-path">${esc(here.path)}</p>
        <div class="browse-list">${here.parent ? `<button class="dir up" data-up="1">‹ Up a folder</button>` : ""}${entries}
          ${here.error ? `<p class="error">${esc(here.error)}</p>` : !here.entries.length ? `<p class="muted">${files ? "Nothing here" : "No folders inside"}</p>` : ""}
          ${here.more ? `<p class="muted">… and ${here.more.toLocaleString()} more</p>` : ""}</div>`,
      [["Cancel", () => done(files ? [] : null)],
        [files ? `Add ${picked.size || ""} picked`.replace("  ", " ") : save ? "Save here" : "Use this folder",
          () => done(files ? [...picked] : save ? join(save) : here.path), true]]);
      const box = $("overlay-box");
      box.classList.add("browse");
      if (files && !picked.size) box.querySelector(".btns .primary").disabled = true;
      overlayCancel = () => done(files ? [] : null);
      box.querySelector(".browse-list").onclick = box.querySelector(".browse-places").onclick = (e) => {
        const b = e.target.closest("button");
        if (!b) return;
        if (b.dataset.up) show(here.parent, here.path.replace(/[\\/]$/, "").split(/[\\/]/).pop());
        else if (b.dataset.place) show(here.places[Number(b.dataset.place)].path);
        else if (b.classList.contains("dir")) show(join(b.dataset.name));
        else { const p = join(b.dataset.name); if (picked.has(p)) picked.delete(p); else picked.add(p); show(here.path, b.dataset.name); }
      };
      const first = [...box.querySelectorAll(".browse-list button")].find((b) => b.dataset.name === land)
        || box.querySelector(".browse-list button");
      if (first && (S.pad || document.body.classList.contains("kbd"))) setCursor(first);
    }
    show(start);
  });
}

// ---------- the on-screen keyboard ----------
const osk = (() => {
  const ROWS = ["1234567890", "qwertyuiop", "asdfghjkl'", "zxcvbnm,.-", "*?!()[]#&:"];
  const K = { el: null, target: null, r: 1, c: 0, shift: false };

  function keys() {
    const rows = ROWS.map((r) => [...(K.shift ? r.toUpperCase() : r)].map((ch) => ({ ch, label: ch })));
    rows.push([{ act: "shift", label: "⇧ Shift" }, { ch: " ", label: "Space" }, { act: "del", label: "⌫" },
      ...(K.target?.tagName === "TEXTAREA" ? [{ ch: "\n", label: "↵" }] : []), { act: "done", label: "Done" }]);
    return rows;
  }

  function draw() {
    const rows = keys();
    K.r = Math.min(K.r, rows.length - 1);
    K.c = Math.min(K.c, rows[K.r].length - 1);
    K.el.innerHTML = rows.map((row, r) => `<div class="osk-row">${row.map((k, c) =>
      `<button class="osk-key${k.act || k.ch === " " ? " wide" : ""}${r === K.r && c === K.c ? " on" : ""}${k.act === "shift" && K.shift ? " lit" : ""}"
        data-r="${r}" data-c="${c}">${esc(k.label)}</button>`).join("")}</div>`).join("");
  }

  function type(k) {
    const t = K.target;
    if (k.act === "shift") { K.shift = !K.shift; draw(); return; }
    if (k.act === "done") { close(); return; }
    if (t.type === "number") {
      t.value = k.act === "del" ? t.value.slice(0, -1) : /[\d.]/.test(k.ch) ? t.value + k.ch : t.value;
    } else if (k.act === "del") {
      const s = t.selectionStart, e = t.selectionEnd;
      if (s === e && s > 0) t.setRangeText("", s - 1, s, "end"); else t.setRangeText("", s, e, "end");
    } else t.setRangeText(k.ch, t.selectionStart, t.selectionEnd, "end");
    t.dispatchEvent(new Event("input", { bubbles: true }));
    if (K.shift && k.ch) { K.shift = false; draw(); }
  }

  function open(target) {
    if (!K.el) {
      K.el = document.createElement("div");
      K.el.id = "osk";
      K.el.className = "osk";
      K.el.addEventListener("mousedown", (e) => e.preventDefault());  // (keeps the text box focused)
      K.el.addEventListener("click", (e) => {
        const b = e.target.closest(".osk-key");
        if (!b) return;
        K.r = Number(b.dataset.r); K.c = Number(b.dataset.c);
        type(keys()[K.r][K.c]);
        if (K.el) draw();
      });
      document.body.appendChild(K.el);
    }
    K.target = target;
    K.shift = false;
    K.el.hidden = false;
    draw();
    const low = target.getBoundingClientRect().bottom > innerHeight - K.el.offsetHeight - 90;  // (don't cover the box)
    K.el.classList.toggle("top", low);
    hints();
  }

  function close() {
    if (!K.el || K.el.hidden) return;
    K.el.hidden = true;
    const t = K.target;
    K.target = null;
    if (t?.isConnected) {
      t.dispatchEvent(new Event("change", { bubbles: true }));
      t.blur();
      if (t === $("search")) setCursor(null); else setCursor(t, { focus: false });
    }
    hints();
  }

  function pad(b) {
    const rows = keys();
    const go = (dr, dc) => {
      if (dr) {
        const x = (K.c + 0.5) / rows[K.r].length;
        K.r = (K.r + dr + rows.length) % rows.length;
        K.c = Math.min(rows[K.r].length - 1, Math.floor(x * rows[K.r].length));
      } else K.c = (K.c + dc + rows[K.r].length) % rows[K.r].length;
      draw();
    };
    if (b === 12) go(-1, 0); else if (b === 13) go(1, 0); else if (b === 14) go(0, -1); else if (b === 15) go(0, 1);
    else if (b === 0) type(rows[K.r][K.c]);
    else if (b === 2) type({ ch: " " });
    else if (b === 3) type({ act: "del" });
    else if (b === 4 || b === 5) { K.shift = !K.shift; draw(); }
    else if (b === 1 || b === 9) close();
  }

  return { open, close, pad, shown: () => Boolean(K.el && !K.el.hidden) };
})();

requestAnimationFrame(pollPads);
