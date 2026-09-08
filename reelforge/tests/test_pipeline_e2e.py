"""End-to-end tests: real ffmpeg encodes, then QA on the produced files.

These exercise the whole chain — probe -> plan -> minterpolate -> filters ->
encode -> verify — so a regression in any module shows up here, not just in a
unit assertion.  They are skipped when no ffmpeg binary is installed.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from reelforge.models import Codec, FitMode, JobOptions
from reelforge.pipeline import Pipeline, ReelForge
from reelforge.presets import Presets
from reelforge.probe import count_frames, probe
from reelforge.toolchain import Toolchain


def frame_luma(path: Path, toolchain: Toolchain, index: int) -> bytes:
    """Raw luma plane of one decoded frame."""
    cmd = [
        str(toolchain.ffmpeg), "-hide_banner", "-nostdin", "-loglevel", "error",
        "-i", str(path), "-vf", f"select=eq(n\\,{index})", "-frames:v", "1",
        "-f", "rawvideo", "-pix_fmt", "gray", "-",
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    assert proc.stdout, f"kadr {index} oxunmadı: {path}"
    return proc.stdout


def frame_motion(path: Path, toolchain: Toolchain, start: int = 60, count: int = 6) -> list:
    """Mean absolute luma difference between each pair of consecutive frames.

    Duplicated frames give ~0.0, interpolated frames give a steady non-zero
    value — this is how we tell real interpolation from frame duplication.
    """
    frames = [frame_luma(path, toolchain, start + i) for i in range(count + 1)]
    return [
        sum(abs(a - b) for a, b in zip(frames[i], frames[i + 1])) / len(frames[i])
        for i in range(count)
    ]


def run(toolchain: Toolchain, source: Path, preset, opts: JobOptions):
    logs = []
    pipeline = Pipeline(toolchain, log_callback=logs.append)
    result = pipeline.run(source, preset, opts)
    assert result.ok, f"{result.error}\n" + "\n".join(logs[-25:])
    return result, logs


# --------------------------------------------------------------------------- #
# Safe Mode — the TikTok anti-downscale structure
# --------------------------------------------------------------------------- #


def test_safe_mode_produces_cfr_60fps_with_one_second_gop(
    toolchain: Toolchain, sample_clip: Path, tmp_path: Path
):
    result, _ = run(toolchain, sample_clip, Presets.SAFE, JobOptions(output_dir=tmp_path))

    assert len(result.outputs) == 1
    out = result.outputs[0]
    assert out.path.exists() and out.size_bytes > 10_000

    info = probe(out.path, toolchain)
    assert info.fps == pytest.approx(60.0, abs=0.2)
    assert info.video.codec_name == "h264"
    assert info.video.profile == "High"
    assert info.video.pix_fmt == "yuv420p"
    assert info.video.color_primaries == "bt709"
    assert count_frames(out.path, toolchain) == 120      # 2 s x 60 fps

    verify = out.verify
    assert verify is not None and verify.ok, verify.warnings
    # a 2 s file with a 1 s GOP has keyframes at 0.0 and 1.0
    assert verify.keyframe_gaps == pytest.approx([1.0], abs=0.06)

    text = " ".join(out.command)
    assert "-g 60" in text and "-keyint_min 60" in text and "-sc_threshold 0" in text


def test_safe_mode_audio_is_reencoded_to_aac(
    toolchain: Toolchain, sample_clip: Path, tmp_path: Path
):
    result, _ = run(toolchain, sample_clip, Presets.SAFE, JobOptions(output_dir=tmp_path))
    info = probe(result.outputs[0].path, toolchain)
    assert info.audio.codec_name == "aac"
    assert info.audio.sample_rate == 48000


def test_json_report_is_written_and_parseable(
    toolchain: Toolchain, sample_clip: Path, tmp_path: Path
):
    result, _ = run(toolchain, sample_clip, Presets.FAST, JobOptions(output_dir=tmp_path))
    assert result.report_path and result.report_path.exists()
    data = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert data["ok"] is True
    assert data["outputs"][0]["fps"] == 60
    assert data["outputs"][0]["command"][0].endswith("ffmpeg") or "ffmpeg" in data["outputs"][0]["command"][0]


# --------------------------------------------------------------------------- #
# Ultra 120FPS — dual output + interpolation
# --------------------------------------------------------------------------- #


def test_ultra_120_writes_both_variants(
    toolchain: Toolchain, sample_clip: Path, tmp_path: Path
):
    result, logs = run(
        toolchain, sample_clip, Presets.ULTRA_120, JobOptions(output_dir=tmp_path)
    )

    assert [o.target.fps for o in result.outputs] == [60, 120]
    for out in result.outputs:
        assert out.path.exists()
        info = probe(out.path, toolchain)
        assert info.fps == pytest.approx(float(out.target.fps), abs=0.3)
        assert count_frames(out.path, toolchain) == out.target.fps * 2

    assert count_frames(result.outputs[1].path, toolchain) == 240
    # AUTO must have resolved to a real engine and landed in the -vf chain
    chain = " ".join(result.outputs[1].command)
    assert "minterpolate=fps=120" in chain
    assert any("İnterpolyasiya mühərriki" in line for line in logs)


def test_plan_writes_the_resolved_engine_back_onto_the_target(
    toolchain: Toolchain, sample_clip: Path, tmp_path: Path
):
    """AUTO must become a concrete engine kind before the filter chain is built."""
    from reelforge.models import InterpolationEngineKind

    info = probe(sample_clip, toolchain)
    items, total_steps = Pipeline(toolchain).plan(
        sample_clip, Presets.ULTRA_120, JobOptions(output_dir=tmp_path), info, tmp_path
    )
    kinds = [target.interpolation for target, _, _, _ in items]
    assert kinds == [InterpolationEngineKind.MINTERPOLATE] * 2
    assert InterpolationEngineKind.AUTO not in kinds
    assert total_steps == 2                      # one encode step per target


def test_ultra_120_generates_new_frames_instead_of_duplicating(
    toolchain: Toolchain, sample_clip: Path, tmp_path: Path
):
    """Regression: AUTO used to leave `minterpolate` out, so 120fps was just
    duplicated 30fps frames.  Every consecutive pair must now show motion."""
    result, _ = run(
        toolchain, sample_clip, Presets.ULTRA_120, JobOptions(output_dir=tmp_path)
    )
    for out in result.outputs:
        motion = frame_motion(out.path, toolchain)
        assert min(motion) > 0.3, (
            f"{out.target.fps}fps çıxışında dublikat kadrlar var: {motion}"
        )


def test_fast_preset_duplicates_frames_by_design(
    toolchain: Toolchain, sample_clip: Path, tmp_path: Path
):
    """The Fast preset deliberately does not interpolate: 30 -> 60 fps means
    each source frame appears twice, so every other pair is (near) identical."""
    result, _ = run(toolchain, sample_clip, Presets.FAST, JobOptions(output_dir=tmp_path))
    out = result.outputs[0]
    assert "minterpolate" not in " ".join(out.command)
    motion = frame_motion(out.path, toolchain)
    assert min(motion) < 0.3, f"dublikat gözlənilirdi, amma hər kadr fərqlidir: {motion}"
    assert max(motion) > 1.0, "mənbə hərəkətsizdir — test mənasızdır"


def test_ultra_120_single_variant_when_dual_disabled(
    toolchain: Toolchain, sample_clip: Path, tmp_path: Path
):
    result, _ = run(
        toolchain, sample_clip, Presets.ULTRA_120,
        JobOptions(output_dir=tmp_path, dual_output=False),
    )
    assert [o.target.fps for o in result.outputs] == [120]


# --------------------------------------------------------------------------- #
# Cinematic motion blur
# --------------------------------------------------------------------------- #


def test_motion_blur_keeps_the_requested_rate(
    toolchain: Toolchain, sample_clip: Path, tmp_path: Path
):
    result, logs = run(
        toolchain, sample_clip, Presets.MOTION_BLUR, JobOptions(output_dir=tmp_path)
    )
    out = result.outputs[0]
    info = probe(out.path, toolchain)
    assert info.fps == pytest.approx(60.0, abs=0.3)
    assert count_frames(out.path, toolchain) == 120
    assert any("tmix" in line for line in logs)


# --------------------------------------------------------------------------- #
# options that change the command line
# --------------------------------------------------------------------------- #


def test_hevc_output_is_tagged_hvc1(
    toolchain: Toolchain, sample_clip: Path, tmp_path: Path
):
    if not toolchain.supports_hevc:
        pytest.skip("libx265 yoxdur")
    result, _ = run(
        toolchain, sample_clip, Presets.FAST,
        JobOptions(output_dir=tmp_path, codec=Codec.HEVC),
    )
    info = probe(result.outputs[0].path, toolchain)
    assert info.video.codec_name == "hevc"
    assert "-tag:v hvc1" in " ".join(result.outputs[0].command)
    assert "-x265-params" in result.outputs[0].command


def test_cover_fit_resizes_to_the_target_canvas(
    toolchain: Toolchain, sample_clip: Path, tmp_path: Path
):
    result, _ = run(
        toolchain, sample_clip, Presets.FAST,
        JobOptions(output_dir=tmp_path, fit=FitMode.COVER,
                   target_width=270, target_height=480),
    )
    info = probe(result.outputs[0].path, toolchain)
    assert (info.width, info.height) == (270, 480)


def test_crf_override_reaches_the_command(
    toolchain: Toolchain, sample_clip: Path, tmp_path: Path
):
    result, _ = run(
        toolchain, sample_clip, Presets.SAFE,
        JobOptions(output_dir=tmp_path, crf_override=25),
    )
    assert "-crf 25" in " ".join(result.outputs[0].command)
    # ...and the preset default (17) must not be there
    assert "-crf 17" not in " ".join(result.outputs[0].command)


def test_dry_run_writes_nothing(
    toolchain: Toolchain, sample_clip: Path, tmp_path: Path
):
    result, _ = run(
        toolchain, sample_clip, Presets.ULTRA_120,
        JobOptions(output_dir=tmp_path, dry_run=True),
    )
    assert [o.target.fps for o in result.outputs] == [60, 120]
    for out in result.outputs:
        assert not out.path.exists()
    assert list(tmp_path.glob("*.mp4")) == []


def test_temp_directory_is_cleaned_up(
    toolchain: Toolchain, sample_clip: Path, tmp_path: Path
):
    run(toolchain, sample_clip, Presets.ULTRA_120, JobOptions(output_dir=tmp_path))
    assert not (tmp_path / ".reelforge_tmp").exists()


# --------------------------------------------------------------------------- #
# facade
# --------------------------------------------------------------------------- #


def test_build_commands_matches_what_runs(
    toolchain: Toolchain, sample_clip: Path, tmp_path: Path
):
    app = ReelForge.__new__(ReelForge)          # reuse the session toolchain
    app.toolchain = toolchain
    app.log_callback = None
    app.progress_callback = None
    import threading

    app.cancel_event = threading.Event()

    opts = JobOptions(output_dir=tmp_path)
    planned = app.build_commands(sample_clip, Presets.SAFE, opts)
    assert len(planned) == 1
    result, _ = run(toolchain, sample_clip, Presets.SAFE, opts)
    assert planned[0] == result.outputs[0].command
