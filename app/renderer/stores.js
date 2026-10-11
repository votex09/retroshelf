// Tools that get games into the ROMs folder: NoPayStation, and the homebrew stores (Homebrew Hub, itch.io, PDRoms,
// MAMEDEV), which share one window. (Uses app.js, sheets.js and tools.js: call, runJob, sheet, setProgress …)
"use strict";

registerTool({ cmd: "nps", group: "get", label: "NoPayStation…", sub: "PS3, PS Vita and PSP packages", system: false, open: () => openNps() });
registerTool({ cmd: "homebrew", group: "get", label: "Homebrew Hub…", sub: "free GB / GBC / GBA / NES homebrew", system: false, open: () => openStore("homebrew") });
registerTool({ cmd: "itch", group: "get", label: "itch.io homebrew…", sub: "free homebrew, downloaded in your browser", system: false, open: () => openStore("itch") });
registerTool({ cmd: "pdroms", group: "get", label: "PDRoms homebrew…", sub: "homebrew since 1998, downloaded in your browser", system: false, open: () => openStore("pdroms") });
registerTool({ cmd: "mamedev", group: "get", label: "Free arcade games (MAMEDEV)…", sub: "arcade games released for free", system: false, open: () => openStore("mamedev") });

const options = (items, current) => items.map(([v, label]) => `<option value="${esc(v)}"${v === current ? " selected" : ""}>${esc(label)}</option>`).join("");

// Click picks a row, Ctrl-click adds or removes one, Shift-click picks a run. -> the picked keys
function pickKeys(sel, keys, key, e, anchor) {
  if (e.shiftKey && anchor != null && keys.includes(anchor)) {
    const [a, b] = [keys.indexOf(anchor), keys.indexOf(key)].sort((x, y) => x - y);
    if (!e.ctrlKey && !e.metaKey) sel.clear();
    for (const k of keys.slice(a, b + 1)) sel.add(k);
  } else if (e.ctrlKey || e.metaKey) {
    sel.has(key) ? sel.delete(key) : sel.add(key);
  } else {
    sel.clear();
    sel.add(key);
  }
}

// ---------- NoPayStation ----------
const npsSize = (n) => (n >= 1073741824 ? `${(n / 1073741824).toFixed(2)} GB` : `${(n / 1048576).toFixed(1)} MB`);
const NPS_HINT = "Double-click or Enter to queue · Ctrl / Shift-click for several";
const NPS_OWNED = ["Installed", "Have as ROM", "Have (other region)"];

async function openNps(system) {
  const info = await call("nps_info", { system });
  const N = { info, kind: info.kinds[0], loaded: new Set(), list: null, sel: new Set(), anchor: null, sort: "name", desc: false,
    queue: [], states: new Map(), qsel: new Set(), qanchor: null, job: null, installed: false, timer: null, seq: 0 };
  sheet(`
    <div class="sheet-head"><div class="head-row"><h2>NoPayStation  ·  ${esc(info.console)}</h2><span class="grow"></span>
      <span class="muted small-text" id="n-age"></span><button class="ghost small" id="n-refresh">Refresh lists</button></div>
      <p>${esc(info.note)}</p>${info.problem ? `<p class="note warn">⚠ ${esc(info.problem)}</p>` : ""}</div>
    <div class="sheet-tools">
      <select id="n-system">${options(info.systems, info.system)}</select>
      <select id="n-kind">${options(info.kinds.map((k) => [k, k]), N.kind)}</select>
      <select id="n-region">${options(info.regions.map((r) => [r, r]), "US")}</select>
      <input type="search" id="n-q" placeholder="Search" spellcheck="false">
      ${info.mine ? `<label class="check"><input type="checkbox" id="n-mine"> Only for my games</label>` : ""}
      <label class="check"><input type="checkbox" id="n-hide"> Hide ones I have</label>
    </div>
    <div class="results-line" id="n-res"></div>
    <div class="table nps-rows" id="n-table"></div>
    <div class="sheet-tools under"><span class="grow muted" id="n-hint">${NPS_HINT}</span><button class="ghost small" id="n-add">Add to queue</button></div>
    <div class="sheet-tools queue-head"><b id="n-qhead">Queue</b><span class="grow"></span>
      <button class="ghost small" id="n-retry">Retry failed</button><button class="ghost small" id="n-remove">Remove</button></div>
    <div class="table nps-queue" id="n-queue"></div>
    <div class="nps-progress"><div class="progress-bar"><div id="n-bar"></div></div><div class="progress-text" id="n-status"></div></div>
    <div class="sheet-foot">
      <span class="muted">Downloads</span><span class="path-text" id="n-dir" title="${esc(info.dir)}">${esc(info.dir)}</span>
      <button class="ghost small" id="n-dir-btn">Change…</button>
      ${info.emulator ? `<button class="ghost small" id="n-emu" title="${esc(`${info.emulator.label}: ${info.emulator.path}`)}">Emulators…</button>` : ""}
      <label class="check"><input type="checkbox" id="n-keep"${info.keep_pkg ? " checked" : ""}> Keep .pkg after install</label>
      <label class="check"><input type="checkbox" id="n-scrape"${info.scrape ? " checked" : ""}> Scrape new games (LaunchBox)</label>
      <span class="grow"></span><button class="ghost" id="n-close">Close</button><button class="primary" id="n-start">Start</button>
    </div>`,
  "stores-sheet", () => {
    N.job?.stop();
    if (N.installed && S.sys?.system === info.system) rescanQuietly();
  }, npsKeys);
  const status = (text) => { if ($("n-status")) $("n-status").textContent = text; };
  const filters = () => ({ system: info.system, kind: N.kind, region: $("n-region").value, query: $("n-q").value,
    mine: !!$("n-mine")?.checked, hide_have: $("n-hide").checked, sort: N.sort, desc: N.desc,
    queued: Object.fromEntries(N.states) });

  async function load() {
    const kind = N.kind;
    if (N.loaded.has(kind)) return refresh();
    status(kind === "Updates" ? "Checking Sony's update server …" : `Loading ${info.console} ${kind} list …`);
    try {
      const r = await runJob("nps_load", { system: info.system, kind }, (p) => status(p.message)).done;
      N.loaded.add(kind);
      $("n-age").textContent = r.age;
      status(r.message);
      if (kind === N.kind) refresh();
    } catch (e) { status(`Couldn't load the list: ${e.message}`); }
  }
  async function refresh() {
    if (!N.loaded.has(N.kind)) return;
    const n = ++N.seq;
    try {
      const r = await call("nps_rows", filters());
      if (n !== N.seq || !$("n-table") || !r) return;
      N.list = r;
      fillRows();
    } catch (e) { oops(e); }
  }
  function fillRows() {
    const r = N.list, keys = new Set(r.rows.map((x) => x.key));
    for (const k of [...N.sel]) if (!keys.has(k)) N.sel.delete(k);
    const head = (col, label, cls = "") => `<span class="sort ${cls}" data-sort="${col}">${label}${N.sort === col ? (N.desc ? " ▾" : " ▴") : ""}</span>`;
    $("n-table").innerHTML = `<div class="trow head">${head("name", "Name")}${head("id", "Title ID")}${head("region", "Region")}${head("size", "Size", "num")}<span>Status</span></div>` +
      (r.rows.length ? r.rows.map((x) => `<div class="trow${N.sel.has(x.key) ? " on" : ""}" data-key="${esc(x.key)}">
        <span class="nm" title="${esc(x.name)}">${esc(x.name)}</span><span class="dim">${esc(x.id)}</span><span class="dim">${esc(x.region)}</span>
        <span class="num">${npsSize(x.size)}</span><span class="dim ${statusClass(x.status)}">${esc(x.status)}</span></div>`).join("")
        : `<div class="none">Nothing matches.</div>`);
    $("n-res").textContent = `${r.shown.toLocaleString()} of ${r.total.toLocaleString()} ${N.kind.toLowerCase()}` +
      (r.rows.length < r.shown ? ` (the first ${r.rows.length.toLocaleString()} shown: search to narrow it down)` : "");
    showHave();
  }
  function statusClass(st) {
    return st === "Installed" ? "st-ok" : NPS_OWNED.includes(st) ? "st-have" : st.startsWith("Failed") ? "st-bad" : "";
  }
  function showHave() {
    const row = N.sel.size === 1 ? N.list?.rows.find((x) => N.sel.has(x.key)) : null;
    $("n-hint").textContent = row?.have.length ?`You have: ${row.have.join("  ·  ")}` : NPS_HINT;
  }

  // ----- the queue -----
  async function enqueue(keys) {
    if (!keys.length) return;
    const rows = await call("nps_enqueue", { system: info.system, kind: N.kind, keys });
    let added = 0;
    for (const row of rows) {
      if (N.queue.some((q) => q.key === row.key)) {
        if ((N.states.get(row.key) || "").startsWith("Failed")) { N.states.set(row.key, "Queued"); added++; }  // adding a failed one again retries it
        continue;
      }
      N.queue.push(row);
      N.states.set(row.key, "Queued");
      added++;
    }
    if (added) { fillQueue(); refresh(); }
  }
  function fillQueue() {
    if (!$("n-queue")) return;
    $("n-queue").innerHTML = N.queue.length ? N.queue.map((q) => `<div class="trow${N.qsel.has(q.key) ? " on" : ""}" data-key="${esc(q.key)}">
      <span class="nm" title="${esc(q.label)}">${esc(q.label)}</span><span class="num">${npsSize(q.size)}</span>
      <span class="dim ${statusClass(N.states.get(q.key) || "")}" data-state>${esc(N.states.get(q.key) || "")}</span></div>`).join("")
      : `<div class="none">Pick games above and press Add to queue.</div>`;
    const pending = N.queue.filter((q) => N.states.get(q.key) === "Queued");
    $("n-qhead").textContent = `Queue   ${pending.length} waiting  ·  ${npsSize(pending.reduce((s, q) => s + q.size, 0))}`;
    $("n-retry").disabled = !N.queue.some((q) => (N.states.get(q.key) || "").startsWith("Failed"));
  }
  function setState(key, text) {
    N.states.set(key, text);
    const cell = document.querySelector(`#n-queue .trow[data-key="${CSS.escape(key)}"] [data-state]`);
    if (cell) { cell.textContent = text; cell.className = `dim ${statusClass(text)}`; }
  }
  function dequeue() {
    for (const q of N.queue.filter((q) => N.qsel.has(q.key))) {
      const st = N.states.get(q.key) || "";
      if (st === "Queued" || st === "Done" || st.startsWith("Failed")) {
        N.queue = N.queue.filter((j) => j !== q);
        N.states.delete(q.key);
        N.qsel.delete(q.key);
      }
    }
    fillQueue();
    refresh();
  }
  function retry() {  // failed jobs go back to Queued; an already-downloaded .pkg is reused
    const failed = N.queue.filter((q) => (N.states.get(q.key) || "").startsWith("Failed"));
    const picked = failed.filter((q) => N.qsel.has(q.key));
    for (const q of picked.length ? picked : failed) N.states.set(q.key, "Queued");
    fillQueue();
    refresh();
    status(`${(picked.length || failed.length)} queued again` + (N.job ? "  ·  they run after the current batch, press Start then" : "  ·  press Start"));
  }

  // ----- running it -----
  async function start() {
    if (N.job) {
      N.job.stop();
      $("n-start").disabled = true;
      $("n-start").textContent = "Stopping…";
      return;
    }
    const pending = N.queue.filter((q) => N.states.get(q.key) === "Queued");
    if (!pending.length) { status("Queue is empty: pick games above and press Add to queue."); return; }
    const keys = pending.map((q) => q.key);
    try {
      const room = await call("nps_space", { system: info.system, keys });
      if (room.free < room.need && !await confirmBox({ title: "Low disk space", ok: "Start anyway", warning: true,
        message: `About ${npsSize(room.need)} is needed but only ${npsSize(room.free)} is free in ${room.dir}`, detail: "Start anyway?" })) return;
    } catch (e) { oops(e); return; }
    const others = N.queue.filter((q) => !keys.includes(q.key)).map((q) => N.states.get(q.key) || "");
    $("n-start").textContent = "Stop";
    $("n-system").disabled = $("n-refresh").disabled = true;
    $("n-bar").style.width = "0%";
    N.job = runJob("nps_run", { system: info.system, keys, others }, (p) => {
      if (p.key && p.state) setState(p.key, p.state);
      if (p.message) status(p.message);
      if ($("n-bar")) $("n-bar").style.width = `${(100 * p.done) / p.total}%`;
    });
    try {
      const r = await N.job.done;
      for (const [k, v] of Object.entries(r.states)) N.states.set(k, v);
      N.installed ||= r.installed;
      status(r.summary);
      if (!r.stopped && $("n-bar")) $("n-bar").style.width = "100%";
    } catch (e) { status(`Failed: ${e.message}`); }
    N.job = null;
    if (!$("n-start")) return;
    $("n-start").disabled = $("n-system").disabled = $("n-refresh").disabled = false;
    $("n-start").textContent = "Start";
    fillQueue();
    refresh();
  }

  // ----- wiring -----
  function tableClick(id, sel, anchorKey, e) {
    const row = e.target.closest(".trow[data-key]");
    if (!row) return null;
    const keys = [...$(id).querySelectorAll(".trow[data-key]")].map((r) => r.dataset.key);
    pickKeys(sel, keys, row.dataset.key, e, N[anchorKey]);
    if (!e.shiftKey) N[anchorKey] = row.dataset.key;
    return row.dataset.key;
  }
  $("n-table").addEventListener("click", (e) => {
    const s = e.target.closest("[data-sort]");
    if (s) {
      const col = s.dataset.sort;
      N.desc = N.sort === col ? !N.desc : col === "size";
      N.sort = col;
      refresh();
      return;
    }
    if (tableClick("n-table", N.sel, "anchor", e)) fillRows();
  });
  $("n-table").addEventListener("dblclick", (e) => {
    const row = e.target.closest(".trow[data-key]");
    if (row) enqueue([row.dataset.key]).catch(oops);
  });
  $("n-queue").addEventListener("click", (e) => { if (tableClick("n-queue", N.qsel, "qanchor", e)) fillQueue(); });
  function npsKeys(key) {
    if (key === "Enter") { enqueue([...N.sel]).catch(oops); return true; }
    if (key === "Delete") { dequeue(); return true; }
    if (key === "ArrowDown" || key === "ArrowUp") {
      const keys = N.list?.rows.map((x) => x.key) || [];
      if (!keys.length) return false;
      const cur = keys.findIndex((k) => N.sel.has(k));
      const i = Math.max(0, Math.min(keys.length - 1, cur < 0 ? 0 : cur + (key === "ArrowDown" ? 1 : -1)));
      N.sel = new Set([keys[i]]);
      N.anchor = keys[i];
      fillRows();
      document.querySelector(`#n-table .trow[data-key="${CSS.escape(keys[i])}"]`)?.scrollIntoView({ block: "nearest" });
      return true;
    }
    return false;
  }
  $("n-system").onchange = (e) => { closeSheet(); openNps(e.target.value).catch(oops); };
  $("n-kind").onchange = (e) => { N.kind = e.target.value; N.sel.clear(); load(); };
  $("n-region").onchange = $("n-hide").onchange = refresh;
  if ($("n-mine")) $("n-mine").onchange = refresh;
  $("n-q").oninput = () => { clearTimeout(N.timer); N.timer = setTimeout(refresh, 200); };
  $("n-add").onclick = () => enqueue([...N.sel]).catch(oops);
  $("n-remove").onclick = dequeue;
  $("n-retry").onclick = retry;
  $("n-start").onclick = () => start().catch(oops);
  $("n-close").onclick = closeSheet;
  $("n-refresh").onclick = async () => {
    if (N.job) return;
    status("Downloading NPS lists …");
    try {
      await call("nps_refresh", { system: info.system });
      N.loaded.clear();
      load();
    } catch (e) { status(`Couldn't refresh: ${e.message}`); }
  };
  $("n-keep").onchange = (e) => call("nps_options", { keep_pkg: e.target.checked }).catch(oops);
  $("n-scrape").onchange = (e) => call("nps_options", { scrape: e.target.checked }).catch(oops);
  $("n-dir-btn").onclick = async () => {
    const path = await rs.pickFolder($("n-dir").title, "Where packages are downloaded");
    if (!path) return;
    await call("nps_options", { folder: path });
    $("n-dir").textContent = $("n-dir").title = path;
  };
  if ($("n-emu")) $("n-emu").onclick = async () => {
    const path = await rs.pickFolder(info.emulator.path === "not found" ? S.overview?.roms : info.emulator.path, `Folder with ${info.emulator.exe}`);
    if (!path) return;
    try {
      const fresh = await call("nps_set_emulator", { system: info.system, path });
      if (N.job) { toast(`${fresh.emulator.label}: ${fresh.emulator.path}`); return; }
      closeSheet();  // opened again: the warning and what's installed may have changed
      openNps(info.system).catch(oops);
    } catch (e) {
      overlay(`<h2>No ${esc(info.emulator.exe)}</h2><p>${esc(e.message)}</p>`, [["OK", closeOverlay, true]]);
    }
  };
  fillQueue();
  load();
  $("n-q").focus();
}

// ---------- the homebrew stores ----------
const STORE_WATCH_MS = 1500;

async function openStore(store) {
  const info = await call("store_info", { store });
  const W = { info, code: info.code, rows: [], sel: null, game: null, job: null, seq: 0, gseq: 0, timer: null, watching: null, waiting: info.waiting };
  const cols = ["minmax(0, 1fr)", "160px", ...(info.kinds ? ["70px"] : []), ...(info.license_header ? ["110px"] : []), "110px"].join(" ");
  sheet(`
    <div class="sheet-head"><div class="head-row"><h2>${esc(info.heading)}</h2><span class="grow"></span>
      <span class="muted small-text" id="w-age"></span><button class="ghost small" id="w-refresh">Refresh list</button></div>
      <p>${esc(info.note)}</p></div>
    <div class="sheet-tools">
      <select id="w-system">${options(info.systems, info.code)}</select>
      ${info.kinds ? `<select id="w-kind">${options(["all", ...info.kinds].map((k) => [k, k]), info.default_kind)}</select>` : ""}
      <input type="search" id="w-q" placeholder="Search" spellcheck="false">
      ${info.one_click_filter ? `<label class="check"><input type="checkbox" id="w-one"> One-click only</label>` : ""}
      <label class="check"><input type="checkbox" id="w-hide"> Hide ones I have</label>
    </div>
    <div class="store-body">
      <div class="store-list"><div class="results-line" id="w-res"></div><div class="table store-rows" id="w-table" style="--cols: ${cols}"></div></div>
      <div class="store-details" id="w-details"></div>
    </div>
    <div class="store-status">
      <div class="progress-bar" id="w-barbox" hidden><div id="w-bar"></div></div>
      <div class="progress-text" id="w-status"></div>
      <div class="waiting" id="w-waiting" hidden><span class="grow" id="w-wait-text"></span><button class="ghost small" id="w-stop-wait">Stop waiting</button></div>
    </div>
    <div class="sheet-foot">
      ${info.browser_downloads ? `<span class="muted">Downloads</span><button class="ghost small" id="w-dir-btn">Change…</button>
        <span class="path-text" id="w-dir" title="${esc(info.downloads)}">${esc(info.downloads_short)}</span>` : ""}
      <span class="grow"></span><button class="ghost" id="w-close">Close</button>
      ${info.browse_label ? `<button class="ghost" id="w-browse">${esc(info.browse_label)}</button>` : ""}
      <button class="${info.one_click ? "ghost" : "primary"}" id="w-open">${esc(info.open_label)}</button>
      ${info.one_click ? `<button class="primary" id="w-install">Install</button>` : ""}
    </div>`,
  "stores-sheet", () => {
    clearInterval(W.watching);
    W.job?.stop();
    if (W.waiting.count) call("store_stop_waiting", { store }).catch(oops);
  }, storeKeys);
  const status = (text) => { if ($("w-status")) $("w-status").textContent = text; };
  const label = () => info.systems.find(([c]) => c === W.code)[1];

  async function load(refresh = false) {
    const code = W.code;
    status(`Loading the ${label()} list from ${info.name} …`);
    const r = await call("store_load", { store, code, refresh });
    if (code !== W.code || !$("w-table")) return;  // switched while loading
    $("w-age").textContent = r.age;
    status(r.error);
    await rows();
  }
  async function rows() {
    const n = ++W.seq;
    const r = await call("store_rows", { store, code: W.code, query: $("w-q").value, kind: $("w-kind")?.value || info.default_kind,
      one_click: !!$("w-one")?.checked, hide_have: $("w-hide").checked });
    if (n !== W.seq || !$("w-table")) return;
    W.rows = r.rows;
    if (!r.rows.some((x) => x.key === W.sel)) W.sel = null;
    $("w-res").textContent = r.results;
    $("w-table").innerHTML = `<div class="trow head"><span>Title</span><span>Developer</span>${info.kinds ? "<span>Type</span>" : ""}` +
      `${info.license_header ? `<span>${esc(info.license_header)}</span>` : ""}<span></span></div>` +
      (r.rows.length ? r.rows.map((x) => `<div class="trow${x.key === W.sel ? " on" : ""}" data-key="${esc(x.key)}">
        <span class="nm" title="${esc(x.title)}">${esc(x.title)}</span><span class="dim">${esc(x.developer)}</span>
        ${info.kinds ? `<span class="dim">${esc(x.kind)}</span>` : ""}${info.license_header ? `<span class="dim">${esc(x.license)}</span>` : ""}
        <span class="dim ${x.status === "Installed" ? "st-ok" : x.status === "Waiting" ? "st-have" : ""}">${esc(x.status)}</span></div>`).join("")
        : `<div class="none">Nothing to show.</div>`);
    if (W.sel !== W.game?.key) details();
    else buttons();
  }

  // ----- the picked game -----
  async function details() {
    const n = ++W.gseq, row = W.rows.find((x) => x.key === W.sel);
    W.game = null;
    buttons();
    if (!row) {
      $("w-details").innerHTML = `<p class="muted">Pick a game to see its details.</p>`;
      return;
    }
    $("w-details").innerHTML = `<div class="shot muted"></div><h3>${esc(row.title)}</h3><p class="muted">Loading details …</p>`;
    let g;
    try { g = await call("store_game", { store, code: W.code, key: row.key }); } catch (e) { oops(e); return; }
    if (n !== W.gseq || !$("w-details")) return;
    W.game = g;
    $("w-details").innerHTML = `<div class="shot muted" id="w-shot">${g.shot ? "Loading screenshot …" : "No screenshot"}</div>
      <h3>${esc(g.title)}</h3>${g.meta ? `<p class="muted">${esc(g.meta)}</p>` : ""}<p class="desc">${esc(g.description)}</p>
      ${g.note ? `<p class="muted">${esc(g.note)}</p>` : ""}`;
    buttons();
    if (!g.shot) return;
    const src = await call("store_shot", { url: g.shot }).catch(() => null);
    if (n !== W.gseq || !$("w-shot")) return;
    $("w-shot").innerHTML = src ? `<img src="${esc(src)}" alt="">` : "No screenshot";
  }
  function buttons() {
    if (!$("w-open")) return;
    $("w-open").disabled = !W.sel;
    if ($("w-install") && !W.job) $("w-install").disabled = !W.game?.can_install;
  }
  function select(key) {
    if (key === W.sel) return;
    W.sel = key;
    for (const r of $("w-table").querySelectorAll(".trow[data-key]")) r.classList.toggle("on", r.dataset.key === key);
    details();
  }

  // ----- getting games -----
  function showWaiting(w) {
    W.waiting = w;
    if (!$("w-waiting")) return;
    $("w-waiting").hidden = !w.count;
    $("w-wait-text").textContent = w.text;
  }
  function filed(f) {  // a ROM landed in roms/<system> (or failed to)
    status(f.message);
    if (f.error) {
      overlay(`<h2>Couldn't add the game</h2><p>${esc(f.title)}: ${esc(f.error)}</p>`, [["OK", closeOverlay, true]]);
      return;
    }
    toast(f.toast);
    if (S.sys?.system === f.system) rescanQuietly().catch(oops);
  }
  async function install() {
    const g = W.game;
    if (W.job) { W.job.stop(); $("w-install").disabled = true; $("w-install").textContent = "Stopping…"; return; }
    if (!g?.can_install) return;
    if (g.confirm && !await confirmBox({ title: `Install ${g.title}`, ok: "Install", message: g.confirm })) return;
    $("w-install").textContent = "Stop";
    $("w-barbox").hidden = false;
    $("w-bar").style.width = "0%";
    status(`Downloading ${g.title} …`);
    W.job = runJob("store_install", { store, code: W.code, key: g.key }, (p) => setProgress("w-bar", "w-status", p));
    try {
      const r = await W.job.done;
      if (r.stopped) status("Stopped.");
      else filed(r);
    } catch (e) { status(`${g.title}: ${e.message}`); }
    W.job = null;
    if (!$("w-install")) return;
    $("w-barbox").hidden = true;
    $("w-install").textContent = "Install";
    W.game = null;
    await rows();
    details();
  }
  async function openPage() {
    if (!W.sel) return;
    const r = await call("store_open", { store, code: W.code, key: W.sel });
    const err = await rs.openUrl(r.url);
    if (err) toast(`Couldn't open it: ${err}`, { error: true });
    showWaiting(r.waiting);
    rows();
  }
  async function watch() {
    if (!W.waiting.count) return;
    try {
      const r = await call("store_watch", { store });
      showWaiting(r.waiting);
      r.filed.forEach(filed);
      if (r.filed.length) rows();
    } catch (e) { oops(e); }
  }

  // ----- wiring -----
  $("w-table").addEventListener("click", (e) => {
    const row = e.target.closest(".trow[data-key]");
    if (row) select(row.dataset.key);
  });
  $("w-table").addEventListener("dblclick", (e) => {
    const row = e.target.closest(".trow[data-key]");
    if (!row) return;
    select(row.dataset.key);
    activate();
  });
  function activate() {  // double-click or Enter: install when it can, else the game's page
    if (W.game?.key === W.sel && W.game.can_install) install().catch(oops);
    else openPage().catch(oops);
  }
  function storeKeys(key) {
    if (key === "Enter") { if (W.sel) activate(); return true; }
    if (key === "ArrowDown" || key === "ArrowUp") {
      if (!W.rows.length) return false;
      const cur = W.rows.findIndex((x) => x.key === W.sel);
      const i = Math.max(0, Math.min(W.rows.length - 1, cur < 0 ? 0 : cur + (key === "ArrowDown" ? 1 : -1)));
      select(W.rows[i].key);
      document.querySelector(`#w-table .trow[data-key="${CSS.escape(W.rows[i].key)}"]`)?.scrollIntoView({ block: "nearest" });
      return true;
    }
    return false;
  }
  $("w-system").onchange = (e) => { W.code = e.target.value; W.sel = null; browseTip(); load().catch(oops); };
  if ($("w-kind")) $("w-kind").onchange = () => rows().catch(oops);
  if ($("w-one")) $("w-one").onchange = () => rows().catch(oops);
  $("w-hide").onchange = () => rows().catch(oops);
  $("w-q").oninput = () => { clearTimeout(W.timer); W.timer = setTimeout(() => rows().catch(oops), 150); };
  $("w-refresh").onclick = () => load(true).catch(oops);
  $("w-open").onclick = () => openPage().catch(oops);
  if ($("w-install")) $("w-install").onclick = () => install().catch(oops);
  if ($("w-browse")) $("w-browse").onclick = async () => {
    try {
      const r = await call("store_browse", { store, code: W.code });
      const err = await rs.openUrl(r.url);
      if (err) toast(`Couldn't open it: ${err}`, { error: true });
      showWaiting(r.waiting);
    } catch (e) { oops(e); }
  };
  const browseTip = () => $("w-browse") && ($("w-browse").title = `Opens ${info.name} in your browser. Every ${label()} ROM you download there is put in roms/${W.code}.`);
  $("w-stop-wait").onclick = async () => {
    try { showWaiting((await call("store_stop_waiting", { store })).waiting); rows(); } catch (e) { oops(e); }
  };
  if ($("w-dir-btn")) $("w-dir-btn").onclick = async () => {
    const path = await rs.pickFolder($("w-dir").title, "Where your browser saves downloads");
    if (!path) return;
    $("w-dir").textContent = await call("store_set_downloads", { path });
    $("w-dir").title = path;
  };
  $("w-close").onclick = async () => {
    if (W.waiting.count && !await confirmBox({ title: "Still waiting", ok: "Close",
      message: "RetroShelf is still waiting for downloads to put in your ROMs folder. Close anyway?" })) return;
    closeSheet();
  };
  showWaiting(W.waiting);
  browseTip();
  details();
  W.watching = setInterval(watch, STORE_WATCH_MS);
  $("w-q").focus();
  load().catch((e) => status(`Couldn't load the list: ${e.message}`));
}
