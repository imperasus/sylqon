# Sylqon Desktop

A single desktop application that wraps the existing **Sylqon** web UI and adds
an always-on-top in-game **overlay** window. It's a thin Electron shell:

- **Main window** — loads the Sylqon dashboard (`http://127.0.0.1:8077/`).
- **Overlay window** — frameless, transparent, always-on-top; loads `/overlay`;
  summoned with a global hotkey for use while you're in a game.
- **Bundled backend** — the packaged app ships the Python/FastAPI backend as a
  standalone executable and **starts it automatically**. Just run the exe — no
  manual `python -m sylqon.server`, no Python install needed on the user's PC.
- **System tray** — closing the main window **hides to the tray** instead of
  quitting; the app (and overlay hotkey) keep running. Quit from the tray menu.

## Riot-safe by design — read-only

This app does **not** interact with the League of Legends process in any way:

- ❌ No reading or writing of game process memory
- ❌ No DLL / code / overlay injection into the game
- ❌ No simulated or forwarded keyboard / mouse input to the game

All game logic (LCU, Live Client, recommendations) lives in the Python Sylqon
backend. Electron only opens normal desktop windows that display backend URLs.
The overlay's optional *click-through* uses Electron's built-in
`setIgnoreMouseEvents` — a standard windowing attribute, not an input hook.

## Requirements

**To run the packaged app:** nothing — the backend is bundled. Just the exe.

**To develop / build it:**
- Node.js 18+ and npm
- Windows (this build targets Windows x64)
- Python 3.11 with the backend build deps, **only needed to build the bundled
  backend** (`npm run build:backend`):
  ```powershell
  pip install -r backend/requirements-build.txt
  ```
  (In dev you can also just have the Sylqon backend importable at the repo root;
  the app will fall back to `python -m sylqon.server` if no bundle is built.)

## Install

```powershell
cd sylqon-desktop
npm install
```

## Run in dev mode

```powershell
npm run dev
```

This compiles the TypeScript and launches Electron.

- The app **auto-starts the backend** on launch (a built bundle under
  `backend/dist/` if present, otherwise it falls back to `python -m sylqon.server`
  at the repo root). If something is already serving `:8077`, it's reused — no
  double-start.
- The **main window** opens on the dashboard. Until the backend answers you get a
  **"Backend not running"** screen that auto-retries and switches to the dashboard
  the moment it responds.
- The **overlay** starts hidden — press **F10** to show/hide it. It appears in
  the **top-right** of your primary monitor (or wherever you last left it).

> For the fastest dev loop against the real bundle, run `npm run build:backend`
> once; otherwise the `python -m sylqon.server` fallback is used.

## Backend auto-start & system tray

- **Auto-start:** on launch the app spawns the backend as a child process and
  redirects its writable paths (DB, cache, log) into the app's `userData` folder
  (so a read-only install location is fine). Backend output is captured to
  `userData/backend.log`. Disable auto-start with `SYLQON_SPAWN_BACKEND=0` if you
  prefer to run the server yourself.
- **Close-to-tray:** the **✕** button hides the window to the system tray; the app
  keeps running (overlay hotkey stays live). Left-click the tray icon to reopen
  the dashboard, or use the tray menu (**Megnyitás**, **Overlay be/ki**,
  **Kilépés**). Only **Kilépés** (or `before-quit`) actually exits — and it stops
  the backend child process it started (the whole tree, so nothing is orphaned).
- **Single instance:** launching the exe again focuses the existing window
  instead of starting a second app/backend.

## Hotkeys

| Action | Default | Override (env) |
|--------|---------|----------------|
| Show / hide overlay | `F10` | `SYLQON_TOGGLE_HOTKEY` |
| Toggle overlay click-through | `F9` | `SYLQON_CLICKTHROUGH_HOTKEY` |

- **Click-through OFF** (default): the overlay is interactive (click/resize it).
- **Click-through ON**: clicks pass through the overlay to the game beneath it.

Hotkeys use [Electron Accelerator](https://www.electronjs.org/docs/latest/api/accelerator)
syntax, e.g. `F10`, `Alt+O`, `CommandOrControl+Shift+S`.

## Configuration

Settings resolve in this order: **environment variable → config file → default**.

### Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `SYLQON_BASE_URL` | `http://127.0.0.1:8077` | Backend origin for both windows |
| `SYLQON_TOGGLE_HOTKEY` | `F10` | Show/hide overlay |
| `SYLQON_CLICKTHROUGH_HOTKEY` | `F9` | Toggle click-through |
| `SYLQON_CLICK_THROUGH` | `false` | Start overlay in click-through mode (`1`/`true` to enable) |
| `SYLQON_DESKTOP_CONFIG` | — | Explicit path to a config file |
| `SYLQON_SPAWN_BACKEND` | `1` | Auto-start the backend (`0`/`false` to disable) |
| `SYLQON_PYTHON` | `python` | Interpreter for the dev `python -m sylqon.server` fallback |

Example (PowerShell):

```powershell
$env:SYLQON_BASE_URL = "http://127.0.0.1:9000"
$env:SYLQON_TOGGLE_HOTKEY = "Alt+O"
npm run dev
```

### Config file (user-editable)

Copy the example and edit it:

```powershell
copy sylqon-desktop.config.example.json sylqon-desktop.config.json
```

```json
{
  "baseUrl": "http://127.0.0.1:8077",
  "toggleHotkey": "F10",
  "clickThroughHotkey": "F9",
  "clickThrough": false
}
```

The file is searched at: `SYLQON_DESKTOP_CONFIG` → the app's `userData` dir →
the current working directory. A missing or malformed file is ignored. **The app
never writes to this file.**

### Overlay position & size (auto-persisted)

When you move or resize the overlay, its bounds are saved to
`userData/sylqon-desktop.state.json` and restored next launch. If the saved spot
is no longer on a connected display (monitor unplugged), it falls back to the
top-right default. This state file is written by the app — separate from your
config file.

> **Dragging the frameless overlay:** position *persistence* always works, but to
> drag the borderless window with the mouse, the Sylqon `/overlay` web page needs
> a drag region:
> ```css
> .drag-handle { -webkit-app-region: drag; }
> .drag-handle button { -webkit-app-region: no-drag; }
> ```
> Add that to the overlay view in the main repo, or ask to have a thin draggable
> strip injected from the Electron side.

## Build a Windows installer

```powershell
pip install -r backend/requirements-build.txt   # once, for the bundled backend
npm run build
```

`npm run build` runs three stages:
1. **`build:backend`** — builds the React UI and packages the Python backend into
   `backend/dist/sylqon-server/` with PyInstaller.
2. **`build:main`** — compiles the Electron TypeScript.
3. **electron-builder** — produces `release/Sylqon Setup <version>.exe`, an NSIS
   installer (chooses install dir, desktop + Start menu shortcuts) with the
   backend embedded under `resources/backend/`.

For a faster unpacked build (a folder with `Sylqon.exe`, no installer):

```powershell
npm run pack      # → release/win-unpacked/Sylqon.exe
```

> Tip: `SKIP_UI=1 npm run build` reuses the existing `ui/dist` (skips the React
> rebuild) when you've only changed Electron/backend code.

### Just the backend bundle

```powershell
npm run build:backend   # → backend/dist/sylqon-server/sylqon-server.exe
```

Runs standalone (no Python needed). Useful to test the bundled server directly.

## App icon

The Sylqon icon is **generated from vector** — a targeting-reticle / crosshair
with an "S" monogram core, teal line art on a dark rounded tile with transparent
corners. The design lives in [`scripts/gen-icon.mjs`](scripts/gen-icon.mjs) and
renders to:

- `build/icon.png` (1024×1024, transparent corners)
- `build/icon.ico` (16…256 px frames for Windows)

That `.ico` is auto-detected by electron-builder for the packaged `Sylqon.exe`
and the installer, and is used (via `src/main/icon.ts`) for the dev
BrowserWindow / taskbar icon. No config changes are needed.

```powershell
npm run gen:icon      # re-render build/icon.png + build/icon.ico from the vector
```

Tweak the look by editing the design tokens at the top of `gen-icon.mjs`
(colors, ring radius, stroke widths) and re-running `gen:icon`.

### Using your own image instead

Drop a square PNG (ideally 1024×1024, transparent background) at
`build/icon.png` and run:

```powershell
npm run make:icon     # build/icon.png  →  build/icon.ico (no re-generation)
```

Full details: [`build/ICON_README.md`](build/ICON_README.md).

## Scripts

| Script | Does |
|--------|------|
| `npm run dev` | Compile + launch in Electron |
| `npm run build:main` | Compile TypeScript only |
| `npm run build:backend` | Build the React UI + PyInstaller backend bundle |
| `npm start` | Launch already-compiled `dist/` |
| `npm run build` | Full NSIS installer (backend + main + electron-builder) |
| `npm run pack` | Unpacked app folder (backend + main + electron-builder --dir) |
| `npm run gen:icon` | Re-render the vector app icon → `build/icon.{png,ico}` |
| `npm run make:icon` | Pack a custom `build/icon.png` → `build/icon.ico` |
| `npm run clean` | Remove `dist/` |

## Project structure

```
sylqon-desktop/
├── package.json                       # scripts + deps
├── tsconfig.json                      # TS → dist/
├── electron-builder.yml               # Windows packaging + bundled backend + icon
├── sylqon-desktop.config.example.json # copy to sylqon-desktop.config.json
├── README.md
├── backend/                           # Python-backend → standalone-exe bundling
│   ├── launcher.py                    # PyInstaller entry (= python -m sylqon.server)
│   ├── sylqon-server.spec             # PyInstaller spec (onedir, data + hidden imports)
│   ├── requirements-build.txt         # build-time Python deps (PyInstaller etc.)
│   └── dist/sylqon-server/            # build output (gitignored) → bundled into the app
├── build/
│   ├── icon.png / icon.ico            # generated app icon
│   └── ICON_README.md
├── scripts/
│   ├── gen-icon.mjs / make-icon.mjs   # icon generation
│   └── build-backend.mjs              # UI build + PyInstaller driver
├── static/
│   └── backend-down.html              # "backend not running" fallback screen
└── src/
    └── main/
        ├── main.ts                    # app lifecycle, main window, tray, single-instance
        ├── backend.ts                 # auto-start / stop the bundled backend
        ├── tray.ts                    # system-tray icon + menu (close-to-tray)
        ├── overlay.ts                 # frameless always-on-top overlay window
        ├── health.ts                  # shared backend reachability check
        ├── config.ts                  # env / file / default settings resolution
        ├── store.ts                   # persisted overlay bounds (state)
        ├── icon.ts                    # shared app-icon resolver
        └── preload.ts                 # tiny read-only bridge for backend-down.html
```
