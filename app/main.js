// RetroShelf's Electron app: this window, with RetroShelf's Python code running behind it as a helper process.
//   npm install && npm start        run from a checkout (uses python3 for the helper)
//   npm run dist                    build an AppImage (Linux) or installer + portable .exe (Windows) into dist/
//   electron . --smoke              start, check the window and the helper work together, print SMOKE OK, quit
const { app, BrowserWindow, dialog, ipcMain, Menu, protocol, shell } = require("electron");
const fs = require("fs");
const path = require("path");
const { Helper } = require("./helper");
const { checkForUpdates } = require("./updates");

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
  win.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  win.webContents.on("will-navigate", (e) => e.preventDefault());
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
ipcMain.handle("confirm", async (_e, opts) => {
  const r = await dialog.showMessageBox(win, { type: opts.warning ? "warning" : "question", buttons: [opts.ok || "OK", "Cancel"], defaultId: 0,
    cancelId: 1, title: opts.title || "RetroShelf", message: opts.message, detail: opts.detail || undefined });
  return r.response === 0;
});
ipcMain.handle("pick-folder", async (_e, start, title) => {
  const r = await dialog.showOpenDialog(win, { title: title || "Your ROMs folder", defaultPath: start || undefined,
    properties: ["openDirectory", "createDirectory"] });
  return r.canceled ? null : r.filePaths[0];
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
  if (!/^https:\/\//.test(String(url))) return "not a web address";
  return shell.openExternal(url).then(() => "");
});
ipcMain.handle("app:version", () => app.getVersion());

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
    startHelper();
    createWindow();
    checkForUpdates(app);
  });
  app.on("before-quit", () => { app.isQuitting = true; if (helper) helper.stop(); });
  app.on("window-all-closed", () => app.quit());
}
