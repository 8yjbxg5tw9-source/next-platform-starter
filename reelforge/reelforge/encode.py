"""Command-line construction for the encode step.

This module owns the *anti-compression* part of the pipeline: codec, profile,
CRF, fixed GOP, pixel format, colour tagging, audio and container flags.  It
returns a plain ``argv`` list — nothing is executed here, so the exact command
can be inspected, logged, unit-tested or copy-pasted into a shell.

Canonical output (H.264, TikTok-safe):

.. code-block:: text

    ffmpeg -hide_banner -nostdin -nostats -y \
      -i input.mp4 -map 0:v:0 -map 0:a:0? \
      -vf "fps=60:round=near,cas=strength=0.5,format=yuv420p,
           setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv" \
      -fps_mode cfr -r 60 \
      -c:v libx264 -preset slow -profile:v high -level 4.2 -pix_fmt yuv420p -crf 17 \
      -g 60 -keyint_min 60 -sc_threshold 0 -bf 2 -tune film \
      -x264-params keyint=60:min-keyint=60:scenecut=0 \
      -color_primaries bt709 -color_trc bt709 -colorspace bt709 -color_range tv \
      -c:a aac -b:a 320k -ar 48000 -ac 2 \
      -movflags +faststart -max_muxing_queue_size 1024 -sn -dn output.mp4
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence

from .models import Codec, JobOptions, RenderTarget
from .toolchain import Toolchain

#: AAC-LC is capped at 6144 bits per frame; anything above that gets clamped
#: by the encoder with a warning.  6144 bits/frame * sr / 1024 = 6 * sr.
AAC_MAX_BITS_PER_FRAME = 6144
AAC_FRAME_SIZE = 1024


class EncodeError(ValueError):
    """The requested codec is not available in this build."""


@dataclass
class EncodePlan:
    command: List[str]
    notes: List[str] = field(default_factory=list)
    expected_duration: float = 0.0


def aac_max_bitrate_kbps(sample_rate: int) -> int:
    """Highest AAC-LC bitrate the encoder will actually honour at ``sr``."""
    return (AAC_MAX_BITS_PER_FRAME * int(sample_rate)) // (AAC_FRAME_SIZE * 1000)


def build_encode_plan(
    *,
    ffmpeg: Path,
    video_input: str,
    video_input_args: Sequence[str] = (),
    audio_input: Optional[Path] = None,
    output: Path,
    target: RenderTarget,
    opts: JobOptions,
    toolchain: Toolchain,
    video_filter: Optional[str] = None,
    has_audio: bool = True,
    expected_duration: float = 0.0,
) -> EncodePlan:
    """Assemble the full encode command for one render target."""
    notes: List[str] = []
    cmd: List[str] = [
        str(ffmpeg),
        "-hide_banner",
        "-nostdin",
        "-nostats",
        "-progress", "pipe:1",
        "-y" if opts.overwrite else "-n",
    ]

    if opts.hwaccel:
        cmd += ["-hwaccel", str(opts.hwaccel)]

    # ---- inputs -----------------------------------------------------------
    cmd += list(video_input_args)
    cmd += ["-i", str(video_input)]
    audio_is_second_input = False
    if has_audio and audio_input is not None:
        cmd += ["-i", str(audio_input)]
        audio_is_second_input = True

    # ---- stream selection -------------------------------------------------
    cmd += ["-map", "0:v:0"]
    if has_audio:
        cmd += ["-map", "1:a:0?" if audio_is_second_input else "0:a:0?"]
    else:
        cmd += ["-an"]
    cmd += ["-sn", "-dn"]

    # ---- filters ----------------------------------------------------------
    if video_filter:
        cmd += ["-vf", video_filter]

    # ---- constant frame rate ---------------------------------------------
    if toolchain.supports_fps_mode:
        cmd += ["-fps_mode", "cfr"]
    else:  # FFmpeg < 5.1
        cmd += ["-vsync", "cfr"]
    cmd += ["-r", _rate(target.fps)]

    # ---- video codec ------------------------------------------------------
    cmd += _video_codec_args(target, toolchain, notes)

    # ---- colour metadata --------------------------------------------------
    tag = str(opts.color_tag or "bt709")
    cmd += [
        "-color_primaries", tag,
        "-color_trc", tag,
        "-colorspace", tag,
    ]
    if opts.limited_range:
        cmd += ["-color_range", "tv"]

    # ---- audio ------------------------------------------------------------
    if has_audio:
        cmd += _audio_args(opts, notes)

    # ---- container --------------------------------------------------------
    if opts.faststart:
        cmd += ["-movflags", "+faststart"]
    cmd += ["-max_muxing_queue_size", "1024"]
    if opts.threads:
        cmd += ["-threads", str(int(opts.threads))]

    cmd += [str(output)]
    return EncodePlan(command=cmd, notes=notes, expected_duration=expected_duration)


# --------------------------------------------------------------------------- #
# codec specifics
# --------------------------------------------------------------------------- #


def _video_codec_args(target: RenderTarget, toolchain: Toolchain, notes: List[str]) -> List[str]:
    gop = target.gop
    if target.codec == Codec.NVENC:
        return _nvenc_args(target, toolchain, notes, gop)
    if target.codec == Codec.HEVC:
        if not toolchain.supports_hevc:
            raise EncodeError(
                "libx265 (HEVC) bu ffmpeg build-də yoxdur — H.264 seçin."
            )
        args = [
            "-c:v", "libx265",
            "-preset", target.x264_preset,
            "-profile:v", target.profile,
            "-level:v", target.level,
            "-pix_fmt", "yuv420p",
            "-crf", str(target.crf),
            "-g", str(gop),
            "-keyint_min", str(gop),
            "-sc_threshold", "0",
            "-tag:v", "hvc1",          # required for QuickTime/Safari playback
            "-x265-params", f"keyint={gop}:min-keyint={gop}:scenecut=0:log-level=error",
        ]
        if target.b_frames >= 0:
            args += ["-bf", str(target.b_frames)]
        if target.tune:
            args += ["-tune", target.tune]
        args += _rate_control_args(target, notes)
        notes.append(
            f"HEVC/HEVC(hvc1) CRF {target.crf} · GOP {gop} ({gop / max(1, target.fps):.2f}s)"
        )
        return args

    if not toolchain.has_encoder("libx264"):
        raise EncodeError("libx264 bu ffmpeg build-də yoxdur.")

    args = [
        "-c:v", "libx264",
        "-preset", target.x264_preset,
        "-profile:v", target.profile,
        "-level:v", target.level,
        "-pix_fmt", "yuv420p",
        "-crf", str(target.crf),
        "-g", str(gop),
        "-keyint_min", str(gop),
        "-sc_threshold", "0",
    ]
    if target.b_frames >= 0:
        args += ["-bf", str(target.b_frames)]
    if target.tune:
        args += ["-tune", target.tune]
    # belt and braces: x264's own parser is authoritative for scenecut
    args += [
        "-x264-params",
        f"keyint={gop}:min-keyint={gop}:scenecut=0",
    ]
    args += _rate_control_args(target, notes)
    notes.append(
        f"H.264 {target.profile}@{target.level} CRF {target.crf} "
        f"({target.x264_preset}) · GOP {gop} = {gop / max(1, target.fps):.2f}s sabit"
    )
    return args


def _rate_control_args(target: RenderTarget, notes: List[str]) -> List[str]:
    """Optional VBV ceiling (Studio tier) — keeps bitrate high but bounded."""
    args: List[str] = []
    if target.maxrate_kbps:
        args += ["-maxrate", f"{int(target.maxrate_kbps)}k"]
    if target.bufsize_kbps:
        args += ["-bufsize", f"{int(target.bufsize_kbps)}k"]
    if args:
        notes.append(
            f"VBV tavanı: maxrate {int(target.maxrate_kbps or 0)}k / "
            f"bufsize {int(target.bufsize_kbps or 0)}k"
        )
    return args


#: x264 preset name -> NVENC preset (FFmpeg 5+ uses p1..p7)
_NVENC_PRESET_MAP = {
    "ultrafast": "p1", "superfast": "p2", "veryfast": "p2", "faster": "p3",
    "fast": "p4", "medium": "p5", "slow": "p6", "slower": "p7",
    "veryslow": "p7", "placebo": "p7",
}


def _nvenc_args(target: RenderTarget, toolchain: Toolchain, notes: List[str], gop: int) -> List[str]:
    """NVIDIA hardware path: ``hevc_nvenc`` when present, else ``h264_nvenc``."""
    if toolchain.has_encoder("hevc_nvenc"):
        encoder, profile, tag = "hevc_nvenc", "main", ["-tag:v", "hvc1"]
    elif toolchain.has_encoder("h264_nvenc"):
        encoder, profile, tag = "h264_nvenc", "high", []
    else:
        raise EncodeError(
            "NVENC tapılmadı (hevc_nvenc/h264_nvenc yoxdur) — NVIDIA sürücüsü "
            "və NVENC dəstəkli ffmpeg lazımdır, ya da H.264 seçin."
        )

    if toolchain.major >= 5:
        preset = _NVENC_PRESET_MAP.get(target.x264_preset, "p6")
    else:  # legacy nvenc preset names
        preset = "slow" if target.x264_preset in {"slow", "slower", "veryslow"} else "fast"

    args = [
        "-c:v", encoder,
        "-preset", preset,
        "-tune", "hq",
        "-rc", "vbr",
        "-cq", str(target.crf),
        "-b:v", "0",                    # quality-driven, no bitrate target
        "-profile:v", profile,
        "-pix_fmt", "yuv420p",
        "-g", str(gop),
        "-no-scenecut", "1",            # NVENC equivalent of sc_threshold=0
        "-forced-idr", "1",
        *tag,
    ]
    if target.b_frames >= 0:
        args += ["-bf", str(target.b_frames)]
    args += _rate_control_args(target, notes)
    notes.append(
        f"{encoder} ({preset}, tune=hq) CQ {target.crf} · GOP {gop} · GPU sürətləndirmə"
    )
    return args


def _audio_args(opts: JobOptions, notes: List[str]) -> List[str]:
    codec = str(opts.audio_codec or "aac")
    args = ["-c:a", codec]
    if codec == "copy":
        notes.append("Audio kopyalanır (re-encode yoxdur).")
        return args

    requested = int(opts.audio_bitrate)
    sr = int(opts.audio_sample_rate or 48000)
    cap = aac_max_bitrate_kbps(sr)
    if codec == "aac" and requested > cap:
        notes.append(
            f"AAC {requested}kbps @{sr}Hz mümkün deyil (maks {cap}kbps) — encoder "
            f"{cap}kbps-ə sıxacaq. Əsl 320kbps üçün 96000Hz seçin."
        )
    args += ["-b:a", f"{requested}k", "-ar", str(sr)]
    if opts.audio_channels:
        args += ["-ac", str(int(opts.audio_channels))]
    return args


def _rate(fps: float) -> str:
    if abs(fps - round(fps)) < 1e-6:
        return str(int(round(fps)))
    return f"{fps:.4f}".rstrip("0").rstrip(".")


def quote_command(command: Sequence[str]) -> str:
    """Human-readable single-line form for the GUI "copy command" button."""
    out: List[str] = []
    for arg in command:
        text = str(arg)
        if any(c in text for c in " \"'\\"):
            text = "'" + text.replace("'", "'\\''") + "'"
        out.append(text)
    return " ".join(out)
