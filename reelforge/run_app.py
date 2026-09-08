"""ReelForge — single-file launcher (PyInstaller entry point).

Why this file exists
--------------------
When the project is packed into one ``.exe``, Python's normal import and PATH
machinery no longer "just works": the ``reelforge`` package may live inside the
extracted ``sys._MEIPASS`` folder and the bundled ``ffmpeg.exe``/``ffprobe.exe``
are **not** on the system ``PATH``.  This launcher fixes both *before* any
reelforge module is imported:

1. puts the folder(s) that contain the ``reelforge`` package on ``sys.path``;
2. prepends the folders that may hold ``ffmpeg.exe``/``ffprobe.exe`` to
   ``os.environ["PATH"]`` and exports ``REELFORGE_FFMPEG``/``REELFORGE_FFPROBE``
   (which :mod:`reelforge.toolchain` reads first);
3. only then imports and starts the GUI, with a graceful fallback and a log
   file so a headless failure is never silent when ``console=False``.

It works identically from a source checkout (``python run_app.py``) and from a
frozen build, because every path is derived at runtime.
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _candidate_dirs() -> list[Path]:
    """Folders that may contain the ``reelforge`` package *and* ffmpeg."""
    dirs: list[Path] = []
    if _is_frozen():
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            dirs.append(Path(meipass))
        try:
            dirs.append(Path(sys.executable).resolve().parent)
        except (OSError, AttributeError):  # pragma: no cover
            pass
    else:
        # source checkout: run_app.py sits at the project root that *contains*
        # the `reelforge/` package directory
        dirs.append(Path(__file__).resolve().parent)
    # also look one level deeper and in an `ffmpeg/` sub-folder
    for base in list(dirs):
        dirs.append(base / "ffmpeg")
        inner = base / "reelforge"
        if inner.is_dir():
            dirs.append(inner.parent)
    # de-duplicate, keep order
    seen: set[str] = set()
    out: list[Path] = []
    for d in dirs:
        key = str(d)
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out


def _prepare_sys_path(dirs: list[Path]) -> None:
    """Make `import reelforge` resolve even when unpacked from the exe."""
    for base in dirs:
        if (base / "reelforge" / "__init__.py").is_file() or (
            base / "reelforge"
        ).is_dir():
            p = str(base)
            if p not in sys.path:
                sys.path.insert(0, p)


def _prepare_ffmpeg_env(dirs: list[Path]) -> list[Path]:
    """Expose bundled ffmpeg/ffprobe via PATH + explicit env vars."""
    found: dict[str, Path] = {}
    for base in dirs:
        for tool in ("ffmpeg", "ffprobe"):
            if tool in found:
                continue
            for name in (tool, f"{tool}.exe"):
                cand = base / name
                if cand.is_file():
                    found[tool] = cand
                    break

    # explicit env vars win in toolchain.find_executable
    for tool, env in (("ffmpeg", "REELFORGE_FFMPEG"), ("ffprobe", "REELFORGE_FFPROBE")):
        if tool in found and not os.environ.get(env):
            os.environ[env] = str(found[tool])

    # prepend candidate dirs to PATH so subprocess children also see them
    path_dirs = [str(d) for d in dirs]
    existing = os.environ.get("PATH", "")
    os.environ["PATH"] = os.pathsep.join(
        path_dirs + ([existing] if existing else [])
    )
    return [found.get("ffmpeg", Path()), found.get("ffprobe", Path())]


def prepare_environment() -> dict:
    """Public helper (also unit-tested): fix sys.path + ffmpeg env."""
    dirs = _candidate_dirs()
    _prepare_sys_path(dirs)
    bins = _prepare_ffmpeg_env(dirs)
    return {"dirs": dirs, "ffmpeg": bins[0], "ffprobe": bins[1]}


def _log_path() -> Path:
    base = (
        Path(sys.executable).resolve().parent
        if _is_frozen()
        else Path(__file__).resolve().parent
    )
    return base / "reelforge_launch.log"


def main() -> int:
    env = prepare_environment()

    # Headless/`--version`-style probes from a console still work:
    if "--diagnostics" in sys.argv[1:]:
        from reelforge.cli import main as cli_main

        return cli_main(["--diagnostics"])

    log = _log_path()
    try:
        from reelforge.gui.decoy import launch

        return 0 if launch() else 1
    except BaseException as exc:  # noqa: BLE001 - never die silently (console=False)
        detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        try:
            log.write_text(
                f"ffmpeg={env['ffmpeg']}\nffprobe={env['ffprobe']}\n\n{detail}",
                encoding="utf-8",
            )
        except OSError:  # pragma: no cover
            pass
        try:  # best-effort visible error on the user's desktop
            from tkinter import messagebox

            messagebox.showerror(
                "ReelForge",
                f"GUI açıla bilmədi:\n{type(exc).__name__}: {exc}\n\nLog: {log}",
            )
        except Exception:  # pragma: no cover - no display at all
            sys.stderr.write(detail)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
