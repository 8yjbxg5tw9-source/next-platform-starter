"""End-to-end render through the real engine with the bundled ffmpeg.

Exercises: probe -> target planning -> filter chain -> argv build -> worker
run/progress -> output verification, plus the cancel path.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from akai import ffmpeg_tools
from akai.engine import RenderJob, RenderWorker
from akai.ffmpeg_tools import probe

pytestmark = pytest.mark.skipif(sys.platform.startswith("win"), reason="linux sandbox")


@pytest.fixture(scope="module")
def sample(tmp_path_factory) -> Path:
    ffmpeg = ffmpeg_tools.find_ffmpeg()
    out = tmp_path_factory.mktemp("src") / "input.mp4"
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", "testsrc=size=320x180:rate=15",
                    "-t", "2", "-pix_fmt", "yuv420p", str(out)],
                   check=True, capture_output=True)
    return out


def test_probe_reads_source(sample):
    info = probe(sample)
    assert info.width == 320 and info.height == 180
    assert info.duration >= 1.5


def test_render_upscale_to_640(sample, tmp_path):
    job = RenderJob(source=sample, output_dir=tmp_path, target="CUSTOM",
                    custom_size=(640, 360), encoder="H.264",
                    auto_mode=True)
    worker = RenderWorker(job)
    worker.run()
    assert worker.error is None, worker.error
    assert worker.output is not None and worker.output.exists()
    result = probe(worker.output)
    assert result.width == 640 and result.height == 360
    assert result.duration >= 1.5


def test_render_cancel_path(sample, tmp_path):
    job = RenderJob(source=sample, output_dir=tmp_path, target="1080p",
                    encoder="H.264")
    worker = RenderWorker(job)
    worker.cancel()  # pre-cancelled: worker must stop and report cleanly
    worker.run()
    assert worker.output is None
    assert worker.error == "Render dayandırıldı"


def test_render_reports_progress(sample, tmp_path):
    seen = []
    job = RenderJob(source=sample, output_dir=tmp_path, target="CUSTOM",
                    custom_size=(640, 360))
    worker = RenderWorker(job, progress_cb=lambda f, m: seen.append((f, m)))
    worker.run()
    assert worker.error is None, worker.error
    fractions = [f for f, _ in seen]
    assert fractions and all(0.0 <= f <= 1.0 for f in fractions)
    assert fractions[-1] == 1.0


def test_missing_source_yields_error_not_crash(tmp_path):
    job = RenderJob(source=tmp_path / "yoxdur.mp4", output_dir=tmp_path)
    worker = RenderWorker(job)
    worker.run()
    assert worker.output is None
    assert worker.error and "xətası" in worker.error
