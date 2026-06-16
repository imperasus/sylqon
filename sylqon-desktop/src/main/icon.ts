import { app } from "electron";
import * as fs from "fs";
import * as path from "path";

/**
 * Resolve the Windows app icon used for BrowserWindow / taskbar / tray.
 *
 * Drop your custom `XY icon` at  build/icon.ico  (see build/ICON_README.md).
 * Returns undefined (→ Electron's default icon) until that file exists, so the
 * app stays buildable without the asset. No placeholder icon is invented.
 *
 * app.getAppPath() === the project root in dev and the app root inside the
 * packaged asar in production, so build/icon.ico resolves correctly in both.
 */
export function resolveAppIcon(): string | undefined {
  const iconPath = path.join(app.getAppPath(), "build", "icon.ico");
  if (fs.existsSync(iconPath)) return iconPath;
  console.warn(
    `[sylqon-desktop] no app icon at ${iconPath} — using Electron default. ` +
      "Drop your XY icon there (see build/ICON_README.md)."
  );
  return undefined;
}
