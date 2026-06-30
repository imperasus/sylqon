"""Offline tests for the dashboard settings store + endpoints layer.

Fully offline: no network, no LCU, no Ollama. The ``isolated_settings`` fixture
swaps ``config.USER_SETTINGS`` for a throwaway tmp-backed store and restores every
config constant the spec can mutate, so these tests never touch the real
cache/user_settings.json and never leak state into other tests.
"""
from __future__ import annotations

import pytest

from sylqon import config
from sylqon.settings import MISSION_TYPE_IDS, SETTINGS_SPEC, UserSettings


@pytest.fixture
def isolated_settings(tmp_path):
    saved_store = config.USER_SETTINGS
    saved_attrs = {spec["attr"]: getattr(config, spec["attr"]) for spec in SETTINGS_SPEC.values()}
    config.USER_SETTINGS = UserSettings(tmp_path / "user_settings.json")
    try:
        yield config
    finally:
        config.USER_SETTINGS = saved_store
        for attr, val in saved_attrs.items():
            setattr(config, attr, val)


# --- the JSON store ---------------------------------------------------------

def test_user_settings_round_trip(tmp_path):
    path = tmp_path / "s.json"
    store = UserSettings(path)
    assert store.all() == {}
    store.update({"a": 1, "b": "x"})
    assert store.get("a") == 1
    assert store.get("missing", "fallback") == "fallback"
    # persisted to disk: a fresh instance reads the same data back
    assert UserSettings(path).all() == {"a": 1, "b": "x"}


def test_user_settings_corrupt_file_is_ignored(tmp_path):
    path = tmp_path / "s.json"
    path.write_text("{ not json", encoding="utf-8")
    assert UserSettings(path).all() == {}  # degrades to empty, never raises


# --- settings_payload -------------------------------------------------------

def test_payload_shape_and_groups(isolated_settings):
    payload = isolated_settings.settings_payload()
    assert set(payload) == set(SETTINGS_SPEC)
    assert {v["group"] for v in payload.values()} == {"region", "riot", "ai", "overlay"}
    # every entry carries the metadata the dashboard renders from
    for entry in payload.values():
        assert {"value", "type", "group", "applies", "secret"} <= set(entry)


def test_payload_masks_secret(isolated_settings):
    cfg = isolated_settings
    cfg.RIOT_API_KEY = "RGAPI-secret"
    p = cfg.settings_payload()
    assert p["riot_api_key"]["secret"] is True
    assert p["riot_api_key"]["value"] is True  # masked to set/unset, never the key
    cfg.RIOT_API_KEY = ""
    assert cfg.settings_payload()["riot_api_key"]["value"] is False


# --- update_settings --------------------------------------------------------

def test_update_unknown_key_ignored(isolated_settings):
    cfg = isolated_settings
    cfg.update_settings({"definitely_not_a_setting": 1, "opgg_region": "kr"})
    assert cfg.OPGG_REGION == "kr"
    assert "definitely_not_a_setting" not in cfg.USER_SETTINGS.all()


def test_update_applies_live_and_persists(isolated_settings):
    cfg = isolated_settings
    cfg.update_settings({"opgg_region": "euw", "open_build_mode": "true", "cache_ttl_seconds": "100"})
    assert cfg.OPGG_REGION == "euw"
    assert cfg.OPEN_BUILD_MODE is True
    assert cfg.CACHE_TTL_SECONDS == 100
    # persisted in the store too
    assert cfg.USER_SETTINGS.all()["cache_ttl_seconds"] == 100


@pytest.mark.parametrize("truthy", [True, "true", "1", "yes", "on"])
def test_bool_coercion_true(isolated_settings, truthy):
    isolated_settings.update_settings({"auto_full_sync": truthy})
    assert isolated_settings.AUTO_FULL_SYNC is True


@pytest.mark.parametrize("falsy", [False, "false", "0", "no", "off"])
def test_bool_coercion_false(isolated_settings, falsy):
    isolated_settings.update_settings({"auto_full_sync": falsy})
    assert isolated_settings.AUTO_FULL_SYNC is False


def test_uncoercible_value_ignored(isolated_settings):
    cfg = isolated_settings
    cfg.RIOT_MATCH_COUNT = 20
    cfg.update_settings({"riot_match_count": "not-a-number"})
    assert cfg.RIOT_MATCH_COUNT == 20  # left unchanged, never raises


def test_secret_blank_leaves_credential_unchanged(isolated_settings):
    cfg = isolated_settings
    cfg.update_settings({"riot_api_key": "RGAPI-abc"})
    assert cfg.RIOT_API_KEY == "RGAPI-abc"
    cfg.update_settings({"riot_api_key": ""})  # blank submit must not wipe it
    assert cfg.RIOT_API_KEY == "RGAPI-abc"


def test_mission_types_filtered_and_applied(isolated_settings):
    cfg = isolated_settings
    cfg.update_settings({"mission_types_enabled": ["warding", "bogus_type", "farm_cs_delta"]})
    # unknown id dropped, persisted as a sorted JSON list
    assert cfg.USER_SETTINGS.all()["mission_types_enabled"] == ["farm_cs_delta", "warding"]
    # applied as a set on the config constant the engine reads
    assert cfg.MISSION_TYPES_ENABLED == {"farm_cs_delta", "warding"}


def test_mission_types_empty_means_all(isolated_settings):
    cfg = isolated_settings
    cfg.update_settings({"mission_types_enabled": []})
    assert cfg.MISSION_TYPES_ENABLED is None  # None = every mission type enabled


def test_persisted_overlay_applies_on_apply(tmp_path):
    saved_store = config.USER_SETTINGS
    saved_region = config.OPGG_REGION
    try:
        store = UserSettings(tmp_path / "s.json")
        store.update({"opgg_region": "kr"})
        config.USER_SETTINGS = store
        config.apply_settings()
        assert config.OPGG_REGION == "kr"
    finally:
        config.USER_SETTINGS = saved_store
        config.OPGG_REGION = saved_region


# --- guardrail: the hardcoded mission-id mirror must track missions.py ------

def test_mission_type_ids_stay_in_sync():
    from sylqon.livegame import missions
    actual = {
        missions.NO_DEATH, missions.FARM_CS_DELTA, missions.CS_PER_MIN,
        missions.OBJECTIVE, missions.WARDING, missions.ROAM_ASSIST, missions.GANK_ASSIST,
    }
    assert MISSION_TYPE_IDS == actual
