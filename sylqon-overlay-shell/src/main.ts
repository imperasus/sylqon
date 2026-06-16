import { app, BrowserWindow, globalShortcut, screen } from "electron";
import {
  getOverlayUrl,
  getToggleHotkey,
  getClickThroughHotkey,
  getClickThroughDefault,
} from "./config";

// PHASE 3 — global hotkey, fixed positioning, safe click-through.
//
// This app is a *thin, read-only frame* around a web URL. It does NOT touch the
// League of Legends process in any way: no memory reads, no DLL/code injection,
// no synthetic input. Click-through uses Electron's built-in
// setIgnoreMouseEvents — a standard windowing API, not an input hook.

let overlayWindow: BrowserWindow | null = null;
let clickThrough = getClickThroughDefault();

const WINDOW_WIDTH = 400;
const WINDOW_HEIGHT = 300;
const SCREEN_MARGIN = 16; // px gap from the screen edge

function positionTopLeft(win: BrowserWindow): void {
  // Use the primary display's *work area* (excludes the taskbar).
  const { workArea } = screen.getPrimaryDisplay();
  const x = workArea.x + SCREEN_MARGIN;
  const y = workArea.y + SCREEN_MARGIN;
  win.setPosition(Math.round(x), Math.round(y));
}

function applyClickThrough(win: BrowserWindow): void {
  // forward:true still delivers mouse-move events to the renderer (so hover
  // styling works) while letting clicks pass through to the window below.
  win.setIgnoreMouseEvents(clickThrough, { forward: true });
}

function createOverlayWindow(): void {
  overlayWindow = new BrowserWindow({
    width: WINDOW_WIDTH,
    height: WINDOW_HEIGHT,
    show: false, // hidden by default — visibility is controlled by the hotkey
    frame: false, // borderless
    transparent: true, // let the web UI design its own background
    alwaysOnTop: true,
    resizable: false,
    skipTaskbar: true,
    focusable: true,
    backgroundColor: "#00000000", // fully transparent
    webPreferences: {
      // Keep the renderer locked down — this shell runs no privileged code.
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  // Keep it above normal always-on-top windows / fullscreen-ish clients.
  overlayWindow.setAlwaysOnTop(true, "screen-saver");
  overlayWindow.setMenuBarVisibility(false);
  applyClickThrough(overlayWindow);

  const url = getOverlayUrl();
  overlayWindow.loadURL(url);

  overlayWindow.webContents.on(
    "did-fail-load",
    (_event, errorCode, errorDescription, validatedURL) => {
      console.error(
        `[sylqon-overlay] failed to load ${validatedURL} ` +
          `(${errorCode} ${errorDescription}). ` +
          `Is the Sylqon backend running at ${url}?`
      );
    }
  );

  overlayWindow.on("closed", () => {
    overlayWindow = null;
  });
}

function toggleOverlay(): void {
  if (!overlayWindow) return;

  if (overlayWindow.isVisible()) {
    overlayWindow.hide();
    return;
  }

  positionTopLeft(overlayWindow);
  applyClickThrough(overlayWindow); // re-assert in case it changed while hidden
  // showInactive: don't steal focus from the game when the overlay appears.
  overlayWindow.showInactive();
  overlayWindow.setAlwaysOnTop(true, "screen-saver");
}

function toggleClickThrough(): void {
  if (!overlayWindow) return;
  clickThrough = !clickThrough;
  applyClickThrough(overlayWindow);
  console.log(
    `[sylqon-overlay] click-through ${clickThrough ? "ON" : "OFF"} ` +
      `(${clickThrough ? "clicks pass to game" : "overlay is interactive"})`
  );
}

function registerHotkeys(): void {
  const toggleKey = getToggleHotkey();
  const clickKey = getClickThroughHotkey();

  if (!globalShortcut.register(toggleKey, toggleOverlay)) {
    console.error(
      `[sylqon-overlay] failed to register toggle hotkey "${toggleKey}" ` +
        `(already in use by another app?).`
    );
  } else {
    console.log(`[sylqon-overlay] toggle overlay: ${toggleKey}`);
  }

  if (!globalShortcut.register(clickKey, toggleClickThrough)) {
    console.error(
      `[sylqon-overlay] failed to register click-through hotkey "${clickKey}".`
    );
  } else {
    console.log(`[sylqon-overlay] toggle click-through: ${clickKey}`);
  }
}

app.whenReady().then(() => {
  createOverlayWindow();
  registerHotkeys();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createOverlayWindow();
    }
  });
});

app.on("will-quit", () => {
  globalShortcut.unregisterAll();
});

// Windows-first: keep the process alive even with no visible window, because
// the overlay starts hidden and is summoned by the global hotkey.
app.on("window-all-closed", () => {
  app.quit();
});
