// Updates from GitHub Releases. Every change that lands on main is released (.github/workflows/release.yml), tagged
// by date: v2026.10.11, then v2026.10.11.2 for a second one that day. The app's own version is the same date as a
// semver, 2026.1011.0 and 2026.1011.1 (tagVersion), so newer always compares higher.
//   The installed Windows app and the Linux AppImage update themselves through electron-updater: the new version
// downloads in the background and goes in when RetroShelf restarts. The portable .exe and a run from a checkout
// can't replace themselves, so they only say a new version is out and link to it.
const { net } = require("electron");

const REPO = "votex09/retroshelf";
const RELEASES = `https://github.com/${REPO}/releases/latest`;

function tagVersion(tag) {
  const m = /^v?(\d{4})\.(\d{1,2})\.(\d{1,2})(?:\.(\d+))?$/.exec(tag || "");
  return m ? `${Number(m[1])}.${Number(m[2]) * 100 + Number(m[3])}.${m[4] ? Number(m[4]) - 1 : 0}` : null;
}

function newer(a, b) {  // is version a newer than b?
  const pa = String(a).split(/[.-]/).map(Number), pb = String(b).split(/[.-]/).map(Number);
  for (let i = 0; i < 3; i++) if ((pa[i] || 0) !== (pb[i] || 0)) return (pa[i] || 0) > (pb[i] || 0);
  return false;
}

// Can this copy replace itself? (the installed Windows app or the AppImage, not the portable .exe or a checkout)
function selfUpdating(app) {
  if (!app.isPackaged || process.env.RETROSHELF_NO_UPDATES) return false;
  if (process.platform === "linux") return Boolean(process.env.APPIMAGE);
  return process.platform === "win32" && !process.env.PORTABLE_EXECUTABLE_DIR;
}

class Updates {
  constructor(app, send, log = console.log) {
    this.app = app;
    this.send = send;  // send(state): tells the window, see state()
    this.log = log;
    this.status = { state: "idle", version: "", url: RELEASES, self: selfUpdating(app) };
    this.updater = null;
  }

  set(fields) {
    Object.assign(this.status, fields);
    this.send({ ...this.status });
    return { ...this.status };
  }

  // -> { state: idle | checking | latest | available | downloading | ready | error, version, url, self, message }
  async check() {
    if (["checking", "downloading", "ready"].includes(this.status.state)) return { ...this.status };
    this.set({ state: "checking", message: "" });
    try {
      if (this.status.self) return await this.checkSelf();
      const res = await net.fetch(`https://api.github.com/repos/${REPO}/releases/latest`,
        { headers: { Accept: "application/vnd.github+json", "User-Agent": "RetroShelf" } });
      if (res.status === 404) return this.set({ state: "latest" });  // nothing released yet
      if (!res.ok) throw new Error(`GitHub answered ${res.status}`);
      const rel = await res.json();
      const version = tagVersion(rel.tag_name);
      return version && newer(version, this.app.getVersion())
        ? this.set({ state: "available", version, url: rel.html_url || RELEASES })
        : this.set({ state: "latest" });
    } catch (e) {
      this.log(`Update check failed: ${e.message}`);
      return this.set({ state: "error", message: e.message });
    }
  }

  async checkSelf() {
    if (!this.updater) {
      const { autoUpdater } = require("electron-updater");
      this.updater = autoUpdater;
      autoUpdater.logger = null;
      autoUpdater.autoDownload = true;
      autoUpdater.autoInstallOnAppQuit = true;
      autoUpdater.on("download-progress", (p) => this.set({ state: "downloading", percent: Math.round(p.percent) }));
      autoUpdater.on("update-downloaded", (info) => this.set({ state: "ready", version: info.version }));
      autoUpdater.on("error", (e) => {
        this.log(`Update failed: ${e.message}`);
        if (this.status.state !== "ready") this.set({ state: "error", message: e.message });
      });
    }
    const r = await this.updater.checkForUpdates();
    const version = r?.updateInfo?.version;
    if (version && newer(version, this.app.getVersion())) {
      return this.status.state === "ready" ? { ...this.status } : this.set({ state: "downloading", version, percent: 0 });
    }
    return this.set({ state: "latest" });
  }

  install() {
    if (this.status.state === "ready" && this.updater) {
      this.app.isQuitting = true;
      this.updater.quitAndInstall();
    }
  }
}

module.exports = { Updates, tagVersion, newer, selfUpdating };
