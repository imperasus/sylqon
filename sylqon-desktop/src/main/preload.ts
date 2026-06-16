import { contextBridge, ipcRenderer } from "electron";

// Minimal, read-only bridge exposed to the local "backend not running" page.
// Nothing here touches the game or the OS — it only lets that static page ask
// the main process to re-check the backend and read the configured URL.
//
// This preload is ONLY attached to the bundled backend-down.html. The real
// Sylqon UI is served over HTTP and gets no preload / no privileged bridge.

contextBridge.exposeInMainWorld("sylqon", {
  /** Ask the main process to re-check the backend and (re)load the dashboard. */
  retry: (): void => ipcRenderer.send("sylqon:retry"),
  /** Resolve the configured backend base URL (for display). */
  getBaseUrl: (): Promise<string> => ipcRenderer.invoke("sylqon:getBaseUrl"),
  /** Resolve the backend log file path (for troubleshooting display). */
  getLogPath: (): Promise<string> => ipcRenderer.invoke("sylqon:getLogPath"),
});
