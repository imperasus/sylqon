import { app } from "electron";
import { ChildProcess, execFileSync, spawn } from "child_process";
import * as fs from "fs";
import * as path from "path";
import { getDashboardUrl } from "./config";
import { checkBackend } from "./health";

// ---------------------------------------------------------------------------
// Backend lifecycle — auto-start the bundled Sylqon server so "just the exe" is
// enough (no manual `python -m sylqon.server`).
//
// The backend is the unchanged Python/FastAPI server, shipped as a standalone
// PyInstaller executable inside the app's resources. It is 100% read-only toward
// the game; this module only spawns/stops a normal child process.
// ---------------------------------------------------------------------------

let proc: ChildProcess | null = null;
let logStream: fs.WriteStream | null = null;

interface BackendCmd {
  cmd: string;
  args: string[];
  cwd: string;
  label: string;
}

function spawnEnabled(): boolean {
  const raw = process.env.SYLQON_SPAWN_BACKEND?.trim().toLowerCase();
  return !(raw === "0" || raw === "false" || raw === "no");
}

/**
 * Locate the backend to run, in priority order:
 *   1. packaged bundle in resources/backend/ (production)
 *   2. locally-built bundle under backend/dist/ (dev, after `npm run build:backend`)
 *   3. system Python `python -m sylqon.server` at the repo root (dev convenience)
 */
function resolveBackendCommand(): BackendCmd | null {
  const exeName = process.platform === "win32" ? "sylqon-server.exe" : "sylqon-server";

  const packaged = path.join(process.resourcesPath, "backend", exeName);
  if (fs.existsSync(packaged)) {
    return { cmd: packaged, args: [], cwd: path.dirname(packaged), label: "bundled" };
  }

  const appPath = app.getAppPath(); // sylqon-desktop/ in dev
  const devBundle = path.join(appPath, "backend", "dist", "sylqon-server", exeName);
  if (fs.existsSync(devBundle)) {
    return { cmd: devBundle, args: [], cwd: path.dirname(devBundle), label: "dev-bundle" };
  }

  const repoRoot = path.resolve(appPath, "..");
  if (fs.existsSync(path.join(repoRoot, "sylqon", "server.py"))) {
    const py = process.env.SYLQON_PYTHON || "python";
    return { cmd: py, args: ["-m", "sylqon.server"], cwd: repoRoot, label: "system-python" };
  }

  return null;
}

/**
 * Redirect the backend's writable paths (DB, cache, logs) into the desktop app's
 * userData dir, because the bundle itself may live in a read-only location.
 * Honored by sylqon/config.py via DB_PATH / SYLQON_CACHE_DIR / SYLQON_LOG_DIR.
 */
function backendEnv(): NodeJS.ProcessEnv {
  const dataDir = app.getPath("userData");
  return {
    ...process.env,
    DB_PATH: path.join(dataDir, "sylqon.db"),
    SYLQON_CACHE_DIR: path.join(dataDir, "cache"),
    SYLQON_LOG_DIR: dataDir,
  };
}

/**
 * On first launch (no userData DB yet), copy the bundled seed snapshot so the
 * app starts WITH data (champion universe, meta, builds) instead of empty. Only
 * runs when the DB is absent — it never overwrites an existing/updated DB.
 */
function seedUserDataIfEmpty(): void {
  const dataDir = app.getPath("userData");
  const dbPath = path.join(dataDir, "sylqon.db");
  if (fs.existsSync(dbPath)) return; // not first run — leave the user's data alone

  const seedDir = fs.existsSync(path.join(process.resourcesPath, "seed"))
    ? path.join(process.resourcesPath, "seed")
    : path.join(app.getAppPath(), "backend", "seed");
  const seedDb = path.join(seedDir, "sylqon.db");
  if (!fs.existsSync(seedDb)) return; // no snapshot bundled — start empty, sync in-app

  try {
    fs.mkdirSync(dataDir, { recursive: true });
    fs.copyFileSync(seedDb, dbPath);
    const seedCache = path.join(seedDir, "cache");
    if (fs.existsSync(seedCache)) {
      const dstCache = path.join(dataDir, "cache");
      fs.mkdirSync(dstCache, { recursive: true });
      for (const f of fs.readdirSync(seedCache)) {
        fs.copyFileSync(path.join(seedCache, f), path.join(dstCache, f));
      }
    }
    console.log("[sylqon-desktop] first run — seeded userData from bundled snapshot");
  } catch (err) {
    console.error(`[sylqon-desktop] seed failed (starting empty): ${err}`);
  }
}

/** Start the backend unless disabled or already running. Never throws. */
export async function startBackend(): Promise<void> {
  if (!spawnEnabled()) {
    console.log("[sylqon-desktop] backend auto-start disabled (SYLQON_SPAWN_BACKEND=0)");
    return;
  }

  // Seed the DB before the backend opens it.
  seedUserDataIfEmpty();
  // Don't double-start: if something already answers on the port (the user ran
  // it manually, or a prior instance), leave it alone — and remember we didn't
  // spawn it, so we won't kill it on quit.
  if (await checkBackend(getDashboardUrl())) {
    console.log("[sylqon-desktop] backend already running — not spawning");
    return;
  }

  const command = resolveBackendCommand();
  if (!command) {
    console.error("[sylqon-desktop] no backend executable found to start");
    return;
  }

  const logPath = path.join(app.getPath("userData"), "backend.log");
  try {
    logStream = fs.createWriteStream(logPath, { flags: "a" });
  } catch {
    logStream = null;
  }
  const banner =
    `\n[sylqon-desktop] === backend start ${new Date().toISOString()} (${command.label}) ===\n` +
    `[cmd] ${command.cmd} ${command.args.join(" ")}\n`;
  logStream?.write(banner);
  console.log(`[sylqon-desktop] starting backend (${command.label}): ${command.cmd} ${command.args.join(" ")}`);

  try {
    proc = spawn(command.cmd, command.args, {
      cwd: command.cwd,
      env: backendEnv(),
      windowsHide: true,
    });
  } catch (err) {
    console.error(`[sylqon-desktop] backend spawn threw: ${err}`);
    logStream?.write(`\n[spawn threw] ${err}\n`);
    proc = null;
    return;
  }

  proc.stdout?.on("data", (d) => logStream?.write(d));
  proc.stderr?.on("data", (d) => logStream?.write(d));
  proc.on("error", (err) => {
    console.error(`[sylqon-desktop] backend failed to start: ${err}`);
    logStream?.write(`\n[spawn error] ${err}\n`);
    proc = null;
  });
  proc.on("exit", (code, signal) => {
    console.log(`[sylqon-desktop] backend exited (code=${code} signal=${signal})`);
    logStream?.write(`\n[exit] code=${code} signal=${signal}\n`);
    proc = null;
  });
}

/**
 * Stop the backend we started (and ONLY the one we started). If the backend was
 * already running when we launched, `proc` is null and we leave it untouched.
 */
export function stopBackend(): void {
  if (proc && proc.pid != null) {
    const pid = proc.pid;
    try {
      if (process.platform === "win32") {
        // Kill the whole process tree (uvicorn workers) synchronously so nothing
        // is orphaned when the app exits.
        execFileSync("taskkill", ["/PID", String(pid), "/T", "/F"], { timeout: 5000 });
      } else {
        proc.kill("SIGTERM");
      }
    } catch (err) {
      // taskkill exits non-zero if the process is already gone — that's fine.
      console.error(`[sylqon-desktop] stopBackend: ${err}`);
    }
  }
  proc = null;
  logStream?.end();
  logStream = null;
}
