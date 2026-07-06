# Sylqon Ingestion Service

Hosted-side Match-V5 ingestion + rule-based post-game advice (roadmap Phase 0 +
the codeable core of Phase 1, see `docs/FEJLESZTESI_TERV.md`). Standalone
FastAPI app — does **not** import the local `sylqon/` package.

## What it does

1. **Ingest** — Riot ID → PUUID → last N match ids → match + timeline →
   Postgres, idempotently (`ON CONFLICT DO NOTHING`; known matches skip the API
   entirely). All Riot calls go through a dual-window token-bucket rate limiter
   (Redis Lua script shared across workers; in-memory fallback).
2. **Advice** — for a stored (match, player): five deterministic heuristics
   (death context, CS benchmark, item timing, vision, objective presence) →
   weighted top-1 lesson → 2–3 sentence HU + EN template text, cached per
   match+player in the `advice` table.

## Local pilot (test the full stack before hosting)

`powershell -ExecutionPolicy Bypass -File run_stack.ps1` starts Postgres+Redis
(with `restart: unless-stopped`), the API on :8090 and the Discord bot,
logging to `api.log` / `bot.log` next to the script (`-Stop` shuts it down).
Point the desktop app at it with a user-level env var, then restart the app:

```powershell
setx SYLQON_META_URL http://localhost:8090
```

From then on live builds and the full sync (trigger: `POST /api/sync/full` on
the desktop backend, port 8077) come from your own aggregation; op.gg is only
a fallback. Containers survive reboots as long as Docker Desktop auto-starts.

## Prerequisites

- Python 3.11+, `pip install -r requirements.txt`
- Docker (Postgres 16 + Redis 7 via compose)
- `RIOT_API_KEY` env var (the repo-root `.env` is picked up automatically)

## Run

```bash
docker compose up -d                          # Postgres + Redis (from this dir)
uvicorn app.main:app --port 8090              # API (creates tables on startup)

# or headless:
python -m app.cli ingest "Name#TAG" --count 20
python -m app.cli advise EUN1_1234567890 <puuid> --lang hu
```

## Discord bot (slash commands)

Set `DISCORD_BOT_TOKEN`, then `python -m app.bot`. Commands: `/link Név#TAG`
(account linking + backfill; linked users are auto-watched), `/utolsomeccs`
(latest match's lesson with 👍/👎 buttons → `advice_feedback`), `/riport`
(weekly summary on demand), `/pool` (pool-coverage report for the linked
account), `/build <champion>` and `/matchup <a> <b>` (own-data aggregation —
honest "not enough data yet" below the sample floor), `/beallitas` (advice +
reports channel and guild language, needs Manage Server). The match watcher
runs inside the bot process and posts advice embeds to the configured channel,
mentioning the linked user; without a configured channel it falls back to the
webhook below. When a reports channel is configured, the weekly summary for
every linked account is posted there automatically once per 7 days.

## Discord delivery (webhook MVP)

Set `DISCORD_WEBHOOK_URL` (service-local `.env` is picked up), then:

```bash
python -m app.cli watch            # poll tracked accounts, post advice for new matches
python -m app.cli watch --once     # single cycle (first run baselines the backlog silently)
python -m app.cli notify <match_id> <puuid> --lang hu   # one-off manual send
python -m app.cli report --days 7 --lang hu --send      # weekly trend report → webhook
python -m app.cli benchmarks                            # recompute own-data role medians
```

Tracked accounts: `WATCH_PUUIDS` (comma-separated; falls back to `RIOT_SELF_PUUID`).
Poll cadence `WATCH_POLL_SECONDS` (default 180), language `WATCH_LANG` (`hu`/`en`).
The uvicorn app starts the watcher automatically when the webhook URL is set.
Dedupe lives in the `deliveries` table; failed sends are retried next cycle.

## Public web pages (S3 website MVP)

Served by the same FastAPI app (no build step): `/` (Riot ID form),
`/pool-report?riot_id=Name%23TAG` (server-rendered pool-coverage audit),
`/champions` and `/champion/{name}` (SEO-friendly presence/win-rate, core
items and lane-matchup pages from our own aggregation). All copy follows the
pool-coverage framing — no skill-rating vocabulary (enforced by a test).

## API

| Endpoint | Purpose |
|---|---|
| `POST /api/ingest?game_name=X&tag_line=Y&count=20` | Fetch + persist matches and timelines; returns insert/skip/fail counts |
| `GET /api/advice/{match_id}/{puuid}?lang=hu` | Top-1 post-game lesson (HU/EN), generated on first call, cached after |
| `GET /api/pool/{game_name}/{tag_line}` | Champion-pool coverage report (Phase 2 / S3 core): per-role performance + blind-pick safety + counter coverage from own aggregation, with a suggested 3-champion pool; `?refresh=false` skips the ingest. CLI: `python -m app.cli pool "Name#TAG"` |
| `GET /api/meta-sync/full?min_games=8` | The complete op.gg-replacement bundle in one response: per-role meta stats (tier/WR/presence), build payloads, lane counters and same-team synergies for every champion+role above the sample floor. The local app's full sync consumes this via `sylqon/mcp/svc_http.py` when `SYLQON_META_URL` is set (op.gg only as fallback). Prewarm: `python -m app.cli metasync` |
| `GET /api/meta-build/{champion}?role=bottom` | Own-data build payload (items from timeline purchase order, modal rune pages/shards/spells, Q/W/E max order) in the exact op.gg payload shape the local client's `opgg_to_build` consumes — the op.gg replacement source. 404 below the sample floor; cached in `meta_builds` for 24h. Local opt-in: set `SYLQON_META_URL` for the desktop app |
| `GET /healthz` | Liveness |

## Configuration (env)

| Variable | Default | Notes |
|---|---|---|
| `RIOT_API_KEY` | — | required; fail-fast at startup |
| `RIOT_MASS_REGION` / `RIOT_PLATFORM_REGION` | `europe` / `euw1` | falls back to the local app's `RIOT_API_MASS_REGION` / `RIOT_API_REGION` |
| `DATABASE_URL` | `postgresql+psycopg://sylqon:sylqon@localhost:5432/sylqon` | |
| `REDIS_URL` | `redis://localhost:6379/0` | |
| `RATELIMIT_MODE` | `redis` | `memory` = single-process fallback |
| `RATE_LIMIT_BURST` / `RATE_LIMIT_SUSTAINED` | `450/10` / `27000/600` | production key with 10% margin; personal key: `18/1` / `95/120` — if you see a 429 with a ~95s Retry-After, your key runs personal limits: use the latter |
| `CRAWL_ENABLED` / `CRAWL_BATCH` / `CRAWL_MATCH_COUNT` | `1` / `3` / `10` | co-player seed crawl: each watch cycle also ingests the least-recently-crawled discovered players, growing the benchmark/build/matchup pool; `CRAWL_RECRAWL_HOURS` (72) throttles re-visits |
| `RIOT_MATCH_COUNT` | `20` | ids per ingest run |
| `ADVICE_TUNING_JSON` | `{}` | heuristic threshold overrides |

## Tests

```bash
python -m pytest tests -q      # offline: no network, no Docker (Redis tests auto-skip)
```

## Exit-criterion demo (Phase 0)

```bash
docker compose up -d
python -m app.cli ingest "Name#TAG" --count 20   # → inserted: 20, timelines: 20
python -m app.cli ingest "Name#TAG" --count 20   # → skipped_existing: 20, inserted: 0  (idempotent)
```

## Notes

- **ToS framing rule (S3):** pool numbers measure *pool coverage* (blind-pick
  safety, counter coverage, own performance) — never player skill. No MMR/ELO
  vocabulary in UI copy or API field names.

- `app/advice/data/completed_items.json` is generated from the repo's
  `cache/ddragon_catalog.json` (core-item detection for the item-timing
  heuristic; filter: `completed && gold >= 2000 && id < 100000` — the id cap
  excludes Arena-mode item variants). Regenerate on patch bumps.
- Benchmark tables in `app/advice/benchmarks.py` are Iron–Gold seed medians.
  `app/aggregate.py` computes role medians from our own stored SR matches
  (every match contributes all 10 participants); once a role clears
  `BENCHMARK_MIN_SAMPLES` (default 40), the own-data values override the seed
  in the advice pipeline. The watcher refreshes them after every new ingest.
  Aggregation is partitioned by rank band (`iron-bronze`, `silver-gold`,
  `plat-emerald`, `diamond+`, plus `ALL`): the seed crawl fetches each crawled
  player's solo-queue rank (League-V4 → `player_ranks`), and advice prefers
  the player's own band once it clears the threshold, falling back to ALL.
  Backfill ranks for already-stored players: `python -m app.cli ranks`.
