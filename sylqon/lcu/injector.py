"""Idempotent LCU injection of the compiled loadout.

Guardrails enforced here:
  1. ANTI-CLUTTER: item set and rune page always use the exact title
     "Antigravity Meta". Existing entries are fetched first and destructively
     overwritten via PUT; POST happens at most once (first run ever).
  2. SPELLS: spell1 (D key) is a utility spell — or Smite for junglers — and
     can never be Flash; spell2 (F key) is a mobility spell (Flash by default,
     Ghost when the build calls for it). The two slots can never collide.
  3. STAT SHARDS: the 3 shard ids are never sent as a separate block — they
     are stripped from and re-appended onto the tail of selectedPerkIds so
     the client registers the stat changes.
"""
from __future__ import annotations

import logging

import requests

from sylqon import config
from sylqon.data import static
from sylqon.lcu.client import LCUClient
from sylqon.loadout import Loadout

log = logging.getLogger(__name__)


# --- guardrail 3: stat shard routing ----------------------------------------
def merge_stat_shards(rune_perk_ids: list[int], shard_ids: list[int]) -> list[int]:
    """Append the 3 stat shard ids onto the tail-end of the main rune
    payload's selectedPerkIds. Any shard ids accidentally present earlier in
    the array are stripped first so the shards occupy exactly the final three
    indices of the payload."""
    runes_only = [pid for pid in rune_perk_ids if pid not in static.SHARD_ID_SET]
    shards = [sid for sid in shard_ids if sid in static.SHARD_ID_SET][:3]
    while len(shards) < 3:
        shards.append(static.STAT_SHARDS[static.DEFAULT_SHARDS[len(shards)]])
    return runes_only + shards


def _elixir_for(loadout: Loadout) -> dict:
    """The elixir matching the build's damage class: Wrath for AD-item builds,
    Sorcery for AP, Iron otherwise (tanks/supports/hybrids get more from the
    tenacity + size)."""
    ad = ap = 0
    for it in loadout.items:
        cls = static.ITEM_CLASS_RESTRICTION.get(it.get("name", ""), "universal")
        ad += cls == "ad_only"
        ap += cls == "ap_only"
    if ad >= 2 and ad > ap:
        return static.ELIXIR_OF_WRATH
    if ap >= 2 and ap > ad:
        return static.ELIXIR_OF_SORCERY
    return static.ELIXIR_OF_IRON


def _consumables_block_items(loadout: Loadout) -> list[dict]:
    return [static.CONTROL_WARD, dict(static.STARTER_CONSUMABLE), _elixir_for(loadout)]


def build_item_blocks(loadout: Loadout) -> list[dict]:
    """LCU item-set blocks for the injected set.

    With a situational pool the set is split into labelled phases — starting
    items, boots + core, the picks chosen for THIS game, then the unused pool
    items grouped by tactical purpose ("ALT % Pen: vs 2+ tanks", "ALT
    Anti-heal: ...") — so the player can re-route mid-game without leaving the
    shop. Legacy builds (no pool) keep the original single core block. Every
    set ends with a consumables block (Control Ward each back + the elixir
    matching the build's damage class).
    """
    def block(title: str, items: list[dict]) -> dict:
        return {"type": title, "items": [{"id": str(i["id"]), "count": 1} for i in items]}

    consumables = block("Consumables: Control Ward every back; Elixir at 3+ items",
                        _consumables_block_items(loadout))

    blocks = []
    if loadout.starting_items:
        blocks.append(block("Starting Items", loadout.starting_items))

    core_len = len(loadout.core_items)
    if not (core_len and loadout.situational_pool and loadout.boots is not None
            and len(loadout.items) > core_len + 1):
        # No pool structure — show all items in one block
        blocks.append(block(f"Core Build vs {loadout.enemy_summary}", loadout.items))
        blocks.append(consumables)
        return blocks

    # items = [boots, core..., situational picks...] (the AI may have swapped
    # one core item, so split positionally instead of trusting core_items).
    blocks.append(block("Early Core (boots + core 3)", loadout.items[:core_len + 1]))
    blocks.append(block(f"Picked vs {loadout.enemy_summary}"[:80],
                        loadout.items[core_len + 1:]))

    # Unused pool items, grouped by primary counter tag so each block title
    # says when to pivot to it.
    used_ids = {i["id"] for i in loadout.items}
    groups: dict[str, list[dict]] = {}
    for it in loadout.situational_pool:
        if it["id"] in used_ids:
            continue
        tags = static.ITEM_COUNTER_TAGS.get(it["id"], ())
        groups.setdefault(tags[0] if tags else "damage", []).append(it)
    for tag, (label, when) in static.COUNTER_TAG_INFO.items():
        if tag in groups:
            blocks.append(block(f"ALT {label}: {when}", groups[tag]))
    blocks.append(consumables)
    return blocks


class Injector:
    def __init__(self, client: LCUClient) -> None:
        self.client = client

    def inject(self, loadout: Loadout, summoner_id: int, champion_id: int) -> bool:
        ok_items = self._inject_item_set(loadout, summoner_id, champion_id)
        ok_runes = self._inject_rune_page(loadout)
        ok_spells = self._inject_spells(loadout)
        return ok_items and ok_runes and ok_spells

    # --- item set (guardrail 1: destructive overwrite by title) --------------
    def _inject_item_set(self, loadout: Loadout, summoner_id: int, champion_id: int) -> bool:
        path = f"/lol-item-sets/v1/item-sets/{summoner_id}/sets"
        try:
            current = self.client.get_json(path) or {}
        except requests.RequestException:
            current = {}
        sets = current.get("itemSets", []) if isinstance(current, dict) else []

        blocks = build_item_blocks(loadout)

        new_set = {
            "title": config.PROFILE_TITLE,
            "associatedChampions": [],   # single stable profile, visible on all heroes
            "associatedMaps": [],
            "blocks": blocks,
            "map": "any",
            "mode": "any",
            "preferredItemSlots": [],
            "sortrank": 0,
            "startedFrom": "blank",
            "type": "custom",
        }

        # Overwrite the matching title in place; never accumulate new sets.
        replaced = False
        for idx, existing in enumerate(sets):
            if existing.get("title") == config.PROFILE_TITLE:
                new_set["uid"] = existing.get("uid", "")
                sets[idx] = new_set
                replaced = True
                break
        if not replaced:
            sets.append(new_set)

        body = {
            "accountId": current.get("accountId", summoner_id),
            "itemSets": sets,
            "timestamp": current.get("timestamp", 0),
        }
        try:
            resp = self.client.put(path, json=body)
            ok = resp.status_code in (200, 201, 204)
            if resp.status_code == 413:
                log.warning(
                    "Item set collection exceeds the LCU's 64KB body limit "
                    "(%d sets); delete old third-party item sets in the "
                    "client to make room.", len(sets))
        except requests.RequestException as exc:
            log.error("Item set PUT failed: %s", exc)
            return False
        log.info("Item set '%s' %s (%s)", config.PROFILE_TITLE,
                 "overwritten" if replaced else "created", resp.status_code)
        return ok

    # --- rune page (guardrail 1 + 3) -------------------------------------------
    def _inject_rune_page(self, loadout: Loadout) -> bool:
        selected = merge_stat_shards(loadout.rune_perk_ids, loadout.shard_ids)
        payload = {
            "name": config.PROFILE_TITLE,
            "primaryStyleId": loadout.primary_style_id,
            "subStyleId": loadout.secondary_style_id,
            "selectedPerkIds": selected,
            "current": True,
        }
        pages = self.client.get_json("/lol-perks/v1/pages")
        pages = pages if isinstance(pages, list) else []

        existing = next((p for p in pages if p.get("name") == config.PROFILE_TITLE), None)
        try:
            if existing:
                resp = self.client.put(f"/lol-perks/v1/pages/{existing['id']}", json=payload)
            else:
                resp = self.client.post("/lol-perks/v1/pages", json=payload)
                if resp.status_code == 400:
                    # Page limit reached: destructively reuse an editable page
                    # rather than failing — still exactly one Antigravity page.
                    victim = next((p for p in pages if p.get("isEditable", p.get("isDeletable", False))), None)
                    if victim:
                        resp = self.client.put(f"/lol-perks/v1/pages/{victim['id']}", json=payload)
            ok = resp.status_code in (200, 201, 204)
        except requests.RequestException as exc:
            log.error("Rune page injection failed: %s", exc)
            return False
        log.info("Rune page '%s' %s (%s); selectedPerkIds tail=%s",
                 config.PROFILE_TITLE, "updated" if existing else "created",
                 resp.status_code, selected[-3:])
        return ok

    # --- summoner spells (guardrail 2) -------------------------------------------
    def _inject_spells(self, loadout: Loadout) -> bool:
        """D key = loadout.spell1 (utility, or Smite for jungle); F key =
        loadout.spell2 (mobility). Guard: the two slots can never be the same
        spell — if they collide, F falls back to Flash."""
        d_name = loadout.spell1
        # D must be a valid utility spell or Smite (jungle); else default Heal.
        if d_name != "Smite" and d_name not in static.ALLOWED_SPELL1:
            d_name = "Heal"
        f_name = loadout.spell2 if loadout.spell2 in static.ALLOWED_SPELL2 else "Flash"

        spell1_id = static.SUMMONER_SPELLS[d_name]
        spell2_id = static.SUMMONER_SPELLS[f_name]
        if spell1_id == spell2_id:  # never double up a slot
            spell2_id = static.FLASH_ID
            f_name = "Flash"
        try:
            resp = self.client.patch(
                "/lol-champ-select/v1/session/my-selection",
                json={"spell1Id": spell1_id, "spell2Id": spell2_id},
            )
            ok = resp.status_code in (200, 204)
        except requests.RequestException as exc:
            log.error("Spell patch failed: %s", exc)
            return False
        log.info("Spells set: D=%s + F=%s (%s)", d_name, f_name, resp.status_code)
        return ok
