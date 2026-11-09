"use strict";
const { contextBridge, ipcRenderer } = require("electron");
const listen = (channel, callback) => {
  if (typeof callback !== "function")
    throw new TypeError("A callback is required.");
  const listener = (_event, value) => callback(value);
  ipcRenderer.on(channel, listener);
  return () => ipcRenderer.removeListener(channel, listener);
};
contextBridge.exposeInMainWorld(
  "ankiDesktop",
  Object.freeze({
    info: () => ipcRenderer.invoke("desktop:info"),
    diagnostics: () => ipcRenderer.invoke("desktop:diagnostics"),
    exportDiagnostics: () => ipcRenderer.invoke("desktop:export-diagnostics"),
    restartBackend: () => ipcRenderer.invoke("desktop:restart"),
    openDirectory: (kind) => ipcRenderer.invoke("desktop:open-directory", kind),
    openDownload: (id, action) =>
      ipcRenderer.invoke("desktop:open-download", id, action),
    onState: (callback) => listen("desktop:state", callback),
    onNavigate: (callback) => listen("desktop:navigate", callback),
    onDownload: (callback) => listen("desktop:download", callback),
  }),
);
