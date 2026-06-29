"""op.gg sync — run order and payload shapes for the Claude-driven ingest.

There is no automated transport here (by design — see the v2 plan). A full sync
is performed by Claude Code calling the op.gg MCP tools in conversation and
POSTing the parsed results to the ingest endpoints, in this order:

1. Roles + meta tiers/win/pick  (per role)
   tool:  lol_list_lane_meta_champions(position=<adc|mid|jungle|top|support>)
   fields: data.positions.<pos>[].{champion, tier, win_rate, pick_rate}
   POST  /api/ingest/lane-meta  {position, entries:[{champion, tier, win_rate, pick_rate}]}

2. Counters + synergies  (per champion x role, for champions worth scoring)
   tool:  lol_get_champion_analysis(champion=<UPPER_SNAKE>, position=<pos>, game_mode="ranked",
            fields: data.{damage_type, strong_counters[].{champion_name,win_rate},
                          weak_counters[].{champion_name,win_rate},
                          synergies.<allypos>[].{synergy_champion_name,win_rate}})
   POST  /api/ingest/counters   {champion, position, strong_counters:[...], weak_counters:[...]}
   POST  /api/ingest/synergies  {champion, position, synergies:[{synergy_champion_name, win_rate}]}

3. Builds  (per champion x role) — already handled by the existing
   POST /api/opgg-build path, which now also mirrors into ChampionBuild.

4. Pro / esports builds  (optional, per champion x role) — Claude-driven:
   tool:  lol_get_pro_player_riot_id(pro_name=...) -> riot id, then
          lol_get_summoner_game_detail(...) for the items/runes the pro ran.
   POST  /api/pro-build  {champion, role, pro_name, team, region, patch,
                          items:[{id,name}], skill_order, spell1, spell2, keystone}
   Read back via GET /api/pro-builds?champion=&role= (shown in the champion modal).

The whole-universe meta/counters/synergies/builds (steps 1-3) run unattended via
:func:`run_full_sync` (direct op.gg HTTP, no MCP, fetched concurrently over a
shared keep-alive session). There is no manual trigger: the runtime fires one
automatically whenever the live patch differs from the last synced patch —
including the first run, where nothing is synced yet (see ``AUTO_FULL_SYNC`` and
``Runtime._maybe_auto_full_sync``). ``python -m sylqon.mcp.sync`` stays available
as a dev/CLI entry point.

The pure normalize/upsert logic lives in :mod:`sylqon.mcp.ingest`; the
FastAPI request models live in :mod:`sylqon.server`. This module is the
human/agent-facing playbook plus the typed payload shapes below.
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass
class LaneMetaEntry:
    champion: str          # display name, e.g. "Miss Fortune"
    tier: int | None = None
    win_rate: float = 0.0  # fraction (0.55)
    pick_rate: float = 0.0


@dataclass
class CounterEntry:
    champion_name: str     # display name
    win_rate: float = 0.0  # winning side's rate, fraction


@dataclass
class SynergyEntry:
    synergy_champion_name: str
    win_rate: float = 0.0


@dataclass
class LaneMetaPayload:
    position: str
    entries: list[LaneMetaEntry] = field(default_factory=list)


@dataclass
class CountersPayload:
    champion: str
    position: str
    strong_counters: list[CounterEntry] = field(default_factory=list)
    weak_counters: list[CounterEntry] = field(default_factory=list)


@dataclass
class SynergiesPayload:
    champion: str
    position: str
    synergies: list[SynergyEntry] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Automated full sync (direct op.gg HTTP — no MCP/Node needed)
# ---------------------------------------------------------------------------
def run_full_sync(region: str | None = None, sleep: float = 0.12,
                  progress=None, store=None, catalog=None) -> dict:
    """Populate the DB for EVERY champion in EVERY role it plays: roles + meta
    tiers/win/pick, counters, synergies and builds.

    Pulls straight from op.gg's champion API via :mod:`sylqon.mcp.opgg_http`,
    fetching champion-roles concurrently (``OPGG_SYNC_WORKERS`` over a shared
    keep-alive session) while DB writes stay single-threaded. Runs unattended;
    idempotent — safe to re-run each patch. ``progress(done, total)`` is called
    periodically.

    When a ``store`` (:class:`~sylqon.cache.store.MetaCache`) is passed, every
    converted build is also mirrored into the live injection cache in one batched
    write at the end — so the "X BUILDS" badge reflects the whole universe and any
    champion is instantly injectable in draft (no live op.gg fetch). Pass the
    runtime ``catalog`` too so the cache builds carry the same patch as the rest
    of the app (no patch drift); when omitted a fresh ``Catalog`` is built.
    """
    from sylqon import config
    from sylqon.cache.opgg import opgg_to_build
    from sylqon.data.catalog import Catalog
    from sylqon.db.migrate import seed_champions
    from sylqon.db.schema import Champion
    from sylqon.db.session import get_session, init_db
    from sylqon.mcp import ingest, opgg_http

    init_db()
    if catalog is None:
        catalog = Catalog()
    catalog.refresh_if_stale()
    session = get_session()
    cache_writes: list[tuple] = []  # (champion, role, build, raw_payload) for the live cache
    counts = {"champions": 0, "builds": 0, "counters": 0, "synergies": 0,
              "cached": 0, "skipped": 0}
    try:
        # Self-bootstrap: ensure a Champion row exists per Data Dragon champion so
        # the sync can populate roles/stats/builds even on a fresh DB.
        seed_champions(session, catalog)
        session.commit()
        rows = {c.riot_key: c for c in session.query(Champion).all() if c.riot_key}

        meta = opgg_http.fetch_all_meta(region)
        if not meta:
            return {"error": "op.gg meta fetch returned nothing", **counts}

        # 1) roles + per-role meta stats (one pass, no network beyond the meta call)
        for cid, positions in meta.items():
            champ = rows.get(cid)
            if champ is None:
                continue
            roles = list(champ.roles or [])
            stats = dict(champ.op_gg_stats or {})
            for p in positions:
                r = p["role"]
                if r not in roles:
                    roles.append(r)
                stats[r] = {"tier": p["tier"],
                            "win_rate": ingest.winrate_pct(p["win_rate"]),
                            "pick_rate": ingest.winrate_pct(p["pick_rate"])}
            champ.roles = roles
            champ.op_gg_stats = stats
            counts["champions"] += 1
        session.commit()

        # 2) per champion x role: build + counters + synergies. The network
        # fetches run in a small thread pool over the shared keep-alive session;
        # the DB writes stay on this thread (the SQLAlchemy session isn't shared).
        tasks = [(cid, p["role"]) for cid, positions in meta.items()
                 if rows.get(cid) is not None for p in positions]
        total = len(tasks)
        done = 0

        def fetch_one(task: tuple[int, str]):
            cid, role = task
            try:
                payload, counters = opgg_http.fetch_detail(cid, role, region)
                synergies = opgg_http.fetch_synergies(cid, role, region)
            except Exception:
                log.warning("op.gg fetch failed for cid=%s %s", cid, role, exc_info=True)
                payload, counters, synergies = None, [], []
            if sleep:
                time.sleep(sleep)  # per-worker politeness delay
            return cid, role, payload, counters, synergies

        workers = max(1, config.OPGG_SYNC_WORKERS)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(fetch_one, t) for t in tasks]
            for fut in as_completed(futures):
                cid, role, payload, counters, synergies = fut.result()
                champ = rows.get(cid)
                if champ is None:
                    done += 1
                    continue
                try:
                    if payload:
                        build = opgg_to_build(payload, catalog)
                        if build and ingest.mirror_build(session, champ.name, role, build,
                                                         "opgg-sync", catalog.patch):
                            counts["builds"] += 1
                            # Mirror into the live injection cache too (batched
                            # write below) so every champion is instantly buildable.
                            cache_writes.append((champ.name, role, build, payload))
                    for c in counters:
                        other = rows.get(c["champion_id"])
                        if other is None:
                            continue
                        adv = max(-10.0, min(10.0, (0.5 - c["opp_winrate"]) * 100))
                        ingest.upsert_counter(session, champ.id, other.id, role, round(adv, 2))
                        counts["counters"] += 1
                    for s in synergies:
                        ally = rows.get(s["synergy_champion_id"])
                        if ally is None:
                            continue
                        ingest.upsert_synergy(session, champ.id, ally.id, role,
                                              ingest.synergy_from_winrate(s["win_rate"]))
                        counts["synergies"] += 1
                except Exception:
                    counts["skipped"] += 1
                    log.warning("sync failed for %s %s", champ.name, role, exc_info=True)
                done += 1
                if done % 25 == 0:
                    session.commit()
                    log.info("synced %d/%d champion-roles", done, total)
                    if progress:
                        progress(done, total)
        session.commit()
        # Pre-warm the live injection cache in one batched save (avoids the O(n²)
        # disk churn of a per-build put_build during the loop).
        if store is not None and cache_writes:
            counts["cached"] = store.bulk_put_builds(cache_writes, catalog.patch)
    finally:
        session.close()
    log.info("Full sync complete: %s", counts)
    return counts


def main() -> None:
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description="Full op.gg -> SQLite sync (all champions, all roles).")
    ap.add_argument("--region", default=None, help="op.gg region (default: OPGG_REGION env / na)")
    ap.add_argument("--sleep", type=float, default=0.12, help="delay between requests (seconds)")
    args = ap.parse_args()
    result = run_full_sync(region=args.region, sleep=args.sleep)
    print(f"Full sync complete: {result}")


if __name__ == "__main__":
    main()
