"""PyInstaller entry point for the bundled Sylqon backend.

Starts the exact same uvicorn server as `python -m sylqon.server`, but as a
self-contained executable so the desktop app needs no system Python install.

Writable paths (DB, cache, logs) are redirected by the Electron app via the
SYLQON_CACHE_DIR / SYLQON_LOG_DIR / DB_PATH environment variables (see
sylqon/config.py), because the bundle itself may live in a read-only location.
"""
import multiprocessing

from sylqon.server import run

if __name__ == "__main__":
    # No-op for our single-process server, but the correct guard for frozen
    # apps in case any dependency ever spawns a child process.
    multiprocessing.freeze_support()
    run()
