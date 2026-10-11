// RetroShelf's Electron app: this window, with RetroShelf's Python code running behind it as a helper process.
//   npm install && npm start        run from a checkout (uses python3 for the helper)
//   npm run dist                    build an AppImage (Linux) or installer + portable .exe (Windows) into dist/
//   electron . --smoke              start, check the window and the helper work together, print SMOKE OK, quit
const { app, BrowserWindow, dialog, ipcMain, Menu } = require("electron");
const fs = require("fs");
const path = require("path");
const { Helper } = require("./helper");
const { checkForUpdates } = require("./updates");

const smoke = process.argv.includes("--smoke");
let win = null;
let helper = null;

// ---------- settings (the Tk app keeps its own config.json; these are this app's) ----------
const settingsFile = () => path.join(app.getPath("userData"), "settings.json");
function loadSettings() {
  try { return JSON.parse(fs.readFileSync(settingsFile(), "utf8")); } catch { return {}; }
}
function saveSettings(changes) {
  const merged = { ...loadSettings(), ...changes };
  fs.mkdirSync(path.dirname(settingsFile()), { recursive: true });
  fs.writeFileSync(settingsFile() + ".tmp", JSON.stringify(merged, null, 2));
  fs.renameSync(settingsFile() + ".tmp", settingsFile());
  return merged;
}

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
  return helper.call(method, params);
});
ipcMain.handle("pick-folder", async (_e, start) => {
  const r = await dialog.showOpenDialog(win, { title: "Your ROMs folder", defaultPath: start || undefined,
    properties: ["openDirectory"] });
  return r.canceled ? null : r.filePaths[0];
});
ipcMain.handle("settings:get", () => loadSettings());
ipcMain.handle("settings:save", (_e, changes) => saveSettings(changes));
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
    startHelper();
    createWindow();
    checkForUpdates(app);
  });
  app.on("before-quit", () => { app.isQuitting = true; if (helper) helper.stop(); });
  app.on("window-all-closed", () => app.quit());
}
