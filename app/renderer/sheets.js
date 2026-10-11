// Sheets: the bigger jobs that open over the main window. The holding folder, restoring a Move, region priority
// and picking a game's LaunchBox match. (Uses app.js's helpers: call, esc, human, plural, toast, oops, S …)
"use strict";

let onSheetClose = null;

function sheet(html, cls = "", onClose = null) {
  $("sheet").className = `sheet ${cls}`;
  $("sheet").innerHTML = html;
  $("sheet-wrap").hidden = false;
  onSheetClose = onClose;
}

function closeSheet() {
  if ($("sheet-wrap").hidden) return;
  $("sheet-wrap").hidden = true;
  $("sheet").innerHTML = "";
  const fn = onSheetClose;
  onSheetClose = null;
  if (fn) Promise.resolve().then(fn).catch(oops);
}

$("sheet-wrap").addEventListener("mousedown", (e) => { if (e.target === $("sheet-wrap")) closeSheet(); });

function failures(title, failed) {
  overlay(`<h2>${esc(title)}</h2><ul>${failed.slice(0, 50).map((f) => `<li>${esc(f)}</li>`).join("")}</ul>`,
    [["Close", closeOverlay, true]]);
}

// After files moved under the open system, scan it again, staying on the same game.
async function rescanQuietly() {
  if (!S.sys) return;
  const keep = L().current?.key;
  loadSystem(await call("rescan"), keep);
}

const when = (t) => (t ? t.replace("T", "  ") : "—");

// ---------- the holding folder ----------
async function openHolding() {
  const H = { data: await call("holding_list"), sel: new Set(), dest: "All", system: "All", q: "", changed: false };
  sheet(`
    <div class="sheet-head"><h2>Holding folder</h2><p id="h-root"></p></div>
    <div class="sheet-tools">
      <select id="h-dest"><option>All</option><option>to_delete</option><option>review_low_value</option></select>
      <select id="h-system"></select>
      <input type="search" id="h-q" placeholder="Search" spellcheck="false">
      <button class="ghost small" id="h-open">Open folder</button>
    </div>
    <div class="table" id="h-table"></div>
    <div class="sheet-foot">
      <span class="grow" id="h-sum"></span>
      <label class="check"><input type="checkbox" id="h-forget" checked> Deleting also removes ES-DE artwork and gamelist entries</label>
    </div>
    <div class="sheet-foot">
      <button class="ghost danger" id="h-empty"></button>
      <span class="grow"></span>
      <button class="ghost" id="h-close">Close</button>
      <button class="ghost danger" id="h-delete">Delete selected</button>
      <button class="primary" id="h-restore">Restore selected</button>
    </div>`, "", () => H.changed && rescanQuietly());

  const shown = () => {
    const q = H.q.toLowerCase();
    return H.data.games.filter((g) => (H.dest === "All" || g.dest === H.dest) && (H.system === "All" || g.system === H.system) &&
      (!q || g.key.toLowerCase().includes(q) || g.label.toLowerCase().includes(q)));
  };
  function fill() {
    const d = H.data;
    $("h-root").textContent = `${d.root}  ·  Look through what you moved out, put games back, or delete them for good.` +
      (d.same_drive ? "  It's on the same drive as your ROMs, so space only frees up once games are deleted." : "");
    const systems = [...new Set(d.games.map((g) => g.system))].sort();
    if (!systems.includes(H.system)) H.system = "All";
    $("h-system").innerHTML = ["All", ...systems].map((x) => `<option${x === H.system ? " selected" : ""}>${esc(x)}</option>`).join("");
    const rows = shown();
    const ids = new Set(rows.map((g) => g.id));
    for (const id of [...H.sel]) if (!ids.has(id)) H.sel.delete(id);
    const all = rows.length && rows.every((g) => H.sel.has(g.id));
    $("h-table").innerHTML = `<div class="trow head" data-all="1"><input type="checkbox"${all ? " checked" : ""}><span>Game</span><span>System</span><span>Folder</span><span class="num">Size</span><span>Moved</span></div>` +
      (rows.length ? rows.map((g) => `<div class="trow${H.sel.has(g.id) ? " on" : ""}" data-id="${g.id}">
        <input type="checkbox"${H.sel.has(g.id) ? " checked" : ""}><span class="nm" title="${esc(g.label)}">${esc(g.label)}</span>
        <span class="dim">${esc(g.system)}</span><span class="dim">${esc(g.dest)}</span>
        <span class="num">${human(g.size)}</span><span class="dim">${esc(when(g.moved))}</span></div>`).join("")
        : `<div class="none">${d.games.length ? "No matches" : "Nothing in the holding folder."}</div>`);
    const picked = rows.filter((g) => H.sel.has(g.id));
    $("h-sum").textContent = `${plural(rows.length, "game")} · ${human(rows.reduce((s, g) => s + g.size, 0))}` +
      (picked.length ? `  ·  ${picked.length} selected (${human(picked.reduce((s, g) => s + g.size, 0))})` : "");
    const del = rows.filter((g) => g.dest === "to_delete");
    $("h-empty").textContent = `Empty to_delete (${del.length.toLocaleString()} · ${human(del.reduce((s, g) => s + g.size, 0))})`;
    $("h-empty").disabled = !del.length;
    $("h-restore").disabled = $("h-delete").disabled = !picked.length;
  }
  $("h-table").addEventListener("click", (e) => {
    const row = e.target.closest(".trow");
    if (!row) return;
    if (row.dataset.all) {
      const rows = shown(), all = rows.every((g) => H.sel.has(g.id));
      for (const g of rows) all ? H.sel.delete(g.id) : H.sel.add(g.id);
    } else {
      const id = Number(row.dataset.id);
      H.sel.has(id) ? H.sel.delete(id) : H.sel.add(id);
    }
    fill();
  });
  $("h-dest").onchange = (e) => { H.dest = e.target.value; fill(); };
  $("h-system").onchange = (e) => { H.system = e.target.value; fill(); };
  $("h-q").oninput = (e) => { H.q = e.target.value; fill(); };
  $("h-open").onclick = () => rs.openFolder(H.data.root).then((err) => err && toast(`Couldn't open it: ${err}`, { error: true }));
  $("h-close").onclick = closeSheet;

  $("h-restore").onclick = async () => {
    const ids = [...H.sel];
    try {
      const r = await call("holding_restore", { ids });
      H.data = r.holding; H.sel.clear(); H.changed = true;
      fill();
      if (r.failed.length) failures(`Put ${plural(r.back, "file")} back; ${r.failed.length} couldn't be`, r.failed);
      else toast(`Put ${plural(r.back, "file")} back`);
    } catch (e) { oops(e); }
  };
  async function del(games, what) {
    if (!games.length) return;
    const extra = games.filter((g) => g.installed).length;
    const forget = $("h-forget").checked;
    const ok = await rs.confirm({ title: "Delete for good", ok: "Delete", warning: true,
      message: `Permanently delete ${what} (${plural(games.length, "game")}, ${human(games.reduce((s, g) => s + g.size, 0))})?`,
      detail: [extra ? `${extra} of them include RPCS3 / Vita3K game data, which is deleted too.` : "",
        forget ? "Their ES-DE artwork and gamelist entries are removed as well." : "", "This can't be undone."].filter(Boolean).join("\n\n") });
    if (!ok) return;
    try {
      const r = await call("holding_delete", { ids: games.map((g) => g.id), forget });
      H.data = r.holding; H.sel.clear();
      if (r.disk) $("free").textContent = human(r.disk.free);
      fill();
      if (r.failed.length) failures("Some files weren't deleted", r.failed);
      else toast(`Deleted ${plural(games.length, "game")}`);
    } catch (e) { oops(e); }
  }
  $("h-delete").onclick = () => del(shown().filter((g) => H.sel.has(g.id)), "the selected games");
  $("h-empty").onclick = () => del(shown().filter((g) => g.dest === "to_delete"),
    "everything in to_delete" + (H.system === "All" ? "" : ` for ${H.system}`));
  fill();
}

// ---------- restore a whole Move ----------
async function openMoves() {
  const M = { runs: await call("moves"), sel: new Set(), changed: false };
  sheet(`
    <div class="sheet-head"><h2>Restore a move</h2>
      <p>Every Move is logged. Restoring puts its files (and any RPCS3 / Vita3K data that went with them) back where they came from.</p></div>
    <div class="table moves" id="m-table"></div>
    <div class="sheet-foot"><span class="grow" id="m-sum"></span>
      <button class="ghost" id="m-close">Close</button><button class="primary" id="m-restore">Restore selected</button></div>`,
  "", () => M.changed && rescanQuietly());
  function fill() {
    $("m-table").innerHTML = `<div class="trow head"><span></span><span>When</span><span>System</span><span>Moved to</span><span class="num">Games</span><span class="num">Still in holding</span></div>` +
      (M.runs.length ? M.runs.map((r) => `<div class="trow${M.sel.has(r.id) ? " on" : ""}" data-id="${r.id}">
        <input type="checkbox"${M.sel.has(r.id) ? " checked" : ""}><span>${esc(when(r.time))}</span><span class="dim">${esc(r.system)}</span>
        <span class="dim">${esc(r.dest)}</span><span class="num">${r.games.toLocaleString()} · ${human(r.size)}</span>
        <span class="num">${r.left} / ${plural(r.files, "file")}</span></div>`).join("")
        : `<div class="none">Nothing logged yet.</div>`);
    $("m-restore").disabled = !M.sel.size;
    $("m-sum").textContent = M.sel.size ? `${M.sel.size} selected` : "";
  }
  $("m-table").addEventListener("click", (e) => {
    const row = e.target.closest(".trow[data-id]");
    if (!row) return;
    const id = Number(row.dataset.id);
    M.sel.has(id) ? M.sel.delete(id) : M.sel.add(id);
    fill();
  });
  $("m-close").onclick = closeSheet;
  $("m-restore").onclick = async () => {
    try {
      const r = await call("restore_moves", { ids: [...M.sel] });
      M.runs = await call("moves"); M.sel.clear(); M.changed = true;
      fill();
      if (r.failed.length) failures(`Put ${plural(r.back, "file")} back; ${r.failed.length} couldn't be`, r.failed);
      else toast(`Put ${plural(r.back, "file")} back`);
    } catch (e) { oops(e); }
  };
  fill();
}

// ---------- region priority ----------
async function openPriority() {
  await flushDecide();
  const P = await call("region_priority");
  let order = [...P.order], drag = null;
  sheet(`
    <div class="sheet-head"><h2>Region priority</h2>
      <p>Region dupes keeps the copy whose region is highest here. Drag to reorder, or use the arrows.</p></div>
    <div class="prio" id="p-list"></div>
    <div class="sheet-foot"><button class="ghost" id="p-reset">Reset to default</button><span class="grow"></span>
      <button class="ghost" id="p-cancel">Cancel</button><button class="primary" id="p-apply">Apply</button></div>`, "small");
  function fill() {
    $("p-list").innerHTML = order.map((r, i) => `<div class="prio-row" draggable="true" data-i="${i}">
      <span class="rank">${i + 1}</span><span>${esc(r)} <small>${P.counts[r] ? plural(P.counts[r], "game") : "none here"}</small></span>
      <button data-up="${i}" title="Up"${i ? "" : " disabled"}>↑</button><button data-down="${i}" title="Down"${i < order.length - 1 ? "" : " disabled"}>↓</button></div>`).join("");
  }
  const swap = (a, b) => { [order[a], order[b]] = [order[b], order[a]]; fill(); };
  const list = $("p-list");
  list.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (b?.dataset.up) swap(Number(b.dataset.up), Number(b.dataset.up) - 1);
    if (b?.dataset.down) swap(Number(b.dataset.down), Number(b.dataset.down) + 1);
  });
  list.addEventListener("dragstart", (e) => { drag = Number(e.target.closest(".prio-row").dataset.i); e.target.classList.add("drag"); });
  list.addEventListener("dragover", (e) => {
    e.preventDefault();
    list.querySelectorAll(".over").forEach((x) => x.classList.remove("over"));
    e.target.closest(".prio-row")?.classList.add("over");
  });
  list.addEventListener("drop", (e) => {
    e.preventDefault();
    const to = e.target.closest(".prio-row");
    if (drag == null || !to) return fill();
    const [r] = order.splice(drag, 1);
    order.splice(Number(to.dataset.i), 0, r);
    drag = null;
    fill();
  });
  list.addEventListener("dragend", () => { drag = null; fill(); });
  $("p-reset").onclick = () => {
    const low = P.default.map((x) => x.toLowerCase());
    order = [...P.default, ...order.filter((r) => !low.includes(r.toLowerCase()))];
    fill();
  };
  $("p-cancel").onclick = closeSheet;
  $("p-apply").onclick = async () => {
    try {
      applyDecision(await call("set_region_priority", { order }));
      closeSheet();
      toast(`Region dupes now prefer ${order.slice(0, 2).join(", then ")}`);
    } catch (e) { oops(e); }
  };
  fill();
}

// ---------- which LaunchBox game is this? ----------
async function openMatch(key) {
  const g = S.byKey.get(key);
  let res = null, sel = null, timer = null, seq = 0;
  sheet(`
    <div class="sheet-head"><h2>Which ${esc(S.sys.platform)} game is this?</h2><p id="x-now"></p></div>
    <div class="sheet-tools"><input type="text" id="x-q" spellcheck="false"></div>
    <div class="table matches" id="x-table"></div>
    <div class="sheet-foot"><button class="ghost" id="x-none">Not in LaunchBox</button>
      <button class="ghost" id="x-auto" hidden>Back to automatic</button><span class="grow"></span>
      <button class="ghost" id="x-cancel">Cancel</button><button class="primary" id="x-use" disabled>Use selected</button></div>`);
  async function search() {
    const n = ++seq;
    try {
      const r = await call("match_search", { key, query: $("x-q").value });
      if (n !== seq) return;
      res = r;
      sel = r.results.some((x) => x.id === r.current) ? r.current : r.results[0]?.id ?? null;
      fill();
    } catch (e) { oops(e); closeSheet(); }
  }
  function fill() {
    const now = g.rating != null || g.genres.length ? "matched" : "no match";
    $("x-now").textContent = `${g.label}  ·  now: ${res.kind === "manual" ? "picked by hand" : res.kind || now}` +
      (res.same_title > 1 ? `  ·  applies to all ${res.same_title} versions titled “${res.title}”` : "");
    $("x-auto").hidden = res.kind !== "manual";
    $("x-table").innerHTML = `<div class="trow head"><span>LaunchBox game</span><span>Rating</span><span>Genre</span></div>` +
      (res.results.length ? res.results.map((x) => `<div class="trow${x.id === sel ? " on" : ""}" data-id="${esc(x.id)}">
        <span class="nm">${esc(x.name)}${x.aka ? ` <span class="dim">(aka ${esc(x.aka)})</span>` : ""}</span>
        <span class="dim">${x.rating == null ? "—" : `★ ${x.rating.toFixed(1)} (${x.votes})`}</span>
        <span class="dim">${esc(x.genres.join(", "))}</span></div>`).join("") : `<div class="none">No LaunchBox games match.</div>`);
    $("x-use").disabled = sel == null;
    $("x-table").querySelector(".trow.on")?.scrollIntoView({ block: "nearest" });
  }
  const use = async (gid, clear = false) => { closeSheet(); try { await setMatch(key, gid, clear); } catch (e) { oops(e); } };
  $("x-q").value = res?.title || g.title;
  $("x-q").oninput = () => { clearTimeout(timer); timer = setTimeout(search, 250); };
  $("x-q").onkeydown = (e) => {
    if (e.key === "Enter" && sel != null) use(sel);
    if (!res || !["ArrowDown", "ArrowUp"].includes(e.key)) return;
    const i = res.results.findIndex((x) => x.id === sel) + (e.key === "ArrowDown" ? 1 : -1);
    if (res.results[i]) { sel = res.results[i].id; fill(); }
    e.preventDefault();
  };
  $("x-table").addEventListener("click", (e) => { const row = e.target.closest(".trow[data-id]"); if (row) { sel = row.dataset.id; fill(); } });
  $("x-table").addEventListener("dblclick", (e) => { const row = e.target.closest(".trow[data-id]"); if (row) use(row.dataset.id); });
  $("x-use").onclick = () => use(sel);
  $("x-none").onclick = () => use(null);
  $("x-auto").onclick = () => use(null, true);
  $("x-cancel").onclick = closeSheet;
  $("x-q").focus();
  $("x-q").select();
  await search();
}
