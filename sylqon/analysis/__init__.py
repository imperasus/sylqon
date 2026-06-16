"""Deterministic, DB-backed analysis (no Ollama).

Houses the 0-100 champion scorer that powers universal role-based
recommendations. Pure and testable: given the SQLite store it always returns the
same scores for the same draft state.
"""
