import { contextBridge, ipcRenderer } from "electron";

// Minimal, read-only bridge exposed to the local "backend not running" page.
// Nothing here touches the game or the OS — it only lets that static page ask
// the main process to re-check the backend and read the configured URL.
//
// The `sylqon` bridge below is meaningful to the bundled backend-down.html. The
// `sylqonUpdater` bridge is consumed by the in-app update banner (injected by
// updater.ts) and so must be available on every page the main window shows.
// Both expose only send/invoke wrappers — no Node, no game/OS access.

contextBridge.exposeInMainWorld("sylqon", {
  /** Ask the main process to re-check the backend and (re)load the dashboard. */
  retry: (): void => ipcRenderer.send("sylqon:retry"),
  /** Resolve the configured backend base URL (for display). */
  getBaseUrl: (): Promise<string> => ipcRenderer.invoke("sylqon:getBaseUrl"),
  /** Resolve the backend log file path (for troubleshooting display). */
  getLogPath: (): Promise<string> => ipcRenderer.invoke("sylqon:getLogPath"),
  /** Resolve the installed app version (for the UI version badge). */
  getVersion: (): Promise<string> => ipcRenderer.invoke("sylqon:getVersion"),
});

// Update banner buttons (Download / Restart) → main process (see updater.ts).
contextBridge.exposeInMainWorld("sylqonUpdater", {
  /** Manually check for an update (shows checking → up-to-date / available). */
  check: (): void => ipcRenderer.send("sylqon:update-check"),
  /** Start downloading the available update. */
  download: (): void => ipcRenderer.send("sylqon:update-download"),
  /** Quit and install the downloaded update. */
  restart: (): void => ipcRenderer.send("sylqon:update-restart"),
});
