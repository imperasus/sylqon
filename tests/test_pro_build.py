"""Offline tests for pro/esports build ingest + read.

In-memory SQLite; verifies upsert-by-(champion, role, pro) and the serialized
read shape. No network.

Run: python -m pytest tests/test_pro_build.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from sylqon.db.schema import Base, Champion
from sylqon.mcp import ingest


def _session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True, expire_on_commit=False)()
    s.add(Champion(name="Ahri", riot_key=103, slug="Ahri", roles=["middle"]))
    s.commit()
    return s


def _build(items):
    return {"items": items, "skill_order": ["Q", "W", "E"], "spell1": "Flash",
            "spell2": "Ignite", "keystone": "Electrocute"}


def test_ingest_and_read():
    s = _session()
    res = ingest.ingest_pro_build(s, "Ahri", "mid", "Faker",
                                  _build([{"id": 1, "name": "Luden"}]),
                                  team="T1", region="LCK", patch="14.10")
    assert res["ok"] is True
    assert res["role"] == "middle"  # normalized from "mid"
    s.commit()

    out = ingest.pro_builds_for(s, "Ahri")
    assert len(out) == 1
    assert out[0]["pro_name"] == "Faker"
    assert out[0]["team"] == "T1"
    assert out[0]["build"]["skill_order"] == ["Q", "W", "E"]


def test_upsert_replaces_same_pro():
    s = _session()
    ingest.ingest_pro_build(s, "Ahri", "middle", "Faker", _build([{"id": 1, "name": "A"}]))
    ingest.ingest_pro_build(s, "Ahri", "middle", "Faker", _build([{"id": 2, "name": "B"}]))
    s.commit()
    out = ingest.pro_builds_for(s, "Ahri", "middle")
    assert len(out) == 1                       # same pro/role → updated, not duplicated
    assert out[0]["build"]["items"][0]["name"] == "B"


def test_two_pros_coexist_and_role_filter():
    s = _session()
    ingest.ingest_pro_build(s, "Ahri", "middle", "Faker", _build([]))
    ingest.ingest_pro_build(s, "Ahri", "middle", "Chovy", _build([]))
    s.commit()
    assert len(ingest.pro_builds_for(s, "Ahri", "middle")) == 2
    assert ingest.pro_builds_for(s, "Ahri", "top") == []   # role with no pro builds


def test_unknown_champion_errors():
    s = _session()
    res = ingest.ingest_pro_build(s, "Nope", "mid", "Faker", _build([]))
    assert "error" in res
