import { BrowserWindow, screen } from "electron";
import { getClickThroughDefault, getOverlayUrl } from "./config";
import { resolveAppIcon } from "./icon";
import { getSavedOverlayBounds, saveOverlayBounds } from "./store";

// ---------------------------------------------------------------------------
// Overlay window — the always-on-top, frameless, transparent in-game panel.
//
// Riot-safe by design: this is a normal desktop window positioned over the
// game. It does NOT read game memory, inject code, or simulate input. The
// optional click-through uses Electron's built-in setIgnoreMouseEvents — a
// standard windowing attribute, not an input hook.
// ---------------------------------------------------------------------------

let overlayWindow: BrowserWindow | null = null;

// Initial click-through is config-driven (default OFF = interactive, so you can
// click/drag it). Toggle at runtime with the click-through hotkey.
let clickThrough = getClickThroughDefault();

const WIDTH = 420;
const HEIGHT = 320;
const SCREEN_MARGIN = 16; // px gap from the screen edge

/**
 * Place the overlay: restore last saved bounds if available & still on-screen,
 * otherwise default to the top-right of the primary display's work area.
 */
function placeOverlay(win: BrowserWindow): void {
  const saved = getSavedOverlayBounds();
  if (saved) {
    win.setBounds(saved);
    return;
  }
  const { workArea } = screen.getPrimaryDisplay();
  const x = workArea.x + workArea.width - WIDTH - SCREEN_MARGIN;
  const y = workArea.y + SCREEN_MARGIN;
  win.setPosition(Math.round(x), Math.round(y));
}

function applyClickThrough(win: BrowserWindow): void {
  // forward:true still delivers mouse-move events to the renderer (so hover
  // styling works) while letting clicks pass through to whatever is below.
  win.setIgnoreMouseEvents(clickThrough, { forward: true });
}

export function createOverlayWindow(): BrowserWindow {
  overlayWindow = new BrowserWindow({
    width: WIDTH,
    height: HEIGHT,
    show: false, // hidden by default — visibility is controlled by the hotkey
    frame: false, // borderless
    transparent: true, // let the web UI design its own background
    alwaysOnTop: true,
    resizable: true, // allow resize so the persisted size is meaningful
    skipTaskbar: true,
    focusable: true,
    backgroundColor: "#00000000", // fully transparent
    icon: resolveAppIcon(),
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  // Sit above normal always-on-top windows / borderless-fullscreen clients.
  overlayWindow.setAlwaysOnTop(true, "screen-saver");
  overlayWindow.setMenuBarVisibility(false);
  applyClickThrough(overlayWindow);

  const url = getOverlayUrl();
  overlayWindow.loadURL(url);

  overlayWindow.webContents.on(
    "did-fail-load",
    (_e, errorCode, errorDescription, validatedURL) => {
      console.error(
        `[sylqon-desktop] overlay failed to load ${validatedURL} ` +
          `(${errorCode} ${errorDescription}). Is the backend serving ${url}?`
      );
    }
  );

  // Persist position & size whenever the user moves or resizes the overlay
  // (debounced inside the store). This is how it reopens where you left it.
  const persist = () => {
    if (overlayWindow && !overlayWindow.isDestroyed()) {
      saveOverlayBounds(overlayWindow.getBounds());
    }
  };
  overlayWindow.on("move", persist);
  overlayWindow.on("resize", persist);

  overlayWindow.on("closed", () => {
    overlayWindow = null;
  });

  return overlayWindow;
}

/** Show the overlay if hidden, hide it if shown. Never steals focus on show. */
export function toggleOverlay(): void {
  if (!overlayWindow || overlayWindow.isDestroyed()) {
    createOverlayWindow();
  }
  const win = overlayWindow!;

  if (win.isVisible()) {
    win.hide();
    return;
  }

  placeOverlay(win);
  applyClickThrough(win); // re-assert in case it changed while hidden
  // showInactive: appear WITHOUT stealing focus from the game.
  win.showInactive();
  win.setAlwaysOnTop(true, "screen-saver");
}

/** Toggle whether clicks pass through the overlay to the window below. */
export function toggleClickThrough(): void {
  if (!overlayWindow || overlayWindow.isDestroyed()) return;
  clickThrough = !clickThrough;
  applyClickThrough(overlayWindow);
  console.log(
    `[sylqon-desktop] overlay click-through ${clickThrough ? "ON" : "OFF"} ` +
      `(${clickThrough ? "clicks pass to game" : "overlay is interactive"})`
  );
}

/** Tear down the overlay window (called on app quit). */
export function destroyOverlay(): void {
  if (overlayWindow && !overlayWindow.isDestroyed()) overlayWindow.destroy();
  overlayWindow = null;
}
