"""CustomTkinter GUI — dark mode, drag-and-drop, live progress.

The window is a *thin* shell: every decision lives in
:mod:`reelforge.presets`, :mod:`reelforge.filters` and :mod:`reelforge.encode`,
and the heavy work runs in :class:`reelforge.pipeline.Pipeline` on a worker
thread.  The UI only renders events that arrive through a ``queue.Queue``,
which keeps Tk single-threaded and therefore crash-free.

Run with::

    python -m reelforge
"""

from __future__ import annotations

import queue
import sys
import threading
from pathlib import Path
from typing import Dict, List, Optional

try:
    import customtkinter as ctk
except ImportError as exc:  # pragma: no cover - user-facing guidance
    raise ImportError(
        "CustomTkinter quraşdırılmayıb:  pip install customtkinter  "
        "(Linux-da əlavə olaraq python3-tk lazımdır)"
    ) from exc

from tkinter import filedialog, messagebox

from ..models import (
    Codec,
    ColorTag,
    FitMode,
    InterpolationEngineKind,
    JobOptions,
    ProgressInfo,
    ensure_video_files,
)
from ..pipeline import ReelForge
from ..presets import Presets
from ..toolchain import ToolchainError
from . import dnd
from .theme import APPEARANCE_MODE, COLOR_THEME, FONTS, PALETTE

ctk.set_appearance_mode(APPEARANCE_MODE)
ctk.set_default_color_theme(COLOR_THEME)


# --------------------------------------------------------------------------- #
# small widgets
# --------------------------------------------------------------------------- #


class DropZone(ctk.CTkFrame):
    """Dashed-border area that accepts dropped files *and* plain clicks."""

    def __init__(self, master, on_files, dnd_enabled: bool):
        super().__init__(master, corner_radius=16, fg_color=PALETTE["surface_2"],
                         border_width=2, border_color=PALETTE["border"], height=128)
        self.on_files = on_files
        title = "Videonu buraya sürükləyib buraxın" if dnd_enabled else "Fayl seçmək üçün klikləyin"
        hint = (
            "MP4 · MOV · MKV · AVI · WebM — birdən çox fayl da olar"
            if dnd_enabled
            else "Sürüklə-burax üçün: pip install tkinterdnd2"
        )
        self.label = ctk.CTkLabel(self, text=title, font=FONTS["h2"], text_color=PALETTE["text"])
        self.label.pack(pady=(26, 2))
        self.sub = ctk.CTkLabel(self, text=hint, font=FONTS["small"], text_color=PALETTE["text_dim"])
        self.sub.pack()
        for widget in (self, self.label, self.sub):
            widget.bind("<Button-1>", self._clicked)
        self.pack_propagate(False)

    def _clicked(self, _event=None) -> None:
        picked = filedialog.askopenfilenames(
            title="Video seçin",
            filetypes=[
                ("Video faylları", "*.mp4 *.mov *.mkv *.avi *.webm *.m4v *.mpg *.ts *.flv"),
                ("Bütün fayllar", "*.*"),
            ],
        )
        if picked:
            self.on_files(list(picked))

    def highlight(self, active: bool) -> None:
        self.configure(border_color=PALETTE["accent"] if active else PALETTE["border"])


class PresetCard(ctk.CTkFrame):
    """Selectable preset with a title, a tagline and a description."""

    def __init__(self, master, preset, variable, command):
        super().__init__(master, corner_radius=12, fg_color=PALETTE["surface_2"],
                         border_width=1, border_color=PALETTE["border"])
        self.preset = preset
        self.variable = variable
        self.radio = ctk.CTkRadioButton(
            self, text=preset.label, variable=variable, value=preset.id,
            font=FONTS["h2"], command=command, text_color=PALETTE["text"],
            fg_color=PALETTE["accent"], hover_color=PALETTE["accent"],
        )
        self.radio.pack(anchor="w", padx=12, pady=(10, 0))
        self.tagline = ctk.CTkLabel(
            self, text=preset.tagline, font=FONTS["small"],
            text_color=PALETTE["accent"], anchor="w", justify="left",
        )
        self.tagline.pack(anchor="w", padx=34)
        self.desc = ctk.CTkLabel(
            self, text=preset.description, font=FONTS["small"],
            text_color=PALETTE["text_dim"], anchor="w", justify="left", wraplength=300,
        )
        self.desc.pack(anchor="w", padx=34, pady=(2, 10))
        for widget in (self, self.tagline, self.desc):
            widget.bind("<Button-1>", lambda _e: self.select())
        self.grid_columnconfigure(0, weight=1)

    def select(self) -> None:
        self.variable.set(self.preset.id)
        self.radio.select()


# --------------------------------------------------------------------------- #
# application
# --------------------------------------------------------------------------- #


class ReelForgeApp(ctk.CTk):
    def __init__(self, engine: ReelForge):
        super().__init__()
        self.engine = engine
        self.dnd_enabled = dnd.enable_on(self)
        self.events: "queue.Queue[tuple]" = queue.Queue()
        self.worker: Optional[threading.Thread] = None
        self.files: List[Path] = []
        self.file_rows: Dict[Path, ctk.CTkFrame] = {}

        # -- tk variables ---------------------------------------------------
        self.var_preset = ctk.StringVar(value=Presets.ULTRA_120.id)
        self.var_codec = ctk.StringVar(value="H.264")
        self.var_crf = ctk.DoubleVar(value=0)      # 0 = preset default
        self.var_fps = ctk.StringVar(value="Preset")
        self.var_interp = ctk.StringVar(value="auto")
        self.var_quality = ctk.StringVar(value="balanced")
        self.var_fit = ctk.StringVar(value=FitMode.KEEP.value)
        self.var_width = ctk.StringVar(value="1080")
        self.var_height = ctk.StringVar(value="1920")
        self.var_dual = ctk.BooleanVar(value=True)
        self.var_verify = ctk.BooleanVar(value=True)
        self.var_faststart = ctk.BooleanVar(value=True)
        self.var_audio_br = ctk.StringVar(value="320")
        self.var_audio_sr = ctk.StringVar(value="48000")
        self.var_threads = ctk.StringVar(value="0 (avtomatik)")
        self.var_outdir = ctk.StringVar(value="")

        self._build_layout()
        self._log(self.engine.describe())

    # ------------------------------------------------------------------ UI --
    def _build_layout(self) -> None:
        self.title("ReelForge — TikTok / Reels / Shorts 60-120FPS Studio")
        self.geometry("1320x820")
        self.minsize(1120, 700)
        self.configure(fg_color=PALETTE["bg"])

        self.grid_columnconfigure(0, weight=10, uniform="col")
        self.grid_columnconfigure(1, weight=11, uniform="col")
        self.grid_columnconfigure(2, weight=10, uniform="col")
        self.grid_rowconfigure(1, weight=1)

        self._build_header()
        self._build_left()
        self._build_center()
        self._build_right()
        self._build_bottom()
        self.after(90, self._pump)

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, fg_color=PALETTE["surface"], corner_radius=0, height=64)
        header.grid(row=0, column=0, columnspan=3, sticky="ew")
        header.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            header, text="ReelForge", font=FONTS["title"], text_color=PALETTE["accent"]
        ).grid(row=0, column=0, padx=(18, 8), pady=12, sticky="w")
        ctk.CTkLabel(
            header,
            text="60/120FPS · minimal sıxılma · TikTok-safe GOP · RIFE AI",
            font=FONTS["small"], text_color=PALETTE["text_dim"],
        ).grid(row=0, column=1, padx=8, pady=12, sticky="w")
        self.badge = ctk.CTkLabel(
            header,
            text=f"ffmpeg {self.engine.toolchain.version or '?'}",
            font=FONTS["small"], text_color=PALETTE["text_dim"],
        )
        self.badge.grid(row=0, column=2, padx=18, pady=12, sticky="e")

    def _build_left(self) -> None:
        col = ctk.CTkFrame(self, fg_color=PALETTE["surface"], corner_radius=14)
        col.grid(row=1, column=0, sticky="nsew", padx=(12, 6), pady=(10, 6))
        col.grid_rowconfigure(2, weight=1)
        col.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(col, text="1 · Mənbə fayllar", font=FONTS["h2"],
                     text_color=PALETTE["text"]).grid(row=0, column=0, padx=14, pady=(12, 6), sticky="w")

        self.drop = DropZone(col, self.add_files, self.dnd_enabled)
        self.drop.grid(row=1, column=0, padx=12, pady=4, sticky="ew")
        if self.dnd_enabled:
            dnd.register_drop_target(self.drop, self.add_files)

        buttons = ctk.CTkFrame(col, fg_color="transparent")
        buttons.grid(row=2, column=0, sticky="nsew", padx=12, pady=6)
        buttons.grid_rowconfigure(1, weight=1)
        buttons.grid_columnconfigure(0, weight=1)

        row = ctk.CTkFrame(buttons, fg_color="transparent")
        row.grid(row=0, column=0, sticky="ew")
        row.grid_columnconfigure((0, 1), weight=1)
        ctk.CTkButton(row, text="+ Fayl əlavə et", command=self._pick_files,
                      fg_color=PALETTE["accent_2"], hover_color="#d81e42"
                      ).grid(row=0, column=0, padx=(0, 4), sticky="ew")
        ctk.CTkButton(row, text="Təmizlə", command=self.clear_files,
                      fg_color=PALETTE["surface_3"], hover_color=PALETTE["border"]
                      ).grid(row=0, column=1, padx=(4, 0), sticky="ew")

        self.list_frame = ctk.CTkScrollableFrame(
            buttons, fg_color=PALETTE["bg"], corner_radius=10, label_text=None
        )
        self.list_frame.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        self.list_frame.grid_columnconfigure(0, weight=1)
        self.empty_hint = ctk.CTkLabel(
            self.list_frame, text="Siyahı boşdur", font=FONTS["small"],
            text_color=PALETTE["text_dim"],
        )
        self.empty_hint.grid(row=0, column=0, pady=18)

        self.count_label = ctk.CTkLabel(col, text="0 fayl", font=FONTS["small"],
                                        text_color=PALETTE["text_dim"])
        self.count_label.grid(row=3, column=0, padx=14, pady=(2, 12), sticky="w")

    def _build_center(self) -> None:
        col = ctk.CTkFrame(self, fg_color=PALETTE["surface"], corner_radius=14)
        col.grid(row=1, column=1, sticky="nsew", padx=6, pady=(10, 6))
        col.grid_rowconfigure(1, weight=1)
        col.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(col, text="2 · Rejim (preset)", font=FONTS["h2"],
                     text_color=PALETTE["text"]).grid(row=0, column=0, padx=14, pady=(12, 6), sticky="w")

        scroll = ctk.CTkScrollableFrame(col, fg_color=PALETTE["bg"], corner_radius=10)
        scroll.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 10))
        scroll.grid_columnconfigure(0, weight=1)
        for index, preset in enumerate(Presets.ALL):
            card = PresetCard(scroll, preset, self.var_preset, self._preset_changed)
            card.grid(row=index, column=0, sticky="ew", pady=4, padx=2)
        PresetCard  # keep a reference for typing tools
        self._preset_changed()

    def _build_right(self) -> None:
        col = ctk.CTkFrame(self, fg_color=PALETTE["surface"], corner_radius=14)
        col.grid(row=1, column=2, sticky="nsew", padx=(6, 12), pady=(10, 6))
        col.grid_rowconfigure(1, weight=1)
        col.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(col, text="3 · Parametrlər", font=FONTS["h2"],
                     text_color=PALETTE["text"]).grid(row=0, column=0, padx=14, pady=(12, 6), sticky="w")

        scroll = ctk.CTkScrollableFrame(col, fg_color=PALETTE["bg"], corner_radius=10)
        scroll.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        scroll.grid_columnconfigure(0, weight=1)

        def section(title: str, row: int) -> None:
            ctk.CTkLabel(scroll, text=title, font=FONTS["h2"],
                         text_color=PALETTE["accent"]).grid(
                row=row, column=0, sticky="w", pady=(12, 2))

        def widget_row(row: int) -> ctk.CTkFrame:
            frame = ctk.CTkFrame(scroll, fg_color="transparent")
            frame.grid(row=row, column=0, sticky="ew", pady=2)
            frame.grid_columnconfigure(1, weight=1)
            return frame

        section("Kodek və keyfiyyət", 0)
        r = widget_row(1)
        ctk.CTkLabel(r, text="Kodek", font=FONTS["body"],
                     text_color=PALETTE["text_dim"]).grid(row=0, column=0, sticky="w", padx=(0, 8))
        ctk.CTkSegmentedButton(r, values=["H.264", "HEVC"], variable=self.var_codec,
                               command=lambda _v: None).grid(row=0, column=1, sticky="e")

        r = widget_row(2)
        ctk.CTkLabel(r, text="CRF (0 = preset)", font=FONTS["body"],
                     text_color=PALETTE["text_dim"]).grid(row=0, column=0, sticky="w")
        self.crf_label = ctk.CTkLabel(r, text="preset", font=FONTS["body"], width=42,
                                      text_color=PALETTE["accent"])
        self.crf_label.grid(row=0, column=1, sticky="e")
        ctk.CTkSlider(r, from_=0, to=30, number_of_steps=30, variable=self.var_crf,
                      command=self._crf_changed).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 4))

        section("Kadr sürəti və interpolyasiya", 3)
        r = widget_row(4)
        ctk.CTkLabel(r, text="Hədəf FPS", font=FONTS["body"],
                     text_color=PALETTE["text_dim"]).grid(row=0, column=0, sticky="w", padx=(0, 8))
        ctk.CTkSegmentedButton(r, values=["Preset", "60", "120", "240"],
                               variable=self.var_fps, command=lambda _v: None
                               ).grid(row=0, column=1, sticky="e")

        r = widget_row(5)
        ctk.CTkLabel(r, text="Mühərrik", font=FONTS["body"],
                     text_color=PALETTE["text_dim"]).grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.interp_menu = ctk.CTkOptionMenu(
            r, values=[k.value for k in InterpolationEngineKind], variable=self.var_interp)
        self.interp_menu.grid(row=0, column=1, sticky="e")

        r = widget_row(6)
        ctk.CTkLabel(r, text="Keyfiyyət", font=FONTS["body"],
                     text_color=PALETTE["text_dim"]).grid(row=0, column=0, sticky="w", padx=(0, 8))
        ctk.CTkSegmentedButton(r, values=["fast", "balanced", "quality"],
                               variable=self.var_quality, command=lambda _v: None
                               ).grid(row=0, column=1, sticky="e")

        section("Kadr ölçüsü", 7)
        r = widget_row(8)
        ctk.CTkLabel(r, text="Yerləşdirmə", font=FONTS["body"],
                     text_color=PALETTE["text_dim"]).grid(row=0, column=0, sticky="w", padx=(0, 8))
        ctk.CTkOptionMenu(r, values=[f.value for f in FitMode], variable=self.var_fit
                          ).grid(row=0, column=1, sticky="e")
        r = widget_row(9)
        ctk.CTkLabel(r, text="En × Hünd.", font=FONTS["body"],
                     text_color=PALETTE["text_dim"]).grid(row=0, column=0, sticky="w", padx=(0, 8))
        size = ctk.CTkFrame(r, fg_color="transparent")
        size.grid(row=0, column=1, sticky="e")
        ctk.CTkEntry(size, textvariable=self.var_width, width=70).grid(row=0, column=0, padx=(0, 4))
        ctk.CTkEntry(size, textvariable=self.var_height, width=70).grid(row=0, column=1)

        section("Audio", 10)
        r = widget_row(11)
        ctk.CTkLabel(r, text="AAC bitrate", font=FONTS["body"],
                     text_color=PALETTE["text_dim"]).grid(row=0, column=0, sticky="w", padx=(0, 8))
        ctk.CTkOptionMenu(r, values=["128", "192", "256", "320"], variable=self.var_audio_br
                          ).grid(row=0, column=1, sticky="e")
        r = widget_row(12)
        ctk.CTkLabel(r, text="Sample rate", font=FONTS["body"],
                     text_color=PALETTE["text_dim"]).grid(row=0, column=0, sticky="w", padx=(0, 8))
        ctk.CTkOptionMenu(r, values=["44100", "48000", "96000"], variable=self.var_audio_sr
                          ).grid(row=0, column=1, sticky="e")

        section("Əlavə", 13)
        for offset, (text, var) in enumerate([
            ("İki variant (60 + 120 FPS)", self.var_dual),
            ("Nəticəni yoxla (QA)", self.var_verify),
            ("+faststart (veb üçün)", self.var_faststart),
        ]):
            ctk.CTkSwitch(scroll, text=text, variable=var, onvalue=True, offvalue=False,
                          font=FONTS["body"], text_color=PALETTE["text_dim"]
                          ).grid(row=14 + offset, column=0, sticky="w", pady=1)

        r = widget_row(17)
        ctk.CTkLabel(r, text="Threads", font=FONTS["body"],
                     text_color=PALETTE["text_dim"]).grid(row=0, column=0, sticky="w", padx=(0, 8))
        ctk.CTkOptionMenu(r, values=["0 (avtomatik)", "2", "4", "6", "8", "12"],
                          variable=self.var_threads).grid(row=0, column=1, sticky="e")

        section("Çıxış qovluğu", 18)
        r = widget_row(19)
        ctk.CTkEntry(r, textvariable=self.var_outdir, placeholder_text="mənbə ilə eyni qovluq"
                     ).grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(r, text="Seç", width=54, fg_color=PALETTE["surface_3"],
                      hover_color=PALETTE["border"], command=self._pick_outdir
                      ).grid(row=0, column=1, padx=(6, 0))

    def _build_bottom(self) -> None:
        bottom = ctk.CTkFrame(self, fg_color=PALETTE["surface"], corner_radius=14)
        bottom.grid(row=2, column=0, columnspan=3, sticky="nsew", padx=12, pady=(6, 12))
        bottom.grid_columnconfigure(0, weight=1)
        bottom.grid_rowconfigure(1, weight=1)

        bar_row = ctk.CTkFrame(bottom, fg_color="transparent")
        bar_row.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 4))
        bar_row.grid_columnconfigure(1, weight=1)

        self.start_btn = ctk.CTkButton(
            bar_row, text="▶  Emalı başlat", width=150, command=self.start,
            fg_color=PALETTE["accent"], hover_color="#00c3a4", text_color="#06231d",
            font=FONTS["h2"],
        )
        self.start_btn.grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.cancel_btn = ctk.CTkButton(
            bar_row, text="Dayandır", width=100, command=self.cancel, state="disabled",
            fg_color=PALETTE["surface_3"], hover_color=PALETTE["error"],
        )
        self.cancel_btn.grid(row=0, column=1, sticky="w")
        self.progress = ctk.CTkProgressBar(bar_row, fg_color=PALETTE["surface_3"],
                                           progress_color=PALETTE["accent"], height=14)
        self.progress.set(0)
        self.progress.grid(row=0, column=2, sticky="ew", padx=12)
        self.progress_label = ctk.CTkLabel(bar_row, text="hazır", width=190,
                                           font=FONTS["small"], text_color=PALETTE["text_dim"])
        self.progress_label.grid(row=0, column=3, sticky="e")
        ctk.CTkButton(
            bar_row, text="Əmrləri göstər", width=120, command=self.show_commands,
            fg_color=PALETTE["surface_3"], hover_color=PALETTE["border"],
        ).grid(row=0, column=4, padx=(8, 0))

        self.log_box = ctk.CTkTextbox(
            bottom, fg_color=PALETTE["bg"], text_color=PALETTE["text"],
            font=FONTS["mono"], wrap="word", corner_radius=10,
        )
        self.log_box.grid(row=1, column=0, sticky="nsew", padx=14, pady=(4, 14))

    # --------------------------------------------------------------- events --
    def _preset_changed(self) -> None:
        preset = Presets.by_id(self.var_preset.get())
        self._log(
            f"Rejim seçildi: {preset.label} — çıxışlar: "
            + ", ".join(f"{f}fps" for f in preset.output_fps_list)
        )
        self.var_crf.set(0)
        self.crf_label.configure(text="preset")

    def _crf_changed(self, value) -> None:
        value = float(value)
        if value < 1:
            self.crf_label.configure(text="preset")
        else:
            self.crf_label.configure(text=f"CRF {int(value)}")

    def _pick_files(self) -> None:
        picked = filedialog.askopenfilenames(
            title="Video seçin",
            filetypes=[("Video faylları", "*.mp4 *.mov *.mkv *.avi *.webm *.m4v *.mpg *.ts *.flv")],
        )
        if picked:
            self.add_files(list(picked))

    def _pick_outdir(self) -> None:
        picked = filedialog.askdirectory(title="Çıxış qovluğu")
        if picked:
            self.var_outdir.set(picked)

    def add_files(self, paths: List[str]) -> None:
        files = ensure_video_files(paths)
        skipped = len(paths) - len(files)
        for path in files:
            if path in self.file_rows:
                continue
            self.files.append(path)
            self._add_row(path)
        if skipped > 0:
            self._log(f"{skipped} fayl dəstəklənmir və ya tapılmadı.")
        self._refresh_count()

    def _add_row(self, path: Path) -> None:
        if self.empty_hint is not None:
            self.empty_hint.grid_forget()
            self.empty_hint = None
        row = ctk.CTkFrame(self.list_frame, fg_color=PALETTE["surface_2"], corner_radius=8)
        row.grid(row=len(self.file_rows), column=0, sticky="ew", pady=2)
        row.grid_columnconfigure(0, weight=1)
        detail = ""
        try:
            info = self.engine.probe(path)
            detail = f"{info.resolution} · {info.fps:.2f}fps · {info.duration:.1f}s"
            if info.is_hdr:
                detail += " · HDR"
        except Exception as exc:
            detail = f"oxunmadı: {exc}"
        ctk.CTkLabel(row, text=path.name, font=FONTS["body"], anchor="w",
                     text_color=PALETTE["text"]).grid(row=0, column=0, padx=(10, 4), pady=(6, 0), sticky="w")
        ctk.CTkLabel(row, text=detail, font=FONTS["small"], anchor="w",
                     text_color=PALETTE["text_dim"]).grid(row=1, column=0, padx=(10, 4), pady=(0, 6), sticky="w")
        ctk.CTkButton(
            row, text="✕", width=28, fg_color="transparent", hover_color=PALETTE["error"],
            command=lambda p=path: self.remove_file(p),
        ).grid(row=0, column=1, rowspan=2, padx=(0, 6))
        self.file_rows[path] = row

    def remove_file(self, path: Path) -> None:
        row = self.file_rows.pop(path, None)
        if row is not None:
            row.destroy()
        if path in self.files:
            self.files.remove(path)
        self._reindex_rows()
        self._refresh_count()

    def clear_files(self) -> None:
        for row in self.file_rows.values():
            row.destroy()
        self.file_rows.clear()
        self.files.clear()
        self._refresh_count()

    def _reindex_rows(self) -> None:
        for index, (path, row) in enumerate(self.file_rows.items()):
            row.grid(row=index, column=0, sticky="ew", pady=2)

    def _refresh_count(self) -> None:
        count = len(self.files)
        self.count_label.configure(text=f"{count} fayl" if count else "Siyahı boşdur")

    # -------------------------------------------------------------- options --
    def collect_options(self) -> JobOptions:
        crf = int(self.var_crf.get())
        fps_text = self.var_fps.get()
        try:
            width = int(self.var_width.get()) if self.var_width.get().strip() else None
            height = int(self.var_height.get()) if self.var_height.get().strip() else None
        except ValueError:
            width = height = None
        threads_text = self.var_threads.get().split()[0]
        outdir = self.var_outdir.get().strip()
        return JobOptions(
            output_dir=Path(outdir) if outdir else None,
            fit=FitMode(self.var_fit.get()),
            target_width=width if self.var_fit.get() != FitMode.KEEP.value else None,
            target_height=height if self.var_fit.get() != FitMode.KEEP.value else None,
            interpolation_quality=self.var_quality.get(),
            color_tag=ColorTag.BT709,
            audio_bitrate=int(self.var_audio_br.get()),
            audio_sample_rate=int(self.var_audio_sr.get()),
            threads=int(threads_text),
            dual_output=bool(self.var_dual.get()),
            verify_output=bool(self.var_verify.get()),
            faststart=bool(self.var_faststart.get()),
            codec=Codec.HEVC if self.var_codec.get() == "HEVC" else Codec.H264,
            crf_override=crf if crf > 0 else None,
            fps_override=None if fps_text == "Preset" else int(fps_text),
            interpolation_override=InterpolationEngineKind(self.var_interp.get()),
        )

    # ------------------------------------------------------------------ run --
    def show_commands(self) -> None:
        if not self.files:
            messagebox.showinfo("ReelForge", "Əvvəlcə video faylı əlavə edin.")
            return
        try:
            preset = Presets.by_id(self.var_preset.get())
            opts = self.collect_options()
            for source in self.files:
                self._log(f"### {source.name}")
                for index, command in enumerate(
                    self.engine.build_commands(source, preset, opts), 1
                ):
                    self._log(f"[{index}] " + " ".join(command))
        except Exception as exc:
            messagebox.showerror("ReelForge", f"Əmrlər qurulmadı:\n{exc}")

    def start(self) -> None:
        if not self.files:
            messagebox.showinfo("ReelForge", "Əvvəlcə video faylı əlavə edin.")
            return
        if self.worker and self.worker.is_alive():
            return
        preset = Presets.by_id(self.var_preset.get())
        opts = self.collect_options()
        self.engine.progress_callback = self._on_progress
        self.engine.log_callback = self._log
        self.start_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.progress.set(0)
        self._log(f"Başlayır: {len(self.files)} fayl · {preset.label}")
        self.worker = threading.Thread(
            target=self._work, args=(list(self.files), preset, opts), daemon=True
        )
        self.worker.start()

    def _work(self, files, preset, opts) -> None:
        try:
            results = self.engine.run_many(files, preset, opts)
            ok = sum(1 for r in results if r.ok)
            self.events.put(("done", f"{ok}/{len(results)} fayl uğurla emal olundu"))
        except Exception as exc:  # pragma: no cover - defensive
            self.events.put(("error", str(exc)))

    def cancel(self) -> None:
        self.engine.cancel()
        self._log("Dayandırılır…")

    # ------------------------------------------------------------- UI queue --
    def _log(self, text: str) -> None:
        if threading.current_thread() is not threading.main_thread():
            self.events.put(("log", text))
            return
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")

    def _on_progress(self, info: ProgressInfo) -> None:
        self.events.put(("progress", info))

    def _pump(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "log":
                    self.log_box.insert("end", payload + "\n")
                    self.log_box.see("end")
                elif kind == "progress":
                    info: ProgressInfo = payload
                    self.progress.set(max(0.0, min(1.0, info.percent / 100.0)))
                    eta = f" · ETA {info.eta_seconds:.0f}s" if info.eta_seconds else ""
                    self.progress_label.configure(
                        text=f"{info.percent:5.1f}%  {info.phase}{eta}"
                    )
                elif kind == "done":
                    self.progress.set(1.0)
                    self.progress_label.configure(text=payload)
                    self._log(payload)
                    self.start_btn.configure(state="normal")
                    self.cancel_btn.configure(state="disabled")
                elif kind == "error":
                    self.progress_label.configure(text="XƏTA")
                    self._log("XƏTA: " + payload)
                    self.start_btn.configure(state="normal")
                    self.cancel_btn.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(90, self._pump)


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #


def launch(ffmpeg: Optional[str] = None, ffprobe: Optional[str] = None) -> bool:
    """Create the window and run the main loop.  ``False`` if it cannot start."""
    try:
        engine = ReelForge(ffmpeg, ffprobe)
    except ToolchainError as exc:
        print(f"XƏTA: {exc}", file=sys.stderr)
        return False

    try:
        app = ReelForgeApp(engine)
    except Exception as exc:  # no display / broken Tk
        print(f"GUI açıla bilmədi: {type(exc).__name__}: {exc}", file=sys.stderr)
        return False

    app.protocol("WM_DELETE_WINDOW", app.destroy)
    try:
        app.mainloop()
    except KeyboardInterrupt:  # pragma: no cover
        pass
    return True
