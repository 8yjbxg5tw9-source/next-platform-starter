"""Output planning: target sizes, filter chains, encoder argv."""

from __future__ import annotations

from pathlib import Path

from akai.engine import ENCODERS, RenderJob, build_filter_chain


def _job(**kwargs) -> RenderJob:
    base = dict(source=Path("clip.mp4"), output_dir=Path("/tmp"))
    base.update(kwargs)
    return RenderJob(**base)


# -- target sizes -----------------------------------------------------------

def test_upscale_1080p_keeps_source_when_already_hd():
    assert _job(target="1080p").target_size(1920, 1080) == (1920, 1080)


def test_upscale_4k_doubles_1080p():
    assert _job(target="4K").target_size(1920, 1080) == (3840, 2160)


def test_upscale_8k_from_1080p():
    assert _job(target="8K").target_size(1920, 1080) == (7680, 4320)


def test_no_downscale_below_source():
    w, h = _job(target="1080p").target_size(2560, 1440)
    assert (w, h) >= (2560, 1440)


def test_portrait_video_fits_the_box():
    w, h = _job(target="4K").target_size(720, 1280)
    assert h == 2160 and w <= 3840
    assert w % 2 == 0 and h % 2 == 0


def test_custom_size_is_forced_even():
    assert _job(target="CUSTOM",
                custom_size=(641, 361)).target_size(320, 180) == (640, 360)


# -- filter chain -------------------------------------------------------------

def test_chain_starts_with_lanczos_scale():
    chain = build_filter_chain(_job(target="4K"), 1920, 1080)
    assert chain.startswith("scale=3840:2160:flags=lanczos")


def test_auto_mode_applies_denoise_and_detail_filters():
    chain = build_filter_chain(_job(auto_mode=True), 1920, 1080)
    assert "hqdn3d=" in chain
    assert "cas=" in chain


def test_fine_tune_zero_sliders_disable_filters():
    job = _job(auto_mode=False, revert_compression=0, reduce_noise=0,
               sharpen=0, recover_details=0, dehaloing=0)
    chain = build_filter_chain(job, 1920, 1080)
    assert "hqdn3d" not in chain
    assert "cas" not in chain


def test_reduce_noise_scales_hqdn3d_spatial_strength():
    quiet = build_filter_chain(
        _job(auto_mode=False, reduce_noise=10, revert_compression=0,
             sharpen=0, recover_details=0, dehaloing=0), 1920, 1080)
    loud = build_filter_chain(
        _job(auto_mode=False, reduce_noise=100, revert_compression=0,
             sharpen=0, recover_details=0, dehaloing=0), 1920, 1080)
    q = float(quiet.split("hqdn3d=")[1].split(":")[0])
    l = float(loud.split("hqdn3d=")[1].split(":")[0])
    assert l > q


def test_interpolation_only_when_requested():
    assert "minterpolate" not in build_filter_chain(
        _job(interp_fps=0), 1920, 1080)
    assert "minterpolate=fps=120" in build_filter_chain(
        _job(interp_fps=120), 1920, 1080)


def test_motion_deblur_adds_temporal_sharpen():
    chain = build_filter_chain(_job(motion_deblur=True), 1920, 1080)
    assert "unsharp=7:7" in chain


def test_chain_always_ends_with_encoder_safe_format():
    chain = build_filter_chain(_job(), 1920, 1080)
    assert chain.endswith("format=yuv420p,setsar=1")


# -- encoders + output naming ---------------------------------------------------

def test_encoder_table_shapes():
    for args, suffix, audio in ENCODERS.values():
        assert "-c:v" in args and suffix in (".mp4", ".mov") and audio


def test_output_path_matches_encoder(tmp_path):
    assert _job(target="4K", encoder="H.265",
                output_dir=tmp_path).output_path("my clip.mp4").name \
        == "my clip_4k.mp4"
    assert _job(encoder="ProRes",
                output_dir=tmp_path).output_path("a.mp4").suffix == ".mov"


def test_unicode_filenames_survive(tmp_path):
    out = _job(target="8K", output_dir=tmp_path).output_path("Mənim Video.mp4")
    assert out.name == "Mənim Video_8k.mp4"
    assert out.parent.exists()
