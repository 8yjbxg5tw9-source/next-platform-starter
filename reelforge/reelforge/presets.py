"""Preset library — the four shipping modes plus a bonus archive master.

A :class:`Preset` is a *pure description*: a tuple of :class:`TargetSpec`
objects.  :meth:`Preset.build_targets` turns those specs into concrete
:class:`~reelforge.models.RenderTarget` instances once we know the source
file (its real frame rate, whether it has audio, whether it is HDR) and the
user's :class:`~reelforge.models.JobOptions`.

The FFmpeg flags each preset produces are documented in ``FFMPEG_REFERENCE.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from .models import (
    Codec,
    InterpolationEngineKind,
    JobOptions,
    MediaInfo,
    MotionBlurMode,
    RenderTarget,
    SharpenMode,
)


@dataclass(frozen=True)
class TargetSpec:
    """One output variant inside a preset."""

    fps: int
    suffix: str
    label: str
    crf: int
    x264_preset: str
    gop_seconds: float = 1.0
    gop_size: Optional[int] = None
    b_frames: int = 2
    profile: str = "high"
    level: str = "4.2"
    tune: Optional[str] = None
    interpolation: InterpolationEngineKind = InterpolationEngineKind.NONE
    oversample: int = 1
    sharpen: SharpenMode = SharpenMode.SHARPEN_OFF
    sharpen_amount: float = 0.0
    motion_blur: MotionBlurMode = MotionBlurMode.OFF
    motion_blur_frames: int = 2
    motion_blur_amount: float = 0.5
    keep_source_fps: bool = False


@dataclass(frozen=True)
class Preset:
    """A user-selectable mode in the GUI / CLI."""

    id: str
    label: str
    tagline: str
    description: str
    specs: Tuple[TargetSpec, ...]
    #: presets whose whole point is frame generation advertise it in the GUI
    interpolates: bool = False
    #: near-lossless presets warn about file size
    heavy: bool = False

    # -- construction ---------------------------------------------------------
    def build_targets(
        self,
        opts: JobOptions,
        info: Optional[MediaInfo] = None,
        codec_override: Optional[Codec] = None,
        crf_override: Optional[int] = None,
        interp_override: Optional[InterpolationEngineKind] = None,
    ) -> List[RenderTarget]:
        """Expand this preset into the concrete list of render targets."""
        specs: Tuple[TargetSpec, ...] = self.specs
        if len(specs) > 1 and not opts.dual_output:
            # user asked for a single file -> keep the highest-quality variant
            specs = (max(specs, key=lambda s: s.fps),)

        src_fps = round(info.fps) if info and info.fps > 0 else 0
        targets: List[RenderTarget] = []
        for spec in specs:
            fps = src_fps if spec.keep_source_fps and src_fps else spec.fps
            if opts.fps_override:
                fps = int(opts.fps_override)
            if fps <= 0:
                fps = 60

            codec = codec_override or opts.codec or Codec.H264
            profile, level = _profile_for(codec, spec, fps)

            interp = (
                interp_override
                or opts.interpolation_override
                or spec.interpolation
            )
            if interp and interp != InterpolationEngineKind.NONE and src_fps:
                # Interpolation is pointless (and lossy) when the source is
                # already at/above the target rate -> degrade to a plain
                # frame-rate conversion instead of throwing the job away.
                if fps <= src_fps:
                    interp = InterpolationEngineKind.NONE

            crf = crf_override if crf_override is not None else (
                opts.crf_override if opts.crf_override is not None else spec.crf
            )
            crf = _clamp_crf(codec, crf)

            targets.append(
                RenderTarget(
                    fps=fps,
                    suffix=spec.suffix,
                    label=spec.label,
                    codec=codec,
                    crf=crf,
                    x264_preset=spec.x264_preset,
                    profile=profile,
                    level=level,
                    gop_seconds=spec.gop_seconds,
                    gop_size=spec.gop_size,
                    b_frames=spec.b_frames,
                    tune=spec.tune,
                    interpolation=interp,
                    oversample=max(1, spec.oversample),
                    sharpen=spec.sharpen,
                    sharpen_amount=spec.sharpen_amount,
                    motion_blur=spec.motion_blur,
                    motion_blur_frames=spec.motion_blur_frames,
                    motion_blur_amount=spec.motion_blur_amount,
                    tonemap_sdr=bool(info and info.is_hdr),
                )
            )
        return targets

    # -- introspection used by the GUI ---------------------------------------
    @property
    def primary_fps(self) -> int:
        return max(s.fps for s in self.specs)

    @property
    def output_fps_list(self) -> List[int]:
        return sorted({s.fps for s in self.specs})


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _profile_for(codec: Codec, spec: TargetSpec, fps: int) -> Tuple[str, str]:
    """HEVC has different profile/level names than H.264."""
    if codec == Codec.HEVC:
        level = "5.1" if fps > 60 else "5.0"
        return "main", level
    profile = spec.profile
    level = spec.level
    if fps > 60 and level in {"4.2", "4.1"}:
        level = "5.1"          # 120 fps 1080p needs H.264 level 5.x
    return profile, level


def _clamp_crf(codec: Codec, crf: int) -> int:
    """x264 CRF is 0-51, x265 is 0-51 too but scales ~+6 for equal quality."""
    lo, hi = (0, 51) if codec == Codec.H264 else (0, 51)
    return max(lo, min(hi, int(crf)))


# --------------------------------------------------------------------------- #
# The shipping presets
# --------------------------------------------------------------------------- #

FAST = Preset(
    id="fast",
    label="Fast Conversion",
    tagline="Sürətli 60FPS — minimum emal",
    description=(
        "x264 preset=fast, CRF 20, 60 FPS. İnterpolyasiya yoxdur: kadr sayı "
        "sadəcə 60-a çatdırılır. Sınaq və kütləvi emal üçün."
    ),
    specs=(
        TargetSpec(
            fps=60,
            suffix="fast",
            label="Fast 60FPS",
            crf=20,
            x264_preset="fast",
            gop_seconds=1.0,
            sharpen=SharpenMode.SHARPEN_OFF,
        ),
    ),
)

SAFE = Preset(
    id="safe",
    label="Safe Mode (TikTok Bypass)",
    tagline="Sabit GOP — TikTok 30FPS-ə salmasın",
    description=(
        "CRF 17, x264 preset=slow, sabit GOP (-g 60 -keyint_min 60 "
        "-sc_threshold 0), CFR 60 FPS, +faststart. TikTok-un videoyu 30 FPS-ə "
        "endirməsinin qarşısını alan strukturdur."
    ),
    specs=(
        TargetSpec(
            fps=60,
            suffix="safe",
            label="TikTok Safe 60FPS",
            crf=17,
            x264_preset="slow",
            gop_seconds=1.0,
            b_frames=2,
            tune="film",
            sharpen=SharpenMode.CAS,
            sharpen_amount=0.5,
        ),
    ),
)

ULTRA_120 = Preset(
    id="ultra120",
    label="Ultra 120FPS Mode",
    tagline="RIFE / minterpolate ilə 120FPS + kəskinlik",
    description=(
        "Mənbə 120 FPS-dən aşağıdırsa RIFE AI (mövcud deyilsə FFmpeg "
        "minterpolate) ilə interpolyasiya olunur, CAS ilə kəskinlik verilir və "
        "CRF 17 / sabit GOP ilə eksport edilir. Həm 60 FPS, həm 120 FPS "
        "variantı yazılır."
    ),
    specs=(
        TargetSpec(
            fps=60,
            suffix="ultra60",
            label="Ultra 60FPS",
            crf=18,
            x264_preset="slow",
            gop_seconds=1.0,
            tune="film",
            interpolation=InterpolationEngineKind.AUTO,
            sharpen=SharpenMode.CAS,
            sharpen_amount=0.6,
        ),
        TargetSpec(
            fps=120,
            suffix="ultra120",
            label="Ultra 120FPS",
            crf=17,
            x264_preset="slow",
            gop_seconds=1.0,
            b_frames=2,
            tune="film",
            interpolation=InterpolationEngineKind.AUTO,
            sharpen=SharpenMode.CAS,
            sharpen_amount=0.8,
        ),
    ),
    interpolates=True,
)

MOTION_BLUR = Preset(
    id="motionblur",
    label="Cinematic Motion Blur",
    tagline="2× oversample + tmix = 180° shutter",
    description=(
        "Kadrlar əvvəl 2× sıxlığa interpolyasiya olunur, tmix ilə 2 kadr "
        "birləşdirilir (tmix/tblend), sonra 60 FPS-ə endirilir. Nəticə: təbii "
        "180° shutter motion blur + CAS ilə bərpa olunmuş kəskinlik."
    ),
    specs=(
        TargetSpec(
            fps=60,
            suffix="blur60",
            label="Cinematic Blur 60FPS",
            crf=18,
            x264_preset="slow",
            gop_seconds=1.0,
            tune="film",
            interpolation=InterpolationEngineKind.MINTERPOLATE,
            oversample=2,
            motion_blur=MotionBlurMode.TMIX,
            motion_blur_frames=2,
            sharpen=SharpenMode.CAS,
            sharpen_amount=0.6,
        ),
    ),
    interpolates=True,
)

MASTER = Preset(
    id="master",
    label="Archive Master (near-lossless)",
    tagline="CRF 12 · mənbə FPS · arxiv üçün",
    description=(
        "Sosial şəbəkə üçün deyil, arxiv üçün: mənbə kadr sürəti saxlanılır, "
        "CRF 12 (demək olar ki, itkisiz), x264 preset=veryslow. Fayl ölçüsü "
        "böyük olur."
    ),
    specs=(
        TargetSpec(
            fps=60,
            suffix="master",
            label="Archive Master",
            crf=12,
            x264_preset="veryslow",
            gop_seconds=2.0,
            tune="film",
            sharpen=SharpenMode.SHARPEN_OFF,
            keep_source_fps=True,
        ),
    ),
    heavy=True,
)


ALL_PRESETS: Tuple[Preset, ...] = (FAST, SAFE, ULTRA_120, MOTION_BLUR, MASTER)


class Presets:
    """Namespace so callers can write ``Presets.ULTRA_120``."""

    FAST = FAST
    SAFE = SAFE
    ULTRA_120 = ULTRA_120
    MOTION_BLUR = MOTION_BLUR
    MASTER = MASTER

    ALL: Tuple[Preset, ...] = ALL_PRESETS

    @classmethod
    def by_id(cls, preset_id: str) -> Preset:
        key = str(preset_id).strip().lower().replace("-", "").replace("_", "")
        for p in cls.ALL:
            if p.id == key:
                return p
        aliases = {
            "fast": cls.FAST,
            "tiktok": cls.SAFE,
            "safe": cls.SAFE,
            "bypass": cls.SAFE,
            "ultra": cls.ULTRA_120,
            "120": cls.ULTRA_120,
            "ultra120": cls.ULTRA_120,
            "blur": cls.MOTION_BLUR,
            "cinematic": cls.MOTION_BLUR,
            "master": cls.MASTER,
            "archive": cls.MASTER,
        }
        if key in aliases:
            return aliases[key]
        raise KeyError(
            f"unknown preset {preset_id!r}; valid: {', '.join(p.id for p in cls.ALL)}"
        )

    @classmethod
    def choices(cls) -> List[str]:
        return [p.id for p in cls.ALL]
