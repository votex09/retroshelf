// Getting around everything that isn't the game lists, with a gamepad or the keyboard: the header, the filter tabs,
// the footer, the details panel, the ☰ menu, popovers, sheets and boxes. (Uses app.js, sheets.js and settings.js.)
//   A cursor (an accent ring, .pad-cur) sits on one control; the d-pad or the arrow keys move it to the nearest
// control that way, A / Enter / Space presses it and B / Esc goes back: out of a text box, out of a submenu, closes
// the popover or sheet, then back to the lists. In the lists themselves the keys are app.js's handle(). Everywhere in
// the main window LB / RB (F6) go round its parts (header, filter tabs, Keeping, Moving, details, footer), Select
// (View) searches, Start opens ☰, and R3, the Menu key or Shift+F10 opens the game's menu. A in a text box opens an
// on-screen keyboard (osk below). The hints along the bottom always list what the buttons do right there (uiHints).
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

// ---------- the cursor ----------
function sig(el) {  // enough to find a control again after its sheet redraws
  const holder = el.closest("[id]");
  const data = Object.entries(el.dataset || {})
    .map(([k, v]) => `[data-${k.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`)}="${CSS.escape(v)}"]`).join("");
  return el.id ? `#${CSS.escape(el.id)}` : data && holder ? `#${CSS.escape(holder.id)} ${el.tagName.toLowerCase()}${data}` : null;
}

function setCursor(el, { focus = true } = {}) {
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
  hints();
}

function enterList(name) {
  if (P.cur) box(P.cur).classList.remove("pad-cur");
  P.saved.delete(document.body);
  P.cur = null; P.sig = null;
  if (document.activeElement && document.activeElement !== document.body) document.activeElement.blur();
  if (S.sys) setActive(name);
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
  let to = nearest(from, dir, els.filter((el) => el !== from), from.classList.contains("list"));
  if (!to && (dir === "up" || dir === "down") && ["menu", "ctx", "systems-pop", "picker"].includes(layer.id)) {  // a menu goes round
    to = dir === "down" ? els[0] : els[els.length - 1];
  }
  if (to) setCursor(to);
}

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

// LB / RB (F6 / Shift+F6): the next or previous part of the main window, round and round: the header, the filter
// tabs, the Keeping list, the Moving list, the details panel and the footer. Each part remembers where the cursor
// was in it; parts with nothing to press right now (a footer whose buttons are off) are skipped.
const AREAS = [".topbar", "#filterbar", "keep", "move", "#details", "footer"];
const areaSaved = new Map();
const isList = (area) => area === "keep" || area === "move";
const areaOf = (el) => (el ? AREAS.findIndex((a) => !isList(a) && el.closest(a)) : AREAS.indexOf(S.active));
function nextZone(step) {
  closePopovers();
  const els = focusables(document.body);
  const at = areaOf(P.cur);
  if (at >= 0 && P.cur) areaSaved.set(AREAS[at], P.cur);
  for (let i = 1; i <= AREAS.length; i++) {
    const area = AREAS[((at < 0 ? 0 : at) + step * i + AREAS.length * 2) % AREAS.length];
    if (isList(area)) {
      if (S.sys) { enterList(area); return; }
      continue;
    }
    const inside = els.filter((x) => x.closest(area));
    if (!inside.length) continue;
    const saved = areaSaved.get(area);
    setCursor(inside.includes(saved) ? saved : inside.find((x) => x.matches(".primary")) || inside[0]);
    return;
  }
}

// Select (View): search, with the on-screen keyboard.
function openSearch() {
  closePopovers();
  setCursor($("search"), { focus: false });
  press($("search"));
}

// ---------- the keyboard ----------
document.addEventListener("mousedown", (e) => {
  document.body.classList.remove("kbd");
  if (picker.shown() && !e.target.closest("#picker")) picker.close();
  if (P.cur) { box(P.cur).classList.remove("pad-cur"); if (topLayer() === document.body) P.cur = null; }
}, true);

document.addEventListener("focusin", (e) => {  // Tab, a click, a sheet focusing its own box: the cursor follows
  const el = e.target;
  if (el === P.cur || !el.matches?.(FOCUSABLE) || el.closest(".list, #osk")) return;
  const top = topLayer();
  if (top !== document.body && layerOf(el) !== top) {  // Tab out of a sheet or box: back into it
    el.blur();
    const inside = landing(top);
    if (inside) setCursor(inside);
    return;
  }
  if (P.cur) box(P.cur).classList.remove("pad-cur");
  P.cur = el; P.sig = sig(el);
  P.saved.set(layerOf(el), el);
  if (document.body.classList.contains("kbd") || S.pad) box(el).classList.add("pad-cur");
});

document.addEventListener("keydown", (e) => {
  document.body.classList.add("kbd");
  if (osk.shown()) osk.close();
  if (S.pad) { S.pad = false; hints(); }
  const t = e.target;
  if (t === $("search")) {
    if (e.key === "Escape" || e.key === "ArrowDown" || e.key === "Enter") { t.blur(); setCursor(null); e.preventDefault(); }
    return;
  }
  if (t.matches?.(TEXTY) || t.matches?.("input[type=number]")) {  // typing: Esc stops, the cursor stays on the box
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); t.blur(); setCursor(t, { focus: false }); back(); }
    return;
  }
  syncCursor();
  const layer = topLayer(), dir = NAV[e.key];
  if (e.key === "Escape") { e.preventDefault(); back(); return; }
  const navKey = dir || e.key === "Enter" || e.key === " ";
  const table = tableOf();
  if (layer === $("sheet") && sheetKeys && (!navKey || !P.cur || P.cur.matches(".trow")) && sheetKeys(e.key, e)) {
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
    if (handle(e.key, e)) e.preventDefault();
    return;
  }
  // a control has the cursor
  if (layer === document.body && (e.key === "F5" || (e.ctrlKey && (e.key === "r" || e.key === "i")))) {
    if (handle(e.key, e)) e.preventDefault();
    return;
  }
  if (layer === document.body && e.key === "F6") { e.preventDefault(); nextZone(e.shiftKey ? -1 : 1); return; }
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
  if (b === 9) { startMenu(); return; }
  if (layer === document.body && !P.cur) {  // the lists
    if (b === 1) { back(); return; }
    if (b === 8) { openSearch(); return; }
    if (b === 11) { gameMenu(); return; }
    if (b === 4 || b === 5) { nextZone(b === 5 ? 1 : -1); return; }
    const last = S.sys && L().sel >= L().items.length - 1;
    const leave = (b === 12 && S.sys && L().sel === 0) || (b === 13 && last) || (b === 15 && S.active === "move") || (!S.sys && dir);
    if (!repeat && leave) {
      move(dir);
      return;
    }
    if (LIST_KEYS[b]) handle(LIST_KEYS[b]);
    return;
  }
  if (layer === $("sheet") && sheetKeys && (!P.cur || P.cur.matches(".trow")) && b !== 1) {
    const key = { ...LIST_KEYS, 1: "Escape" }[b];
    const table = tableOf();
    if (key && sheetKeys(key, {})) { followSelection(table); return; }
  }
  if (dir) { move(dir); return; }
  if (b === 0) { if (P.cur) press(); else move("down"); return; }
  if (b === 1) { back(); return; }
  if (b === 8 && layer === document.body) { openSearch(); return; }
  if ((b === 4 || b === 5) && layer === document.body) { nextZone(b === 5 ? 1 : -1); return; }
  if (b === 6 || b === 7) padScroll(b === 7 ? 1 : -1, true);
}

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
    for (const b of pressed) {
      if (!(b in held)) {
        held[b] = now + 400;
        if (!S.pad) { S.pad = true; document.body.classList.remove("kbd"); if (P.cur) box(P.cur).classList.add("pad-cur"); hints(); }
        padButton(b, false);
      } else if (REPEATS.has(b) && now >= held[b]) { held[b] = now + 80; padButton(b, true); }
    }
    for (const b of Object.keys(held)) if (!pressed.has(Number(b))) delete held[b];
  }
  syncCursor();
}

// Everything the keys or buttons do right now, for the hints along the bottom (app.js's hints()): [class, glyph, text].
// A sheet can add its own (its keys handler's .hints = { pad: [...], keys: [...] }), shown while its table or its
// own keys have the cursor.
function uiHints() {
  const layer = topLayer(), pad = S.pad, main = layer === document.body;
  const k = (key, text) => ["key", key, text];
  if (osk.shown()) {
    return [["dpad", "✥", "Keys"], ["a", "A", "Type"], ["x", "X", "Space"], ["y", "Y", "Delete"], ["bumper", "LB", "Shift"],
      ["b", "B", "Done"]];
  }
  const around = pad ? [["bumper", "LB/RB", "Next area"], ["select", "SELECT", "Search"], ["start", "START", "Menu"]]
    : [k("F6", "Next area"), k("/", "Search")];
  if (main && !P.cur) {  // the lists
    if (!S.sys) return [pad ? ["dpad", "✥", "Move"] : k("↑ ↓ ← →", "Move"), ...around];
    const marked = L().items.filter((g) => S.marked.has(g.key)).length;
    const verb = S.active === "keep" ? "Move" : "Keep", act = marked ? `${verb} ${marked} marked` : verb;
    return pad
      ? [["dpad", "✥", "Choose"], ["a", "A", "Mark"], ["x", "X", act], ["y", "Y", "Undo"], ["stick", "R3", "Game options"],
        ...(S.query ? [["b", "B", "Clear search"]] : []), ...around, ["stick", "RS", "Scroll details"]]
      : [k(S.active === "keep" ? "→" : "←", act), k("Space", "Mark"), k("Ctrl+Z", "Undo"), k("Tab", "Other list"),
        k("Shift+F10", "Game options"), ...around];
  }
  const what = layer === $("picker") ? "Pick" : P.cur?.tagName === "SELECT" ? "Change"
    : P.cur?.matches(`${TEXTY}, input[type=number]`) ? "Type" : "Select";
  const lone = layer === $("overlay-box") && layer.querySelectorAll(".btns button").length === 1;
  const backText = layer === $("picker") ? "Cancel" : main ? "Back to the lists" : layer === $("sheet") ? "Close"
    : layer === $("overlay-box") ? (overlayCancel ? "Cancel" : lone ? "OK" : "") : layer.id === "menu" && layer.dataset.group
      ? "Back" : "Close";
  const backHint = backText ? [pad ? ["b", "B", backText] : k("Esc", backText)] : [];
  const own = layer === $("sheet") && sheetKeys?.hints && (!P.cur || P.cur.matches(".trow"))
    ? sheetKeys.hints[pad ? "pad" : "keys"] : null;
  const h = own ? [...own, ...backHint]
    : [pad ? ["dpad", "✥", "Move"] : k("↑ ↓ ← →", "Move"), pad ? ["a", "A", what] : k("Enter", what), ...backHint];
  if (main) {
    h.push(...around);
    if (pad && P.cur?.closest("#details")) h.push(["stick", "RS", "Scroll"]);
  }
  if (layer === $("sheet") && pad) h.push(["bumper", "LT/RT", "Scroll"]);
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
