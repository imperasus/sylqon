"""Champ select monitoring and enemy-team context parsing."""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field

from sylqon.data import static
from sylqon.data.catalog import Catalog
from sylqon.lcu.client import LCUClient

log = logging.getLogger(__name__)


@dataclass
class ChampPick:
    """One picked champion in champ select — used for both teams.

    Allies and enemies share this shape; `side` distinguishes them and drives
    whether the AI treats the pick as a synergy or a counter signal.
    """
    name: str
    champion_id: int
    role: str
    side: str                 # "ally" | "enemy"
    damage_type: str          # "AD" | "AP" | "Mixed"
    tags: list[str] = field(default_factory=list)
    threats: list[str] = field(default_factory=list)
    spell1: str = ""          # summoner spell names (resolved from ids)
    spell2: str = ""
    locked: bool = False       # pick is locked in (vs. merely hovered)

    def spell_line(self) -> str:
        spells = [s for s in (self.spell1, self.spell2) if s]
        return " + ".join(spells) if spells else "spells hidden"

    def describe(self) -> str:
        threat_txt = ", ".join(self.threats) if self.threats else "none flagged"
        return (f"{self.name} ({self.role or 'unknown role'}, {self.damage_type} damage, "
                f"class: {'/'.join(self.tags) or 'unknown'}, threats: {threat_txt}, "
                f"summoners: {self.spell_line()})")


# Backwards-compatible alias: the original name used across the codebase.
EnemyProfile = ChampPick


@dataclass
class MatchContext:
    summoner_id: int
    my_champion: str
    my_champion_id: int
    my_role: str
    locked: bool                       # our pick is locked in
    all_locked: bool                   # every player in the lobby has locked
    my_turn: bool                      # our pick action is in progress (our turn)
    enemies: list[ChampPick]
    allies: list[ChampPick]            # team-mates excluding the local player
    fingerprint: str
    bans: list[int] = field(default_factory=list)   # champion ids banned by both teams
    # Per-team ban slots in draft order, display-ready (see ``parse_bans``).
    ban_slots: dict = field(default_factory=lambda: {"ally": [], "enemy": []})
    enemy_picks_after_me: int = 0      # enemy pick actions still to come after ours
    ally_picks_after_me: int = 0       # ally pick actions still to come after ours
    is_last_pick: bool = False         # our pick is the last one in the draft order
    my_ban_turn: bool = False          # our ban action is in progress (act on a ban now)
    # Actor cellIds of pick actions in real chronological draft order, per side —
    # drives the live-draft card insertion order (see ``_turn_orders``).
    ally_turn_order: list[int] = field(default_factory=list)
    enemy_turn_order: list[int] = field(default_factory=list)
    # Side + index (within that side's turn order) of the pick action currently
    # in progress, or (None, None) between actions / during a ban (see ``_active_pick``).
    active_pick_side: str | None = None
    active_pick_index: int | None = None

    def trigger_signature(self) -> str:
        """Signature of the *meaningful* draft state — the bits that should
        re-trigger heavy work (recommendation, counter-analysis). It moves only
        when a champion locks in, when it becomes our turn, or when the draft
        finalizes. Crucially it is stable across hovers and timer ticks, so the
        WebSocket can fire many times a second without waking Ollama."""
        locked_enemies = sorted(e.champion_id for e in self.enemies if e.locked)
        locked_allies = sorted(a.champion_id for a in self.allies if a.locked)
        return "|".join([
            self.my_role,
            str(self.my_champion_id),
            "E:" + ",".join(map(str, locked_enemies)),
            "A:" + ",".join(map(str, locked_allies)),
            f"turn={int(self.my_turn)}",
            f"all={int(self.all_locked)}",
        ])

    def team_threat_summary(self) -> dict:
        return summarize_team(self.enemies)


def summarize_team(picks) -> dict:
    """Aggregate the damage / threat profile of a list of picks. Accepts either
    ``ChampPick`` instances or the plain dict shape ``{tags, threats,
    damage_type}`` so a synthesised pick (e.g. the local player) can be folded
    in. Superset of the original enemy threat summary — adds a ``frontline``
    count that drives the live-draft structure warnings."""
    picks = [p for p in picks if p]

    def tags_of(p) -> set:
        return set(p["tags"] if isinstance(p, dict) else p.tags)

    def threats_of(p) -> set:
        return set(p["threats"] if isinstance(p, dict) else p.threats)

    def dmg_of(p) -> str:
        return p["damage_type"] if isinstance(p, dict) else p.damage_type

    ad = sum(1 for p in picks if dmg_of(p) == "AD")
    ap = sum(1 for p in picks if dmg_of(p) == "AP")
    return {
        "physical_threats": ad,
        "magic_threats": ap,
        "mixed_threats": len(picks) - ad - ap,
        "heavy_cc_count": sum(1 for p in picks if "heavy_cc" in threats_of(p)),
        "suppression": any("suppression" in threats_of(p) for p in picks),
        "burst_ad": any("burst_ad" in threats_of(p) for p in picks),
        "burst_ap": any("burst_ap" in threats_of(p) for p in picks),
        "heavy_healing": any("heavy_healing" in threats_of(p) for p in picks),
        "tanks": sum(1 for p in picks if "tank" in threats_of(p)),
        "frontline": sum(1 for p in picks if tags_of(p) & {"Tank", "Fighter"}),
    }


def _damage_type(info: dict | None) -> str:
    if not info:
        return "Mixed"
    attack, magic = info.get("attack", 0), info.get("magic", 0)
    if attack >= magic + 3:
        return "AD"
    if magic >= attack + 3:
        return "AP"
    return "Mixed"


def _threats(name: str) -> list[str]:
    out = []
    if name in static.HEAVY_CC_CHAMPS:
        out.append("heavy_cc")
    if name in static.SUPPRESSION_CHAMPS:
        out.append("suppression")
    if name in static.HIGH_BURST_AD:
        out.append("burst_ad")
    if name in static.HIGH_BURST_AP:
        out.append("burst_ap")
    if name in static.HEAVY_HEALING:
        out.append("heavy_healing")
    if name in static.HEAVY_POKE:
        out.append("poke")
    if name in static.HEAVY_TANK:
        out.append("tank")
    return out


def _profile(player: dict, side: str, catalog: Catalog,
             locked_cells: set[int]) -> ChampPick:
    champion_id = player["championId"]
    info = catalog.champion_by_key(champion_id)
    name = info["name"] if info else f"Champion#{champion_id}"
    return ChampPick(
        name=name,
        champion_id=champion_id,
        role=static.ROLE_ALIASES.get(player.get("assignedPosition", ""),
                                     player.get("assignedPosition", "")),
        side=side,
        damage_type=_damage_type(info),
        tags=info.get("tags", []) if info else [],
        threats=_threats(name),
        spell1=static.SPELL_BY_ID.get(player.get("spell1Id", 0), ""),
        spell2=static.SPELL_BY_ID.get(player.get("spell2Id", 0), ""),
        locked=player.get("cellId") in locked_cells,
    )


def _locked_cells(session: dict) -> set[int]:
    """Cell ids whose pick action is completed (champion locked in)."""
    return {
        a.get("actorCellId")
        for group in session.get("actions", [])
        for a in group
        if a.get("type") == "pick" and a.get("completed")
    }


def _is_my_turn(session: dict, cell_id: int) -> bool:
    """True while our own pick action is the one in progress."""
    for group in session.get("actions", []):
        for a in group:
            if (a.get("actorCellId") == cell_id and a.get("type") == "pick"
                    and a.get("isInProgress") and not a.get("completed")):
                return True
    return False


def _is_my_ban_turn(session: dict, cell_id: int) -> bool:
    """True while our own ban action is the one in progress — the moment to act on
    a ban suggestion. Mirrors :func:`_is_my_turn` for ``type == "ban"``."""
    for group in session.get("actions", []):
        for a in group:
            if (a.get("actorCellId") == cell_id and a.get("type") == "ban"
                    and a.get("isInProgress") and not a.get("completed")):
                return True
    return False


def _banned_champions(session: dict) -> list[int]:
    """Champion ids removed by completed ban actions from either team."""
    out: list[int] = []
    for group in session.get("actions", []):
        for a in group:
            if (a.get("type") == "ban" and a.get("completed")
                    and a.get("championId")):
                out.append(a["championId"])
    return out


def _action_team(action: dict, ally_cells: set[int]) -> str:
    """Which side an action belongs to. Prefer the client's own ``isAllyAction``
    flag; fall back to mapping the actor cell onto our team."""
    if "isAllyAction" in action:
        return "ally" if action.get("isAllyAction") else "enemy"
    return "ally" if action.get("actorCellId") in ally_cells else "enemy"


def parse_timer(session: dict) -> dict | None:
    """Countdown snapshot for the live-draft UI: remaining/total ms in the
    current phase. Reads the raw session directly (no catalog lookup, no
    dataclass build) so the caller can publish it on every ~1/sec LCU push,
    independent of :func:`display_signature`'s gate that skips heavier work
    on pure timer ticks."""
    if not isinstance(session, dict):
        return None
    timer = session.get("timer")
    if not isinstance(timer, dict):
        return None
    return {
        "phase": timer.get("phase", ""),
        "remaining_ms": max(0, timer.get("adjustedTimeLeftInPhase", 0)),
        "total_ms": timer.get("totalTimeInPhase", 0),
    }


def _turn_orders(session: dict, ally_cells: set[int],
                  my_cell_id: int) -> tuple[list[int], list[int]]:
    """Actor cellIds of pick actions in real chronological draft order, split
    per side. Unlike raw ``myTeam``/``theirTeam`` order (seat order), this
    reflects the actual sequence picks happen in — drives the live-draft
    card insertion order and locates the active turn even before anyone has
    hovered a champion for it. ``my_cell_id`` is excluded from the ally order:
    the local player's own row is always a fixed first slot on the frontend,
    and its turn is already signalled separately via ``MatchContext.my_turn``."""
    ally_order: list[int] = []
    enemy_order: list[int] = []
    for group in session.get("actions", []):
        for a in group:
            if a.get("type") != "pick":
                continue
            cell = a.get("actorCellId")
            if cell == my_cell_id:
                continue
            (ally_order if _action_team(a, ally_cells) == "ally" else enemy_order).append(cell)
    return ally_order, enemy_order


def _active_pick(session: dict, ally_cells: set[int], ally_order: list[int],
                  enemy_order: list[int]) -> tuple[str | None, int | None]:
    """Side + index (within that side's turn order) of the pick action
    currently in progress, or ``(None, None)`` between actions or during a
    ban — the moment to pulse the "on the clock" card in the live draft."""
    for group in session.get("actions", []):
        for a in group:
            if a.get("type") != "pick" or not a.get("isInProgress") or a.get("completed"):
                continue
            cell = a.get("actorCellId")
            if _action_team(a, ally_cells) == "ally":
                return ("ally", ally_order.index(cell)) if cell in ally_order else (None, None)
            return ("enemy", enemy_order.index(cell)) if cell in enemy_order else (None, None)
    return None, None


def parse_bans(session: dict, catalog: Catalog) -> dict:
    """Per-team ban slots in draft order, ready for the dashboard.

    Returns ``{"ally": [...], "enemy": [...]}`` where each slot is either a
    revealed ban ``{champion_id, name, slug, revealed: True}`` or a placeholder
    ``{revealed: False}`` for a pending or hidden (hovered) ban. The slot count
    per team is whatever the queue exposes via its ban actions, so non-draft
    modes simply yield empty lists — no hard-coded ban count."""
    ally_cells = {p.get("cellId") for p in session.get("myTeam", [])}
    out: dict[str, list[dict]] = {"ally": [], "enemy": []}
    for group in session.get("actions", []):
        for a in group:
            if a.get("type") != "ban":
                continue
            team = _action_team(a, ally_cells)
            cid = a.get("championId") or 0
            if a.get("completed") and cid:
                info = catalog.champion_by_key(cid) or {}
                out[team].append({
                    "champion_id": cid,
                    "name": info.get("name", ""),
                    "slug": info.get("id", ""),
                    "revealed": True,
                })
            else:
                out[team].append({"revealed": False})
    return out


def _pick_timing(session: dict, cell_id: int) -> tuple[int, int, bool]:
    """How many enemy / ally pick actions still come *after* ours in draft order,
    and whether ours is the very last pick. Drives counter-pick advice: a last
    pick can hard-counter freely; a blind pick should stay flexible.

    Pick actions appear in the session's ``actions`` groups in draft order, so a
    flat scan preserves the snake order."""
    enemy_cells = {p.get("cellId") for p in session.get("theirTeam", [])}
    picks = [a for group in session.get("actions", []) for a in group
             if a.get("type") == "pick"]
    my_index = next((i for i, a in enumerate(picks)
                     if a.get("actorCellId") == cell_id), -1)
    if my_index < 0:
        return 0, 0, False
    after = picks[my_index + 1:]
    enemy_after = sum(1 for a in after
                      if a.get("actorCellId") in enemy_cells and not a.get("completed"))
    ally_after = sum(1 for a in after
                     if a.get("actorCellId") not in enemy_cells and not a.get("completed"))
    is_last = all(a.get("completed") for a in after)
    return enemy_after, ally_after, is_last


def _all_players_locked(session: dict) -> bool:
    """True once the draft has reached finalization — every pick action across
    both teams is completed (or the client has flipped into FINALIZATION)."""
    timer_phase = (session.get("timer") or {}).get("phase", "")
    if timer_phase == "FINALIZATION":
        return True
    pick_actions = [a for group in session.get("actions", []) for a in group
                    if a.get("type") == "pick"]
    if not pick_actions:
        return False
    return all(a.get("completed") for a in pick_actions)


def display_signature(session: dict) -> str:
    """A cheap fingerprint over everything that affects the *display* of the
    draft — champion ids, summoner spells and lock state for every cell — but
    NOT the timer. Lets the WebSocket handler discard pure timer ticks (which
    fire several times a second) before doing any parsing or HTTP."""
    if not isinstance(session, dict):
        return ""
    parts: list[str] = [str(session.get("localPlayerCellId", -1))]
    for key in ("myTeam", "theirTeam"):
        for p in session.get(key, []):
            parts.append(f'{p.get("cellId")}:{p.get("championId", 0)}:'
                         f'{p.get("spell1Id", 0)}:{p.get("spell2Id", 0)}')
    for group in session.get("actions", []):
        for a in group:
            if a.get("type") == "pick":
                parts.append(f'{a.get("actorCellId")}='
                             f'{int(bool(a.get("completed")))}'
                             f'{int(bool(a.get("isInProgress")))}')
            elif a.get("type") == "ban":
                # Bans must move the signature too, otherwise a completed ban is
                # discarded as a timer tick and never reaches the live board.
                parts.append(f'b{a.get("actorCellId")}='
                             f'{a.get("championId", 0)}:'
                             f'{int(bool(a.get("completed")))}')
    parts.append(str(int(bool(((session.get("timer") or {})
                               .get("phase")) == "FINALIZATION"))))
    return "|".join(parts)


def read_match_context(client: LCUClient, catalog: Catalog,
                       session: dict | None = None,
                       summoner_id: int | None = None) -> MatchContext | None:
    """Parses /lol-champ-select/v1/session into a MatchContext, or None if we
    aren't in a champ select with a local player cell.

    The local player need NOT have picked yet: the context is built the moment
    champ select opens so the champion recommendation can read the enemy/ally
    picks and suggest what to play *before* we lock in. ``my_champion`` is empty
    until we hover/pick; the loadout is only compiled and injected once the
    whole lobby is locked (which implies our own pick exists).

    ``session`` may be supplied directly (e.g. straight from a WebSocket event
    payload) to avoid an extra HTTP round-trip; otherwise it is fetched.
    ``summoner_id``, when supplied, skips the per-call current-summoner lookup."""
    if session is None:
        session = client.get_json("/lol-champ-select/v1/session")
    if not isinstance(session, dict):
        return None

    cell_id = session.get("localPlayerCellId", -1)
    me = next((p for p in session.get("myTeam", []) if p.get("cellId") == cell_id), None)
    if not me:
        return None

    my_champion_id = me.get("championId") or 0
    locked_cells = _locked_cells(session)

    # Locked = a completed pick action for our cell, or championId pinned with
    # no pending pick action (covers non-draft queues). Never "locked" before
    # we've actually chosen a champion.
    has_pick_action = any(
        action.get("actorCellId") == cell_id and action.get("type") == "pick"
        for group in session.get("actions", []) for action in group
    )
    locked = bool(my_champion_id) and ((cell_id in locked_cells) or not has_pick_action)

    if summoner_id is None:
        summoner_id = (client.current_summoner() or {}).get("summonerId", 0)

    # Order enemies/allies by real chronological pick order (not raw LCU seat
    # order) so the live-draft cards fill in the order picks actually happen.
    # Falls back to raw seat order when the queue has no pick actions to scan
    # (e.g. ARAM) — unchanged from prior behaviour.
    ally_cells = {p.get("cellId") for p in session.get("myTeam", [])}
    ally_order, enemy_order = _turn_orders(session, ally_cells, cell_id)
    active_pick_side, active_pick_index = _active_pick(
        session, ally_cells, ally_order, enemy_order)

    their_by_cell = {p.get("cellId"): p for p in session.get("theirTeam", [])}
    enemy_players = ([their_by_cell[c] for c in enemy_order if c in their_by_cell]
                      if enemy_order else session.get("theirTeam", []))
    enemies = [
        _profile(p, "enemy", catalog, locked_cells)
        for p in enemy_players
        if p.get("championId")
    ]

    my_by_cell = {p.get("cellId"): p for p in session.get("myTeam", [])}
    ally_players = ([my_by_cell[c] for c in ally_order if c in my_by_cell and c != cell_id]
                     if ally_order else
                     [p for p in session.get("myTeam", []) if p.get("cellId") != cell_id])
    allies = [
        _profile(p, "ally", catalog, locked_cells)
        for p in ally_players
        if p.get("championId")
    ]

    my_role = static.ROLE_ALIASES.get(me.get("assignedPosition", ""),
                                      me.get("assignedPosition", "")) or "middle"
    all_locked = _all_players_locked(session)
    my_turn = _is_my_turn(session, cell_id)
    my_ban_turn = _is_my_ban_turn(session, cell_id)
    bans = _banned_champions(session)
    ban_slots = parse_bans(session, catalog)
    enemy_after, ally_after, is_last = _pick_timing(session, cell_id)
    fp_raw = (f'{session.get("gameId", 0)}|{my_champion_id}|{my_role}|'
              f'{int(all_locked)}|'
              + ",".join(str(e.champion_id) for e in sorted(enemies, key=lambda e: e.champion_id))
              + "|" + ",".join(str(a.champion_id) for a in sorted(allies, key=lambda a: a.champion_id)))
    return MatchContext(
        summoner_id=summoner_id,
        my_champion=catalog.champion_name(my_champion_id) if my_champion_id else "",
        my_champion_id=my_champion_id,
        my_role=my_role,
        locked=locked,
        all_locked=all_locked,
        my_turn=my_turn,
        enemies=enemies,
        allies=allies,
        fingerprint=hashlib.sha1(fp_raw.encode()).hexdigest(),
        bans=bans,
        ban_slots=ban_slots,
        enemy_picks_after_me=enemy_after,
        ally_picks_after_me=ally_after,
        is_last_pick=is_last,
        my_ban_turn=my_ban_turn,
        ally_turn_order=ally_order,
        enemy_turn_order=enemy_order,
        active_pick_side=active_pick_side,
        active_pick_index=active_pick_index,
    )
