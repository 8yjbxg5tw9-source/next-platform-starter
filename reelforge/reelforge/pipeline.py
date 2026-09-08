"""Pipeline: the automatic operation chain.

    input -> probe -> (interpolate) -> (sharpen + motion blur)
          -> TikTok-optimal GOP/CRF export -> QA verify -> JSON report

``Pipeline`` is the only class that executes subprocesses; the GUI and the CLI
both drive it and differ only in how they render progress.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from . import encode as encode_mod
from . import filters as filters_mod
from . import interpolate as interp_mod
from . import upload as upload_mod
from .models import (
    JobOptions,
    JobResult,
    MediaInfo,
    ProgressCallback,
    ProgressInfo,
    RenderOutput,
    RenderTarget,
    VerifyReport,
    human_size,
)
from .presets import Preset
from .probe import keyframe_gaps, probe
from .toolchain import Cancelled, FFmpegError, FFmpegRunner, Toolchain, find_toolchain


class PipelineError(RuntimeError):
    """Fatal problem while planning or running a job."""


# planned work for one output file
PlannedTarget = Tuple[RenderTarget, interp_mod.InterpolationEngine, interp_mod.InterpolationPlan, Path]


def _info_with_fps(info: MediaInfo, fps: float) -> MediaInfo:
    """Copy of ``info`` whose video stream reports ``fps``.

    Used after an external RIFE pass so the filter chain reasons about the
    *interpolated* stream instead of the original one.
    """
    video = info.video
    if video is None:
        return info
    new_video = replace(video, fps=fps, avg_frame_rate=fps)
    streams = [new_video if s is video else s for s in info.streams]
    return replace(info, streams=streams)


def _timestamp() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


# --------------------------------------------------------------------------- #
# pipeline
# --------------------------------------------------------------------------- #


class Pipeline:
    """Runs one preset over one source file."""

    def __init__(
        self,
        toolchain: Toolchain,
        *,
        log_callback=None,
        progress_callback: Optional[ProgressCallback] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> None:
        self.toolchain = toolchain
        self.log_callback = log_callback
        self.progress_callback = progress_callback
        self.cancel = cancel_event or threading.Event()

    # -- plumbing -----------------------------------------------------------
    def _progress(self, info: ProgressInfo) -> None:
        if callable(self.progress_callback):
            try:
                self.progress_callback(info)
            except Exception:  # pragma: no cover - UI code must never kill a job
                pass

    # -- main entry ---------------------------------------------------------
    def run(self, source: str | Path, preset: Preset, opts: JobOptions) -> JobResult:
        source = Path(source)
        out_dir = opts.resolved_output_dir(source)
        out_dir.mkdir(parents=True, exist_ok=True)

        stamp = _timestamp()
        result = JobResult(
            source=source,
            input_info=None,
            log_path=out_dir / f"{source.stem}__reelforge_{stamp}.log",
            report_path=out_dir / f"{source.stem}__reelforge_{stamp}.json",
        )

        with FFmpegRunner(
            self.toolchain.ffmpeg,
            log_path=result.log_path,
            log_callback=self.log_callback,
        ) as runner:
            runner.log(f"ReelForge başladı: {source.name}")
            runner.log(self.toolchain.describe().replace("\n", " | "))

            # 1) probe ------------------------------------------------------
            try:
                info = probe(source, self.toolchain)
            except Exception as exc:
                result.ok = False
                result.error = f"probe xətası: {exc}"
                runner.log(result.error)
                result.finished_at = time.time()
                return result
            result.input_info = info
            runner.log(f"Mənbə: {info.summary()}")
            if info.is_hdr:
                runner.log("HDR mənbə aşkarlandı -> Rec.709 SDR tonemap açılacaq.")

            # 2) plan -------------------------------------------------------
            try:
                plan_items, total_steps = self.plan(source, preset, opts, info, out_dir)
            except (PipelineError, interp_mod.InterpolationUnavailable) as exc:
                result.ok = False
                result.error = str(exc)
                runner.log(f"PLAN XƏTASI: {exc}")
                result.finished_at = time.time()
                return result

            runner.log(
                f"Preset: {preset.label} -> "
                + ", ".join(f"{t.fps}fps/{t.suffix}" for t, _, _, _ in plan_items)
                + f" ({total_steps} mərhələ)"
            )

            # 3) execute ----------------------------------------------------
            step = 0
            for target, engine, plan, workdir in plan_items:
                if self.cancel.is_set():
                    result.ok = False
                    result.error = "istifadəçi tərəfindən ləğv edildi"
                    break
                try:
                    output = self._run_target(
                        runner=runner,
                        source=source,
                        info=info,
                        target=target,
                        plan=plan,
                        workdir=workdir,
                        opts=opts,
                        out_dir=out_dir,
                        step_start=step,
                        total_steps=total_steps,
                    )
                    step += 1 + len(plan.steps)
                    result.outputs.append(output)
                    if output.error:
                        result.ok = False
                        runner.log(f"XƏTA ({target.suffix}): {output.error}")
                    else:
                        runner.log(
                            f"Hazır: {output.path.name} ({human_size(output.size_bytes)}, "
                            f"{output.bitrate_kbps:.0f} kbps, {target.fps}fps, CRF {target.crf})"
                        )
                except Cancelled:
                    result.ok = False
                    result.error = "istifadəçi tərəfindən ləğv edildi"
                    runner.log("İş ləğv edildi.")
                    break
                except FFmpegError as exc:
                    result.ok = False
                    result.error = str(exc)
                    runner.log(f"FFMPEG XƏTASI ({target.suffix}): {exc}")
                    break
                finally:
                    self._cleanup(workdir, opts, runner)

            # 4) report -----------------------------------------------------
            result.finished_at = time.time()
            if result.report_path is not None:
                try:
                    result.report_path.write_text(result.to_json(), encoding="utf-8")
                    runner.log(f"Hesabat: {result.report_path.name}")
                except OSError as exc:  # pragma: no cover
                    runner.log(f"Hesabat yazılmadı: {exc}")

            runner.log(
                f"Bitdi: {len(result.succeeded)}/{len(result.outputs)} fayl · "
                f"{result.duration:.1f}s"
            )
        return result

    # -- planning -----------------------------------------------------------
    def plan(
        self,
        source: Path,
        preset: Preset,
        opts: JobOptions,
        info: MediaInfo,
        out_dir: Path,
    ) -> Tuple[List[PlannedTarget], int]:
        """Resolve engines and build every command list without running them."""
        targets = preset.build_targets(opts, info)
        if not targets:
            raise PipelineError("preset heç bir render target yaratmadı")

        items: List[PlannedTarget] = []
        total_steps = 0
        tmp_root = out_dir / ".reelforge_tmp"
        for target in targets:
            engine, notes = interp_mod.resolve(
                target.interpolation, toolchain=self.toolchain, opts=opts
            )
            # Write the resolved engine back onto the target: presets carry
            # AUTO, but build_filter_plan() must know whether the extra frames
            # come from `minterpolate` (in-graph) or from RIFE (out-of-graph).
            target = replace(target, interpolation=engine.kind)
            workdir = tmp_root / f"{source.stem}_{target.suffix}"
            plan = interp_mod.plan_for(
                engine,
                source=source,
                target=target,
                source_fps=info.fps,
                source_frames=int(info.video.nb_frames or 0) if info.video else 0,
                duration=info.duration,
                toolchain=self.toolchain,
                opts=opts,
                workdir=workdir,
            )
            plan.notes = list(notes) + list(plan.notes)
            items.append((target, engine, plan, workdir))
            total_steps += 1 + len(plan.steps)
        return items, max(1, total_steps)

    # -- one render target --------------------------------------------------
    def _run_target(
        self,
        *,
        runner: FFmpegRunner,
        source: Path,
        info: MediaInfo,
        target: RenderTarget,
        plan: interp_mod.InterpolationPlan,
        workdir: Path,
        opts: JobOptions,
        out_dir: Path,
        step_start: int,
        total_steps: int,
    ) -> RenderOutput:
        runner.log(
            f"— {target.label}: {target.fps}fps · {target.codec} CRF {target.crf} · "
            f"GOP {target.gop} · {target.x264_preset} · engine={plan.engine}"
        )
        for note in plan.notes:
            runner.log(f"  · {note}")
        # let the UI know which engine is doing the frame generation
        self._progress(
            ProgressInfo(
                phase="prepare",
                step=step_start,
                total_steps=total_steps,
                message=f"engine={plan.engine}",
            )
        )

        step = step_start
        # 1) pre-encode steps (PNG extraction / RIFE / vspipe)
        for cmd_step in plan.steps:
            step += 1
            self._progress(
                ProgressInfo(
                    phase=cmd_step.phase,
                    step=step,
                    total_steps=total_steps,
                    percent=((step - 1) / total_steps) * 100.0,
                    message=f"{target.suffix}: {cmd_step.phase}",
                )
            )
            self._run_step(runner, cmd_step, step, total_steps, info.duration)

        # 2) filter chain
        graph_info = (
            _info_with_fps(info, plan.intermediate_fps)
            if plan.external and plan.intermediate_fps
            else info
        )
        plan_filters = filters_mod.build_filter_plan(
            target, opts, graph_info, self.toolchain,
            external_interpolation=plan.external,
        )
        for note in plan_filters.graph.notes:
            runner.log(f"  · {note}")
        video_filter = None if plan_filters.graph.is_empty else plan_filters.graph.build()

        # 3) encode
        out_path = out_dir / target.output_name(source)
        encode_plan = encode_mod.build_encode_plan(
            ffmpeg=self.toolchain.ffmpeg,
            video_input=plan.video_input,
            video_input_args=plan.video_input_args,
            audio_input=plan.audio_input,
            output=out_path,
            target=target,
            opts=opts,
            toolchain=self.toolchain,
            video_filter=video_filter,
            has_audio=bool(info.has_audio),
            expected_duration=info.duration,
        )
        for note in encode_plan.notes:
            runner.log(f"  · {note}")

        step += 1
        if opts.dry_run:
            runner.log("DRY-RUN: encode icra olunmadı.")
            self._progress(
                ProgressInfo(phase="dry-run", step=step, total_steps=total_steps, percent=100.0)
            )
            return RenderOutput(path=out_path, target=target, command=encode_plan.command)

        runner.run(
            encode_plan.command,
            expected_duration=info.duration,
            phase=f"encode:{target.suffix}",
            step=step,
            total_steps=total_steps,
            progress=self._progress,
            cancel=self.cancel,
        )

        # 4) QA
        size = out_path.stat().st_size if out_path.exists() else 0
        bitrate = (size * 8 / 1000.0) / info.duration if info.duration else 0.0
        verify: Optional[VerifyReport] = None
        if opts.verify_output:
            try:
                verify = self.verify(out_path, target, info.duration)
                for warn in verify.warnings:
                    runner.log(f"  ! {warn}")
            except Exception as exc:  # QA must never fail the job
                runner.log(f"  ! QA yoxlanışı alınmadı: {exc}")

        return RenderOutput(
            path=out_path,
            target=target,
            size_bytes=size,
            bitrate_kbps=bitrate,
            command=encode_plan.command,
            verify=verify,
        )

    def _run_step(
        self,
        runner: FFmpegRunner,
        step: interp_mod.CommandStep,
        index: int,
        total_steps: int,
        duration: float,
    ) -> None:
        """Run one pre-encode step, optionally piping into a consumer."""
        if step.consumer_argv is None:
            runner.run(
                step.argv,
                expected_duration=step.expected_duration or duration,
                phase=step.phase,
                step=index,
                total_steps=total_steps,
                progress=self._progress,
                cancel=self.cancel,
            )
            return
        self._run_pipe(runner, step)

    def _run_pipe(self, runner: FFmpegRunner, step: interp_mod.CommandStep) -> None:
        """``producer.stdout -> consumer.stdin`` without a shell."""
        runner.log_command(list(step.argv) + ["|"] + list(step.consumer_argv or []))
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as err_log:
            producer = subprocess.Popen(
                step.argv,
                stdout=subprocess.PIPE,
                stderr=err_log,
                stdin=subprocess.DEVNULL,
                cwd=str(step.cwd) if step.cwd else None,
            )
            consumer = subprocess.Popen(
                step.consumer_argv or [],
                stdin=producer.stdout,
                stdout=subprocess.DEVNULL,
                stderr=err_log,
            )
            assert producer.stdout is not None
            producer.stdout.close()   # consumer gets EOF when producer exits
            consumer.wait()
            producer.wait()

            err_log.seek(0)
            tail = [line.rstrip() for line in err_log.readlines() if line.strip()][-8:]
            for line in tail:
                runner.log(line)

        if producer.returncode != 0 or consumer.returncode != 0:
            raise FFmpegError(
                f"{step.phase} pipe uğursuz oldu "
                f"(producer={producer.returncode}, consumer={consumer.returncode}): "
                + " | ".join(tail[-4:]),
                command=list(step.argv) + list(step.consumer_argv or []),
                tail=tail,
            )

    def _cleanup(self, workdir: Path, opts: JobOptions, runner: FFmpegRunner) -> None:
        if not workdir.exists():
            return
        if opts.keep_temp:
            runner.log(f"Ara fayllar saxlanıldı: {workdir}")
            return
        shutil.rmtree(workdir, ignore_errors=True)
        parent = workdir.parent
        try:
            if parent.name == ".reelforge_tmp" and not any(parent.iterdir()):
                parent.rmdir()
        except OSError:  # pragma: no cover
            pass

    # -- QA -----------------------------------------------------------------
    def verify(
        self, path: Path, target: RenderTarget, source_duration: float = 0.0
    ) -> VerifyReport:
        """Re-read the file and confirm the requested structure is there."""
        info = probe(path, self.toolchain)
        video = info.video
        report = VerifyReport(
            path=path,
            fps=info.fps,
            expected_fps=float(target.fps),
            codec=video.codec_name if video else "",
            profile=video.profile if video else "",
            pix_fmt=video.pix_fmt if video else "",
            color_primaries=(video.color_primaries if video else "") or "",
            expected_gop=target.gop,
        )

        if abs(report.fps - report.expected_fps) > 0.5:
            report.ok = False
            report.warnings.append(
                f"Kadr sürəti {report.fps:.2f} (gözlənilən {report.expected_fps:g})"
            )
        expected_codec = target.codec.probe_name
        if report.codec and report.codec != expected_codec:
            report.ok = False
            report.warnings.append(f"Kodek {report.codec} (gözlənilən {expected_codec})")
        if report.pix_fmt and report.pix_fmt != "yuv420p":
            report.ok = False
            report.warnings.append(f"Piksel formatı {report.pix_fmt} (gözlənilən yuv420p)")
        if report.color_primaries and report.color_primaries.lower() != "bt709":
            report.warnings.append(f"Rəng primaries: {report.color_primaries}")

        try:
            times = keyframe_gaps(path, self.toolchain)
        except Exception:
            times = []
        if len(times) >= 2:
            gaps = [round(times[i + 1] - times[i], 3) for i in range(len(times) - 1)]
            report.keyframe_gaps = gaps
            expected_gap = target.gop / max(1.0, float(target.fps))
            tolerance = max(0.1, expected_gap * 0.1)
            bad = [g for g in gaps if abs(g - expected_gap) > tolerance]
            if bad:
                report.warnings.append(
                    f"GOP qeyri-sabitdir: {bad[:3]} (gözlənilən {expected_gap:.3f}s)"
                )
        elif len(times) == 1 and source_duration > 2.0:
            report.warnings.append("Yalnız 1 keyframe tapıldı — GOP yoxlanıla bilmədi.")
        return report


# --------------------------------------------------------------------------- #
# facade
# --------------------------------------------------------------------------- #


class ReelForge:
    """High-level API used by both the GUI and the CLI."""

    def __init__(
        self,
        ffmpeg: Optional[str | Path] = None,
        ffprobe: Optional[str | Path] = None,
        *,
        log_callback=None,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> None:
        self.toolchain = find_toolchain(ffmpeg, ffprobe)
        self.log_callback = log_callback
        self.progress_callback = progress_callback
        self.cancel_event = threading.Event()

    # -- introspection ------------------------------------------------------
    def probe(self, path: str | Path) -> MediaInfo:
        return probe(path, self.toolchain)

    def engines(self, opts: Optional[JobOptions] = None) -> List[Tuple[str, bool, str]]:
        return interp_mod.list_engines(self.toolchain, opts or JobOptions())

    def describe(self) -> str:
        engines = "\n".join(
            f"  - {name}: {'OK' if ok else 'yox'} ({reason})"
            for name, ok, reason in self.engines()
        )
        return self.toolchain.describe() + "\nİnterpolyasiya mühərrikləri:\n" + engines

    # -- dry run ------------------------------------------------------------
    def build_commands(
        self,
        source: str | Path,
        preset: Preset,
        opts: Optional[JobOptions] = None,
    ) -> List[List[str]]:
        """Return the exact argv lists without executing anything."""
        source = Path(source)
        opts = opts or JobOptions()
        info = probe(source, self.toolchain)
        pipeline = self._pipeline()
        items, _ = pipeline.plan(source, preset, opts, info, opts.resolved_output_dir(source))

        commands: List[List[str]] = []
        for target, _engine, plan, _workdir in items:
            for step in plan.steps:
                argv = list(step.argv)
                if step.consumer_argv:
                    argv = argv + ["|"] + list(step.consumer_argv)
                commands.append(argv)
            plan_filters = filters_mod.build_filter_plan(
                target, opts, info, self.toolchain,
                external_interpolation=plan.external,
            )
            video_filter = None if plan_filters.graph.is_empty else plan_filters.graph.build()
            encode_plan = encode_mod.build_encode_plan(
                ffmpeg=self.toolchain.ffmpeg,
                video_input=plan.video_input,
                video_input_args=plan.video_input_args,
                audio_input=plan.audio_input,
                output=opts.resolved_output_dir(source) / target.output_name(source),
                target=target,
                opts=opts,
                toolchain=self.toolchain,
                video_filter=video_filter,
                has_audio=bool(info.has_audio),
                expected_duration=info.duration,
            )
            commands.append(encode_plan.command)
        return commands

    # -- execution ----------------------------------------------------------
    def run(self, source: str | Path, preset: Preset, opts: Optional[JobOptions] = None) -> JobResult:
        self.cancel_event.clear()
        return self._pipeline().run(source, preset, opts or JobOptions())

    def run_many(
        self,
        sources: Sequence[str | Path],
        preset: Preset,
        opts: Optional[JobOptions] = None,
    ) -> List[JobResult]:
        results: List[JobResult] = []
        for source in sources:
            results.append(self.run(source, preset, opts))
            if self.cancel_event.is_set():
                break
        return results

    def cancel(self) -> None:
        self.cancel_event.set()

    # -- TikTok upload ------------------------------------------------------
    def upload(
        self,
        video: str | Path | upload_mod.UploadRequest,
        description: str = "",
        cookies: Optional[str | Path] = None,
        *,
        proxy: Optional[str] = None,
        headless: bool = True,
        timeout: float = 900.0,
        backend: str = "auto",
    ) -> upload_mod.UploadResult:
        """Post a rendered file to TikTok **without re-encoding it**.

        Safe to call from the GUI worker thread: :func:`reelforge.upload.upload`
        converts every expected failure (missing cookies, no backend, network)
        into ``UploadResult(ok=False, error=...)`` instead of raising.
        """
        if isinstance(video, upload_mod.UploadRequest):
            request = video
        else:
            request = upload_mod.UploadRequest(
                path=Path(video),
                description=description,
                cookies=Path(cookies) if cookies else None,
                proxy=proxy,
                headless=headless,
                timeout=timeout,
                backend=backend,
            )
        return upload_mod.upload(request, log_callback=self.log_callback)

    def _pipeline(self) -> Pipeline:
        return Pipeline(
            self.toolchain,
            log_callback=self.log_callback,
            progress_callback=self.progress_callback,
            cancel_event=self.cancel_event,
        )
