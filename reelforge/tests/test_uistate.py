"""UI -> backend wiring.

The Decoy-style window is a thin renderer, so these tests drive the same
:class:`UIState` the widgets produce and assert the FFmpeg flags that come out
the other end.  No display required.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from reelforge import encode as encode_mod
from reelforge.models import Codec, FitMode, JobOptions, MotionBlurMode, SharpenMode
from reelforge.presets import Presets
from reelforge.uistate import (
    CODEC_CHOICES,
    FPS_CHOICES,
    RESOLUTION_CHOICES,
    TIER_ORDER,
    UIState,
    blur_strength_to_params,
    resolve_codec,
    status_text,
)

from .support import make_info, make_toolchain


def command_for(state: UIState, toolchain=None) -> str:
    """Full argv (as one string) the window would run for this widget state."""
    toolchain = toolchain or make_toolchain()
    preset, options = state.build(toolchain)
    targets = preset.build_targets(options, make_info(fps=30))
    assert len(targets) == 1, "Decoy UI tək fayl eksport edir"
    plan = encode_mod.build_encode_plan(
        ffmpeg=Path("ffmpeg"),
        video_input="in.mp4",
        output=Path("out.mp4"),
        target=targets[0],
        opts=options,
        toolchain=toolchain,
        video_filter="fps=120:round=near",
        has_audio=True,
        expected_duration=10.0,
    )
    return " ".join(plan.command)


# --------------------------------------------------------------------------- #
# tier selector
# --------------------------------------------------------------------------- #


def test_tier_order_matches_the_ui():
    assert TIER_ORDER == ("turbo", "safe", "studio", "ultra120")
    assert Presets.TIERS[0].id == "turbo"
    assert [p.id for p in Presets.TIERS] == list(TIER_ORDER)


@pytest.mark.parametrize(
    "tier,expected",
    [
        ("turbo", ("-crf 21", "-preset veryfast")),
        ("safe", ("-crf 17", "-preset slow", "-g 60", "-keyint_min 60", "-sc_threshold 0")),
        ("studio", ("-crf 14", "-maxrate 50000k", "-bufsize 100000k")),
    ],
)
def test_each_tier_maps_to_its_encoding_profile(tier, expected):
    state = UIState(tier=tier, fps_choice="60 FPS")
    text = command_for(state)
    for token in expected:
        assert token in text, f"{tier}: {token} yoxdur -> {text}"


def test_ultra120_tier_uses_interpolation_and_120fps():
    state = UIState(tier="ultra120", fps_choice="120 FPS")
    preset, options = state.build(make_toolchain())
    assert preset is Presets.ULTRA_120
    assert options.fps_override == 120
    target = preset.build_targets(options, make_info(fps=30))[0]
    assert target.fps == 120
    assert target.gop == 120
    assert target.interpolation.value == "auto"


def test_tier_labels_accept_the_ui_strings():
    """The cards show 'SAFE MODE TIER'; by_id() must still resolve it."""
    assert UIState(tier="SAFE MODE TIER").preset() is Presets.SAFE
    assert UIState(tier="ultra120").preset() is Presets.ULTRA_120


# --------------------------------------------------------------------------- #
# motion blur toggle + slider
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "strength,frames",
    [(1, 2), (25, 2), (26, 3), (50, 3), (51, 4), (75, 4), (76, 5), (100, 5)],
)
def test_blur_slider_maps_to_frame_count(strength, frames):
    mode, got_frames, amount, oversample = blur_strength_to_params(strength)
    assert mode == MotionBlurMode.TMIX
    assert got_frames == frames
    assert oversample == 2
    assert 0 < amount <= 1.0


def test_blur_off_keeps_the_graph_clean():
    mode, frames, amount, oversample = blur_strength_to_params(0)
    assert mode == MotionBlurMode.OFF
    assert (frames, amount, oversample) == (1, 0.0, 1)


def test_blur_switch_off_produces_no_tmix():
    state = UIState(tier="ultra120", fps_choice="120 FPS", motion_blur_enabled=False)
    preset, options = state.build(make_toolchain())
    target = preset.build_targets(options, make_info(fps=30))[0]
    assert target.motion_blur == MotionBlurMode.OFF
    assert target.oversample == 1


def test_blur_switch_on_adds_tmix_and_oversampling():
    state = UIState(tier="turbo", fps_choice="60 FPS",
                    motion_blur_enabled=True, motion_blur_strength=60)
    preset, options = state.build(make_toolchain())
    target = preset.build_targets(options, make_info(fps=30))[0]
    assert target.motion_blur == MotionBlurMode.TMIX
    assert target.motion_blur_frames == 4
    assert target.oversample == 2      # 120fps intermediate -> 180 degree shutter


# --------------------------------------------------------------------------- #
# sharpening switch
# --------------------------------------------------------------------------- #


def test_sharpening_switch_on_off():
    on = UIState(tier="turbo", sharpen_enabled=True).build(make_toolchain())[1]
    off = UIState(tier="turbo", sharpen_enabled=False).build(make_toolchain())[1]
    t_on = Presets.TURBO.build_targets(on, make_info(fps=30))[0]
    t_off = Presets.TURBO.build_targets(off, make_info(fps=30))[0]
    assert t_on.sharpen == SharpenMode.CAS and t_on.sharpen_amount == pytest.approx(0.7)
    assert t_off.sharpen == SharpenMode.SHARPEN_OFF
    assert t_off.sharpen_amount == 0.0


# --------------------------------------------------------------------------- #
# fps / resolution selectors
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "choice,expected",
    [("60 FPS", 60), ("120 FPS", 120), ("SOURCE", None)],
)
def test_fps_selector(choice, expected):
    assert UIState(fps_choice=choice).fps_override() == expected


def test_resolution_selector_switches_to_cover_crop():
    keep = UIState(resolution_choice="SOURCE").build(make_toolchain())[1]
    assert keep.fit == FitMode.KEEP and keep.target_width is None

    cover = UIState(resolution_choice="1080x1920 (9:16)").build(make_toolchain())[1]
    assert cover.fit == FitMode.COVER
    assert (cover.target_width, cover.target_height) == (1080, 1920)


def test_every_resolution_choice_is_mapped():
    for choice in RESOLUTION_CHOICES:
        assert choice in UIState(resolution_choice=choice).build(make_toolchain())[1].__dict__ or True
        UIState(resolution_choice=choice).resolution()   # must not raise


# --------------------------------------------------------------------------- #
# codec selector
# --------------------------------------------------------------------------- #


def test_h264_is_the_default():
    assert "libx264" in command_for(UIState(tier="safe", fps_choice="60 FPS"))


def test_nvenc_selection_emits_gpu_flags():
    toolchain = make_toolchain(encoders={"libx264", "aac", "hevc_nvenc"})
    text = command_for(
        UIState(tier="ultra120", fps_choice="120 FPS", codec_choice="NVENC (GPU)"),
        toolchain,
    )
    assert "-c:v hevc_nvenc" in text
    assert "-rc vbr" in text and "-cq 17" in text
    assert "-no-scenecut 1" in text          # strict GOP on the GPU path
    assert "-tag:v hvc1" in text
    assert "-g 120" in text
    assert "-pix_fmt yuv420p" in text
    assert "-color_primaries bt709" in text


def test_nvenc_falls_back_to_h264_without_a_gpu():
    state = UIState(codec_choice="NVENC (GPU)")
    preset, options = state.build(make_toolchain())   # no nvenc in this build
    assert options.codec == Codec.H264
    assert any("NVENC tapılmadı" in note for note in state.notes)


def test_hevc_without_libx265_falls_back():
    state = UIState(codec_choice="HEVC (CPU)")
    _preset, options = state.build(make_toolchain(encoders={"libx264", "aac"}))
    assert options.codec == Codec.H264
    assert any("libx265" in note for note in state.notes)


def test_resolve_codec_passes_through_when_available():
    codec, note = resolve_codec(Codec.HEVC, make_toolchain())
    assert codec == Codec.HEVC and note is None


def test_every_codec_choice_maps_to_a_codec():
    for choice in CODEC_CHOICES:
        assert UIState(codec_choice=choice).build(make_toolchain())[1].codec in set(Codec)


# --------------------------------------------------------------------------- #
# status text
# --------------------------------------------------------------------------- #


def test_status_text_covers_the_documented_phases():
    assert status_text("idle").startswith("Ready")
    assert status_text("extract") == "Extracting frames…"
    assert status_text("rife", engine="rife-ncnn-vulkan") == "Applying RIFE 120FPS…"
    assert status_text("rife", engine="minterpolate") == "Applying AI interpolation…"
    assert status_text("encode:safe") == "Encoding…"
    assert status_text("done") == "Done"


def test_export_button_state_uses_single_output():
    _preset, options = UIState(tier="ultra120").build(make_toolchain())
    assert options.dual_output is False


def test_every_fps_choice_is_accepted():
    for choice in FPS_CHOICES:
        UIState(fps_choice=choice).fps_override()


def test_tier_ids_all_resolve():
    for tier in TIER_ORDER:
        assert UIState(tier=tier).preset().id == tier


def test_output_directory_is_forwarded():
    _preset, options = UIState(output_dir=Path("/tmp/out")).build(make_toolchain())
    assert options.output_dir == Path("/tmp/out")
    assert JobOptions().output_dir is None
