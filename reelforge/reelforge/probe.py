"""Media inspection: ffprobe when present, ``ffmpeg -i`` parsing when not.

Two backends produce the same :class:`~reelforge.models.MediaInfo`:

``ffprobe``
    ``ffprobe -v error -print_format json -show_format -show_streams``
    – authoritative, used whenever the binary exists.
``ffmpeg``
    ``ffmpeg -hide_banner -i <file>`` and parse the human-readable banner –
    the fallback that keeps ReelForge working with stripped-down static builds
    (e.g. the ``imageio-ffmpeg`` wheel) that ship only ``ffmpeg``.

Also provides :func:`keyframe_gaps` and :func:`count_frames`, used by the QA
step that checks the TikTok GOP structure actually made it into the file.
"""

from __future__ import annotations

import json
import re
import subprocess
from fractions import Fraction
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from .models import MediaInfo, StreamInfo
from .toolchain import Toolchain


class ProbeError(RuntimeError):
    """The file could not be inspected at all."""


# --------------------------------------------------------------------------- #
# public API
# --------------------------------------------------------------------------- #


def probe(path: str | Path, toolchain: Toolchain) -> MediaInfo:
    """Inspect ``path`` with the best available backend."""
    path = Path(path)
    if not path.exists():
        raise ProbeError(f"fayl tapılmadı: {path}")
    if not path.is_file():
        raise ProbeError(f"fayl deyil: {path}")

    if toolchain.ffprobe is not None:
        try:
            return _probe_with_ffprobe(path, toolchain)
        except ProbeError:
            if toolchain.ffmpeg is None:  # pragma: no cover - always set
                raise
        # ffprobe present but failed -> fall through to the ffmpeg parser

    return _probe_with_ffmpeg(path, toolchain)


def keyframe_gaps(
    path: str | Path, toolchain: Toolchain, timeout: int = 600
) -> List[float]:
    """Timestamps (seconds) of every keyframe, via ``select+showinfo``."""
    cmd = [
        str(toolchain.ffmpeg), "-hide_banner", "-nostdin", "-nostats",
        "-i", str(path),
        "-map", "0:v:0",
        "-vf", "select='eq(pict_type\\,I)',showinfo",
        "-an", "-f", "null", "-",
    ]
    try:
        proc = subprocess.run(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            text=True, errors="replace", timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ProbeError(f"keyframe analizi alınmadı: {exc}") from exc
    text = proc.stderr or ""
    times: List[float] = []
    for match in re.finditer(r"pts_time:([0-9.]+)", text):
        times.append(float(match.group(1)))
    return times


def count_frames(path: str | Path, toolchain: Toolchain, timeout: int = 900) -> int:
    """Exact decoded frame count of the video stream (``-f null`` decode)."""
    cmd = [
        str(toolchain.ffmpeg), "-hide_banner", "-nostdin",
        "-i", str(path), "-map", "0:v:0", "-f", "null", "-",
    ]
    try:
        proc = subprocess.run(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            text=True, errors="replace", timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ProbeError(f"kadr sayı oxunmadı: {exc}") from exc
    text = proc.stderr or ""
    numbers = [int(n) for n in re.findall(r"frame=\s*(\d+)", text)]
    return max(numbers) if numbers else 0


# --------------------------------------------------------------------------- #
# backend 1: ffprobe JSON
# --------------------------------------------------------------------------- #


def _probe_with_ffprobe(path: Path, toolchain: Toolchain) -> MediaInfo:
    cmd = [
        str(toolchain.ffprobe),
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    try:
        proc = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, errors="replace", timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ProbeError(f"ffprobe işə salınmadı: {exc}") from exc
    if proc.returncode != 0:
        raise ProbeError(f"ffprobe exit {proc.returncode}: {(proc.stderr or '').strip()}")
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise ProbeError(f"ffprobe JSON oxunmadı: {exc}") from exc
    return parse_ffprobe_json(data, path)


def parse_ffprobe_json(data: Dict, path: Path) -> MediaInfo:
    """Pure function: ffprobe JSON -> :class:`MediaInfo` (unit-testable)."""
    fmt = data.get("format") or {}
    streams: List[StreamInfo] = []
    for raw in data.get("streams") or []:
        codec_type = str(raw.get("codec_type", ""))
        if codec_type not in {"video", "audio"}:
            continue
        transfer = str(raw.get("color_transfer", "") or "").lower()
        streams.append(
            StreamInfo(
                index=int(raw.get("index", len(streams))),
                codec_type=codec_type,
                codec_name=str(raw.get("codec_name", "") or ""),
                profile=str(raw.get("profile", "") or ""),
                width=_int(raw.get("width")),
                height=_int(raw.get("height")),
                pix_fmt=str(raw.get("pix_fmt", "") or ""),
                fps=_rate(raw.get("r_frame_rate")) or _rate(raw.get("avg_frame_rate")),
                avg_frame_rate=_rate(raw.get("avg_frame_rate")),
                duration=_float(raw.get("duration")),
                bit_rate=_int(raw.get("bit_rate")),
                nb_frames=_int(raw.get("nb_frames")),
                sample_rate=_int(raw.get("sample_rate")),
                channels=_int(raw.get("channels")),
                color_primaries=str(raw.get("color_primaries", "") or ""),
                color_transfer=str(raw.get("color_transfer", "") or ""),
                color_space=str(raw.get("color_space", "") or ""),
                color_range=str(raw.get("color_range", "") or ""),
                is_hdr=transfer in {"smpte2084", "arib-std-b67"},
            )
        )

    size = _int(fmt.get("size"))
    if size is None:
        try:
            size = path.stat().st_size
        except OSError:  # pragma: no cover
            size = 0

    info = MediaInfo(
        path=path,
        format_name=str(fmt.get("format_name", "") or ""),
        duration=_float(fmt.get("duration")) or _max_stream_duration(streams),
        bit_rate=_int(fmt.get("bit_rate")),
        size_bytes=size or 0,
        streams=streams,
        probe_backend="ffprobe",
    )
    if not info.video:
        raise ProbeError(f"video stream tapılmadı: {path}")
    return info


def _max_stream_duration(streams: Sequence[StreamInfo]) -> float:
    durations = [s.duration for s in streams if s.duration]
    return max(durations) if durations else 0.0


# --------------------------------------------------------------------------- #
# backend 2: ffmpeg -i banner parsing
# --------------------------------------------------------------------------- #

_RE_DURATION = re.compile(
    r"Duration:\s*(?P<h>\d+):(?P<m>\d+):(?P<s>\d+(?:\.\d+)?)", re.I
)
_RE_FORMAT_BITRATE = re.compile(r"Duration:.*?bitrate:\s*(\d+)\s*kb/s", re.I)
_RE_STREAM = re.compile(
    r"Stream\s+#(?P<idx>\d+):(?P<sub>\d+).*?:\s*(?P<type>Video|Audio):\s*(?P<rest>.*)$"
)
_RE_SIZE = re.compile(r"(\d{2,5})x(\d{2,5})")
_RE_FPS = re.compile(r"(?P<fps>\d+(?:\.\d+)?)\s+fps")
_RE_TBR = re.compile(r"(?P<tbr>\d+(?:\.\d+)?)\s+tbr")
_RE_KBPS = re.compile(r"(?P<kbps>\d+)\s+kb/s")
_RE_SAMPLE = re.compile(r"(?P<sr>\d{3,6})\s+Hz")
_RE_CHANNELS = re.compile(
    r"\b(?P<ch>\d+)\s+channels?\b|\b(?P<mono>mono)\b|\b(?P<stereo>stereo)\b", re.I
)
_RE_PIXFMT = re.compile(
    r"\b(yuv\d+p\d*(?:le|be)?|nv12|nv16|nv21|rgb24|rgba|bgr24|gray10le|yuvj420p)\b"
)
_RE_COLOR = re.compile(
    r"(?P<pix>yuv\w+|nv\d+|rgb\w+)?\s*(?:\((?P<tags>[^)]*)\))?"
)
_RE_VIDEO_CODECS = re.compile(
    r"^(?P<codec>[a-z0-9_]+)\s*(?:\((?P<profile>[^)]*)\))?", re.I
)
_RE_AUDIO_CODECS = re.compile(r"^(?P<codec>[a-z0-9_]+)", re.I)


def _probe_with_ffmpeg(path: Path, toolchain: Toolchain) -> MediaInfo:
    cmd = [str(toolchain.ffmpeg), "-hide_banner", "-nostdin", "-i", str(path)]
    try:
        proc = subprocess.run(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            text=True, errors="replace", timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ProbeError(f"ffmpeg işə salınmadı: {exc}") from exc
    return parse_ffmpeg_banner(proc.stderr or "", path)


def parse_ffmpeg_banner(banner: str, path: Path) -> MediaInfo:
    """Pure function: ``ffmpeg -i`` stderr -> :class:`MediaInfo`."""
    if "Invalid data" in banner and "Stream" not in banner:
        raise ProbeError(f"ffmpeg faylı oxuya bilmədi: {path}")

    duration = 0.0
    m = _RE_DURATION.search(banner)
    if m:
        duration = (
            int(m.group("h")) * 3600 + int(m.group("m")) * 60 + float(m.group("s"))
        )
    bit_rate: Optional[int] = None
    mb = _RE_FORMAT_BITRATE.search(banner)
    if mb:
        bit_rate = int(mb.group(1)) * 1000

    streams: List[StreamInfo] = []
    for line in banner.splitlines():
        sm = _RE_STREAM.search(line.strip())
        if not sm:
            continue
        kind = sm.group("type")
        rest = sm.group("rest")
        index = int(sm.group("idx")) * 100 + int(sm.group("sub"))

        if kind == "Video":
            streams.append(_parse_video_stream(index, rest))
        else:
            streams.append(_parse_audio_stream(index, rest))

    try:
        size = path.stat().st_size
    except OSError:  # pragma: no cover
        size = 0

    info = MediaInfo(
        path=path,
        format_name=path.suffix.lstrip(".").lower(),
        duration=duration,
        bit_rate=bit_rate,
        size_bytes=size,
        streams=streams,
        probe_backend="ffmpeg",
    )
    if not info.video:
        raise ProbeError(f"video stream tapılmadı (ffmpeg banner): {path}")
    return info


def _parse_video_stream(index: int, rest: str) -> StreamInfo:
    codec_m = _RE_VIDEO_CODECS.match(rest)
    codec = codec_m.group("codec") if codec_m else ""
    profile = (codec_m.group("profile") or "") if codec_m else ""

    size_m = _RE_SIZE.search(rest)
    width = int(size_m.group(1)) if size_m else None
    height = int(size_m.group(2)) if size_m else None

    fps_m = _RE_FPS.search(rest)
    fps = float(fps_m.group("fps")) if fps_m else None
    if fps is None:
        tbr_m = _RE_TBR.search(rest)
        fps = float(tbr_m.group("tbr")) if tbr_m else None

    pix_m = _RE_PIXFMT.search(rest)
    pix_fmt = pix_m.group(1) if pix_m else ""

    kbps_m = _RE_KBPS.search(rest)
    bit_rate = int(kbps_m.group("kbps")) * 1000 if kbps_m else None

    # colour tags appear inside parentheses after the pixel format, e.g.
    # "yuv420p(tv, bt709, progressive)"
    primaries = transfer = space = rng = ""
    paren = re.search(r"\(([^)]*)\)", rest[pix_m.end():] if pix_m else rest)
    if paren:
        for tag in [t.strip().lower() for t in paren.group(1).split(",")]:
            if tag in {"tv", "mpeg"}:
                rng = "tv"
            elif tag in {"pc", "jpeg"}:
                rng = "pc"
            elif tag in {"bt709", "bt601", "bt2020", "smpte170m"}:
                primaries = primaries or ("smpte170m" if tag == "smpte170m" else tag)
                space = space or tag
            elif tag in {"bt2020-10", "smpte2084", "arib-std-b67"}:
                transfer = tag

    return StreamInfo(
        index=index,
        codec_type="video",
        codec_name=codec,
        profile=profile,
        width=width,
        height=height,
        pix_fmt=pix_fmt,
        fps=fps,
        avg_frame_rate=fps,
        bit_rate=bit_rate,
        color_primaries=primaries,
        color_transfer=transfer,
        color_space=space,
        color_range=rng,
        is_hdr=transfer in {"smpte2084", "arib-std-b67"},
    )


def _parse_audio_stream(index: int, rest: str) -> StreamInfo:
    codec_m = _RE_AUDIO_CODECS.match(rest)
    codec = codec_m.group("codec") if codec_m else ""
    sr_m = _RE_SAMPLE.search(rest)
    ch_m = _RE_CHANNELS.search(rest)
    channels: Optional[int] = None
    if ch_m:
        if ch_m.group("ch"):
            channels = int(ch_m.group("ch"))
        elif ch_m.group("mono"):
            channels = 1
        elif ch_m.group("stereo"):
            channels = 2
    kbps_m = _RE_KBPS.search(rest)
    return StreamInfo(
        index=index,
        codec_type="audio",
        codec_name=codec,
        sample_rate=int(sr_m.group("sr")) if sr_m else None,
        channels=channels,
        bit_rate=int(kbps_m.group("kbps")) * 1000 if kbps_m else None,
    )


# --------------------------------------------------------------------------- #
# small numeric helpers
# --------------------------------------------------------------------------- #


def _rate(value) -> Optional[float]:
    """``"60000/1001"`` / ``"60"`` / ``60.0`` -> float fps (``None`` if 0)."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value) or None
    text = str(value).strip()
    if not text:
        return None
    try:
        if "/" in text:
            frac = Fraction(text)
            return float(frac) if frac else None
        return float(text) or None
    except (ValueError, ZeroDivisionError):
        return None


def _int(value) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(str(value).strip())
    except ValueError:
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None


def _float(value) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
