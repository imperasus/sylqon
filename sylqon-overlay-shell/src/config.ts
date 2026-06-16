// Central config for the overlay shell. Kept tiny on purpose.
//
// Everything here is presentation/window behavior only — there is no game
// integration of any kind.
//
// Resolution order for every setting:  environment variable  >  config file  >
// built-in default.

import * as fs from "fs";
import * as path from "path";

export const DEFAULT_OVERLAY_URL = "http://127.0.0.1:8077/overlay";
export const DEFAULT_TOGGLE_HOTKEY = "F10";
export const DEFAULT_CLICKTHROUGH_HOTKEY = "F9";

interface FileConfig {
  overlayUrl?: string;
  toggleHotkey?: string;
  clickThroughHotkey?: string;
  clickThrough?: boolean;
}

/**
 * Loads an optional JSON config file. Looked up in this order:
 *   1. path in the SYLQON_OVERLAY_CONFIG env var
 *   2. sylqon-overlay.config.json next to the running executable / cwd
 * Missing or malformed files are ignored (env vars / defaults still apply).
 */
function loadFileConfig(): FileConfig {
  const candidates = [
    process.env.SYLQON_OVERLAY_CONFIG?.trim(),
    path.join(process.cwd(), "sylqon-overlay.config.json"),
  ].filter((p): p is string => !!p && p.length > 0);

  for (const file of candidates) {
    try {
      if (!fs.existsSync(file)) continue;
      // Strip a UTF-8 BOM if present (Windows editors often add one).
      const raw = fs.readFileSync(file, "utf-8").replace(/^﻿/, "");
      const parsed = JSON.parse(raw);
      console.log(`[sylqon-overlay] loaded config file: ${file}`);
      return parsed as FileConfig;
    } catch (err) {
      console.error(`[sylqon-overlay] ignoring bad config file ${file}: ${err}`);
    }
  }
  return {};
}

// Read the file once at startup.
const fileConfig = loadFileConfig();

function pickString(envVal: string | undefined, fileVal: string | undefined, fallback: string): string {
  const env = envVal?.trim();
  if (env && env.length > 0) return env;
  if (fileVal && fileVal.trim().length > 0) return fileVal.trim();
  return fallback;
}

/** URL the overlay window loads. Env: SYLQON_OVERLAY_URL. */
export function getOverlayUrl(): string {
  return pickString(process.env.SYLQON_OVERLAY_URL, fileConfig.overlayUrl, DEFAULT_OVERLAY_URL);
}

/** Global hotkey to show/hide the overlay. Env: SYLQON_TOGGLE_HOTKEY. */
export function getToggleHotkey(): string {
  return pickString(process.env.SYLQON_TOGGLE_HOTKEY, fileConfig.toggleHotkey, DEFAULT_TOGGLE_HOTKEY);
}

/** Global hotkey to toggle click-through. Env: SYLQON_CLICKTHROUGH_HOTKEY. */
export function getClickThroughHotkey(): string {
  return pickString(
    process.env.SYLQON_CLICKTHROUGH_HOTKEY,
    fileConfig.clickThroughHotkey,
    DEFAULT_CLICKTHROUGH_HOTKEY
  );
}

/**
 * Whether the overlay starts in click-through mode.
 * Click-through uses Electron's built-in setIgnoreMouseEvents (a normal
 * windowing API) — it does NOT inject into or capture input from the game.
 * Env: SYLQON_CLICK_THROUGH ("0"/"false" to start interactive).
 */
export function getClickThroughDefault(): boolean {
  const raw = process.env.SYLQON_CLICK_THROUGH?.trim().toLowerCase();
  if (raw === "0" || raw === "false" || raw === "no") return false;
  if (raw === "1" || raw === "true" || raw === "yes") return true;
  if (typeof fileConfig.clickThrough === "boolean") return fileConfig.clickThrough;
  return true;
}
