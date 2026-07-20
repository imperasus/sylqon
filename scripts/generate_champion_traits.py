"""Generate full-roster champion trait coverage from the Data Dragon
``championFull.json`` (the rich per-ability data the summary catalog omits), so
the hand-curated threat tables in ``data/static.py`` no longer silently leave
most of the roster as a "neutral blob".

We ONLY generate the traits that DDragon can identify **deterministically**,
mirroring the discipline of ``generate_item_tags.py`` (which generates only the
stat-level resist tags and leaves effect-level tags to the hand table):

    damage_type    ← info.attack vs info.magic (per-champion, whole roster)
    heavy_cc       ← a hard-CC keyword (stun/root/taunt/charm/fear/knock/…)
                     appears in an ability description
    suppression    ← the word "suppress" appears (a rare, unambiguous term)
    heavy_healing  ← a self/ally heal-for-health keyword appears
    tank           ← Tank class tag, or a high DDragon defense score

Effect-level judgment calls that a keyword scan cannot make reliably —
``burst_ad`` / ``burst_ap`` (what counts as lethal burst) and ``poke`` (siege
range pressure) — are LEFT to the curated hand tables. The runtime UNIONS the
generated members into the curated sets (see ``static._merge_champion_traits``),
so generation only ever ADDS coverage and the curated tables always win.

Re-run after a patch bump (same cadence as the catalog fixture / item tags):

    python scripts/generate_champion_traits.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DDRAGON = "https://ddragon.leagueoflegends.com"

# Hard-CC vocabulary. These are effects a QSS/Cleanse or a durability item is
# bought against — deliberately EXCLUDES slows (a slow alone is not "heavy CC").
# Word-boundary matched against ability descriptions.
_HARD_CC = (
    r"stun", r"stuns", r"stunn\w+",
    r"root", r"roots", r"rooted", r"snare", r"snares", r"immobiliz\w+",
    r"taunt", r"taunts", r"taunted",
    r"charm", r"charms", r"charmed",
    r"fear", r"fears", r"feared", r"terrify\w*", r"flee",
    r"knock\s?up", r"knock\s?back", r"knock\s?aside", r"knocks?\s\w+\sup",
    r"airborne", r"knocked\s+\w+",
    r"suppress\w*", r"sleep", r"drowsy", r"polymorph\w*",
)
_HARD_CC_RE = re.compile(r"\b(" + "|".join(_HARD_CC) + r")\b", re.IGNORECASE)
_SUPPRESS_RE = re.compile(r"\bsuppress\w*\b", re.IGNORECASE)
# Self/ally healing: a heal-for-health effect (not lifesteal-only flavour text).
_HEAL_RE = re.compile(
    r"\b(heals?|healing|restor\w*\s+(health|hp)|life\s?steal|omnivamp|"
    r"spell\s?vamp|drain\w*\s+(health|hp))\b", re.IGNORECASE)

# A slow is common and would make almost every champion "CC"; we require a hard
# effect. But a lone knock-back on a poke mage (e.g. a self-peel) shouldn't tag
# them either — so hard-CC must appear on a NON-movement, offensive ability. We
# approximate that by scanning all non-passive spell descriptions and requiring
# at least one hard-CC hit; false positives are further filtered by the curated
# table always taking precedence and by the size-bound test.


def _abilities(champ: dict) -> list[str]:
    """Concatenated descriptions of every castable spell (Q/W/E/R), passive
    excluded — passives rarely define the champion's CC threat and add noise."""
    return [s.get("description", "") or "" for s in champ.get("spells", [])]


def _has_hard_cc(champ: dict) -> bool:
    return any(_HARD_CC_RE.search(text) for text in _abilities(champ))


def _has_suppression(champ: dict) -> bool:
    return any(_SUPPRESS_RE.search(text) for text in _abilities(champ))


def _has_healing(champ: dict) -> bool:
    # Require the heal keyword on at least one ability AND that the champion is
    # not a pure marksman (their lifesteal is itemised, not kit sustain).
    tags = set(champ.get("tags", []))
    if tags == {"Marksman"}:
        return False
    return any(_HEAL_RE.search(text) for text in _abilities(champ))


def _is_tank(champ: dict) -> bool:
    tags = set(champ.get("tags", []))
    defense = champ.get("info", {}).get("defense", 0)
    return "Tank" in tags or defense >= 8


def _damage_type(champ: dict) -> str:
    info = champ.get("info", {})
    attack, magic = info.get("attack", 0), info.get("magic", 0)
    tags = set(champ.get("tags", []))
    # Clear separations first; fall back to "mixed" for genuine hybrids/tanks
    # whose counter items are universal anyway (matches static.py's convention).
    if "Marksman" in tags:
        return "ad"
    if attack >= magic + 3:
        return "ad"
    if magic >= attack + 3:
        return "ap"
    if "Mage" in tags:
        return "ap"
    if "Fighter" in tags or "Assassin" in tags:
        return "ad" if attack >= magic else "mixed"
    return "mixed"


def main() -> int:
    patch = requests.get(f"{DDRAGON}/api/versions.json", timeout=15).json()[0]
    full = requests.get(
        f"{DDRAGON}/cdn/{patch}/data/en_US/championFull.json", timeout=60
    ).json()["data"]

    damage_type: dict[str, str] = {}
    threats: dict[str, list[str]] = {}
    for champ in full.values():
        name = champ["name"]
        damage_type[name] = _damage_type(champ)
        t: list[str] = []
        if _has_hard_cc(champ):
            t.append("heavy_cc")
        if _has_suppression(champ):
            t.append("suppression")
        if _has_healing(champ):
            t.append("heavy_healing")
        if _is_tank(champ):
            t.append("tank")
        if t:
            threats[name] = t

    out = {
        "_patch": patch,
        "_source": "championFull.json (deterministic keyword/info derivation)",
        "damage_type": {k: damage_type[k] for k in sorted(damage_type)},
        "threats": {k: threats[k] for k in sorted(threats)},
    }
    dest = ROOT / "sylqon" / "data" / "generated_champion_traits.json"
    dest.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")

    # Console summary so the operator can eyeball coverage before committing.
    cc = sum(1 for v in threats.values() if "heavy_cc" in v)
    sup = sum(1 for v in threats.values() if "suppression" in v)
    heal = sum(1 for v in threats.values() if "heavy_healing" in v)
    tank = sum(1 for v in threats.values() if "tank" in v)
    print(f"Wrote {dest} (patch {patch})")
    print(f"  roster: {len(damage_type)} champions")
    print(f"  damage_type: ad={sum(1 for x in damage_type.values() if x=='ad')} "
          f"ap={sum(1 for x in damage_type.values() if x=='ap')} "
          f"mixed={sum(1 for x in damage_type.values() if x=='mixed')}")
    print(f"  threats: heavy_cc={cc} suppression={sup} "
          f"heavy_healing={heal} tank={tank}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
