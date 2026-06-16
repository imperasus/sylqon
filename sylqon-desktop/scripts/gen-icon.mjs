// Generate the Sylqon app icon from scratch (vector → PNG → ICO).
//
// Concept: targeting crosshair / reticle with an "S" monogram core, teal line
// art on a dark rounded tile with transparent corners. Pure vector, so it stays
// crisp at every size. Re-run after tweaking:  npm run gen:icon
//
// Outputs:
//   build/icon.png   (1024×1024, transparent corners)
//   build/icon.ico   (16…256 px frames for Windows)

import { writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { Resvg } from "@resvg/resvg-js";
import pngToIco from "png-to-ico";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

// --- tweakable design tokens ------------------------------------------------
const SIZE = 1024;
const C = SIZE / 2; // center
const TEAL = "#2EC4B6";
const TEAL_HI = "#45E0D0"; // brighter highlight
const TILE_TOP = "#1b2531";
const TILE_BOT = "#0a0d12";

const RING_R = 178; // reticle radius
const TICK_IN = 214; // crosshair tick: inner radius (just outside the ring)
const TICK_OUT = 372; // crosshair tick: outer radius
// ---------------------------------------------------------------------------

const pt = (r, deg) => {
  const a = (deg * Math.PI) / 180;
  return [C + r * Math.cos(a), C - r * Math.sin(a)];
};

// Four reticle arcs sitting in the diagonals, leaving the N/E/S/W axes open for
// the crosshair ticks.
function arc(deg1, deg2, r = RING_R) {
  const [x1, y1] = pt(r, deg1);
  const [x2, y2] = pt(r, deg2);
  const large = Math.abs(deg2 - deg1) > 180 ? 1 : 0;
  return `M ${x1.toFixed(1)} ${y1.toFixed(1)} A ${r} ${r} 0 ${large} 0 ${x2.toFixed(1)} ${y2.toFixed(1)}`;
}
const arcs = [arc(20, 70), arc(110, 160), arc(200, 250), arc(290, 340)]
  .map((d) => `<path d="${d}" />`)
  .join("\n      ");

// Four crosshair ticks (N/E/S/W) with a dot at the outer end.
function tick(deg) {
  const [xi, yi] = pt(TICK_IN, deg);
  const [xo, yo] = pt(TICK_OUT, deg);
  return (
    `<line x1="${xi.toFixed(1)}" y1="${yi.toFixed(1)}" x2="${xo.toFixed(1)}" y2="${yo.toFixed(1)}" />` +
    `<circle cx="${xo.toFixed(1)}" cy="${yo.toFixed(1)}" r="9" stroke="none" fill="${TEAL_HI}" />`
  );
}
const ticks = [tick(90), tick(0), tick(270), tick(180)].join("\n      ");

// "S" monogram spine (stroked), centered at (512,512).
const sPath = [
  "M 568.3 439.1",
  "C 557 410.8 467 410.8 455.8 443.9",
  "C 446.4 480.9 488.6 498.4 512 512",
  "C 535.4 525.6 577.6 543.2 568.3 580.1",
  "C 557 613.2 467 613.2 455.8 584.9",
].join(" ");

const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${SIZE} ${SIZE}">
  <defs>
    <radialGradient id="tile" cx="50%" cy="40%" r="75%">
      <stop offset="0%" stop-color="${TILE_TOP}" />
      <stop offset="100%" stop-color="${TILE_BOT}" />
    </radialGradient>
    <linearGradient id="teal" gradientUnits="userSpaceOnUse"
                    x1="0" y1="${C - RING_R - 120}" x2="0" y2="${C + RING_R + 120}">
      <stop offset="0%" stop-color="${TEAL_HI}" />
      <stop offset="100%" stop-color="${TEAL}" />
    </linearGradient>
    <filter id="glow" x="-25%" y="-25%" width="150%" height="150%">
      <feGaussianBlur stdDeviation="7" result="b" />
      <feMerge>
        <feMergeNode in="b" />
        <feMergeNode in="SourceGraphic" />
      </feMerge>
    </filter>
  </defs>

  <!-- dark rounded tile (transparent corners) -->
  <rect x="64" y="64" width="896" height="896" rx="214"
        fill="url(#tile)" stroke="${TEAL}" stroke-opacity="0.22" stroke-width="4" />

  <!-- teal line art: reticle + crosshair + S -->
  <g filter="url(#glow)" fill="none" stroke="url(#teal)"
     stroke-linecap="round" stroke-linejoin="round">
    <g stroke-width="11">
      ${arcs}
    </g>
    <g stroke-width="16">
      ${ticks}
    </g>
    <path d="${sPath}" stroke-width="34" />
  </g>
</svg>`;

const png = new Resvg(svg, {
  fitTo: { mode: "width", value: SIZE },
  background: "rgba(0,0,0,0)",
})
  .render()
  .asPng();

await writeFile(path.join(root, "build", "icon.png"), png);
const ico = await pngToIco(png);
await writeFile(path.join(root, "build", "icon.ico"), ico);
console.log(
  `[gen-icon] wrote build/icon.png (${(png.length / 1024).toFixed(0)} KB) ` +
    `and build/icon.ico (${(ico.length / 1024).toFixed(0)} KB)`
);
