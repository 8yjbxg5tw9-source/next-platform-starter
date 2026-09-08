"""FFmpeg discovery, capability probing and the subprocess runner.

Everything that touches the OS lives here so the rest of the package stays
pure and unit-testable:

* :func:`find_toolchain`  – locate ``ffmpeg`` / ``ffprobe`` (PATH, common
  install prefixes, or a bundled wheel such as ``imageio-ffmpeg``).
* :class:`Toolchain`      – cached facts about that build: version, available
  filters and encoders.  Presets degrade gracefully based on this.
* :class:`FFmpegRunner`   – runs one command, parses ``-progress pipe:1``
  into :class:`~reelforge.models.ProgressInfo`, streams stderr into a log
  file / GUI callback and honours a cancellation event.
"""

from __future__ import annotations

import collections
import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Deque, Dict, List, Optional, Sequence, Set

from .models import ProgressCallback, ProgressInfo


class ToolchainError(RuntimeError):
    """Raised when a usable ffmpeg build cannot be found."""


# --------------------------------------------------------------------------- #
# discovery
# --------------------------------------------------------------------------- #

_COMMON_PATHS = (
    "/usr/local/bin",
    "/usr/bin",
    "/opt/homebrew/bin",
    "/usr/local/bin",
    "/snap/bin",
    r"C:\ffmpeg\bin",
    r"C:\Program Files\ffmpeg\bin",
)


def _from_bundled_wheel(name: str) -> Optional[Path]:
    """Look inside optional pip packages that ship a static ffmpeg binary."""
    if name != "ffmpeg":
        return None
    try:  # imageio-ffmpeg wheels carry a ready-to-run static build
        import imageio_ffmpeg  # type: ignore

        exe = Path(imageio_ffmpeg.get_ffmpeg_exe())
        if exe.exists():
            return exe
    except Exception:  # pragma: no cover - optional dependency
        pass
    return None


def find_executable(name: str, override: Optional[str | os.PathLike] = None) -> Optional[Path]:
    """Resolve ``ffmpeg``/``ffprobe`` to an absolute path, or ``None``."""
    if override:
        cand = Path(override).expanduser()
        if cand.exists():
            return cand.resolve()
        found = shutil.which(str(cand))
        return Path(found).resolve() if found else None

    env_key = f"REELFORGE_{name.upper()}"
    env_val = os.environ.get(env_key) or os.environ.get(name.upper())
    if env_val:
        found = shutil.which(env_val) or (env_val if Path(env_val).exists() else None)
        if found:
            return Path(found).resolve()

    found = shutil.which(name)
    if found:
        return Path(found).resolve()

    for directory in _COMMON_PATHS:
        cand = Path(directory) / (f"{name}.exe" if os.name == "nt" else name)
        if cand.exists():
            return cand.resolve()

    bundled = _from_bundled_wheel(name)
    if bundled:
        return bundled

    return None


# --------------------------------------------------------------------------- #
# toolchain description
# --------------------------------------------------------------------------- #

_VERSION_RE = re.compile(r"ffmpeg version\s+(n?)(\d+)\.(\d+)(?:\.(\d+))?", re.I)

# Filter list lines look like:   " TSC cas      V->V   Contrast Adaptive Sharpen."
#   col1 = timeline, col2 = slice threading, col3 = command support
_FILTER_RE = re.compile(r"^\s*[TSC\.][S\.][C\.]\s+(\S+)\s+")

# Encoder list lines look like:  " V....D libx264   libx264 H.264 / AVC ..."
#   col1 = V/A/S/O  col2 = frame threading  col3 = slice threading
#   col4 = experimental  col5 = draw_horiz_band  col6 = direct rendering
_ENCODER_RE = re.compile(r"^\s*[VASO\.][F\.][S\.][X\.][B\.][D\.]\s+(\S+)\s+")


@dataclass
class Toolchain:
    """What the local ffmpeg build can actually do."""

    ffmpeg: Path
    ffprobe: Optional[Path] = None
    version: str = ""
    major: int = 0
    minor: int = 0
    filters: Set[str] = field(default_factory=set)
    encoders: Set[str] = field(default_factory=set)

    # -- feature flags --------------------------------------------------------
    def has_filter(self, name: str) -> bool:
        return name in self.filters

    def has_encoder(self, name: str) -> bool:
        return name in self.encoders

    @property
    def has_ffprobe(self) -> bool:
        return self.ffprobe is not None

    @property
    def supports_fps_mode(self) -> bool:
        """``-fps_mode`` replaced ``-vsync`` in FFmpeg 5.1."""
        return (self.major, self.minor) >= (5, 1) or self.major == 0

    @property
    def supports_cas(self) -> bool:
        return self.has_filter("cas")

    @property
    def supports_mblur(self) -> bool:
        return self.has_filter("mblur")

    @property
    def supports_zscale(self) -> bool:
        return self.has_filter("zscale") and self.has_filter("tonemap")

    @property
    def supports_hevc(self) -> bool:
        return self.has_encoder("libx265")

    def describe(self) -> str:
        bits = [
            f"ffmpeg {self.version or '?'} @ {self.ffmpeg}",
            f"ffprobe: {self.ffprobe or 'not found (using ffmpeg -i fallback)'}",
            f"filters: {len(self.filters)} | encoders: {len(self.encoders)}",
            f"libx264={self.has_encoder('libx264')} libx265={self.supports_hevc} "
            f"minterpolate={self.has_filter('minterpolate')} tmix={self.has_filter('tmix')} "
            f"cas={self.supports_cas} mblur={self.supports_mblur} zscale={self.supports_zscale}",
        ]
        return "\n".join(bits)


def _run_capture(cmd: Sequence[str], timeout: int = 60) -> str:
    try:
        proc = subprocess.run(
            list(cmd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            text=True,
            errors="replace",
        )
    except (OSError, subprocess.SubprocessError) as exc:  # pragma: no cover
        raise ToolchainError(f"could not execute {cmd[0]}: {exc}") from exc
    return proc.stdout or ""


def _parse_filters(text: str) -> Set[str]:
    out: Set[str] = set()
    for line in text.splitlines():
        m = _FILTER_RE.match(line)
        if m:
            name = m.group(1)
            if "=" not in name and "->" not in name:
                out.add(name)
    return out


def _parse_encoders(text: str) -> Set[str]:
    out: Set[str] = set()
    for line in text.splitlines():
        m = _ENCODER_RE.match(line)
        if m:
            name = m.group(1)
            if "=" not in name:      # skips the legend lines ("V..... = Video")
                out.add(name)
    return out


def find_toolchain(
    ffmpeg: Optional[str | os.PathLike] = None,
    ffprobe: Optional[str | os.PathLike] = None,
    *,
    probe_capabilities: bool = True,
) -> Toolchain:
    """Build a :class:`Toolchain`, raising :class:`ToolchainError` if unusable."""
    ffmpeg_path = find_executable("ffmpeg", ffmpeg)
    if ffmpeg_path is None:
        raise ToolchainError(
            "ffmpeg tapılmadı. Qurulum: https://ffmpeg.org/download.html "
            "(Windows: winget install Gyan.FFmpeg · macOS: brew install ffmpeg). "
            "Alternativ: REELFORGE_FFMPEG=/path/to/ffmpeg"
        )
    ffprobe_path = find_executable("ffprobe", ffprobe)

    tc = Toolchain(ffmpeg=ffmpeg_path, ffprobe=ffprobe_path)
    banner = _run_capture([str(ffmpeg_path), "-hide_banner", "-version"])
    m = _VERSION_RE.search(banner)
    if m:
        tc.major = int(m.group(2))
        tc.minor = int(m.group(3))
        tc.version = m.group(0).split("version", 1)[1].strip()

    if probe_capabilities:
        tc.filters = _parse_filters(
            _run_capture([str(ffmpeg_path), "-hide_banner", "-filters"])
        )
        tc.encoders = _parse_encoders(
            _run_capture([str(ffmpeg_path), "-hide_banner", "-encoders"])
        )
    return tc


# --------------------------------------------------------------------------- #
# runner
# --------------------------------------------------------------------------- #


class FFmpegError(RuntimeError):
    """A subprocess failed; ``tail`` holds the last stderr lines."""

    def __init__(self, message: str, command: Sequence[str], tail: Sequence[str]):
        super().__init__(message)
        self.command = list(command)
        self.tail = list(tail)


class Cancelled(RuntimeError):
    """The user pressed Cancel."""


_PROGRESS_KEYS = {
    "frame", "fps", "speed", "out_time_ms", "out_time_us", "out_time",
    "progress", "total_size", "bitrate", "dup_frames", "drop_frames",
}


def _time_to_seconds(value: str) -> float:
    """``00:00:12.34`` or ``12.34`` -> 12.34"""
    value = value.strip()
    if not value or value.lower() in {"n/a"}:
        return 0.0
    if ":" not in value:
        try:
            return float(value)
        except ValueError:
            return 0.0
    total = 0.0
    for part in value.split(":"):
        try:
            total = total * 60.0 + float(part)
        except ValueError:
            return 0.0
    return total


@dataclass
class RunResult:
    returncode: int
    duration: float
    stderr_tail: List[str]
    cancelled: bool = False
    frames: int = 0


class FFmpegRunner:
    """Executes ffmpeg with live progress + cancellation.

    ``log_path`` receives the *complete* stderr of every command, which is what
    the GUI's console shows and what the JSON report links to.
    """

    def __init__(
        self,
        ffmpeg: Path,
        log_path: Optional[Path] = None,
        log_callback: Optional[object] = None,
        tail_size: int = 80,
    ) -> None:
        self.ffmpeg = Path(ffmpeg)
        self.log_path = Path(log_path) if log_path else None
        self.log_callback = log_callback
        self.tail: Deque[str] = collections.deque(maxlen=tail_size)
        self._log_fh = None
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            self._log_fh = open(self.log_path, "a", encoding="utf-8", errors="replace")

    # -- lifecycle ------------------------------------------------------------
    def close(self) -> None:
        if self._log_fh:
            try:
                self._log_fh.close()
            finally:
                self._log_fh = None

    def __enter__(self) -> "FFmpegRunner":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- logging --------------------------------------------------------------
    def log(self, line: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        text = f"[{stamp}] {line}"
        self.tail.append(text)
        if self._log_fh:
            self._log_fh.write(text + "\n")
            self._log_fh.flush()
        if callable(self.log_callback):
            try:
                self.log_callback(text)
            except Exception:  # pragma: no cover - GUI must never break the job
                pass

    def log_command(self, command: Sequence[str]) -> None:
        self.log("$ " + " ".join(_quote(a) for a in command))

    # -- the actual run -------------------------------------------------------
    def run(
        self,
        command: Sequence[str],
        *,
        expected_duration: float = 0.0,
        phase: str = "encode",
        step: int = 0,
        total_steps: int = 1,
        progress: Optional[ProgressCallback] = None,
        cancel: Optional[threading.Event] = None,
        echo_command: bool = True,
    ) -> RunResult:
        """Run one ffmpeg command; raise :class:`FFmpegError` on failure."""
        argv = [str(a) for a in command]
        if echo_command:
            self.log_command(argv)

        started = time.time()
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

        reader = threading.Thread(
            target=self._drain_stderr, args=(proc,), name="ffmpeg-stderr", daemon=True
        )
        reader.start()

        cancelled = False
        last_emit = 0.0
        state = {"frame": 0, "fps": 0.0, "speed": 0.0}
        assert proc.stdout is not None
        try:
            for raw in proc.stdout:
                if cancel is not None and cancel.is_set():
                    cancelled = True
                    self._terminate(proc)
                    break
                key, _, value = raw.partition("=")
                key = key.strip()
                value = value.strip()
                if key not in _PROGRESS_KEYS:
                    continue
                if key == "frame":
                    state["frame"] = _to_int(value)
                elif key == "fps":
                    state["fps"] = _to_float(value)
                elif key == "speed":
                    state["speed"] = _to_float(value.rstrip("x"))
                if key == "out_time_us":
                    out_time = _micros_to_seconds(value)
                elif key == "out_time":
                    out_time = _time_to_seconds(value)
                else:
                    continue
                now = time.time()
                if progress is not None and (now - last_emit) >= 0.12:
                    last_emit = now
                    progress(
                        self._make_progress(
                            phase=phase,
                            step=step,
                            total_steps=total_steps,
                            out_time=out_time,
                            expected=expected_duration,
                            started=started,
                            raw=raw,
                            state=state,
                        )
                    )
        finally:
            proc.wait()
            reader.join(timeout=5)

        elapsed = time.time() - started
        tail = list(self.tail)
        if cancelled:
            self.log(f"ləğv edildi ({phase})")
            raise Cancelled(f"cancelled during {phase}")
        if proc.returncode != 0:
            raise FFmpegError(
                f"ffmpeg failed ({phase}) with exit code {proc.returncode}: "
                + " | ".join([l for l in tail[-6:] if l.strip()]),
                command=argv,
                tail=tail,
            )
        return RunResult(proc.returncode, elapsed, tail)

    # -- internals ------------------------------------------------------------
    def _drain_stderr(self, proc: subprocess.Popen) -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            line = line.rstrip("\n")
            if not line.strip():
                continue
            # ffmpeg prints banner/filter info here; keep it, the GUI wants it.
            self.tail.append(line)
            if self._log_fh:
                try:
                    self._log_fh.write(line + "\n")
                    self._log_fh.flush()
                except ValueError:  # pragma: no cover - closed during shutdown
                    return
            if callable(self.log_callback) and _is_interesting(line):
                try:
                    self.log_callback(line)
                except Exception:  # pragma: no cover
                    pass

    def _make_progress(
        self,
        *,
        phase: str,
        step: int,
        total_steps: int,
        out_time: float,
        expected: float,
        started: float,
        raw: str,
        state: Optional[Dict[str, float]] = None,
    ) -> ProgressInfo:
        state = state or {}
        step_percent = 0.0
        if expected > 0:
            step_percent = min(100.0, out_time / expected * 100.0)
        total_steps = max(1, total_steps)
        percent = ((max(0, step - 1) + step_percent / 100.0) / total_steps) * 100.0
        eta: Optional[float] = None
        elapsed = max(0.001, time.time() - started)
        if step_percent > 0.5:
            eta = max(0.0, (elapsed / step_percent) * (100.0 - step_percent))
        return ProgressInfo(
            phase=phase,
            step=step,
            total_steps=total_steps,
            percent=percent,
            step_percent=step_percent,
            frame=int(state.get("frame", 0) or 0),
            fps=float(state.get("fps", 0.0) or 0.0),
            speed=float(state.get("speed", 0.0) or 0.0),
            out_time=out_time,
            eta_seconds=eta,
            message=raw.strip(),
        )

    @staticmethod
    def _terminate(proc: subprocess.Popen) -> None:
        try:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:  # pragma: no cover
                proc.kill()
                proc.wait(timeout=5)
        except OSError:  # pragma: no cover - already dead
            pass


def _micros_to_seconds(value: str) -> float:
    try:
        return float(value) / 1_000_000.0
    except ValueError:
        return 0.0


def _to_int(value: str) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _to_float(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _is_interesting(line: str) -> bool:
    """Filter out ffmpeg's per-frame noise from the GUI console."""
    noise = ("frame=", "size=", "bitrate=", "Lsize=", "Stream mapping", "Metadata:")
    return not line.startswith(noise)


def _quote(arg: str) -> str:
    if any(c in arg for c in " \"'\\"):
        return "'" + arg.replace("'", "'\\''") + "'"
    return arg


def ffmpeg_version_tuple(tc: Toolchain) -> Dict[str, int]:
    return {"major": tc.major, "minor": tc.minor}
