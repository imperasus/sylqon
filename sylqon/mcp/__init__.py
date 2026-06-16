"""op.gg ingest helpers for the v2 store (Claude-driven, not a subprocess client).

The app does not embed an MCP transport. Instead — exactly like the existing
``POST /api/opgg-build`` path — Claude calls the op.gg MCP tools in conversation
and POSTs the parsed results to the ``/api/ingest/*`` endpoints. This package
holds the pure validate/normalize/upsert logic those endpoints call, plus a
description of the sync run order (see :mod:`sylqon.mcp.sync`).
"""
