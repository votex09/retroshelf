// Tools that look at the whole ROMs folder: Storage overview, Library health check and Find duplicates.
// (Uses app.js, sheets.js and tools.js: call, runJob, sheet, setProgress …)
"use strict";

registerTool({ cmd: "storage", group: "library", label: "Storage overview…", sub: "space per system, and the biggest games", system: false, open: () => openStorage() });
registerTool({ cmd: "health", group: "library", label: "Health check…", sub: "missing tracks, stray files and artwork", system: false, open: () => openHealth() });
registerTool({ cmd: "dupes", group: "library", label: "Find duplicates…", sub: "games kept twice, identical copies", system: false, open: () => openDupes() });

// Put the main window on a system, and on one of its games (emptying the search box if that hides it).
async function showInMain(system, key) {
  closeSheet();
  if (S.sys?.system !== system) {
    await flushDecide();
    loadSystem(await call("open_system", { system }), key);
    return;
  }
  if (!key || !S.byKey.has(key)) return;
  if (S.query) { S.query = $("search").value = ""; rebuild({ slide: false }); }
  setActive(S.byKey.get(key).move ? "move" : "keep");
  const i = L().indexOf(key);
  if (i >= 0) select(i, false);
}

// The "Look again" button of a sheet that looks through the library: Stop while it's looking.
// run() -> the answer, or null when it was already looking (that click stops it instead).
function looker(btnId, label, method, params, onProgress) {
  const lk = { job: null };
  lk.run = async () => {
    if (lk.job) { lk.job.stop(); $(btnId).disabled = true; return null; }
    $(btnId).textContent = "Stop";
    lk.job = runJob(method, params(), onProgress);
    try {
      return await lk.job.done;
    } finally {
      lk.job = null;
      if ($(btnId)) { $(btnId).disabled = false; $(btnId).textContent = label; }
    }
  };
  lk.stop = () => lk.job?.stop();
  return lk;
}

const share = (f) => `<span class="share"><i style="width:${Math.round(100 * Math.max(0, Math.min(1, f)))}%"></i></span>`;

// ---------- Storage overview ----------
async function openStorage() {
  const T = { systems: [], sel: null };
  sheet(`
    <div class="sheet-head"><h2>Storage overview</h2><p id="st-drive"></p></div>
    <div class="progress-bar drive"><div id="st-drive-bar"></div></div>
    <div class="table storage" id="st-systems"></div>
    <div class="table-label" id="st-games-label">Biggest games</div>
    <div class="table storage-games" id="st-games"></div>
    <div class="sheet-foot"><span class="grow" id="st-status"></span>
      <button class="ghost" id="st-again">Add up again</button><button class="ghost" id="st-close">Close</button>
      <button class="primary" id="st-open">Open in the main window</button></div>`,
  "storage-sheet", () => look.stop(), storageKeys);
  const look = looker("st-again", "Add up again", "storage_scan", () => ({}), (p) => ($("st-status").textContent = p.message));
  $("st-systems").innerHTML = `<div class="none">Adding up …</div>`;

  function fillSystems() {
    const total = T.systems.reduce((n, s) => n + s.total, 0) || 1;
    $("st-systems").innerHTML = `<div class="trow head"><span>System</span><span class="num">Games</span><span class="num">Games' size</span>
      <span class="num" title="ES-DE's artwork, videos and manuals for the system">Media</span><span class="num">Total</span><span></span>
      <span class="num" title="Disc images Tools → Compress games would turn into .chd / .rvz (usually a third to a half smaller)">Could compress</span></div>` +
      (T.systems.length ? T.systems.map((s) => `<div class="trow${s.code === T.sel ? " on" : ""}" data-code="${esc(s.code)}">
        <span class="nm" title="${esc(s.label)}">${esc(s.label)}</span><span class="num">${s.games.toLocaleString()}</span>
        <span class="num">${human(s.size)}</span><span class="num">${s.media ? human(s.media) : "—"}</span><span class="num">${human(s.total)}</span>
        ${share(s.total / total)}<span class="num">${s.compressible ? human(s.compressible) : ""}</span></div>`).join("")
        : `<div class="none">No games here yet.</div>`);
    fillGames();
  }
  function fillGames() {
    const s = T.systems.find((x) => x.code === T.sel);
    $("st-games-label").textContent = s ? `Biggest games in ${s.label}` : "Biggest games";
    $("st-open").disabled = !s;
    if (!s) { $("st-games").innerHTML = ""; return; }
    const top = s.biggest[0]?.[1] || 1;
    $("st-games").innerHTML = `<div class="trow head"><span>Game</span><span class="num">Size</span><span></span></div>` +
      s.biggest.map(([key, size]) => `<div class="trow" data-key="${esc(key)}"><span class="nm" title="${esc(key)}">${esc(key)}</span>
        <span class="num">${human(size)}</span>${share(size / top)}</div>`).join("") +
      (s.more ? `<div class="trow more"><span class="dim">… and ${s.more.toLocaleString()} smaller ones</span></div>` : "");
  }
  function pick(code) {
    T.sel = code;
    for (const r of $("st-systems").querySelectorAll(".trow[data-code]")) r.classList.toggle("on", r.dataset.code === code);
    $("st-systems").querySelector(".trow.on")?.scrollIntoView({ block: "nearest" });
    fillGames();
  }
  storageKeys.hints = { pad: [["dpad", "Choose"], ["x", "Open the system"]],
    keys: [["key", "↑ ↓", "Choose"], ["key", "Enter", "Open the system"]] };
  function storageKeys(key) {
    const i = T.systems.findIndex((s) => s.code === T.sel);
    if (key === "ArrowDown" || key === "ArrowUp") {
      const s = T.systems[Math.max(0, Math.min(T.systems.length - 1, i + (key === "ArrowDown" ? 1 : -1)))];
      if (s) pick(s.code);
      return true;
    }
    if (key === "Enter" && T.sel) { open(); return true; }
    return false;
  }
  const known = (code) => S.overview.systems.some((s) => s.code === code);
  const open = (key) => known(T.sel) && showInMain(T.sel, key).catch(oops);
  async function scan() {
    if (look.job) { look.run(); return; }
    $("st-status").textContent = "Adding up …";
    try {
      const r = await look.run();
      if (!$("st-systems")) return;
      if (r.stopped) { $("st-status").textContent = "Stopped."; return; }
      T.systems = r.systems;
      const has = (c) => T.systems.some((s) => s.code === c);
      T.sel = has(T.sel) ? T.sel : has(S.sys?.system) ? S.sys.system : T.systems[0]?.code ?? null;
      fillSystems();
      $("st-systems").querySelector(".trow.on")?.scrollIntoView({ block: "nearest" });
      const sum = (f) => T.systems.reduce((n, s) => n + s[f], 0), comp = sum("compressible");
      $("st-status").textContent = `${plural(T.systems.length, "system")}: ${human(sum("size"))} of games and ${human(sum("media"))} of media.` +
        (comp ? ` ${human(comp)} of disc images could be compressed (Tools → Compress games).` : "");
      const d = r.drive;
      $("st-drive").textContent = d && d.total ? `The drive with your ROMs: ${human(d.free)} free of ${human(d.total)} (${Math.round(100 * (d.total - d.free) / d.total)}% used)` : "";
      $("st-drive-bar").style.width = d && d.total ? `${100 * (d.total - d.free) / d.total}%` : "0";
    } catch (e) {
      if ($("st-status")) $("st-status").textContent = `Couldn't add up: ${e.message}`;
    }
  }
  $("st-systems").addEventListener("click", (e) => { const r = e.target.closest(".trow[data-code]"); if (r) pick(r.dataset.code); });
  $("st-systems").addEventListener("dblclick", (e) => { if (e.target.closest(".trow[data-code]")) open(); });
  $("st-games").addEventListener("dblclick", (e) => { const r = e.target.closest(".trow[data-key]"); if (r) open(r.dataset.key); });
  $("st-again").onclick = scan;
  $("st-close").onclick = closeSheet;
  $("st-open").onclick = () => open();
  $("st-open").disabled = true;
  scan();
}

// ---------- Library health check ----------
async function openHealth() {
  const H = { problems: [], kinds: [], sel: new Set(), state: {}, touched: new Set() };  // state: id -> "fixed" / "failed"
  const scopes = [["", "All systems"], ...(S.sys ? [[S.sys.system, `${S.sys.fullname} (${S.sys.system})`]] : [])];
  sheet(`
    <div class="sheet-head"><h2>Library health check</h2>
      <p>Things that stop games starting (sheets and playlists naming files that aren't there, disc images without their .cue), and things that take space for nothing (empty files, unfinished downloads, artwork, videos and gamelist entries for games that are gone). Nothing changes until you press Fix.</p></div>
    <div class="sheet-tools">Look at <select id="hc-scope">${scopes.map(([v, l]) => `<option value="${esc(v)}">${esc(l)}</option>`).join("")}</select>
      <button class="ghost small" id="hc-again">Look again</button></div>
    <div class="table health" id="hc-table"></div>
    <div class="tool-progress"><div class="progress-text" id="hc-status"></div><div class="progress-bar"><div id="hc-bar"></div></div></div>
    <div class="sheet-foot"><span class="grow" id="hc-sum"></span><button class="ghost" id="hc-close">Close</button>
      <button class="primary" id="hc-fix" title="Fixes the selected problems that can be fixed, or all of them when nothing is selected. It says what it will do first.">Fix</button></div>`,
  "", () => { look.stop(); if (S.sys && H.touched.has(S.sys.system)) return rescanQuietly(); });
  const look = looker("hc-again", "Look again", "health_scan", () => ({ system: $("hc-scope").value || null }), (p) => setProgress("hc-bar", "hc-status", p));
  const chosen = () => {
    const ids = H.sel.size ? [...H.sel] : H.problems.map((p) => p.id);
    return ids.filter((i) => H.problems[i].fix && !H.state[i]);
  };
  function fill() {
    const heading = Object.fromEntries(H.kinds);
    let html = "", kind = null;
    for (const p of H.problems) {
      if (p.kind !== kind) {
        kind = p.kind;
        const n = H.problems.filter((x) => x.kind === kind).length;
        html += `<div class="trow group" data-kind="${p.kind}"><span>${esc(heading[kind])}  (${n.toLocaleString()})</span></div>`;
      }
      const st = H.state[p.id], on = H.sel.has(p.id);
      html += `<div class="trow${on ? " on" : ""}${p.fix ? "" : " nofix"}${st ? ` ${st}` : ""}" data-id="${p.id}"><input type="checkbox"${on ? " checked" : ""}>
        <span class="nm" title="${esc(p.name)}">${esc(p.name)}</span><span class="dim">${esc(p.system)}</span>
        <span class="dim" title="${esc(p.detail)}">${esc(p.detail)}</span><span class="dim fix">${esc(st === "fixed" ? "Done" : st === "failed" ? "Failed" : p.fix || "—")}</span></div>`;
    }
    $("hc-table").innerHTML = `<div class="trow head"><span></span><span>Problem</span><span>System</span><span></span><span>Fix</span></div>` +
      (html || `<div class="none">Nothing wrong found.</div>`);
    summary();
  }
  function summary() {
    const ids = chosen();
    $("hc-fix").disabled = !ids.length || !!look.job;
    $("hc-fix").textContent = ids.length ? `Fix ${ids.length.toLocaleString()}` : "Fix";
    const freed = ids.reduce((n, i) => n + H.problems[i].frees, 0);
    $("hc-sum").textContent = ids.length ? `${ids.length.toLocaleString()} to fix` + (freed ? `  ·  frees ${human(freed)}` : "") : "";
  }
  async function scan() {
    if (look.job) { look.run(); return; }
    $("hc-status").textContent = "Looking …";
    $("hc-fix").disabled = true;
    try {
      const r = await look.run();
      if (!$("hc-table")) return;
      $("hc-bar").style.width = "0";
      if (r.stopped) { $("hc-status").textContent = "Stopped."; summary(); return; }
      Object.assign(H, { problems: r.problems, kinds: r.kinds, sel: new Set(), state: {} });
      const fixable = H.problems.filter((p) => p.fix).length;
      $("hc-status").textContent = H.problems.length ? `${plural(H.problems.length, "problem")} found, ${fixable.toLocaleString()} that RetroShelf can fix.` : "Nothing wrong found.";
      fill();
    } catch (e) {
      if ($("hc-status")) { $("hc-status").textContent = `Couldn't look: ${e.message}`; summary(); }
    }
  }
  $("hc-table").addEventListener("click", (e) => {
    const row = e.target.closest(".trow[data-id], .trow.group");
    if (!row) return;
    const ids = row.dataset.kind ? H.problems.filter((p) => p.kind === row.dataset.kind).map((p) => p.id) : [Number(row.dataset.id)];
    const on = !ids.every((i) => H.sel.has(i));
    for (const i of ids) on ? H.sel.add(i) : H.sel.delete(i);
    fill();
  });
  $("hc-scope").onchange = () => { if (!look.job) scan(); };
  $("hc-again").onclick = scan;
  $("hc-close").onclick = closeSheet;
  $("hc-fix").onclick = async () => {
    const ids = chosen();
    if (!ids.length || look.job) return;
    try {
      const plan = await call("health_fix_plan", { ids });
      const ok = await confirmBox({ title: "Library health check", ok: "Fix", message: "Fix these?",
        detail: plan.lines.map((l) => `• ${l}`).join("\n") +
          (plan.deletes ? `\n\n${plan.deletes.toLocaleString()} files are deleted for good (artwork and videos can be scraped again).` : "") });
      if (!ok) return;
      const r = await call("health_fix", { ids });
      for (const [i, what] of Object.entries(r.done)) { H.state[i] = "fixed"; H.problems[i].detail = what; }
      for (const i of Object.keys(r.failed)) H.state[i] = "failed";
      r.systems.forEach((s) => H.touched.add(s));
      H.sel.clear();
      if (!$("hc-table")) return;
      fill();
      const n = Object.keys(r.done).length, failed = Object.values(r.failed);
      $("hc-status").textContent = `Fixed ${plural(n, "problem")}.` + (failed.length ? ` ${failed.length.toLocaleString()} couldn't be fixed.` : "");
      if (failed.length) failures(`Fixed ${plural(n, "problem")}, ${failed.length} couldn't be fixed`, failed);
      else if (n) toast(`Library health check: fixed ${plural(n, "problem")}.`);
    } catch (e) { oops(e); }
  };
  scan();
}

// ---------- Find duplicates ----------
const DUPE_KINDS = { formats: "Same game, two forms", copies: "Identical copies" };

async function openDupes() {
  const D = { sets: [], sel: new Set(), done: new Set(), holding: "", same: false, moved: false };  // sel: "s3" sets, "c3-1" copies
  sheet(`
    <div class="sheet-head"><h2>Find duplicates</h2>
      <p>Games kept twice in one folder in different forms (a .cue / .bin and a .chd, a .zip and the ROM inside it …), and identical files anywhere in the library, compared by content (the same game in snes and sfc, or under two names). One copy of each stays: the one ES-DE knows, or the best form. Double-click another copy to keep that one instead. The others go to the holding folder.</p></div>
    <div class="table dupes" id="du-table"></div>
    <div class="tool-progress"><div class="progress-text" id="du-status"></div><div class="progress-bar"><div id="du-bar"></div></div></div>
    <div class="sheet-foot"><span class="grow" id="du-sum"></span>
      <button class="ghost" id="du-again">Look again</button><button class="ghost" id="du-keep">Keep this copy</button>
      <button class="ghost" id="du-close">Close</button>
      <button class="primary" id="du-go" title="For the selected sets, or every set when none is selected: the copies not kept move to the holding folder (Restore a move… puts them back).">Move the extra copies</button></div>`,
  "", () => { look.stop(); if (D.moved) return rescanQuietly(); });
  const look = looker("du-again", "Look again", "dupes_scan", () => ({}), (p) => setProgress("du-bar", "du-status", p));
  const extra = (s) => s.copies.reduce((n, c, i) => n + (i === s.keep ? 0 : c.size), 0);
  const chosen = () => {
    const ids = [...new Set([...D.sel].map((id) => Number(id.slice(1).split("-")[0])))];
    return (ids.length ? ids : D.sets.map((s) => s.id)).filter((i) => !D.done.has(i));
  };
  function fill() {
    $("du-table").innerHTML = `<div class="trow head"><span>Game</span><span></span><span>System</span><span>Form</span><span class="num">Size</span></div>` +
      (D.sets.length ? D.sets.map((s) => {
        const done = D.done.has(s.id) ? " done" : "";
        return `<div class="trow set${D.sel.has(`s${s.id}`) ? " on" : ""}${done}" data-id="s${s.id}"><span class="nm" title="${esc(s.title)}">${esc(s.title)}</span>
          <span class="dim">${DUPE_KINDS[s.kind]}</span><span></span><span class="dim">${s.copies.length} copies</span><span class="num dim">${done ? "done" : `${human(extra(s))} extra`}</span></div>` +
          (done ? "" : s.copies.map((c, i) => `<div class="trow copy${D.sel.has(`c${s.id}-${i}`) ? " on" : ""}" data-id="c${s.id}-${i}">
            <span class="nm" title="${esc(c.rel)}">${esc(c.rel)}</span><span class="${i === s.keep ? "keep" : "go"}">${i === s.keep ? "✓ Keep" : "→ Holding folder"}</span>
            <span class="dim">${esc(c.system)}</span><span class="dim">${esc(c.fmt)}</span><span class="num">${human(c.size)}</span></div>`).join(""));
      }).join("") : `<div class="none">No duplicates found.</div>`);
    summary();
  }
  function summary() {
    const ids = chosen();
    $("du-keep").disabled = ![...D.sel].some((id) => id[0] === "c" && !D.done.has(Number(id.slice(1).split("-")[0])));
    $("du-go").disabled = !ids.length || !!look.job;
    const bytes = ids.reduce((n, i) => n + extra(D.sets[i]), 0);
    $("du-sum").textContent = ids.length ? `${plural(ids.length, "game")}  ·  frees ${human(bytes)}` : "";
  }
  function keepSelected() {
    for (const id of D.sel) {
      if (id[0] !== "c") continue;
      const [sid, i] = id.slice(1).split("-").map(Number);
      if (!D.done.has(sid)) D.sets[sid].keep = i;
    }
    fill();
  }
  async function scan() {
    if (look.job) { look.run(); return; }
    $("du-status").textContent = "Looking …";
    $("du-go").disabled = $("du-keep").disabled = true;
    try {
      const r = await look.run();
      if (!$("du-table")) return;
      $("du-bar").style.width = "0";
      if (r.stopped) { $("du-status").textContent = "Stopped."; summary(); return; }
      Object.assign(D, { sets: r.sets, holding: r.holding, same: r.same_drive, sel: new Set(), done: new Set() });
      const bytes = D.sets.reduce((n, s) => n + extra(s), 0);
      $("du-status").textContent = D.sets.length ? `${plural(D.sets.length, "game")} with duplicates: ${human(bytes)} in the copies that would go.` : "No duplicates found.";
      fill();
    } catch (e) {
      if ($("du-status")) { $("du-status").textContent = `Couldn't look: ${e.message}`; summary(); }
    }
  }
  $("du-table").addEventListener("click", (e) => {
    const row = e.target.closest(".trow[data-id]");
    if (!row || row.classList.contains("done")) return;
    D.sel.has(row.dataset.id) ? D.sel.delete(row.dataset.id) : D.sel.add(row.dataset.id);
    row.classList.toggle("on", D.sel.has(row.dataset.id));  // (not fill(): a double-click needs the row it started on)
    summary();
  });
  $("du-table").addEventListener("dblclick", (e) => {
    const row = e.target.closest(".trow.copy");
    if (!row) return;
    D.sel = new Set([row.dataset.id]);
    keepSelected();
  });
  $("du-again").onclick = scan;
  $("du-keep").onclick = keepSelected;
  $("du-close").onclick = closeSheet;
  $("du-go").onclick = async () => {
    const ids = chosen();
    if (!ids.length || look.job) return;
    const sets = ids.map((i) => D.sets[i]), n = sets.reduce((k, s) => k + s.copies.length - 1, 0);
    const ok = await confirmBox({ title: "Find duplicates", ok: "Move",
      message: `Move ${n.toLocaleString()} extra cop${n === 1 ? "y" : "ies"} of ${plural(sets.length, "game")} (${human(sets.reduce((k, s) => k + extra(s), 0))}) into ${D.holding}?`,
      detail: D.same ? "The holding folder is on the same drive: the space comes back when you delete them there." : "" });
    if (!ok) return;
    try {
      const r = await call("dupes_resolve", { keep: Object.fromEntries(sets.map((s) => [s.id, s.keep])) });
      r.sets.forEach((i) => D.done.add(i));
      if (r.moved) D.moved = true;
      D.sel.clear();
      if (!$("du-table")) return;
      fill();
      $("du-status").textContent = r.moved ? `Moved the extra copies of ${plural(r.sets.length, "game")}.` : "Nothing moved.";
      if (r.problems.length) failures(`Moved ${plural(r.moved, "duplicate file")}, ${r.problems.length} problems`, r.problems);
      else if (r.moved) toast(`Moved ${plural(r.moved, "duplicate file")} to the holding folder.`);
    } catch (e) { oops(e); }
  };
  scan();
}
