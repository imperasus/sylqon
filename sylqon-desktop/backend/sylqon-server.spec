# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the bundled Sylqon backend (onedir).
#
# Build via:  npm run build:backend   (from sylqon-desktop/)
# Output:     backend/dist/sylqon-server/sylqon-server.exe
#
# onedir (COLLECT) is used over onefile: faster startup, fewer antivirus false
# positives, and no per-launch temp extraction.

import os
from PyInstaller.utils.hooks import collect_all, collect_submodules

# SPECPATH is sylqon-desktop/backend ; repo root is two levels up.
repo_root = os.path.abspath(os.path.join(SPECPATH, "..", ".."))

# Static data the backend reads at runtime (resolved relative to the package
# via Path(__file__), so the bundle layout must mirror the repo layout).
datas = [
    (os.path.join(repo_root, "sylqon", "data"), os.path.join("sylqon", "data")),
    (os.path.join(repo_root, "ui", "dist"), os.path.join("ui", "dist")),
]
binaries = []
# Pull in the whole sylqon package (covers any lazily-imported submodules) plus
# the SQLite dialect, which SQLAlchemy imports by name.
hiddenimports = collect_submodules("sylqon") + ["sqlalchemy.dialects.sqlite"]

# uvicorn/fastapi/starlette/anyio load protocols & loops dynamically — collect
# everything so PyInstaller doesn't miss them.
for pkg in ("uvicorn", "fastapi", "starlette", "anyio"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    [os.path.join(SPECPATH, "launcher.py")],
    pathex=[repo_root],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="sylqon-server",
    console=True,
    icon=os.path.join(repo_root, "sylqon-desktop", "build", "icon.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="sylqon-server",
)
