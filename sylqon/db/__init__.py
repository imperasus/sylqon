"""SQLite persistence layer for Antigravity v2.

Owns the full champion universe (stats, builds, counters, synergies) plus match
history and AI analyses. Additive to the existing file-based meta cache: the
live champ-select -> injection pipeline keeps reading from MetaCache; builds are
*mirrored* here for the champion browser, scoring and build variants.
"""
