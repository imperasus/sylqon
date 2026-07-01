"""Sylqon headless CLI entrypoint.

Runs the full pipeline (background search caching + lobby detection + Ollama
analysis + LCU injection) without the dashboard. For the Hextech dashboard,
run `python -m sylqon.server` instead — both share PipelineRunner.
"""
from __future__ import annotations

import logging

# Re-exported for backwards compatibility: server.py and tests import
# ``setup_logging`` from here. The implementation now lives in one place.
from sylqon.logging_setup import setup_logging  # noqa: F401


def run() -> None:
    setup_logging()
    from sylqon.runtime import PipelineRunner

    try:
        PipelineRunner().run_forever()
    except KeyboardInterrupt:
        logging.getLogger("sylqon").info("Shutting down")


if __name__ == "__main__":
    run()
