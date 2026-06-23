"""Retrieval-Augmented Generation layer for Sylqon.

Currently scoped to item retrieval: a semantic, patch-resilient replacement for
the hand-maintained ``static.ITEM_COUNTER_TAGS`` table used by the OpenBuild
counter-loadout path. Everything here degrades gracefully — if the local
embedding model or the prebuilt index is unavailable, callers fall back to the
existing deterministic ``Catalog.items_for_threat`` path.
"""
