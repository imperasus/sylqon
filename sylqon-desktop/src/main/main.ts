import { app, BrowserWindow, globalShortcut, ipcMain } from "electron";
import * as fs from "fs";
import * as path from "path";
import { spawn } from "child_process";
import {
  getBaseUrl,
  getClickThroughHotkey,
  getDashboardUrl,
  getOverlayAutoDefault,
  getToggleHotkey,
} from "./config";
import { resolveAppIcon } from "./icon";
import {
  applyGameActive,
  createOverlayWindow,
  destroyOverlay,
  toggleClickThrough,
  toggleOverlay,
} from "./overlay";
import { startBackend, stopBackend } from "./backend";
import { createTray, destroyTray, notifyTray } from "./tray";
import { checkBackend, fetchJson } from "./health";
import { setupAutoUpdates, attachUpdateBanner, checkForUpdatesManual } from "./updater";
import { getSavedMainBounds, saveMainBounds } from "./store";

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
let overlayAutoPoll: ReturnType<typeof setInterval> | null = null;
let isQuitting = false; // true only once the user really wants to exit
let trayBalloonShown = false;

// How often to poll the backend game state for auto show/hide of the overlay.
const OVERLAY_POLL_MS = 2500;

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
  // The dashboard is now fully responsive (fluid root scale + adaptive density),
  // so the window is freely resizable. Default to the tuned 1280x800 canvas, but
  // honor a saved size/position and clamp to a sensible minimum below which the
  // dense views stop being comfortable.
  const saved = getSavedMainBounds();
  mainWindow = new BrowserWindow({
    width: saved?.width ?? 1280,
    height: saved?.height ?? 800,
    ...(saved ? { x: saved.x, y: saved.y } : {}),
    minWidth: 1024,
    minHeight: 640,
    resizable: true,
    maximizable: true,
    backgroundColor: "#0e0e0f", // matches the app bg; guarantees a painted surface
    show: false, // shown on ready-to-show to avoid a white flash
    frame: true, // normal OS frame (title bar + controls)
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

  // Open DevTools automatically in dev, or when SYLQON_DEVTOOLS=1 is set, so the
  // dashboard renderer can be inspected without a rebuild.
  if (process.env.SYLQON_DEVTOOLS === "1" || process.env.NODE_ENV === "development") {
    mainWindow.webContents.openDevTools({ mode: "detach" });
  }

  // Remember size/position across runs (debounced inside the store). Persist the
  // normal (non-maximized) bounds so un-maximizing restores the prior size.
  const persistBounds = () => {
    if (!mainWindow || mainWindow.isDestroyed() || mainWindow.isMinimized()) return;
    saveMainBounds(mainWindow.getNormalBounds());
  };
  mainWindow.on("resize", persistBounds);
  mainWindow.on("move", persistBounds);

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

/**
 * Auto show/hide the overlay by polling the backend game state. Shows it when a
 * game becomes active, hides it when the game ends; the F10 hotkey still works as
 * a manual override (overlay.applyGameActive only acts on edges).
 *
 * The poll always runs: whether auto show/hide is enabled is read LIVE from the
 * backend's `overlay_auto` flag (driven by the dashboard Settings panel), so a
 * user can turn it on/off without restarting the app. The desktop config
 * (SYLQON_OVERLAY_AUTO / `autoOverlay`) only supplies the initial default used
 * until the backend answers.
 */
function startOverlayAutoToggle(): void {
  const stateUrl = getBaseUrl() + "/api/state";
  const initialAuto = getOverlayAutoDefault();
  overlayAutoPoll = setInterval(async () => {
    const data = await fetchJson<{
      overlay_auto?: boolean;
      overlay?: { active?: boolean };
      live?: { active?: boolean };
    }>(stateUrl);
    if (!data) return; // backend not ready / unreachable → leave state unchanged
    const auto = typeof data.overlay_auto === "boolean" ? data.overlay_auto : initialAuto;
    if (!auto) return; // auto disabled from Settings → manual F10 only
    applyGameActive(!!(data.overlay?.active || data.live?.active));
  }, OVERLAY_POLL_MS);
  console.log("[sylqon-desktop] overlay auto show/hide poll started");
}

function stopOverlayAutoToggle(): void {
  if (overlayAutoPoll) {
    clearInterval(overlayAutoPoll);
    overlayAutoPoll = null;
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

// --- Launch the League client (Home "Next match" CTA) -----------------------
// Starts Riot's own launcher with its documented product arguments. This only
// *starts* an application the user already has installed — it does not attach
// to, read, or interact with the game process in any way, so it stays clear of
// the read-only boundary the overlay is built on.
const RIOT_CLIENT_CANDIDATES = [
  "C:\\Riot Games\\Riot Client\\RiotClientServices.exe",
  "C:\\Program Files\\Riot Games\\Riot Client\\RiotClientServices.exe",
  "C:\\Program Files (x86)\\Riot Games\\Riot Client\\RiotClientServices.exe",
];

ipcMain.handle("sylqon:launchLeague", async () => {
  const exe = RIOT_CLIENT_CANDIDATES.find((p) => fs.existsSync(p));
  if (!exe) {
    return { ok: false, reason: "not-found" };
  }
  try {
    const child = spawn(
      exe,
      ["--launch-product=league_of_legends", "--launch-patchline=live"],
      { detached: true, stdio: "ignore" }
    );
    child.unref();
    return { ok: true };
  } catch (err) {
    return { ok: false, reason: String(err) };
  }
});

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
    // Auto show/hide the overlay as games start/end (F10 still overrides).
    startOverlayAutoToggle();
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
  stopOverlayAutoToggle();
  destroyOverlay();
  destroyTray();
  stopBackend();
});

// Do NOT quit when all windows are closed: the tray keeps the app alive. Quit
// happens explicitly via the tray menu (quitApp).
app.on("window-all-closed", () => {
  // intentionally empty
});
