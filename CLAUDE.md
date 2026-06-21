# CLAUDE.md

<!-- maintainer notes
  Rebranded from Antigravity → Sylqon on 2026-06-15
  DB renamed antigravity.db → sylqon.db (legacy may still exist locally)
  LCU injection tag must stay "Sylqon Meta" — matches existing client item sets in the wild
  Release: only .github/workflows/release.yml fires on vX.Y.Z tag push; never on PRs/main
  Path-scoped constraints live in .claude/rules/ — edit there, not here
-->

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**Sylqon** — a League of Legends counter-draft AI assistant. It watches live Champion Select via the League Client Universal (LCU) API, recommends the best champion from the user's pool, then generates counter-loadouts (items, runes, summoner spells) using a local Ollama LLM and injects them directly into the client. A second, read-only **in-game overlay** ("coach") watches the Live Client Data API and surfaces role-aware missions while you play.

This is a monorepo: the Python backend (`sylqon/`), the React dashboard (`ui/`), and two Electron shells (`sylqon-desktop/`, `sylqon-overlay-shell/`) that frame backend URLs as desktop/overlay windows.

## Commands

**Backend**
```bash
python -m sylqon.server          # Start with dashboard (port 8077)
python -m sylqon.main            # Headless CLI mode
python -m pytest tests/ -q            # Run the offline test suite (~116 tests)
python -m pytest tests/test_scoring.py -q   # Run a single test file
python -m pytest tests/ -k scoring    # Run tests matching an expression
```

**Frontend**
```bash
npm run dev --prefix ui               # Dev server on port 5173 (proxies /api → 8077)
npm run build --prefix ui             # Production build → ui/dist/
```

**Desktop / overlay (Electron)** — `sylqon-desktop/` is the shipped app (wraps the dashboard + overlay window and auto-starts a PyInstaller-bundled backend). `sylqon-overlay-shell/` is the standalone overlay-only shell.
```bash
npm run dev   --prefix sylqon-desktop   # Run the Electron shell in dev
npm run build --prefix sylqon-desktop   # Build the Windows installer (NSIS)
```

**Live integration checks** (require running services — not part of the offline suite)
```bash
python tests/live_lcu_check.py        # Test LCU connection
python tests/live_ai_check.py         # Test Ollama integration
python tests/live_cache_check.py      # Validate build cache
```

**Environment variables**
```
OLLAMA_URL          (default: http://127.0.0.1:11434)
OLLAMA_MODEL        (default: llama3.1)
OLLAMA_TIMEOUT      (default: 45s)
OPGG_REGION         (default: na)
AG_CACHE_TTL        (default: 86400)
LOL_LOCKFILE        (override lockfile path)
DB_PATH             (default: sylqon.db)
SYLQON_CACHE_DIR    (writable cache dir; override for packaged builds)
SYLQON_LOG_DIR      (writable log dir; override for packaged builds)
MISSION_TUNING_JSON (overlay mission thresholds, e.g. '{"adc_cs_delta": 50}')
```

## Architecture

### Draft data flow (champ-select pipeline)

1. **LCU connect** — locate lockfile → authenticate HTTPS/WSS to League client (`lcu/client.py`)
2. **Champ select events** — WebSocket subscription to `OnJsonApiEvent_lol-champ-select_v1_session` (`lcu/events.py`)
3. **State diffing** — two cheap signatures gate Ollama calls (avoid redundant LLM invocations)
4. **Draft intelligence** — instant, network-free comp classification + counter advice (`analysis/draft_intel.py`)
5. **Champion recommendation** — heuristic score first (instant), then Ollama refines in background (`ai/pick_prompt.py`, `analysis/scoring.py`)
6. **Build compile** — cache → live op.gg fetch → seed fallback (`cache/store.py`, `cache/opgg_fetch.py`, `cache/seed.py`)
7. **Counter-loadout generation** — Ollama prompt with full enemy team context (`ai/prompts.py`, `ai/engine.py`); build variants labeled by archetype (`analysis/build_archetype.py`, `ai/build_variants.py`)
8. **Validation** — every AI field checked against static tables (runes/spells/items) in `data/static.py`
9. **Injection** — PUT item set + rune page, PATCH summoner spells, all tagged "Sylqon Meta" (`lcu/injector.py`)

### In-game overlay flow (`livegame/`)

Strictly **read-only and observational** — see "Riot-safe" below. Polls Riot's Live Client Data API (`https://127.0.0.1:2999/.../allgamedata`, self-signed cert, no auth) via `livegame/client.py`, builds a `LiveGameState` snapshot (`state.py`), and runs a `MissionEngine` (`engine.py`) that keeps 1–2 active role-aware missions (`missions.py`, `champion_missions.py`), resolves them, and feeds a progression service (`progression.py`). `demo.py` drives the overlay without a live game. Served at `/overlay`; state at `/api/overlay/state` and `/api/live/state`.

### Backend layout (`sylqon/`)

| Module | Role |
|--------|------|
| `server.py` | FastAPI app; bridges runtime state to HTTP endpoints, the React dashboard, and the overlay |
| `runtime.py` | Core orchestrator — connection watchdog, state machine, coordinates all subsystems |
| `loadout.py` | `Loadout` dataclass; deterministic build-slot logic |
| `config.py` | Single source of truth for all paths, timeouts, LLM settings, mission tuning |
| `lcu/` | LCU credentials, WebSocket listener, lobby parser, item/rune injector, match history |
| `livegame/` | Read-only in-game overlay coach — Live Client Data client, mission engine, progression |
| `ai/` | Ollama engine (temp=0, seed=1337), prompt builders, build variants, mission + match-review prompts |
| `analysis/` | Champion scoring, draft intel (comp classification), build-archetype labeling |
| `cache/` | `meta_cache.json` keyed by champion name; op.gg payload conversion + fetch; seed builds |
| `db/` | SQLite via SQLAlchemy — champion counters/synergies, match ingestion, migration |
| `data/` | Static Data Dragon catalog, rune/spell/item tables, hardcoded seed builds |
| `mcp/` | Model Context Protocol integration for op.gg data ingestion |

### Frontend layout (`ui/src/`)

`App.jsx` routes between phase-driven views based on backend state:
- **DashboardView** — champion pool management, win-rate stats, tier list, Meta Scout
- **LiveDraftView** — real-time three-column draft board with recommendation overlay
- **PostLockView** — final items, runes, AI explanation after champion lock

`api.js` polls `/api/state` and manages all server communication. Components consume this via hooks in `hooks/`.

### Database (SQLite, `sylqon.db`)

Schema lives in `db/schema.py`. Migration is handled by `db/migrate.py`. Tables: champions, counters, synergies, matches, match_participants. (A legacy `antigravity.db` may exist from before the rename — `sylqon.db` is current.)

### Release pipeline

`.github/workflows/release.yml` builds the Windows installer and publishes a GitHub Release on every `vX.Y.Z` tag push (never on PRs/main). It runs on `windows-latest`, sets up both Node.js and Python, bundles the backend with PyInstaller, and builds the Electron app in `sylqon-desktop/`.
