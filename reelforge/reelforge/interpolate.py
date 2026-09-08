"""Frame interpolation engines: RIFE (AI) and FFmpeg ``minterpolate``.

Engines are pluggable and *all* of them return a declarative
:class:`InterpolationPlan` instead of running anything themselves — the
pipeline owns subprocess execution, progress and cancellation.

Three engines ship with ReelForge:

``RifeNcnnEngine``
    nihui's ``rife-ncnn-vulkan``.  Lossless PNG frames in, PNG frames out.
    ``-n`` is the **target frame count**, so arbitrary rates work
    (30 fps -> 120 fps == ``-n <frames*4>``).  Needs a Vulkan GPU.
``VapourSynthRifeEngine``
    ``vspipe`` + ``VapourSynth-RIFE-ncnn-Vulkan`` (``rife.RIFE``), using
    ``fps_num``/``fps_den`` for an exact target rate; falls back to
    ``vsmlrt.RIFE`` (``factor_num``/``factor_den``).
``MinterpolateEngine``
    Pure FFmpeg ``minterpolate`` — always available, no GPU, slower and with
    more edge artefacts, but it never fails to exist.

:func:`resolve` implements the AUTO policy: RIFE when it is really installed,
``minterpolate`` otherwise (with the reason logged so the user knows why).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from .models import InterpolationEngineKind, JobOptions, RenderTarget
from .toolchain import Toolchain, find_executable


class InterpolationUnavailable(RuntimeError):
    """The requested engine cannot run on this machine."""


@dataclass
class CommandStep:
    """One subprocess the pipeline must run *before* the final encode.

    ``consumer_argv`` turns the step into a shell-free pipe:
    ``producer.stdout -> consumer.stdin`` (used for ``vspipe --y4m ... -``).
    """

    argv: List[str]
    phase: str
    expected_duration: float = 0.0
    cwd: Optional[Path] = None
    consumer_argv: Optional[List[str]] = None


@dataclass
class InterpolationPlan:
    """What the encoder should read, and what had to happen to get there."""

    engine: str
    external: bool                      # True -> frames already generated
    video_input: str                    # file or ``%08d.png`` pattern
    video_input_args: List[str] = field(default_factory=list)
    audio_input: Optional[Path] = None  # audio taken from the original file
    steps: List[CommandStep] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    intermediate_fps: float = 0.0

    @property
    def has_steps(self) -> bool:
        return bool(self.steps)


# --------------------------------------------------------------------------- #
# engine interface
# --------------------------------------------------------------------------- #


class InterpolationEngine:
    """Base class — subclasses are stateless and cheap to construct."""

    name: str = "base"
    kind: InterpolationEngineKind = InterpolationEngineKind.NONE

    def available(self, toolchain: Toolchain, opts: JobOptions) -> Tuple[bool, str]:
        raise NotImplementedError

    def plan(self, **kwargs) -> InterpolationPlan:
        raise NotImplementedError


def _passthrough(source: Path, engine: str, note: str = "") -> InterpolationPlan:
    return InterpolationPlan(
        engine=engine,
        external=False,
        video_input=str(source),
        notes=[note] if note else [],
    )


# --------------------------------------------------------------------------- #
# none / minterpolate (both stay inside the -vf graph)
# --------------------------------------------------------------------------- #


class NoInterpolationEngine(InterpolationEngine):
    name = "none"
    kind = InterpolationEngineKind.NONE

    def available(self, toolchain: Toolchain, opts: JobOptions) -> Tuple[bool, str]:
        return True, "kadr sürəti olduğu kimi saxlanılır"

    def plan(self, **kwargs) -> InterpolationPlan:  # type: ignore[override]
        return _passthrough(kwargs["source"], self.name, "İnterpolyasiya yoxdur.")


class MinterpolateEngine(InterpolationEngine):
    """Adds ``minterpolate`` to the ``-vf`` chain — no extra subprocess."""

    name = "minterpolate"
    kind = InterpolationEngineKind.MINTERPOLATE

    def available(self, toolchain: Toolchain, opts: JobOptions) -> Tuple[bool, str]:
        if toolchain.has_filter("minterpolate"):
            return True, "ffmpeg minterpolate hazırdır"
        return False, "bu ffmpeg build-də minterpolate filtri yoxdur"

    def plan(self, **kwargs) -> InterpolationPlan:  # type: ignore[override]
        return _passthrough(
            kwargs["source"], self.name, "minterpolate -vf zəncirinə əlavə olunacaq."
        )


# --------------------------------------------------------------------------- #
# RIFE — rife-ncnn-vulkan
# --------------------------------------------------------------------------- #


class RifeNcnnEngine(InterpolationEngine):
    """``rife-ncnn-vulkan -i frames_in -o frames_out -n <target frames> -m model``"""

    name = "rife-ncnn-vulkan"
    kind = InterpolationEngineKind.RIFE

    def __init__(self, executable: Optional[Path] = None, model_dir: Optional[Path] = None):
        self._executable = executable
        self._model_dir = model_dir

    # -- discovery ----------------------------------------------------------
    def resolve_paths(self, opts: JobOptions) -> Tuple[Optional[Path], Optional[Path]]:
        exe = (
            Path(self._executable)
            if self._executable
            else Path(opts.rife_executable)
            if opts.rife_executable
            else find_executable("rife-ncnn-vulkan")
        )
        model_dir = (
            Path(self._model_dir)
            if self._model_dir
            else Path(opts.rife_model_dir) if opts.rife_model_dir else None
        )
        if exe is None:
            return None, model_dir
        if model_dir is None:
            for candidate in (exe.parent / "models", exe.parent):
                if _looks_like_model_dir(candidate):
                    model_dir = candidate
                    break
        return exe, model_dir

    def available(self, toolchain: Toolchain, opts: JobOptions) -> Tuple[bool, str]:
        exe, model_dir = self.resolve_paths(opts)
        if exe is None:
            return False, "rife-ncnn-vulkan tapılmadı (PATH / REELFORGE_RIFE)"
        if not Path(exe).exists():
            return False, f"rife-ncnn-vulkan mövcud deyil: {exe}"
        if model_dir is None or not _looks_like_model_dir(model_dir):
            return False, f"RIFE model qovluğu tapılmadı (gözlənilən: {exe.parent}/models)"
        return True, f"RIFE AI hazırdır: {exe} (model: {model_dir.name})"

    # -- plan ---------------------------------------------------------------
    def plan(self, **kwargs) -> InterpolationPlan:  # type: ignore[override]
        source: Path = kwargs["source"]
        target: RenderTarget = kwargs["target"]
        source_fps: float = kwargs["source_fps"]
        source_frames: int = int(kwargs.get("source_frames") or 0)
        opts: JobOptions = kwargs["opts"]
        workdir: Path = kwargs["workdir"]
        toolchain: Toolchain = kwargs["toolchain"]
        pattern: str = kwargs.get("frame_pattern", "%08d.png")

        exe, model_dir = self.resolve_paths(opts)
        if exe is None or model_dir is None:
            raise InterpolationUnavailable("rife-ncnn-vulkan və ya model qovluğu tapılmadı")
        if source_fps <= 0:
            raise InterpolationUnavailable("mənbə kadr sürəti oxunmadı")

        wanted = float(target.fps) * max(1, int(target.oversample))
        ratio = wanted / source_fps
        if ratio <= 1.02:
            raise InterpolationUnavailable(
                f"mənbə ({source_fps:.2f}fps) artıq {wanted:g}fps-dədir"
            )

        if source_frames <= 0:
            duration = float(kwargs.get("duration") or 0.0)
            source_frames = max(2, int(round(duration * source_fps)))
        target_frames = max(source_frames + 1, int(round(source_frames * ratio)))
        intermediate_fps = source_fps * (target_frames / max(1, source_frames))

        frames_in = workdir / "frames_in"
        frames_out = workdir / "frames_rife"
        frames_in.mkdir(parents=True, exist_ok=True)
        frames_out.mkdir(parents=True, exist_ok=True)

        passthrough = (
            ["-fps_mode", "passthrough"] if toolchain.supports_fps_mode else ["-vsync", "0"]
        )
        steps = [
            # 1) lossless PNG extraction — interpolation must not start from an
            #    already-compressed decode of a compressed frame
            CommandStep(
                argv=[
                    str(toolchain.ffmpeg), "-hide_banner", "-nostdin", "-nostats",
                    "-progress", "pipe:1", "-y",
                    "-i", str(source),
                    "-map", "0:v:0",
                    *passthrough,
                    "-qscale:v", "1", "-q:v", "1",
                    "-start_number", "1",
                    str(frames_in / pattern),
                ],
                phase="extract",
                expected_duration=float(kwargs.get("duration") or 0.0),
            ),
            # 2) RIFE: -n is the *target frame count*, not a multiplier
            CommandStep(
                argv=[
                    str(exe),
                    "-i", str(frames_in),
                    "-o", str(frames_out),
                    "-n", str(target_frames),
                    "-m", str(model_dir),
                    "-f", pattern,
                    "-j", "2:2:2",
                ],
                phase="rife",
                expected_duration=0.0,   # no progress protocol -> indeterminate
                cwd=exe.parent,
            ),
        ]

        notes = [
            f"RIFE AI: {source_frames} kadr -> {target_frames} kadr "
            f"({ratio:.2f}x, {source_fps:.2f}fps -> {intermediate_fps:.2f}fps), "
            f"model: {model_dir.name}",
            f"Encoder {target.fps}fps-ə sabitləyir (fps filtri).",
        ]
        return InterpolationPlan(
            engine=self.name,
            external=True,
            video_input=str(frames_out / pattern),
            video_input_args=["-framerate", _rate(intermediate_fps)],
            audio_input=source,
            steps=steps,
            notes=notes,
            intermediate_fps=intermediate_fps,
        )


def _looks_like_model_dir(path: Optional[Path]) -> bool:
    if path is None or not path.is_dir():
        return False
    return bool(list(path.glob("*.param")))


# --------------------------------------------------------------------------- #
# RIFE — VapourSynth (VapourSynth-RIFE-ncnn-Vulkan / vsmlrt)
# --------------------------------------------------------------------------- #

VSPY_TEMPLATE = '''"""Generated by ReelForge — VapourSynth RIFE interpolation."""
import vapoursynth as vs

core = vs.core
core.max_cache_size = 4096

SOURCE = {source!r}
FPS_NUM = {num}
FPS_DEN = {den}
MODEL = {model}

clip = None
for _loader in (
    lambda p: core.ffms2.Source(source=p),
    lambda p: core.lsmas.LWLibavSource(source=p),
    lambda p: core.bs.VideoSource(source=p),
):
    try:
        clip = _loader(SOURCE)
        break
    except Exception:
        continue
if clip is None:
    raise RuntimeError("no usable source filter (ffms2 / lsmas / bestsource)")

# RIFE wants 32-bit float RGB
clip = clip.resize.Point(format=vs.RGBS, matrix_in_s="709")

try:
    import rife  # VapourSynth-RIFE-ncnn-Vulkan: exact target rate
    clip = rife.RIFE(clip, model=MODEL, fps_num=FPS_NUM, fps_den=FPS_DEN, gpu_thread=2)
except ImportError:
    import vsmlrt  # fallback: integer factor only
    clip = vsmlrt.RIFE(
        clip,
        factor_num=FPS_NUM,
        factor_den=FPS_DEN,
        backend=vsmlrt.BackendV2.CPU(),
    )

clip = clip.resize.Point(format=vs.YUV420P8, matrix_s="709")
clip.set_output()
'''


class VapourSynthRifeEngine(InterpolationEngine):
    name = "vapoursynth-rife"
    kind = InterpolationEngineKind.RIFE

    def __init__(self, model: int = 5):
        self.model = int(model)

    def available(self, toolchain: Toolchain, opts: JobOptions) -> Tuple[bool, str]:
        vspipe = find_executable("vspipe")
        if vspipe is None:
            return False, "vspipe tapılmadı (VapourSynth quraşdırılmayıb)"
        return True, f"VapourSynth hazırdır: {vspipe}"

    def plan(self, **kwargs) -> InterpolationPlan:  # type: ignore[override]
        source: Path = kwargs["source"]
        target: RenderTarget = kwargs["target"]
        source_fps: float = kwargs["source_fps"]
        workdir: Path = kwargs["workdir"]
        toolchain: Toolchain = kwargs["toolchain"]

        vspipe = find_executable("vspipe")
        if vspipe is None:
            raise InterpolationUnavailable("vspipe tapılmadı")
        if source_fps <= 0:
            raise InterpolationUnavailable("mənbə kadr sürəti oxunmadı")

        num, den = _rational(
            float(target.fps) * max(1, int(target.oversample)), source_fps
        )
        workdir.mkdir(parents=True, exist_ok=True)
        script = workdir / "reelforge_rife.vpy"
        script.write_text(
            VSPY_TEMPLATE.format(
                source=str(source), num=num, den=den, model=self.model
            ),
            encoding="utf-8",
        )

        # vspipe streams y4m on stdout; ffmpeg wraps it losslessly (FFV1) so the
        # final CRF encode is still the *only* lossy generation.
        intermediate = workdir / "rife_intermediate.mkv"
        steps = [
            CommandStep(
                argv=[str(vspipe), "--y4m", str(script), "-"],
                consumer_argv=[
                    str(toolchain.ffmpeg), "-hide_banner", "-nostdin", "-nostats",
                    "-y", "-f", "y4m", "-i", "pipe:0",
                    "-c:v", "ffv1", "-level", "3", "-pix_fmt", "yuv420p",
                    str(intermediate),
                ],
                phase="rife",
                expected_duration=0.0,
            )
        ]
        notes = [
            f"VapourSynth + RIFE: {source_fps:.2f}fps -> "
            f"{float(target.fps) * max(1, int(target.oversample)):g}fps ({num}/{den})",
            "Ara fayl FFV1 (itkisiz) — son CRF encode yeganə itkili mərhələdir.",
        ]
        return InterpolationPlan(
            engine=self.name,
            external=True,
            video_input=str(intermediate),
            video_input_args=[],
            audio_input=source,
            steps=steps,
            notes=notes,
            intermediate_fps=float(target.fps) * max(1, int(target.oversample)),
        )


def _rational(wanted_fps: float, source_fps: float) -> Tuple[int, int]:
    """Exact-ish ``num/den`` for vs-rife's ``fps_num``/``fps_den``."""
    if source_fps <= 0:
        return 1, 1
    ratio = wanted_fps / source_fps
    for den in range(1, 12):
        num = ratio * den
        if abs(num - round(num)) < 0.02:
            return int(round(num)), den
    return int(round(ratio * 1000)), 1000


# --------------------------------------------------------------------------- #
# resolver
# --------------------------------------------------------------------------- #

_ALL_ENGINES: Tuple[InterpolationEngine, ...] = (
    RifeNcnnEngine(),
    VapourSynthRifeEngine(),
    MinterpolateEngine(),
)


def engine_by_name(name: str) -> Optional[InterpolationEngine]:
    key = str(name).lower()
    for engine in _ALL_ENGINES:
        if engine.name == key:
            return engine
    return None


def list_engines(toolchain: Toolchain, opts: JobOptions) -> List[Tuple[str, bool, str]]:
    """``[(name, available, reason)]`` — the GUI diagnostics panel uses this."""
    return [
        (engine.name, *engine.available(toolchain, opts)) for engine in _ALL_ENGINES
    ]


def resolve(
    kind: InterpolationEngineKind,
    *,
    toolchain: Toolchain,
    opts: JobOptions,
) -> Tuple[InterpolationEngine, List[str]]:
    """Pick the engine for a preset.  ``AUTO`` never raises."""
    notes: List[str] = []
    kind = InterpolationEngineKind(kind)

    if kind == InterpolationEngineKind.NONE:
        return NoInterpolationEngine(), notes

    if kind == InterpolationEngineKind.RIFE:
        candidates: Sequence[InterpolationEngine] = (
            RifeNcnnEngine(),
            VapourSynthRifeEngine(),
        )
    elif kind == InterpolationEngineKind.MINTERPOLATE:
        candidates = (MinterpolateEngine(),)
    else:  # AUTO -> prefer AI, fall back to FFmpeg
        candidates = (RifeNcnnEngine(), MinterpolateEngine())

    for engine in candidates:
        ok, reason = engine.available(toolchain, opts)
        if ok:
            notes.append(f"İnterpolyasiya mühərriki: {engine.name} — {reason}")
            return engine, notes
        notes.append(f"{engine.name} istifadə oluna bilməz: {reason}")

    if kind == InterpolationEngineKind.RIFE:
        raise InterpolationUnavailable(
            "RIFE tələb olundu, amma heç bir RIFE mühərriki tapılmadı. "
            "rife-ncnn-vulkan quraşdırın və ya minterpolate seçin."
        )
    notes.append("İnterpolyasiya söndürüldü — kadrlar dublikasiya olunacaq.")
    return NoInterpolationEngine(), notes


def plan_for(
    engine: InterpolationEngine,
    *,
    source: Path,
    target: RenderTarget,
    source_fps: float,
    source_frames: int,
    duration: float,
    toolchain: Toolchain,
    opts: JobOptions,
    workdir: Path,
) -> InterpolationPlan:
    """Build the plan, downgrading to ``minterpolate`` on hard failure."""
    wanted = float(target.fps) * max(1, int(target.oversample))
    if source_fps > 0 and wanted <= source_fps * 1.02:
        return _passthrough(
            source,
            engine.name,
            f"Mənbə ({source_fps:.2f}fps) artıq {wanted:g}fps-dədir — interpolyasiya lazım deyil.",
        )
    try:
        return engine.plan(
            source=source,
            target=target,
            source_fps=source_fps,
            source_frames=source_frames,
            duration=duration,
            toolchain=toolchain,
            opts=opts,
            workdir=workdir,
        )
    except InterpolationUnavailable as exc:
        fallback = MinterpolateEngine()
        if not fallback.available(toolchain, opts)[0]:
            raise
        return _passthrough(
            source,
            fallback.name,
            f"{engine.name} alınmadı ({exc}) — minterpolate-a keçildi.",
        )


def _rate(fps: float) -> str:
    if abs(fps - round(fps)) < 1e-6:
        return str(int(round(fps)))
    return f"{fps:.4f}".rstrip("0").rstrip(".")
