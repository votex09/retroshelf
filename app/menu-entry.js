// The Linux app menu entry (~/.local/share/applications/retroshelf.desktop) for the AppImage, which has no installer
// to add one. Updates rename the AppImage (RetroShelf-<version>-linux-x86_64.AppImage), so the entry is pointed at
// the new file when an update goes in, and mended at start when it names one that's gone.
const fs = require("fs");
const path = require("path");

const quote = (a) => `"${a.replace(/["`$\\]/g, (c) => "\\" + c)}"`;

function entryText(exe, icon) {
  return ["[Desktop Entry]", "Type=Application", "Name=RetroShelf", "GenericName=ROM library manager",
    "Comment=Prune, scrape, rename and install games for ES-DE / RetroDECK", `Exec=${quote(exe)} %U`, `Icon=${icon}`,
    "Terminal=false", "Categories=Game;", "Keywords=ROM;ES-DE;RetroDECK;emulation;LaunchBox;NoPayStation;",
    "StartupWMClass=RetroShelf", ""].join("\n");
}

// The program an entry starts (Exec's first word, unquoted), or null.
function execOf(text) {
  const m = /^Exec=(.*)$/m.exec(text || "");
  if (!m) return null;
  const line = m[1].trim();
  if (line.startsWith('"')) {
    const q = /^"((?:\\.|[^"\\])*)"/.exec(line);
    return q ? q[1].replace(/\\(.)/g, "$1") : null;
  }
  return line.split(/\s+/)[0] || null;
}

// The version in a RetroShelf AppImage's name (RetroShelf-2026.1012.1-linux-x86_64.AppImage) as numbers, or null.
function versionOf(file) {
  const m = /^RetroShelf-(\d+)\.(\d+)\.(\d+)\b.*\.AppImage$/i.exec(path.basename(file));
  return m ? m.slice(1).map(Number) : null;
}
const older = (a, b) => { for (let i = 0; i < 3; i++) if (a[i] !== b[i]) return a[i] < b[i]; return false; };

// Should an entry that starts `was` be pointed at `exe` (this AppImage)? Yes when `was` is gone (an update renamed
// it, or it was moved), or when it's an older RetroShelf AppImage left in the same folder. Never backwards: running
// an older copy kept beside a newer one leaves the entry on the newer one.
function stale(was, exe, exists = fs.existsSync) {
  if (!was || was === exe) return false;
  if (!exists(was)) return true;
  const a = versionOf(was), b = versionOf(exe);
  return path.dirname(was) === path.dirname(exe) && Boolean(a && b) && older(a, b);
}

class MenuEntry {
  constructor(dataHome, iconSource) {
    this.file = path.join(dataHome, "applications", "retroshelf.desktop");
    this.icon = path.join(dataHome, "icons", "hicolor", "256x256", "apps", "retroshelf.png");
    this.iconSource = iconSource;
  }

  read() {
    try { return fs.readFileSync(this.file, "utf8"); } catch { return ""; }
  }

  write(exe) {
    fs.mkdirSync(path.dirname(this.icon), { recursive: true });
    fs.copyFileSync(this.iconSource, this.icon);
    fs.mkdirSync(path.dirname(this.file), { recursive: true });
    fs.writeFileSync(this.file, entryText(exe, this.icon));
  }

  // Point an existing entry at exe when it starts an AppImage that's gone or left behind. -> true when it did.
  mend(exe) {
    const text = this.read();
    if (!text || !stale(execOf(text), exe)) return false;
    this.write(exe);
    return true;
  }

  // An update put the new AppImage at `to` (and removed `from`): an entry that started `from` starts `to` now.
  moved(from, to) {
    const was = execOf(this.read());
    if (was && (was === from || stale(was, to))) this.write(to);
  }
}

module.exports = { MenuEntry, entryText, execOf, stale, versionOf };
