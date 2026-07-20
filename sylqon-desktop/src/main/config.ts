// Central config for Sylqon Desktop. Presentation / window behavior only —
// there is no game integration of any kind here.
//
// Resolution order for every setting:  environment variable > config file >
// built-in default.
//
// The config file is USER-EDITABLE and the app NEVER writes to it. Persisted
// runtime state (overlay window bounds) lives separately in store.ts so app
// writes can't clobber your settings.

import { app } from "electron";
import * as fs from "fs";
import * as path from "path";

/** Default Sylqon backend origin (FastAPI). No trailing slash. */
export const DEFAULT_BASE_URL = "http://127.0.0.1:8077";

/** Global hotkey to show/hide the overlay window. Electron Accelerator syntax. */
export const DEFAULT_TOGGLE_HOTKEY = "F10";
/** Global hotkey to toggle overlay click-through (interactive vs pass-through). */
export const DEFAULT_CLICKTHROUGH_HOTKEY = "F9";

interface FileConfig {
  baseUrl?: string;
  toggleHotkey?: string;
  clickThroughHotkey?: string;
  clickThrough?: boolean;
  autoOverlay?: boolean;
}

/**
 * Candidate config file locations, in priority order:
 *   1. path in the SYLQON_DESKTOP_CONFIG env var
 *   2. sylqon-desktop.config.json in the app's userData dir (the normal home)
 *   3. sylqon-desktop.config.json in the current working directory
 */
function configCandidates(): string[] {
  const list = [process.env.SYLQON_DESKTOP_CONFIG?.trim()];
  try {
    list.push(path.join(app.getPath("userData"), "sylqon-desktop.config.json"));
  } catch {
    // app not ready yet — userData path unavailable; fall through to cwd.
  }
  list.push(path.join(process.cwd(), "sylqon-desktop.config.json"));
  return list.filter((p): p is string => !!p && p.length > 0);
}

let cachedFileConfig: FileConfig | null = null;

/** Load the first readable config file (memoized). Bad/missing files ignored. */
function getFileConfig(): FileConfig {
  if (cachedFileConfig) return cachedFileConfig;
  for (const file of configCandidates()) {
    try {
      if (!fs.existsSync(file)) continue;
      // Strip a UTF-8 BOM if present (Windows editors often add one).
      const raw = fs.readFileSync(file, "utf-8").replace(/^﻿/, "");
      cachedFileConfig = JSON.parse(raw) as FileConfig;
      console.log(`[sylqon-desktop] loaded config file: ${file}`);
      return cachedFileConfig;
    } catch (err) {
      console.error(`[sylqon-desktop] ignoring bad config file ${file}: ${err}`);
    }
  }
  cachedFileConfig = {};
  return cachedFileConfig;
}

function pickString(
  envVal: string | undefined,
  fileVal: string | undefined,
  fallback: string
): string {
  const env = envVal?.trim();
  if (env && env.length > 0) return env;
  if (fileVal && fileVal.trim().length > 0) return fileVal.trim();
  return fallback;
}

/**
 * Base origin of the Sylqon backend. Override with SYLQON_BASE_URL (env) or
 * `baseUrl` in the config file. Any trailing slash is stripped.
 */
export function getBaseUrl(): string {
  const raw = pickString(
    process.env.SYLQON_BASE_URL,
    getFileConfig().baseUrl,
    DEFAULT_BASE_URL
  );
  return raw.replace(/\/+$/, "");
}

/** URL the main window loads: the Sylqon dashboard at the backend root. */
export function getDashboardUrl(): string {
  return getBaseUrl() + "/";
}

/** URL the overlay window loads: the Sylqon in-game overlay view. */
export function getOverlayUrl(): string {
  return getBaseUrl() + "/overlay";
}

/** Show/hide overlay hotkey. Env: SYLQON_TOGGLE_HOTKEY, file: toggleHotkey. */
export function getToggleHotkey(): string {
  return pickString(
    process.env.SYLQON_TOGGLE_HOTKEY,
    getFileConfig().toggleHotkey,
    DEFAULT_TOGGLE_HOTKEY
  );
}

/** Click-through hotkey. Env: SYLQON_CLICKTHROUGH_HOTKEY, file: clickThroughHotkey. */
export function getClickThroughHotkey(): string {
  return pickString(
    process.env.SYLQON_CLICKTHROUGH_HOTKEY,
    getFileConfig().clickThroughHotkey,
    DEFAULT_CLICKTHROUGH_HOTKEY
  );
}

/**
 * Whether the overlay starts in click-through mode. Default true (clicks pass to
 * the game, so the overlay can never be clicked or dragged by accident) — toggle
 * to interactive with the click-through hotkey (F9) when you want to reposition
 * it. Env: SYLQON_CLICK_THROUGH ("0"/"false" to start interactive), file:
 * clickThrough.
 */
export function getClickThroughDefault(): boolean {
  const raw = process.env.SYLQON_CLICK_THROUGH?.trim().toLowerCase();
  if (raw === "1" || raw === "true" || raw === "yes") return true;
  if (raw === "0" || raw === "false" || raw === "no") return false;
  const fileVal = getFileConfig().clickThrough;
  if (typeof fileVal === "boolean") return fileVal;
  return true;
}

/**
 * Whether the overlay auto shows when a game starts and hides when it ends
 * (the manual F10 toggle still works as an override). Default true. Env:
 * SYLQON_OVERLAY_AUTO ("0"/"false" to disable), file: autoOverlay.
 */
export function getOverlayAutoDefault(): boolean {
  const raw = process.env.SYLQON_OVERLAY_AUTO?.trim().toLowerCase();
  if (raw === "1" || raw === "true" || raw === "yes") return true;
  if (raw === "0" || raw === "false" || raw === "no") return false;
  const fileVal = getFileConfig().autoOverlay;
  if (typeof fileVal === "boolean") return fileVal;
  return true;
}
