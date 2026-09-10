"""FFmpeg discovery and media probing.

No shell strings are ever assembled — argument lists and ``pathlib`` paths
keep Unicode filenames (Az/Tr/Ru characters, spaces) safe on every platform.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .config import log


class FFmpegMissing(RuntimeError):
    """Neither a bundled nor a system ffmpeg could be located."""


def find_ffmpeg() -> str:
    env = os.environ.get("AKAI_FFMPEG", "").strip()
    if env and Path(env).exists():
        return env
    located = shutil.which("ffmpeg")
    if located:
        return located
    try:  # bundled static build (pip dependency, works on Windows too)
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:
        raise FFmpegMissing(
            "ffmpeg tapılmadı. AKAI_FFMPEG env dəyişənini təyin edin və ya "
            "pip install imageio-ffmpeg"
        ) from exc


def find_ffprobe() -> Optional[str]:
    located = shutil.which("ffprobe")
    if located:
        return located
    env = os.environ.get("AKAI_FFPROBE", "").strip()
    return env or None


@dataclass
class MediaProbe:
    path: Path
    width: int = 0
    height: int = 0
    fps: float = 0.0
    duration: float = 0.0

    @property
    def summary(self) -> str:
        return (f"{self.path.name} · {self.width}x{self.height} · "
                f"{self.fps:.2f}fps · {self.duration:.1f}s")


def _probe_ffprobe(path: Path, ffprobe: str) -> Optional[MediaProbe]:
    try:
        proc = subprocess.run(
            [ffprobe, "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        if proc.returncode != 0:
            return None
        data = json.loads(proc.stdout or "{}")
        video = next((s for s in data.get("streams", [])
                      if s.get("codec_type") == "video"), None)
        if not video:
            return None
        num, _, den = (video.get("avg_frame_rate", "0/1").partition("/"))
        fps = float(num) / float(den or 1)
        return MediaProbe(
            path=path,
            width=int(video.get("width", 0)),
            height=int(video.get("height", 0)),
            fps=fps,
            duration=float(data.get("format", {}).get("duration", 0) or 0),
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _probe_ffmpeg(path: Path, ffmpeg: str) -> MediaProbe:
    """Fallback parser for builds without ffprobe."""
    probe = MediaProbe(path=path)
    try:
        proc = subprocess.run([ffmpeg, "-hide_banner", "-i", str(path)],
                              capture_output=True, text=True, timeout=30)
        text = (proc.stderr or "") + (proc.stdout or "")
        match = re.search(r"(\d{2,5})x(\d{2,5})", text)
        if match:
            probe.width, probe.height = int(match.group(1)), int(match.group(2))
        fps = re.search(r"(\d+(?:\.\d+)?)\s*fps", text)
        if fps:
            probe.fps = float(fps.group(1))
        dur = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
        if dur:
            probe.duration = (int(dur.group(1)) * 3600 + int(dur.group(2)) * 60
                              + float(dur.group(3)))
    except (OSError, subprocess.SubprocessError):
        pass
    return probe


def probe(path: str | Path) -> MediaProbe:
    """Resolve resolution / fps / duration for the UI and the engine."""
    path = Path(path)
    ffprobe = find_ffprobe()
    if ffprobe:
        parsed = _probe_ffprobe(path, ffprobe)
        if parsed is not None:
            return parsed
    return _probe_ffmpeg(path, find_ffmpeg())


def extract_preview_frame(video: str | Path, out_png: str | Path,
                          at_seconds: float = 1.0) -> bool:
    """Write one decoded frame to ``out_png`` (used by the Preview panel)."""
    try:
        proc = subprocess.run(
            [find_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
             "-ss", f"{at_seconds:.2f}", "-i", str(video),
             "-frames:v", "1", str(out_png)],
            capture_output=True, text=True, timeout=60,
        )
        return proc.returncode == 0 and Path(out_png).exists()
    except (OSError, subprocess.SubprocessError) as exc:
        log().warning("preview frame çıxarılmadı: %s", exc)
        return False


def run_argv(argv: List[str], **popen_kwargs) -> subprocess.Popen:
    """Single spawn point — keeps encoding/flags consistent everywhere."""
    return subprocess.Popen(argv, **popen_kwargs)
