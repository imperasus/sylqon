"""Offline tests for the meta-build aggregator (op.gg replacement source)."""
from datetime import datetime, timedelta, timezone

import pytest
from app import metabuild, store
from app.advice import benchmarks
from app.models import Base, MetaBuild
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

CORE = sorted(benchmarks.CORE_ITEM_IDS)[:4]
ROLE_POOL = sorted(benchmarks.CORE_ITEM_IDS)[4:12]  # enemy-BOTTOM final items
BOOT = sorted(benchmarks.BOOT_IDS)[0]
STARTER = sorted(benchmarks.STARTER_IDS)[0]


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def jinx_match(match_id, *, win=True, core=None, spells=(4, 7), keystone=8008):
    core = core or CORE[:3]
    participants = []
    for i in range(10):
        p = {
            "puuid": f"p-{match_id}-{i}",
            "participantId": i + 1,
            "teamId": 100 if i < 5 else 200,
            "championName": "Jinx" if i == 3 else f"Filler{i}",
            "championId": 222 if i == 3 else 1000 + i,
            "teamPosition": ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"][i % 5],
            "win": (i < 5) == win,
        }
        if i == 8:  # enemy BOTTOM's final inventory feeds the role item pool
            p.update({f"item{j}": iid for j, iid in enumerate(ROLE_POOL[:6])})
        if i == 3:
            p.update({
                "summoner1Id": spells[0], "summoner2Id": spells[1],
                "perks": {
                    "statPerks": {"offense": 5005, "flex": 5008, "defense": 5001},
                    "styles": [
                        {"style": 8000, "selections": [{"perk": keystone}, {"perk": 9101},
                                                       {"perk": 9104}, {"perk": 8014}]},
                        {"style": 8100, "selections": [{"perk": 8139}, {"perk": 8135}]},
                    ],
                },
            })
        participants.append(p)
    match = {
        "metadata": {"matchId": match_id},
        "info": {"queueId": 420, "gameDuration": 1800, "gameVersion": "16.13.1.1",
                 "gameCreation": 1751000000000, "participants": participants},
    }
    events = [
        {"type": "ITEM_PURCHASED", "timestamp": 5000, "participantId": 4, "itemId": STARTER},
        {"type": "ITEM_PURCHASED", "timestamp": 400000, "participantId": 4, "itemId": BOOT},
    ]
    for j, iid in enumerate(core):
        events.append({"type": "ITEM_PURCHASED", "timestamp": 600000 + j * 300000,
                       "participantId": 4, "itemId": iid})
    for lvl in range(1, 16):  # max Q, then W, then E
        slot = 1 if lvl <= 5 else (2 if lvl <= 10 else 3)
        events.append({"type": "SKILL_LEVEL_UP", "timestamp": lvl * 60000,
                       "participantId": 4, "skillSlot": slot})
    timeline = {"info": {"frames": [{"timestamp": 0, "events": events,
                                     "participantFrames": {}}],
                         "frameInterval": 60000}}
    return match, timeline


def seed(session_factory, count=10, **kw):
    with session_factory() as s:
        for i in range(count):
            m, t = jinx_match(f"EUN1_{i}", **kw)
            store.insert_match_bundle(s, m, t, region="europe")


def test_payload_shape_and_modal_values(session_factory):
    seed(session_factory, count=10)
    with session_factory() as s:
        p = metabuild.compute_meta_build(s, "jinx", "BOTTOM")
    assert p is not None
    assert p["games"] == 10
    assert p["core_item_ids"] == CORE[:3]          # median purchase order
    assert p["boot_ids"][0] == BOOT
    assert p["starter_item_ids"] == [STARTER]
    assert p["summoner_spell_ids"] == [4, 7]
    assert p["primary_page_id"] == 8000
    assert p["primary_rune_ids"][0] == 8008        # keystone first
    assert p["secondary_rune_ids"] == [8139, 8135]
    assert p["stat_mod_ids"] == [5005, 5008, 5001]
    assert p["skill_order"] == ["Q", "W", "E"]
    # all 10 games ran the same trio → one core option, matching the core
    assert p["core_options"] == [{"ids": CORE[:3], "play": 10, "win": 10}]
    # every key the local opgg_to_build reads is present
    for key in ("role", "starter_item_ids", "boot_ids", "core_item_ids",
                "core_options",
                "fourth_item_ids", "fifth_item_ids", "sixth_item_ids",
                "primary_page_id", "primary_rune_ids", "secondary_page_id",
                "secondary_rune_ids", "stat_mod_ids", "summoner_spell_ids",
                "summoner_spell_options", "skill_order"):
        assert key in p, key


def test_core_options_aggregated_and_merged(session_factory):
    """Per-game first-3-completed trios aggregate into core_options: purchase-
    order permutations of one set merge (play/win summed, most-played ordering
    kept), combos under MIN_COMBO_GAMES are dropped, ranking is by play."""
    combo_a = CORE[:3]
    combo_a_perm = [CORE[1], CORE[0], CORE[2]]   # same set, different order
    combo_b = [CORE[0], CORE[1], CORE[3]]
    combo_c = [CORE[0], CORE[2], CORE[3]]        # only 2 games → dropped
    with session_factory() as s:
        i = 0

        def put(core, win, n):
            nonlocal i
            for _ in range(n):
                m, t = jinx_match(f"EUN1_{i}", core=core, win=win)
                store.insert_match_bundle(s, m, t, region="europe")
                i += 1

        put(combo_a, True, 4)
        put(combo_a, False, 2)
        put(combo_a_perm, True, 2)
        put(combo_b, True, 3)
        put(combo_b, False, 2)
        put(combo_c, True, 2)
        p = metabuild.compute_meta_build(s, "jinx", "BOTTOM")

    opts = p["core_options"]
    assert opts[0] == {"ids": list(combo_a), "play": 8, "win": 6}   # 6+2 merged
    assert opts[1] == {"ids": list(combo_b), "play": 5, "win": 3}
    assert len(opts) == 2                                           # C dropped


def test_situational_pool_padded_to_minimum(session_factory):
    # Jinx buys only her 3-core → own situational is empty; the pool must be
    # padded to MIN_SITUATIONAL from the role's common completed items.
    seed(session_factory, count=10, core=CORE[:3])
    with session_factory() as s:
        p = metabuild.compute_meta_build(s, "jinx", "BOTTOM")
    pool = p["fourth_item_ids"] + p["fifth_item_ids"] + p["sixth_item_ids"]
    assert len(pool) == metabuild.MIN_SITUATIONAL
    assert set(pool).isdisjoint(set(p["core_item_ids"]))
    assert set(pool) <= set(ROLE_POOL) | set(CORE)  # padded from role inventories


def test_min_games_gate(session_factory):
    seed(session_factory, count=metabuild.MIN_GAMES - 1)
    with session_factory() as s:
        assert metabuild.compute_meta_build(s, "jinx", "BOTTOM") is None


def test_role_normalization():
    assert metabuild.normalize_role("bottom") == "BOTTOM"
    assert metabuild.normalize_role("ADC") == "BOTTOM"
    assert metabuild.normalize_role("support") == "UTILITY"
    assert metabuild.normalize_role("mid") == "MIDDLE"
    assert metabuild.normalize_role("nonsense") is None


def test_cache_and_staleness(session_factory):
    seed(session_factory, count=10)
    with session_factory() as s:
        first = metabuild.get_meta_build(s, "Jinx", "adc")
        assert first is not None
        row = s.get(MetaBuild, ("jinx", "BOTTOM"))
        assert row.samples == 10

        # fresh cache row is served without recompute (marker survives)
        row.payload = {**row.payload, "marker": True}
        s.commit()
        assert metabuild.get_meta_build(s, "Jinx", "adc").get("marker") is True

        # stale row triggers recompute (marker gone)
        row.computed_at = datetime.now(timezone.utc) - timedelta(hours=48)
        s.commit()
        assert "marker" not in metabuild.get_meta_build(s, "Jinx", "adc")
