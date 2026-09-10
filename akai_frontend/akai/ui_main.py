"""Main working panel: model controls, output settings, preview, render.

All heavy work (probe, preview frame, render) happens in worker threads;
UI updates travel through ``after()``.  A missing ``tkinterdnd2`` only
disables drag & drop — the rest of the window keeps working.
"""

from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Dict, List, Optional

import customtkinter as ctk
from PIL import Image, ImageTk

from .config import BASE_DIR, ICON_PATH, log
from .engine import (DeviceInfo, RenderJob, RenderWorker, build_filter_chain,
                     detect_device, plan_tiles)
from .ffmpeg_tools import FFmpegMissing, MediaProbe, probe

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD

    DND_AVAILABLE = True
except ImportError:  # drag & drop is optional
    TkinterDnD = None
    DND_AVAILABLE = False

ACCENT = "#e5322d"
TARGETS = ("1080p", "4K", "8K", "CUSTOM")
ENCODERS = ("H.264", "H.265", "ProRes")
INTERP = ("Off", "60 fps", "120 fps")


def _window_base():
    """CTk root with the tkdnd library loaded when tkinterdnd2 is present."""
    if not DND_AVAILABLE:
        return ctk.CTk

    class _DndWindow(TkinterDnD.DnDWrapper, ctk.CTk):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            try:
                self.TkdndVersion = TkinterDnD._require(self)
            except Exception:  # noqa: BLE001 - keep app alive without tkdnd
                log().debug("tkdnd tcl paketi yüklənmədi, drag&drop passivdir")

    return _DndWindow


class _Slider(ctk.CTkFrame):
    """Labelled 0..100 slider row used by the Proteus panel."""

    def __init__(self, master, label: str, value: int):
        super().__init__(master, fg_color="transparent")
        self.grid_columnconfigure(0, weight=1)
        self._label = ctk.CTkLabel(self, text=f"{label}: {value}", anchor="w",
                                   font=ctk.CTkFont("Segoe UI", 12))
        self._label.grid(row=0, column=0, sticky="ew")
        self._slider = ctk.CTkSlider(self, from_=0, to=100, number_of_steps=100,
                                     command=self._on_change)
        self._slider.set(value)
        self._slider.grid(row=1, column=0, sticky="ew", pady=(2, 8))

    def _on_change(self, raw: str) -> None:
        self._label.configure(text=f"{self._label.cget('text').split(':')[0]}: {self.value}")

    @property
    def value(self) -> int:
        return int(round(float(self._slider.get())))

    def set_enabled(self, enabled: bool) -> None:
        self._slider.configure(state="normal" if enabled else "disabled")


class MainWindow(_window_base()):
    def __init__(self, session: Dict):
        super().__init__()
        self.session = session
        ctk.set_appearance_mode("dark")
        self.title("Akai")
        self.geometry("1060x720")
        self.minsize(940, 620)
        self._apply_icon()

        self.source: Optional[Path] = None
        self.info: Optional[MediaProbe] = None
        self.device: DeviceInfo = DeviceInfo()
        self.worker: Optional[RenderWorker] = None
        self._preview_source: Optional[ImageTk.PhotoImage] = None
        self._preview_out: Optional[ImageTk.PhotoImage] = None

        self._build_layout()
        threading.Thread(target=self._detect_device_worker, daemon=True).start()

    # ---------------------------------------------------------------- layout
    def _apply_icon(self) -> None:
        if not ICON_PATH.exists():
            return
        try:
            self.iconbitmap(str(ICON_PATH))
        except tk.TclError:
            pass

    def _build_layout(self) -> None:
        self.grid_columnconfigure(0, weight=3)
        self.grid_columnconfigure(1, weight=2)
        self.grid_rowconfigure(0, weight=1)

        # ---------- left: preview + transport ------------------------------
        left = ctk.CTkFrame(self, fg_color="#15171c")
        left.grid(row=0, column=0, sticky="nsew", padx=(14, 7), pady=14)
        left.grid_columnconfigure(0, weight=1)
        left.grid_rowconfigure(1, weight=1)

        top = ctk.CTkFrame(left, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 4))
        top.grid_columnconfigure(0, weight=1)
        self.source_label = ctk.CTkLabel(
            top, text="Video seçilməyib — sürüşdürün və ya Seçin",
            anchor="w", font=ctk.CTkFont("Segoe UI", 13))
        self.source_label.grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(top, text="Fayl seç", width=110, fg_color="#2b2f36",
                      hover_color="#3a3f47",
                      command=self._choose_file).grid(row=0, column=1, padx=8)
        ctk.CTkButton(top, text="Önizləmə", width=110, fg_color="#2b2f36",
                      hover_color="#3a3f47",
                      command=self._preview_worker).grid(row=0, column=2)

        self.preview = ctk.CTkLabel(left, text="Preview",
                                    font=ctk.CTkFont("Segoe UI", 14),
                                    fg_color="#0e1014")
        self.preview.grid(row=1, column=0, sticky="nsew", padx=12, pady=6)
        self._enable_drop(self.preview)

        self.progress = ctk.CTkProgressBar(left)
        self.progress.set(0.0)
        self.progress.grid(row=2, column=0, sticky="ew", padx=12, pady=(4, 2))
        self.progress_label = ctk.CTkLabel(left, text="Hazır", anchor="w",
                                           font=ctk.CTkFont("Segoe UI", 12),
                                           text_color="#9aa0a6")
        self.progress_label.grid(row=3, column=0, sticky="ew", padx=12)

        transport = ctk.CTkFrame(left, fg_color="transparent")
        transport.grid(row=4, column=0, sticky="ew", padx=12, pady=(6, 12))
        transport.grid_columnconfigure((0, 1), weight=1)
        self.start_btn = ctk.CTkButton(transport, text="RENDER", height=44,
                                       fg_color=ACCENT, hover_color="#b8221e",
                                       font=ctk.CTkFont("Segoe UI Semibold", 15),
                                       command=self._start_render)
        self.start_btn.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.cancel_btn = ctk.CTkButton(transport, text="Dayandır", height=44,
                                        state="disabled", fg_color="#2b2f36",
                                        hover_color="#3a3f47",
                                        command=self._cancel_render)
        self.cancel_btn.grid(row=0, column=1, sticky="ew", padx=(6, 0))
        self.open_btn = ctk.CTkButton(transport, text="Çıxış qovluğunu aç",
                                      height=30, fg_color="transparent",
                                      border_width=1, command=self._open_output)
        self.open_btn.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))

        # ---------- right: scrollable settings -----------------------------
        self.settings = ctk.CTkScrollableFrame(self, label_text=" Parametrlər ")
        self.settings.grid(row=0, column=1, sticky="nsew", padx=(7, 14), pady=14)
        self.settings.grid_columnconfigure(0, weight=1)
        self._build_settings()

    def _section(self, title: str) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(self.settings, fg_color="#15171c", corner_radius=10)
        frame.grid(sticky="ew", pady=(0, 10))
        frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(frame, text=title, anchor="w",
                     font=ctk.CTkFont("Segoe UI Semibold", 13),
                     text_color=ACCENT).grid(row=0, column=0, sticky="ew",
                                             padx=12, pady=(10, 6))
        return frame

    def _build_settings(self) -> None:
        # --- Proteus -------------------------------------------------------
        proteus = self._section("PROTEUS — Bərpa modeli")
        self.mode = ctk.CTkSegmentedButton(proteus, values=["Auto", "Fine-Tune"],
                                           command=self._mode_changed)
        self.mode.set("Auto")
        self.mode.grid(row=1, column=0, sticky="ew", padx=12)
        self.sliders: List[_Slider] = []
        row = 2
        for label, default in (("Revert Compression", 40),
                               ("Recover Details", 55),
                               ("Sharpen", 35),
                               ("Reduce Noise", 30),
                               ("Dehaloing", 25)):
            slider = _Slider(proteus, label, default)
            slider.grid(row=row, column=0, sticky="ew", padx=12)
            slider.set_enabled(False)
            self.sliders.append(slider)
            row += 1
        self.deblur = ctk.CTkSwitch(proteus, text="Motion Deblur",
                                    font=ctk.CTkFont("Segoe UI", 12))
        self.deblur.grid(row=row, column=0, sticky="ew", padx=12, pady=(4, 12))

        # --- Upscale -------------------------------------------------------
        upscale = self._section("UPSCALE — Hədəf ölçü")
        self.target = ctk.CTkSegmentedButton(upscale, values=TARGETS,
                                             command=self._target_changed)
        self.target.set("4K")
        self.target.grid(row=1, column=0, sticky="ew", padx=12)
        custom = ctk.CTkFrame(upscale, fg_color="transparent")
        custom.grid(row=2, column=0, sticky="ew", padx=12, pady=(8, 12))
        custom.grid_columnconfigure((0, 2), weight=1)
        self.custom_w = ctk.CTkEntry(custom, placeholder_text="genişlik", height=34)
        self.custom_w.grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(custom, text="×").grid(row=0, column=1, padx=8)
        self.custom_h = ctk.CTkEntry(custom, placeholder_text="hündürlük", height=34)
        self.custom_h.grid(row=0, column=2, sticky="ew")
        self.custom_w.configure(state="disabled")
        self.custom_h.configure(state="disabled")

        # --- Interpolation + render params ----------------------------------
        render = self._section("RENDER — Kadr & Kodlayıcı")
        self.interp = ctk.CTkSegmentedButton(render, values=INTERP)
        self.interp.set("Off")
        self.interp.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 8))
        self.encoder = ctk.CTkSegmentedButton(render, values=ENCODERS)
        self.encoder.set("H.264")
        self.encoder.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 10))

        # --- Device ---------------------------------------------------------
        device = self._section("GPU / VRAM")
        self.device_label = ctk.CTkLabel(device, text="Cihaz yoxlanılır…",
                                         anchor="w", justify="left",
                                         font=ctk.CTkFont("Segoe UI", 12))
        self.device_label.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))

    # ------------------------------------------------------------- callbacks
    def _mode_changed(self, mode: str) -> None:
        for slider in self.sliders:
            slider.set_enabled(mode == "Fine-Tune")

    def _target_changed(self, target: str) -> None:
        state = "normal" if target == "CUSTOM" else "disabled"
        self.custom_w.configure(state=state)
        self.custom_h.configure(state=state)

    def _enable_drop(self, widget) -> None:
        if not DND_AVAILABLE:
            return
        try:
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self._on_drop)
        except tk.TclError as exc:  # pragma: no cover - platform quirk
            log().debug("dnd unavailable: %s", exc)

    def _on_drop(self, event) -> None:
        raw = event.data.strip().strip("{}")
        if raw:
            self._set_source(Path(raw.split("} {")[0]))

    def _choose_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Video seçin",
            filetypes=[("Video faylları", "*.mp4 *.mkv *.mov *.avi *.webm *.m4v"),
                       ("Bütün fayllar", "*.*")])
        if path:
            self._set_source(Path(path))

    def _set_source(self, path: Path) -> None:
        try:
            self.source = path
            self.info = probe(path)
            self.source_label.configure(text=self.info.summary)
            self._show_preview(None)
        except FFmpegMissing as exc:
            messagebox.showerror("Akai", str(exc))
        except Exception as exc:  # noqa: BLE001 - corrupt file must not crash
            log().exception("fayl oxunmadı")
            messagebox.showerror("Akai", f"Fayl oxuna bilmədi: {exc}")

    # -------------------------------------------------------------- previews
    def _show_preview(self, image: Optional[Image.Image]) -> None:
        if image is None:
            self.preview.configure(image=None, text="Preview")
            return
        image.thumbnail((480, 360))
        photo = ImageTk.PhotoImage(image)
        self._preview_source = photo  # keep reference alive
        self.preview.configure(image=photo, text="")

    def _preview_worker(self) -> None:
        if not self.source:
            messagebox.showinfo("Akai", "Əvvəlcə video seçin.")
            return

        def work() -> None:
            try:
                job = self._make_job()
                out_png = BASE_DIR / ".preview_tmp.png"
                vf = build_filter_chain(job, self.info.width, self.info.height)
                from . import ffmpeg_tools

                import subprocess

                subprocess.run(
                    [ffmpeg_tools.find_ffmpeg(), "-hide_banner", "-loglevel",
                     "error", "-y", "-ss", "1.0", "-i", str(self.source),
                     "-vf", vf, "-frames:v", "1", str(out_png)],
                    capture_output=True, timeout=120)
                if out_png.exists():
                    image = Image.open(out_png).convert("RGB")
                    self.after(0, lambda: self._show_preview(image))
                else:
                    self.after(0, lambda: messagebox.showwarning(
                        "Akai", "Önizləmə yaradıla bilmədi."))
            except Exception as exc:  # noqa: BLE001
                log().exception("preview failed")
                message = f"Önizləmə xətası: {exc}"
                self.after(0, lambda: messagebox.showwarning("Akai", message))

        threading.Thread(target=work, daemon=True).start()

    # ----------------------------------------------------------- device info
    def _detect_device_worker(self) -> None:
        device = detect_device()
        self.device = device
        vram = f"{device.vram_mb} MB VRAM" if device.vram_mb else "paylaşımlı yaddaş"
        if device.supported:
            text = f"Cihaz: {device.label}\nNöv: {device.kind.upper()} · {vram}"
        else:
            text = (f"Cihaz: {device.label}\nDiqqət: uyğun GPU tapılmadı — "
                    "render CPU-da daha yavaş gedəcək.")
        self.after(0, lambda: self.device_label.configure(text=text))
        if not device.supported:
            log().warning("GPU tapılmadı, CPU fallback işlədilir")

    # ---------------------------------------------------------------- render
    def _make_job(self) -> RenderJob:
        custom = None
        if self.target.get() == "CUSTOM":
            try:
                custom = (int(self.custom_w.get()), int(self.custom_h.get()))
            except ValueError:
                custom = None
        interp_value = {"Off": 0, "60 fps": 60, "120 fps": 120}[self.interp.get()]
        values = {slider._label.cget("text").split(":")[0]: slider.value
                  for slider in self.sliders}
        return RenderJob(
            source=self.source or Path(),
            output_dir=Path(self.source.parent if self.source else BASE_DIR),
            target=self.target.get(),
            custom_size=custom,
            encoder=self.encoder.get(),
            auto_mode=self.mode.get() == "Auto",
            revert_compression=values.get("Revert Compression", 40),
            recover_details=values.get("Recover Details", 55),
            sharpen=values.get("Sharpen", 35),
            reduce_noise=values.get("Reduce Noise", 30),
            dehaloing=values.get("Dehaloing", 25),
            motion_deblur=bool(self.deblur.get()),
            interp_fps=interp_value,
            device=self.device,
        )

    def _start_render(self) -> None:
        if not self.source or not self.info:
            messagebox.showinfo("Akai", "Əvvəlcə video seçin.")
            return
        if self.target.get() == "CUSTOM":
            try:
                width, height = int(self.custom_w.get()), int(self.custom_h.get())
                if width < 64 or height < 64:
                    raise ValueError
            except ValueError:
                messagebox.showwarning("Akai",
                                       "CUSTOM üçün en×hölçü düzgün deyil "
                                       "(min 64px).")
                return
        try:
            job = self._make_job()
        except Exception as exc:  # noqa: BLE001
            log().exception("job qurulmadı")
            messagebox.showerror("Akai", f"Render xətası: {exc}")
            return

        plan = plan_tiles(self.info.width, self.info.height,
                          max(job.target_size(self.info.width, self.info.height)[0]
                              // max(self.info.width, 1), 1),
                          self.device.vram_mb)
        log().info("tiling plan: %s", plan)

        self.start_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.worker = RenderWorker(
            job,
            progress_cb=lambda f, m: self.after(
                0, lambda: (self.progress.set(f),
                            self.progress_label.configure(text=m))),
            done_cb=self._on_render_done,
            error_cb=self._on_render_error,
        )
        self.worker.start()

    def _cancel_render(self) -> None:
        if self.worker:
            self.worker.cancel()
            self.progress_label.configure(text="Dayandırılır…")

    def _on_render_done(self, output: Path) -> None:
        self.after(0, lambda: (
            self.start_btn.configure(state="normal"),
            self.cancel_btn.configure(state="disabled"),
            self.progress_label.configure(text=f"Hazır: {output.name}")))

    def _on_render_error(self, message: str) -> None:
        self.after(0, lambda: (
            self.start_btn.configure(state="normal"),
            self.cancel_btn.configure(state="disabled"),
            self.progress.set(0.0),
            self.progress_label.configure(text=message),
            messagebox.showwarning("Akai", message)))

    def _open_output(self) -> None:
        folder = Path(self.source.parent if self.source else BASE_DIR)
        try:
            import os
            import subprocess
            import sys

            if sys.platform.startswith("win"):
                os.startfile(folder)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
        except Exception as exc:  # noqa: BLE001
            log().warning("qovluq açıla bilmədi: %s", exc)
