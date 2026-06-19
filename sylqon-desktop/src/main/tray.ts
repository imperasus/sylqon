import { Menu, Tray, nativeImage } from "electron";
import { resolveAppIcon } from "./icon";
import { toggleOverlay } from "./overlay";

// System-tray icon + menu. Lets the app keep running after the main window is
// closed (close-to-tray), and gives quick access to the overlay and a real Quit.

let tray: Tray | null = null;

interface TrayActions {
  showMainWindow: () => void;
  checkForUpdates: () => void;
  quit: () => void;
}

export function createTray(actions: TrayActions): void {
  if (tray) return;

  const iconPath = resolveAppIcon();
  const image = iconPath ? nativeImage.createFromPath(iconPath) : nativeImage.createEmpty();
  tray = new Tray(image);
  tray.setToolTip("Sylqon");

  const menu = Menu.buildFromTemplate([
    { label: "Megnyitás", click: () => actions.showMainWindow() },
    { label: "Overlay be/ki (F10)", click: () => toggleOverlay() },
    { type: "separator" },
    { label: "Frissítés keresése", click: () => actions.checkForUpdates() },
    { type: "separator" },
    { label: "Kilépés", click: () => actions.quit() },
  ]);
  tray.setContextMenu(menu);

  // Left-click the tray icon brings the dashboard back.
  tray.on("click", () => actions.showMainWindow());
}

/** Show a one-off Windows tray balloon (no-op on other platforms). */
export function notifyTray(title: string, content: string): void {
  if (tray && process.platform === "win32") {
    tray.displayBalloon({ title, content });
  }
}

export function destroyTray(): void {
  tray?.destroy();
  tray = null;
}
