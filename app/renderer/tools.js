// Tools from the ☰ menu: Scrape metadata and Rename files. (Uses app.js and sheets.js: call, runJob, sheet …)
"use strict";

const pickedKeys = () => L().items.filter((g) => S.marked.has(g.key)).map((g) => g.key);

// A row of radio buttons for which games a tool works on. scopes: [[value, label, keys]]
function scopeRadios(name, scopes, current) {
  return scopes.map(([v, label, keys]) => `<label class="check"><input type="radio" name="${name}" value="${v}"
    ${v === current ? "checked" : ""}${keys.length ? "" : " disabled"}> ${esc(label)}</label>`).join("");
}

function setProgress(barId, textId, p) {
  if (!$(barId)) return;
  $(barId).style.width = `${p.total ? (100 * p.done) / p.total : 0}%`;
  $(textId).textContent = p.message;
}

// ---------- Scrape metadata ----------
registerTool({ cmd: "scrape", group: "system", label: "Scrape metadata…", sub: "LaunchBox text and artwork for ES-DE", system: true, open: () => openScrape() });
registerTool({ cmd: "rename", group: "system", label: "Rename files…", sub: "to No-Intro style names, undoable", system: true, open: () => openRename() });

async function openScrape() {
  await flushDecide();
  const info = await call("scrape_info");
  if (!info.platform) { toast("Pick a LaunchBox platform for this system first", { error: true }); return; }
  if (!info.has_details) {
    overlay(`<h2>LaunchBox data needs updating</h2><p>The scraper needs descriptions and image lists that older downloads don't include. Download LaunchBox data again from the ☰ menu.</p>`,
      [["OK", closeOverlay, true]]);
    return;
  }
  const linked = new Set(info.linked), close = new Set(info.close);
  const picked = pickedKeys();
  const scopes = [["keep", "Keeping list", S.games.filter((g) => !g.move).map((g) => g.key)],
    ["all", "All games", S.games.map((g) => g.key)], ["picked", "Marked games", picked]];
  const label = ([v, name, keys]) => {
    const l = keys.filter((k) => linked.has(k)).length, c = keys.filter((k) => close.has(k)).length;
    return [v, `${name}: ${plural(keys.length, "game")}, ${l.toLocaleString()} matched in LaunchBox${c ? ` (+${c} close)` : ""}`, keys];
  };
  let job = null, ran = false;
  sheet(`
    <div class="sheet-head"><h2>Scrape ${esc(S.sys.fullname)} from LaunchBox</h2>
      <p>Fills gaps: existing images are never replaced, text only if you tick that below, and play counts, favorites and hidden flags are left alone.</p></div>
    <div class="form">
      <div class="label">Games</div>
      ${scopeRadios("s-scope", scopes.map(label), picked.length ? "picked" : "keep")}
      <div class="label">What to fill</div>
      <label class="check"><input type="checkbox" id="s-text" checked> Text: name, description, developer, publisher, release date, players, genre, rating</label>
      <div class="grid2">${info.media.map((m) => `<label class="check"><input type="checkbox" data-media="${m.type}"${m.default ? " checked" : ""}> ${esc(m.label)}</label>`).join("")}</div>
      <label class="check"><input type="checkbox" id="s-close"> Also scrape close (fuzzy) matches; check them in the details panel first</label>
      <label class="check"><input type="checkbox" id="s-over"> Replace existing text with LaunchBox's</label>
      <p class="note">Videos and miximages aren't in LaunchBox's free data. Afterwards, in ES-DE: Scraper → Content to scrape → only Videos, and Scraper → Other settings → Miximage settings → Offline generator.</p>
      ${info.es_de_running ? `<p class="note warn">RetroDECK / ES-DE is running. It rewrites gamelist.xml when it quits, so text can't be saved until you close it. Images are fine to download now.</p>` : ""}
      <div class="progress-bar"><div id="s-bar"></div></div>
      <div class="progress-text" id="s-status"></div>
    </div>
    <div class="sheet-foot"><span class="grow"></span><button class="ghost" id="s-close-btn">Close</button><button class="primary" id="s-start">Start</button></div>`,
  "small wide form-sheet", () => { job?.stop(); if (ran) rescanQuietly(); });
  $("s-close-btn").onclick = closeSheet;
  $("s-start").onclick = async () => {
    if (job) { job.stop(); $("s-start").disabled = true; $("s-start").textContent = "Stopping…"; return; }
    const scope = document.querySelector('input[name="s-scope"]:checked').value;
    const keys = scopes.find(([v]) => v === scope)[2];
    const media = [...document.querySelectorAll("[data-media]:checked")].map((b) => b.dataset.media);
    const text = $("s-text").checked, useClose = $("s-close").checked;
    if (!text && !media.length) return;
    $("s-start").textContent = "Stop";
    $("s-status").textContent = "Preparing…";
    $("s-status").scrollIntoView({ block: "nearest" });
    job = runJob("scrape", { keys, text, media, close: useClose, overwrite: $("s-over").checked }, (p) => setProgress("s-bar", "s-status", p));
    try {
      const r = await job.done;
      ran = true;
      if ($("s-status")) {
        $("s-bar").style.width = "100%";
        $("s-status").textContent = `${r.stopped ? "Stopped early. " : ""}Filled ${r.text} text fields (${r.added || 0} new gamelist entries), ` +
          `downloaded ${r.images} images. ${r.skipped} already had that image, ${r.missing} not in LaunchBox, ${r.failed} failed. ` +
          `${r.unmatched} games had no ${useClose ? "" : "exact "}LaunchBox match (right-click a game to pick one).`;
        $("s-status").scrollIntoView({ block: "nearest" });
      }
    } catch (e) {
      if ($("s-status")) $("s-status").textContent = `Failed: ${e.message}`;
    }
    job = null;
    if ($("s-start")) { $("s-start").disabled = false; $("s-start").textContent = "Start"; }
  };
}

// ---------- Rename files ----------
async function openRename() {
  await flushDecide();
  const info = await call("rename_info");
  if (info.arcade) {
    overlay(`<h2>Arcade games keep their names</h2><p>MAME and FinalBurn find arcade games by their ROM set's file name (like gridlee.zip), so renaming them would stop them starting. ES-DE shows their full titles anyway.</p>`,
      [["OK", closeOverlay, true]]);
    return;
  }
  const picked = pickedKeys();
  const scopes = [["all", `All games (${S.games.length.toLocaleString()})`, S.games.map((g) => g.key)],
    ["keep", `Keeping list (${S.games.filter((g) => !g.move).length.toLocaleString()})`, S.games.filter((g) => !g.move).map((g) => g.key)],
    ["picked", `Marked (${picked.length})`, picked]];
  let plan = null, timer = null, seq = 0, renamed = false;
  sheet(`
    <div class="sheet-head"><h2>Rename files to a pattern</h2>
      <p>ES-DE media and gamelist entries are renamed along with each game, so play counts, favorites, scraped text and images stay with it. File names inside .cue / .m3u files are updated too.</p></div>
    <div class="sheet-tools"><input type="text" id="n-tpl" class="mono" spellcheck="false">${scopeRadios("n-scope", scopes, picked.length ? "picked" : "all")}</div>
    <div class="fields">${Object.entries(info.fields).map(([k, v]) => `<code>{${esc(k)}}</code> ${esc(v)}`).join(" · ")}. Disc / Track parts and the extension are always kept.</div>
    <div class="sheet-tools"><label class="check"><input type="checkbox" id="n-fix" checked> Use the LaunchBox name as {title} for games matched by hand or whose file name isn't a proper title (e.g. Final_Fantasy_IV_US)</label></div>
    <div class="table renames" id="n-table"></div>
    <div class="sheet-foot"><span class="grow" id="n-sum"></span>
      <label class="check"><input type="checkbox" id="n-same"> Show unchanged</label>
      <button class="ghost" id="n-undo">Undo…</button><button class="ghost" id="n-close">Close</button><button class="primary" id="n-go">Rename</button></div>`,
  "", () => renamed && rescanQuietly());
  const keys = () => scopes.find(([v]) => v === document.querySelector('input[name="n-scope"]:checked').value)[2];
  async function refresh() {
    const n = ++seq;
    try {
      const p = await call("rename_plan", { template: $("n-tpl").value, keys: keys(), fix_titles: $("n-fix").checked });
      if (n !== seq || !$("n-table")) return;
      plan = p;
      fill();
    } catch (e) { oops(e); }
  }
  function fill() {
    const rows = plan.rows.filter((r) => r.status !== "same" || $("n-same").checked);
    $("n-table").innerHTML = `<div class="trow head"><span>Now</span><span>Becomes</span><span></span></div>` +
      (rows.length ? rows.slice(0, 3000).map((r) => {
        const ok = r.status === "rename" || r.status === "same";
        return `<div class="trow"><span class="nm" title="${esc(r.old)}">${esc(r.old)}</span>
          <span class="nm" title="${esc(ok ? r.new : "")}">${ok ? esc(r.new) : ""}</span><span class="dim${ok ? "" : " bad"}">${ok ? "" : esc(r.status)}</span></div>`;
      }).join("") : `<div class="none">Every file already matches the pattern.</div>`);
    $("n-sum").textContent = `${plural(plan.rename, "file")} to rename · ${plan.same.toLocaleString()} already match · ${plan.skip.toLocaleString()} skipped`;
    $("n-go").disabled = !plan.rename;
  }
  $("n-tpl").value = info.template;
  $("n-tpl").oninput = () => { clearTimeout(timer); timer = setTimeout(refresh, 250); };
  document.querySelectorAll('input[name="n-scope"]').forEach((r) => (r.onchange = refresh));
  $("n-fix").onchange = refresh;
  $("n-same").onchange = () => plan && fill();
  $("n-close").onclick = closeSheet;
  $("n-undo").onclick = () => { closeSheet(); openRenameUndo(); };
  $("n-go").onclick = async () => {
    const ok = await confirmBox({ title: "Rename files", ok: "Rename", message: `Rename ${plural(plan.rename, "file")}?`,
      detail: "You can undo this later with Undo… in this window." });
    if (!ok) return;
    try {
      busy(`Renaming ${plural(plan.rename, "file")}…`);
      const res = await call("rename_apply", { template: $("n-tpl").value, keys: keys(), fix_titles: $("n-fix").checked });
      closeOverlay();
      loadSystem(res);
      renamed = false;  // (just opened again)
      const r = res.renamed, esde = `ES-DE: renamed ${r.media.toLocaleString()} media files and ${r.entries.toLocaleString()} gamelist entries.`;
      if (r.failed.length) failures(`Renamed ${plural(r.files, "file")}, ${r.failed.length} problems`, [...r.failed, esde]);
      else toast(`Renamed ${plural(r.files, "file")}. ${esde}`);
      refresh();
    } catch (e) { closeOverlay(); oops(e); }
  };
  refresh();
  $("n-tpl").focus();
}

async function openRenameUndo() {
  const U = { runs: await call("rename_runs"), sel: new Set(), changed: false };
  sheet(`
    <div class="sheet-head"><h2>Put old file names back</h2><p>Every rename run is logged. Undo newer runs first if the same games were renamed more than once.</p></div>
    <div class="table runs" id="u-table"></div>
    <div class="sheet-foot"><span class="grow"></span><button class="ghost" id="u-close">Close</button><button class="primary" id="u-go">Undo selected</button></div>`,
  "", () => U.changed && rescanQuietly());
  function fill() {
    $("u-table").innerHTML = `<div class="trow head"><span></span><span>When</span><span>System</span><span>Pattern</span><span class="num">Still renamed</span></div>` +
      (U.runs.length ? U.runs.map((r) => `<div class="trow${U.sel.has(r.id) ? " on" : ""}" data-id="${r.id}"><input type="checkbox"${U.sel.has(r.id) ? " checked" : ""}>
        <span>${esc(when(r.time))}</span><span class="dim">${esc(r.system)}</span><span class="dim mono">${esc(r.template)}</span>
        <span class="num">${r.left} / ${plural(r.files, "file")}</span></div>`).join("") : `<div class="none">Nothing logged yet.</div>`);
    $("u-go").disabled = !U.sel.size;
  }
  $("u-table").addEventListener("click", (e) => {
    const row = e.target.closest(".trow[data-id]");
    if (!row) return;
    const id = Number(row.dataset.id);
    U.sel.has(id) ? U.sel.delete(id) : U.sel.add(id);
    fill();
  });
  $("u-close").onclick = closeSheet;
  $("u-go").onclick = async () => {
    try {
      const r = await call("rename_undo", { ids: [...U.sel] });
      U.runs = await call("rename_runs"); U.sel.clear(); U.changed = true;
      fill();
      if (r.failed.length) failures(`Undid ${plural(r.back, "rename")}, ${r.failed.length} problems`, r.failed);
      else toast(`Put back ${plural(r.back, "file name")}`);
    } catch (e) { oops(e); }
  };
  fill();
}
