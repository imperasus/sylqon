import { app, screen } from "electron";
import * as fs from "fs";
import * as path from "path";

// Persisted runtime STATE (app-written), kept separate from the user-editable
// config file. Currently just the overlay window's last position & size, so it
// reopens where you left it. Written to userData/sylqon-desktop.state.json.

export interface OverlayBounds {
  x: number;
  y: number;
  width: number;
  height: number;
}

interface AppState {
  overlayBounds?: OverlayBounds;
  mainBounds?: OverlayBounds;
}

/** True if a saved window's top-left still lands on a connected display
 *  (guards against a monitor being unplugged since last run). */
function boundsOnScreen(b: OverlayBounds): boolean {
  return screen.getAllDisplays().some((d) => {
    const a = d.workArea;
    return b.x >= a.x && b.x < a.x + a.width && b.y >= a.y && b.y < a.y + a.height;
  });
}

function statePath(): string {
  return path.join(app.getPath("userData"), "sylqon-desktop.state.json");
}

function readState(): AppState {
  try {
    const file = statePath();
    if (!fs.existsSync(file)) return {};
    const raw = fs.readFileSync(file, "utf-8").replace(/^﻿/, "");
    return JSON.parse(raw) as AppState;
  } catch (err) {
    console.error(`[sylqon-desktop] ignoring bad state file: ${err}`);
    return {};
  }
}

function writeState(state: AppState): void {
  try {
    fs.writeFileSync(statePath(), JSON.stringify(state, null, 2), "utf-8");
  } catch (err) {
    console.error(`[sylqon-desktop] failed to write state: ${err}`);
  }
}

/**
 * Saved overlay bounds, but only if they still land on a connected display
 * (guards against a monitor being unplugged since last run). Returns null
 * otherwise so the caller falls back to the default top-right position.
 */
export function getSavedOverlayBounds(): OverlayBounds | null {
  const b = readState().overlayBounds;
  if (!b) return null;
  return boundsOnScreen(b) ? b : null;
}

/** Saved main-window bounds, but only if they still land on a connected display
 *  (a smaller monitor since last run could otherwise open it off-screen). */
export function getSavedMainBounds(): OverlayBounds | null {
  const b = readState().mainBounds;
  if (!b) return null;
  return boundsOnScreen(b) ? b : null;
}

let saveTimer: ReturnType<typeof setTimeout> | null = null;

/** Persist overlay bounds, debounced (move/resize fire rapidly while dragging). */
export function saveOverlayBounds(bounds: OverlayBounds): void {
  if (saveTimer) clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    const state = readState();
    state.overlayBounds = bounds;
    writeState(state);
  }, 400);
}

let mainSaveTimer: ReturnType<typeof setTimeout> | null = null;

/** Persist main-window bounds, debounced (move/resize fire rapidly while dragging). */
export function saveMainBounds(bounds: OverlayBounds): void {
  if (mainSaveTimer) clearTimeout(mainSaveTimer);
  mainSaveTimer = setTimeout(() => {
    const state = readState();
    state.mainBounds = bounds;
    writeState(state);
  }, 400);
}
