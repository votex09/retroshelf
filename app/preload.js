// The only doors from the window into the rest of the app.
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("retroshelf", {
  call: (method, params) => ipcRenderer.invoke("helper:call", method, params),
  pickFolder: (start) => ipcRenderer.invoke("pick-folder", start),
  settings: () => ipcRenderer.invoke("settings:get"),
  saveSettings: (changes) => ipcRenderer.invoke("settings:save", changes),
  version: () => ipcRenderer.invoke("app:version"),
  onHelperEvent: (fn) => ipcRenderer.on("helper:event", (_e, name, data) => fn(name, data)),
  onHelperExit: (fn) => ipcRenderer.on("helper:exit", (_e, info) => fn(info)),
  ready: (summary) => ipcRenderer.send("renderer:ready", summary),
});
