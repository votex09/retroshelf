// RetroShelf's Electron app: this window, with RetroShelf's Python code running behind it as a helper process.
//   npm install && npm start        run from a checkout (uses python3 for the helper)
//   npm run dist                    build an AppImage (Linux) or installer + portable .exe (Windows) into dist/
//   electron . --smoke              start, check the window and the helper work together, print SMOKE OK, quit
const { app, BrowserWindow, dialog, ipcMain, Menu, protocol, session, shell } = require("electron");
const fs = require("fs");
const path = require("path");
const { Helper } = require("./helper");
const { Updates } = require("./updates");

const smoke = process.argv.includes("--smoke");

// ---------- artwork and videos from disk ----------
// The window shows pictures and clips as rsmedia://file/<encoded path>. Only files the helper named (in a game's
// details or its list row) can be read this way, so the window can't open anything else on disk.
const media = new Set();
const MEDIA_TYPES = { ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
  ".webp": "image/webp", ".bmp": "image/bmp", ".mp4": "video/mp4", ".webm": "video/webm", ".mkv": "video/x-matroska",
  ".mov": "video/quicktime", ".avi": "video/x-msvideo" };
protocol.registerSchemesAsPrivileged([{ scheme: "rsmedia",
  privileges: { standard: true, secure: true, supportFetchAPI: true, stream: true } }]);

function allowMedia(result) {
  const add = (p) => { if (typeof p === "string" && p) media.add(path.resolve(p)); };
  if (!result || typeof result !== "object") return;
  if (Array.isArray(result.games)) for (const g of result.games) add(g?.thumb);
  if (Array.isArray(result.images)) for (const i of result.images) add(i?.path);
  add(result.video);
}

function serveMedia(request) {
  const file = path.resolve(decodeURIComponent(new URL(request.url).pathname.slice(1)));
  if (!media.has(file)) return new Response("Not found", { status: 404 });
  let size;
  try { size = fs.statSync(file).size; } catch { return new Response("Not found", { status: 404 }); }
  const type = MEDIA_TYPES[path.extname(file).toLowerCase()] || "application/octet-stream";
  const range = /bytes=(\d*)-(\d*)/.exec(request.headers.get("range") || "");
  const { Readable } = require("stream");
  if (range) {  // videos seek with byte ranges
    const start = range[1] ? Number(range[1]) : Math.max(0, size - Number(range[2]));
    const end = range[1] && range[2] ? Math.min(Number(range[2]), size - 1) : size - 1;
    if (start >= size || start > end) return new Response(null, { status: 416, headers: { "Content-Range": `bytes */${size}` } });
    return new Response(Readable.toWeb(fs.createReadStream(file, { start, end })), { status: 206, headers: {
      "Content-Type": type, "Content-Length": String(end - start + 1), "Content-Range": `bytes ${start}-${end}/${size}`,
      "Accept-Ranges": "bytes" } });
  }
  return new Response(Readable.toWeb(fs.createReadStream(file)), { headers: {
    "Content-Type": type, "Content-Length": String(size), "Accept-Ranges": "bytes" } });
}
let win = null;
let helper = null;

// ---------- the window ----------
function createWindow() {
  win = new BrowserWindow({
    width: 1280, height: 800, minWidth: 960, minHeight: 600, show: false,
    backgroundColor: "#0e1016", title: "RetroShelf",
    icon: path.join(__dirname, "renderer", "icon-256.png"),
    autoHideMenuBar: true,
    webPreferences: { preload: path.join(__dirname, "preload.js"), sandbox: true, contextIsolation: true },
  });
  win.once("ready-to-show", () => { if (!smoke) win.show(); });
  win.webContents.setWindowOpenHandler(({ url }) => {  // YouTube's player links to the video on YouTube
    if (/^https:\/\/(www\.)?(youtube\.com|youtu\.be)\//.test(url)) shell.openExternal(url);
    return { action: "deny" };
  });
  win.webContents.on("will-navigate", (e) => e.preventDefault());
  win.on("close", (e) => {  // an import going on: the window asks what to do first (file-tools.js)
    if (!jobRunning || closeOK || smoke) return;
    e.preventDefault();
    win.webContents.send("app:close-asked");
  });
  win.loadFile(path.join(__dirname, "renderer", "index.html"));
}

function startHelper() {
  helper = new Helper(app);
  helper.on("event", (name, data) => win && !win.isDestroyed() && win.webContents.send("helper:event", name, data));
  helper.on("exit", (info) => {
    if (app.isQuitting) return;
    if (win && !win.isDestroyed()) win.webContents.send("helper:exit", info);
    if (smoke) fail(`helper stopped: ${info.error || info.stderr}`);
  });
  helper.start().catch(() => {});  // a failed start arrives as "exit" too
}

ipcMain.handle("helper:call", async (_e, method, params) => {
  await helper.ready;
  const result = await helper.call(method, params);
  allowMedia(result);
  return result;
});
ipcMain.handle("pick-folder", async (_e, start, title) => {
  const r = await dialog.showOpenDialog(win, { title: title || "Your ROMs folder", defaultPath: start || undefined,
    properties: ["openDirectory", "createDirectory"] });
  return r.canceled ? null : r.filePaths[0];
});
ipcMain.handle("pick-files", async (_e, start, title) => {
  const r = await dialog.showOpenDialog(win, { title: title || "Add games", defaultPath: start || undefined,
    properties: ["openFile", "multiSelections"] });
  return r.canceled ? [] : r.filePaths;
});
ipcMain.handle("save-file", async (_e, opts) => {
  const r = await dialog.showSaveDialog(win, { title: opts.title, defaultPath: opts.name,
    filters: [{ name: "Text", extensions: ["txt"] }] });
  return r.canceled ? null : r.filePath;
});
ipcMain.handle("open-folder", (_e, folder) => {  // folders only: opening a file could run it
  try { if (!fs.statSync(folder).isDirectory()) return "not a folder"; } catch (e) { return e.message; }
  return shell.openPath(folder);
});
ipcMain.handle("open-url", (_e, url) => {  // web pages only, in the user's browser
  if (!/^https?:\/\//i.test(String(url))) return "not a web page";
  return shell.openExternal(url).then(() => "", (e) => e.message);
});
ipcMain.handle("app:version", () => app.getVersion());

// ---------- updates (updates.js) ----------
const updates = new Updates(app, (state) => win?.webContents.send("update", state));
ipcMain.handle("update:check", (_e, auto) => updates.check(Boolean(auto)));
ipcMain.handle("update:install", () => { closeOK = true; return updates.install(); });

// An import or a copy from a source going on in the background: closing the window asks first.
let jobRunning = false, closeOK = false;
ipcMain.on("app:busy", (_e, on) => { jobRunning = Boolean(on); });
ipcMain.on("app:quit", () => { closeOK = true; app.quit(); });

// ---------- the app menu entry (Linux AppImage: it has no installer to add one) ----------
const DESKTOP = path.join(process.env.XDG_DATA_HOME || path.join(app.getPath("home"), ".local", "share"));
const desktopFile = path.join(DESKTOP, "applications", "retroshelf.desktop");
ipcMain.handle("desktop:status", () => {
  if (process.platform !== "linux" || !process.env.APPIMAGE) return { can: false };
  let text = "";
  try { text = fs.readFileSync(desktopFile, "utf8"); } catch {}
  return { can: true, installed: text.includes(process.env.APPIMAGE) };
});
ipcMain.handle("desktop:install", () => {
  if (process.platform === "win32") {  // the old app's Start menu shortcut, pointed at this app (the installer's own has the same name)
    if (!app.isPackaged) return "only the built app can add itself";
    const exe = process.env.PORTABLE_EXECUTABLE_FILE || process.execPath;
    const lnk = path.join(app.getPath("appData"), "Microsoft", "Windows", "Start Menu", "Programs", "RetroShelf.lnk");
    const ok = shell.writeShortcutLink(lnk, fs.existsSync(lnk) ? "replace" : "create", { target: exe, args: "",
      cwd: path.dirname(exe), icon: exe, iconIndex: 0, description: "Prune, scrape, rename and install games for ES-DE / RetroDECK" });
    return ok ? "" : "the Start menu shortcut couldn't be written";
  }
  const exe = process.env.APPIMAGE;
  if (process.platform !== "linux" || !exe) return "only the AppImage can add itself";
  const icon = path.join(DESKTOP, "icons", "hicolor", "256x256", "apps", "retroshelf.png");
  fs.mkdirSync(path.dirname(icon), { recursive: true });
  fs.copyFileSync(path.join(__dirname, "renderer", "icon-256.png"), icon);
  fs.mkdirSync(path.dirname(desktopFile), { recursive: true });
  const quote = (a) => `"${a.replace(/["`$\\]/g, (c) => "\\" + c)}"`;
  fs.writeFileSync(desktopFile, ["[Desktop Entry]", "Type=Application", "Name=RetroShelf", "GenericName=ROM library manager",
    "Comment=Prune, scrape, rename and install games for ES-DE / RetroDECK", `Exec=${quote(exe)} %U`, `Icon=${icon}`,
    "Terminal=false", "Categories=Game;", "Keywords=ROM;ES-DE;RetroDECK;emulation;LaunchBox;NoPayStation;",
    "StartupWMClass=RetroShelf", ""].join("\n"));
  return "";
});

// ---------- --smoke: used by CI on the built app ----------
function fail(why) {
  console.error(`SMOKE FAILED: ${why}`);
  app.exit(1);
}
if (smoke) {
  ipcMain.on("renderer:ready", (_e, summary) => {
    console.log(`SMOKE OK ${JSON.stringify(summary)}`);
    app.isQuitting = true;
    helper.stop();
    app.exit(0);
  });
  setTimeout(() => fail("timed out"), 45000).unref();
} else {
  ipcMain.on("renderer:ready", () => {});
}

// ---------- start ----------
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => { if (win) { if (win.isMinimized()) win.restore(); win.focus(); } });
  Menu.setApplicationMenu(null);
  app.whenReady().then(() => {
    protocol.handle("rsmedia", serveMedia);
    // YouTube's embedded player refuses to play for a page without a web address (error 153), and this window is a
    // file: page, so its requests say where they come from: the project's page.
    session.defaultSession.webRequest.onBeforeSendHeaders({ urls: ["https://www.youtube-nocookie.com/*"] }, (d, done) =>
      done({ requestHeaders: { ...d.requestHeaders, Referer: "https://github.com/votex09/retroshelf" } }));
    startHelper();
    createWindow();
  });
  app.on("before-quit", () => { app.isQuitting = true; if (helper) helper.stop(); });
  app.on("window-all-closed", () => app.quit());
}
