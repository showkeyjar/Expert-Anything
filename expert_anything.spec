# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the ExpertAnything desktop app (onedir build).

Build:
    pip install -r requirements.txt pyinstaller
    python -m PyInstaller expert_anything.spec --clean --noconfirm

Output: dist/ExpertAnything/ExpertAnything(.exe) — double-click to run.
The repo-root ``data/`` folder is bundled and, on first run, copied into a
writable ``data/`` next to the executable (see pyi_runtime_data_dir.py).
"""
import os

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

# Bundle the repo-root demo/seed data next to the executable.
datas = [("data", "data")]

# Static safety net: pull in every submodule so dynamically imported
# domain/skill packages are not dropped from the frozen binary.
hiddenimports = collect_submodules("expert_anything")

a = Analysis(
    ["main.py"],
    pathex=[os.getcwd()],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=["pyi_runtime_data_dir.py"],
    excludes=[
        "flet",                 # retired frontend, shrinks the bundle
        "expert_anything.ui.app",
        "tkinter",
        "unittest",
        "test",
    ],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name="ExpertAnything",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,            # GUI app — no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="ExpertAnything",
)
