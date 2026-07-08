// Generate the Sylqon app icon from scratch (vector → PNG → ICO).
//
// Concept: "Signal S" — three stacked equalizer bars with alternating offsets
// whose silhouette forms an S, plus one amber data-point dot. Flat lime bars on
// a flat graphite tile (no gradient, no glow) — mirrors ui/src/components/
// BrandMark.jsx. Pure vector, so it stays crisp at every size, including the
// 16×16 ICO frame (bar height ≈ 2px there). Re-run after tweaking:
//   npm run gen:icon
//
// Outputs:
//   build/icon.png   (1024×1024, transparent corners)
//   build/icon.ico   (16…256 px frames for Windows)

import { writeFile, mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { Resvg } from "@resvg/resvg-js";
import pngToIco from "png-to-ico";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

// --- tweakable design tokens ------------------------------------------------
const SIZE = 1024;
const LIME = "#a3e635";
const AMBER = "#fbbf24";
const TILE = "#17181b";
const TILE_BORDER = "#2c2c30";

// The mark shares BrandMark.jsx's 24-unit grid, scaled by U and centered.
const U = 32; // 24 units × 32 = 768px content box
const O = (SIZE - 24 * U) / 2; // origin offset (128)
// ---------------------------------------------------------------------------

const bar = (x, y, w) =>
  `<rect x="${O + x * U}" y="${O + y * U}" width="${w * U}" height="${4 * U}" rx="${U}" fill="${LIME}" />`;

const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${SIZE} ${SIZE}">
  <!-- flat graphite tile (transparent corners) -->
  <rect x="64" y="64" width="896" height="896" rx="214"
        fill="${TILE}" stroke="${TILE_BORDER}" stroke-width="8" />

  <!-- Signal S: top bar right, middle full, bottom bar left + amber dot -->
  ${bar(7, 3, 14)}
  ${bar(3, 10, 18)}
  ${bar(3, 17, 14)}
  <circle cx="${O + 19.5 * U}" cy="${O + 19 * U}" r="${2 * U}" fill="${AMBER}" />
</svg>`;

const png = new Resvg(svg, {
  fitTo: { mode: "width", value: SIZE },
  background: "rgba(0,0,0,0)",
})
  .render()
  .asPng();

// Ensure the output dir exists (it isn't committed, so it's absent on a fresh
// checkout / in CI).
await mkdir(path.join(root, "build"), { recursive: true });
await writeFile(path.join(root, "build", "icon.png"), png);
const ico = await pngToIco(png);
await writeFile(path.join(root, "build", "icon.ico"), ico);
console.log(
  `[gen-icon] wrote build/icon.png (${(png.length / 1024).toFixed(0)} KB) ` +
    `and build/icon.ico (${(ico.length / 1024).toFixed(0)} KB)`
);
