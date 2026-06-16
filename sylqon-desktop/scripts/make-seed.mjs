// Generate a first-run data snapshot from the current repo, bundled into the
// app so a fresh install starts WITH data (champion universe, meta, builds)
// instead of an empty database.
//
//   npm run make:seed   (also run automatically by build:backend)
//
// Output: backend/seed/sylqon.db (+ backend/seed/cache/*.json)
// The desktop app copies these into userData on first launch (see backend.ts).
//
// If the repo has no sylqon.db (e.g. building on a clean machine), this is a
// no-op — the app then just starts empty and populates via in-app Sync.

import { execFileSync } from "node:child_process";
import {
  copyFileSync,
  existsSync,
  mkdirSync,
  readdirSync,
} from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const desktop = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = path.resolve(desktop, "..");
const py = process.env.SYLQON_PYTHON || "python";

const repoDb = path.join(repoRoot, "sylqon.db");
const repoCache = path.join(repoRoot, "cache");
const seedDir = path.join(desktop, "backend", "seed");
const seedCache = path.join(seedDir, "cache");

// Always ensure the seed dir exists so electron-builder's extraResources has a
// source, even when there's nothing to seed.
mkdirSync(seedCache, { recursive: true });

if (!existsSync(repoDb)) {
  console.warn(`[make-seed] no repo DB at ${repoDb} — skipping seed (app will start empty)`);
  process.exit(0);
}

// Consolidated SQLite backup (collapses any WAL into a single clean file).
const seedDb = path.join(seedDir, "sylqon.db");
const code =
  "import sqlite3; " +
  `s=sqlite3.connect(r'${repoDb}'); d=sqlite3.connect(r'${seedDb}'); ` +
  "s.backup(d); " +
  "print(d.execute('select count(*) from champions').fetchone()[0]); " +
  "d.close(); s.close()";
const champs = execFileSync(py, ["-c", code], { encoding: "utf-8" }).trim();
console.log(`[make-seed] seed DB written (${champs} champions)`);

if (existsSync(repoCache)) {
  const jsons = readdirSync(repoCache).filter((f) => f.endsWith(".json"));
  for (const f of jsons) copyFileSync(path.join(repoCache, f), path.join(seedCache, f));
  console.log(`[make-seed] copied cache: ${jsons.join(", ") || "(none)"}`);
}
console.log("[make-seed] done");
