"""Sylqon headless CLI entrypoint.

Runs the full pipeline (background search caching + lobby detection + Ollama
analysis + LCU injection) without the dashboard. For the Hextech dashboard,
run `python -m sylqon.server` instead — both share PipelineRunner.
"""
from __future__ import annotations

import logging

from sylqon import config


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(config.LOG_PATH, encoding="utf-8"),
        ],
    )


def run() -> None:
    setup_logging()
    from sylqon.runtime import PipelineRunner

    try:
        PipelineRunner().run_forever()
    except KeyboardInterrupt:
        logging.getLogger("sylqon").info("Shutting down")


if __name__ == "__main__":
    run()
