"""Filtergraph construction — the exact FFmpeg filter chain per render target.

The chain is always emitted in this fixed order, because the order *is* the
image quality:

    geometry -> (HDR tonemap) -> interpolation -> motion blur -> fps lock
              -> sharpening -> pixel format -> colour metadata

Every helper is a pure function returning filter strings, which makes the
generated command line trivially unit-testable and copy-pasteable into a
terminal (``FFMPEG_REFERENCE.md`` lists the canonical commands).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .models import (
    ColorTag,
    FitMode,
    InterpolationEngineKind,
    JobOptions,
    MediaInfo,
    MotionBlurMode,
    RenderTarget,
    SharpenMode,
)
from .toolchain import Toolchain


class FilterGraphError(ValueError):
    """A requested filter is not present in this ffmpeg build."""


# --------------------------------------------------------------------------- #
# container
# --------------------------------------------------------------------------- #


@dataclass
class FilterGraph:
    """A linear ``-vf`` chain."""

    nodes: List[str]

    def __post_init__(self) -> None:
        self.notes: List[str] = []

    def add(self, node: str) -> "FilterGraph":
        if node:
            self.nodes.append(node.strip().rstrip(","))
        return self

    def note(self, text: str) -> "FilterGraph":
        self.notes.append(text)
        return self

    @property
    def is_empty(self) -> bool:
        return not self.nodes

    def build(self) -> str:
        """Return the string that goes after ``-vf``."""
        return ",".join(self.nodes)


# --------------------------------------------------------------------------- #
# geometry
# --------------------------------------------------------------------------- #


def geometry_filters(
    opts: JobOptions,
    info: Optional[MediaInfo],
    *,
    scaler: Optional[str] = None,
) -> List[str]:
    """Scale/crop/pad the source onto the requested canvas.

    ``FitMode.KEEP`` emits nothing unless the source has odd dimensions, which
    H.264/HEVC in yuv420p cannot encode.
    """
    flags = f":flags={scaler or opts.scaler or 'lanczos'}"
    w = opts.target_width
    h = opts.target_height
    nodes: List[str] = []

    if opts.fit == FitMode.KEEP or not (w and h):
        if info and info.width and info.height and (info.width % 2 or info.height % 2):
            nodes.append("scale=trunc(iw/2)*2:trunc(ih/2)*2")
            nodes.append("setsar=1")
        return nodes

    if opts.fit == FitMode.COVER:
        # fill the frame, then crop the overflow from the centre
        nodes += [
            f"scale={w}:{h}:force_original_aspect_ratio=increase{flags}",
            f"crop={w}:{h}",
        ]
    elif opts.fit == FitMode.CONTAIN:
        nodes += [
            f"scale={w}:{h}:force_original_aspect_ratio=decrease{flags}",
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black",
        ]
    elif opts.fit == FitMode.STRETCH:
        nodes.append(f"scale={w}:{h}{flags}")
    else:  # pragma: no cover - enum is exhaustive
        raise FilterGraphError(f"naməlum fit rejimi: {opts.fit}")

    nodes.append("setsar=1")
    return nodes


# --------------------------------------------------------------------------- #
# HDR -> SDR
# --------------------------------------------------------------------------- #

HDR_TONEMAP_CHAIN = (
    "zscale=t=linear:npl=100",
    "format=gbrpf32le",
    "zscale=p=bt709",
    "tonemap=tonemap=hable:desat=0",
    "zscale=t=bt709:m=bt709:r=bt709:range=tv",
)


def tonemap_filters(info: Optional[MediaInfo], toolchain: Toolchain, graph: FilterGraph) -> List[str]:
    """HDR (PQ/HLG) sources are converted to Rec.709 SDR before encoding.

    Social platforms re-encode SDR; uploading untouched HDR usually results in
    washed-out or grey output, so the tonemap is applied automatically.
    """
    if not info or not info.is_hdr:
        return []
    if not toolchain.supports_zscale:
        graph.note(
            "HDR mənbə aşkarlandı, amma bu ffmpeg build-də zscale/tonemap yoxdur — "
            "rənglər solğun görünə bilər."
        )
        return []
    graph.note("HDR -> Rec.709 SDR tonemap tətbiq olundu (hable).")
    return list(HDR_TONEMAP_CHAIN)


# --------------------------------------------------------------------------- #
# interpolation
# --------------------------------------------------------------------------- #

MINTERPOLATE_PROFILES = {
    # cheap: cross-fade between neighbours (visible ghosting on fast motion)
    "fast": "mi_mode=blend:scd=none",
    # default: motion-compensated, adaptive OBMC, bidirectional ME
    "balanced": "mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1:scd=fdiff:scd_threshold=8",
    # best: same + smaller macroblocks (slower, fewer edge artefacts)
    "quality": (
        "mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1:"
        "scd=fdiff:scd_threshold=6:mb_size=8"
    ),
}


def minterpolate_filter(rate: float, quality: str = "balanced") -> str:
    """``minterpolate=...`` string for the requested output rate."""
    profile = MINTERPOLATE_PROFILES.get(str(quality).lower(), MINTERPOLATE_PROFILES["balanced"])
    return f"minterpolate=fps={_rate_str(rate)}:{profile}"


def fps_filter(rate: float, *, round_mode: str = "near") -> str:
    """Lock the output to a constant frame rate (CFR)."""
    return f"fps={_rate_str(rate)}:round={round_mode}"


def _rate_str(rate: float) -> str:
    """60.0 -> ``60``; 59.94 -> ``60000/1001``-style exact rational."""
    rounded = round(rate, 3)
    if abs(rounded - round(rounded)) < 1e-6:
        return str(int(round(rounded)))
    for num, den in ((60000, 1001), (30000, 1001), (24000, 1001), (120000, 1001)):
        if abs(rounded - num / den) < 0.01:
            return f"{num}/{den}"
    return f"{rounded:.4f}".rstrip("0").rstrip(".")


# --------------------------------------------------------------------------- #
# motion blur
# --------------------------------------------------------------------------- #


def motion_blur_filters(
    target: RenderTarget, toolchain: Toolchain, graph: FilterGraph
) -> List[str]:
    """Cinematic shutter simulation.

    ``tmix``  – averages N consecutive frames, keeps the frame count.  Combined
                with 2x oversampling this yields a true 180 degree shutter.
    ``tblend``– blends frame N with N+1 and therefore halves the frame rate, so
                a following ``fps`` filter restores it.
    ``mblur`` – dedicated motion-blur filter; only in some builds.
    """
    mode = target.motion_blur
    if mode == MotionBlurMode.OFF:
        return []

    if mode == MotionBlurMode.TMIX:
        frames = max(1, int(target.motion_blur_frames))
        weights = " ".join(["1"] * frames)
        return [f"tmix=frames={frames}:weights={weights}"]

    if mode == MotionBlurMode.TBLEND:
        return ["tblend=all_mode=average"]

    if mode == MotionBlurMode.MBLUR:
        if toolchain.supports_mblur:
            amount = max(0.0, min(1.0, float(target.motion_blur_amount)))
            return [f"mblur={amount}"]
        graph.note(
            "mblur filtri bu ffmpeg build-də yoxdur — tmix ilə əvəz olundu."
        )
        frames = max(1, int(target.motion_blur_frames))
        return [f"tmix=frames={frames}:weights={' '.join(['1'] * frames)}"]

    raise FilterGraphError(f"naməlum motion blur rejimi: {mode}")  # pragma: no cover


# --------------------------------------------------------------------------- #
# sharpening
# --------------------------------------------------------------------------- #


def sharpen_filters(
    target: RenderTarget, toolchain: Toolchain, graph: FilterGraph
) -> List[str]:
    mode = target.sharpen
    amount = float(target.sharpen_amount)
    if mode == SharpenMode.SHARPEN_OFF or amount <= 0:
        return []

    if mode == SharpenMode.CAS:
        if toolchain.supports_cas:
            clamped = max(0.0, min(1.0, amount))
            return [f"cas=strength={clamped:.3f}".rstrip("0").rstrip(".")]
        graph.note("cas filtri yoxdur — unsharp ilə əvəz olundu.")
        return [_unsharp(amount * 0.8)]

    if mode == SharpenMode.UNSHARP:
        return [_unsharp(amount)]

    raise FilterGraphError(f"naməlum sharpen rejimi: {mode}")  # pragma: no cover


def _unsharp(amount: float) -> str:
    luma = max(-2.0, min(5.0, amount))
    return (
        f"unsharp=luma_msize_x=5:luma_msize_y=5:luma_amount={luma:.3f}"
        ":chroma_msize_x=5:chroma_msize_y=5:chroma_amount=0"
    )


# --------------------------------------------------------------------------- #
# colour / format
# --------------------------------------------------------------------------- #


def format_filters(opts: JobOptions) -> List[str]:
    """``yuv420p`` + explicit bt709 tagging (both required by the platforms)."""
    nodes = ["format=yuv420p"]
    tag = opts.color_tag or ColorTag.BT709
    rng = "tv" if opts.limited_range else "pc"
    nodes.append(
        f"setparams=color_primaries={tag}:color_trc={tag}:colorspace={tag}:range={rng}"
    )
    return nodes


# --------------------------------------------------------------------------- #
# the whole graph
# --------------------------------------------------------------------------- #


@dataclass
class FilterPlan:
    """The video filter chain plus the input the encoder should read."""

    graph: FilterGraph
    #: rate the *interpolation* stage has to hit (target fps x oversample)
    interp_rate: float
    #: ``True`` when interpolation is handled outside the graph (RIFE)
    external_interpolation: bool = False


def build_filter_plan(
    target: RenderTarget,
    opts: JobOptions,
    info: Optional[MediaInfo],
    toolchain: Toolchain,
    *,
    external_interpolation: bool = False,
) -> FilterPlan:
    """Assemble the complete ``-vf`` chain for one render target.

    ``external_interpolation`` is set when an outside tool (RIFE) already
    produced the extra frames, in which case no ``minterpolate`` node is added
    and the graph starts from the already-interpolated stream.
    """
    graph = FilterGraph([])
    src_fps = float(info.fps) if info and info.fps else 0.0
    interp_rate = float(target.fps) * max(1, int(target.oversample))

    # 1) geometry ---------------------------------------------------------
    for node in geometry_filters(opts, info):
        graph.add(node)

    # 2) HDR -> SDR -------------------------------------------------------
    for node in tonemap_filters(info, toolchain, graph):
        graph.add(node)

    # 3) frame generation -------------------------------------------------
    needs_interp = bool(src_fps) and interp_rate > src_fps * 1.02
    if (
        needs_interp
        and not external_interpolation
        and target.interpolation == InterpolationEngineKind.MINTERPOLATE
        and toolchain.has_filter("minterpolate")
    ):
        graph.add(minterpolate_filter(interp_rate, opts.interpolation_quality))
        graph.note(
            f"minterpolate: {src_fps:.2f}fps -> {interp_rate:g}fps "
            f"({opts.interpolation_quality})"
        )
    elif needs_interp and target.interpolation == InterpolationEngineKind.MINTERPOLATE:
        graph.note("minterpolate filtri bu build-də yoxdur — kadrlar dublikasiya olunacaq.")

    # 4) motion blur ------------------------------------------------------
    for node in motion_blur_filters(target, toolchain, graph):
        graph.add(node)

    # 5) lock the output rate (also repairs tblend's halved rate and the
    #    non-integer rate coming back from an external RIFE pass) ----------
    if (
        external_interpolation
        or interp_rate != float(target.fps)
        or needs_interp
        or target.motion_blur != MotionBlurMode.OFF
    ):
        graph.add(fps_filter(target.fps))

    # 6) sharpening -------------------------------------------------------
    for node in sharpen_filters(target, toolchain, graph):
        graph.add(node)

    # 7) pixel format + colour metadata ----------------------------------
    for node in format_filters(opts):
        graph.add(node)

    return FilterPlan(
        graph=graph,
        interp_rate=interp_rate,
        external_interpolation=external_interpolation,
    )
