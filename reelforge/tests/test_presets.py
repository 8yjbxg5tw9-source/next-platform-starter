from __future__ import annotations

import pytest

from reelforge.models import (
    Codec,
    InterpolationEngineKind,
    JobOptions,
    MediaInfo,
    MotionBlurMode,
    SharpenMode,
    StreamInfo,
)
from reelforge.presets import Presets


def info_at(fps: float, width: int = 1080, height: int = 1920, audio: bool = True) -> MediaInfo:
    streams = [
        StreamInfo(index=0, codec_type="video", codec_name="h264", width=width,
                   height=height, pix_fmt="yuv420p", fps=fps, avg_frame_rate=fps,
                   nb_frames=int(fps * 4), duration=4.0)
    ]
    if audio:
        streams.append(StreamInfo(index=1, codec_type="audio", codec_name="aac",
                                  sample_rate=48000, channels=2))
    return MediaInfo(path=__file__, duration=4.0, streams=streams)


def test_preset_ids_and_lookup():
    assert Presets.choices() == [
        "turbo", "safe", "studio", "ultra120", "fast", "motionblur", "master",
    ]
    assert Presets.by_id("safe") is Presets.SAFE
    assert Presets.by_id("tiktok") is Presets.SAFE
    assert Presets.by_id("120") is Presets.ULTRA_120
    assert Presets.by_id("turbo") is Presets.TURBO
    assert Presets.by_id("studio") is Presets.STUDIO
    with pytest.raises(KeyError):
        Presets.by_id("nope")


def test_turbo_is_the_fastest_path():
    t = Presets.TURBO.build_targets(JobOptions(), info_at(30))[0]
    assert (t.crf, t.x264_preset, t.fps) == (21, "veryfast", 60)
    assert t.gop == 60
    assert t.interpolation == InterpolationEngineKind.NONE


def test_studio_is_the_high_bitrate_path():
    t = Presets.STUDIO.build_targets(JobOptions(), info_at(30))[0]
    assert (t.crf, t.x264_preset) == (14, "slow")
    assert (t.maxrate_kbps, t.bufsize_kbps) == (50_000, 100_000)
    assert t.sharpen == SharpenMode.CAS


def test_nvenc_profile_and_level():
    from reelforge.models import Codec

    t = Presets.ULTRA_120.build_targets(
        JobOptions(codec=Codec.NVENC), info_at(30), codec_override=Codec.NVENC
    )
    assert t[1].codec == Codec.NVENC
    assert t[1].profile == "main"
    assert t[1].codec.probe_name == "hevc"


def test_fast_preset_is_60fps_crf20():
    targets = Presets.FAST.build_targets(JobOptions(), info_at(30))
    assert len(targets) == 1
    t = targets[0]
    assert (t.fps, t.crf, t.x264_preset) == (60, 20, "fast")
    assert t.gop == 60                      # one second at 60 fps
    assert t.interpolation == InterpolationEngineKind.NONE


def test_safe_preset_locks_one_second_gop():
    t = Presets.SAFE.build_targets(JobOptions(), info_at(30))[0]
    assert t.crf == 17 and t.x264_preset == "slow" and t.tune == "film"
    assert t.gop == 60 and t.gop_seconds == 1.0
    assert t.sharpen == SharpenMode.CAS


def test_ultra120_produces_two_variants():
    targets = Presets.ULTRA_120.build_targets(JobOptions(), info_at(30))
    assert [t.fps for t in targets] == [60, 120]
    assert targets[1].interpolation == InterpolationEngineKind.AUTO
    assert targets[1].crf == 17
    assert targets[1].gop == 120            # still exactly one second


def test_ultra120_single_variant_when_dual_disabled():
    targets = Presets.ULTRA_120.build_targets(JobOptions(dual_output=False), info_at(30))
    assert [t.fps for t in targets] == [120]


def test_interpolation_is_skipped_when_source_already_fast_enough():
    targets = Presets.ULTRA_120.build_targets(JobOptions(), info_at(120))
    for t in targets:
        assert t.interpolation == InterpolationEngineKind.NONE


def test_hevc_override_switches_profile_and_level():
    targets = Presets.ULTRA_120.build_targets(
        JobOptions(codec=Codec.HEVC), info_at(30), codec_override=Codec.HEVC
    )
    for t in targets:
        assert t.codec == Codec.HEVC
        assert t.profile == "main"
    assert targets[1].level == "5.1"        # 120 fps needs a higher level
    assert targets[0].level == "5.0"


def test_overrides_from_options_win():
    targets = Presets.SAFE.build_targets(
        JobOptions(crf_override=23, fps_override=120, codec=Codec.H264), info_at(30)
    )
    assert (targets[0].crf, targets[0].fps) == (23, 120)
    assert targets[0].level == "5.1"


def test_motion_blur_preset_oversamples_for_shutter():
    t = Presets.MOTION_BLUR.build_targets(JobOptions(), info_at(30))[0]
    assert t.motion_blur == MotionBlurMode.TMIX
    assert t.motion_blur_frames == 2
    assert t.oversample == 2
    assert t.interpolation == InterpolationEngineKind.MINTERPOLATE


def test_master_keeps_source_fps():
    t = Presets.MASTER.build_targets(JobOptions(), info_at(24))[0]
    assert t.fps == 24
    assert t.crf == 12 and t.gop == 48      # 2 seconds at 24 fps


def test_output_naming():
    t = Presets.ULTRA_120.build_targets(JobOptions(), info_at(30))[1]
    assert t.output_name(__import__("pathlib").Path("/tmp/My Clip.mp4")) == (
        "My Clip__ultra120_120fps.mp4"
    )
