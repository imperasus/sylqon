# Debugging Sylqon

A repeatable process for diagnosing problems across the backend (Python
pipeline) and the frontend (React dashboard + Electron shells). Sylqon degrades
gracefully by design — most failures return empty/`None` rather than crashing —
so the first job when something "just doesn't work" is to make the failure
*visible*. This guide is built around the diagnostics added for exactly that.

---

## 0. Turn on visibility first

| What | How |
|------|-----|
| Backend DEBUG logs | `SYLQON_DEBUG=1 python -m sylqon.server` (or `SYLQON_LOG_LEVEL=DEBUG`) |
| Structured (JSON) logs | `SYLQON_LOG_JSON=1` (one JSON object per line — easy to grep/ship) |
| Frontend verbose console | open the dashboard with `?debug=1`, or `localStorage.sylqon_debug = "1"` |
| Electron DevTools | `SYLQON_DEVTOOLS=1` (desktop + overlay shells open DevTools detached) |

Log file: `sylqon.log` in the project root (or `$SYLQON_LOG_DIR`). It now
**rotates** (5 MB × 3 backups), so it can't grow unbounded.

---

## 1. First stop: `/api/debug/health`

Always start here. It re-probes every dependency *at request time* (not the
startup cache), so a service that came up late — or died since — is reported
correctly.

```bash
curl -s http://127.0.0.1:8077/api/debug/health | python -m json.tool
```

```jsonc
{
  "ok": true,
  "lcu":      { "connected": false },
  "ollama":   { "available": true, "url": "http://127.0.0.1:11434", "model": "llama3.1" },
  "opgg":     { "reachable": true, "region": "na" },
  "database": { "ok": true, "path": "sylqon.db" },
  "cache":    { "builds": 168 },
  "log":      { "level": "INFO", "path": "sylqon.log" }
}
```

Whatever is `false` is your lead.

- **`/api/debug/config`** — the effective (non-secret) configuration. Answers
  "what settings is it *actually* running with?" Secrets (Riot API key) show
  only as present/absent.
- **`/api/debug/logs?level=error&limit=50`** — recent pipeline events over HTTP,
  no need to open the log file.

---

## 2. Symptom → where to look

| Symptom | Likely layer | Files / checks |
|---------|--------------|----------------|
| Dashboard is blank / "BACKEND OFFLINE" pill | frontend ↔ backend link | Is the backend up? `curl /api/state`. Check DevTools console for `[sylqon] GET /api/state failed`. |
| No champion recommendation | Ollama | `health.ollama.available`? `ai/engine.py`. Falls back to the deterministic heuristic when Ollama is down. |
| No build / empty loadout | op.gg → cache → seed | `health.opgg.reachable`? `cache/opgg_fetch.py` → `cache/store.py` → seed fallback `cache/seed.py`. |
| Nothing injected into the client | LCU | `health.lcu.connected`? `lcu/client.py` (connect), `lcu/injector.py` (PUT/PATCH). DEBUG logs show the handshake. |
| Overlay shows nothing in-game | Live Client Data API | `livegame/client.py` (port 2999, self-signed). No active game ⇒ silent by design. |
| A UI action does nothing | frontend action path | Toast now shows `Hiba: …` on failure; DevTools console logs the endpoint + status. |
| The whole UI white-screens | React render error | The `ErrorBoundary` panel shows the stack; details also in the console. |

---

## 3. Reproduce without a live game

You don't need League running to exercise most of the app:

```bash
# Draft pipeline — synthetic champ-select lobby
curl -X POST http://127.0.0.1:8077/api/demo -H 'Content-Type: application/json' -d '{}'
curl -X DELETE http://127.0.0.1:8077/api/demo

# In-game overlay — simulated game
curl -X POST http://127.0.0.1:8077/api/live/demo -H 'Content-Type: application/json' -d '{"role":"middle"}'

# Overlay from your last ranked match (needs RIOT_API_KEY + RIOT_SELF_PUUID)
curl -X POST http://127.0.0.1:8077/api/live/demo/last-match

# Wipe overlay progression while iterating
curl -X POST http://127.0.0.1:8077/api/overlay/debug/reset
```

The frontend has a **DEMO** toggle in the StatusBar for the draft lobby.

---

## 4. Errors are structured now

Any unhandled exception in an API endpoint returns a structured 500 instead of
an opaque stack, and every request carries a short trace id (also in the
`X-Trace-Id` response header):

```json
{ "error": "ValueError", "detail": "…", "trace_id": "a1b2c3d4" }
```

Grep the log for that `trace_id` to find the full server-side traceback and the
request timing line.

---

## 5. Tests & linters

```bash
python -m pytest tests/ -q                 # full offline suite (no network/LCU/Ollama)
python -m pytest tests/test_error_paths.py -q   # diagnostics + error-path coverage
ruff check .                               # Python lint (config in pyproject.toml)
npm run lint --prefix ui                   # dashboard ESLint
npm run build --prefix ui                  # production build (catches JSX/import errors)
```

CI (`.github/workflows/ci.yml`) runs the offline suite as a gate and the linters
as a non-blocking job.

---

## 6. Live integration checks (require real services)

Not part of the offline suite — run them against a live environment when a real
integration misbehaves:

| Script | Verifies |
|--------|----------|
| `python tests/live_lcu_check.py`   | LCU injection is idempotent (no duplicate pages/sets) |
| `python tests/live_ai_check.py`    | Ollama determinism (fixed seed, temp 0) |
| `python tests/live_cache_check.py` | Build cache freshness |
| `python tests/live_riot_check.py`  | Riot API scouting endpoints |
