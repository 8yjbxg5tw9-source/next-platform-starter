"""Data model: everything the pipeline, the CLI and the GUI share.

No module in :mod:`reelforge` may import :mod:`reelforge.gui`, so this module
holds *only* plain data types.  That keeps the backend testable without a
display server and keeps the GUI a thin shell around :class:`Pipeline`.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

# --------------------------------------------------------------------------- #
# Enumerations
# --------------------------------------------------------------------------- #


class StrEnum(str, Enum):
    """``str``-backed enum (works on Python 3.8+, ``enum.StrEnum`` is 3.11+)."""

    def __str__(self) -> str:  # pragma: no cover - trivial
        return str(self.value)


class Codec(StrEnum):
    """Video codec used for the final master."""

    H264 = "h264"
    HEVC = "hevc"


class FitMode(StrEnum):
    """How the source is fitted into the target canvas."""

    KEEP = "keep"          # no geometry change at all
    COVER = "cover"        # scale up + centre crop  (fills the frame)
    CONTAIN = "contain"    # scale down + letterbox    (never crops)
    STRETCH = "stretch"    # non-uniform scale         (distorts)


class InterpolationEngineKind(StrEnum):
    """How extra frames are generated."""

    AUTO = "auto"            # prefer RIFE, fall back to minterpolate
    RIFE = "rife"            # external RIFE (rife-ncnn-vulkan / VapourSynth)
    MINTERPOLATE = "minterpolate"  # FFmpeg motion-compensated interpolation
    NONE = "none"            # plain frame-rate conversion (drop/duplicate)


class MotionBlurMode(StrEnum):
    """Cinematic motion blur implementations."""

    OFF = "off"
    TMIX = "tmix"        # tmix  -> temporal average, frame count preserved
    TBLEND = "tblend"    # tblend-> blends neighbours, halves the frame count
    MBLUR = "mblur"      # mblur -> dedicated motion-blur filter (not all builds)


class SharpenMode(StrEnum):
    SHARPEN_OFF = "off"
    CAS = "cas"          # Contrast Adaptive Sharpening (cheap, artefact-safe)
    UNSHARP = "unsharp"  # classic convolution sharpening


class ColorTag(StrEnum):
    """Colour metadata written into the container."""

    BT709 = "bt709"
    BT601 = "bt601"
    BT2020 = "bt2020"


# --------------------------------------------------------------------------- #
# Progress / logging plumbing
# --------------------------------------------------------------------------- #

LogCallback = Callable[[str], None]
ProgressCallback = Callable[["ProgressInfo"], None]


@dataclass
class ProgressInfo:
    """One progress tick, emitted by :class:`reelforge.toolchain.FFmpegRunner`."""

    phase: str = "idle"
    step: int = 0
    total_steps: int = 1
    percent: float = 0.0          # 0..100, overall job progress
    step_percent: float = 0.0     # 0..100, current step progress
    frame: int = 0
    fps: float = 0.0
    speed: float = 0.0            # ffmpeg "speed=1.83x"
    out_time: float = 0.0         # seconds of output produced
    eta_seconds: Optional[float] = None
    message: str = ""

    @property
    def percent_int(self) -> int:
        return max(0, min(100, int(round(self.percent))))


# --------------------------------------------------------------------------- #
# Media probing
# --------------------------------------------------------------------------- #


@dataclass
class StreamInfo:
    """One stream of a media file (video or audio)."""

    index: int
    codec_type: str                     # "video" | "audio"
    codec_name: str = ""
    profile: str = ""
    width: Optional[int] = None
    height: Optional[int] = None
    pix_fmt: str = ""
    fps: Optional[float] = None
    avg_frame_rate: Optional[float] = None
    duration: Optional[float] = None
    bit_rate: Optional[int] = None
    nb_frames: Optional[int] = None
    sample_rate: Optional[int] = None
    channels: Optional[int] = None
    color_primaries: str = ""
    color_transfer: str = ""
    color_space: str = ""
    color_range: str = ""
    is_hdr: bool = False


@dataclass
class MediaInfo:
    """Normalised description of an input file."""

    path: Path
    format_name: str = ""
    duration: float = 0.0
    bit_rate: Optional[int] = None
    size_bytes: int = 0
    streams: List[StreamInfo] = field(default_factory=list)
    probe_backend: str = "unknown"      # "ffprobe" | "ffmpeg"

    # -- convenience accessors ------------------------------------------------
    @property
    def video(self) -> Optional[StreamInfo]:
        for s in self.streams:
            if s.codec_type == "video":
                return s
        return None

    @property
    def audio(self) -> Optional[StreamInfo]:
        for s in self.streams:
            if s.codec_type == "audio":
                return s
        return None

    @property
    def has_audio(self) -> bool:
        return self.audio is not None

    @property
    def fps(self) -> float:
        v = self.video
        if not v:
            return 0.0
        return float(v.fps or v.avg_frame_rate or 0.0)

    @property
    def width(self) -> int:
        return int(self.video.width or 0) if self.video else 0

    @property
    def height(self) -> int:
        return int(self.video.height or 0) if self.video else 0

    @property
    def resolution(self) -> str:
        return f"{self.width}x{self.height}" if self.width else "?"

    @property
    def orientation(self) -> str:
        if not self.width or not self.height:
            return "unknown"
        if self.height > self.width:
            return "vertical"
        if self.width > self.height:
            return "horizontal"
        return "square"

    @property
    def is_hdr(self) -> bool:
        v = self.video
        if not v:
            return False
        if v.is_hdr:
            return True
        return str(v.color_transfer).lower() in {"smpte2084", "arib-std-b67"}

    def summary(self) -> str:
        a = self.audio
        audio = (
            f"{a.codec_name} {a.sample_rate}Hz {a.channels}ch"
            if a
            else "no audio"
        )
        return (
            f"{self.resolution} @ {self.fps:.3f}fps | {self.video.codec_name if self.video else '?'} "
            f"({self.video.pix_fmt if self.video else '?'}) | {audio} | {self.duration:.2f}s"
        )

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["path"] = str(self.path)
        return data


# --------------------------------------------------------------------------- #
# Render targets & options
# --------------------------------------------------------------------------- #


@dataclass
class RenderTarget:
    """One output the pipeline has to produce (e.g. 60 FPS + 120 FPS)."""

    fps: int
    suffix: str
    label: str
    codec: Codec = Codec.H264
    crf: int = 18
    x264_preset: str = "slow"
    profile: str = "high"
    level: str = "4.2"
    gop_seconds: float = 1.0            # GOP length in seconds
    gop_size: Optional[int] = None      # explicit override
    b_frames: int = 2
    tune: Optional[str] = None
    interpolation: InterpolationEngineKind = InterpolationEngineKind.NONE
    oversample: int = 1                 # generate fps*oversample, then blend+decimate
    sharpen: SharpenMode = SharpenMode.CAS
    sharpen_amount: float = 0.7
    motion_blur: MotionBlurMode = MotionBlurMode.OFF
    motion_blur_frames: int = 2
    motion_blur_amount: float = 0.5
    denoise: bool = False
    tonemap_sdr: bool = False           # auto-enabled for HDR sources

    @property
    def gop(self) -> int:
        if self.gop_size:
            return max(1, int(self.gop_size))
        return max(1, int(round(self.fps * self.gop_seconds)))

    def output_name(self, source: Path) -> str:
        return f"{source.stem}__{self.suffix}_{self.fps}fps.mp4"


@dataclass
class JobOptions:
    """User-controlled knobs shared by every render target."""

    output_dir: Optional[Path] = None
    # geometry
    fit: FitMode = FitMode.KEEP
    target_width: Optional[int] = None
    target_height: Optional[int] = None
    scaler: str = "lanczos"
    # interpolation / quality
    interpolation_quality: str = "balanced"   # "fast" | "balanced" | "quality"
    rife_model_dir: Optional[Path] = None     # rife-ncnn-vulkan model folder
    rife_executable: Optional[Path] = None    # override discovery
    # container / colour
    color_tag: ColorTag = ColorTag.BT709
    limited_range: bool = True
    faststart: bool = True
    # audio
    audio_codec: str = "aac"
    audio_bitrate: int = 320            # kbps
    audio_sample_rate: int = 48000
    audio_channels: int = 2
    # preset overrides (GUI/CLI bind straight to these)
    codec: Codec = Codec.H264
    crf_override: Optional[int] = None
    interpolation_override: Optional[InterpolationEngineKind] = None
    fps_override: Optional[int] = None

    # runtime
    threads: int = 0                    # 0 -> let ffmpeg decide
    overwrite: bool = True
    keep_temp: bool = False
    dry_run: bool = False
    dual_output: bool = True            # also render the 60 FPS variant
    verify_output: bool = True
    hwaccel: Optional[str] = None       # "cuda" | "videotoolbox" | ...

    def resolved_output_dir(self, source: Path) -> Path:
        return Path(self.output_dir) if self.output_dir else source.parent

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        for key in ("output_dir", "rife_model_dir", "rife_executable"):
            value = data.get(key)
            data[key] = str(value) if value else None
        return data


# --------------------------------------------------------------------------- #
# Results
# --------------------------------------------------------------------------- #


@dataclass
class VerifyReport:
    """Post-encode QA: did the file really come out the way we asked?"""

    path: Path
    ok: bool = True
    fps: float = 0.0
    expected_fps: float = 0.0
    codec: str = ""
    profile: str = ""
    pix_fmt: str = ""
    color_primaries: str = ""
    keyframe_gaps: List[float] = field(default_factory=list)
    expected_gop: int = 0
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["path"] = str(self.path)
        return data


@dataclass
class RenderOutput:
    path: Path
    target: RenderTarget
    size_bytes: int = 0
    bitrate_kbps: float = 0.0
    command: List[str] = field(default_factory=list)
    verify: Optional[VerifyReport] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": str(self.path),
            "suffix": self.target.suffix,
            "fps": self.target.fps,
            "codec": str(self.target.codec),
            "crf": self.target.crf,
            "gop": self.target.gop,
            "size_bytes": self.size_bytes,
            "bitrate_kbps": round(self.bitrate_kbps, 1),
            "command": self.command,
            "verify": self.verify.to_dict() if self.verify else None,
            "error": self.error,
        }


@dataclass
class JobResult:
    source: Path
    input_info: Optional[MediaInfo]
    outputs: List[RenderOutput] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    finished_at: float = field(default_factory=time.time)
    ok: bool = True
    error: Optional[str] = None
    log_path: Optional[Path] = None
    report_path: Optional[Path] = None

    @property
    def duration(self) -> float:
        return max(0.0, self.finished_at - self.started_at)

    @property
    def succeeded(self) -> List[RenderOutput]:
        return [o for o in self.outputs if o.error is None]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": str(self.source),
            "ok": self.ok,
            "error": self.error,
            "duration_seconds": round(self.duration, 2),
            "input": self.input_info.to_dict() if self.input_info else None,
            "outputs": [o.to_dict() for o in self.outputs],
            "log_path": str(self.log_path) if self.log_path else None,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)


# --------------------------------------------------------------------------- #
# Small helpers used across the package
# --------------------------------------------------------------------------- #


def human_size(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num) < 1024.0:
            return f"{num:3.1f}{unit}"
        num /= 1024.0
    return f"{num:.1f}PB"


def ensure_video_files(paths: Sequence[str | Path]) -> List[Path]:
    """Filter a drag-and-drop payload down to files ffmpeg can plausibly read."""
    exts = {
        ".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".mpg", ".mpeg",
        ".ts", ".m2ts", ".3gp", ".flv", ".wmv", ".gif", ".png", ".jpg",
        ".jpeg", ".hevc", ".h264", ".h265", ".mxf",
    }
    out: List[Path] = []
    for p in paths:
        path = Path(str(p).strip().strip("{}"))   # tkinterdnd2 braces spaces
        if path.is_file() and path.suffix.lower() in exts:
            out.append(path)
    return out
