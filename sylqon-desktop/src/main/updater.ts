import { app, ipcMain, BrowserWindow } from "electron";
import { autoUpdater } from "electron-updater";

// ---------------------------------------------------------------------------
// Auto-update — non-intrusive, in-app banner UX.
//
// electron-updater reads `latest.yml` from the latest GitHub Release (publish
// config in electron-builder.yml) on startup. We deliberately drive our OWN
// in-app banner instead of native OS dialogs/notifications:
//
//   update-available   → banner "Sylqon X.Y.Z is available  [Download]"
//   download-progress  → banner "Downloading update… NN%"
//   update-downloaded  → banner "Update X.Y.Z ready  [Restart]"
//
// The banner is injected into whatever page the main window is showing (loading
// splash, dashboard, or backend-down page), so it survives navigations. Its
// buttons call window.sylqonUpdater.{download,restart} (see preload.ts), which
// send the IPC handled below.
//
// Auto-download is OFF: nothing downloads until the user clicks Download, and
// nothing installs until they click Restart (or quit the app). No surprises.
// ---------------------------------------------------------------------------

type UpdateStatus =
  | { phase: "checking" }
  | { phase: "uptodate"; version: string }
  | { phase: "error"; message: string }
  | { phase: "available"; version: string }
  | { phase: "progress"; percent: number }
  | { phase: "downloaded"; version: string };

// Re-check for updates periodically while the app stays open (it lives in the
// tray for long sessions). The initial check runs at startup.
const RECHECK_INTERVAL_MS = 6 * 60 * 60 * 1000; // 6 hours

let getMainWindow: () => BrowserWindow | null = () => null;
let latestStatus: UpdateStatus | null = null;
// True only while a USER-triggered check is in flight, so the "up to date" /
// "check failed" feedback is shown for manual checks but stays silent for the
// routine background checks (which must never interrupt the user).
let manualCheckPending = false;

/** Build a self-contained, idempotent script that renders/updates the banner. */
function bannerScript(status: UpdateStatus): string {
  // status is JSON-encoded into the script so nothing is string-concatenated
  // into executable code. All dynamic values (version, percent) are written
  // via textContent — never innerHTML — so there is no XSS surface even if the
  // release metadata were tampered with.
  return `(function(){
    if(!document.body) return;
    var s = ${JSON.stringify(status)};
    var id = "sylqon-update-banner";
    var el = document.getElementById(id);
    if(!el){
      el = document.createElement("div");
      el.id = id;
      el.style.cssText = "position:fixed;left:50%;bottom:20px;transform:translateX(-50%);z-index:2147483647;background:#0f1620;color:#e6f0f3;border:1px solid #1f9e8f;border-radius:10px;padding:12px 16px;font:13px/1.4 system-ui,'Segoe UI',sans-serif;box-shadow:0 8px 30px rgba(0,0,0,.45);display:flex;align-items:center;gap:14px;max-width:90vw;";
      document.body.appendChild(el);
    }
    while(el.firstChild) el.removeChild(el.firstChild);
    var api = window.sylqonUpdater || {};
    function span(text){ var n=document.createElement("span"); n.textContent=text; return n; }
    function button(label, onClick){
      var b=document.createElement("button");
      b.textContent=label;
      b.style.cssText="background:#1f9e8f;color:#04110f;border:0;border-radius:6px;padding:6px 12px;font-weight:600;cursor:pointer;";
      b.onclick=onClick;
      return b;
    }
    if(s.phase==="checking"){
      el.appendChild(span("Checking for updates…"));
    } else if(s.phase==="uptodate"){
      el.appendChild(span("Sylqon "+s.version+" is up to date."));
    } else if(s.phase==="error"){
      el.appendChild(span(s.message));
    } else if(s.phase==="available"){
      el.appendChild(span("Sylqon "+s.version+" is available."));
      el.appendChild(button("Download", function(){ if(api.download) api.download(); }));
    } else if(s.phase==="progress"){
      el.appendChild(span("Downloading update… "+s.percent+"%"));
    } else if(s.phase==="downloaded"){
      el.appendChild(span("Update "+s.version+" ready."));
      el.appendChild(button("Restart", function(){ if(api.restart) api.restart(); }));
    }
    var dismiss=span("✕");
    dismiss.title="Dismiss";
    dismiss.style.cssText="cursor:pointer;opacity:.6;padding-left:4px;";
    dismiss.onclick=function(){ el.remove(); };
    el.appendChild(dismiss);
    // Transient results clear themselves so a stale "up to date"/error notice
    // doesn't linger (or reappear after a page navigation).
    if(s.phase==="uptodate" || s.phase==="error"){
      setTimeout(function(){ if(el && el.parentNode) el.remove(); }, s.phase==="error"?6000:4000);
    }
  })();`;
}

/** Render the current status into the main window (no-op if nothing pending). */
function renderBanner(): void {
  const win = getMainWindow();
  if (!win || win.isDestroyed() || !latestStatus) return;
  win.webContents.executeJavaScript(bannerScript(latestStatus)).catch(() => {
    // Page navigated mid-injection or has no DOM yet — the did-finish-load
    // hook (attachUpdateBanner) will re-render once it settles.
  });
}

function pushStatus(status: UpdateStatus): void {
  latestStatus = status;
  renderBanner();
}

/** Push a self-clearing status: the banner removes itself client-side, and we
 *  also drop it from `latestStatus` so a later navigation won't re-render it. */
function pushTransient(status: UpdateStatus, ms: number): void {
  pushStatus(status);
  setTimeout(() => {
    if (latestStatus === status) latestStatus = null;
  }, ms);
}

/**
 * User-triggered "check for updates" (tray menu / UI version badge). Unlike the
 * silent background checks, this always gives feedback: a "checking…" banner,
 * then "up to date" / "available" / "check failed". No-ops with a friendly
 * notice when the app isn't packaged (no release feed to check against).
 */
export function checkForUpdatesManual(): void {
  if (!app.isPackaged) {
    pushTransient(
      { phase: "error", message: "Updates are only available in the installed app." },
      6000
    );
    return;
  }
  manualCheckPending = true;
  pushStatus({ phase: "checking" });
  autoUpdater.checkForUpdates().catch((err) => {
    console.error("[sylqon-desktop] manual update check failed:", err?.message ?? err);
    if (manualCheckPending) {
      manualCheckPending = false;
      pushTransient({ phase: "error", message: "Update check failed." }, 6000);
    }
  });
}

/**
 * Re-render the banner after in-app navigations (e.g. loading splash → live
 * dashboard) so a pending update notice isn't lost when the page swaps.
 * Call once per main window, from createMainWindow().
 */
export function attachUpdateBanner(win: BrowserWindow): void {
  win.webContents.on("did-finish-load", () => renderBanner());
}

/**
 * Configure electron-updater, wire the banner IPC, and start checking.
 * Safe to call in dev — it no-ops when the app isn't packaged (electron-updater
 * has no release metadata to check against outside a real install).
 */
export function setupAutoUpdates(resolveWindow: () => BrowserWindow | null): void {
  getMainWindow = resolveWindow;

  // Banner button → main process actions. Registered regardless of packaging so
  // the bridge exists; they're only ever triggered by our own banner.
  ipcMain.on("sylqon:update-download", () => {
    autoUpdater.downloadUpdate().catch((err) =>
      console.error("[sylqon-desktop] downloadUpdate failed:", err?.message ?? err)
    );
  });
  ipcMain.on("sylqon:update-restart", () => {
    // Quit all windows and install. before-quit (main.ts) flips isQuitting so
    // the close-to-tray handler lets the app actually exit.
    autoUpdater.quitAndInstall();
  });
  // Manual "check for updates" from the tray menu / UI version badge.
  ipcMain.on("sylqon:update-check", () => checkForUpdatesManual());

  if (!app.isPackaged) {
    console.log("[sylqon-desktop] auto-update disabled (not packaged).");
    return;
  }

  autoUpdater.autoDownload = false; // user clicks Download
  autoUpdater.autoInstallOnAppQuit = true; // install on quit if already downloaded

  autoUpdater.on("update-available", (info) => {
    manualCheckPending = false;
    pushStatus({ phase: "available", version: info.version });
  });
  autoUpdater.on("update-not-available", (info) => {
    // Only surface "you're up to date" for a check the user explicitly asked
    // for; background checks finding nothing must stay silent.
    if (manualCheckPending) {
      manualCheckPending = false;
      pushTransient({ phase: "uptodate", version: info?.version ?? app.getVersion() }, 4000);
    }
  });
  autoUpdater.on("download-progress", (p) =>
    pushStatus({ phase: "progress", percent: Math.round(p.percent) })
  );
  autoUpdater.on("update-downloaded", (info) =>
    pushStatus({ phase: "downloaded", version: info.version })
  );
  autoUpdater.on("error", (err) => {
    // Background failures are logged only — they must never interrupt the user.
    // A failure during a manual check gets a transient, dismissable notice.
    console.error("[sylqon-desktop] auto-update error:", err?.message ?? err);
    if (manualCheckPending) {
      manualCheckPending = false;
      pushTransient({ phase: "error", message: "Update check failed." }, 6000);
    }
  });

  const check = () =>
    autoUpdater.checkForUpdates().catch((err) =>
      console.error("[sylqon-desktop] update check failed:", err?.message ?? err)
    );

  void check();
  setInterval(check, RECHECK_INTERVAL_MS);
}
