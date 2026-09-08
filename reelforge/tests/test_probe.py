"""Probe tests.

``parse_ffmpeg_banner`` / ``parse_ffprobe_json`` are tested against recorded
real output, and additionally against the live local build whenever ffmpeg is
installed (the fixtures in ``conftest.py`` skip otherwise).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from reelforge import probe
from reelforge.toolchain import Toolchain

# --- recorded `ffmpeg -i` banner -------------------------------------------
BANNER = """ffmpeg version 7.0.2-static Copyright (c) the FFmpeg developers
Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'out60.mp4':
  Metadata:
    major_brand     : isom
    minor_version   : 512
    compatible_brands: isomiso2avc1mp41
    encoder         : Lavf61.1.100
  Duration: 00:00:01.02, start: 0.000000, bitrate: 2714 kb/s
  Stream #0:0[0x1](und): Video: h264 (High) (avc1 / 0x31637661), yuv420p(tv, bt709, progressive), 540x960 [SAR 1:1 DAR 9:16], 2602 kb/s, 60 fps, 60 tbr, 15360 tbn (default)
      Metadata:
        handler_name    : VideoHandler
        vendor_id       : [0][0][0][0]
  Stream #0:1[0x2](und): Audio: aac (LC) (mp4a / 0x6134706D), 48000 Hz, mono, fltp, 140 kb/s (default)
At least one output file must be specified
"""

# --- recorded `ffprobe -show_format -show_streams` JSON --------------------
PROBE_JSON = {
    "streams": [
        {
            "index": 0, "codec_name": "h264", "codec_type": "video",
            "profile": "High", "width": 1080, "height": 1920,
            "pix_fmt": "yuv420p", "r_frame_rate": "60/1",
            "avg_frame_rate": "60/1", "duration": "10.000000",
            "bit_rate": "8000000", "nb_frames": "600",
            "color_range": "tv", "color_space": "bt709",
            "color_transfer": "bt709", "color_primaries": "bt709",
        },
        {
            "index": 1, "codec_name": "aac", "codec_type": "audio",
            "sample_rate": "48000", "channels": 2, "bit_rate": "320000",
            "duration": "10.000000",
        },
        {"index": 2, "codec_name": "mov_text", "codec_type": "subtitle"},
    ],
    "format": {
        "filename": "out.mp4", "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
        "duration": "10.021000", "size": "10485760", "bit_rate": "8320000",
    },
}


def test_banner_parsing_extracts_everything_we_need():
    info = probe.parse_ffmpeg_banner(BANNER, Path("out60.mp4"))
    assert info.probe_backend == "ffmpeg"
    assert info.duration == pytest.approx(1.02, abs=0.001)
    assert info.bit_rate == 2714000
    assert info.video.codec_name == "h264"
    assert info.video.profile == "High"
    assert info.video.pix_fmt == "yuv420p"
    assert (info.width, info.height) == (540, 960)
    assert info.fps == 60.0
    assert info.video.color_primaries == "bt709"
    assert info.video.color_range == "tv"
    assert info.has_audio
    assert info.audio.codec_name == "aac"
    assert info.audio.sample_rate == 48000
    assert info.audio.channels == 1
    assert info.audio.bit_rate == 140000


def test_banner_orientation_helper():
    info = probe.parse_ffmpeg_banner(BANNER, Path("out60.mp4"))
    assert info.orientation == "vertical"
    assert not info.is_hdr


def test_banner_without_video_raises():
    with pytest.raises(probe.ProbeError):
        probe.parse_ffmpeg_banner("Input #0 ... \n  Stream #0:0: Audio: mp3", Path("a.mp3"))


def test_ffprobe_json_parsing():
    info = probe.parse_ffprobe_json(PROBE_JSON, Path("out.mp4"))
    assert info.probe_backend == "ffprobe"
    assert info.fps == 60.0
    assert info.video.nb_frames == 600
    assert info.video.color_primaries == "bt709"
    assert info.audio.channels == 2
    assert info.duration == pytest.approx(10.021)
    assert info.size_bytes == 10485760
    assert len(info.streams) == 2      # subtitle stream is ignored


def test_rate_helper_handles_rationals():
    assert probe._rate("60000/1001") == pytest.approx(59.94005994)
    assert probe._rate("60/1") == 60.0
    assert probe._rate("0/0") is None
    assert probe._rate(None) is None


def test_probe_missing_file():
    from .support import make_toolchain

    with pytest.raises(probe.ProbeError):
        probe.probe("/no/such/file.mp4", make_toolchain())


# --------------------------------------------------------------------------- #
# live tests (need a real ffmpeg)
# --------------------------------------------------------------------------- #


def test_live_probe_reads_the_generated_clip(toolchain: Toolchain, sample_clip: Path):
    info = probe.probe(sample_clip, toolchain)
    assert info.fps == pytest.approx(30.0, abs=0.2)
    assert (info.width, info.height) == (320, 568)
    assert info.has_audio
    assert info.duration == pytest.approx(2.0, abs=0.3)


def test_live_probe_backend_matches_available_binaries(toolchain: Toolchain, sample_clip: Path):
    info = probe.probe(sample_clip, toolchain)
    expected = "ffprobe" if toolchain.ffprobe else "ffmpeg"
    assert info.probe_backend == expected


def test_live_frame_count_and_keyframes(toolchain: Toolchain, sample_clip: Path):
    assert probe.count_frames(sample_clip, toolchain) == 60
    times = probe.keyframe_gaps(sample_clip, toolchain)
    assert times and times[0] == pytest.approx(0.0, abs=0.05)
