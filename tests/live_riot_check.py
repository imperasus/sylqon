"""Live Riot API integration check — NOT part of the offline suite.

Requires a valid RIOT_API_KEY + RIOT_SELF_PUUID and network access. Exercises
every endpoint the live-game scout depends on against the account owner's PUUID
and reports whether real data comes back, then runs the full scout pipeline
(fingerprint + account + comatches + current-champ stats) with a small match
window so it stays well under the dev-key rate limit.

Run: python tests/live_riot_check.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

from sylqon import config
from sylqon.riot import api, scout


def mask(p: str) -> str:
    return f"{p[:6]}…{p[-4:]}" if p and len(p) > 12 else "(none)"


def line(ok: bool, label: str, detail: str = "") -> None:
    print(f"  [{'OK ' if ok else 'XX'}] {label}{(' — ' + detail) if detail else ''}")


def main() -> int:
    key = config.RIOT_API_KEY
    puuid = config.RIOT_SELF_PUUID
    print(f"Region: {config.RIOT_API_REGION} | Mass: {config.RIOT_API_MASS_REGION} "
          f"| PUUID: {mask(puuid)}")
    if not key:
        print("RIOT_API_KEY not set — cannot test."); return 1
    if not puuid:
        print("RIOT_SELF_PUUID not set — cannot test puuid-based endpoints."); return 1

    # 0) Key validity / region sanity via a raw LEAGUE-V4 call (captures status).
    base = f"https://{config.RIOT_API_REGION}.api.riotgames.com"
    try:
        r = requests.get(f"{base}/lol/league/v4/entries/by-puuid/{puuid}",
                         headers={"X-Riot-Token": key}, timeout=10)
        print(f"\nKey check: LEAGUE-V4 HTTP {r.status_code}")
        if r.status_code in (401, 403):
            print("  -> key is INVALID/EXPIRED or wrong region/route. Stopping.")
            return 1
        if r.status_code == 429:
            print("  -> rate-limited (429). Key works but is throttled (dev key).")
    except requests.RequestException as e:
        print(f"  -> network error: {e}"); return 1

    print("\nEndpoints:")
    # 1) LEAGUE-V4 ranked stats
    entries = api.get_ranked_stats(puuid)
    if isinstance(entries, list):
        solo = next((e for e in entries if e.get("queueType") == "RANKED_SOLO_5x5"), None)
        line(True, "LEAGUE-V4 ranked",
             f"{len(entries)} entr(y/ies); soloQ={scout.rank_label(solo) or 'Unranked'}")
    else:
        line(False, "LEAGUE-V4 ranked", "no data")

    # 2) MASTERY-V4 top
    mastery = api.get_top_mastery(puuid, 5)
    top_champ = mastery[0].get("championId") if mastery else 0
    if mastery:
        line(True, "MASTERY-V4 top",
             f"{len(mastery)} champs; top={top_champ} "
             f"L{mastery[0].get('championLevel')} {mastery[0].get('championPoints')} pts")
    else:
        line(False, "MASTERY-V4 top", "no data")

    # 3) MATCH-V5 ids (now ALL queues incl. Normal Draft)
    ids = api.get_match_ids(puuid, 5)
    line(bool(ids), "MATCH-V5 ids (all queues)", f"{len(ids)} ids" if ids else "none")

    # 4) MATCH-V5 object — verify shape premade detection + fingerprint need
    if ids:
        m = api.get_match(ids[0])
        info = (m or {}).get("info") or {}
        parts = info.get("participants") or []
        line(bool(parts), "MATCH-V5 object",
             f"queueId={info.get('queueId')} participants={len(parts)} "
             f"puuids={sum(1 for p in parts if p.get('puuid'))}")

    # 5) MASTERY-V4 by-champion (current-champ mastery fallback path)
    if top_champ:
        bc = api.get_mastery_by_champion(puuid, top_champ)
        line(bool(bc), "MASTERY-V4 by-champion",
             f"champ {top_champ}: L{(bc or {}).get('championLevel')} "
             f"{(bc or {}).get('championPoints')} pts" if bc else "no entry")

    # 6) SPECTATOR-V5 active game (404/None when not in a game — expected)
    g = api.get_active_game_by_puuid(puuid)
    if isinstance(g, dict):
        gp = g.get("participants") or []
        line(True, "SPECTATOR-V5 active game",
             f"IN GAME — {len(gp)} players, {sum(1 for p in gp if p.get('puuid'))} puuids revealed")
    else:
        line(True, "SPECTATOR-V5 active game", "not in a game right now (expected unless playing)")

    # 7) Full pipeline on a small window (keeps under the rate limit)
    print("\nFull pipeline (scout_puuid, match window = 8):")
    config.RIOT_MATCH_COUNT = 8
    fp, account, comatches = scout.scout_puuid(puuid)
    line(fp.games_analyzed > 0, "fingerprint",
         f"{fp.games_analyzed} SR games; main={fp.main_role or '—'}; "
         f"pool={[c.get('champion_id') for c in fp.champion_pool[:3]]}")
    line(True, "account", f"rank={account.get('rank') or 'Unranked'}; "
         f"mastery_pool={len(account.get('mastery') or [])}")
    line(bool(comatches), "comatches (premade signal)",
         f"{len(comatches)} games mapped; sample teammates="
         f"{len(next(iter(comatches.values()))) if comatches else 0}")
    if top_champ:
        cc = scout.current_champ_stats(fp, account.get("mastery"), top_champ)
        line(True, f"current_champ_stats (champ {top_champ})",
             f"games={cc['games']} wr={cc['win_rate']} "
             f"mastery={cc['mastery_points']} L{cc['mastery_level']}")

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
