# Sylqon Overlay (shell)

A tiny **Electron window shell** that frames the existing Sylqon `/overlay` web
UI as a borderless, transparent, always-on-top desktop window — summoned with a
global hotkey.

It is a **thin, read-only frame around a URL**. All game logic (missions, stats)
lives in the Sylqon backend that serves `/overlay`; this app just displays it.

## Riot-safe by design

This shell does **not** interact with the League of Legends process in any way:

- ❌ No reading or writing of game process memory
- ❌ No DLL / code / overlay injection into the game
- ❌ No simulated or forwarded keyboard / mouse input to the game

It is just a normal always-on-top desktop window positioned over the game.
The optional *click-through* feature uses Electron's built-in
`setIgnoreMouseEvents` — a standard windowing attribute that lets clicks fall to
whatever is beneath the window. It is **not** an input hook and reads nothing
from the game.

## Requirements

- Node.js 18+ and npm
- Windows (this build targets Windows; macOS/Linux are not configured)
- The Sylqon backend running and serving the overlay URL (default
  `http://127.0.0.1:8077/overlay`)

## Install

```bash
cd sylqon-overlay-shell
npm install
```

## Run in dev mode

```bash
npm run dev
```

This compiles the TypeScript and launches Electron. The window starts **hidden**
— press the toggle hotkey (default **F10**) to show/hide it. It appears fixed in
the **top-left** corner of the primary monitor.

> Tip: start your Sylqon backend first (`python -m sylqon.server`) so the overlay
> has something to render. If the backend is down, the window logs a clear
> `ERR_CONNECTION_REFUSED` message and stays blank — no crash.

## Hotkeys

| Action | Default | Override (env) |
|--------|---------|----------------|
| Show / hide overlay | `F10` | `SYLQON_TOGGLE_HOTKEY` |
| Toggle click-through | `F9` | `SYLQON_CLICKTHROUGH_HOTKEY` |

- **Click-through ON** (default): clicks pass through the overlay to the game.
- **Click-through OFF**: the overlay is interactive (you can click its UI).

Hotkeys use [Electron Accelerator](https://www.electronjs.org/docs/latest/api/accelerator)
syntax, e.g. `F10`, `Alt+O`, `CommandOrControl+Shift+S`.

## Configuration

Settings resolve in this order: **environment variable → config file → default**.

### Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `SYLQON_OVERLAY_URL` | `http://127.0.0.1:8077/overlay` | URL to load |
| `SYLQON_TOGGLE_HOTKEY` | `F10` | Show/hide hotkey |
| `SYLQON_CLICKTHROUGH_HOTKEY` | `F9` | Click-through toggle hotkey |
| `SYLQON_CLICK_THROUGH` | `true` | Start in click-through mode (`0`/`false` = interactive) |
| `SYLQON_OVERLAY_CONFIG` | — | Explicit path to a config file |

Example (PowerShell):

```powershell
$env:SYLQON_OVERLAY_URL = "http://127.0.0.1:8077/overlay"
$env:SYLQON_TOGGLE_HOTKEY = "Alt+O"
npm run dev
```

### Config file

Copy `sylqon-overlay.config.example.json` to `sylqon-overlay.config.json`
(placed next to the executable, or pointed at via `SYLQON_OVERLAY_CONFIG`):

```json
{
  "overlayUrl": "http://127.0.0.1:8077/overlay",
  "toggleHotkey": "F10",
  "clickThroughHotkey": "F9",
  "clickThrough": true
}
```

A missing or malformed file is ignored (env vars / defaults still apply).

## Build a Windows executable

```bash
npm run dist
```

This compiles TypeScript and runs `electron-builder`, producing a single
portable **`release/SylqonOverlay.exe`** — no installer, just run it.

For a faster unpacked build (a folder, not a single .exe):

```bash
npm run dist:dir
```

Output lands in `release/`.

## Project structure

```
sylqon-overlay-shell/
├── package.json                         # scripts + electron-builder config
├── tsconfig.json                        # TS → dist/
├── sylqon-overlay.config.example.json   # copy to sylqon-overlay.config.json
├── README.md
└── src/
    ├── main.ts                          # Electron main process (window, hotkeys)
    └── config.ts                        # env / file / default resolution
```

## Scripts

| Script | Does |
|--------|------|
| `npm run dev` | Compile + launch in Electron |
| `npm run build:ts` | Compile TypeScript only |
| `npm start` | Launch already-compiled `dist/` |
| `npm run dist` | Build portable `SylqonOverlay.exe` |
| `npm run dist:dir` | Build unpacked app folder |
