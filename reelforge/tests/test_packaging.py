"""Single-file (.exe) packaging: launcher bootstrap + spec wiring.

These run headlessly and prove, without building an actual Windows exe, that:

* a frozen app (``sys.frozen``/``sys._MEIPASS``) finds a side-by-side ffmpeg;
* ``run_app.prepare_environment`` fixes ``sys.path`` and ``PATH``;
* ``run_app.spec`` executes and wires ffmpeg into ``datas``, sets
  ``console=False`` and lists the required ``hiddenimports``.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

from reelforge import toolchain

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_run_app():
    spec = importlib.util.spec_from_file_location(
        "run_app_under_test", PROJECT_ROOT / "run_app.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------- #
# frozen ffmpeg discovery
# --------------------------------------------------------------------------- #


def test_frozen_app_finds_side_by_side_ffmpeg(tmp_path, monkeypatch):
    fake = tmp_path / "ffmpeg"
    fake.write_text("#!/bin/sh\n")
    fake.chmod(0o755)

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(toolchain.shutil, "which", lambda *a, **k: None)
    monkeypatch.delenv("REELFORGE_FFMPEG", raising=False)
    monkeypatch.delenv("FFMPEG", raising=False)

    found = toolchain.find_executable("ffmpeg")
    assert found == fake.resolve()


def test_runtime_dirs_empty_when_not_frozen():
    # not frozen in the test process -> no MEIPASS-derived dirs
    assert not [d for d in toolchain.runtime_dirs() if "_MEI" in str(d)]


# --------------------------------------------------------------------------- #
# run_app bootstrap
# --------------------------------------------------------------------------- #


def test_prepare_environment_fixes_sys_path_and_path():
    run_app = _load_run_app()
    env = run_app.prepare_environment()

    # the folder that contains the `reelforge` package is importable
    assert str(PROJECT_ROOT) in sys.path
    assert importlib.util.find_spec("reelforge") is not None

    # PATH now contains our candidate dirs
    assert PROJECT_ROOT in env["dirs"]
    assert os_path_starts_with(PROJECT_ROOT)

    # ffmpeg may or may not exist here; the call must not raise
    assert isinstance(env["ffmpeg"], Path)


def os_path_starts_with(root: Path) -> bool:
    import os

    return str(root) in os.environ["PATH"].split(os.pathsep)


def test_prepare_ffmpeg_env_exports_env_vars(tmp_path, monkeypatch):
    run_app = _load_run_app()
    fake = tmp_path / "ffmpeg.exe"
    fake.write_bytes(b"MZ")
    # set (not del) so monkeypatch restores a harmless empty value afterwards
    monkeypatch.setenv("REELFORGE_FFMPEG", "")
    monkeypatch.setenv("REELFORGE_FFPROBE", "")

    run_app._prepare_ffmpeg_env([tmp_path])
    import os

    assert os.environ["REELFORGE_FFMPEG"] == str(fake)


# --------------------------------------------------------------------------- #
# run_app.spec smoke test (exec with stubbed PyInstaller)
# --------------------------------------------------------------------------- #


class _Recorder:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


class _Analysis:
    """Stands in for PyInstaller's Analysis: exposes attrs the spec reads."""

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.pure = "PURE"
        self.zlib_data = "ZLIB"
        self.scripts = kwargs.get("scripts", [])
        self.binaries = kwargs.get("binaries", [])
        self.zipfiles = []
        self.datas = kwargs.get("datas", [])


def _exec_spec(tmp_path: Path):
    spec_text = (PROJECT_ROOT / "run_app.spec").read_text(encoding="utf-8")

    # fake `from PyInstaller.utils.hooks import collect_all`
    pkg = types.ModuleType("PyInstaller")
    utils = types.ModuleType("PyInstaller.utils")
    hooks = types.ModuleType("PyInstaller.utils.hooks")

    def collect_all(name):
        return ([(name, name)], [(name, name)], [name])

    hooks.collect_all = collect_all
    pkg.utils = utils
    utils.hooks = hooks
    for key, mod in (("PyInstaller", pkg), ("PyInstaller.utils", utils),
                     ("PyInstaller.utils.hooks", hooks)):
        sys.modules[key] = mod

    recorded = {}

    def make_analysis(*a, **k):
        rec = _Analysis(*a, **k)
        recorded["analysis"] = rec
        return rec

    namespace = {
        "SPECPATH": str(tmp_path),
        "Analysis": make_analysis,
        "PYZ": lambda *a, **k: _Recorder(*a, **k),
        "EXE": lambda *a, **k: _record(recorded, "exe", a, k),
        "COLLECT": lambda *a, **k: _Recorder(*a, **k),
        "BUNDLE": lambda *a, **k: _Recorder(*a, **k),
    }
    exec(spec_text, namespace)
    return recorded


def _record(store, key, args, kwargs):
    rec = _Recorder(*args, **kwargs)
    store[key] = rec
    return rec


def test_spec_wires_ffmpeg_console_and_hiddenimports(tmp_path):
    (tmp_path / "ffmpeg.exe").write_bytes(b"MZ")
    (tmp_path / "ffprobe.exe").write_bytes(b"MZ")

    recorded = _exec_spec(tmp_path)

    exe = recorded["exe"]
    assert exe.kwargs["console"] is False
    assert exe.kwargs["name"] == "ReelForge"

    analysis = recorded["analysis"]
    datas = analysis.kwargs["datas"]
    # both binaries end up at the bundle root ("." target)
    targets = {src for src, _dst in datas}
    assert any(str(src).endswith("ffmpeg.exe") for src in targets)
    assert any(str(src).endswith("ffprobe.exe") for src in targets)
    assert all(dst == "." for _src, dst in datas if str(_src).endswith(".exe"))

    hidden = analysis.kwargs["hiddenimports"]
    for required in (
        "reelforge.gui.decoy", "reelforge.pipeline", "reelforge.uistate",
        "reelforge.toolchain", "tkinter", "tkinterdnd2",
    ):
        assert required in hidden

    # collect_all was applied to the four requested packages (datas sources)
    all_datas_srcs = {str(src) for src, _ in datas}
    for pkg_name in ("customtkinter", "tkinterdnd2", "PIL", "reelforge"):
        assert pkg_name in all_datas_srcs


def test_spec_skips_missing_ffmpeg(tmp_path):
    """No ffmpeg.exe next to the spec -> spec still builds (no datas entry)."""
    recorded = _exec_spec(tmp_path)
    datas = recorded["analysis"].kwargs["datas"]
    assert not any(str(src).endswith("ffmpeg.exe") for src, _ in datas)


def test_launcher_module_is_importable_and_has_main():
    run_app = _load_run_app()
    assert callable(run_app.main)
    assert callable(run_app.prepare_environment)
