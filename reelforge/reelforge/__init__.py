"""ReelForge — 60/120 FPS short-form video studio (TikTok / Reels / Shorts).

ReelForge is a Python re-implementation of the "Decoy 60FPS" workflow plus two
features that tool does not have: **120 FPS interpolation** (RIFE AI or
FFmpeg ``minterpolate``) and **HQ transcoding** (CRF 17-20, fixed GOP,
bt709 tagging, faststart).

Public API:

>>> from reelforge import ReelForge, Presets, JobOptions
>>> app = ReelForge()                       # locates ffmpeg/ffprobe
>>> info = app.probe("clip.mp4")
>>> result = app.run("clip.mp4", Presets.ULTRA_120, JobOptions(output_dir="out"))

The GUI lives in :mod:`reelforge.gui.app`; the headless entry point is
:mod:`reelforge.cli` (``python -m reelforge.cli``).
"""

from __future__ import annotations

from .models import (
    ColorTag,
    Codec,
    FitMode,
    InterpolationEngineKind,
    JobOptions,
    JobResult,
    MediaInfo,
    MotionBlurMode,
    ProgressInfo,
    RenderTarget,
    SharpenMode,
    StreamInfo,
    VerifyReport,
)
from .presets import Preset, Presets
from .probe import ProbeError
from .probe import probe as probe_media   # aliased: `reelforge.probe` must stay the module
from .toolchain import Toolchain, ToolchainError, find_toolchain
from .pipeline import Pipeline, PipelineError, ReelForge

__version__ = "1.0.0"

__all__ = [
    "ColorTag",
    "Codec",
    "FitMode",
    "InterpolationEngineKind",
    "JobOptions",
    "JobResult",
    "MediaInfo",
    "MotionBlurMode",
    "Pipeline",
    "PipelineError",
    "Preset",
    "Presets",
    "ProbeError",
    "ProgressInfo",
    "ReelForge",
    "RenderTarget",
    "SharpenMode",
    "StreamInfo",
    "Toolchain",
    "ToolchainError",
    "VerifyReport",
    "__version__",
    "find_toolchain",
    "probe_media",
]
