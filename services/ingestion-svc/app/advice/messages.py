"""HU/EN template texts for each finding type — 2–3 short, actionable sentences.

Template-based on purpose (no LLM): deterministic, offline-testable, and the
roadmap's sprint order ships templates first, LLM phrasing later. Placeholders
are filled from the finding's evidence dict.
"""
from __future__ import annotations

from app.advice.heuristics import Finding

_TEMPLATES: dict[str, dict[str, str]] = {
    "death_outnumbered": {
        "hu": (
            "A(z) {champion} meccseden a halálaid nagy része ({dominant_count}/{total_deaths}) "
            "létszámhátrányos helyzetben történt. Mielőtt belemész egy harcba, számold meg, "
            "hány ellenfél látszik a térképen — ha kettőnél több hiányzik, húzódj vissza. "
            "Egyetlen elkerült halál is átfordíthat egy lane-t."
        ),
        "en": (
            "Most of your deaths on {champion} ({dominant_count}/{total_deaths}) happened while "
            "outnumbered. Before committing to a fight, count the missing enemies on the map — "
            "if more than two are unaccounted for, back off. One avoided death can flip a lane."
        ),
    },
    "death_no_vision": {
        "hu": (
            "A halálaid többsége ({dominant_count}/{total_deaths}) úgy történt, hogy a csapatodnak "
            "nem volt friss wardja. Halál előtt jellemzően percek óta nem raktatok le víziót. "
            "Vegyél control wardot minden bázislátogatásnál, és wardolj, mielőtt előretolod a wave-et."
        ),
        "en": (
            "Most of your deaths ({dominant_count}/{total_deaths}) came without fresh team vision — "
            "typically minutes had passed since the last ward. Buy a control ward every base trip, "
            "and ward before pushing the wave forward."
        ),
    },
    "death_objective_trade": {
        "hu": (
            "Sokszor haltál meg ({dominant_count}/{total_deaths}) objective-harcok környékén. "
            "Ha a csapat drake-et vagy Heraldot csinál, ne külön vonalon halj meg — vagy érj oda "
            "időben, vagy nyomj másik oldalt, de félúton sose ragadj."
        ),
        "en": (
            "You died repeatedly ({dominant_count}/{total_deaths}) around objective fights. When "
            "your team plays for drake or Herald, don't die in a side lane — either arrive on time "
            "or push the opposite side, but never get caught in between."
        ),
    },
    "cs_low": {
        "hu": (
            "A CS-ed elmaradt a szintedtől: {deficit_pct}%-kal a benchmark alatt farmoltál "
            "(10. percben {cs10}, cél: {bench10}). Két-három extra minion percenként több aranyat ad, "
            "mint egy kill — a következő meccsen csak a last hitre figyelj az első 10 percben."
        ),
        "en": (
            "Your CS fell behind: {deficit_pct}% under the benchmark ({cs10} at 10 min, target "
            "{bench10}). Two-three extra minions per minute out-earn a kill — next game, make "
            "last-hitting your only focus for the first 10 minutes."
        ),
    },
    "item_slow": {
        "hu": (
            "Az itemjeid lassan készültek el — az első core itemed a {first_core_min}. percben jött "
            "össze (cél: {bench_first}.). Költsd el az aranyat minden visszatérésnél: egy fél-kész "
            "item a boltban nulla sebzés a pályán."
        ),
        "en": (
            "Your items came online late — the first core item completed at minute {first_core_min} "
            "(target: {bench_first}). Spend your gold on every recall: a half-finished item sitting "
            "in the shop deals zero damage on the map."
        ),
    },
    "vision_low": {
        "hu": (
            "Kevés víziót adtál a csapatnak: {wards_per_min} ward/perc (cél: {bench_wards_per_min}) "
            "és {control_wards} control ward (cél: {bench_control_wards}). A ward a legolcsóbb "
            "'item' a játékban — rakd le a trinketet minden cooldownon, és vegyél control wardot "
            "bázisnál."
        ),
        "en": (
            "You gave your team too little vision: {wards_per_min} wards/min (target "
            "{bench_wards_per_min}) and {control_wards} control wards (target {bench_control_wards}). "
            "Wards are the cheapest item in the game — use your trinket on cooldown and buy a "
            "control ward each base."
        ),
    },
    "objective_absent": {
        "hu": (
            "A csapatod {team_objectives} nagy objective-et szerzett, de te csak {attended}-nél "
            "voltál ott ({ratio_pct}%). A drake- és Herald-harcok döntik el a meccset — indulj el "
            "már a spawn előtt 30 másodperccel, ne az utolsó pillanatban."
        ),
        "en": (
            "Your team took {team_objectives} major objectives but you were only present for "
            "{attended} ({ratio_pct}%). Drake and Herald fights decide games — start rotating 30 "
            "seconds before the spawn, not at the last moment."
        ),
    },
    "clean_game": {
        "hu": (
            "Ezen a meccsen egyik fő mutatód sem lógott ki negatívan — a halálaid, a farmod, a "
            "víziód és az objective-jelenléted is rendben volt. Ilyenkor a következő lépés a "
            "konzisztencia: játszd ugyanígy a következő ötöt."
        ),
        "en": (
            "No major metric stood out negatively this game — deaths, farm, vision and objective "
            "presence were all in order. The next step is consistency: play the next five games "
            "exactly like this."
        ),
    },
}


def render(finding: Finding | None, lang: str, champion: str) -> str:
    key = finding.message_key if finding else "clean_game"
    template = _TEMPLATES.get(key, _TEMPLATES["clean_game"])[lang]
    values = {"champion": champion}
    if finding:
        values.update(finding.evidence)
    try:
        return template.format(**values)
    except (KeyError, IndexError):
        # evidence lacked a placeholder (e.g. short game) → clean fallback
        return _TEMPLATES["clean_game"][lang]
