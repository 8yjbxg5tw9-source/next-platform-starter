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

# optional drag & drop support
try:
    import tkinterdnd2  # noqa: F401

    hiddenimports.append("tkinterdnd2")
    datas += [("tkinterdnd2/tkDnD", "tkinterdnd2/tkDnD")]
except ImportError:
    pass

a = Analysis(
    ["main.py"],
    pathex=["."],
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
