from __future__ import annotations

from reelforge import filters as f
from reelforge.models import (
    ColorTag,
    FitMode,
    InterpolationEngineKind,
    JobOptions,
    MotionBlurMode,
    RenderTarget,
    SharpenMode,
)

from .support import make_info, make_toolchain


def target(**kwargs) -> RenderTarget:
    base = dict(
        fps=60, suffix="t", label="t", crf=18, x264_preset="slow",
        gop_seconds=1.0, interpolation=InterpolationEngineKind.MINTERPOLATE,
        sharpen=SharpenMode.CAS, sharpen_amount=0.7,
    )
    base.update(kwargs)
    return RenderTarget(**base)


# --------------------------------------------------------------------------- #
# geometry
# --------------------------------------------------------------------------- #


def test_keep_fit_emits_nothing_for_even_source():
    assert f.geometry_filters(JobOptions(fit=FitMode.KEEP), make_info()) == []


def test_keep_fit_fixes_odd_dimensions():
    nodes = f.geometry_filters(JobOptions(fit=FitMode.KEEP), make_info(width=1081, height=1921))
    assert nodes[0] == "scale=trunc(iw/2)*2:trunc(ih/2)*2"
    assert nodes[-1] == "setsar=1"


def test_cover_fit_scales_up_then_crops():
    opts = JobOptions(fit=FitMode.COVER, target_width=1080, target_height=1920)
    nodes = f.geometry_filters(opts, make_info(width=1920, height=1080))
    assert nodes[0].startswith("scale=1080:1920:force_original_aspect_ratio=increase")
    assert "flags=lanczos" in nodes[0]
    assert nodes[1] == "crop=1080:1920"
    assert nodes[2] == "setsar=1"


def test_contain_fit_letterboxes():
    opts = JobOptions(fit=FitMode.CONTAIN, target_width=1080, target_height=1920)
    nodes = f.geometry_filters(opts, make_info(width=1920, height=1080))
    assert nodes[0].startswith("scale=1080:1920:force_original_aspect_ratio=decrease")
    assert nodes[1] == "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black"


def test_stretch_fit_and_custom_scaler():
    opts = JobOptions(fit=FitMode.STRETCH, target_width=1080, target_height=1920,
                      scaler="bicubic")
    nodes = f.geometry_filters(opts, make_info())
    assert nodes[0] == "scale=1080:1920:flags=bicubic"


# --------------------------------------------------------------------------- #
# interpolation / rate
# --------------------------------------------------------------------------- #


def test_minterpolate_string_is_complete():
    node = f.minterpolate_filter(120, "balanced")
    assert node.startswith("minterpolate=fps=120:")
    for token in ("mi_mode=mci", "mc_mode=aobmc", "me_mode=bidir", "vsbmc=1",
                  "scd=fdiff", "scd_threshold=8"):
        assert token in node


def test_minterpolate_quality_levels_differ():
    fast = f.minterpolate_filter(120, "fast")
    quality = f.minterpolate_filter(120, "quality")
    assert "mi_mode=blend" in fast
    assert "mb_size=8" in quality


def test_rate_string_handles_ntsc():
    assert f._rate_str(59.94) == "60000/1001"
    assert f._rate_str(60.0) == "60"
    assert f._rate_str(23.976) == "24000/1001"


def test_graph_interpolates_then_locks_rate():
    plan = f.build_filter_plan(
        target(fps=120), JobOptions(), make_info(fps=30), make_toolchain()
    )
    chain = plan.graph.build()
    assert "minterpolate=fps=120" in chain
    assert chain.index("minterpolate") < chain.index("fps=120")
    assert "format=yuv420p" in chain


def test_oversample_interpolates_higher_then_decimates():
    plan = f.build_filter_plan(
        target(fps=60, oversample=2), JobOptions(), make_info(fps=30), make_toolchain()
    )
    chain = plan.graph.build()
    assert "minterpolate=fps=120" in chain
    assert "fps=60:round=near" in chain


def test_no_interpolation_filter_when_source_is_already_fast():
    plan = f.build_filter_plan(
        target(fps=60), JobOptions(), make_info(fps=120), make_toolchain()
    )
    assert "minterpolate" not in plan.graph.build()


def test_external_interpolation_forces_fps_lock():
    plan = f.build_filter_plan(
        target(fps=120, interpolation=InterpolationEngineKind.RIFE),
        JobOptions(), make_info(fps=30), make_toolchain(),
        external_interpolation=True,
    )
    chain = plan.graph.build()
    assert "minterpolate" not in chain
    assert "fps=120:round=near" in chain


# --------------------------------------------------------------------------- #
# motion blur
# --------------------------------------------------------------------------- #


def test_tmix_motion_blur_with_weights():
    nodes = f.motion_blur_filters(
        target(motion_blur=MotionBlurMode.TMIX, motion_blur_frames=3),
        make_toolchain(), f.FilterGraph([]),
    )
    assert nodes == ["tmix=frames=3:weights=1 1 1"]


def test_tblend_motion_blur():
    nodes = f.motion_blur_filters(
        target(motion_blur=MotionBlurMode.TBLEND), make_toolchain(), f.FilterGraph([])
    )
    assert nodes == ["tblend=all_mode=average"]


def test_mblur_falls_back_to_tmix_when_missing():
    graph = f.FilterGraph([])
    nodes = f.motion_blur_filters(
        target(motion_blur=MotionBlurMode.MBLUR), make_toolchain(filters={"tmix"}), graph
    )
    assert nodes[0].startswith("tmix=frames=")
    assert any("mblur" in note for note in graph.notes)


def test_mblur_used_when_available():
    nodes = f.motion_blur_filters(
        target(motion_blur=MotionBlurMode.MBLUR, motion_blur_amount=0.6),
        make_toolchain(filters={"mblur", "tmix"}), f.FilterGraph([]),
    )
    assert nodes == ["mblur=0.6"]


# --------------------------------------------------------------------------- #
# sharpening / colour
# --------------------------------------------------------------------------- #


def test_cas_sharpening():
    nodes = f.sharpen_filters(target(sharpen_amount=0.85), make_toolchain(), f.FilterGraph([]))
    assert nodes == ["cas=strength=0.85"]


def test_cas_amount_is_clamped_to_one():
    nodes = f.sharpen_filters(target(sharpen_amount=3.0), make_toolchain(), f.FilterGraph([]))
    assert nodes == ["cas=strength=1"]


def test_cas_missing_falls_back_to_unsharp():
    graph = f.FilterGraph([])
    nodes = f.sharpen_filters(target(sharpen_amount=0.5), make_toolchain(filters={"unsharp"}), graph)
    assert nodes[0].startswith("unsharp=luma_msize_x=5")
    assert "luma_amount=0.400" in nodes[0]
    assert graph.notes


def test_sharpening_disabled_by_zero():
    assert f.sharpen_filters(target(sharpen_amount=0), make_toolchain(), f.FilterGraph([])) == []


def test_format_and_bt709_tagging():
    nodes = f.format_filters(JobOptions())
    assert nodes[0] == "format=yuv420p"
    assert nodes[1] == (
        "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv"
    )


def test_full_range_and_bt2020_tag():
    nodes = f.format_filters(JobOptions(color_tag=ColorTag.BT2020, limited_range=False))
    assert nodes[1].endswith("range=pc")
    assert "color_primaries=bt2020" in nodes[1]


# --------------------------------------------------------------------------- #
# whole chain
# --------------------------------------------------------------------------- #


def test_chain_order_is_geometry_interp_blur_sharpen_format():
    plan = f.build_filter_plan(
        target(fps=60, oversample=2, motion_blur=MotionBlurMode.TMIX),
        JobOptions(fit=FitMode.COVER, target_width=1080, target_height=1920),
        make_info(fps=30), make_toolchain(),
    )
    chain = plan.graph.build()
    order = [chain.index(token) for token in
             ("scale=1080:1920", "minterpolate", "tmix", "cas", "format=yuv420p", "setparams")]
    assert order == sorted(order)


def test_hdr_source_gets_tonemapped():
    plan = f.build_filter_plan(target(fps=60), JobOptions(),
                               make_info(fps=30, hdr=True), make_toolchain())
    chain = plan.graph.build()
    assert "zscale=t=linear:npl=100" in chain
    assert "tonemap=tonemap=hable:desat=0" in chain


def test_hdr_without_zscale_only_warns():
    graph_plan = f.build_filter_plan(
        target(fps=60), JobOptions(), make_info(fps=30, hdr=True),
        make_toolchain(filters={"scale", "fps", "format", "setparams", "minterpolate"}),
    )
    assert "tonemap" not in graph_plan.graph.build()
    assert any("zscale" in note for note in graph_plan.graph.notes)


def test_graph_renders_without_commas_in_wrong_places():
    plan = f.build_filter_plan(target(fps=60), JobOptions(), make_info(), make_toolchain())
    chain = plan.graph.build()
    assert not chain.startswith(",") and not chain.endswith(",")
    assert ",," not in chain
