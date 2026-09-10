"""Render pipeline: device probing, VRAM-safe tiling and the ffmpeg driver.

Three ideas keep this module safe on unknown hardware:

1. **Device probing never crashes** — torch/onnxruntime are optional imports
   and every failure path ends on the CPU profile.
2. **Tiling shrinks the AI tile until it fits the VRAM budget**; when the
   budget is unknown (0 = CPU / ffmpeg path) the whole frame is processed.
3. **Rendering runs in a worker thread** and only ever talks to the GUI
   through plain callbacks, so the window stays responsive and Cancel can
   terminate ffmpeg and free GPU memory (``torch.cuda.empty_cache()``).
"""

from __future__ import annotations

import math
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from . import ffmpeg_tools
from .config import log


# --------------------------------------------------------------------------
# Device detection
# --------------------------------------------------------------------------

@dataclass
class DeviceInfo:
    kind: str = "cpu"          # cuda | rocm | directml | cpu
    label: str = "CPU (ffmpeg fallback)"
    vram_mb: int = 0

    @property
    def supported(self) -> bool:
        return self.kind != "cpu"


def detect_device() -> DeviceInfo:
    try:
        import torch  # type: ignore

        if torch.cuda.is_available():
            props = torch.cuda.get_device_properties(0)
            kind = "rocm" if getattr(torch.version, "hip", None) else "cuda"
            return DeviceInfo(kind=kind, label=props.name,
                              vram_mb=int(props.total_memory // 1048576))
    except Exception as exc:  # noqa: BLE001 - probing must never kill the app
        log().debug("torch probe failed: %s", exc)
    try:
        import onnxruntime as ort  # type: ignore

        providers = ort.get_available_providers()
        if "DmlExecutionProvider" in providers:
            return DeviceInfo(kind="directml", label="DirectML (DirectX 12)")
        if "ROCMExecutionProvider" in providers:
            return DeviceInfo(kind="rocm", label="ROCm")
        if "CUDAExecutionProvider" in providers:
            return DeviceInfo(kind="cuda", label="CUDA")
    except Exception as exc:  # noqa: BLE001
        log().debug("onnxruntime probe failed: %s", exc)
    return DeviceInfo()


# --------------------------------------------------------------------------
# VRAM-aware tiling
# --------------------------------------------------------------------------

TILE_STEPS: Tuple[int, ...] = (1024, 768, 512, 384, 256, 192, 128)
# fp32 activations + weights margin per output pixel of a super-resolution
# tile pass; empirically ~14 B/px covers two network passes at once.
BYTES_PER_PIXEL = 14


def choose_tile(out_w: int, out_h: int, vram_mb: int) -> int:
    """Largest tile that fits half the reported VRAM (0 = whole-frame pass)."""
    if vram_mb <= 0:
        return 0
    budget = vram_mb * 1048576 // 2  # keep 50 % headroom for encoders/caches
    for tile in TILE_STEPS:
        if tile * tile * BYTES_PER_PIXEL <= budget:
            return tile
    return TILE_STEPS[-1]


def plan_tiles(src_w: int, src_h: int, scale: int, vram_mb: int) -> Dict[str, object]:
    """Tiling plan for the AI path (ffmpeg path uses tile=0)."""
    out_w, out_h = src_w * scale, src_h * scale
    tile = choose_tile(out_w, out_h, vram_mb)
    if tile == 0:
        return {"tile": 0, "grid": (1, 1), "overlap": 0,
                "out": (out_w, out_h)}
    overlap = max(8, tile // 16)
    grid = (math.ceil(out_w / tile), math.ceil(out_h / tile))
    return {"tile": tile, "grid": grid, "overlap": overlap,
            "out": (out_w, out_h)}


# --------------------------------------------------------------------------
# Job description + output planning
# --------------------------------------------------------------------------

TARGET_SIZES = {
    "1080p": (1920, 1080),
    "4K": (3840, 2160),
    "8K": (7680, 4320),
}

ENCODERS: Dict[str, Tuple[List[str], str, List[str]]] = {
    "H.264": (["-c:v", "libx264", "-preset", "slow", "-crf", "18"],
              ".mp4", ["-c:a", "aac", "-b:a", "192k"]),
    "H.265": (["-c:v", "libx265", "-preset", "slow", "-crf", "20",
               "-tag:v", "hvc1"],
              ".mp4", ["-c:a", "aac", "-b:a", "192k"]),
    "ProRes": (["-c:v", "prores_ks", "-profile:v", "3",
                "-pix_fmt", "yuv422p10le"],
               ".mov", ["-c:a", "pcm_s16le"]),
}


@dataclass
class RenderJob:
    source: Path
    output_dir: Path
    target: str = "4K"                       # 1080p | 4K | 8K | CUSTOM
    custom_size: Optional[Tuple[int, int]] = None
    encoder: str = "H.264"
    # Proteus fine-tune sliders, 0..100:
    revert_compression: int = 40
    recover_details: int = 55
    sharpen: int = 35
    reduce_noise: int = 30
    dehaloing: int = 25
    auto_mode: bool = True
    motion_deblur: bool = False
    interp_fps: int = 0                      # 0 = keep source fps
    device: DeviceInfo = field(default_factory=DeviceInfo)

    # -- derived ------------------------------------------------------------
    def target_size(self, src_w: int, src_h: int) -> Tuple[int, int]:
        if self.target == "CUSTOM" and self.custom_size:
            return (max(2, self.custom_size[0] // 2 * 2),
                    max(2, self.custom_size[1] // 2 * 2))
        box = TARGET_SIZES.get(self.target, TARGET_SIZES["4K"])
        ratio = min(box[0] / src_w, box[1] / src_h)
        if ratio <= 1.0 and self.target != "CUSTOM":
            ratio = 1.0  # never downscale below the source resolution
        return (max(2, round(src_w * ratio / 2) * 2),
                max(2, round(src_h * ratio / 2) * 2))

    def output_path(self, src_name: str) -> Path:
        stem = Path(src_name).stem
        suffix = ENCODERS.get(self.encoder, ENCODERS["H.264"])[1]
        self.output_dir.mkdir(parents=True, exist_ok=True)
        return self.output_dir / f"{stem}_{self.target.lower()}{suffix}"


def build_filter_chain(job: RenderJob, src_w: int, src_h: int) -> str:
    """ffmpeg ``-vf`` chain implementing the Proteus-style control panel.

    Slider mapping (all inputs are 0..100):
      Revert Compression -> hqdn3d temporal strength
      Reduce Noise       -> hqdn3d spatial strength
      Sharpen            -> cas
      Recover Details    -> unsharp luma amount
      Dehaloing          -> negative luma bias inside unsharp (edge softener)
    """
    width, height = job.target_size(src_w, src_h)
    filters: List[str] = [
        f"scale={width}:{height}:flags=lanczos",
    ]

    if job.auto_mode:
        noise = details = sharp = halos = compression = 0
        noise, compression = 2.0, 3.0
        details, sharp, halos = 0.6, 0.30, 0.15
    else:
        noise = job.reduce_noise / 100 * 4.0
        compression = job.revert_compression / 100 * 6.0
        sharp = job.sharpen / 100
        details = job.recover_details / 100 * 1.2
        halos = job.dehaloing / 100 * 0.4

    if noise > 0 or compression > 0:
        filters.append(f"hqdn3d={noise:.2f}:{noise / 2:.2f}:"
                       f"{compression:.2f}:{compression / 2:.2f}")
    if sharp > 0:
        filters.append(f"cas={min(sharp, 1.0):.2f}")
    if details > 0 or halos > 0:
        luma = details - halos
        if luma > 0:
            filters.append(f"unsharp=5:5:{luma:.2f}:5:5:0.0")
    if job.motion_deblur:
        filters.append("unsharp=7:7:0.60:7:7:0.0")
    if job.interp_fps > 0:
        filters.append(f"minterpolate=fps={job.interp_fps}:"
                       "mi_mode=mci:mc_mode=aobmc:vsbmc=1")
    filters += ["format=yuv420p", "setsar=1"]
    return ",".join(filters)


def build_command(job: RenderJob, source: Path, output: Path,
                  ffmpeg: Optional[str] = None, vf: Optional[str] = None) -> List[str]:
    """Full argv for the render; ``vf`` defaults to the job's filter chain."""
    ffmpeg = ffmpeg or ffmpeg_tools.find_ffmpeg()
    info = ffmpeg_tools.probe(source)
    video_args, _, audio_args = ENCODERS.get(job.encoder, ENCODERS["H.264"])
    argv: List[str] = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(source),
        "-vf", vf if vf is not None else build_filter_chain(job, info.width, info.height),
        *video_args,
        "-movflags", "+faststart",
        *audio_args,
        "-progress", "pipe:1",
        str(output),
    ]
    return argv


# --------------------------------------------------------------------------
# Worker thread
# --------------------------------------------------------------------------

ProgressCallback = Callable[[float, str], None]


class RenderWorker(threading.Thread):
    """Runs one ffmpeg render off the GUI thread.

    ``cancel()`` terminates ffmpeg promptly and frees CUDA memory if torch
    is present, so the user can start a different job immediately.
    """

    def __init__(self, job: RenderJob,
                 progress_cb: Optional[ProgressCallback] = None,
                 done_cb: Optional[Callable[[Path], None]] = None,
                 error_cb: Optional[Callable[[str], None]] = None,
                 ffmpeg: Optional[str] = None):
        super().__init__(daemon=True, name="akai-render")
        self.job = job
        self.progress_cb = progress_cb
        self.done_cb = done_cb
        self.error_cb = error_cb
        self.ffmpeg = ffmpeg
        self.output: Optional[Path] = None
        self.error: Optional[str] = None
        self._cancel = threading.Event()
        self._proc: Optional[subprocess.Popen] = None

    def cancel(self) -> None:
        self._cancel.set()
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass
        self._free_gpu()

    @staticmethod
    def _free_gpu() -> None:
        try:
            import torch  # type: ignore

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:  # noqa: BLE001 - torch is optional
            pass

    # -- internals ----------------------------------------------------------
    def _emit(self, fraction: float, message: str) -> None:
        if self.progress_cb:
            self.progress_cb(max(0.0, min(1.0, fraction)), message)

    def run(self) -> None:  # pragma: no cover - thin orchestration
        try:
            info = ffmpeg_tools.probe(self.job.source)
            output = self.job.output_path(info.path.name)
            argv = build_command(self.job, info.path, output, self.ffmpeg)
            log().info("render start: %s -> %s", info.summary, output)
            self._emit(0.0, "Render başlayır…")
            duration = max(info.duration, 1e-6)
            self._proc = ffmpeg_tools.run_argv(
                argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True,
            )
            assert self._proc.stdout is not None
            for line in self._proc.stdout:
                if self._cancel.is_set():
                    break
                if line.startswith("out_time_ms="):
                    try:
                        used = int(line.split("=", 1)[1].strip()) / 1e6
                        self._emit(min(used / duration, 1.0), "Render gedir…")
                    except (ValueError, IndexError):
                        pass
            code = self._proc.wait()
            self._free_gpu()
            if self._cancel.is_set():
                self.error = "Render dayandırıldı"
                self._emit(0.0, self.error)
                return
            if code != 0 or not output.exists():
                stderr = self._proc.stderr.read() if self._proc.stderr else ""
                self.error = f"Render xətası (exit {code}): {stderr.strip()[-300:]}"
                log().error(self.error)
                return
            self.output = output
            self._emit(1.0, "Hazır!")
            log().info("render done: %s", output)
        except Exception as exc:  # noqa: BLE001 - worker must never raise
            self.error = f"Render xətası: {exc}"
            log().exception("render worker failed")
        finally:
            if self.error and self.error_cb:
                self.error_cb(self.error)
            elif self.output and self.done_cb:
                self.done_cb(self.output)
