"""Draft Lab tests: the analyze/rank core, the permalink codec and the routes."""
from __future__ import annotations

import pytest
from app import db, draftlab, store
from app.models import Base
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from tests.test_pool import ME, lane_match

ENGAGE = ["Amumu", "Sejuani", "Alistar", "Miss Fortune", "Yasuo"]
POKE = ["Xerath", "Ziggs", "Jayce", "Caitlyn", "Karma"]


# -- core ----------------------------------------------------------------------
def test_analyze_empty_board():
    result = draftlab.analyze([], [])
    assert result["ally_comp"]["archetype"] == "unknown"
    assert result["balance"]["win_pct"] == 50
    assert result["hidden_enemies"] == 5
    assert result["ally"] == [] and result["enemy"] == []


def test_analyze_full_board_reads_the_clash():
    result = draftlab.analyze(ENGAGE, POKE)
    assert result["ally_comp"]["archetype"] == "hard_engage"
    assert result["enemy_comp"]["archetype"] == "poke_siege"
    assert 35 <= result["balance"]["win_pct"] <= 65
    assert result["balance"]["win_pct"] > 50  # engage is favoured into poke
    assert result["hidden_enemies"] == 0
    assert result["ally_chips"]["frontline"] >= 2
    assert result["enemy_chips"]["ap"] >= 3


def test_analyze_drops_unknown_and_partial_names():
    result = draftlab.analyze(["Amumu", "Notachamp", "Xer"], [])
    assert [c["name"] for c in result["ally"]] == ["Amumu"]


def test_clean_names_guards():
    assert draftlab.clean_names(None) == []
    assert draftlab.clean_names("Amumu") == []
    assert draftlab.clean_names(["a", 1, "b", "c", "d", "e", "f"]) == \
        ["a", "b", "c", "d", "e"]  # non-strings dropped, capped at SLOTS


def test_rank_pool_orders_options_and_skips_board():
    ranking = draftlab.rank_pool(["Malphite", "Zed", "Amumu", "Notachamp"],
                                 ENGAGE[:4], POKE)
    names = [r["name"] for r in ranking]
    assert "Amumu" not in names  # already on the board
    assert "Notachamp" not in names
    assert set(names) == {"Malphite", "Zed"}
    assert [r["win_pct"] for r in ranking] == \
        sorted((r["win_pct"] for r in ranking), reverse=True)
    assert all(35 <= r["win_pct"] <= 65 for r in ranking)


# -- permalink codec --------------------------------------------------------------
def test_state_roundtrip():
    code = draftlab.encode_state(["Amumu", "DrMundo"], ["Xerath"])
    ally, enemy = draftlab.decode_state(code)
    assert ally == ["Amumu", "Dr. Mundo"] and enemy == ["Xerath"]


def test_encode_pads_and_zeroes_unknowns():
    code = draftlab.encode_state(["Amumu", "Notachamp"], [])
    ally_part, enemy_part = code.split("-")
    assert len(ally_part.split(".")) == 5 and len(enemy_part.split(".")) == 5
    assert ally_part.split(".")[1] == "0"  # unknown name encodes as empty
    assert enemy_part == "0.0.0.0.0"


@pytest.mark.parametrize("bad", ["", "garbage", "1.2.3-4.5", "1.2.3.4.5-6.7.8.9",
                                 "a.b.c.d.e-1.2.3.4.5", "1.2.3.4.5-1.2.3.4.5-x"])
def test_decode_rejects_malformed(bad):
    assert draftlab.decode_state(bad) is None


def test_decode_skips_unknown_ids():
    ally, enemy = draftlab.decode_state("32.999999.0.0.0-0.0.0.0.0")
    assert ally == ["Amumu"] and enemy == []


# -- routes ---------------------------------------------------------------------
@pytest.fixture()
def client(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db, "_engine", engine)
    monkeypatch.setattr(db, "_session_factory", factory)
    with factory() as s:
        for i in range(3):
            store.insert_match_bundle(
                s, lane_match(f"EUN1_{i}", "Jinx", "Caitlyn", True, a_puuid=ME),
                {"info": {}}, region="europe")
    from app.main import app
    return TestClient(app, raise_server_exceptions=True)


def test_draft_page_renders_board(client):
    r = client.get("/draft")
    assert r.status_code == 200
    assert r.text.count('class="lab-pick"') == 10
    assert 'datalist id="champ-list"' in r.text
    assert "var CHAMPS=" in r.text and '"Amumu"' in r.text
    assert "talks back" in r.text
    assert 'href="/draft"' in client.get("/").text  # nav links the lab


def test_draft_page_prefills_from_permalink(client):
    code = draftlab.encode_state(["Amumu"], ["Xerath"])
    r = client.get("/draft", params={"d": code})
    assert 'value="Amumu"' in r.text and 'value="Xerath"' in r.text


def test_panel_fragment_updates_live(client):
    r = client.post("/draft/panel", json={"ally": ENGAGE, "enemy": POKE, "pool": ["Malphite"]})
    assert r.status_code == 200
    assert "Hard Engage / Dive" in r.text and "Poke / Siege" in r.text
    assert "Draft balance" in r.text
    assert "a read, not a prediction" in r.text
    assert "Your pool, ranked" in r.text and "Malphite" in r.text


def test_panel_fragment_empty_state(client):
    r = client.post("/draft/panel", json={"ally": [], "enemy": []})
    assert "engine starts reading" in r.text


def test_shared_draft_page(client):
    code = draftlab.encode_state(ENGAGE, POKE)
    r = client.get(f"/d/{code}")
    assert r.status_code == 200
    assert "Hard Engage / Dive vs Poke / Siege" in r.text
    assert "Amumu" in r.text and "Xerath" in r.text  # the static board shows the picks
    assert f'href="/draft?d={code}"' in r.text  # fork link
    assert "Not a draft link" in client.get("/d/garbage").text


def test_api_draft_analyze(client):
    r = client.post("/api/draft/analyze",
                    json={"ally": ENGAGE, "enemy": POKE, "pool": ["Malphite", "Zed"]})
    assert r.status_code == 200
    data = r.json()
    assert data["ally_comp"]["archetype"] == "hard_engage"
    assert data["permalink"].startswith("/d/")
    assert [p["name"] for p in data["pool_ranking"]] and \
        all(35 <= p["win_pct"] <= 65 for p in data["pool_ranking"])
    bare = client.post("/api/draft/analyze", json={}).json()
    assert bare["balance"]["win_pct"] == 50 and "pool_ranking" not in bare


def test_api_draft_pool(client, monkeypatch):
    import app.main as main_mod

    class StubRiot:
        def get_account_by_riot_id(self, g, t, region=None):
            return {"puuid": ME} if g == "Me" else None

    class StubIngest:
        _riot = StubRiot()

    monkeypatch.setattr(main_mod, "_ingest_service", StubIngest())
    r = client.get("/api/draft/pool", params={"riot_id": "Me#TAG"})
    assert r.status_code == 200
    assert "Jinx" in r.json()["champions"]
    assert client.get("/api/draft/pool", params={"riot_id": "Ghost#X"}).status_code == 404
    assert client.get("/api/draft/pool", params={"riot_id": "no-tag"}).status_code == 400
