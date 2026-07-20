"""Normalized snapshot of the live game, parsed from the Live Client Data API.

Everything here comes from ``allgamedata`` — information already visible to the
player. ``LiveGameState.none()`` is the explicit "no game running" sentinel.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from functools import lru_cache

from sylqon import config
from sylqon.data import static


# Live Client Data API positions are upper-case (TOP/JUNGLE/MIDDLE/BOTTOM/UTILITY).
def _norm_role(position: str) -> str:
    p = (position or "").lower().strip()
    return static.ROLE_ALIASES.get(p, p)


@dataclass
class LiveGameState:
    active: bool
    game_time: float = 0.0          # seconds since game start
    my_name: str = ""
    champion: str = ""
    level: int = 0
    kills: int = 0
    deaths: int = 0
    assists: int = 0
    cs: int = 0                     # creepScore (lane + jungle minions)
    cs_per_min: float = 0.0
    ward_score: float = 0.0
    role: str = ""                 # normalized top/jungle/middle/bottom/utility
    position: str = ""             # raw live position (may be empty)
    team: str = ""                 # ORDER | CHAOS
    is_dead: bool = False
    respawn_timer: float = 0.0
    objectives: dict = field(default_factory=dict)   # {dragons:{ally,enemy}, ...}
    death_times: list = field(default_factory=list)  # game-time of my deaths
    events: list = field(default_factory=list)       # lightweight event log
    roster: list = field(default_factory=list)       # all 10 players, live stats
    cs_benchmark: dict = field(default_factory=dict) # {target, delta, status}
    level_diff: int = 0                              # my level − enemy avg level
    objective_timers: dict = field(default_factory=dict)  # {dragon, baron} secs to next
    soul: dict = field(default_factory=dict)         # {status, ally, enemy, type} dragon-soul read
    item_spike: dict = field(default_factory=dict)   # {mine, opponent, status} vs lane opp
    current_gold: float = 0.0                        # activePlayer.currentGold (recall math)
    champion_stats: dict = field(default_factory=dict)   # live combat stats (haste, hp%, …)
    abilities: dict = field(default_factory=dict)    # {q,w,e,r,ult_level} skill levels
    map_terrain: str = ""                            # elemental rift type (soul being formed)
    last_death: dict = field(default_factory=dict)   # {killer_champ, assisters, game_time}
    matchup: dict = field(default_factory=dict)      # lane-opponent plan {opponent, playstyle, tempo}

    @classmethod
    def none(cls) -> "LiveGameState":
        return cls(active=False)

    def to_dict(self) -> dict:
        return asdict(self)


def _find_me(active: dict, all_players: list[dict]) -> dict | None:
    """Resolve the active player's row in ``allPlayers`` across the various name
    fields Riot has used (riotIdGameName / summonerName / riotId)."""
    candidates = set()
    for key in ("riotIdGameName", "summonerName", "riotId", "gameName"):
        v = (active.get(key) or "").strip()
        if v:
            candidates.add(v)
            candidates.add(v.split("#")[0])
    candidates.discard("")
    for p in all_players:
        for key in ("riotIdGameName", "summonerName", "riotId", "gameName"):
            v = (p.get(key) or "").strip()
            if v and (v in candidates or v.split("#")[0] in candidates):
                return p
    return None


def _team_map(all_players: list[dict]) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in all_players:
        team = p.get("team") or ""
        for key in ("riotIdGameName", "summonerName", "riotId", "gameName"):
            v = (p.get(key) or "").strip()
            if v:
                out[v] = team
                out[v.split("#")[0]] = team
    return out


def _parse_objectives(events: list[dict], name_to_team: dict[str, str],
                      my_team: str) -> dict:
    obj = {k: {"ally": 0, "enemy": 0} for k in ("dragons", "heralds", "barons", "towers")}
    kind = {"DragonKill": "dragons", "HeraldKill": "heralds", "BaronKill": "barons",
            "TurretKilled": "towers"}
    for e in events:
        key = kind.get(e.get("EventName", ""))
        if not key:
            continue
        if key == "towers":
            # Turret name encodes its OWNER side (T1 = ORDER, T2 = CHAOS). The team
            # that destroyed it is the other side.
            turret = e.get("TurretKilled", "")
            owner = "ORDER" if "_T1_" in turret else ("CHAOS" if "_T2_" in turret else "")
            if owner and my_team:
                obj[key]["ally" if owner != my_team else "enemy"] += 1
            continue
        kteam = name_to_team.get(e.get("KillerName", ""))
        if kteam and my_team:
            obj[key]["ally" if kteam == my_team else "enemy"] += 1
    return obj


def _player_name(p: dict) -> str:
    for key in ("riotIdGameName", "summonerName", "riotId", "gameName"):
        v = (p.get(key) or "").strip()
        if v:
            return v.split("#")[0]
    return ""


# Live Client Data localizes ``displayName`` to the client language, so we resolve
# summoner spells from the locale-independent ``rawDisplayName`` token
# (e.g. "GeneratedTip_SummonerSpell_SummonerFlash_DisplayName") to the canonical
# English name the UI's icon lookup expects. displayName is only a last resort.
_SPELL_RAW = {
    "SummonerFlash": "Flash", "SummonerHeal": "Heal", "SummonerHaste": "Ghost",
    "SummonerBoost": "Cleanse", "SummonerExhaust": "Exhaust",
    "SummonerBarrier": "Barrier", "SummonerDot": "Ignite",
    "SummonerTeleport": "Teleport", "SummonerSmite": "Smite",
    "SummonerMana": "Clarity", "SummonerSnowball": "Snowball",
}


def _spell_from_raw(raw: str) -> str:
    for token, name in _SPELL_RAW.items():
        if token in raw:
            return name
    return ""


def _spell_names(p: dict) -> list[str]:
    """The two summoner spells as canonical English names (e.g. ['Flash','Ignite']),
    resolved locale-independently so non-English clients map to icons correctly."""
    s = p.get("summonerSpells") or {}
    out = []
    for key in ("summonerSpellOne", "summonerSpellTwo"):
        spell = s.get(key) or {}
        name = (_spell_from_raw(spell.get("rawDisplayName") or "")
                or (spell.get("displayName") or "").strip())
        if name:
            out.append(name)
    return out


def _item_ids(p: dict) -> list[int]:
    """Live item IDs in inventory-slot order (Live Client Data ``items``)."""
    items = p.get("items") or []
    out = []
    for it in sorted(items, key=lambda i: i.get("slot", 0)):
        iid = it.get("itemID")
        if iid:
            out.append(int(iid))
    return out


# Gold-threshold fallback for items the catalog doesn't know (e.g. a brand-new
# item not yet in the cached DDragon dump): a completed legendary/mythic costs
# ~2500-3400g, well above boots (~1100) and components (≤1300).
LEGENDARY_PRICE = 2000


@lru_cache(maxsize=1)
def _catalog_item_sets() -> tuple[frozenset[int], frozenset[int]]:
    """``(all_item_ids, completed_non_boots_ids)`` from the local DDragon catalog.
    Both empty when the catalog is absent, so callers fall back to the price
    proxy. Cached — the catalog is static within a run."""
    try:
        data = json.loads(config.CATALOG_CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return frozenset(), frozenset()
    all_ids: set[int] = set()
    completed: set[int] = set()
    for it in (data.get("items") or {}).values():
        iid = it.get("id")
        if not isinstance(iid, int):
            continue
        all_ids.add(iid)
        if it.get("completed") and "Boots" not in (it.get("tags") or []):
            completed.add(iid)
    return frozenset(all_ids), frozenset(completed)


def _completed_count(p: dict) -> int:
    """Number of completed legendary items (boots excluded) a player holds, from
    the on-screen Live Client ``items``. Prefers the DDragon catalog's authoritative
    ``completed`` flag; for an item the catalog doesn't know it falls back to the
    gold-price proxy — so the read never regresses on a stale/missing catalog."""
    all_ids, completed_ids = _catalog_item_sets()
    count = 0
    for it in p.get("items") or []:
        if it.get("consumable"):
            continue
        iid = int(it.get("itemID") or 0)
        if iid in completed_ids:
            count += 1
        elif iid not in all_ids and int(it.get("price") or 0) >= LEGENDARY_PRICE:
            count += 1
    return count


def _rune_name(node: dict, table: dict) -> str:
    """Resolve a rune/style node to its canonical English name by id (locale-
    independent), falling back to the localized displayName if the id is unknown."""
    node = node or {}
    return table.get(node.get("id"), (node.get("displayName") or "").strip())


def _runes(p: dict) -> dict:
    """Keystone + primary/secondary tree names for a player, resolved by id so
    non-English clients still yield canonical English names the UI can map."""
    r = p.get("runes") or {}
    return {
        "keystone": _rune_name(r.get("keystone"), static.RUNE_BY_ID),
        "primary": _rune_name(r.get("primaryRuneTree"), static.STYLE_BY_ID),
        "secondary": _rune_name(r.get("secondaryRuneTree"), static.STYLE_BY_ID),
    }


def _parse_roster(all_players: list[dict], my_team: str) -> list[dict]:
    """All ten players with their LIVE stats, tagged ally/enemy relative to me.
    Everything here is already on-screen in-game (Live Client Data ``allPlayers``)
    — champion, level, K/D/A, CS, items, summoner spells, runes — so it is
    read-only and ToS-safe. Enemy *history* (puuid) is not exposed by Riot, so
    this is the live read, not a fingerprint."""
    out: list[dict] = []
    for p in all_players:
        scores = p.get("scores") or {}
        team = p.get("team") or ""
        out.append({
            "name": _player_name(p),
            "champion": p.get("championName") or "",
            "role": _norm_role(p.get("position") or ""),
            "team": team,
            "side": "ally" if (my_team and team == my_team) else "enemy",
            "kills": int(scores.get("kills") or 0),
            "deaths": int(scores.get("deaths") or 0),
            "assists": int(scores.get("assists") or 0),
            "cs": int(scores.get("creepScore") or 0),
            "ward_score": float(scores.get("wardScore") or 0.0),
            "level": int(p.get("level") or 0),
            "is_dead": bool(p.get("isDead")),
            "respawn_timer": float(p.get("respawnTimer") or 0.0),
            "items": _item_ids(p),
            "completed_items": _completed_count(p),
            "spells": _spell_names(p),
            "runes": _runes(p),
        })
    return out


_ROLE_ORDER = ["top", "jungle", "middle", "bottom", "utility"]


def _infer_roles(roster: list[dict]) -> None:
    """Assign positional-fallback roles to roster entries whose role is empty."""
    for side in ("ally", "enemy"):
        side_players = [p for p in roster if p.get("side") == side]
        taken = {p["role"] for p in side_players if p["role"]}
        available = [r for r in _ROLE_ORDER if r not in taken]
        idx = 0
        for p in side_players:
            if not p["role"]:
                if idx < len(available):
                    p["role"] = available[idx]
                    idx += 1


# Rough CS-per-minute targets by role (lane + jungle camps for JG). Used only as
# a live "are you keeping up" gauge, not a hard rule.
_CS_TARGETS = {"top": 7.5, "jungle": 5.5, "middle": 8.0, "bottom": 8.5, "utility": 1.5}


def _cs_benchmark(role: str, cs_per_min: float) -> dict:
    target = _CS_TARGETS.get(role, 7.0)
    delta = round(cs_per_min - target, 1)
    status = "ahead" if delta >= 0.3 else "behind" if delta <= -0.3 else "on-track"
    return {"target": target, "delta": delta, "status": status}


def _level_diff(roster: list[dict], my_level: int, role: str = "") -> int:
    """My level minus my *lane opponent's* (same role) — the comparison that
    actually matters in lane. Falls back to the enemy-team average only when the
    lane opponent can't be resolved (no role match or no level yet)."""
    if not my_level:
        return 0
    if role:
        opp = next((p for p in roster if p.get("side") == "enemy"
                    and p.get("role") == role and p.get("level")), None)
        if opp:
            return my_level - int(opp["level"])
    enemies = [p["level"] for p in roster if p.get("side") == "enemy" and p.get("level")]
    if not enemies:
        return 0
    return my_level - round(sum(enemies) / len(enemies))


def _objective_timers(events: list[dict], game_time: float) -> dict:
    """Seconds until the next dragon / baron, derived from kill events + the clock.
    Standard timings (dragon 5:00, baron 6:00 respawn; baron first at 20:00) — a
    best-effort estimate from on-screen events, not a server feed. 0 == up now."""
    drag = [e["time"] for e in events if e.get("name") == "DragonKill"]
    baron = [e["time"] for e in events if e.get("name") == "BaronKill"]
    next_dragon = (max(drag) + 300.0) if drag else 300.0
    next_baron = (max(baron) + 360.0) if baron else 1200.0
    return {"dragon": max(0, round(next_dragon - game_time)),
            "baron": max(0, round(next_baron - game_time))}


# ``gameData.mapTerrain`` names the rift's active element; the soul being formed is
# that element. "Default"/"" means no soul element locked in yet (< 2 drakes taken).
_TERRAIN_SOUL = {
    "Infernal": "Infernal", "Mountain": "Mountain", "Ocean": "Ocean",
    "Cloud": "Cloud", "Hextech": "Hextech", "Chemtech": "Chemtech",
}


def _dragon_soul(objectives: dict, terrain: str = "") -> dict:
    """Read the dragon-soul race from the drake counts (already on-screen). A team
    on 3 drakes is at its *soul point* — the next dragon grants the soul; ≥4 means
    the soul is taken (dragons then become Elder). Status is "" when neither team
    is close, so the overlay only nags at the decisive moment. ``type`` names the
    soul element (from the rift terrain) so the coach can say *which* soul is live."""
    d = (objectives or {}).get("dragons") or {}
    ally, enemy = int(d.get("ally") or 0), int(d.get("enemy") or 0)
    if ally >= 4:
        status = "ally_soul"
    elif enemy >= 4:
        status = "enemy_soul"
    elif ally >= 3:
        status = "ally_soul_point"
    elif enemy >= 3:
        status = "enemy_soul_point"
    else:
        status = ""
    return {"status": status, "ally": ally, "enemy": enemy,
            "type": _TERRAIN_SOUL.get(terrain, "")}


# Live combat stats we surface for coaching (haste → cooldown reads, hp% → all-in /
# retreat calls). We keep a curated subset — the raw ``championStats`` blob carries
# ~30 fields, most irrelevant to a coach.
def _champion_stats(active: dict) -> dict:
    cs = active.get("championStats") or {}
    cur_hp = float(cs.get("currentHealth") or 0.0)
    max_hp = float(cs.get("maxHealth") or 0.0)
    return {
        "ability_haste": float(cs.get("abilityHaste") or 0.0),
        "attack_damage": round(float(cs.get("attackDamage") or 0.0), 1),
        "ability_power": round(float(cs.get("abilityPower") or 0.0), 1),
        "armor": round(float(cs.get("armor") or 0.0), 1),
        "magic_resist": round(float(cs.get("magicResist") or 0.0), 1),
        "move_speed": round(float(cs.get("moveSpeed") or 0.0), 1),
        "attack_range": round(float(cs.get("attackRange") or 0.0), 1),
        "current_health": round(cur_hp, 1),
        "max_health": round(max_hp, 1),
        "health_pct": round(100.0 * cur_hp / max_hp, 1) if max_hp > 0 else 0.0,
        "resource_value": round(float(cs.get("resourceValue") or 0.0), 1),
        "resource_max": round(float(cs.get("resourceMax") or 0.0), 1),
    }


def _abilities(active: dict) -> dict:
    """Skill levels (Q/W/E/R) from ``activePlayer.abilities`` — the R level drives
    level-6/11/16 ultimate power-spike detection. Empty when unavailable."""
    ab = active.get("abilities") or {}

    def lvl(key: str) -> int:
        return int((ab.get(key) or {}).get("abilityLevel") or 0)

    return {"q": lvl("Q"), "w": lvl("W"), "e": lvl("E"), "r": lvl("R"),
            "ult_level": lvl("R")}


def _item_spike(roster: list[dict], my_role: str) -> dict:
    """Completed-item lead over the same-role enemy laner (a power-spike read).
    Empty when there is no resolvable lane opponent or neither side has finished an
    item yet (nothing useful to show in the early game)."""
    if not my_role:
        return {}
    mine = next((p for p in roster
                 if p.get("side") == "ally" and p.get("role") == my_role), None)
    opp = next((p for p in roster
                if p.get("side") == "enemy" and p.get("role") == my_role), None)
    if mine is None or opp is None:
        return {}
    m, o = int(mine.get("completed_items") or 0), int(opp.get("completed_items") or 0)
    if m == 0 and o == 0:
        return {}
    diff = m - o
    status = "ahead" if diff >= 1 else "behind" if diff <= -1 else "even"
    return {"mine": m, "opponent": o, "status": status}


# Live Client ChampionKill events name the killer + assisters — enough to tell a
# solo loss from a collapse without ever touching the game process.
def _last_death(events: list[dict], my_name: str, roster: list[dict]) -> dict:
    """The most recent time I died, with who landed the kill and how many enemies
    were involved (an ``Assisters`` count > 0 means I was collapsed on, not out-
    played 1v1). ``{}`` when I haven't died yet."""
    mine = [e for e in events
            if e.get("EventName") == "ChampionKill" and e.get("VictimName") == my_name]
    if not mine:
        return {}
    e = mine[-1]
    killer = (e.get("KillerName") or "").strip()
    name_to_champ = {p.get("name"): p.get("champion") for p in roster}
    # KillerName is the summoner name for a champion kill (else a turret/monster).
    killer_champ = name_to_champ.get(killer) or name_to_champ.get(killer.split("#")[0]) or ""
    return {
        "killer_champ": killer_champ,
        "assisters": len(e.get("Assisters") or []),
        "game_time": float(e.get("EventTime") or 0.0),
    }


@lru_cache(maxsize=1)
def _champion_class_map() -> dict[str, tuple[str, ...]]:
    """``champion name/slug (lower) -> class tags`` from the local DDragon catalog
    (e.g. "zed" -> ("Assassin",)). Empty when the catalog is absent."""
    try:
        data = json.loads(config.CATALOG_CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: dict[str, tuple[str, ...]] = {}
    for info in (data.get("champions") or {}).values():
        tags = tuple(info.get("tags") or [])
        for key in ((info.get("name") or "").lower(), (info.get("id") or "").lower()):
            if key:
                out[key] = tags
    return out


# Class → the single most useful early-lane note against that archetype. Beginner-
# grade but on-screen-grounded: the enemy's champion class is visible from pick.
_CLASS_PLAYSTYLE = {
    "Assassin": "Respect the level-6 all-in — track their ultimate and hold a summoner.",
    "Marksman": "Deny CS and trade early; they win the game if they get to scale.",
    "Mage": "Dodge their key skillshot — their damage and threat drop hard on cooldown.",
    "Fighter": "Avoid extended fights at their item spikes; kite and short-trade.",
    "Tank": "Don't feed early kills; they scale on time, so pressure them off CS.",
    "Support": "Watch for a roam/engage; ward your flanks and don't get picked.",
}
# Enemy summoner spell → the tempo it signals for the lane.
_SPELL_TEMPO = {
    "Ignite": "Enemy Ignite means an early all-in — play safe until you out-trade it.",
    "Teleport": "Enemy Teleport is map pressure — watch their recalls and TP flanks.",
    "Heal": "Sustain summoner — extended trades favour them; look for burst windows.",
    "Barrier": "Barrier eats your burst — bait it before you commit your combo.",
    "Exhaust": "Exhaust neuters your all-in — force it out before you go in.",
    "Cleanse": "Cleanse escapes your lockdown — chain CC or wait it out.",
}


def _matchup(roster: list[dict], role: str) -> dict:
    """A lane plan against the same-role enemy: a class-based playstyle note plus a
    tempo read from their summoner spells — all from on-screen pick + loadout.
    ``{}`` when there is no resolvable lane opponent."""
    if not role:
        return {}
    opp = next((p for p in roster
                if p.get("side") == "enemy" and p.get("role") == role), None)
    if not opp or not opp.get("champion"):
        return {}
    tags = _champion_class_map().get((opp["champion"] or "").lower(), ())
    playstyle = next((_CLASS_PLAYSTYLE[t] for t in tags if t in _CLASS_PLAYSTYLE), "")
    tempo = next((_SPELL_TEMPO[s] for s in (opp.get("spells") or []) if s in _SPELL_TEMPO), "")
    if not playstyle and not tempo:
        return {}
    return {"opponent": opp["champion"], "playstyle": playstyle, "tempo": tempo}


def parse_live_state(raw: dict | None, *, my_role: str = "") -> LiveGameState:
    """Convert a raw ``allgamedata`` payload into a normalized snapshot. Returns
    the no-game sentinel for ``None``/malformed input. ``my_role`` (the champ-select
    role) is preferred over the live ``position`` field when provided."""
    if not isinstance(raw, dict):
        return LiveGameState.none()

    game = raw.get("gameData") or {}
    active = raw.get("activePlayer") or {}
    all_players = raw.get("allPlayers") or []
    events = (raw.get("events") or {}).get("Events") or []
    game_time = float(game.get("gameTime") or 0.0)
    map_terrain = (game.get("mapTerrain") or "").strip()

    me = _find_me(active, all_players) or {}
    scores = me.get("scores") or {}
    cs = int(scores.get("creepScore") or 0)
    cs_per_min = round(cs / (game_time / 60.0), 2) if game_time > 0 else 0.0
    my_team = me.get("team") or ""
    my_name = (me.get("riotIdGameName") or me.get("summonerName") or "").strip()

    position = me.get("position") or ""
    role = my_role or _norm_role(position)

    name_to_team = _team_map(all_players)
    objectives = _parse_objectives(events, name_to_team, my_team)
    death_times = [float(e.get("EventTime") or 0.0) for e in events
                   if e.get("EventName") == "ChampionKill" and e.get("VictimName") == my_name]
    light_events = [{"name": e.get("EventName"), "time": float(e.get("EventTime") or 0.0)}
                    for e in events]
    roster = _parse_roster(all_players, my_team)
    _infer_roles(roster)
    my_level = int(me.get("level") or active.get("level") or 0)

    return LiveGameState(
        active=True,
        game_time=game_time,
        my_name=my_name,
        champion=me.get("championName") or active.get("championName") or "",
        level=int(me.get("level") or active.get("level") or 0),
        kills=int(scores.get("kills") or 0),
        deaths=int(scores.get("deaths") or 0),
        assists=int(scores.get("assists") or 0),
        cs=cs,
        cs_per_min=cs_per_min,
        ward_score=float(scores.get("wardScore") or 0.0),
        role=role,
        position=position,
        team=my_team,
        is_dead=bool(me.get("isDead")),
        respawn_timer=float(me.get("respawnTimer") or 0.0),
        objectives=objectives,
        death_times=death_times,
        events=light_events,
        roster=roster,
        cs_benchmark=_cs_benchmark(role, cs_per_min),
        level_diff=_level_diff(roster, my_level, role),
        objective_timers=_objective_timers(light_events, game_time),
        soul=_dragon_soul(objectives, map_terrain),
        item_spike=_item_spike(roster, role),
        current_gold=float(active.get("currentGold") or 0.0),
        champion_stats=_champion_stats(active),
        abilities=_abilities(active),
        map_terrain=map_terrain,
        last_death=_last_death(events, my_name, roster),
        matchup=_matchup(roster, role),
    )
