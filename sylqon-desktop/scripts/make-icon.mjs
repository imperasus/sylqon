// Generate build/icon.ico (multi-resolution) from build/icon.png.
//
// The PNG is the source of truth (your XY icon). Re-run after changing it:
//   npm run make:icon
//
// Produces a Windows .ico containing 16/24/32/48/64/128/256 px frames so the
// app looks crisp in the taskbar, Start menu, installer and exe.

import { readFile, writeFile, access } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
import pngToIco from "png-to-ico";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const srcPng = path.join(root, "build", "icon.png");
const outIco = path.join(root, "build", "icon.ico");

try {
  await access(srcPng);
} catch {
  console.error(
    `[make-icon] source not found: ${srcPng}\n` +
      "Drop your square (>=256px, ideally 1024px) PNG there first."
  );
  process.exit(1);
}

const ico = await pngToIco(srcPng);
await writeFile(outIco, ico);
const { size } = await readFile(outIco).then((b) => ({ size: b.length }));
console.log(`[make-icon] wrote ${outIco} (${(size / 1024).toFixed(1)} KB)`);
