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

// Open DevTools automatically in dev, or when SYLQON_DEVTOOLS=1 is set, so the
// overlay renderer can be inspected without rebuilding.
const DEVTOOLS_ENABLED =
  process.env.SYLQON_DEVTOOLS === "1" || process.env.NODE_ENV !== "production";

// Shown instead of a silent blank window when the backend URL can't be loaded
// (e.g. the Sylqon backend isn't running yet). Data URL so it can never itself
// trigger did-fail-load.
function fallbackPage(url: string, detail: string): string {
  const html = `<!doctype html><meta charset="utf-8"><body style="margin:0;font-family:system-ui,sans-serif;background:#0b0f1acc;color:#e2e8f0;display:flex;align-items:center;justify-content:center;height:100vh;text-align:center">
  <div style="padding:20px">
    <div style="font-weight:700;letter-spacing:.15em;color:#f87171;margin-bottom:8px">OVERLAY OFFLINE</div>
    <div style="font-size:13px;color:#94a3b8;line-height:1.5">Nem sikerült betölteni:<br><code style="color:#7dd3fc">${url}</code><br><br>Fut a Sylqon backend?<br><span style="color:#64748b">${detail}</span></div>
  </div></body>`;
  return "data:text/html;charset=utf-8," + encodeURIComponent(html);
}

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

  if (DEVTOOLS_ENABLED) {
    overlayWindow.webContents.openDevTools({ mode: "detach" });
  }

  const url = getOverlayUrl();
  overlayWindow.loadURL(url);

  overlayWindow.webContents.on(
    "did-fail-load",
    (_event, errorCode, errorDescription, validatedURL) => {
      // errorCode -3 is an aborted (in-app) navigation, not a real failure.
      if (errorCode === -3) return;
      console.error(
        `[sylqon-overlay] failed to load ${validatedURL} ` +
          `(${errorCode} ${errorDescription}). ` +
          `Is the Sylqon backend running at ${url}?`
      );
      // Replace the blank window with a readable offline panel instead of
      // leaving the user staring at nothing.
      overlayWindow?.loadURL(
        fallbackPage(url, `${errorCode} ${errorDescription}`)
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
