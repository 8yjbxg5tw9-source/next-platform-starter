# -*- mode: python ; coding: utf-8 -*-
# PyInstaller build spec for the Akai client.
#
#   pip install -r requirements.txt pyinstaller
#   pyinstaller akai.spec --noconfirm
#
# Output: dist/Akai.exe (one file, no console window).

from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [], [], []
for package in ("customtkinter",):
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hiddenimports += h

# optional drag & drop support. tkinterdnd2 ships its tcl/dll payload (tkDnD)
# inside the *installed* package, so datas must point there with an absolute
# path — a project-relative "tkinterdnd2/tkDnD" can never exist.
import importlib.util

_tkdnd = importlib.util.find_spec("tkinterdnd2")
if _tkdnd is not None and _tkdnd.submodule_search_locations:
    from pathlib import Path as _Path

    _pkg_dir = _Path(list(_tkdnd.submodule_search_locations)[0])
    hiddenimports.append("tkinterdnd2")
    datas += [(str(_pkg_dir), "tkinterdnd2")]

# AKAI_ANALYSIS_PATHS is only used by headless CI/sandbox builds that need a
# tkinter stub for import analysis; on a normal machine it stays empty.
import os

_extra_paths = [p for p in os.environ.get("AKAI_ANALYSIS_PATHS", "")
                .split(os.pathsep) if p]

a = Analysis(
    ["main.py"],
    pathex=[".", *_extra_paths],
    binaries=binaries,
    datas=datas + [
        ("assets", "assets"),
        # ship bundled ffmpeg so users need no extra install:
        # ("ffmpeg/bin/ffmpeg.exe", "."),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["torch", "matplotlib", "scipy"],  # AI deps: bundle only if used
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Akai",
    debug=False,
    strip=False,
    upx=False,
    console=False,                  # windowed app: no console
    icon="assets/icon.ico",         # title bar + taskbar icon
    version=None,
)
