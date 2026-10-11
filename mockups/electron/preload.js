const { contextBridge, ipcRenderer } = require("electron");
contextBridge.exposeInMainWorld("backend", { library: () => ipcRenderer.invoke("library") });
