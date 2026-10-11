// Tools that work on the files themselves: Compress games and Import ROMs. (Uses app.js, sheets.js and tools.js:
// call, runJob, sheet, setProgress …; the work is in app/helper/tool_files.py.)
"use strict";

registerTool({ cmd: "compress", label: "Compress games…", sub: "disc images to CHD / RVZ, originals held", system: true, open: () => openCompress() });
registerTool({ cmd: "import", label: "Import ROMs…", sub: "file new games into the ROMs folder by system", system: false, open: () => openImport() });

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
      <label class="check" title="Originals go to ${esc(info.holding)}, where ☰ → Holding folder deletes them for good (or Restore a move puts them back)."><input type="checkbox" id="c-delete"${info.delete ? " checked" : ""}> Delete the originals (instead of moving them to the holding folder)</label>
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
    if (!await rs.confirm({ title: "Compress games", ok: "Stop", message: "Stop compressing?", detail: "The game being compressed now stays as it was." })) return;
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
    if (!await rs.confirm({ title: "Compress games", ok: "Compress", message: `Compress ${plural(keys.length, "game")} (${human(size)})?`,
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
      if (r.games) toast(`Compressed ${plural(r.games, "game")}, saving ${human(r.saved)}.${r.held ? " The originals are in the holding folder (☰ → Holding folder)." : ""}`);
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
async function openImport() {
  if (!S.overview?.roms) { toast("Pick your ROMs folder first", { error: true }); return; }
  const info = await call("import_info");
  const I = { list: info, inbox: info.inbox, sel: new Set(), job: null, scanning: 0, watching: false, timer: null };
  sheet(`
    <div class="sheet-head"><h2>Import ROMs</h2>
      <p>Put games in the import folder (or add them from anywhere): ROM files, disc images and zip / 7z / rar archives, as they are. RetroShelf works out which system each one is for, unpacks it, and files it into your ROMs folder in a form the emulators read. Check the systems below, change any that are wrong, then press Import.</p></div>
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
      <span class="grow"></span><button class="ghost" id="i-close">Close</button><button class="primary" id="i-go">Import</button></div>`,
  "", () => {
    clearInterval(I.timer);
    if (I.job) { I.job.stop(); I.job.done.then(imported).catch(() => {}); }
  });
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
    $("i-go").textContent = I.job ? "Stop" : n ? `Import ${plural(n, "game")}` : "Import";
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
  async function imported(r) {  // after a run: new system folders show up, and the open system's new games
    if (!r.imported) return;
    S.overview = await call("startup");
    if (S.sys && r.systems.includes(S.sys.system)) await rescanQuietly();
  }
  pickRows($("i-table"), I.sel, Number, () => { fill(); syncSystem(); });
  $("i-open").onclick = () => rs.openFolder(I.inbox).then((err) => err && toast(`Couldn't open ${I.inbox}: ${err}`, { error: true }));
  $("i-change").onclick = async () => {
    const path = await rs.pickFolder(I.inbox, "Import folder");
    if (!path) return;
    try {
      const r = await call("import_set_inbox", { path });
      I.inbox = r.inbox;
      await scan(r);
    } catch (e) { oops(e); }
  };
  $("i-files").onclick = async () => {
    const paths = await rs.pickFiles(info.home, "Add games");
    if (!paths.length) return;
    try { await scan(await call("import_add", { paths })); } catch (e) { oops(e); }
  };
  $("i-folder").onclick = async () => {
    const path = await rs.pickFolder(info.home, "Add a folder of games");
    if (!path) return;
    try {
      const p = await call("import_folder", { path });
      if (!p.games) {
        overlay(`<h2>Nothing to add</h2><p>There are no games or archives in ${esc(path)} (or they're already in the list).</p>`, [["OK", closeOverlay, true]]);
        return;
      }
      const where = p.folders > 1 ? ` in ${p.folders} folders` : "";
      if (!await rs.confirm({ title: "Import ROMs", ok: "Add", message: `Add ${plural(p.games, "game")}${where} from\n\n${path}${p.folders > 1 ? " (and the folders inside it)" : ""}?`,
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
  const askStop = async () => {  // closing while it works (Close, Esc, a click outside) asks first
    if (!await rs.confirm({ title: "Import ROMs", ok: "Stop", message: "Stop importing?", detail: "The game being imported now is left where it was." })) return;
    sheetBusy = null;
    closeSheet();
  };
  $("i-go").onclick = async () => {
    if (I.job) { I.job.stop(); $("i-go").disabled = true; $("i-status").textContent = "Stopping …"; return; }
    if (!I.list.ready) return;
    sheetBusy = askStop;
    I.job = runJob("import_run", { delete: $("i-delete").checked }, (p) => {
      if (!$("i-table")) return;
      if (p.row) {
        I.list.rows = I.list.rows.map((r) => (r.id === p.row.id ? p.row : r));
        fill();
      } else {
        $("i-bar").style.width = `${p.total ? (100 * p.done) / p.total : 0}%`;
        if (p.message) $("i-status").textContent = p.message;
      }
    });
    buttons();
    try {
      const r = await I.job.done;
      I.job = null;
      if (!$("i-table")) { await imported(r); return; }
      sheetBusy = null;
      $("i-bar").style.width = "0";
      show(r);
      if (r.imported) {
        $("i-status").textContent = `${r.stopped ? "Stopped. " : ""}Imported ${r.imported.toLocaleString()} — they're in your ROMs folder now.`;
        toast(`Imported ${plural(r.imported, "game")}${r.systems.length ? ` into ${r.systems.join(", ")}` : ""}.`);
        await imported(r);
      }
    } catch (e) {
      I.job = null;
      if ($("i-status")) { sheetBusy = null; buttons(); $("i-status").textContent = `Failed: ${e.message}`; }
    }
  };
  // new files in the import folder show up while the window is open
  I.timer = setInterval(async () => {
    if (I.watching || I.job || I.scanning) return;
    I.watching = true;
    try { const list = await call("import_watch"); if (list) await scan(list); } catch (e) { console.error(e); } finally { I.watching = false; }
  }, 2000);
  await scan(info);
}
