"""Shared fixtures.

The backend needs a real ``ffmpeg`` binary for the end-to-end tests; when one
is missing those tests skip with an explicit reason instead of failing.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reelforge.toolchain import Toolchain, ToolchainError, find_toolchain  # noqa: E402


@pytest.fixture(scope="session")
def toolchain() -> Toolchain:
    try:
        return find_toolchain()
    except ToolchainError as exc:  # pragma: no cover
        pytest.skip(f"ffmpeg yoxdur: {exc}")


@pytest.fixture(scope="session")
def sample_clip(toolchain: Toolchain, tmp_path_factory) -> Path:
    """2 seconds of 30 fps 320x568 test footage with a sine track."""
    import subprocess

    out = tmp_path_factory.mktemp("media") / "sample.mp4"
    cmd = [
        str(toolchain.ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc2=size=320x568:rate=30:duration=2",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-shortest", str(out),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return out
