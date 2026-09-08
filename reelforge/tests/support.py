"""Helpers for unit tests that must not depend on a real ffmpeg binary."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional

from reelforge.models import MediaInfo, StreamInfo
from reelforge.toolchain import Toolchain

DEFAULT_FILTERS = {
    "scale", "pad", "crop", "fps", "format", "setparams", "setsar",
    "minterpolate", "tmix", "tblend", "cas", "unsharp", "zscale", "tonemap",
}
DEFAULT_ENCODERS = {"libx264", "libx265", "aac"}


def make_info(
    fps: float = 30.0,
    width: int = 1080,
    height: int = 1920,
    *,
    audio: bool = True,
    hdr: bool = False,
    pix_fmt: str = "yuv420p",
    duration: float = 4.0,
) -> MediaInfo:
    streams = [
        StreamInfo(
            index=0, codec_type="video", codec_name="h264", profile="High",
            width=width, height=height, pix_fmt=pix_fmt, fps=fps,
            avg_frame_rate=fps, nb_frames=int(fps * duration), duration=duration,
            color_transfer="smpte2084" if hdr else "",
            is_hdr=hdr,
        )
    ]
    if audio:
        streams.append(
            StreamInfo(index=1, codec_type="audio", codec_name="aac",
                       sample_rate=48000, channels=2)
        )
    return MediaInfo(path=__file__, duration=duration, streams=streams)


def make_toolchain(
    *,
    filters: Optional[Iterable[str]] = None,
    encoders: Optional[Iterable[str]] = None,
    major: int = 7,
    minor: int = 0,
    ffprobe: Optional[Path] = None,
    ffmpeg: Path = Path("/usr/local/bin/ffmpeg"),
) -> Toolchain:
    return Toolchain(
        ffmpeg=ffmpeg,
        ffprobe=ffprobe,
        version=f"{major}.{minor}.2",
        major=major,
        minor=minor,
        filters=set(DEFAULT_FILTERS if filters is None else filters),
        encoders=set(DEFAULT_ENCODERS if encoders is None else encoders),
    )
