"""Tests for the encode command builder (the anti-compression core)."""

from __future__ import annotations

import pytest

from reelforge import encode
from reelforge.models import Codec, JobOptions, RenderTarget
from reelforge.toolchain import Toolchain

from .support import make_toolchain


def target(**kwargs) -> RenderTarget:
    base = dict(fps=60, suffix="safe", label="safe", crf=17, x264_preset="slow",
                profile="high", level="4.2", gop_seconds=1.0, b_frames=2, tune="film")
    base.update(kwargs)
    return RenderTarget(**base)


def build(toolchain: Toolchain = None, opts: JobOptions = None, **target_kwargs):
    toolchain = toolchain or make_toolchain()
    opts = opts or JobOptions()
    plan = encode.build_encode_plan(
        ffmpeg=toolchain.ffmpeg,
        video_input="in.mp4",
        output=__import__("pathlib").Path("out.mp4"),
        target=target(**target_kwargs),
        opts=opts,
        toolchain=toolchain,
        video_filter="fps=60:round=near,format=yuv420p",
        has_audio=True,
        expected_duration=10.0,
    )
    return plan.command, plan.notes


def joined(command) -> str:
    return " ".join(str(c) for c in command)


# --------------------------------------------------------------------------- #
# structure every preset must satisfy
# --------------------------------------------------------------------------- #


def test_tiktok_gop_structure_is_present():
    command, _ = build()
    text = joined(command)
    assert "-g 60" in text
    assert "-keyint_min 60" in text
    assert "-sc_threshold 0" in text
    assert "keyint=60:min-keyint=60:scenecut=0" in text


def test_gop_scales_with_frame_rate():
    command, _ = build(fps=120)
    assert "-g 120" in joined(command)
    assert "-keyint_min 120" in joined(command)


def test_constant_rate_factor_and_pixel_format():
    command, _ = build()
    text = joined(command)
    assert "-crf 17" in text
    assert "-pix_fmt yuv420p" in text
    assert "-profile:v high" in text
    assert "-level:v 4.2" in text
    assert "-preset slow" in text


def test_colour_metadata_is_tagged():
    command, _ = build()
    text = joined(command)
    assert "-color_primaries bt709" in text
    assert "-color_trc bt709" in text
    assert "-colorspace bt709" in text
    assert "-color_range tv" in text


def test_audio_is_aac_320k_48k_stereo():
    command, _ = build()
    text = joined(command)
    assert "-c:a aac" in text
    assert "-b:a 320k" in text
    assert "-ar 48000" in text
    assert "-ac 2" in text


def test_faststart_and_safe_muxing():
    command, _ = build()
    text = joined(command)
    assert "-movflags +faststart" in text
    assert "-max_muxing_queue_size 1024" in text


def test_cfr_flag_follows_ffmpeg_version():
    command, _ = build(toolchain=make_toolchain(major=7, minor=0))
    assert "-fps_mode cfr" in joined(command)
    old, _ = build(toolchain=make_toolchain(major=5, minor=0))
    assert "-vsync cfr" in joined(old)


def test_filter_chain_is_passed_through():
    command, _ = build()
    assert "-vf" in command
    assert command[command.index("-vf") + 1].startswith("fps=60")


def test_output_is_last_and_y_flag_first():
    command, _ = build()
    assert command[-1].endswith("out.mp4")
    assert "-y" in command[:12]


def test_no_overwrite_flag_when_disabled():
    command, _ = build(opts=JobOptions(overwrite=False))
    assert "-n" in command[:12]


# --------------------------------------------------------------------------- #
# codecs
# --------------------------------------------------------------------------- #


def test_hevc_uses_hvc1_tag_and_x265_params():
    command, notes = build(codec=Codec.HEVC, profile="main", level="5.1")
    text = joined(command)
    assert "-c:v libx265" in text
    assert "-tag:v hvc1" in text
    assert "keyint=60:min-keyint=60:scenecut=0" in text
    assert any("HEVC" in note for note in notes)


def test_hevc_requires_encoder_support():
    with pytest.raises(encode.EncodeError):
        build(toolchain=make_toolchain(encoders={"libx264", "aac"}), codec=Codec.HEVC)


def test_missing_x264_raises():
    with pytest.raises(encode.EncodeError):
        build(toolchain=make_toolchain(encoders={"aac"}))


def test_nvenc_uses_cq_vbr_and_strict_gop():
    command, notes = build(
        toolchain=make_toolchain(encoders={"libx264", "aac", "hevc_nvenc"}),
        codec=Codec.NVENC, profile="main", level="5.1",
    )
    text = joined(command)
    assert "-c:v hevc_nvenc" in text
    assert "-rc vbr" in text
    assert "-cq 17" in text
    assert "-b:v 0" in text
    assert "-no-scenecut 1" in text
    assert "-forced-idr 1" in text
    assert "-tag:v hvc1" in text
    assert "-g 60" in text
    assert "-crf" not in text          # NVENC uses -cq, not -crf
    assert any("GPU" in note for note in notes)


def test_nvenc_falls_back_to_h264_nvenc_when_hevc_is_missing():
    command, _ = build(
        toolchain=make_toolchain(encoders={"libx264", "aac", "h264_nvenc"}),
        codec=Codec.NVENC,
    )
    text = joined(command)
    assert "-c:v h264_nvenc" in text
    assert "-tag:v hvc1" not in text


def test_nvenc_without_any_gpu_encoder_raises():
    with pytest.raises(encode.EncodeError):
        build(toolchain=make_toolchain(encoders={"libx264", "aac"}), codec=Codec.NVENC)


def test_nvenc_preset_uses_legacy_names_on_old_ffmpeg():
    command, _ = build(
        toolchain=make_toolchain(major=4, minor=4,
                                 encoders={"libx264", "aac", "hevc_nvenc"}),
        codec=Codec.NVENC,
    )
    assert "-preset slow" in joined(command)


def test_maxrate_and_bufsize_are_emitted():
    from reelforge.models import RenderTarget

    target = RenderTarget(
        fps=60, suffix="studio", label="studio", crf=14, x264_preset="slow",
        maxrate_kbps=50_000, bufsize_kbps=100_000,
    )
    plan = encode.build_encode_plan(
        ffmpeg=__import__("pathlib").Path("ffmpeg"),
        video_input="in.mp4",
        output=__import__("pathlib").Path("out.mp4"),
        target=target,
        opts=JobOptions(),
        toolchain=make_toolchain(),
        has_audio=True,
    )
    text = joined(plan.command)
    assert "-maxrate 50000k" in text
    assert "-bufsize 100000k" in text
    assert any("VBV" in note for note in plan.notes)


# --------------------------------------------------------------------------- #
# audio specifics
# --------------------------------------------------------------------------- #


def test_aac_cap_is_288kbps_at_48khz():
    assert encode.aac_max_bitrate_kbps(48000) == 288
    assert encode.aac_max_bitrate_kbps(96000) == 576


def test_320k_at_48khz_produces_a_warning_note():
    _, notes = build(opts=JobOptions(audio_bitrate=320, audio_sample_rate=48000))
    assert any("288" in note for note in notes)


def test_320k_at_96khz_is_not_clamped():
    command, notes = build(opts=JobOptions(audio_bitrate=320, audio_sample_rate=96000))
    assert "-ar 96000" in joined(command)
    assert not any("288" in note for note in notes)


def test_audio_copy_skips_bitrate_flags():
    command, notes = build(opts=JobOptions(audio_codec="copy"))
    text = joined(command)
    assert "-c:a copy" in text
    assert "-b:a" not in text
    assert any("kopyalanır" in note for note in notes)


def test_silent_source_gets_an_flag():
    plan = encode.build_encode_plan(
        ffmpeg=__import__("pathlib").Path("ffmpeg"),
        video_input="in.mp4",
        output=__import__("pathlib").Path("out.mp4"),
        target=target(),
        opts=JobOptions(),
        toolchain=make_toolchain(),
        has_audio=False,
    )
    assert "-an" in plan.command
    assert "-c:a" not in plan.command


def test_second_audio_input_is_mapped_for_rife():
    plan = encode.build_encode_plan(
        ffmpeg=__import__("pathlib").Path("ffmpeg"),
        video_input="frames/%08d.png",
        video_input_args=["-framerate", "120"],
        audio_input=__import__("pathlib").Path("in.mp4"),
        output=__import__("pathlib").Path("out.mp4"),
        target=target(fps=120),
        opts=JobOptions(),
        toolchain=make_toolchain(),
        has_audio=True,
    )
    text = joined(plan.command)
    assert "-framerate 120" in text
    assert "-map 1:a:0?" in text


def test_threads_and_hwaccel_are_optional():
    command, _ = build(opts=JobOptions(threads=8, hwaccel="cuda"))
    text = joined(command)
    assert "-threads 8" in text
    assert "-hwaccel cuda" in text


def test_quote_command_escapes_spaces():
    assert encode.quote_command(["ffmpeg", "-i", "my clip.mp4"]) == (
        "ffmpeg -i 'my clip.mp4'"
    )
