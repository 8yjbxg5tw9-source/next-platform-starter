# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — build ReelForge as ONE self-contained .exe.

Build (run this once on Windows, next to this file):

    pip install -r requirements.txt pyinstaller
    pyinstaller run_app.spec --noconfirm

Output:  dist/ReelForge.exe   (single file, no console window)

The spec:
  * collect_all() -> customtkinter, tkinterdnd2, PIL, reelforge   (code+data+binaries)
  * datas          -> ffmpeg.exe / ffprobe.exe copied to the bundle ROOT
  * console=False  -> no black terminal window
  * hiddenimports  -> every lazily-imported reelforge/tkinter submodule

ffmpeg.exe / ffprobe.exe are NOT shipped in git (they are large, licensed
binaries).  Drop them next to this .spec before building — see README "EXE".
"""

import os

from PyInstaller.utils.hooks import collect_all

# Root of the project (the folder that contains run_app.spec).  PyInstaller
# injects SPECPATH; fall back to the file location for standalone exec.
if "SPECPATH" not in globals():
    SPECPATH = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(SPECPATH)

block_cipher = None

# ---- gather code + data + binaries from the Python packages -----------------
datas = []
binaries = []
hiddenimports = []

for package in ("customtkinter", "tkinterdnd2", "PIL", "reelforge"):
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hiddenimports += h

# ---- lazily imported modules PyInstaller's static analysis can miss ---------
hiddenimports += [
    # reelforge submodules (some imported via importlib / inside functions)
    "reelforge", "reelforge.models", "reelforge.presets", "reelforge.toolchain",
    "reelforge.probe", "reelforge.filters", "reelforge.encode",
    "reelforge.interpolate", "reelforge.pipeline", "reelforge.uistate",
    "reelforge.cli", "reelforge.gui", "reelforge.gui.decoy", "reelforge.gui.app",
    "reelforge.gui.theme", "reelforge.gui.dnd",
    # tkinter pieces used at runtime
    "tkinter", "tkinter.ttk", "tkinter.filedialog", "tkinter.messagebox",
    "tkinter.font",
    # optional conveniences (app degrades gracefully when absent)
    "tkinterdnd2",
]

# ---- side-by-side ffmpeg / ffprobe -----------------------------------------
# Any of these placed next to run_app.spec gets copied into the bundle root,
# where run_app.py (via toolchain.runtime_dirs) will find them at runtime.
for _exe in ("ffmpeg.exe", "ffprobe.exe", "ffmpeg", "ffprobe"):
    _src = os.path.join(ROOT, _exe)
    if os.path.isfile(_src):
        datas.append((_src, "."))

a = Analysis(
    [os.path.join(ROOT, "run_app.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zlib_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="ReelForge",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # <- no terminal window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    cipher=block_cipher,
)
