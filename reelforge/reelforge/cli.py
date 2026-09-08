"""Command-line front end.

Examples
--------

List what is installed and what interpolation engines are reachable::

    python -m reelforge.cli --diagnostics

Show the exact FFmpeg commands without running them::

    python -m reelforge.cli clip.mp4 -p safe --dry-run

Ultra 120FPS with both variants (60 + 120), HEVC master::

    python -m reelforge.cli clip.mp4 -p ultra120 --codec hevc -o out/

Force 1080x1920 cover-crop and 320k audio::

    python -m reelforge.cli *.mov -p safe --fit cover --width 1080 --height 1920

The GUI is ``python -m reelforge`` (or ``--gui`` here).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional, Sequence

from .models import (
    Codec,
    ColorTag,
    FitMode,
    InterpolationEngineKind,
    JobOptions,
    SharpenMode,
    ensure_video_files,
)
from .pipeline import ReelForge
from .presets import Presets
from .toolchain import ToolchainError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reelforge",
        description=(
            "TikTok / Instagram Reels / YouTube Shorts üçün 60-120FPS "
            "minimal-sıxılma video emalı (FFmpeg + RIFE)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("inputs", nargs="*", help="video fayl(lar)")
    parser.add_argument(
        "-p", "--preset", default="ultra120",
        choices=Presets.choices(),
        help="hazır rejim (default: ultra120)",
    )
    parser.add_argument("-o", "--out", default=None, help="çıxış qovluğu")
    parser.add_argument(
        "--codec", choices=["h264", "hevc", "nvenc"], default=None,
        help="preset-in kodekini dəyiş (default: h264; nvenc = NVIDIA GPU)",
    )
    parser.add_argument("--crf", type=int, default=None, help="CRF 0-51 (preset-i üstələyir)")
    parser.add_argument(
        "--interp", choices=[k.value for k in InterpolationEngineKind], default=None,
        help="interpolyasiya mühərriki (default: preset seçimi)",
    )
    parser.add_argument("--fps", type=int, default=None, help="bütün çıxışlar üçün FPS")
    parser.add_argument(
        "--fit", choices=[f.value for f in FitMode], default="keep",
        help="kadra yerləşdirmə rejimi",
    )
    parser.add_argument("--width", type=int, default=None, help="hədəf en (məs. 1080)")
    parser.add_argument("--height", type=int, default=None, help="hədəf hündürlük (məs. 1920)")
    parser.add_argument("--scaler", default="lanczos", help="lanczos|bicubic|spline|area")
    parser.add_argument(
        "--interp-quality", choices=["fast", "balanced", "quality"], default="balanced",
        help="minterpolate keyfiyyət/sürət balansı",
    )
    parser.add_argument("--audio-bitrate", type=int, default=320, help="AAC kbps (default 320)")
    parser.add_argument("--audio-rate", type=int, default=48000, help="audio sample rate")
    parser.add_argument("--audio-channels", type=int, default=2, help="audio kanallar")
    parser.add_argument("--color-tag", default="bt709", choices=[c.value for c in ColorTag])
    parser.add_argument("--threads", type=int, default=0, help="0 = avtomatik")
    parser.add_argument("--blur", type=int, default=None, metavar="0-100",
                        help="motion blur gücü: 0=sönülü, 1-100=tmix kadr sayı artır")
    parser.add_argument("--no-sharpen", action="store_true", help="kəskinlik filtri söndür")
    parser.add_argument("--maxrate", type=int, default=None, help="VBV tavanı (kbps)")
    parser.add_argument("--bufsize", type=int, default=None, help="VBV buffer (kbps)")
    parser.add_argument("--hwaccel", default=None, help="cuda | videotoolbox | ...")
    parser.add_argument("--no-dual", action="store_true", help="yalnız ən yüksək FPS variantı")
    parser.add_argument("--no-verify", action="store_true", help="QA yoxlanışını söndür")
    parser.add_argument("--keep-temp", action="store_true", help="ara faylları silmə")
    parser.add_argument("--dry-run", action="store_true", help="əmrləri çap et, icra etmə")
    parser.add_argument("--json", action="store_true", help="hesabatı JSON olaraq çap et")
    parser.add_argument("--quiet", action="store_true", help="log xətlərini gizlət")
    parser.add_argument("--ffmpeg", default=None, help="ffmpeg yolu")
    parser.add_argument("--ffprobe", default=None, help="ffprobe yolu")
    parser.add_argument("--rife", default=None, help="rife-ncnn-vulkan yolu")
    parser.add_argument("--rife-model", default=None, help="RIFE model qovluğu")
    parser.add_argument("--diagnostics", action="store_true", help="mühit məlumatı")
    parser.add_argument("--list-presets", action="store_true", help="preset siyahısı")
    parser.add_argument("--gui", action="store_true", help="Decoy stilində qrafik interfeys")
    parser.add_argument("--gui-advanced", action="store_true",
                        help="geniş (3 sütunlu) qrafik interfeys")
    return parser


def _make_options(args: argparse.Namespace) -> JobOptions:
    opts = JobOptions(
        output_dir=Path(args.out) if args.out else None,
        fit=FitMode(args.fit),
        target_width=args.width,
        target_height=args.height,
        scaler=args.scaler,
        interpolation_quality=args.interp_quality,
        color_tag=ColorTag(args.color_tag),
        audio_bitrate=args.audio_bitrate,
        audio_sample_rate=args.audio_rate,
        audio_channels=args.audio_channels,
        threads=args.threads,
        hwaccel=args.hwaccel,
        dry_run=args.dry_run,
        dual_output=not args.no_dual,
        verify_output=not args.no_verify,
        keep_temp=args.keep_temp,
        codec=Codec(args.codec) if args.codec else Codec.H264,
        crf_override=args.crf,
        fps_override=args.fps,
        interpolation_override=(
            InterpolationEngineKind(args.interp) if args.interp else None
        ),
    )
    if args.rife:
        opts.rife_executable = Path(args.rife)
    if args.rife_model:
        opts.rife_model_dir = Path(args.rife_model)

    if args.blur is not None:
        from .uistate import blur_strength_to_params

        mode, frames, amount, oversample = blur_strength_to_params(args.blur)
        opts.motion_blur_override = mode
        opts.motion_blur_frames_override = frames
        opts.motion_blur_amount_override = amount
        opts.oversample_override = oversample
    if args.no_sharpen:
        opts.sharpen_override = SharpenMode.SHARPEN_OFF
        opts.sharpen_amount_override = 0.0
    opts.maxrate_override = args.maxrate
    opts.bufsize_override = args.bufsize
    return opts


def _print_presets() -> None:
    print("ReelForge presetləri\n" + "=" * 72)
    for preset in Presets.ALL:
        print(f"\n{preset.id:<12} {preset.label}")
        print(f"{'':<12} {preset.tagline}")
        print(f"{'':<12} Çıxışlar: {', '.join(str(f) + 'fps' for f in preset.output_fps_list)}")
        for spec in preset.specs:
            print(
                f"{'':<14}· {spec.suffix}: CRF {spec.crf}, x264 {spec.x264_preset}, "
                f"GOP {spec.gop_seconds:g}s, interp={spec.interpolation}, "
                f"blur={spec.motion_blur}, oversample={spec.oversample}x"
            )
        print(f"{'':<12} {preset.description}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    if args.list_presets:
        _print_presets()
        return 0

    def log_line(text: str) -> None:
        if not args.quiet:
            print(text, flush=True)

    try:
        app = ReelForge(
            args.ffmpeg, args.ffprobe,
            log_callback=log_line,
            progress_callback=None if args.quiet else _cli_progress,
        )
    except ToolchainError as exc:
        print(f"XƏTA: {exc}", file=sys.stderr)
        return 2

    if args.diagnostics:
        print(app.describe())
        return 0

    if args.gui:
        from .gui.decoy import launch

        return 0 if launch(ffmpeg=args.ffmpeg, ffprobe=args.ffprobe) else 1

    if args.gui_advanced:
        from .gui.app import launch as launch_advanced

        return 0 if launch_advanced(ffmpeg=args.ffmpeg, ffprobe=args.ffprobe) else 1

    if not args.inputs:
        print("XƏTA: heç bir giriş faylı verilməyib. --help", file=sys.stderr)
        return 2

    files = ensure_video_files(args.inputs)
    if not files:
        print(f"XƏTA: dəstəklənən video tapılmadı: {args.inputs}", file=sys.stderr)
        return 2

    preset = Presets.by_id(args.preset)
    opts = _make_options(args)

    if opts.dry_run:
        for source in files:
            print(f"\n### {source}")
            for index, command in enumerate(app.build_commands(source, preset, opts), 1):
                print(f"\n[{index}] " + " \\\n    ".join(_wrap(command)))
        return 0

    exit_code = 0
    for result in app.run_many(files, preset, opts):
        if args.json:
            print(result.to_json())
        if not result.ok:
            exit_code = 1
        elif not args.quiet:
            print(f"\nNəticə: {result.source.name}")
            for out in result.succeeded:
                flag = "OK " if (out.verify and out.verify.ok) else "?? "
                print(
                    f"  {flag}{out.path}  ·  {out.target.fps}fps · CRF {out.target.crf} · "
                    f"GOP {out.target.gop} · {out.size_bytes / 1024 / 1024:.2f} MB"
                )
    return exit_code


def _wrap(command: List[str]) -> List[str]:
    """Group argv into readable chunks for the dry-run printout."""
    out: List[str] = []
    current: List[str] = []
    for token in command:
        if token.startswith("-") and current:
            out.append(" ".join(current))
            current = [token]
        else:
            current.append(token)
    if current:
        out.append(" ".join(current))
    return out


def _cli_progress(info) -> None:
    if info.step_percent <= 0 and info.phase != "encode":
        return
    bar_len = 24
    filled = int(bar_len * info.percent / 100.0)
    bar = "#" * filled + "-" * (bar_len - filled)
    eta = f" ETA {info.eta_seconds:5.0f}s" if info.eta_seconds is not None else ""
    sys.stdout.write(
        f"\r[{bar}] {info.percent:5.1f}%  {info.phase:<18} "
        f"{info.speed:4.1f}x{eta}   "
    )
    sys.stdout.flush()
    if info.percent >= 99.9:
        sys.stdout.write("\n")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
