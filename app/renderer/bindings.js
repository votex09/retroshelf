// Your own buttons and keys: ☰ → Help → Change buttons and keys. (Uses app.js, sheets.js and pad.js's glyphs.)
// A pad button or a key is given another one's work; the two swap, so every job always has exactly one button and one
// key. The rest of the app never sees the change: the pad's buttons are renamed as they're read (pollPads asks
// padRole), and a rebound key is turned back into the key it stands for before anything else hears it.

// Pad buttons by their standard-mapping number: what each does, and its glyph. 10 (L3) does nothing until given a job.
const PAD_ROLES = [
  [0, "a", "A", "Mark; press"], [1, "b", "B", "Back, close; unmark, then clear the search"],
  [2, "x", "X", "Flip to the other list"], [3, "y", "Y", "Undo"],
  [4, "l1", "L1", "Previous part of the window"], [5, "r1", "R1", "Next part of the window"],
  [6, "l2", "L2", "Page / scroll up"], [7, "r2", "R2", "Page / scroll down"],
  [8, "view", "View", "Search"], [9, "menu", "Menu", "☰ menu"], [11, "r3", "R3", "The game's menu"],
];
const PAD_GLYPH = { 0: "a", 1: "b", 2: "x", 3: "y", 4: "l1", 5: "r1", 6: "l2", 7: "r2", 8: "view", 9: "menu", 10: "l3", 11: "r3" };
const PAD_NAME = { 0: "A", 1: "B", 2: "X", 3: "Y", 4: "L1", 5: "R1", 6: "L2", 7: "R2", 8: "View", 9: "Menu", 10: "L3", 11: "R3" };
const PAD_BINDABLE = Object.keys(PAD_GLYPH).map(Number);

// Keys, by the key the app listens for: what it does.
const KEY_JOBS = [
  ["Space", "Mark; press"], ["Enter", "Press; in the lists, flip to the other list"],
  ["Escape", "Back, close; unmark, then clear the search"], ["Ctrl+Z", "Undo"],
  ["Shift+F10", "The game's menu"], ["PageUp", "Page / scroll up"], ["PageDown", "Page / scroll down"],
  ["F6", "Next part of the window"], ["Shift+F6", "Previous part of the window"], ["/", "Search"],
  ["F10", "☰ menu"], ["Ctrl+R", "Review one at a time"], ["Ctrl+I", "Import ROMs"], ["F5", "Rescan"],
];
// Keys that move the cursor or type: never given another job.
const KEEP_KEYS = new Set(["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Tab", "Shift+Tab", "Home", "End", "Backspace"]);

const B = { pad: {}, keys: {} };  // pad: {job's button: the button doing it}; keys: {job's key: the key doing it}
let padFrom = {}, keyFrom = {};   // the other way round: a pressed button / key -> the job's button / key
let capture = null;               // the Change buttons and keys window waiting for a press: fn(button or key)

function useBindings(b) {
  B.pad = Object.fromEntries(Object.entries(b?.pad || {}).map(([k, v]) => [Number(k), Number(v)]));
  B.keys = { ...(b?.keys || {}) };
  padFrom = {};
  for (const [job, btn] of Object.entries(B.pad)) padFrom[btn] = Number(job);
  for (const n of PAD_BINDABLE) if (!(n in padFrom) && !(n in B.pad)) padFrom[n] = n;
  keyFrom = {};
  for (const [job, key] of Object.entries(B.keys)) keyFrom[key] = job;
}
const padButtonFor = (job) => (job in B.pad ? B.pad[job] : job);  // which button does this job now
const keyFor = (job) => B.keys[job] || job;
// A pressed button -> the job it does (null: none now); the d-pad and sticks are never rebound.
const padRole = (n) => (n in padFrom ? padFrom[n] : PAD_BINDABLE.includes(n) ? null : n);

// "Ctrl+Z", "Shift+F10", "Space", "/", "Q": a key press as the tables write it.
function comboOf(e) {
  let k = e.key === " " ? "Space" : e.key.length === 1 ? e.key.toUpperCase() : e.key;
  const shift = e.shiftKey && (e.key.length > 1 || /[a-z]/i.test(e.key));
  return `${e.ctrlKey || e.metaKey ? "Ctrl+" : ""}${e.altKey ? "Alt+" : ""}${shift ? "Shift+" : ""}${k}`;
}
function eventOf(combo) {
  const parts = combo.split("+"), k = parts.pop() || "+";
  const key = k === "Space" ? " " : k.length === 1 ? k.toLowerCase() : k;
  return { key, ctrlKey: parts.includes("Ctrl"), altKey: parts.includes("Alt"), shiftKey: parts.includes("Shift") };
}
const KEY_SHOW = { Escape: "Esc", PageUp: "PgUp", PageDown: "PgDn", ArrowUp: "↑", ArrowDown: "↓", ArrowLeft: "←",
  ArrowRight: "→", " ": "Space" };
const showCombo = (c) => c.split("+").map((p) => KEY_SHOW[p] || p).join("+");

// A hint's or the Help table's key text ("PgUp PgDn", "Space / Backspace") with rebound keys shown as the new ones.
const SHOWN_AS = { Esc: "Escape", PgUp: "PageUp", PgDn: "PageDown" };
function showKeys(text) {
  if (!Object.keys(B.keys).length) return text;
  return text.replace(/[^\s/]+(?:\+[^\s/]+)*/g, (t) => {
    const job = SHOWN_AS[t] || t;
    return B.keys[job] ? showCombo(B.keys[job]) : t;
  });
}

// Before anything else hears a key: a rebound key becomes the one it stands for; a key whose job went elsewhere
// does nothing. Not while typing in a box.
window.addEventListener("keydown", (e) => {
  if (e.__rebound) return;
  if (capture) {
    if (["Shift", "Control", "Alt", "Meta"].includes(e.key)) return;
    e.preventDefault(); e.stopImmediatePropagation();
    capture(e.key === "Escape" && !e.ctrlKey && !e.shiftKey ? null : comboOf(e), "key");
    return;
  }
  if (!Object.keys(B.keys).length || e.target.matches?.(`${TEXTY}, input[type=number]`)) return;
  const c = comboOf(e);
  const job = keyFrom[c];
  if (job && job !== c) {
    e.preventDefault(); e.stopImmediatePropagation();
    const ev = new KeyboardEvent("keydown", { ...eventOf(job), bubbles: true, cancelable: true, repeat: e.repeat });
    ev.__rebound = true;
    e.target.dispatchEvent(ev);
  } else if (B.keys[c] && !job) {
    e.preventDefault(); e.stopImmediatePropagation();
  }
}, true);

// ---------- the window ----------
async function saveBindings(note) {
  try {
    const o = await call("set_bindings", { pad: B.pad, keys: B.keys });
    useBindings(o.bindings);
  } catch (e) { oops(e); }
  hints();
  if (note) toast(note);
}

// Give job's button to button n; whichever job had n takes job's old button.
function bindPad(job, n) {
  const was = padButtonFor(job);
  if (was === n) return null;
  const other = padFrom[n];
  const pad = { ...B.pad, [job]: n };
  if (other !== undefined && other !== null && other !== job) pad[other] = was;
  for (const k of Object.keys(pad)) if (Number(k) === pad[k]) delete pad[k];
  useBindings({ pad, keys: B.keys });
  const role = PAD_ROLES.find((r) => r[0] === other);
  return role && other !== job ? `${PAD_NAME[was]} now does what ${PAD_NAME[n]} did (${role[3].split(";")[0]})` : null;
}
function bindKey(job, combo) {
  const was = keyFor(job);
  if (was === combo) return null;
  const other = keyFrom[combo] || (KEY_JOBS.some(([k]) => k === combo) && !B.keys[combo] ? combo : null);
  const keys = { ...B.keys, [job]: combo };
  if (other && other !== job) keys[other] = was;
  for (const k of Object.keys(keys)) if (keys[k] === k) delete keys[k];
  useBindings({ pad: B.pad, keys });
  const what = other && other !== job ? KEY_JOBS.find(([k]) => k === other)[1].split(";")[0] : null;
  return what ? `${showCombo(was)} now does what ${showCombo(combo)} did (${what})` : null;
}

function openBindings(focus) {
  const padRows = PAD_ROLES.map(([job, , name, what]) => `<span>${esc(what)}</span>`
    + `<span class="bind-now">${padGlyph(PAD_GLYPH[job])}</span>`
    + `<button class="ghost bind" data-pad="${job}">Change</button>`).join("");
  const keyRows = KEY_JOBS.map(([job, what]) => `<span>${esc(what)}</span>`
    + `<span class="bind-now"><kbd>${esc(showCombo(keyFor(job)))}</kbd></span>`
    + `<button class="ghost bind" data-key="${esc(job)}">Change</button>`).join("");
  sheet(`
    <div class="sheet-head"><h2>Change buttons and keys</h2>
      <p>Pick Change, then press the button or key that should do it. If another job had that one, the two swap.</p></div>
    <div class="form help binds">
      <div class="controls-head">Gamepad buttons</div><div class="bind-grid">${padRows}</div>
      <div class="controls-head">Keys</div><div class="bind-grid">${keyRows}</div>
      <p class="note" id="bd-note">The d-pad, the sticks and the arrow keys always move the cursor.</p>
    </div>
    <div class="sheet-foot"><button class="ghost" id="bd-reset">Back to the defaults</button><span class="grow"></span>
      <button class="primary" id="bd-close">Close</button></div>`, "wide form-sheet", () => { capture = null; });
  $("bd-close").onclick = closeSheet;
  $("bd-reset").onclick = async () => {
    useBindings({});
    await saveBindings("Buttons and keys are back to the defaults");
    openBindings("#bd-reset");
  };
  for (const b of document.querySelectorAll("#sheet .bind")) b.onclick = () => listen(b);
  if (focus) { const el = document.querySelector(`#sheet ${focus}`); if (el) setCursor(el); }
}

function listen(btn) {
  const pad = btn.dataset.pad !== undefined;
  const job = pad ? Number(btn.dataset.pad) : btn.dataset.key;
  const note = $("bd-note");
  btn.textContent = pad ? "Press a button…" : "Press a key…";
  btn.classList.add("listening");
  note.textContent = pad ? "Press the pad button for this (or Esc on the keyboard to keep it)."
    : "Press the key for this, with Ctrl, Alt or Shift if you like (Esc keeps it).";
  const timer = setTimeout(() => done(null), 10000);
  function done(v, kind) {
    if (v !== null && kind !== (pad ? "pad" : "key")) { capture = done; return; }  // (a key doesn't pick a button)
    clearTimeout(timer);
    capture = null;
    const sel = pad ? `[data-pad="${job}"]` : `[data-key="${CSS.escape(job)}"]`;
    if (v !== null && !pad && KEEP_KEYS.has(v)) {
      openBindings(sel);
      $("bd-note").textContent = `${showCombo(v)} moves the cursor, so it can't do another job.`;
      return;
    }
    const msg = v === null ? null : pad ? bindPad(job, v) : bindKey(job, v);
    saveBindings(msg).then(() => {
      if ($("sheet-wrap").hidden) return;
      openBindings(sel);
      if (msg) $("bd-note").textContent = `${msg}.`;
      else if (!pad && /^(Shift\+)?[A-Z0-9]$/.test(v || "")) $("bd-note").textContent = `In the lists, ${v.slice(-1)} also jumps to games starting with it.`;
    });
  }
  // (the press that picked Change is still down: only a new press counts)
  setTimeout(() => { capture = done; }, 0);
}
