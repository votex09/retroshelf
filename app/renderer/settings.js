// ☰ → Settings and the help sheets: Keyboard and gamepad, How patterns work. (Uses app.js and sheets.js.)
"use strict";

// The options change how the window behaves right away: see S.opts in app.js.
function applyOptions(o) {
  for (const k of Object.keys(S.opts)) if (k in o) S.opts[k] = o[k];
  document.body.classList.toggle("light", S.opts.light);
  document.body.classList.toggle("still", !S.opts.animations);
  document.body.classList.toggle("no-details", !S.opts.show_details);
  if (!S.opts.gamepad && S.pad) { S.pad = false; hints(); }
}

const OPTION_LABELS = [
  ["light", "Light theme", "dark text on a light background"],
  ["show_details", "Details panel", "the game's box art, text and video beside the lists"],
  ["play_videos", "Play gameplay videos", "ES-DE's clips start by themselves after a moment in the details panel (▶ always plays one)"],
  ["stream_videos", "Gameplay from YouTube when there's no clip", "plays the top YouTube gameplay video in YouTube's own player (needs the internet)"],
  ["gamepad", "Use a gamepad", "a Steam Deck's or Xbox-style pad moves through the lists"],
  ["animations", "Animations", "lists slide, numbers roll and the focus ring glides"],
  ["check_updates", "Check for updates when RetroShelf starts", "new versions download by themselves and go in when you restart"],
];

// The header's update button: a new version is out (portable copies) or ready to go in (the rest).
let lastUpdate = null;
function updateText(u) {
  return {
    checking: "Checking for updates…", latest: "You have the latest RetroShelf.",
    available: `RetroShelf ${u.version} is out. This copy can't update itself: download the new one.`,
    downloading: `Downloading RetroShelf ${u.version}${u.percent ? ` (${u.percent}%)` : ""}…`,
    ready: `RetroShelf ${u.version} is ready: it goes in when RetroShelf restarts.`,
    error: `Couldn't check for updates: ${u.message}`,
  }[u.state] || "";
}
function showUpdate(u) {
  lastUpdate = u;
  const b = $("update-btn");
  b.hidden = !["available", "ready"].includes(u.state);
  b.textContent = u.state === "ready" ? "⬆ Restart to update" : "⬆ New version";
  b.title = updateText(u);
  b.onclick = () => (u.state === "ready" ? rs.installUpdate() : rs.openUrl(u.url));
  if ($("o-update")) $("o-update").textContent = updateText(u);
}

async function openSettings() {
  if (S.sys) await flushDecide();
  const info = await call("settings");
  const p = info.platform;
  sheet(`
    <div class="sheet-head"><h2>Settings</h2></div>
    <div class="form settings">
      ${p ? `<div class="label">LaunchBox platform for ${esc(p.fullname)}</div>
        <p class="dim">Ratings, genres, details and scraping come from LaunchBox's games for this platform.${p.choices.length ? "" : " Download LaunchBox data from the ☰ menu to pick one."}</p>
        <select id="o-platform"${p.choices.length ? "" : " disabled"}>
          <option value="auto">Automatic${p.automatic ? `: ${esc(p.automatic)}` : " (none found)"}</option>
          <option value="">None: don't use LaunchBox here</option>
          ${p.choices.map((c) => `<option value="${esc(c)}">${esc(c)}</option>`).join("")}
        </select>` : ""}
      <div class="label">Window</div>
      ${OPTION_LABELS.map(([k, label, sub]) => `<label class="check opt"><input type="checkbox" data-opt="${k}"${info[k] ? " checked" : ""}>
        <span>${esc(label)}<small>${esc(sub)}</small></span></label>`).join("")}
      <div class="label">RetroShelf</div>
      <div class="row-btns"><button class="ghost" id="o-check">Check for updates</button>
        <button class="ghost" id="o-menu" hidden>Add to app menu</button>
        <button class="ghost" id="o-old">Bring settings over from the old RetroShelf…</button></div>
      <p class="dim" id="o-update"></p>
    </div>
    <div class="sheet-foot"><button class="ghost" id="o-keys">Keyboard and gamepad</button><span class="grow"></span><button class="primary" id="o-close">Close</button></div>`,
  "small form-sheet");
  if (p) {
    $("o-platform").value = !p.override ? "auto" : p.current;
    $("o-platform").onchange = async (e) => {
      const v = e.target.value;
      e.target.disabled = true;
      try {
        loadSystem(await call("set_platform", v === "auto" ? { automatic: true } : { platform: v }), L().current?.key);
        toast(v === "auto" ? "Back to the automatic platform" : v ? `Using LaunchBox's ${v}` : "Not using LaunchBox for this system");
      } catch (err) { oops(err); }
      if ($("o-platform")) e.target.disabled = false;
    };
  }
  for (const b of document.querySelectorAll("[data-opt]")) {
    b.onchange = async () => {
      try { applyOptions(await call("set_option", { name: b.dataset.opt, value: b.checked })); } catch (e) { oops(e); }
      if (b.dataset.opt === "play_videos" && !b.checked) stopVideo();
    };
  }
  if (lastUpdate) $("o-update").textContent = updateText(lastUpdate);
  $("o-check").onclick = async () => {
    $("o-update").textContent = "Checking for updates…";
    try { showUpdate(await rs.checkUpdates()); } catch (e) { $("o-update").textContent = e.message; }
  };
  rs.desktopStatus().then((d) => {
    if (!d.can || !$("o-menu")) return;
    $("o-menu").hidden = false;
    $("o-menu").textContent = d.installed ? "In the app menu ✓" : "Add to app menu";
    $("o-menu").onclick = async () => {
      const err = await rs.addToMenu();
      if (err) { toast(err, { error: true }); return; }
      $("o-menu").textContent = "In the app menu ✓";
      toast("RetroShelf is in your app menu");
    };
  });
  $("o-old").onclick = async () => {
    const folder = await pickFolder(null, "The old RetroShelf's folder (with retroshelf.py in it)");
    if (!folder) return;
    try {
      const r = await call("import_old", { folder });
      closeSheet();
      S.overview = r.overview;
      S.sys = null;
      showOverview();
      toast(`Brought over ${r.copied.join(", ")}`);
      const last = S.overview.systems.find((x) => x.code === S.overview.system && x.games > 0);
      if (last) await openSystem(last.code); else toggleSystems();
    } catch (e) { oops(e); }
  };
  $("o-keys").onclick = () => { closeSheet(); openKeys(); };
  $("o-close").onclick = closeSheet;
}

function helpRows(rows) {
  return `<div class="help-rows">${rows.map(([k, v]) => `<span class="keys">${k.split(" / ").map((x) => `<kbd>${esc(x)}</kbd>`).join(" ")}</span><span>${esc(v)}</span>`).join("")}</div>`;
}

function openKeys() {
  const pads = [...(navigator.getGamepads ? navigator.getGamepads() : [])].filter(Boolean).map((g) => g.id.replace(/\s*\(.*$/, ""));
  sheet(`
    <div class="sheet-head"><h2>Keyboard and gamepad</h2></div>
    <div class="form help">
      <div class="help-cols">
        <div><div class="label">Keyboard</div>${helpRows([
          ["↑ / ↓", "Previous / next game"], ["PgUp / PgDn", "A page up / down"], ["Home / End", "First / last game"],
          ["→ / Del", "Move the game (Keeping list)"], ["←", "Keep the game (Moving list)"], ["Enter", "Flip it to the other list"],
          ["Space", "Mark it; flips then act on all marked games"], ["Tab", "Switch list"], ["Ctrl+Z / Backspace", "Undo"],
          ["/ / Ctrl+F", "Search"], ["S", "Pick a system"], ["Ctrl+R", "Review one at a time"], ["Ctrl+I", "Import ROMs"], ["F5", "Rescan"],
          ["F6 / Shift+F6", "Next / previous part: header, filters, Keeping, Moving, details, buttons"], ["Shift+F10", "The game's menu (hide, LaunchBox match …)"],
          ["Esc", "Close, or clear the search"]])}
          <p class="note">Outside the lists, the arrow keys move between controls and Enter presses them. ↑ on the first game and ↓ on the last leave the list.</p></div>
        <div><div class="label">Gamepad</div>${helpRows([
          ["D-pad ▲ ▼ / Stick", "Move through the list"], ["D-pad ◀ ▶", "Keeping / Moving list"], ["A", "Mark"], ["X", "Flip to the other list"], ["Y", "Undo"],
          ["L1 / R1", "Next / previous part: header, filters, the lists, details, buttons"], ["L2 / R2", "A page up / down"],
          ["Menu (☰)", "☰ menu"], ["View (⧉)", "Search"], ["R3", "The game's menu"], ["Right stick ▲ ▼", "Scroll the details"],
          ["B", "Back, close"]])}
          <p class="note">Outside the lists, the d-pad moves between controls, A presses them and A in a text box opens an on-screen keyboard. The bottom of the window always lists what the buttons do right there, and goes back to keys as soon as you use the mouse or keyboard.</p>
          <p class="note">${S.opts.gamepad ? (pads.length ? `Connected: ${esc(pads.join(", "))}. While you use it, the bottom of the window shows what its buttons do.`
            : "No gamepad found yet: plug one in (or press a button) and it's picked up by itself. On a Steam Deck, Steam keeps the built-in controls while it runs; other pads work.")
            : "The gamepad is off in ☰ → Settings."}</p></div>
      </div>
      <p class="note">Review (Ctrl+R): K or Space keeps · M or Enter moves · S or → skips · ← back · Backspace undoes · Esc closes.</p>
    </div>
    <div class="sheet-foot"><span class="grow"></span><button class="primary" id="k-close">Close</button></div>`, "wide form-sheet");
  $("k-close").onclick = closeSheet;
}

function openPatternHelp() {
  sheet(`
    <div class="sheet-head"><h2>Name patterns</h2><p>Each line is one rule, checked against every game's file name.</p></div>
    <div class="form help">${helpRows([
      ["mario", "Plain text: moves any game whose name contains it, anywhere."],
      ["(Japan) / [b]", "Brackets and parentheses are ordinary characters, so tags like (Japan), (Demo) and [b] match exactly as written."],
      ["*", "Wildcard for any run of characters (including none)."],
      ["?", "Wildcard for exactly one character."],
      ["0002* / *.part / *(USA)*(Rev ?)*", "As soon as a line has * or ?, it must match the whole name. 0002* = starts with 0002, *.part = ends with .part."],
      ["!kart / !*(USA)*", "Lines starting with ! are keep rules: matching games stay, even if a preset, pattern, rating, genre or region would move them."],
      ["# comment", "Lines starting with # are ignored. Blank lines are ignored too."]])}
      <p class="note">Patterns are checked against the game name and each of its file names (with extension), so .nds, .zip or .cue work. Case is ignored unless you untick Ignore case.<br>
      Priority, highest first: flips by hand › Protect played games › games hidden in ES-DE › ! keep rules › everything else that moves a game (presets, patterns, ratings, genres, regions).</p>
    </div>
    <div class="sheet-foot"><span class="grow"></span><button class="primary" id="p-close">Close</button></div>`, "wide form-sheet");
  $("p-close").onclick = closeSheet;
}

$("pattern-help").onclick = () => { closePopovers(); openPatternHelp(); };
