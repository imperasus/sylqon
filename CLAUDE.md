# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**Sylqon** — a League of Legends counter-draft AI assistant. It watches live Champion Select via the League Client Universal (LCU) API, recommends the best champion from the user's pool, then generates counter-loadouts (items, runes, summoner spells) using a local Ollama LLM and injects them directly into the client.

## Commands

**Backend**
```bash
python -m sylqon.server          # Start with dashboard (port 8077)
python -m sylqon.main            # Headless CLI mode
python -m pytest tests/ -q            # Run 29 offline tests
python -m pytest tests/test_scoring.py -q   # Run a single test file
```

**Frontend**
```bash
npm run dev --prefix ui               # Dev server on port 5173 (proxies /api → 8077)
npm run build --prefix ui             # Production build → ui/dist/
```

**Live integration checks** (require running services)
```bash
python tests/live_lcu_check.py        # Test LCU connection
python tests/live_ai_check.py         # Test Ollama integration
python tests/live_cache_check.py      # Validate build cache
```

**Environment variables**
```
OLLAMA_URL      (default: http://127.0.0.1:11434)
OLLAMA_MODEL    (default: llama3.1)
OLLAMA_TIMEOUT  (default: 45s)
OPGG_REGION     (default: na)
AG_CACHE_TTL    (default: 86400)
LOL_LOCKFILE    (override lockfile path)
DB_PATH         (default: sylqon.db)
```

## Architecture

### Data flow

1. **LCU connect** — locate lockfile → authenticate HTTPS/WSS to League client (`lcu/client.py`)
2. **Champ select events** — WebSocket subscription to `OnJsonApiEvent_lol-champ-select_v1_session` (`lcu/events.py`)
3. **State diffing** — two cheap signatures gate Ollama calls (avoid redundant LLM invocations)
4. **Champion recommendation** — heuristic score first (instant), then Ollama refines in background (`ai/pick_prompt.py`, `analysis/scoring.py`)
5. **Build compile** — cache → live op.gg fetch → seed fallback (`cache/store.py`, `cache/opgg_fetch.py`, `data/seed.py`)
6. **Counter-loadout generation** — Ollama prompt with full enemy team context (`ai/prompts.py`, `ai/engine.py`)
7. **Validation** — every AI field checked against static tables (runes/spells/items) in `data/static.py`
8. **Injection** — PUT item set + rune page, PATCH summoner spells, all tagged "Sylqon Meta" (`lcu/injector.py`)

### Backend layout (`sylqon/`)

| Module | Role |
|--------|------|
| `server.py` | FastAPI app; bridges runtime state to HTTP endpoints and the React dashboard |
| `runtime.py` | Core orchestrator — connection watchdog, state machine, coordinates all subsystems |
| `loadout.py` | `Loadout` dataclass; deterministic build-slot logic |
| `config.py` | Single source of truth for all paths, timeouts, LLM settings |
| `lcu/` | LCU credentials, WebSocket listener, lobby parser, item/rune injector, match history |
| `ai/` | Ollama engine (temp=0, seed=1337), prompt builders, build variant handling |
| `cache/` | `meta_cache.json` keyed by champion name; op.gg payload conversion |
| `db/` | SQLite via SQLAlchemy — champion counters/synergies, match ingestion, migration |
| `data/` | Static Data Dragon catalog, rune/spell/item tables, hardcoded seed builds |
| `analysis/` | Champion scoring that combines DB stats, pool order, and threat tables |
| `mcp/` | Model Context Protocol integration for op.gg data ingestion |

### Frontend layout (`ui/src/`)

`App.jsx` routes between three phase-driven views based on backend state:
- **DashboardView** — champion pool management, win-rate stats, tier list, Meta Scout
- **LiveDraftView** — real-time three-column draft board with recommendation overlay
- **PostLockView** — final items, runes, AI explanation after champion lock

`api.js` polls `/api/state` and manages all server communication. Components consume this via hooks in `hooks/`.

### Key constraints

- **LCU item set limit** — 64 KB per item set; JSON must stay compact (no pretty-print)
- **Ollama is optional** — system falls back to heuristic scoring if Ollama is unreachable; never block the UI waiting for LLM
- **Match history deduplication** — LCU match-history endpoint ignores `begIndex`/`endIndex`; always dedupe by `gameId`
- **op.gg builds are cached** — `meta_cache.json` with 24h TTL; live fetch only on cache miss or expiry
- **Validation is mandatory** — LCU rejects invalid rune/spell IDs silently; all AI output must pass `data/static.py` checks before injection

### Database (SQLite, `sylqon.db`)

Schema lives in `db/schema.py`. Migration is handled by `db/migrate.py`. Tables: champions, counters, synergies, matches, match_participants.
