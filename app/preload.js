// The only doors from the window into the rest of the app.
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("retroshelf", {
  call: (method, params) => ipcRenderer.invoke("helper:call", method, params),
  pickFolder: (start, title) => ipcRenderer.invoke("pick-folder", start, title),
  pickFiles: (start, title) => ipcRenderer.invoke("pick-files", start, title),
  saveFile: (opts) => ipcRenderer.invoke("save-file", opts),
  openFolder: (folder) => ipcRenderer.invoke("open-folder", folder),
  openUrl: (url) => ipcRenderer.invoke("open-url", url),
  version: () => ipcRenderer.invoke("app:version"),
  encrypt: (text) => ipcRenderer.invoke("secret:encrypt", text),
  decrypt: (data) => ipcRenderer.invoke("secret:decrypt", data),
  checkUpdates: (auto) => ipcRenderer.invoke("update:check", auto),
  installUpdate: () => ipcRenderer.invoke("update:install"),
  onUpdate: (fn) => ipcRenderer.on("update", (_e, state) => fn(state)),
  desktopStatus: () => ipcRenderer.invoke("desktop:status"),
  addToMenu: () => ipcRenderer.invoke("desktop:install"),
  onHelperEvent: (fn) => ipcRenderer.on("helper:event", (_e, name, data) => fn(name, data)),
  onHelperExit: (fn) => ipcRenderer.on("helper:exit", (_e, info) => fn(info)),
  ready: (summary) => ipcRenderer.send("renderer:ready", summary),
  setBusy: (on) => ipcRenderer.send("app:busy", on),
  quit: () => ipcRenderer.send("app:quit"),
  onCloseAsked: (fn) => ipcRenderer.on("app:close-asked", () => fn()),
});
