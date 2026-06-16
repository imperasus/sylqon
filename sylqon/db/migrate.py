"""One-shot migration: seed the v2 store from existing data sources.

Run as a module::

    python -m sylqon.db.migrate

What it does (idempotent — safe to re-run):
  1. Seed a ``Champion`` row per Data Dragon champion (name, slug, riot_key, tags).
     ``roles`` are left empty here and populated later from op.gg lane-meta (Phase 2).
  2. Mirror every cached build in ``meta_cache.json`` into ``ChampionBuild``
     (the full build dict goes into ``build_json``).

The injection pipeline is untouched: this only *copies* data into SQLite.

The core functions accept an explicit ``session``/``catalog``/``cache`` so tests
can drive them against a temp database with a fake catalog (no network).
"""
from __future__ import annotations

import json
import logging

from sqlalchemy.orm import Session

from sylqon import config
from sylqon.db.schema import Champion, ChampionBuild

log = logging.getLogger(__name__)


def seed_champions(session: Session, catalog) -> int:
    """Upsert one ``Champion`` row per catalog champion. Returns rows touched."""
    touched = 0
    for entry in catalog.all_champions():
        name = entry["name"]
        info = catalog.champion_by_name(name) or {}
        riot_key = None
        try:
            riot_key = int(info["key"])
        except (KeyError, TypeError, ValueError):
            pass

        champ = session.query(Champion).filter_by(name=name).first()
        if champ is None:
            champ = Champion(name=name, roles=[])
            session.add(champ)
        champ.slug = entry.get("slug") or info.get("id")
        champ.tags = entry.get("tags", [])
        if riot_key is not None:
            champ.riot_key = riot_key
        if champ.roles is None:
            champ.roles = []
        touched += 1
    session.flush()
    return touched


def migrate_builds(session: Session, catalog, cache: dict) -> int:
    """Mirror ``meta_cache.json`` builds into ``ChampionBuild``. Returns rows touched."""
    patch = cache.get("patch") or catalog.patch
    touched = 0
    for key, entry in (cache.get("builds") or {}).items():
        build = entry.get("build")
        if not build:
            continue
        name, _, role = key.partition("|")
        champ = session.query(Champion).filter_by(name=name).first()
        if champ is None:
            log.warning("Skipping build for unknown champion %r", name)
            continue

        row = (
            session.query(ChampionBuild)
            .filter_by(champion_id=champ.id, role=role)
            .first()
        )
        if row is None:
            row = ChampionBuild(champion_id=champ.id, role=role)
            session.add(row)
        row.patch = patch
        row.build_json = build
        row.source = entry.get("source")
        touched += 1
    session.flush()
    return touched


def _load_cache() -> dict:
    try:
        return json.loads(config.META_CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log.warning("No readable meta_cache.json at %s", config.META_CACHE_PATH)
        return {}


def run() -> dict:
    """Production entry: real DB, real catalog, real meta_cache.json."""
    from sylqon.data.catalog import Catalog
    from sylqon.db.session import get_session, init_db

    init_db()
    catalog = Catalog()
    catalog.refresh_if_stale()  # uses on-disk cache if fresh; network only if stale

    session = get_session()
    try:
        champs = seed_champions(session, catalog)
        builds = migrate_builds(session, catalog, _load_cache())
        session.commit()
    finally:
        session.close()

    result = {"champions": champs, "builds": builds}
    log.info("Migration complete: %s", result)
    return result


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    result = run()
    print(f"Migration complete: {result['champions']} champions, {result['builds']} builds.")


if __name__ == "__main__":
    main()
