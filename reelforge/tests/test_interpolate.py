"""Interpolation engine selection and plan construction (no GPU needed)."""

from __future__ import annotations

from pathlib import Path

import pytest

from reelforge import interpolate as interp
from reelforge.models import InterpolationEngineKind, JobOptions, RenderTarget

from .support import make_toolchain


def target(fps: int = 120, oversample: int = 1) -> RenderTarget:
    return RenderTarget(
        fps=fps, suffix="t", label="t", crf=17, x264_preset="slow",
        interpolation=InterpolationEngineKind.RIFE, oversample=oversample,
    )


def fake_rife(tmp_path: Path) -> tuple[Path, Path]:
    exe = tmp_path / "rife-ncnn-vulkan"
    exe.write_text("#!/bin/sh\nexit 0\n")
    exe.chmod(0o755)
    models = tmp_path / "models" / "rife-v4.6"
    models.mkdir(parents=True)
    (models / "rife.param").write_text("7767517\n")
    return exe, models


# --------------------------------------------------------------------------- #
# discovery
# --------------------------------------------------------------------------- #


def test_minterpolate_availability_follows_the_filter_list():
    assert interp.MinterpolateEngine().available(make_toolchain(), JobOptions())[0]
    assert not interp.MinterpolateEngine().available(
        make_toolchain(filters={"scale"}), JobOptions()
    )[0]


def test_rife_missing_binary_is_reported():
    engine = interp.RifeNcnnEngine(executable=Path("/nope/rife-ncnn-vulkan"))
    ok, reason = engine.available(make_toolchain(), JobOptions())
    assert not ok
    assert "mövcud deyil" in reason


def test_rife_without_model_directory_is_reported(tmp_path: Path):
    exe = tmp_path / "rife-ncnn-vulkan"
    exe.write_text("#!/bin/sh\n")
    engine = interp.RifeNcnnEngine(executable=exe)
    ok, reason = engine.available(make_toolchain(), JobOptions())
    assert not ok
    assert "model" in reason.lower()


def test_rife_is_detected_with_exe_and_models(tmp_path: Path):
    exe, models = fake_rife(tmp_path)
    engine = interp.RifeNcnnEngine()
    opts = JobOptions(rife_executable=exe, rife_model_dir=models)
    ok, reason = engine.available(make_toolchain(), opts)
    assert ok, reason
    assert "RIFE AI hazırdır" in reason


def test_model_dir_is_auto_discovered_next_to_the_binary(tmp_path: Path):
    exe = tmp_path / "rife-ncnn-vulkan"
    exe.write_text("#!/bin/sh\n")
    models = tmp_path / "models"
    models.mkdir()
    (models / "rife.param").write_text("7767517\n")
    engine = interp.RifeNcnnEngine(executable=exe)
    ok, _ = engine.available(make_toolchain(), JobOptions())
    assert ok


# --------------------------------------------------------------------------- #
# plans
# --------------------------------------------------------------------------- #


def test_rife_plan_targets_an_absolute_frame_count(tmp_path: Path):
    exe, models = fake_rife(tmp_path)
    engine = interp.RifeNcnnEngine()
    opts = JobOptions(rife_executable=exe, rife_model_dir=models)
    plan = engine.plan(
        source=Path("in.mp4"), target=target(120), source_fps=30.0,
        source_frames=60, duration=2.0, toolchain=make_toolchain(),
        opts=opts, workdir=tmp_path / "work",
    )
    assert plan.external is True
    assert len(plan.steps) == 2

    extract, rife = plan.steps
    assert extract.argv[0].endswith("ffmpeg")
    assert "-fps_mode" in extract.argv and "passthrough" in extract.argv
    assert extract.argv[-1].endswith("%08d.png")
    assert "-qscale:v" in extract.argv          # lossless PNG extraction

    assert rife.argv[0] == str(exe)
    n_value = rife.argv[rife.argv.index("-n") + 1]
    assert n_value == "240"                     # 60 frames x4 -> 120 fps
    assert rife.argv[rife.argv.index("-m") + 1] == str(models)
    assert plan.video_input.endswith("%08d.png")
    assert plan.video_input_args[0] == "-framerate"
    assert plan.audio_input == Path("in.mp4")
    assert plan.intermediate_fps == pytest.approx(120.0)


def test_rife_plan_handles_non_integer_ratios(tmp_path: Path):
    exe, models = fake_rife(tmp_path)
    engine = interp.RifeNcnnEngine()
    plan = engine.plan(
        source=Path("in.mp4"), target=target(100), source_fps=30.0,
        source_frames=90, duration=3.0, toolchain=make_toolchain(),
        opts=JobOptions(rife_executable=exe, rife_model_dir=models),
        workdir=tmp_path / "work",
    )
    rife = plan.steps[1]
    assert rife.argv[rife.argv.index("-n") + 1] == "300"   # 90 -> 300 frames


def test_rife_plan_uses_vsync_on_old_ffmpeg(tmp_path: Path):
    exe, models = fake_rife(tmp_path)
    plan = interp.RifeNcnnEngine().plan(
        source=Path("in.mp4"), target=target(120), source_fps=30.0,
        source_frames=60, duration=2.0,
        toolchain=make_toolchain(major=4, minor=4),
        opts=JobOptions(rife_executable=exe, rife_model_dir=models),
        workdir=tmp_path / "work",
    )
    assert "-vsync" in plan.steps[0].argv and "0" in plan.steps[0].argv


def test_vapoursynth_script_is_generated(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(interp, "find_executable", lambda name: Path("/usr/bin/vspipe"))
    engine = interp.VapourSynthRifeEngine(model=12)
    plan = engine.plan(
        source=Path("/tmp/in.mp4"), target=target(120), source_fps=30.0,
        source_frames=60, duration=2.0, toolchain=make_toolchain(),
        opts=JobOptions(), workdir=tmp_path / "work",
    )
    script = tmp_path / "work" / "reelforge_rife.vpy"
    assert script.exists()
    text = script.read_text(encoding="utf-8")
    assert "FPS_NUM = 4" in text and "FPS_DEN = 1" in text
    assert "MODEL = 12" in text
    assert "rife.RIFE(clip, model=MODEL, fps_num=FPS_NUM, fps_den=FPS_DEN" in text
    assert "vsmlrt.RIFE" in text                 # documented fallback

    step = plan.steps[0]
    assert step.argv[:3] == ["/usr/bin/vspipe", "--y4m", str(script)]
    assert step.consumer_argv is not None
    assert "ffv1" in step.consumer_argv          # lossless intermediate


def test_rational_helper():
    assert interp._rational(120.0, 30.0) == (4, 1)
    assert interp._rational(59.94, 29.97) == (2, 1)


# --------------------------------------------------------------------------- #
# resolver
# --------------------------------------------------------------------------- #


def test_auto_falls_back_to_minterpolate_without_rife():
    engine, notes = interp.resolve(
        InterpolationEngineKind.AUTO,
        toolchain=make_toolchain(), opts=JobOptions(rife_executable=Path("/nope")),
    )
    assert engine.name == "minterpolate"
    assert any("minterpolate" in note for note in notes)


def test_auto_prefers_rife_when_installed(tmp_path: Path):
    exe, models = fake_rife(tmp_path)
    engine, notes = interp.resolve(
        InterpolationEngineKind.AUTO,
        toolchain=make_toolchain(),
        opts=JobOptions(rife_executable=exe, rife_model_dir=models),
    )
    assert engine.name == "rife-ncnn-vulkan"


def test_explicit_rife_without_rife_raises():
    with pytest.raises(interp.InterpolationUnavailable):
        interp.resolve(
            InterpolationEngineKind.RIFE,
            toolchain=make_toolchain(), opts=JobOptions(rife_executable=Path("/nope")),
        )


def test_none_returns_passthrough():
    engine, notes = interp.resolve(
        InterpolationEngineKind.NONE, toolchain=make_toolchain(), opts=JobOptions()
    )
    assert engine.name == "none"
    assert notes == []


def test_plan_for_skips_interpolation_for_fast_sources(tmp_path: Path):
    plan = interp.plan_for(
        interp.MinterpolateEngine(), source=Path("in.mp4"), target=target(60),
        source_fps=120.0, source_frames=240, duration=2.0,
        toolchain=make_toolchain(), opts=JobOptions(), workdir=tmp_path,
    )
    assert plan.external is False
    assert plan.steps == []
    assert any("lazım deyil" in note for note in plan.notes)


def test_plan_for_downgrades_to_minterpolate(tmp_path: Path):
    plan = interp.plan_for(
        interp.RifeNcnnEngine(executable=Path("/nope/rife")),
        source=Path("in.mp4"), target=target(120), source_fps=30.0,
        source_frames=60, duration=2.0, toolchain=make_toolchain(),
        opts=JobOptions(), workdir=tmp_path,
    )
    assert plan.engine == "minterpolate"
    assert any("minterpolate-a keçildi" in note for note in plan.notes)


def test_list_engines_reports_all_three():
    engines = dict(
        (name, ok) for name, ok, _ in interp.list_engines(make_toolchain(), JobOptions())
    )
    assert set(engines) == {"rife-ncnn-vulkan", "vapoursynth-rife", "minterpolate"}
    assert engines["minterpolate"] is True
