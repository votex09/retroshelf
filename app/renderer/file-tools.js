// Tools that work on the files themselves: Compress games and Import ROMs. (Uses app.js, sheets.js and tools.js:
// call, runJob, sheet, setProgress …; the work is in app/helper/tool_files.py.)
"use strict";

registerTool({ cmd: "compress", group: "console", label: "Compress games…", sub: "disc images to CHD / RVZ, originals held", system: true, open: () => openCompress() });
registerTool({ cmd: "import", group: "library", key: "Ctrl+I", label: "Import ROMs…", sub: "file new games into the ROMs folder, or copy them from a home server", system: false, open: () => openImport() });

// Clicking a row picks it (again: unpicks it). rows: the .trow elements with data-id; sel: a Set of ids.
function pickRows(table, sel, parse, changed) {
  table.addEventListener("click", (e) => {
    const row = e.target.closest(".trow[data-id]");
    if (!row) return;
    const id = parse(row.dataset.id);
    sel.has(id) ? sel.delete(id) : sel.add(id);
    changed();
  });
}

// ---------- Compress games ----------
async function openCompress() {
  const info = await call("compress_info");
  const name = S.sys.fullname;
  if (!info.supported) {
    overlay(`<h2>Nothing to compress here</h2><p>RetroShelf compresses disc images for CD systems (PlayStation, Saturn, Dreamcast, Sega CD, PC Engine CD …), PS2, GameCube and Wii. ${esc(name)} isn't one of them${info.listed ? ", or its ES-DE folder doesn't list the format." : "."}</p>`,
      [["OK", closeOverlay, true]]);
    return;
  }
  const C = { info, sel: new Set(), results: new Map(), tool: null, job: null, ran: false };
  sheet(`
    <div class="sheet-head"><h2>Compress ${esc(name)} games to ${info.format}</h2>
      <p>${info.ext === ".chd" ? "Disc images become CHD files (MAME's compressed format)" : "Disc images become RVZ files (Dolphin's compressed format)"}: usually a third to a half smaller, and read by the emulators RetroDECK and ES-DE use for this system. Each new file is written next to the game and checked before it replaces anything; playlists (.m3u), ES-DE's gamelist entry and artwork follow it. Pick games to compress only those.</p></div>
    <p class="note tool-line" id="c-tool">Looking for the tools …</p>
    <div class="table compress" id="c-table"></div>
    <div class="job-progress"><div class="progress-bar"><div id="c-bar"></div></div><div class="progress-text" id="c-status"></div></div>
    <div class="sheet-tools">
      <label class="check" title="Reads the new file back through the tool and compares it with what was written. It takes about as long again; without it, a game is replaced as soon as it's written."><input type="checkbox" id="c-verify"${info.verify ? " checked" : ""}> Check each new file before it replaces the original</label>
      <label class="check" title="Originals go to ${esc(info.holding)}, where ☰ → Moved games → Holding folder deletes them for good (or Restore a move puts them back)."><input type="checkbox" id="c-delete"${info.delete ? " checked" : ""}> Delete the originals (instead of moving them to the holding folder)</label>
    </div>
    <div class="sheet-foot"><span class="grow" id="c-sum"></span><button class="ghost" id="c-close">Close</button><button class="primary" id="c-go" disabled>Compress</button></div>`,
  "", () => {
    if (C.job) { C.job.stop(); C.job.done.finally(() => rescanQuietly().catch(oops)); }  // what's done is still logged
    else if (C.ran) rescanQuietly();
  });
  const chosen = () => {
    const picked = C.info.rows.filter((r) => C.sel.has(r.key));
    return picked.length ? picked : C.info.rows;
  };
  function fill() {
    const result = (key) => {
      const r = C.results.get(key);
      return r ? `<span class="nm ${r.tag}" title="${esc(r.text)}">${esc(r.text)}</span>` : null;
    };
    const rows = C.info.rows.map((r) => `<div class="trow${C.sel.has(r.key) ? " on" : ""}" data-id="${esc(r.key)}"><input type="checkbox"${C.sel.has(r.key) ? " checked" : ""}>
        <span class="nm" title="${esc(r.key)}">${esc(r.key)}</span><span class="dim">${esc(r.now)}</span><span class="num">${human(r.size)}</span>
        ${result(r.key) || `<span class="dim">→ ${C.info.format}${r.discs > 1 ? ` (${r.discs} discs)` : ""}</span>`}</div>`);
    const skipped = C.info.skipped.map((r) => `<div class="trow skip"><span></span><span class="nm dim" title="${esc(r.key)}">${esc(r.key)}</span><span></span><span></span>
        ${result(r.key) || `<span class="dim">${esc(r.why)}</span>`}</div>`);
    $("c-table").innerHTML = `<div class="trow head"><span></span><span>Game</span><span>Now</span><span class="num">Size</span><span></span></div>` +
      (rows.length + skipped.length ? rows.concat(skipped).join("") : `<div class="none">Nothing here to compress.</div>`);
    summary();
  }
  function summary() {
    const keys = chosen(), size = keys.reduce((n, r) => n + r.size, 0);
    $("c-sum").textContent = !C.info.rows.length ? "Nothing here to compress." :
      `${C.sel.size ? `${keys.length.toLocaleString()} picked` : plural(keys.length, "game")}  ·  ${human(size)}`;
    if (C.job) return;
    $("c-go").textContent = keys.length ? `Compress ${plural(keys.length, "game")}` : "Compress";
    $("c-go").disabled = !keys.length || !C.tool?.where;
  }
  pickRows($("c-table"), C.sel, String, () => { if (!C.job) fill(); });
  const saveOpts = () => call("compress_options", { verify: $("c-verify").checked, delete: $("c-delete").checked }).catch(oops);
  $("c-verify").onchange = saveOpts;
  $("c-delete").onchange = saveOpts;
  $("c-close").onclick = closeSheet;
  const askStop = async () => {  // closing while it works (Close, Esc, a click outside) asks first
    if (!await confirmBox({ title: "Compress games", ok: "Stop", message: "Stop compressing?", detail: "The game being compressed now stays as it was." })) return;
    sheetBusy = null;
    closeSheet();
  };
  $("c-go").onclick = async () => {
    if (C.job) { C.job.stop(); $("c-go").disabled = true; $("c-status").textContent = "Stopping after the tool lets go …"; return; }
    const keys = chosen().map((r) => r.key), size = chosen().reduce((n, r) => n + r.size, 0);
    if (!keys.length) return;
    const del = $("c-delete").checked;
    const where = del ? "The originals are deleted once each new file is in place." :
      `The originals move to\n${C.info.holding}/` + (C.info.same_drive ? "\n(on the same drive: the space comes back when you delete them there)." : "");
    if (!await confirmBox({ title: "Compress games", ok: "Compress", message: `Compress ${plural(keys.length, "game")} (${human(size)})?`,
      detail: `${where}\n\nBig discs take a few minutes each.` })) return;
    $("c-go").textContent = "Stop";
    $("c-status").textContent = "Starting …";
    sheetBusy = askStop;
    C.job = runJob("compress_games", { keys, verify: $("c-verify").checked, delete: del }, (p) => {
      if (p.key == null) { setProgress("c-bar", "c-status", p); return; }
      C.results.set(p.key, { text: p.result, tag: p.tag });
      if ($("c-table")) fill();
    });
    try {
      const r = await C.job.done;
      C.ran = true;
      if (!$("c-table")) return;
      sheetBusy = null;
      $("c-bar").style.width = "0";
      $("c-status").textContent = (r.stopped ? "Stopped. " : "") + (r.games ? `Compressed ${plural(r.games, "game")}, saving ${human(r.saved)}.` : "Nothing was compressed.");
      C.job = null;
      await rescanQuietly();  // the main window has the new files; and so does the list
      C.info = await call("compress_info");
      C.ran = false;
      const listed = new Set(C.info.rows.map((x) => x.key));
      C.sel = new Set([...C.sel].filter((k) => listed.has(k)));
      fill();
      if (r.games) toast(`Compressed ${plural(r.games, "game")}, saving ${human(r.saved)}.${r.held ? " The originals are in the holding folder (☰ → Moved games → Holding folder)." : ""}`);
      if (r.problems.length) failures(`${r.problems.length === 1 ? "A problem" : `${r.problems.length} problems`} while compressing`, r.problems);
    } catch (e) {
      if ($("c-status")) $("c-status").textContent = `Failed: ${e.message}`;
    }
    C.job = null;
    if ($("c-go")) { sheetBusy = null; summary(); }
  };
  fill();
  try {
    C.tool = await call("compress_tool");
    if (!$("c-tool")) return;
    $("c-tool").textContent = C.tool.where ? `Using ${C.tool.name} from ${C.tool.where}.` : `${C.tool.name} isn't installed, so nothing can be compressed yet. ${C.tool.hint}`;
    $("c-tool").classList.toggle("warn", !C.tool.where);
    summary();
  } catch (e) { oops(e); }
}

// ---------- Import ROMs ----------
// Importing and copying from a source go on when the window closes: one at a time, shown in the main window's footer
// (#bg-job, which opens the window again) until it's done. The window picks it back up when it opens.
const BG = { kind: null, job: null, message: "", done: 0, total: 0, view: null };
const SRC_Q = { queue: [], states: new Map(), qsel: new Set() };  // the Sources queue, kept while the window's closed
function bgStart(kind, method, params, finish) {
  Object.assign(BG, { kind, message: "", done: 0, total: 0 });
  BG.job = runJob(method, params, (p) => {
    if (p.key && p.state) SRC_Q.states.set(p.key, p.state);
    if (p.message) BG.message = p.message;
    if (p.total) { BG.done = p.done; BG.total = p.total; }
    bgShow();
    BG.view?.(p);
  });
  const job = BG.job;
  job.done.then(async (r) => {
    BG.job = BG.kind = null;
    bgShow();
    if (finish(r)) {  // games went in: new system folders show up, and the open system's new games
      S.overview = await call("startup");
      if (S.sys && r.systems.includes(S.sys.system)) await rescanQuietly();
    }
  }, (e) => {
    BG.job = BG.kind = null;
    bgShow();
    if (!BG.view) toast(`${kind === "sources" ? "Copying" : "Importing"} failed: ${e.message}`, { error: true });
  }).catch(oops);
  bgShow();
  return job;
}
function bgShow() {
  const b = $("bg-job");
  b.hidden = !BG.job;
  if (!BG.job) return;
  const text = BG.message || (BG.kind === "sources" ? "Adding games to your library …" : "Importing …");
  b.querySelector(".bg-text").textContent = text;
  b.title = `${text}\nOpen Import ROMs`;
  b.querySelector(".progress-bar > span").style.width = `${BG.total ? (100 * BG.done) / BG.total : 0}%`;
}
$("bg-job").onclick = () => {
  try { localStorage.setItem("import-page", BG.kind === "sources" ? "sources" : "folder"); } catch { /* fine */ }
  openImport().catch(oops);
};
const bgBusy = (kind) => {  // the other page's job is still going
  if (!BG.job || BG.kind === kind) return false;
  toast(BG.kind === "sources" ? "Wait for the copying from the source to finish" : "Wait for the import to finish", { error: true });
  return true;
};
// Two pages: the import folder, and sources (folders to copy games from, like a home server's share).
function importTabs(on) {
  return `<div class="head-row import-tabs"><h2>Import ROMs</h2>
    <button class="tab${on === "folder" ? " on" : ""}" id="i-tab-folder">Import folder</button>
    <button class="tab${on === "sources" ? " on" : ""}" id="i-tab-sources">Sources</button></div>`;
}
function wireImportTabs(on) {
  const go = (page) => async () => {
    if (page === on) return;
    closeSheet();
    try { localStorage.setItem("import-page", page); } catch { /* fine */ }
    (page === "sources" ? openSources : openImport)(true).catch(oops);
  };
  $("i-tab-folder").onclick = go("folder");
  $("i-tab-sources").onclick = go("sources");
}

async function openImport(stay) {
  if (!S.overview?.roms) { toast("Pick your ROMs folder first", { error: true }); return; }
  let page = null;
  try { page = localStorage.getItem("import-page"); } catch { /* fine */ }
  if (!stay && page === "sources") { openSources(true).catch(oops); return; }
  const info = await call("import_info");
  const I = { list: info, inbox: info.inbox, sel: new Set(), job: null, scanning: 0, watching: false, timer: null };
  sheet(`
    <div class="sheet-head">${importTabs("folder")}
      <p>Put games in the import folder (or add them from anywhere): ROM files, disc images and zip / 7z / rar archives, as they are. RetroShelf works out which system each one is for, unpacks it, and files it into your ROMs folder in a form the emulators read. Check the systems below, change any that are wrong, then press Add to Library. It keeps going if you close this window.</p></div>
    <div class="sheet-tools">
      <span>Import folder</span><span class="dim inbox-path" id="i-inbox" title="Files put here are moved into your ROMs folder when imported. RetroShelf notices new ones while this window is open."></span>
      <button class="ghost small" id="i-open">Open folder</button><button class="ghost small" id="i-change">Change…</button>
    </div>
    <div class="sheet-tools">
      <button class="ghost small" id="i-files">Add files…</button><button class="ghost small" id="i-folder">Add a folder…</button>
      <button class="ghost small" id="i-remove">Remove from list</button>
      <span class="grow"></span>
      <span>System for the picked games</span>
      <select id="i-system"><option value="">Detected</option>${info.systems.map((s) => `<option value="${esc(s.code)}">${esc(s.label)} (${esc(s.code)})</option>`).join("")}</select>
      <button class="ghost small" id="i-set">Set</button>
    </div>
    <div class="table imports" id="i-table"></div>
    <div class="job-progress"><div class="progress-bar"><div id="i-bar"></div></div><div class="progress-text" id="i-status"></div></div>
    <div class="sheet-foot">
      <label class="check" title="Games in the import folder are always moved out of it. Games added with Add files / Add a folder are copied, leaving the originals, unless this is ticked."><input type="checkbox" id="i-delete"${info.delete ? " checked" : ""}> Also delete the originals of games added from other folders</label>
      <span class="grow"></span><button class="ghost" id="i-close">Close</button><button class="primary" id="i-go">Add to Library</button></div>`,
  "", () => {  // (an import keeps going: see BG)
    clearInterval(I.timer);
    BG.view = null;
  }, folderKeys);
  // Start (F10) is the Add to Library / Stop button
  function folderKeys() { return false; }
  folderKeys.start = () => $("i-go").click();
  folderKeys.startText = () => (I.job ? "Stop" : "Add to Library");
  function fill() {
    const rows = I.list.rows;
    for (const id of I.sel) if (!rows.some((r) => r.id === id)) I.sel.delete(id);
    $("i-inbox").textContent = I.inbox;
    $("i-table").innerHTML = `<div class="trow head"><span></span><span>Game</span><span>System</span><span>Found by</span><span class="num">Size</span><span>Status</span></div>` +
      (rows.length ? rows.map((r) => `<div class="trow ${r.tag}${I.sel.has(r.id) ? " on" : ""}" data-id="${r.id}"><input type="checkbox"${I.sel.has(r.id) ? " checked" : ""}>
        <span class="nm" title="${esc(r.name)}">${esc(r.name)}</span><span class="nm sys" title="${esc(r.system)}">${esc(r.system)}</span>
        <span class="dim">${esc(r.how)}</span><span class="num">${r.size ? human(r.size) : ""}</span>
        <span class="nm st" title="${esc(r.status)}">${esc(r.status)}</span></div>`).join("") :
        `<div class="none">The import folder is empty.</div>`);
    buttons();
  }
  function buttons() {
    const n = I.list.ready;
    $("i-go").textContent = I.job ? "Stop" : n ? `Add ${plural(n, "game")} to Library` : "Add to Library";
    if (!I.job) $("i-go").disabled = !n || I.scanning > 0;
    for (const id of ["i-files", "i-folder", "i-remove", "i-set", "i-change"]) $(id).disabled = !!I.job;
    if (I.job) return;
    $("i-status").textContent = I.scanning ? "Looking at what's in the list …" :
      !I.list.rows.length ? "Nothing to import yet: put games in the import folder, or press Add files." :
      I.list.unknown ? `${I.list.unknown} can't be placed: pick them and choose their system.` : "Ready.";
  }
  function syncSystem() {  // the picked rows' system, when they all have the same one picked by hand
    const picks = new Set(I.list.rows.filter((r) => I.sel.has(r.id)).map((r) => r.override));
    $("i-system").value = picks.size === 1 && !picks.has(null) ? [...picks][0] : "";
  }
  const show = (list) => { if (list && $("i-table")) { I.list = list; fill(); } };
  async function scan(list) {  // new rows come as Checking …: list them, then look inside
    show(list);
    I.scanning++;
    buttons();
    try { show(await call("import_scan")); } finally { I.scanning--; if ($("i-table")) buttons(); }
  }
  wireImportTabs("folder");
  pickRows($("i-table"), I.sel, Number, () => { fill(); syncSystem(); });
  $("i-open").onclick = () => rs.openFolder(I.inbox).then((err) => err && toast(`Couldn't open ${I.inbox}: ${err}`, { error: true }));
  $("i-change").onclick = async () => {
    const path = await pickFolder(I.inbox, "Import folder");
    if (!path) return;
    try {
      const r = await call("import_set_inbox", { path });
      I.inbox = r.inbox;
      await scan(r);
    } catch (e) { oops(e); }
  };
  $("i-files").onclick = async () => {
    const paths = await pickFiles(info.home, "Add games");
    if (!paths.length) return;
    try { await scan(await call("import_add", { paths })); } catch (e) { oops(e); }
  };
  $("i-folder").onclick = async () => {
    const path = await pickFolder(info.home, "Add a folder of games");
    if (!path) return;
    try {
      const p = await call("import_folder", { path });
      if (!p.games) {
        overlay(`<h2>Nothing to add</h2><p>There are no games or archives in ${esc(path)} (or they're already in the list).</p>`, [["OK", closeOverlay, true]]);
        return;
      }
      const where = p.folders > 1 ? ` in ${p.folders} folders` : "";
      if (!await confirmBox({ title: "Import ROMs", ok: "Add", message: `Add ${plural(p.games, "game")}${where} from\n\n${path}${p.folders > 1 ? " (and the folders inside it)" : ""}?`,
        detail: "They're copied: the originals stay where they are." })) return;
      await scan(await call("import_add_folder"));
    } catch (e) { oops(e); }
  };
  $("i-remove").onclick = async () => {
    if (I.sel.size) show(await call("import_remove", { ids: [...I.sel] }).catch(oops));
  };
  $("i-set").onclick = async () => {
    if (I.sel.size) show(await call("import_set_system", { ids: [...I.sel], system: $("i-system").value || null }).catch(oops));
  };
  $("i-delete").onchange = () => call("import_options", { delete: $("i-delete").checked }).catch(oops);
  $("i-close").onclick = closeSheet;
  $("i-go").onclick = () => {
    if (I.job) { I.job.stop(); $("i-go").disabled = true; $("i-status").textContent = "Stopping …"; return; }
    if (!I.list.ready || bgBusy("folder")) return;
    bgStart("folder", "import_run", { delete: $("i-delete").checked }, (r) => {
      if (r.imported) toast(`Imported ${plural(r.imported, "game")}${r.systems.length ? ` into ${r.systems.join(", ")}` : ""}.`);
      return r.imported > 0;
    });
    follow().catch(oops);
  };
  async function follow() {  // the import going on (just started, or still going from before the window closed)
    I.job = BG.job;
    BG.view = (p) => {
      if (!$("i-table")) return;
      if (p.row) {
        I.list.rows = I.list.rows.map((r) => (r.id === p.row.id ? p.row : r));
        fill();
      } else {
        $("i-bar").style.width = `${p.total ? (100 * p.done) / p.total : 0}%`;
        if (p.message) $("i-status").textContent = p.message;
      }
    };
    buttons();
    $("i-bar").style.width = `${BG.total ? (100 * BG.done) / BG.total : 0}%`;
    if (BG.message) $("i-status").textContent = BG.message;
    let r;
    try { r = await I.job.done; } catch (e) {
      I.job = null;
      if ($("i-status")) { buttons(); $("i-status").textContent = `Failed: ${e.message}`; }
      return;
    }
    I.job = null;
    if (!$("i-table")) return;
    $("i-bar").style.width = "0";
    show(r);
    if (r.imported) $("i-status").textContent = `${r.stopped ? "Stopped. " : ""}Imported ${r.imported.toLocaleString()} — they're in your ROMs folder now.${r.scraped ? `  ${r.scraped}.` : ""}`;
  }
  // new files in the import folder show up while the window is open
  I.timer = setInterval(async () => {
    if (I.watching || I.job || I.scanning) return;
    I.watching = true;
    try { const list = await call("import_watch"); if (list) await scan(list); } catch (e) { console.error(e); } finally { I.watching = false; }
  }, 2000);
  if (BG.kind === "folder") { show(info); follow().catch(oops); } else await scan(info);
}

// ----- sources: folders to copy games from (a home server's share mounted here, another drive …) -----
async function openSources() {
  if (!S.overview?.roms) { toast("Pick your ROMs folder first", { error: true }); return; }
  const saved = await call("source_list");
  const C = { saved, path: null, list: null, sel: null, job: null, seq: 0, timer: null };
  const Q = SRC_Q;
  const pick = (saved.sources.find((x) => x.path === saved.last) || saved.sources[0])?.path || null;
  sheet(`
    <div class="src-layout">
      <div class="src-left">
        <div class="sheet-head">${importTabs("sources")}
          <p>Copy games from another folder, like a home server's share mounted here. They're filed like imports; the source is never changed.</p></div>
        <div class="sheet-tools">
          <select id="c-source"></select><select id="c-system"><option value="">All systems</option></select>
          <button class="ghost small" id="c-add">Add source…</button><button class="ghost small" id="c-forget">Remove source</button>
          <button class="ghost small" id="c-refresh">Look again</button>
        </div>
        <div class="sheet-tools">
          <input type="search" id="c-q" placeholder="Search" spellcheck="false">
          <label class="check"><input type="checkbox" id="c-hide"> Hide ones I have</label>
        </div>
        <div class="nps-main"><div class="results-line" id="c-res"></div><div class="table nps-rows src-rows" id="c-table"></div></div>
        <div class="sheet-foot"><span class="grow"></span><button class="ghost" id="c-close">Close</button><button class="primary" id="c-start">Add to Library</button></div>
      </div>
      <aside class="nps-side src-side">
        <div class="nps-pick"><div class="nps-media" id="c-media" hidden></div><div id="c-pick"></div></div>
        <button class="ghost" id="c-addq">Add to queue</button>
        <div class="nps-qhead"><b id="c-qhead">Queue</b><span class="muted" id="c-qsize"></span><span class="grow"></span><button class="ghost small" id="c-remove">Remove</button></div>
        <div class="table nps-queue" id="c-queue"></div>
        <div class="progress-bar"><div id="c-bar"></div></div><div class="progress-text" id="c-status"></div>
      </aside>
    </div>`,
  "stores-sheet nps", () => {
    C.art.stop();
    BG.view = null;  // (a copy keeps going: see BG)
  }, srcKeys);
  C.art = artBox("c-media", (row) => call("source_art", { key: row.key }),
    (row) => ({ title: row.name.replace(/\s*[([][^)\]]*[)\]]/g, ""), console: row.label }));
  const status = (text) => { if ($("c-status")) $("c-status").textContent = text; };
  function fillSources() {
    $("c-source").innerHTML = C.saved.sources.length
      ? C.saved.sources.map((x) => `<option value="${esc(x.path)}"${x.path === C.path ? " selected" : ""}>${esc(x.label)}${x.here ? "" : "  (can't reach it)"}</option>`).join("")
      : `<option value="">No sources yet: press Add source</option>`;
    $("c-source").title = C.path || "";
    $("c-forget").disabled = $("c-refresh").disabled = !C.path || !!C.job;  // (not while copying from it)
    $("c-source").disabled = $("c-add").disabled = !!C.job;
  }
  async function open(path, refresh = false) {
    C.path = path;
    C.list = null;
    C.sel = null;
    fillSources();
    fillRows();
    if (!path) { status(""); return; }
    status(refresh ? "Looking through the source again …" : "Opening the source …");
    $("c-refresh").disabled = true;
    try {
      const r = await runJob("source_open", { path, refresh }, (p) => status(p.message)).done;
      if (path !== C.path || !$("c-table")) return;
      const keep = $("c-system").value;
      $("c-system").innerHTML = `<option value="">All systems</option>` + r.systems.map(([c, l]) => `<option value="${esc(c)}"${c === keep ? " selected" : ""}>${esc(l)}</option>`).join("");
      status(!r.total ? "No games found in this source." : C.job ? BG.message : "");
      await rows();
    } catch (e) { if (path === C.path) status(`Couldn't open it: ${e.message}`); }
    if ($("c-refresh")) $("c-refresh").disabled = !C.path || !!C.job;
  }
  async function rows() {
    if (!C.path) return;
    const n = ++C.seq;
    try {
      const r = await call("source_rows", { system: $("c-system").value, query: $("c-q").value, hide_have: $("c-hide").checked,
        queued: Object.fromEntries(Q.states) });
      if (n !== C.seq || !$("c-table")) return;
      C.list = r;
      fillRows();
    } catch (e) { oops(e); }
  }
  function fillRows() {
    const r = C.list;
    if (r && !r.rows.some((x) => x.key === C.sel)) C.sel = null;
    $("c-table").innerHTML = `<div class="trow head"><span>Name</span><span>System</span><span class="num">Size</span><span>Status</span></div>` +
      (!r ? `<div class="none">${C.path ? "Opening …" : "Add a source to see its games."}</div>`
        : r.rows.length ? r.rows.map((x) => `<div class="trow${x.key === C.sel ? " on" : ""}" data-key="${esc(x.key)}">
        <span class="nm" title="${esc(x.key)}">${esc(x.name)}</span><span class="dim nm">${esc(x.label)}</span>
        <span class="num">${human(x.size)}</span><span class="dim ${stateClass(x.status)}">${esc(x.status)}</span></div>`).join("")
          : `<div class="none">Nothing matches.</div>`);
    $("c-res").textContent = r ? `${r.shown.toLocaleString()} of ${r.total.toLocaleString()} games` +
      (r.rows.length < r.shown ? ` (the first ${r.rows.length.toLocaleString()} shown: search to narrow it down)` : "") : "";
    showPick();
  }
  const stateClass = (st) => (st === "Done" || st === "In library" ? "st-ok" : st.startsWith("Failed") ? "st-bad" : st ? "st-have" : "");
  function showPick() {
    const row = C.list?.rows.find((x) => x.key === C.sel) || null;
    $("c-pick").innerHTML = row ? `<h3>${esc(row.name)}</h3><p class="muted" title="${esc(row.key)}">${esc(row.label)}  ·  ${human(row.size)}</p>${row.status ? `<p class="${stateClass(row.status)}">${esc(row.status)}</p>` : ""}`
      : `<p class="muted">Pick a game to see it here. Space or Enter adds it to the queue.</p>`;
    $("c-addq").disabled = !row;
    C.art.show(row);
  }

  // ----- the queue -----
  function enqueue(key) {
    const row = C.list?.rows.find((x) => x.key === key);
    if (!row) return;
    const st = Q.states.get(key);
    if (st && !st.startsWith("Failed")) return;
    if (!Q.queue.some((q) => q.key === key)) Q.queue.push(row);
    Q.states.set(key, "Queued");
    fillQueue();
    rows();
  }
  function dequeue(keys) {
    for (const k of keys) {
      if (Q.states.get(k) === "Copying") continue;
      Q.queue = Q.queue.filter((q) => q.key !== k);
      Q.states.delete(k);
      Q.qsel.delete(k);
    }
    fillQueue();
    rows();
  }
  function fillQueue() {
    if (!$("c-queue")) return;
    $("c-queue").innerHTML = Q.queue.length ? Q.queue.map((q) => `<div class="trow${Q.qsel.has(q.key) ? " on" : ""}" data-key="${esc(q.key)}">
      <span class="nm" title="${esc(q.key)}">${esc(q.name)}</span><span class="num">${human(q.size)}</span>
      <span class="dim ${stateClass(Q.states.get(q.key) || "")}" data-state>${esc(Q.states.get(q.key) || "")}</span></div>`).join("")
      : `<div class="none">Nothing queued yet.</div>`;
    const pending = Q.queue.filter((q) => Q.states.get(q.key) === "Queued");
    $("c-qhead").textContent = pending.length ? `Queue: ${pending.length} waiting` : "Queue";
    $("c-qsize").textContent = pending.length ? human(pending.reduce((n, q) => n + q.size, 0)) : "";
    $("c-remove").disabled = !Q.queue.length || !!C.job;
  }
  function start() {
    if (C.job) { C.job.stop(); $("c-start").disabled = true; $("c-start").textContent = "Stopping…"; return; }
    const keys = Q.queue.filter((q) => Q.states.get(q.key) === "Queued").map((q) => q.key);
    if (!keys.length) { status("The queue is empty: pick games and press Add to queue."); return; }
    if (bgBusy("sources")) return;
    bgStart("sources", "source_copy", { keys }, (r) => {
      for (const [k, v] of Object.entries(r.states)) Q.states.set(k, v);
      if (r.copied) toast(`Copied ${plural(r.copied, "game")} into your library.`);
      return r.copied > 0;
    });
    follow().catch(oops);
  }
  async function follow() {  // the copy going on (just started, or still going from before the window closed)
    C.job = BG.job;
    $("c-start").textContent = "Stop";
    fillSources();
    fillQueue();
    $("c-bar").style.width = `${BG.total ? (100 * BG.done) / BG.total : 0}%`;
    if (BG.message) status(BG.message);
    BG.view = (p) => {
      if (!$("c-queue")) return;
      if (p.key && p.state) {
        const cell = document.querySelector(`#c-queue .trow[data-key="${CSS.escape(p.key)}"] [data-state]`);
        if (cell) { cell.textContent = p.state; cell.className = `dim ${stateClass(p.state)}`; }
      }
      if (p.message) status(p.message);
      if (p.total) $("c-bar").style.width = `${(100 * p.done) / p.total}%`;
    };
    try {
      const r = await C.job.done;
      const failed = Object.values(r.states).filter((v) => v.startsWith("Failed")).length;
      status(`${r.stopped ? "Stopped. " : ""}Copied ${plural(r.copied, "game")}${r.systems.length ? ` into roms/${r.systems.join(", roms/")}` : ""}` +
        (failed ? `, ${failed} failed` : "") + "." + (r.scraped ? `  ${r.scraped}.` : ""));
    } catch (e) { status(`Failed: ${e.message}`); }
    C.job = null;
    if (!$("c-start")) return;
    $("c-start").disabled = false;
    $("c-start").textContent = "Add to Library";
    fillSources();
    fillQueue();
    rows();
  }

  // ----- keys: A (Space) or X (Enter) queues the game, Y takes it off; in the queue A picks, Y takes the picked off -----
  const inQueue = (el) => Boolean(el?.closest("#c-queue"));
  srcKeys.hints = (el) => (inQueue(el)
    ? { pad: [["dpad", "Choose"], ["a", "Pick"], ["y", "Take off the queue"]],
      keys: [["key", "↑ ↓", "Choose"], ["key", "Space", "Pick"], ["key", "Backspace", "Take off the queue"]] }
    : { pad: [["dpad", "Choose"], ["a", "Add to queue"], ["y", "Take off the queue"]],
      keys: [["key", "↑ ↓", "Choose"], ["key", "Space", "Add to queue"], ["key", "Backspace", "Take off the queue"]] });
  srcKeys.start = () => $("c-start").click();  // Start (F10): Add to Library / Stop
  srcKeys.startText = () => (C.job ? "Stop" : "Add to Library");
  function srcKeys(key) {
    const queue = inQueue(P.cur);
    if (key === "Enter" || (key === " " && !queue)) { if (C.sel) enqueue(C.sel); return true; }
    if (key === "Delete" || key === "Backspace") { dequeue(queue ? [...Q.qsel] : C.sel ? [C.sel] : []); return true; }
    if (key === "ArrowDown" || key === "ArrowUp") {
      const keys = C.list?.rows.map((x) => x.key) || [];
      if (!keys.length) return false;
      const cur = keys.indexOf(C.sel);
      C.sel = keys[Math.max(0, Math.min(keys.length - 1, cur < 0 ? 0 : cur + (key === "ArrowDown" ? 1 : -1)))];
      fillRows();
      document.querySelector(`#c-table .trow[data-key="${CSS.escape(C.sel)}"]`)?.scrollIntoView({ block: "nearest" });
      return true;
    }
    return false;
  }

  // ----- wiring -----
  wireImportTabs("sources");
  $("c-table").addEventListener("click", (e) => {
    const row = e.target.closest(".trow[data-key]");
    if (row) { C.sel = row.dataset.key; fillRows(); }
  });
  $("c-table").addEventListener("dblclick", (e) => {
    const row = e.target.closest(".trow[data-key]");
    if (row) enqueue(row.dataset.key);
  });
  $("c-queue").addEventListener("click", (e) => {
    const row = e.target.closest(".trow[data-key]");
    if (!row) return;
    const k = row.dataset.key;
    if (e.ctrlKey || e.metaKey) Q.qsel.has(k) ? Q.qsel.delete(k) : Q.qsel.add(k);
    else Q.qsel = Q.qsel.has(k) && Q.qsel.size === 1 ? new Set() : new Set([k]);
    fillQueue();
  });
  $("c-source").onchange = (e) => open(e.target.value || null);
  $("c-add").onclick = async () => {
    const path = await pickFolder(C.path || C.saved.home, "A folder to copy games from (a mounted network share works too)");
    if (!path) return;
    try {
      C.saved = await call("source_add", { path });
      open(C.saved.last);
    } catch (e) { overlay(`<h2>Can't use that folder</h2><p>${esc(e.message)}</p>`, [["OK", closeOverlay, true]]); }
  };
  $("c-forget").onclick = async () => {
    if (!C.path || !await confirmBox({ title: "Remove source", ok: "Remove", message: `Stop listing ${C.path} as a source?`,
      detail: "Nothing in it is deleted; you can add it again any time." })) return;
    C.saved = await call("source_remove", { path: C.path }).catch(oops);
    open(C.saved?.sources[0]?.path || null);
  };
  $("c-refresh").onclick = () => open(C.path, true);
  $("c-system").onchange = $("c-hide").onchange = rows;
  $("c-q").oninput = () => { clearTimeout(C.timer); C.timer = setTimeout(rows, 200); };
  $("c-addq").onclick = () => enqueue(C.sel);
  $("c-remove").onclick = () => dequeue([...Q.qsel]);
  $("c-start").onclick = start;
  $("c-close").onclick = closeSheet;
  fillQueue();
  if (BG.kind === "sources") follow().catch(oops);
  open(pick);
  $("c-q").focus();
}
