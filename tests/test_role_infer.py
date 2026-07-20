"""F1 — enemy role inference guards.

Covers the pure assignment core (no DB) and the DB-backed enrich path that
resurrects the lane layer when Riot hides the enemy team's assignedPosition.
"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from sylqon.analysis import role_infer
from sylqon.db.schema import Base, Champion
from sylqon.lcu.lobby import ChampPick


def _session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True, expire_on_commit=False)()


def _champ(session, name, key, pick_rates: dict):
    """pick_rates: {role: pick_rate} → op_gg_stats prior for inference."""
    c = Champion(name=name, riot_key=key, slug=name.replace(" ", ""),
                 roles=list(pick_rates),
                 op_gg_stats={r: {"tier": 2, "pick_rate": pr}
                              for r, pr in pick_rates.items()})
    session.add(c)
    session.flush()
    return c


def _pick(name, cid, role=""):
    return ChampPick(name=name, champion_id=cid, role=role, side="enemy",
                     damage_type="AD")


# -- pure assignment ---------------------------------------------------------
def test_argmax_assignment_when_unconstrained():
    cands = [
        {"key": 1, "weights": {"top": 9.0, "middle": 1.0}, "pin": None},
        {"key": 2, "weights": {"middle": 8.0, "bottom": 2.0}, "pin": None},
    ]
    got = role_infer.assign_roles(cands)
    assert got[1][0] == "top"
    assert got[2][0] == "middle"


def test_joint_solve_pulls_flex_to_the_open_role():
    # Both champions favour middle, but champ 1 is a hard mid; the joint solve
    # must push the flex (champ 2) off mid onto its next-best lane rather than
    # greedily giving each its own argmax and colliding.
    cands = [
        {"key": 1, "weights": {"middle": 10.0}, "pin": None},            # mid-only
        {"key": 2, "weights": {"middle": 6.0, "top": 5.0}, "pin": None},  # flex
    ]
    got = role_infer.assign_roles(cands)
    assert got[1][0] == "middle"
    assert got[2][0] == "top"


def test_pins_are_hard_constraints():
    cands = [
        {"key": 1, "weights": {"middle": 10.0}, "pin": "top"},   # pinned top
        {"key": 2, "weights": {"middle": 9.0, "bottom": 1.0}, "pin": None},
    ]
    got = role_infer.assign_roles(cands)
    assert got[1] == ("top", 1.0)          # pin wins, full confidence
    assert got[2][0] == "middle"           # free to take its argmax


def test_confidence_flags_flex():
    cands = [{"key": 1, "weights": {"top": 5.0, "middle": 5.0}, "pin": None}]
    role, conf = role_infer.assign_roles(cands)[1]
    assert conf < role_infer.FLEX_CONFIDENCE     # 0.5 share → flagged as flex
    cands = [{"key": 2, "weights": {"top": 19.0, "middle": 1.0}, "pin": None}]
    _, conf2 = role_infer.assign_roles(cands)[2]
    assert conf2 >= role_infer.FLEX_CONFIDENCE    # concentrated → confident


def test_unknown_champion_still_assigned():
    # No weights at all → tiny flat prior; must still receive a role.
    cands = [{"key": 1, "weights": {}, "pin": None}]
    assert role_infer.assign_roles(cands)[1][0] in role_infer.ROLES


# -- DB-backed inference / enrichment ----------------------------------------
def test_infer_enemy_roles_from_db():
    session = _session()
    _champ(session, "Darius", 122, {"top": 12.0})
    _champ(session, "LeeSin", 64, {"jungle": 15.0})
    _champ(session, "Ahri", 103, {"middle": 10.0})
    session.commit()
    picks = [_pick("Darius", 122), _pick("LeeSin", 64), _pick("Ahri", 103)]
    got = role_infer.infer_enemy_roles(session, picks)
    assert got[122][0] == "top"
    assert got[64][0] == "jungle"
    assert got[103][0] == "middle"


def test_enrich_fills_only_missing_roles():
    session = _session()
    _champ(session, "Sett", 875, {"top": 6.0, "utility": 5.0})
    _champ(session, "Gnar", 150, {"top": 9.0})
    session.commit()
    # Gnar's role is already known (top) → pins it, forcing the Sett flex to its
    # open lane (support), and the known role is never overwritten.
    known_gnar = _pick("Gnar", 150, role="top")
    flex_sett = _pick("Sett", 875, role="")
    filled = role_infer.enrich_roles(session, [known_gnar, flex_sett])
    assert filled == 1
    assert known_gnar.role == "top"        # untouched
    assert flex_sett.role == "utility"     # inferred into the open lane


def test_enrich_no_op_when_all_known():
    session = _session()
    picks = [_pick("Darius", 122, role="top")]
    assert role_infer.enrich_roles(session, picks) == 0
