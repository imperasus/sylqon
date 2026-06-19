import { app, BrowserWindow, globalShortcut, ipcMain } from "electron";
import * as path from "path";
import {
  getBaseUrl,
  getClickThroughHotkey,
  getDashboardUrl,
  getToggleHotkey,
} from "./config";
import { resolveAppIcon } from "./icon";
import {
  createOverlayWindow,
  destroyOverlay,
  toggleClickThrough,
  toggleOverlay,
} from "./overlay";
import { startBackend, stopBackend } from "./backend";
import { createTray, destroyTray, notifyTray } from "./tray";
import { checkBackend } from "./health";
import { setupAutoUpdates, attachUpdateBanner, checkForUpdatesManual } from "./updater";

// ---------------------------------------------------------------------------
// Sylqon Desktop — main process
//
// A thin, read-only frame around the local Sylqon web UI plus an always-on-top
// overlay. It does NOT interact with the League of Legends process: no memory
// reads, no DLL/code injection, no synthetic input. All game logic lives in the
// Python Sylqon backend; this process only manages normal desktop windows and
// spawns the (bundled) backend as a child process.
//
// Behaviors:
//   - main window  → Sylqon dashboard (SYLQON_BASE_URL), backend-down fallback
//   - overlay      → /overlay, frameless/always-on-top, F10 toggle (overlay.ts)
//   - backend      → auto-started bundled server (backend.ts)
//   - tray         → close-to-tray; app keeps running, quit from the tray menu
// ---------------------------------------------------------------------------

let mainWindow: BrowserWindow | null = null;
let healthPoll: ReturnType<typeof setInterval> | null = null;
let isQuitting = false; // true only once the user really wants to exit
let trayBalloonShown = false;

const STATIC_PAGE = (name: string) =>
  path.join(app.getAppPath(), "static", name);

// How long to show the loading splash before assuming something is wrong and
// surfacing the troubleshooting page. The bundled backend normally answers in
// ~2-3s; allow generous headroom for a cold start.
const BACKEND_WAIT_MS = 40000;

function stopHealthPoll(): void {
  if (healthPoll) {
    clearInterval(healthPoll);
    healthPoll = null;
  }
}

/**
 * Poll the backend while showing the loading splash. Swap to the dashboard the
 * moment it answers; only fall back to the troubleshooting page if it stays
 * unreachable past BACKEND_WAIT_MS.
 */
function startHealthPoll(win: BrowserWindow): void {
  stopHealthPoll();
  const startedAt = Date.now();
  healthPoll = setInterval(async () => {
    if (await checkBackend(getDashboardUrl())) {
      stopHealthPoll();
      if (!win.isDestroyed()) win.loadURL(getDashboardUrl());
    } else if (Date.now() - startedAt > BACKEND_WAIT_MS) {
      stopHealthPoll();
      if (!win.isDestroyed()) win.loadFile(STATIC_PAGE("backend-down.html"));
    }
  }, 1200);
}

/**
 * Load the dashboard if the backend is already up; otherwise show the loading
 * splash and poll until it comes up (or times out to the troubleshooting page).
 */
async function loadMainContent(win: BrowserWindow): Promise<void> {
  const dashboard = getDashboardUrl();
  if (await checkBackend(dashboard)) {
    stopHealthPoll();
    win.loadURL(dashboard);
  } else {
    win.loadFile(STATIC_PAGE("loading.html"));
    startHealthPoll(win);
  }
}

function createMainWindow(): void {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 900,
    minHeight: 600,
    show: false, // shown on ready-to-show to avoid a white flash
    frame: true, // normal OS frame (title bar + controls)
    resizable: true,
    alwaysOnTop: false, // the MAIN window is a normal window
    icon: resolveAppIcon(),
    title: "Sylqon",
    webPreferences: {
      // Locked-down renderer. The preload is only meaningful for the local
      // backend-down page; the live Sylqon UI ignores it (different origin).
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  mainWindow.setMenuBarVisibility(false);

  // If the live dashboard fails to load (e.g. backend died mid-session), fall
  // back to the backend-down page. Ignore failures of the local file:// page
  // itself and sub-frame failures.
  mainWindow.webContents.on(
    "did-fail-load",
    (_e, errorCode, errorDescription, validatedURL, isMainFrame) => {
      if (!isMainFrame) return;
      if (validatedURL.startsWith("file://")) return;
      // -3 (ABORTED) fires on normal in-app navigations; not a real failure.
      if (errorCode === -3) return;
      console.error(
        `[sylqon-desktop] failed to load ${validatedURL} ` +
          `(${errorCode} ${errorDescription}) — showing loading splash.`
      );
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.loadFile(STATIC_PAGE("loading.html"));
        startHealthPoll(mainWindow);
      }
    }
  );

  mainWindow.once("ready-to-show", () => mainWindow?.show());

  // Re-render the in-app update banner across navigations (splash → dashboard).
  attachUpdateBanner(mainWindow);

  // Close-to-tray: closing the window hides it instead of quitting, unless the
  // user chose Quit (isQuitting). The app keeps running in the tray.
  mainWindow.on("close", (e) => {
    if (!isQuitting) {
      e.preventDefault();
      mainWindow?.hide();
      if (!trayBalloonShown) {
        trayBalloonShown = true;
        notifyTray(
          "Sylqon a tálcán fut tovább",
          "Az alkalmazás a háttérben marad. Jobb klikk a tálcaikonra → Kilépés a teljes bezáráshoz."
        );
      }
    }
  });

  mainWindow.on("closed", () => {
    stopHealthPoll();
    mainWindow = null;
  });

  loadMainContent(mainWindow);
}

/** Bring the dashboard window back (from tray click / second instance). */
function showMainWindow(): void {
  if (!mainWindow || mainWindow.isDestroyed()) {
    createMainWindow();
    return;
  }
  if (mainWindow.isMinimized()) mainWindow.restore();
  if (!mainWindow.isVisible()) mainWindow.show();
  mainWindow.focus();
}

function quitApp(): void {
  isQuitting = true;
  app.quit();
}

function registerHotkeys(): void {
  const toggleKey = getToggleHotkey();
  const clickKey = getClickThroughHotkey();

  if (globalShortcut.register(toggleKey, toggleOverlay)) {
    console.log(`[sylqon-desktop] toggle overlay: ${toggleKey}`);
  } else {
    console.error(
      `[sylqon-desktop] failed to register toggle hotkey "${toggleKey}" ` +
        "(already in use by another app?)."
    );
  }

  if (globalShortcut.register(clickKey, toggleClickThrough)) {
    console.log(`[sylqon-desktop] toggle overlay click-through: ${clickKey}`);
  } else {
    console.error(
      `[sylqon-desktop] failed to register click-through hotkey "${clickKey}".`
    );
  }
}

// --- IPC from the backend-down page (only source of these messages) ---------
ipcMain.on("sylqon:retry", () => {
  if (mainWindow && !mainWindow.isDestroyed()) loadMainContent(mainWindow);
});
ipcMain.handle("sylqon:getBaseUrl", () => getBaseUrl());
ipcMain.handle("sylqon:getLogPath", () =>
  path.join(app.getPath("userData"), "backend.log")
);
// App version (same value electron-updater compares against) for the UI badge.
ipcMain.handle("sylqon:getVersion", () => app.getVersion());

// --- Single instance: a second launch focuses the existing window -----------
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => showMainWindow());

  app.whenReady().then(() => {
    console.log(`[sylqon-desktop] backend base URL: ${getBaseUrl()}`);

    // Start the bundled backend (no-op if it's already running or disabled).
    // The main window's health poll will swap from the backend-down page to the
    // dashboard as soon as it responds.
    void startBackend();

    createMainWindow();
    // Create the overlay up front (hidden) so the first hotkey press is instant.
    createOverlayWindow();
    registerHotkeys();
    createTray({ showMainWindow, checkForUpdates: checkForUpdatesManual, quit: quitApp });

    // Check for updates silently and surface an in-app banner if one is found
    // (no-op when not packaged). Non-blocking — never gates the UI.
    setupAutoUpdates(() => mainWindow);

    app.on("activate", () => showMainWindow());
  });
}

app.on("before-quit", () => {
  isQuitting = true; // allow the main window's close handler to proceed
});

app.on("will-quit", () => {
  globalShortcut.unregisterAll();
  stopHealthPoll();
  destroyOverlay();
  destroyTray();
  stopBackend();
});

// Do NOT quit when all windows are closed: the tray keeps the app alive. Quit
// happens explicitly via the tray menu (quitApp).
app.on("window-all-closed", () => {
  // intentionally empty
});
