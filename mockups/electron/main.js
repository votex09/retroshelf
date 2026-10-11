// RetroShelf main window mock-up in Electron: sample data, no backend.
//   npm install && npm start
//   MOCKUP_CAPTURE=<dir> npm start   # play a short scripted demo, save frames there, quit (for screenshots)
// In a real port the Python code would run as a helper process and this window would talk to it the way
// the renderer asks for games.json here (ipcMain.handle).
const { app, BrowserWindow, ipcMain } = require("electron");
const fs = require("fs");
const path = require("path");

const capture = process.env.MOCKUP_CAPTURE;

ipcMain.handle("library", () =>
  JSON.parse(fs.readFileSync(path.join(__dirname, "..", "shared", "games.json"), "utf8")));

function createWindow() {
  const win = new BrowserWindow({
    width: 1280, height: 800, ...(capture ? { x: 0, y: 0, frame: false } : {}), minWidth: 1024, minHeight: 640,
    backgroundColor: "#0e1016", title: "RetroShelf (Electron mock-up)",
    icon: path.join(__dirname, "..", "..", "assets", "icon-256.png"),
    autoHideMenuBar: true,
    webPreferences: { preload: path.join(__dirname, "preload.js") },
  });
  win.loadFile("index.html");
  if (capture) runCapture(win);
}

// The same scripted demo as the PySide6 mock-up: keys at set times, screenshots at three points.
const DEMO = [
  [1500, "shot", "main.png"], ...Array(5).fill([250, "Down"]), [250, "Right"], [1200, "shot", "after-flip.png"],
  [0, "Space"], [350, "Space"], [350, "Return"], [1200, "Tab"], [600, "Down"], [300, "Down"], [300, "Left"],
  [1200, "Z", ["control"]], [1200, "shot", "end.png"], [100, "quit"],
];

async function runCapture(win) {
  fs.mkdirSync(capture, { recursive: true });
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  await new Promise((r) => win.webContents.once("did-finish-load", r));
  for (const [delay, what, arg] of DEMO) {
    await wait(delay);
    if (what === "shot") fs.writeFileSync(path.join(capture, arg), (await win.webContents.capturePage()).toPNG());
    else if (what === "quit") app.quit();
    else {
      win.webContents.sendInputEvent({ type: "keyDown", keyCode: what, modifiers: arg || [] });
      win.webContents.sendInputEvent({ type: "keyUp", keyCode: what, modifiers: arg || [] });
    }
  }
}

app.whenReady().then(createWindow);
app.on("window-all-closed", () => app.quit());
