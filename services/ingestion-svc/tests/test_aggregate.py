"""Offline tests for own-data benchmark aggregation and seed override."""
import pytest
from app import aggregate, config, store
from app.models import Base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def make_bundle(match_id: str, cs_at_10=70, wards=10, queue=420, duration=1800):
    roles = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]
    participants = [
        {
            "puuid": f"p-{i}",
            "participantId": i + 1,
            "teamId": 100 if i < 5 else 200,
            "teamPosition": roles[i % 5],
            "wardsPlaced": wards,
            "visionWardsBoughtInGame": 2,
        }
        for i in range(10)
    ]
    match = {
        "metadata": {"matchId": match_id},
        "info": {
            "queueId": queue,
            "gameDuration": duration,
            "gameVersion": "16.13.1.1",
            "participants": participants,
        },
    }
    frames = []
    for m in range(31):
        pframes = {
            str(pid): {
                "minionsKilled": int(cs_at_10 / 10 * m),
                "jungleMinionsKilled": 0,
                "position": {"x": 0, "y": 0},
            }
            for pid in range(1, 11)
        }
        frames.append({"timestamp": m * 60000, "events": [], "participantFrames": pframes})
    timeline = {"info": {"frames": frames, "frameInterval": 60000}}
    return match, timeline


def seed_matches(session_factory, count=5, **kwargs):
    with session_factory() as s:
        for i in range(count):
            match, timeline = make_bundle(f"EUN1_{i}", **kwargs)
            store.insert_match_bundle(s, match, timeline, region="europe")


def test_compute_medians_per_role(session_factory):
    seed_matches(session_factory, count=3, cs_at_10=70)
    with session_factory() as s:
        computed = aggregate.compute_role_benchmarks(s)
    assert set(computed) == {(r, "ALL") for r in aggregate.ROLES}
    top = computed[("TOP", "ALL")]
    assert top["samples"] == 6  # 2 TOP per match × 3 matches
    assert top["cs10"] == 70
    assert top["cs15"] == 105
    assert top["wards_per_min"] == pytest.approx(10 / 30, abs=0.01)


def test_non_sr_and_short_games_excluded(session_factory):
    with session_factory() as s:
        m1, t1 = make_bundle("EUN1_aram", queue=450)  # ARAM
        store.insert_match_bundle(s, m1, t1, region="europe")
        m2, t2 = make_bundle("EUN1_remake", duration=600)  # 10-min remake
        store.insert_match_bundle(s, m2, t2, region="europe")
        assert aggregate.compute_role_benchmarks(s) == {}


def test_refresh_persists_and_overrides_apply_above_threshold(session_factory, monkeypatch):
    seed_matches(session_factory, count=25, cs_at_10=80)  # 50 samples/role
    monkeypatch.setattr(config, "BENCHMARK_MIN_SAMPLES", 40)
    with session_factory() as s:
        aggregate.refresh_benchmarks(s)
        cs_over, vision_over = aggregate.load_effective_overrides(s)
    assert cs_over["TOP"] == {10: 80, 15: 120}
    assert "UTILITY" not in cs_over  # support stays CS-exempt
    assert vision_over["UTILITY"]["control_wards"] == 2


def test_band_partitioning_and_preference(session_factory, monkeypatch):
    from app.models import PlayerRank

    seed_matches(session_factory, count=25, cs_at_10=80)  # 50 ALL samples/role
    monkeypatch.setattr(config, "BENCHMARK_MIN_SAMPLES", 40)
    with session_factory() as s:
        # p-0 and p-5 are the two TOPs of every match → 50 samples in the band
        for puuid in ("p-0", "p-5"):
            s.add(PlayerRank(puuid=puuid, platform="eun1", tier="GOLD"))
        s.commit()
        computed = aggregate.refresh_benchmarks(s)
        assert computed[("TOP", "silver-gold")]["samples"] == 50
        assert ("JUNGLE", "silver-gold") not in computed  # no ranked junglers

        # band row wins for TOP when asking for silver-gold; others fall to ALL
        cs_band, _ = aggregate.load_effective_overrides(s, band="silver-gold")
        cs_all, _ = aggregate.load_effective_overrides(s)
        assert cs_band["TOP"] == {10: 80, 15: 120}
        assert cs_band.keys() == cs_all.keys()  # ALL fallback keeps other roles


def test_band_for_tier():
    assert aggregate.band_for_tier("GOLD") == "silver-gold"
    assert aggregate.band_for_tier("EMERALD") == "plat-emerald"
    assert aggregate.band_for_tier("CHALLENGER") == "diamond+"
    assert aggregate.band_for_tier("UNRANKED") is None
    assert aggregate.band_for_tier(None) is None


def test_old_shape_table_is_dropped_on_init():
    from app import db as app_db
    from sqlalchemy import create_engine, inspect, text

    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as conn:  # simulate the pre-band table shape
        conn.execute(text(
            "CREATE TABLE computed_benchmarks (role TEXT PRIMARY KEY, data JSON, "
            "samples INTEGER, computed_at TIMESTAMP)"
        ))
    app_db.init_db(engine)
    assert "band" in {c["name"] for c in inspect(engine).get_columns("computed_benchmarks")}


def test_new_indexes_created_on_existing_table():
    """create_all never alters existing tables — init_db must add indexes that
    models.py gained after the table shipped, and stay idempotent afterwards
    (SQLite reflection skips expression indexes, so checkfirst can't be trusted)."""
    from app import db as app_db
    from sqlalchemy import create_engine, text

    engine = create_engine("sqlite+pysqlite:///:memory:")
    app_db.init_db(engine)
    with engine.begin() as conn:  # simulate a DB from before the indexes shipped
        conn.execute(text("DROP INDEX ix_participants_champ_lower"))
        conn.execute(text("DROP INDEX ix_participants_match_role"))
    app_db.init_db(engine)
    app_db.init_db(engine)  # second startup must not re-issue CREATE INDEX
    with engine.connect() as conn:
        names = {r[0] for r in conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND tbl_name='match_participants'"))}
    assert {"ix_participants_champ_lower", "ix_participants_match_role"} <= names


def test_overrides_empty_below_threshold(session_factory, monkeypatch):
    seed_matches(session_factory, count=3)  # 6 samples/role
    monkeypatch.setattr(config, "BENCHMARK_MIN_SAMPLES", 40)
    with session_factory() as s:
        aggregate.refresh_benchmarks(s)
        cs_over, vision_over = aggregate.load_effective_overrides(s)
    assert cs_over == {} and vision_over == {}


def test_refresh_is_throttled_and_forceable(session_factory):
    seed_matches(session_factory, count=3)
    with session_factory() as s:
        assert aggregate.refresh_benchmarks(s)  # cold table → computes
        # within BENCHMARK_REFRESH_MINUTES of the last refresh → no-op
        assert aggregate.refresh_benchmarks(s) == {}
        assert aggregate.refresh_benchmarks(s, force=True)  # explicit recompute


def test_scan_limit_bounds_the_window(session_factory, monkeypatch):
    monkeypatch.setattr(config, "BENCHMARK_SCAN_LIMIT", 1)
    with session_factory() as s:
        old_m, old_t = make_bundle("EUN1_old", cs_at_10=10)
        old_m["info"]["gameCreation"] = 1_000
        store.insert_match_bundle(s, old_m, old_t, region="europe")
        new_m, new_t = make_bundle("EUN1_new", cs_at_10=90)
        new_m["info"]["gameCreation"] = 2_000
        store.insert_match_bundle(s, new_m, new_t, region="europe")
        computed = aggregate.compute_role_benchmarks(s)
    # only the newest match is inside the window: 2 laners per role, cs10=90
    assert computed[("TOP", "ALL")]["samples"] == 2
    assert computed[("TOP", "ALL")]["cs10"] == 90


def test_index_create_race_is_survivable(session_factory):
    # Two containers race init_db at deploy: the loser's duplicate CREATE
    # INDEX must be swallowed, anything else must still raise.
    from app import db
    from app.models import Base

    with session_factory() as s:
        engine = s.get_bind()
    index = next(iter(Base.metadata.tables["match_participants"].indexes))
    db._create_index_idempotent(index, engine)  # exists (create_all) → no-op
