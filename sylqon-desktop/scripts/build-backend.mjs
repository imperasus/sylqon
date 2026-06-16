// Build the Sylqon backend into a standalone onedir executable with PyInstaller.
//
//   npm run build:backend
//
// Steps:
//   1. Build the React UI (the backend serves ui/dist). Skip with SKIP_UI=1.
//   2. Run PyInstaller against backend/sylqon-server.spec.
// Output: backend/dist/sylqon-server/sylqon-server.exe (+ _internal/).
//
// Requires Python with the build deps installed (backend/requirements-build.txt).
// Override the interpreter with SYLQON_PYTHON (e.g. "py -3.11").

import { execSync } from "node:child_process";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const desktop = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = path.resolve(desktop, "..");
const py = process.env.SYLQON_PYTHON || "python";

function run(cmd, cwd) {
  console.log(`\n$ ${cmd}\n  (cwd=${cwd})`);
  execSync(cmd, { cwd, stdio: "inherit" });
}

// 1. React UI (served by the backend over HTTP).
if (process.env.SKIP_UI === "1") {
  console.log("[build-backend] SKIP_UI=1 — reusing existing ui/dist");
} else {
  run("npm run build", path.join(repoRoot, "ui"));
}

// 2. PyInstaller → onedir bundle.
run(
  `${py} -m PyInstaller "${path.join("backend", "sylqon-server.spec")}" ` +
    "--distpath backend/dist --workpath backend/build --noconfirm",
  desktop
);

const out = path.join(desktop, "backend", "dist", "sylqon-server", "sylqon-server.exe");
if (!existsSync(out)) {
  console.error(`[build-backend] FAILED — expected exe not found:\n  ${out}`);
  process.exit(1);
}
console.log(`\n[build-backend] OK → ${out}`);

// 3. First-run data snapshot (so a fresh install starts WITH data).
run("node scripts/make-seed.mjs", desktop);
