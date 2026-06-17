"""Offline tests for the per-pair counter/synergy ranking (live-draft Top-3).

Covers the tag-heuristic floor (no DB, no Ollama), the op.gg pairwise booster
over an in-memory SQLite store, and the inverse DB queries that feed it.

Run: python -m pytest tests/test_pairwise.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from sylqon.analysis import pairwise
from sylqon.db import queries
from sylqon.db.schema import Base, Champion, ChampionCounter, ChampionSynergy
from sylqon.lcu.lobby import ChampPick


# -- fixtures ----------------------------------------------------------------
def _cand(name, *, tags=(), dmg="AD", threats=(), slug=None):
    return {"name": name, "slug": slug or name.replace(" ", ""),
            "tags": list(tags), "damage_type": dmg, "threats": list(threats)}


def _pick(name, *, role="middle", tags=(), dmg="AP", threats=()):
    return ChampPick(name=name, champion_id=hash(name) % 1000, role=role,
                     side="enemy", damage_type=dmg, tags=list(tags),
                     threats=list(threats))


def _session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True, expire_on_commit=False)()


def _champ(session, name, key, role):
    c = Champion(name=name, riot_key=key, slug=name.replace(" ", ""), roles=[role])
    session.add(c)
    session.flush()
    return c


# -- tag heuristic floor -----------------------------------------------------
def test_marksman_counters_tank():
    enemy = _pick("Malphite", role="top", tags=["Tank"], dmg="AP", threats=["tank", "heavy_cc"])
    score, reasons = pairwise.score_candidate_into_enemy(_cand("Vayne", tags=["Marksman"]), enemy)
    assert score >= 2
    assert "Anti-Tank" in reasons


def test_frontline_is_safe_into_burst():
    enemy = _pick("Zed", tags=["Assassin"], dmg="AD", threats=["burst_ad"])
    score, reasons = pairwise.score_candidate_into_enemy(
        _cand("Malphite", tags=["Tank"], dmg="AP", threats=["tank", "heavy_cc"]), enemy)
    assert "Safe Into Burst" in reasons
    assert score >= 2


def test_engage_dives_squishy_carry():
    enemy = _pick("Jinx", role="bottom", tags=["Marksman"], dmg="AD")
    diver = _cand("Malphite", tags=["Tank", "Fighter"], dmg="AP", threats=["heavy_cc", "tank"])
    score, reasons = pairwise.score_candidate_into_enemy(diver, enemy)
    assert "Engage" in reasons
    assert score >= 2


def test_synergy_scaling_carry_with_engage():
    ally = _pick("Leona", role="utility", tags=["Tank", "Support"], threats=["heavy_cc"])
    score, reasons = pairwise.score_candidate_with_ally(_cand("Jinx", tags=["Marksman"]), ally)
    assert "Cash-in Engage" in reasons
    assert score >= 2


def test_synergy_diversifies_damage():
    ally = _pick("Garen", role="top", tags=["Fighter"], dmg="AD")
    score, reasons = pairwise.score_candidate_with_ally(_cand("Syndra", tags=["Mage"], dmg="AP"), ally)
    assert "Mixed Damage" in reasons


# -- ranking (no DB) ---------------------------------------------------------
def test_rank_counters_no_session_is_tag_only():
    enemy = _pick("Malphite", role="top", tags=["Tank"], threats=["tank", "heavy_cc"])
    candidates = [
        _cand("Vayne", tags=["Marksman"]),      # Anti-Tank → +2
        _cand("Yasuo", tags=["Fighter"]),        # no signal → 0
        _cand("Caitlyn", tags=["Marksman"]),     # Anti-Tank → +2
    ]
    ranked = pairwise.rank_counters_for_enemy(enemy, candidates, limit=3)
    assert len(ranked) == 3
    scores = [r["score"] for r in ranked]
    assert scores == sorted(scores, reverse=True)
    assert ranked[0]["name"] in {"Vayne", "Caitlyn"}      # marksmen lead
    assert ranked[-1]["name"] == "Yasuo"
    assert all(r["edge"] is None for r in ranked)          # no DB → no numeric edge


def test_rank_respects_limit():
    enemy = _pick("Ahri")
    cands = [_cand(f"C{i}") for i in range(8)]
    assert len(pairwise.rank_counters_for_enemy(enemy, cands, limit=3)) == 3


# -- ranking (DB booster) ----------------------------------------------------
def test_db_booster_breaks_tag_ties():
    """Two candidates tie on tags; the real op.gg matchup edge decides + surfaces."""
    session = _session()
    enemy = _champ(session, "Ahri", 103, "middle")          # squishy mage, no tank tag
    a = _champ(session, "Annie", 1, "middle")
    b = _champ(session, "Syndra", 134, "middle")
    # Annie hard-counters Ahri; Syndra is even.
    session.add(ChampionCounter(champion_id=a.id, counter_id=enemy.id, role="middle",
                                advantage_score=10.0))
    session.commit()

    enemy_pick = _pick("Ahri", tags=["Mage"], dmg="AP")
    candidates = [_cand("Syndra", tags=["Mage"], dmg="AP"),
                  _cand("Annie", tags=["Mage"], dmg="AP")]
    ranked = pairwise.rank_counters_for_enemy(
        enemy_pick, candidates, session=session, role="middle", limit=3)
    assert ranked[0]["name"] == "Annie"
    assert ranked[0]["edge"] == 10.0
    assert ranked[0]["score"] > ranked[1]["score"]


def test_synergy_db_booster():
    session = _session()
    ally = _champ(session, "Lulu", 117, "utility")
    a = _champ(session, "Kogmaw", 96, "bottom")
    b = _champ(session, "Ashe", 22, "bottom")
    session.add(ChampionSynergy(champion_id=a.id, synergy_id=ally.id, role="bottom",
                                synergy_score=9.0))
    session.commit()

    ally_pick = _pick("Lulu", role="utility", tags=["Support"])
    candidates = [_cand("Ashe", tags=["Marksman"]), _cand("Kogmaw", tags=["Marksman"])]
    ranked = pairwise.rank_synergies_for_ally(
        ally_pick, candidates, session=session, role="bottom", limit=3)
    assert ranked[0]["name"] == "Kogmaw"
    assert ranked[0]["edge"] == 9.0


# -- inverse DB queries ------------------------------------------------------
def test_inverse_queries():
    session = _session()
    enemy = _champ(session, "Zed", 238, "middle")
    me = _champ(session, "Malzahar", 90, "middle")
    session.add(ChampionCounter(champion_id=me.id, counter_id=enemy.id, role="middle",
                                advantage_score=7.0))
    session.commit()

    id_map = queries.champion_ids_by_name(session, ["Malzahar", "Zed", "Nope"])
    assert id_map == {"Malzahar": me.id, "Zed": enemy.id}
    assert queries.counters_against(session, enemy.id, "middle", [me.id]) == {me.id: 7.0}
    assert queries.counters_against(session, enemy.id, "middle", []) == {}
    assert queries.synergies_with(session, enemy.id, "middle", [me.id]) == {}


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
