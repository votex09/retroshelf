// The new RetroShelf window, phase 1: finds the ROMs folder and lists its systems, all through the Python helper.
"use strict";

const $ = (id) => document.getElementById(id);
const rs = window.retroshelf;
let roms = "";

function gb(bytes) { return `${(bytes / 1024 ** 3).toFixed(1)} GB`; }

function showMessage(text, error = false) {
  const m = $("message");
  m.hidden = !text;
  m.textContent = text || "";
  m.classList.toggle("error", error);
}

async function load(folder) {
  roms = folder;
  $("roms").textContent = folder || "No ROMs folder found yet. Pick yours with Change…";
  $("systems").innerHTML = "";
  showMessage("");
  if (!folder) return { roms: "", systems: 0 };
  const [systems, disk] = await Promise.all([rs.call("systems", { roms: folder }), rs.call("disk", { path: folder })]);
  if (disk) {
    $("space").hidden = false;
    $("free").textContent = gb(disk.free);
    requestAnimationFrame(() => ($("space-ring").style.strokeDashoffset = 94.25 * (disk.free / disk.total)));
  }
  const withGames = systems.filter((s) => s.games > 0);
  if (!withGames.length) showMessage("No games in this folder yet.");
  withGames.forEach((s, i) => {
    const card = document.createElement("div");
    card.className = "system";
    card.style.animationDelay = `${Math.min(i, 20) * 25}ms`;
    card.innerHTML = `<span class="tag"></span><span class="name"></span><span class="count"></span>`;
    card.querySelector(".tag").textContent = s.code;
    card.querySelector(".name").textContent = s.name === "?" ? "" : s.name;  // "?": no systeminfo.txt to name it
    card.querySelector(".count").textContent = `${s.games} ${s.games === 1 ? "game" : "games"}`;
    $("systems").appendChild(card);
  });
  return { roms: folder, systems: withGames.length };
}

async function start() {
  rs.version().then((v) => ($("version").textContent = `v${v} preview`));
  rs.onHelperExit((info) => showMessage(`RetroShelf's helper stopped, so nothing can load.\n\n${info.error || info.stderr || ""}`, true));
  $("change").onclick = async () => {
    const folder = await rs.pickFolder(roms);
    if (!folder) return;
    load(folder).catch((e) => showMessage(e.message, true));
    rs.saveSettings({ roms: folder });
  };
  try {
    const hello = await rs.call("hello");
    const settings = await rs.settings();
    const folder = settings.roms || (await rs.call("roms_folder"));
    const summary = await load(folder);
    rs.ready({ ...summary, python: hello.python, frozen: hello.frozen });
  } catch (e) {
    showMessage(e.message, true);
  }
}

start();
