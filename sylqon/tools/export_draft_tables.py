"""Export the draft-intel data bundle + parity fixtures for ingestion-svc.

The hosted service (``services/ingestion-svc``) must not import ``sylqon``, so
the web port of the draft engine (``app/draftintel.py``) reads a generated
JSON bundle instead of ``sylqon.data.static`` + the Data Dragon catalog. This
tool derives that bundle the exact same way the live champ-select path does
(``lcu.lobby._profile``): DDragon class tags + attack/magic -> damage_type,
and the seven ``static`` name-sets -> threat flags.

It also generates the cross-suite parity fixture: a set of draft inputs with
the *sylqon-side* engine's outputs recorded as ground truth. The sylqon test
suite re-runs the engine against the fixture (catches engine changes without a
bundle regen); the service test suite runs the ported engine against the same
fixture (catches port drift). Both green => engine == port on these inputs.

Run from the repo root (regenerate on patch bumps and on any change to
``analysis/draft_intel.py``, ``lcu/lobby.py`` summaries or the ``static``
threat tables)::

    python -m sylqon.tools.export_draft_tables

Requires a populated Data Dragon catalog cache (``cache/ddragon_catalog.json``
or ``SYLQON_CACHE_DIR``).
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from sylqon import config
from sylqon.analysis.draft_intel import classify_comp, counter_pick_advice, draft_balance
from sylqon.data import static
from sylqon.lcu.lobby import _damage_type, _threats, summarize_team

BUNDLE_VERSION = 1
_SERVICE_DIR = config.PROJECT_ROOT / "services" / "ingestion-svc"
BUNDLE_PATH = _SERVICE_DIR / "app" / "data" / "draft_tables.json"
FIXTURE_PATH = _SERVICE_DIR / "tests" / "fixtures" / "draft_parity.json"

# -- fixture case definitions --------------------------------------------------
# Champion names must exist in the catalog; the generator raises on a typo.
# Chosen to exercise every archetype branch, partial drafts and tie-breaks.
COMP_CASES = [
    ("engage_vs_poke",
     ["Amumu", "Sejuani", "Alistar", "Miss Fortune", "Yasuo"],
     ["Xerath", "Ziggs", "Jayce", "Caitlyn", "Karma"], None),
    ("pick_vs_protect",
     ["Zed", "LeBlanc", "Rengar", "Pyke", "Ahri"],
     ["Soraka", "Braum", "Kog'Maw", "Orianna", "Shen"], None),
    ("split_vs_teamfight",
     ["Fiora", "Jax", "Tryndamere", "Sivir", "Lulu"],
     ["Shen", "Dr. Mundo", "Jinx", "Ashe", "Orianna"], None),
    ("suppression_engage",
     ["Malzahar", "Warwick", "Urgot", "Leona", "Nautilus"],
     ["Vel'Koz", "Lux", "Ezreal", "Varus", "Thresh"], None),
    ("mirror_engage",
     ["Amumu", "Leona", "Ornn", "Jinx", "Annie"],
     ["Zac", "Nautilus", "Sion", "Ashe", "Veigar"], None),
    ("balanced_two_picks", ["Garen", "Orianna"], ["Ezreal", "Thresh"], None),
    ("unknown_single", ["Aatrox"], [], None),
    ("partial_three",
     ["Zed", "Talon", "Qiyana"], ["Maokai", "Braum"], None),
    ("lane_adv_positive",
     ["Fiora", "Jax", "Tryndamere", "Sivir", "Lulu"],
     ["Xerath", "Ziggs", "Jayce", "Caitlyn", "Karma"], 4.0),
    ("lane_adv_negative",
     ["Amumu", "Sejuani", "Alistar", "Miss Fortune", "Yasuo"],
     ["Zed", "LeBlanc", "Rengar", "Pyke", "Ahri"], -6.5),
    ("lane_adv_below_threshold",
     ["Malzahar", "Warwick", "Urgot", "Leona", "Nautilus"],
     ["Soraka", "Braum", "Kog'Maw", "Orianna", "Shen"], 1.0),
    # draft_balance branch coverage: enemy mono-damage + frontline edge…
    ("frontline_vs_mono_ap",
     ["Ornn", "Ahri", "Jinx", "Thresh", "Vi"],
     ["Xerath", "Ziggs", "Lux", "Vel'Koz", "Zoe"], None),
    # …and the ally-side mono-damage penalty.
    ("mono_ad_ally",
     ["Zed", "Talon", "Draven", "Caitlyn", "Pyke"],
     ["Malphite", "Orianna", "Jinx", "Leona", "Riven"], None),
]

# ctx dict shape consumed by the ported counter_pick_advice; the generator maps
# it onto the attribute-shaped MatchContext the sylqon engine expects.
COUNTER_CASES = [
    ("locked", {"locked": True, "my_turn": False,
                "enemies_revealed": 5, "enemy_picks_after_me": 0}),
    ("waiting", {"locked": False, "my_turn": False,
                 "enemies_revealed": 3, "enemy_picks_after_me": 2}),
    ("counter_window", {"locked": False, "my_turn": True,
                        "enemies_revealed": 5, "enemy_picks_after_me": 0}),
    ("blind_spot", {"locked": False, "my_turn": True,
                    "enemies_revealed": 2, "enemy_picks_after_me": 2}),
]


def build_bundle(catalog_champions: dict, patch: str) -> dict:
    """Derive the per-champion draft profiles + the name-sets the classifier
    reads directly. ``catalog_champions`` is the ``champions`` mapping of
    ``ddragon_catalog.json`` (key -> {name, id, tags, attack, magic})."""
    champions = {}
    for key, info in sorted(catalog_champions.items(), key=lambda kv: int(kv[0])):
        name = info["name"]
        champions[key] = {
            "name": name,
            "slug": info.get("id", ""),
            "tags": list(info.get("tags", [])),
            "damage_type": _damage_type(info),
            "threats": _threats(name),
        }
    return {
        "bundle_version": BUNDLE_VERSION,
        "patch": patch,
        "champions": champions,
        "heavy_poke": sorted(static.HEAVY_POKE),
        "split_push": sorted(static.SPLIT_PUSH_CHAMPS),
    }


def _pick_from_bundle(bundle: dict, name: str) -> dict:
    """The synthesised pick shape both engines consume. Raises on typos so a
    bad fixture never silently records wrong ground truth."""
    for prof in bundle["champions"].values():
        if prof["name"] == name:
            return {"name": prof["name"], "tags": list(prof["tags"]),
                    "threats": list(prof["threats"]),
                    "damage_type": prof["damage_type"]}
    raise KeyError(f"champion not in catalog: {name!r}")


def _ctx_namespace(ctx: dict) -> SimpleNamespace:
    """Map the dict ctx shape onto the attribute shape counter_pick_advice
    expects (5 enemies, the first N locked — only the locked count matters)."""
    enemies = [SimpleNamespace(locked=i < ctx["enemies_revealed"]) for i in range(5)]
    return SimpleNamespace(locked=ctx["locked"], my_turn=ctx["my_turn"],
                           enemies=enemies,
                           enemy_picks_after_me=ctx["enemy_picks_after_me"])


def run_comp_case(bundle: dict, ally: list[str], enemy: list[str],
                  lane_advantage: float | None) -> dict:
    """Ground-truth outputs of the sylqon engine for one fixture case."""
    ally_picks = [_pick_from_bundle(bundle, n) for n in ally]
    enemy_picks = [_pick_from_bundle(bundle, n) for n in enemy]
    ally_comp = classify_comp(ally_picks)
    enemy_comp = classify_comp(enemy_picks)
    ally_summary = summarize_team(ally_picks)
    enemy_summary = summarize_team(enemy_picks)
    balance = draft_balance(ally_comp, enemy_comp, ally_summary, enemy_summary,
                            lane_advantage=lane_advantage)
    return {"ally_comp": ally_comp, "enemy_comp": enemy_comp,
            "ally_summary": ally_summary, "enemy_summary": enemy_summary,
            "balance": balance}


def build_fixture(bundle: dict) -> dict:
    comp_cases = [
        {"id": case_id, "ally": ally, "enemy": enemy,
         "lane_advantage": lane_advantage,
         "expected": run_comp_case(bundle, ally, enemy, lane_advantage)}
        for case_id, ally, enemy, lane_advantage in COMP_CASES
    ]
    counter_cases = [
        {"id": case_id, "ctx": ctx,
         "expected": counter_pick_advice(_ctx_namespace(ctx))}
        for case_id, ctx in COUNTER_CASES
    ]
    return {
        "generated_by": "python -m sylqon.tools.export_draft_tables",
        "bundle_version": bundle["bundle_version"],
        "patch": bundle["patch"],
        "comp_cases": comp_cases,
        "counter_cases": counter_cases,
    }


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n",
                    encoding="utf-8")


def main() -> None:
    raw = json.loads(config.CATALOG_CACHE_PATH.read_text(encoding="utf-8"))
    champions = raw.get("champions") or {}
    if not champions:
        raise SystemExit(
            f"empty catalog at {config.CATALOG_CACHE_PATH} — run the app once "
            "or point SYLQON_CACHE_DIR at a populated cache dir")
    bundle = build_bundle(champions, raw.get("patch", "unknown"))
    fixture = build_fixture(bundle)
    _write(BUNDLE_PATH, bundle)
    _write(FIXTURE_PATH, fixture)
    print(f"wrote {BUNDLE_PATH} ({len(bundle['champions'])} champions, "
          f"patch {bundle['patch']})")
    print(f"wrote {FIXTURE_PATH} ({len(fixture['comp_cases'])} comp cases, "
          f"{len(fixture['counter_cases'])} counter cases)")


if __name__ == "__main__":
    main()
