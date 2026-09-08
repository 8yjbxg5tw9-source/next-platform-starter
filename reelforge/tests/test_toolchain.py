"""Toolchain discovery, capability parsing and progress arithmetic."""

from __future__ import annotations

import pytest

from reelforge import toolchain as tc
from reelforge.toolchain import FFmpegRunner, ToolchainError

from .support import make_toolchain

FILTERS_SAMPLE = """Filters:
  T.. = Timeline support
  .S. = Slice threading
  ..C = Command support
  T.C cas               V->V       Contrast Adaptive Sharpen.
 ... format            V->V       Convert the input video to one of the specified pixel format.
 ... fps               V->V       Force constant framerate.
 ... minterpolate      V->V       Frame rate conversion using Motion Interpolation.
 TSC tblend            V->V       Blend successive frames.
"""

ENCODERS_SAMPLE = """Encoders:
 V..... = Video
 A..... = Audio
 S..... = Subtitle
 .F.... = Frame-level multithreading
 ..S... = Slice-level multithreading
 ...X.. = Codec is experimental
 ....B. = Supports draw_horiz_band
 .....D = Supports direct rendering method 1
 ------
 V....D libx264              libx264 H.264 / AVC / MPEG-4 AVC / MPEG-4 part 10 (codec h264)
 V....D libx265              libx265 H.265 / HEVC (codec hevc)
 A....D aac                  AAC (Advanced Audio Coding) (codec aac)
 VF...D cfhd                 GoPro CineForm HD
 VFS..D dnxhd                VC3/DNxHD
 V.S..D ffv1                 FFmpeg video codec #1
 V....D h264_nvenc           NVIDIA NVENC H.264 encoder (codec h264)
"""


def test_filter_list_parsing():
    filters = tc._parse_filters(FILTERS_SAMPLE)
    assert {"cas", "format", "fps", "minterpolate", "tblend"} <= filters
    assert "=" not in filters


def test_encoder_list_parsing_includes_every_capability_column():
    encoders = tc._parse_encoders(ENCODERS_SAMPLE)
    assert {"libx264", "libx265", "aac", "h264_nvenc", "cfhd", "dnxhd", "ffv1"} <= encoders
    assert "=" not in encoders


def test_live_capability_detection(toolchain):
    """Against the real local build: the flags we rely on must be detected."""
    assert toolchain.major >= 4
    assert toolchain.has_encoder("libx264")
    assert toolchain.has_filter("scale")
    assert len(toolchain.filters) > 100


def test_feature_flags_follow_the_version():
    assert make_toolchain(major=7, minor=0).supports_fps_mode is True
    assert make_toolchain(major=5, minor=1).supports_fps_mode is True
    assert make_toolchain(major=5, minor=0).supports_fps_mode is False
    assert make_toolchain(major=4, minor=4).supports_fps_mode is False


def test_missing_ffmpeg_raises_a_helpful_error(monkeypatch):
    monkeypatch.setattr(tc, "find_executable", lambda name, override=None: None)
    with pytest.raises(ToolchainError) as exc:
        tc.find_toolchain()
    assert "ffmpeg" in str(exc.value)


def test_env_override_is_honoured(monkeypatch, tmp_path):
    fake = tmp_path / "ffmpeg"
    fake.write_text("#!/bin/sh\necho 'ffmpeg version 6.1.1'\n")
    fake.chmod(0o755)
    monkeypatch.setenv("REELFORGE_FFMPEG", str(fake))
    found = tc.find_executable("ffmpeg")
    assert found == fake.resolve()


# --------------------------------------------------------------------------- #
# progress parsing
# --------------------------------------------------------------------------- #


def test_time_parsing():
    assert tc._time_to_seconds("00:00:01.020000") == pytest.approx(1.02)
    assert tc._time_to_seconds("00:01:30.500000") == pytest.approx(90.5)
    assert tc._time_to_seconds("N/A") == 0.0
    assert tc._micros_to_seconds("1500000") == pytest.approx(1.5)


def test_progress_carries_speed_fps_and_eta():
    runner = FFmpegRunner(make_toolchain().ffmpeg)
    info = runner._make_progress(
        phase="encode:safe", step=1, total_steps=2, out_time=5.0, expected=10.0,
        started=__import__("time").time() - 3.0, raw="out_time=5.0",
        state={"frame": 300, "fps": 100.0, "speed": 2.5},
    )
    assert info.step_percent == pytest.approx(50.0)
    assert info.percent == pytest.approx(25.0)      # step 1 of 2
    assert info.frame == 300
    assert info.fps == 100.0
    assert info.speed == 2.5
    assert info.eta_seconds == pytest.approx(3.0, abs=0.2)
    runner.close()


def test_progress_percent_spans_all_steps():
    runner = FFmpegRunner(make_toolchain().ffmpeg)
    first = runner._make_progress(
        phase="extract", step=1, total_steps=3, out_time=10.0, expected=10.0,
        started=1.0, raw="",
    )
    second = runner._make_progress(
        phase="encode", step=2, total_steps=3, out_time=10.0, expected=10.0,
        started=1.0, raw="",
    )
    assert first.percent == pytest.approx(100.0 / 3.0)
    assert second.percent == pytest.approx(200.0 / 3.0)
    runner.close()
