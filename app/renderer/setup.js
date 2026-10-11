// First-run setup: install RetroDECK (Linux) or ES-DE (Windows), then use its ROMs folder. Opens by itself when
// no ROMs folder can be found, and from the ☰ menu. (Uses app.js and sheets.js: call, runJob, sheet …)
"use strict";

const SETUP_NAME = /Windows/.test(navigator.userAgent) ? "ES-DE" : "RetroDECK";
registerTool({ cmd: "setup", label: `Set up ${SETUP_NAME}…`, sub: "install it and use its ROMs folder", anywhere: true, open: () => openSetup() });

async function openSetup() {
  let info;
  try { info = await call("setup_info"); } catch (e) { oops(e); return; }
  let job = null, pollTimer = null, custom = null, finished = false;
  const stopPolling = () => { clearTimeout(pollTimer); pollTimer = null; };
  const done = async (roms) => {  // not offered by itself again; with roms: use it
    stopPolling();
    try {
      const res = await call("setup_done", roms ? { roms } : {});
      if (roms) { finished = true; S.overview = res; showOverview(); }
      return res;
    } catch (e) { oops(e); }
  };
  const foot = (left, right) => `<div class="sheet-foot">${left || ""}<span class="grow"></span>${right}</div>`;
  const page = (title, intro, body, footer) => {
    $("sheet").innerHTML = `<div class="sheet-head"><h2>${esc(title)}</h2>${intro ? `<p>${esc(intro)}</p>` : ""}</div>
      <div class="form setup">${body}</div>${footer}`;
  };
  const haveRoms = `<button class="ghost" id="u-have">I already have a ROMs folder…</button>`;
  const wireHave = () => ($("u-have").onclick = async () => {
    closeSheet();
    try { if (await pickRoms()) toggleSystems(); } catch (e) { oops(e); }
  });

  sheet("", "small wide form-sheet", async () => {
    stopPolling();
    if (!finished) await done();
  });
  choose();

  function choose() {
    const intro = info.windows
      ? "ES-DE is the game menu you play from. RetroShelf downloads its official portable version (about 160 MB) into the folder you pick, with your games in its ROMs folder. ES-DE doesn't include emulators: once it's set up, add the ones you want (RetroShelf shows you where)."
      : "RetroDECK is the game menu you play from, with its emulators included. RetroShelf installs it from Flathub for your user (a download of a few GB, no password needed), then starts its first-time setup, which puts a retrodeck folder (games, BIOS, saves) where you choose.";
    const found = info.found ? `<div class="found"><span>${esc(info.name)} is already set up here:<br><code>${esc(info.found)}</code></span>
      <button class="primary" id="u-use">Use this folder</button></div>` : "";
    if (!info.flatpak) {
      page(`Set up ${info.name}`, intro, `${found}<p>Flatpak isn't installed, and RetroDECK needs it. Flathub's guide shows the one command for your Linux distribution; then come back and press Check again.</p>`,
        foot(haveRoms, `<button class="ghost" id="u-guide">Open Flathub's setup guide ↗</button><button class="primary" id="u-again">Check again</button>`));
      $("u-guide").onclick = () => rs.openUrl(info.flatpak_guide);
      $("u-again").onclick = async () => { try { info = await call("setup_info"); choose(); } catch (e) { oops(e); } };
    } else {
      const free = (n) => (n == null ? "?" : human(n));
      const rows = info.choices.map((c, i) => `<label class="check place"><input type="radio" name="u-place" value="${i}"${i ? "" : " checked"}>
        <span>${esc(c.label)}</span><span class="dim">${free(c.free)} free</span><span class="dim nm">${esc(c.folder)}</span></label>`).join("");
      page(`Set up ${info.name}`, intro, `${found}
        <div class="label">Where should your games go?</div>
        <div class="places">${rows}<label class="check place"><input type="radio" name="u-place" value="custom">
          <span>Another folder…</span><span class="dim" id="u-custom-free"></span><span class="dim nm" id="u-custom"></span></label></div>
        <p id="u-target"></p>
        ${info.windows ? `<label class="check"><input type="checkbox" id="u-shortcut" checked> Add ES-DE to the Start menu</label>` : ""}`,
      foot(haveRoms, `<button class="ghost" id="u-cancel">Cancel</button><button class="primary" id="u-install">Install</button>`));
      const picked = () => {
        const v = document.querySelector('input[name="u-place"]:checked').value;
        return v === "custom" ? custom : info.choices[Number(v)];
      };
      const target = () => { const c = picked(); $("u-target").textContent = c ? `Your games will go in:  ${c.games}` : ""; };
      document.querySelectorAll('input[name="u-place"]').forEach((r) => (r.onchange = async () => {
        if (r.value === "custom") {
          const folder = await rs.pickFolder(custom?.folder || info.home, "Where should your games go?");
          if (folder) {
            custom = { kind: "custom", ...(await call("setup_target", { folder })) };
            $("u-custom").textContent = custom.folder;
            $("u-custom-free").textContent = `${free(custom.free)} free`;
          } else if (!custom) document.querySelector('input[name="u-place"]').checked = true;
        }
        target();
      }));
      target();
      $("u-cancel").onclick = closeSheet;
      $("u-install").onclick = () => install(picked(), $("u-shortcut")?.checked ?? true);
    }
    wireHave();
    if (info.found) $("u-use").onclick = () => finish(info.found, []);
  }

  async function install(place, shortcut) {
    page(`Installing ${info.name} …`, "", `<div class="progress-bar"><div id="u-bar" class="indeterminate"></div></div>
      <div class="progress-text" id="u-status"></div><pre class="log" id="u-log"></pre>`,
    foot("", `<button class="ghost" id="u-stop">Cancel</button>`));
    sheetBusy = async () => {
      if (!(await rs.confirm({ title: `Set up ${info.name}`, message: `Stop setting up ${info.name}?`, ok: "Stop" }))) return;
      job?.stop();
    };
    $("u-stop").onclick = sheetBusy;
    job = runJob("setup_install", { kind: place.kind, folder: place.folder, shortcut }, (p) => {
      if (!$("u-log")) return;
      if (p.message) {
        $("u-log").textContent += p.message + "\n";
        $("u-log").scrollTop = $("u-log").scrollHeight;
        $("u-status").textContent = p.message.slice(0, 200);
      }
      if (p.total) { $("u-bar").classList.remove("indeterminate"); $("u-bar").style.width = `${(100 * p.done) / p.total}%`; }
    });
    let res;
    try {
      res = await job.done;
    } catch (e) {
      res = { error: e.message };
    }
    job = null;
    sheetBusy = null;
    if (!$("u-log")) return;
    if (res.stopped) { closeSheet(); return; }
    if (res.error) {
      $("u-bar").classList.remove("indeterminate");
      $("u-status").textContent = `Setup stopped: ${res.error}`;
      $("u-log").textContent += `Error: ${res.error}\n`;
      $("sheet").querySelector(".sheet-foot").innerHTML = `<span class="grow"></span><button class="ghost" id="u-back">Back</button><button class="ghost" id="u-close">Close</button>`;
      $("u-back").onclick = choose;
      $("u-close").onclick = closeSheet;
      return;
    }
    if (res.roms) finish(res.roms, res.notes);
    else firstRun(place, res);
  }

  // RetroDECK's own first-time setup runs in its window; RetroShelf waits for the ROMs folder it makes.
  function firstRun(place, res) {
    page("RetroDECK's first-time setup", "RetroDECK is installed and now runs its own setup in a new window. It asks where to put its data, so answer it like this:",
      `<ol class="steps">${res.steps.map((s) => `<li>${esc(s).replace(/\n/g, "<br>")}</li>`).join("")}</ol>
      <p class="dim">Then answer its other questions as you like. When it finishes it opens the game menu; RetroShelf picks up the new ROMs folder by itself.</p>
      <p id="u-wait"><span class="spinner small"></span> Waiting for RetroDECK's setup to finish …</p>`,
    foot(place.kind !== "home" ? `<button class="ghost" id="u-copy">Copy folder</button>` : "",
      `<button class="ghost" id="u-cancel">Cancel</button><button class="ghost" id="u-launch">Start RetroDECK again</button>`));
    const copy = () => navigator.clipboard.writeText(place.folder).catch(() => {});
    const launch = () => call("setup_launch").catch((e) => ($("u-wait").textContent = `Couldn't start RetroDECK: ${e.message}`));
    if ($("u-copy")) { $("u-copy").onclick = copy; copy(); }
    $("u-cancel").onclick = closeSheet;
    $("u-launch").onclick = launch;
    launch();
    const poll = async () => {
      pollTimer = null;
      if (!$("u-wait")) return;
      let roms = "";
      try { roms = await call("setup_poll"); } catch (e) { console.error(e); }
      if (!$("u-wait")) return;
      if (!roms) { pollTimer = setTimeout(poll, 2000); return; }
      const norm = (p) => p.replace(/[\\/]+$/, "");
      finish(roms, norm(roms) === norm(res.expected) ? [] : ["RetroDECK put its folder somewhere else than planned, so RetroShelf uses where it went."]);
    };
    pollTimer = setTimeout(poll, 2000);
  }

  async function finish(roms, notes) {
    const res = await done(roms);
    if (!res) return;
    page(`${info.name} is set up`, "", `<p>Your games go in:<br><code>${esc(res.roms)}</code></p>
      <ul class="tips">${[...notes, ...(res.tips || [])].map((t) => `<li>${esc(t)}</li>`).join("")}</ul>`,
    foot("", `${info.windows ? `<button class="ghost" id="u-guide">ES-DE user guide ↗</button>` : ""}<button class="primary" id="u-close">Close</button>`));
    if ($("u-guide")) $("u-guide").onclick = () => rs.openUrl(info.guide);
    $("u-close").onclick = () => { closeSheet(); toggleSystems(); };
    toast(`${info.name} is set up. Games go in ${res.roms}.`);
  }
}
