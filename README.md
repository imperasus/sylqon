# Sylqon — Counter-Draft AI for League of Legends

Sylqon watches your live **Champion Select**, recommends *which* champion to
play from your pool, then builds the optimal **items, runes and summoner spells**
against the specific enemy team — and imports the whole loadout into the League
client automatically, before the game starts.

It pairs a real-time read of the League client (LCU) with a current-patch op.gg
meta build and a **local Ollama LLM** that adapts the build to the five enemy
threats. Everything runs on your machine; no account credentials ever leave it.

```
                          ┌──────────────────────── your machine ────────────────────────┐
  op.gg internal API ───▶ │  build cache  ─┐                                              │
  (live, on cache miss)   │                │  candidate build                             │
                          │  match history │      │                                       │
  League client (LCU) ──▶ │  WebSocket ───▶│  draft state ─▶ Ollama (counter-analysis) ─┐ │
  champ select + history  │                │      │                                    │ │
                          │   FastAPI bridge + Hextech dashboard (React)  ◀── state ────┘ │
                          │                       │                                       │
                          │   item set / rune page / spells ─▶ LCU PATCH/PUT (idempotent) │
                          └───────────────────────────────────────────────────────────────┘
```

---

## What it does

- **Champion recommendation** — from your prioritised pool, suggests the best
  champion to play given allies and enemies already picked (synergy + counter
  scoring, refined by Ollama).
- **Counter-itemisation** — picks situational items against the enemy comp
  (anti-heal vs healing, %-pen vs tanks, QSS/Mercurial vs hard CC, survival vs
  assassins), keeping a fixed op.gg core.
- **Rune fine-tuning** — keeps the op.gg page but nudges the flexible defensive
  picks toward the enemy damage profile (armor ↔ magic resist).
- **Summoner spells** — defaults to op.gg's most-used spells and only deviates
  in strongly justified cases, and only into spells op.gg actually runs on the
  champion. D-key = utility (or Smite for jungle), F-key = mobility.
- **Auto-import** — writes the item set, rune page and spells into the client
  the moment the whole lobby has locked. Idempotent: it always overwrites a
  single page/set titled **"Sylqon Meta"**, never accumulating clutter.
- **Live fetch** — if you pick a champion with no cached build, it pulls the
  current ranked build straight from op.gg at runtime and feeds it to the AI.
- **Personal stats** — reads your local match history for a per-champion
  win-rate / games overlay.

---

## The dashboard (three screens)

Open **http://127.0.0.1:8077** after starting the server. The view follows the
game phase automatically; you can also pin a tab manually.

### 1. Dashboard
- Profile banner (summoner, pool size, cached builds, patch).
- **Your Champion Pool** — a visual avatar grid per role, each with your
  personal win-rate / games. A big desaturated role watermark shows the active
  filter. Edit via search or by adding from the meta list (the icon flies into
  your pool).
- **Ollama Meta Scout** — a recommendation card: the strongest pick for the
  role from your pool × the meta × your personal win-rate, with the reasoning
  written by Ollama.
- **Patch Meta** — op.gg tier list per role (circular icons, S+/S glow, win/pick
  rates, one-click add to pool).

### 2. Live Draft
- Three columns: **your team | AI zone | enemy team**, populated live as people
  hover and lock, with summoner-spell icons and enemy threat badges.
- A large **AI recommendation** card (which champion to play) plus a scored
  synergy/counter list of your pool.

### 3. Runes & Items (post-lock)
- **Item order** — starting / core / situational (with build-order arrows) plus
  the AI-picked-vs-this-comp annotation, the situational **alternatives**, and
  the D/F summoner spells.
- **Rune circuit** — both trees with connector lines and names, stat shards.
- **Ollama Stratégia** — a plain-language explanation of why the AI deviated
  from the meta build, with item/mechanic keywords highlighted.
- An import-status banner (ready / importing / imported).

A **SIMULATE** button in the top bar builds a synthetic lobby so you can explore
the Live Draft and Post-Lock screens without being in a real game.

---

## How it works (end to end)

1. **Connect** — `lcu/client.py` reads the client lockfile / process for the LCU
   port + token. `runtime.py` polls the gameflow phase as a connection watchdog.
2. **Champ select via WebSocket** — on entering champ select, `lcu/events.py`
   subscribes to `OnJsonApiEvent_lol-champ-select_v1_session`. The current state
   is seeded immediately (the WS only pushes *deltas*), so the dashboard switches
   to Live Draft the moment champ select opens — before you even hover.
3. **State diffing** — two cheap signatures gate the heavy work so Ollama isn't
   hammered: a *display* signature drops pure timer ticks, and a *trigger*
   signature only fires on a lock-in or when it becomes your turn.
4. **Recommendation** — `ai/pick_prompt.py` scores your pool (heuristic first,
   instant), then Ollama refines it in the background.
5. **Build** — once the whole lobby is locked, `loadout.py` reads the candidate
   build (`cache/store.py`; cache → live op.gg fetch → seed fallback), then
   `ai/prompts.py` compiles the enemy threat profile into a prompt and
   `ai/engine.py` asks Ollama for the counter-loadout.
6. **Validate** — every AI field is checked against the static rune/spell/item
   tables (`data/static.py`); anything invalid falls back to the deterministic
   build. The injector therefore always receives a complete, legal loadout.
7. **Inject** — `lcu/injector.py` PUTs the item set + rune page and PATCHes the
   summoner spells, all under the single "Sylqon Meta" title.

---

## Architecture

### Backend (`sylqon/`, Python)

| Module | Responsibility |
|---|---|
| `runtime.py` | The orchestrator: connection watchdog, WebSocket lifecycle, state publishing, recommendation, build compile, injection, champion stats, Meta Scout. |
| `server.py` | FastAPI bridge — serves the built UI and the JSON API; runs the runtime in a background thread. |
| `lcu/client.py` | LCU credentials + authenticated HTTPS client (self-signed cert, compact-JSON bodies for the 64 KB item-set limit). |
| `lcu/events.py` | Champ-select WebSocket listener (auto-reconnect, delta dispatch). |
| `lcu/lobby.py` | Parses the champ-select session into a `MatchContext` (allies, enemies, roles, threats, lock state, my-turn) + state signatures. |
| `lcu/injector.py` | Idempotent item-set / rune-page / spell injection with guardrails. |
| `lcu/history.py` | Per-champion win-rate / games from local match history (deduped by gameId; SR queues only). |
| `cache/store.py` | `meta_cache.json` build store + curated champion pool. |
| `cache/opgg.py` | Converts an op.gg payload into the internal build dict. |
| `cache/opgg_fetch.py` | Live op.gg ranked-build fetch (used on a cache miss). |
| `cache/seed.py` / `data/seed_builds.json` | Hardcoded final-fallback builds. |
| `data/catalog.py` | Data Dragon champion/item catalog (+ LCU supplement). |
| `data/static.py` | Runes, spells, shards, threat tables, slotting rules. |
| `ai/engine.py` | Deterministic Ollama call (`temperature=0`, fixed seed, `format=json`). |
| `ai/prompts.py` | Counter-loadout prompt + tactical/rune doctrine. |
| `ai/pick_prompt.py` | Champion-recommendation scoring + prompt. |
| `loadout.py` | `Loadout` model, deterministic build, AI-output validation. |

### Frontend (`ui/`, React + Vite + Tailwind v4)

| File | Responsibility |
|---|---|
| `App.jsx` | Phase-driven router across the three screens. |
| `api.js` | Hooks: live state poll, static data, pool, champion stats, scout, perk icons. |
| `components/TopBar.jsx` | Brand, nav tabs, status dots, SIMULATE toggle. |
| `components/DashboardView.jsx` | Pool grid, stat overlay, Meta Scout, tier list, flying-add. |
| `components/LiveDraftView.jsx` | Three-column draft board + recommendation. |
| `components/PostLockView.jsx` | Item order, rune circuit, AI insights. |
| `components/shared.jsx` | Shared primitives (portraits, spell pips, badges). |

---

## Data sources

- **League Client (LCU)** — champ select, summoner, match history, injection.
  Local only, lockfile-authenticated.
- **op.gg internal API** (`lol-api-champion.op.gg`) — live ranked builds and the
  per-role meta tier list. Undocumented; on failure the seed build is used.
- **Data Dragon / Community Dragon** — champion, item, rune and spell icons.
- **Ollama** (`http://127.0.0.1:11434`) — local LLM for counter-analysis and
  recommendation wording. Optional: without it the heuristic build is used.

---

## Setup

**Requirements:** Python 3.11+, Node 18+ (to build the UI), the League client,
and [Ollama](https://ollama.com) with a model pulled (default `llama3.1`).

```bash
# 1. Python deps
pip install -r requirements.txt

# 2. Build the UI (outputs ui/dist, which the server serves)
cd ui && npm install && npm run build && cd ..

# 3. Pull an Ollama model (once)
ollama pull llama3.1

# 4. Run — dashboard on http://127.0.0.1:8077
python -m sylqon.server
```

There is also a headless CLI (`python -m sylqon.main`) that runs the same
pipeline without the dashboard.

During UI development, run the Vite dev server (`npm run dev --prefix ui`,
port 5173) alongside the Python server; CORS is preconfigured.

---

## Configuration (environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `OLLAMA_URL` | `http://127.0.0.1:11434` | Ollama endpoint. |
| `OLLAMA_MODEL` | `llama3.1` | Model tag (resolves `llama3.1` → installed `llama3.1:8b`). |
| `OLLAMA_TIMEOUT` | `45` | Per-call timeout (seconds). |
| `OPGG_REGION` | `na` | Region for live op.gg fetch (meta is region-agnostic). |
| `OPGG_TIMEOUT` | `12` | op.gg fetch timeout (seconds). |
| `OPGG_RETRIES` | `2` | Retries on transient op.gg failures (timeout/5xx). |
| `OPGG_SYNC_WORKERS` | `6` | Parallel network workers for the full sync. |
| `AG_CACHE_TTL` | `86400` | Build cache freshness window (seconds). |
| `BUILD_WARM_INTERVAL` | `3600` | Background build warm-up cadence (seconds); `0` disables. |
| `SYLQON_AUTO_FULL_SYNC` | `1` | Auto-run a full sync when the patch changes (`0` disables). |
| `LOL_LOCKFILE` | — | Override path to the League client lockfile. |

---

## HTTP API

Served by `server.py` on port 8077.

| Method & path | Purpose |
|---|---|
| `GET /api/state` | Full runtime snapshot (lcu, ollama, cache, lobby, recommendation, build, injection) — the dashboard polls this. |
| `GET /api/champions` | All champions (name/slug/tags) for the picker. |
| `GET /api/meta` | op.gg meta tier list per role. |
| `GET /api/pool` / `PUT /api/pool` | Read / replace the curated champion pool. |
| `GET /api/champion-stats` | Per-champion win-rate / games from match history. |
| `GET /api/scout?role=` | Meta Scout recommendation for a role. |
| `POST /api/inject` | Force-inject the current loadout (`optimized`/`standard`). |
| `POST` / `DELETE /api/demo` | Start / stop the synthetic lobby. |
| `POST /api/opgg-build` | Accept an op.gg payload from the MCP tool and cache it. |

---

## Safety & guardrails

- **Idempotent injection** — exactly one item set and one rune page, always
  titled "Sylqon Meta", overwritten via PUT. Your own pages are untouched.
- **AI as a filter only** — the model can never invent items/runes/spells; every
  field is validated against the static tables and falls back deterministically.
- **Spell conservatism** — spells stay on op.gg's defaults unless strongly
  justified, and only ever change into spells op.gg observes on that champion.
- **Inject on full lock only** — the loadout is imported against the final,
  fully-revealed enemy comp, never on a partial draft.
- **Graceful degradation** — no Ollama → heuristic build; no op.gg → seed build;
  no WebSocket → polling fallback. The pipeline never blocks on a dependency.

---

## Testing

```bash
python -m pytest tests/ -q     # 543 offline tests, no client/Ollama/network needed
```

Covers the extraction/conversion pipeline, spell + stat-shard guardrails,
AI-output validation, prompt compilation, state diffing (hover vs lock vs
timer), pre-pick context, champion recommendation, and live-fetch payload
shaping.

---

## Notes & limitations

- The op.gg internal API is undocumented and may change; the seed build is the
  safety net if it does.
- Item names can appear in the League client's locale (e.g. Hungarian) because
  some items are supplemented from the localized LCU catalog — IDs are correct
  and injection works regardless of the displayed name.
- Match history sometimes ignores pagination on certain clients; stats are
  deduped by `gameId` so counts stay accurate.
- For authorized personal use with your own League account. Automating client
  interactions can carry risk; use responsibly.

---

## In-game overlay coach (read-only)

A separate, **strictly read-only** feature that coaches you *during* the game.
It reads Riot's local **Live Client Data API**
(`https://127.0.0.1:2999/liveclientdata/allgamedata`) and shows at most **1–2
missions** (e.g. "Don't die for 2 minutes", "Secure a dragon in 4 min", "Place 3
control wards").

**Per-champion missions.** Each champion has its own rolling mission queue. After
every game on a champion, the local LLM reads that game's post-game stats (deaths,
CS/min, vision, result) and generates personalised missions tailored to your
weaknesses — always emitted as a *structured, validated* mission (a closed type +
param vocabulary the live engine can score), never free text. Completing them
levels up **that champion's mastery**, and the account level is the sum of all
champion points. A champion with no AI missions yet falls back to the static
role catalog, so there's always something to do (see
`livegame/champion_missions.py`, `ai/mission_prompt.py`). Generation runs at game
*end* — never on the live path — so a slow or absent Ollama never blocks the
overlay; the role catalog simply covers the next game.

**Safety guarantees:**

- The overlay only ever performs HTTP **GET** requests against the localhost
  Live Client Data API. It **never** writes to, injects into, or automates input
  for the League client.
- Every mission is based on information the player already sees on screen — CS,
  deaths, wards, objective events, timers. No fog-of-war breaking, no hidden
  cooldown tracking, no scripting.
- TLS is verified against Riot's bundled CA (`sylqon/data/riotgames.pem`)
  when present; otherwise it falls back to unverified transport for the
  localhost-only endpoint and logs a one-time warning.

**Try it:**

```bash
python -m sylqon.server          # serves the dashboard + overlay on :8077
```

- Overlay (OBS browser source / corner widget): `http://127.0.0.1:8077/overlay`
- Debug: `GET /api/live/state` (raw normalized snapshot),
  `GET /api/overlay/state` (active missions + progression).
- No game running? Drive a **simulated** game to test the overlay end-to-end:
  `POST /api/live/demo` (optional `{"role": "middle"}`) and `DELETE /api/live/demo`.
  `POST /api/overlay/debug/reset` wipes progression.

**Configuration** (env vars): `LIVE_POLL_SECONDS` (default 1.0),
`OVERLAY_MAX_MISSIONS` (2), `CHAMPION_MISSION_TARGET` (3 — rolling per-champion
queue size), `MISSION_TUNING_JSON` (override individual mission params),
`MISSION_TYPES_ENABLED` (comma-separated allow-list of mission types).
