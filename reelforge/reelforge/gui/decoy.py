"""Decoy-style window: red-toned hacker terminal, wide 2-column layout.

Layout (1060x700 — everything visible at once, no scrolling)

    +---------------------------------------------------------------+
    |  █ DECOY 120FPS PRO   root@reelforge:~#      [ffmpeg 7.0.2 ●]  |  header
    +----------------------------------+----------------------------+
    |  » INPUT                         |  » EXPORT                  |
    |  [ DRAG & DROP VIDEO HERE ]      |  [####--------] 48%        |
    |  [ SELECT VIDEO ]  file info     |  Encoding…        ETA 12s  |
    |  » RENDER TIER                   |  [  EXPORT / CONVERT  ]    |
    |  [ TURBO ] [ SAFE MODE ]         |  [      CANCEL       ]     |
    |  [ STUDIO ] [ ULTRA 120FPS ]     |  » SYSTEM LOG              |
    |  » CUSTOM CONTROLS               |  [12:04:31] engine=rife    |
    |  MOTION BLUR / SHARPENING        |  [12:04:44] Render Bitti ✓ |
    |  FPS / RESOLUTION / CODEC        |  [12:04:45] TikTok-a …     |
    |  OUTPUT / TIKTOK / HESAB / DESC  |  █                         |
    +----------------------------------+----------------------------+

The window holds no rendering logic: it reads the widgets into a
:class:`~reelforge.uistate.UIState`, hands that to
:class:`~reelforge.pipeline.ReelForge` on a worker thread, and paints whatever
arrives on the event queue.  Every decision (which FFmpeg flags, which engine,
which fallback) is made in the backend and covered by tests.

Startup is gated by the hacker-style password lock (:mod:`reelforge.gui.lock`,
logic in :mod:`reelforge.access`).
"""

from __future__ import annotations

import queue
import sys
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import customtkinter as ctk
except ImportError as exc:  # pragma: no cover - user-facing guidance
    raise ImportError(
        "CustomTkinter quraşdırılmayıb:  pip install customtkinter  "
        "(Linux-da əlavə olaraq python3-tk lazımdır)"
    ) from exc

from tkinter import filedialog

from ..models import ProgressInfo, ensure_video_files
from ..pipeline import ReelForge
from ..toolchain import ToolchainError
from ..upload import UploadRequest
from .. import session as session_mod
from .. import upload as upload_mod
from ..uistate import (
    CODEC_CHOICES,
    FPS_CHOICES,
    RESOLUTION_CHOICES,
    TIER_LABELS,
    TIER_ORDER,
    TIER_TAGLINES,
    UIState,
    blur_strength_to_params,
    status_text,
)
from . import dnd
from .theme import APPEARANCE_MODE, COLOR_THEME, DECOY, DECOY_FONTS, SHARP

ctk.set_appearance_mode(APPEARANCE_MODE)
ctk.set_default_color_theme(COLOR_THEME)

APP_TITLE = "█ DECOY 120FPS PRO"
APP_VERSION = "v1.0.0"
APP_SUBTITLE = "root@reelforge:~# rife-engine --120fps --anti-compression"


# --------------------------------------------------------------------------- #
# tier card
# --------------------------------------------------------------------------- #


class TierCard(ctk.CTkFrame):
    """One selectable tier tile (sharp corners, neon red when active)."""

    def __init__(self, master, tier_id: str, on_select):
        super().__init__(
            master, corner_radius=SHARP, fg_color=DECOY["panel_2"],
            border_width=1, border_color=DECOY["line"],
        )
        self.tier_id = tier_id
        self.on_select = on_select
        self.title = ctk.CTkLabel(
            self, text=TIER_LABELS[tier_id], font=DECOY_FONTS["tier"],
            text_color=DECOY["text"], anchor="w",
        )
        self.title.pack(anchor="w", padx=8, pady=(5, 0))
        self.sub = ctk.CTkLabel(
            self, text=TIER_TAGLINES[tier_id], font=DECOY_FONTS["tier_sub"],
            text_color=DECOY["text_dim"], anchor="w",
        )
        self.sub.pack(anchor="w", padx=8, pady=(0, 5))
        for widget in (self, self.title, self.sub):
            widget.bind("<Button-1>", lambda _e: self.on_select(self.tier_id))
        self.set_active(False)

    def set_active(self, active: bool) -> None:
        self.configure(
            fg_color=DECOY["accent_lo"] if active else DECOY["panel_2"],
            border_color=DECOY["accent"] if active else DECOY["line"],
            border_width=2 if active else 1,
        )
        self.title.configure(
            text_color=DECOY["text"] if active else DECOY["text_dim"]
        )
        self.sub.configure(
            text_color=DECOY["accent_hi"] if active else DECOY["text_dim"]
        )


# --------------------------------------------------------------------------- #
# application window
# --------------------------------------------------------------------------- #


class DecoyApp(ctk.CTk):
    def __init__(self, engine: ReelForge):
        super().__init__()
        self.engine = engine
        self.dnd_enabled = dnd.enable_on(self)
        self.events: "queue.Queue[tuple]" = queue.Queue()
        self.worker: Optional[threading.Thread] = None
        self.login_worker: Optional[threading.Thread] = None
        self.source: Optional[Path] = None
        self.tier: str = "ultra120"
        self.tier_cards: Dict[str, TierCard] = {}
        self.current_engine_name = ""

        self.var_blur = ctk.BooleanVar(value=False)
        self.var_blur_strength = ctk.DoubleVar(value=40)
        self.var_sharpen = ctk.BooleanVar(value=True)
        self.var_fps = ctk.StringVar(value=FPS_CHOICES[1])
        self.var_resolution = ctk.StringVar(value=RESOLUTION_CHOICES[0])
        self.var_codec = ctk.StringVar(value=CODEC_CHOICES[0])
        self.var_outdir = ctk.StringVar(value="")
        self.var_tiktok = ctk.BooleanVar(value=False)
        self.var_description = ctk.StringVar(value="")

        self._build()
        self.after(90, self._pump)

    # ---------------------------------------------------------------- layout
    def _build(self) -> None:
        self.title(f"{APP_TITLE} — {APP_VERSION}")
        self.geometry("1060x700")
        self.minsize(1000, 640)
        self.configure(fg_color=DECOY["bg"])
        self.grid_columnconfigure(0, weight=11, uniform="col")
        self.grid_columnconfigure(1, weight=9, uniform="col")
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=1)

        self._build_header()

        left = ctk.CTkFrame(self, fg_color="transparent")
        left.grid(row=1, column=0, sticky="nsew", padx=(10, 4), pady=(0, 10))
        left.grid_columnconfigure(0, weight=1)
        left.grid_rowconfigure((0, 1, 2), weight=0)

        right = ctk.CTkFrame(self, fg_color="transparent")
        right.grid(row=1, column=1, sticky="nsew", padx=(4, 10), pady=(0, 10))
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(0, weight=0)
        right.grid_rowconfigure(1, weight=1)

        self._build_dropzone(left)
        self._build_tiers(left)
        self._build_controls(left)
        self._build_export(right)
        self._build_log(right)

    def _section(self, parent, row: int, title: str) -> ctk.CTkFrame:
        panel = ctk.CTkFrame(parent, fg_color=DECOY["panel"], corner_radius=SHARP,
                             border_width=1, border_color=DECOY["line"])
        panel.grid(row=row, column=0, sticky="ew", pady=(8, 0))
        panel.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(panel, text=f"» {title}", font=DECOY_FONTS["section"],
                     text_color=DECOY["accent_hi"]).grid(
            row=0, column=0, sticky="w", padx=10, pady=(6, 2))
        return panel

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, fg_color=DECOY["panel"], corner_radius=SHARP,
                              border_width=1, border_color=DECOY["accent_lo"],
                              height=54)
        header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=10, pady=(10, 0))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text=APP_TITLE, font=DECOY_FONTS["logo"],
                     text_color=DECOY["accent_hi"]).grid(
            row=0, column=0, sticky="w", padx=12, pady=(6, 0))
        ctk.CTkLabel(header, text=f"{APP_VERSION} · {APP_SUBTITLE}",
                     font=DECOY_FONTS["logo_sub"],
                     text_color=DECOY["text_dim"]).grid(
            row=1, column=0, sticky="w", padx=12, pady=(0, 6))
        self.badge = ctk.CTkLabel(
            header, text=f"● ffmpeg {self.engine.toolchain.version or '?'}",
            font=DECOY_FONTS["logo_sub"], text_color=DECOY["ok"])
        self.badge.grid(row=0, column=1, rowspan=2, sticky="e", padx=12)

    def _build_dropzone(self, parent) -> None:
        panel = self._section(parent, 0, "INPUT")
        zone = ctk.CTkFrame(panel, fg_color=DECOY["bg"], corner_radius=SHARP,
                            border_width=2, border_color=DECOY["accent_lo"],
                            height=88)
        zone.grid(row=1, column=0, sticky="ew", padx=10, pady=(2, 4))
        zone.grid_columnconfigure(0, weight=1)
        zone.grid_propagate(False)
        self.drop_title = ctk.CTkLabel(
            zone,
            text="DRAG & DROP VIDEO HERE" if self.dnd_enabled else "SELECT A VIDEO FILE",
            font=DECOY_FONTS["tier"], text_color=DECOY["text"])
        self.drop_title.grid(row=0, column=0, pady=(16, 0))
        self.select_btn = ctk.CTkButton(
            zone, text="[ SELECT VIDEO ]", width=150, height=26, corner_radius=SHARP,
            fg_color=DECOY["accent"], hover_color=DECOY["accent_hi"],
            font=DECOY_FONTS["small"], command=self.pick_file,
        )
        self.select_btn.grid(row=1, column=0, pady=(4, 0))
        for widget in (zone, self.drop_title):
            widget.bind("<Button-1>", lambda _e: self.pick_file())
        if self.dnd_enabled:
            dnd.register_drop_target(zone, self.on_drop)

        self.file_label = ctk.CTkLabel(
            panel, text="> heç bir fayl seçilməyib", font=DECOY_FONTS["small"],
            text_color=DECOY["text_dim"], anchor="w", wraplength=460, justify="left")
        self.file_label.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 8))

    def _build_tiers(self, parent) -> None:
        panel = self._section(parent, 1, "RENDER TIER")
        grid = ctk.CTkFrame(panel, fg_color="transparent")
        grid.grid(row=1, column=0, sticky="ew", padx=10, pady=(2, 10))
        grid.grid_columnconfigure((0, 1), weight=1, uniform="tier")
        for index, tier_id in enumerate(TIER_ORDER):
            card = TierCard(grid, tier_id, self.select_tier)
            card.grid(row=index // 2, column=index % 2, sticky="nsew", padx=2, pady=2)
            self.tier_cards[tier_id] = card
        self.select_tier(self.tier)

    def _build_controls(self, parent) -> None:
        panel = self._section(parent, 2, "CUSTOM CONTROLS")
        body = ctk.CTkFrame(panel, fg_color="transparent")
        body.grid(row=1, column=0, sticky="ew", padx=10, pady=(2, 8))
        body.grid_columnconfigure(1, weight=1)

        def row(index: int, label: str) -> ctk.CTkFrame:
            frame = ctk.CTkFrame(body, fg_color="transparent")
            frame.grid(row=index, column=0, sticky="ew", pady=2)
            frame.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(frame, text=label, font=DECOY_FONTS["section"],
                         text_color=DECOY["text_dim"], width=110,
                         anchor="w").grid(row=0, column=0, sticky="w")
            return frame

        # motion blur: switch + slider
        r = row(0, "MOTION BLUR")
        ctk.CTkSwitch(r, text="", variable=self.var_blur, onvalue=True, offvalue=False,
                      width=42, switch_width=38, switch_height=18,
                      progress_color=DECOY["accent"], fg_color=DECOY["line"],
                      command=self._blur_toggled).grid(row=0, column=1, sticky="w")
        self.blur_slider = ctk.CTkSlider(
            r, from_=0, to=100, number_of_steps=20, variable=self.var_blur_strength,
            command=self._blur_slider_moved, progress_color=DECOY["accent"],
            button_color=DECOY["accent_hi"], button_hover_color=DECOY["cyan"],
            fg_color=DECOY["line"], height=14)
        self.blur_slider.grid(row=0, column=2, sticky="ew", padx=(10, 8))
        self.blur_value = ctk.CTkLabel(r, text="40", font=DECOY_FONTS["small"],
                                       text_color=DECOY["accent_hi"], width=78,
                                       anchor="w")
        self.blur_value.grid(row=0, column=3, sticky="w")
        r.grid_columnconfigure(2, weight=1)

        # sharpening switch
        r = row(1, "SHARPENING")
        ctk.CTkSwitch(r, text="CAS filter", variable=self.var_sharpen, onvalue=True,
                      offvalue=False, font=DECOY_FONTS["small"],
                      text_color=DECOY["text_dim"], progress_color=DECOY["accent"],
                      fg_color=DECOY["line"]).grid(row=0, column=1, sticky="w")

        # fps selector
        r = row(2, "OUTPUT FPS")
        ctk.CTkSegmentedButton(
            r, values=list(FPS_CHOICES), variable=self.var_fps,
            selected_color=DECOY["accent"], selected_hover_color=DECOY["accent_hi"],
            unselected_color=DECOY["panel_2"], unselected_hover_color=DECOY["line"],
            fg_color=DECOY["line"], corner_radius=SHARP,
            font=DECOY_FONTS["small"], command=self._fps_changed,
        ).grid(row=0, column=1, sticky="e")

        # resolution selector
        r = row(3, "RESOLUTION")
        ctk.CTkOptionMenu(
            r, values=list(RESOLUTION_CHOICES), variable=self.var_resolution,
            fg_color=DECOY["panel_2"], button_color=DECOY["accent"],
            button_hover_color=DECOY["accent_hi"], corner_radius=SHARP,
            font=DECOY_FONTS["small"], dropdown_fg_color=DECOY["panel_2"],
            dropdown_hover_color=DECOY["accent_lo"],
        ).grid(row=0, column=1, sticky="e")

        # codec selector
        r = row(4, "CODEC")
        ctk.CTkSegmentedButton(
            r, values=list(CODEC_CHOICES), variable=self.var_codec,
            selected_color=DECOY["accent"], selected_hover_color=DECOY["accent_hi"],
            unselected_color=DECOY["panel_2"], unselected_hover_color=DECOY["line"],
            fg_color=DECOY["line"], corner_radius=SHARP,
            font=DECOY_FONTS["small"], command=lambda _v: None,
        ).grid(row=0, column=1, sticky="e")

        # output directory
        r = row(5, "OUTPUT")
        ctk.CTkEntry(r, textvariable=self.var_outdir, corner_radius=SHARP,
                     fg_color=DECOY["panel_2"], border_color=DECOY["line"],
                     font=DECOY_FONTS["small"],
                     placeholder_text="mənbə ilə eyni qovluq").grid(
            row=0, column=1, sticky="ew")
        ctk.CTkButton(r, text="BROWSE", width=68, height=24, corner_radius=SHARP,
                      fg_color=DECOY["panel_2"], hover_color=DECOY["accent_lo"],
                      font=DECOY_FONTS["small"], command=self.pick_outdir).grid(
            row=0, column=2, padx=(8, 0))

        # tiktok auto-upload switch
        r = row(6, "TIKTOK")
        self.tiktok_switch = ctk.CTkSwitch(
            r, text="AUTO-UPLOAD TO TIKTOK", variable=self.var_tiktok, onvalue=True,
            offvalue=False, font=DECOY_FONTS["small"],
            text_color=DECOY["text_dim"], progress_color=DECOY["accent"],
            fg_color=DECOY["line"], command=self._tiktok_toggled)
        self.tiktok_switch.grid(row=0, column=1, sticky="w")

        # tiktok account: one-click login + session status
        r = row(7, "HESAB")
        self.login_btn = ctk.CTkButton(
            r, text="[ LOGIN TO TIKTOK ]", width=142, height=24, corner_radius=SHARP,
            fg_color=DECOY["accent"], hover_color=DECOY["accent_hi"],
            text_color="#ffffff", font=DECOY_FONTS["small"],
            command=self.login_to_tiktok)
        self.login_btn.grid(row=0, column=1, sticky="w")
        self.session_label = ctk.CTkLabel(
            r, text="GİRİŞ YOXDUR", font=DECOY_FONTS["small"],
            text_color=DECOY["text_dim"], width=150, anchor="w")
        self.session_label.grid(row=0, column=2, sticky="w", padx=(8, 0))

        # tiktok description / hashtags
        r = row(8, "DESCRIPTION")
        self.description_entry = ctk.CTkEntry(
            r, textvariable=self.var_description, corner_radius=SHARP,
            fg_color=DECOY["panel_2"], border_color=DECOY["line"],
            font=DECOY_FONTS["small"],
            placeholder_text="#fyp #120fps  · açıqlama / hashtag")
        self.description_entry.grid(row=0, column=1, sticky="ew")

        self._blur_toggled()
        self.description_entry.configure(state="disabled")
        self._refresh_session_label()

    def _build_export(self, parent) -> None:
        panel = self._section(parent, 0, "EXPORT")
        self.progress = ctk.CTkProgressBar(
            panel, progress_color=DECOY["accent"], fg_color=DECOY["line"],
            corner_radius=SHARP, height=12)
        self.progress.set(0)
        self.progress.grid(row=1, column=0, sticky="ew", padx=10, pady=(6, 2))

        status_row = ctk.CTkFrame(panel, fg_color="transparent")
        status_row.grid(row=2, column=0, sticky="ew", padx=10)
        status_row.grid_columnconfigure(0, weight=1)
        self.status = ctk.CTkLabel(status_row, text=status_text("idle"),
                                   font=DECOY_FONTS["body"],
                                   text_color=DECOY["cyan"], anchor="w")
        self.status.grid(row=0, column=0, sticky="w")
        self.eta_label = ctk.CTkLabel(status_row, text="", font=DECOY_FONTS["small"],
                                      text_color=DECOY["text_dim"], anchor="e")
        self.eta_label.grid(row=0, column=1, sticky="e")

        self.export_btn = ctk.CTkButton(
            panel, text="▶  EXPORT / CONVERT", height=44, corner_radius=SHARP,
            fg_color=DECOY["accent"], hover_color=DECOY["accent_hi"],
            text_color="#ffffff", font=DECOY_FONTS["button"], command=self.start_export)
        self.export_btn.grid(row=3, column=0, sticky="ew", padx=10, pady=(8, 4))
        self.cancel_btn = ctk.CTkButton(
            panel, text="CANCEL", height=28, corner_radius=SHARP,
            fg_color=DECOY["panel_2"], hover_color=DECOY["error"],
            text_color=DECOY["text_dim"], font=DECOY_FONTS["small"],
            state="disabled", command=self.cancel_export)
        self.cancel_btn.grid(row=4, column=0, sticky="ew", padx=10, pady=(0, 10))

    def _build_log(self, parent) -> None:
        panel = self._section(parent, 1, "SYSTEM LOG")
        panel.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        self.log_box = ctk.CTkTextbox(
            panel, fg_color="#050203", text_color=DECOY["text_dim"],
            font=DECOY_FONTS["mono"], corner_radius=SHARP, wrap="word")
        self.log_box.grid(row=1, column=0, sticky="nsew", padx=10, pady=(2, 10))
        panel.grid_rowconfigure(1, weight=1)
        try:  # terminal colouring (guarded for older CustomTkinter)
            self.log_box.tag_config("dim", foreground=DECOY["text_dim"])
            self.log_box.tag_config("err", foreground=DECOY["error"])
            self.log_box.tag_config("ok", foreground=DECOY["ok"])
            self.log_box.tag_config("hl", foreground=DECOY["cyan"])
        except Exception:  # pragma: no cover - very old CTk without tags
            pass
        self.log(self.engine.describe())
        self.log(upload_mod.describe())

    # -------------------------------------------------------------- widgets
    def select_tier(self, tier_id: str) -> None:
        self.tier = tier_id
        for key, card in self.tier_cards.items():
            card.set_active(key == tier_id)
        self.log(f"Tier: {TIER_LABELS[tier_id]} — {TIER_TAGLINES[tier_id]}")

    def pick_file(self) -> None:
        picked = filedialog.askopenfilename(
            title="Select video",
            filetypes=[("Video", "*.mp4 *.mov *.mkv *.avi *.webm *.m4v *.mpg *.ts *.flv"),
                       ("All files", "*.*")],
        )
        if picked:
            self.on_drop([picked])

    def on_drop(self, paths: List[str]) -> None:
        files = ensure_video_files(paths)
        if not files:
            self.log("Dəstəklənən video tapılmadı.")
            return
        self.source = files[0]
        if len(files) > 1:
            self.log(f"{len(files)} fayl atıldı — bu UI tək fayl ilə işləyir: {self.source.name}")
        try:
            info = self.engine.probe(self.source)
            self.file_label.configure(
                text=f"> {self.source.name} · {info.resolution} · {info.fps:.2f}fps · "
                     f"{info.duration:.1f}s{' · HDR' if info.is_hdr else ''}")
            self.log(f"Mənbə: {info.summary()}")
        except Exception as exc:
            self.file_label.configure(text=f"> {self.source.name} (oxunmadı: {exc})")

    def pick_outdir(self) -> None:
        picked = filedialog.askdirectory(title="Output folder")
        if picked:
            self.var_outdir.set(picked)

    def _blur_toggled(self) -> None:
        enabled = bool(self.var_blur.get())
        if enabled:
            self.blur_slider.configure(state="normal")
        else:
            self.blur_slider.configure(state="disabled")
        self._blur_slider_moved(self.var_blur_strength.get())

    def _blur_slider_moved(self, value) -> None:
        strength = int(float(value))
        _mode, frames, _amount, _oversample = blur_strength_to_params(strength)
        if not self.var_blur.get():
            self.blur_value.configure(text="OFF")
        else:
            self.blur_value.configure(text=f"{strength} · {frames} frames")

    def _fps_changed(self, _value: str) -> None:
        self.log(f"Output FPS: {self.var_fps.get()}")

    def _tiktok_toggled(self) -> None:
        enabled = bool(self.var_tiktok.get())
        self.description_entry.configure(state="normal" if enabled else "disabled")
        if not enabled:
            self.log("TIKTOK: avtomatik yükləmə söndürüldü.")
            return
        self.log("TIKTOK: render bitəndə fayl olduğu kimi (keyfiyyət itkisiz) "
                 "headless yüklənəcək — brauzer açılmayacaq.")
        info = session_mod.session_info()
        if info["logged_in"]:
            who = f"@{info['username']}" if info["username"] else ""
            self.log(f"  sessiya: LOGGED IN ✓ {who}".rstrip())
        elif info["expired"]:
            self.log(f"  ! {session_mod.SESSION_EXPIRED} — LOGIN TO TIKTOK "
                     "düyməsini basın.")
        else:
            self.log("  ! giriş yoxdur — LOGIN TO TIKTOK düyməsini basın.")
        backend = upload_mod.choose_backend()
        if backend is None:
            self.log("  ! uploader backend yoxdur — quraşdırın: "
                     "pip install playwright && playwright install chromium")
        else:
            self.log(f"  backend: {backend}")

    # ------------------------------------------------------------ tiktok login
    def _refresh_session_label(self) -> None:
        info = session_mod.session_info()
        if info["logged_in"]:
            who = f"@{info['username']}" if info["username"] else ""
            self.session_label.configure(
                text=f"LOGGED IN ✓ {who}".strip(), text_color=DECOY["ok"])
        elif info["expired"]:
            self.session_label.configure(
                text="SESSİYA BİTİB", text_color=DECOY["warn"])
        else:
            self.session_label.configure(
                text="GİRİŞ YOXDUR", text_color=DECOY["text_dim"])

    def login_to_tiktok(self) -> None:
        """One-click Auto-Session Capture: internal Chromium -> save -> close."""
        if self.login_worker and self.login_worker.is_alive():
            return
        self.login_btn.configure(state="disabled")
        self.session_label.configure(text="Giriş gözlənilir…",
                                     text_color=DECOY["cyan"])
        self.log("TIKTOK: daxili brauzer pəncərəsi açılır — TikTok-a daxil olun. "
                 "Giriş bitən kimi sessiya avtomatik saxlanılıb pəncərə bağlanacaq.")
        self.login_worker = threading.Thread(target=self._login_work, daemon=True)
        self.login_worker.start()

    def _login_work(self) -> None:
        result = session_mod.capture_session(
            log_callback=lambda msg: self.events.put(("log", "TIKTOK · " + msg)))
        self.events.put(("login-done", result))

    # ---------------------------------------------------------------- state
    def collect_state(self) -> UIState:
        outdir = self.var_outdir.get().strip()
        return UIState(
            tier=self.tier,
            fps_choice=self.var_fps.get(),
            motion_blur_enabled=bool(self.var_blur.get()),
            motion_blur_strength=int(self.var_blur_strength.get()),
            sharpen_enabled=bool(self.var_sharpen.get()),
            resolution_choice=self.var_resolution.get(),
            codec_choice=self.var_codec.get(),
            output_dir=Path(outdir) if outdir else None,
            tiktok_enabled=bool(self.var_tiktok.get()),
            tiktok_description=self.var_description.get().strip(),
        )

    # ----------------------------------------------------------------- run
    def start_export(self) -> None:
        if self.source is None:
            self.status.configure(text="Əvvəlcə video seçin")
            return
        if self.worker and self.worker.is_alive():
            return
        state = self.collect_state()
        preset, options = state.build(self.engine.toolchain)
        for note in state.notes:
            self.log(note)
        if state.tiktok_enabled:
            self.log("TIKTOK: export bitəndə avtomatik yüklənəcək"
                     + (f" · açıqlama: {state.tiktok_description}"
                        if state.tiktok_description else " · açıqlama boş"))
            if not session_mod.is_logged_in():
                self.log("  ! xəbərdarlıq: sessiya yoxdur — yükləmə alınmayacaq. "
                         "LOGIN TO TIKTOK düyməsini basın.")

        self.engine.log_callback = self.log
        self.engine.progress_callback = self.on_progress
        self.export_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.progress.set(0)
        self.status.configure(text=f"Starting {TIER_LABELS[self.tier]}…")
        self.log(f"EXPORT: {self.source.name} · {preset.label} · "
                 f"fps={options.fps_override or 'preset'} · codec={options.codec}")
        self.worker = threading.Thread(
            target=self._work, args=(self.source, preset, options, state), daemon=True)
        self.worker.start()

    def _work(self, source: Path, preset, options,
              state: Optional[UIState] = None) -> None:
        """Worker thread: render, then auto-upload to TikTok when requested."""
        try:
            result = self.engine.run(source, preset, options)
            if result.ok and result.succeeded:
                out = result.succeeded[0]
                self.events.put(("log", f"Fayl: {out.path}"))
                self.events.put(("log", "Render Bitti ✓"))
                upload_req = state.upload_request(out.path) if state else None
                if upload_req is not None:
                    # switch ON -> render bitən kimi avtomatik headless yükləmə
                    self.events.put(("upload", "start"))
                    ok, _detail = self._upload_to_tiktok(upload_req)
                    self.events.put((
                        "done",
                        f"Done · {out.path.name} · TikTok {'✓' if ok else '✗ log-a bax'}",
                    ))
                else:
                    self.events.put(("done", f"Done · {out.path.name}"))
            else:
                if state is not None and state.tiktok_enabled:
                    self.events.put(("log",
                                     "TIKTOK: export uğursuz oldu — yükləmə atlandı."))
                self.events.put(("error", result.error or "naməlum xəta"))
        except Exception as exc:  # pragma: no cover - defensive
            self.events.put(("error", f"{type(exc).__name__}: {exc}"))

    def _upload_to_tiktok(self, request: UploadRequest) -> Tuple[bool, str]:
        """Post the rendered file as-is; every failure lands in the LOG box."""
        self.events.put((
            "log",
            "TikTok-a yüklənir… (headless — heç bir brauzer açılmır; fayl "
            "re-encode olunmur: 120FPS/kəskinlik/bitrate 100% qorunur)"))
        try:
            result = self.engine.upload(request)
        except Exception as exc:  # upload() özü atmır — bu sadəcə sığortadır
            detail = f"{type(exc).__name__}: {exc}"
            self.events.put(("log", "TIKTOK XƏTA: " + detail))
            self.events.put(("upload", "error"))
            return False, detail
        for line in result.logs:
            self.events.put(("log", "TIKTOK · " + line))
        if result.ok:
            self.events.put(("log", f"TikTok ✓ uğurla yükləndi → {result.url}"))
            self.events.put(("upload", "done"))
            return True, result.url
        detail = result.error or "naməlum xəta"
        self.events.put(("log", "TIKTOK XƏTA: " + detail))
        self.events.put(("upload", "error"))
        if session_mod.SESSION_EXPIRED in detail:
            self.events.put(("session-expired", None))
        return False, detail

    def cancel_export(self) -> None:
        self.engine.cancel()
        self.log("Ləğv edilir…")

    # ------------------------------------------------------------- plumbing
    def _append_log(self, text: str) -> None:
        """Terminal-style line: [HH:MM:SS] prefix + colour tag."""
        stamp = time.strftime("%H:%M:%S")
        lowered = text.lower()
        if "xəta" in lowered or "error" in lowered or text.strip().startswith("!"):
            tag = "err"
        elif "✓" in text or "hazır" in lowered:
            tag = "ok"
        elif text.startswith("TIKTOK") or "backend" in lowered:
            tag = "hl"
        else:
            tag = "dim"
        lines = text.splitlines() or [""]
        for line in lines:
            try:
                self.log_box.insert("end", f"[{stamp}] {line}\n", tag)
            except Exception:  # pragma: no cover - CTk without tag support
                self.log_box.insert("end", f"[{stamp}] {line}\n")
        self.log_box.see("end")

    def log(self, text: str) -> None:
        if threading.current_thread() is not threading.main_thread():
            self.events.put(("log", text))
            return
        self._append_log(text)

    def on_progress(self, info: ProgressInfo) -> None:
        self.events.put(("progress", info))

    def _pump(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "log":
                    self._append_log(payload)
                elif kind == "progress":
                    info: ProgressInfo = payload
                    if info.message.startswith("engine="):
                        self.current_engine_name = info.message.split("=", 1)[1]
                    self.progress.set(max(0.0, min(1.0, info.percent / 100.0)))
                    self.status.configure(
                        text=f"{status_text(info.phase, engine=self.current_engine_name)}"
                             f"  {info.percent:4.1f}%")
                    self.eta_label.configure(
                        text=f"ETA {info.eta_seconds:.0f}s" if info.eta_seconds else "")
                elif kind == "upload":
                    if payload == "start":
                        self.status.configure(text=status_text("upload"))
                    elif payload == "done":
                        self.status.configure(text="TikTok-a yükləndi ✓")
                    else:
                        self.status.configure(text="TikTok xətası — LOG-a baxın")
                elif kind == "login-done":
                    capture = payload
                    self.login_btn.configure(state="normal")
                    if capture.ok:
                        who = f"@{capture.username}" if capture.username else ""
                        self.session_label.configure(
                            text=f"LOGGED IN ✓ {who}".strip(), text_color=DECOY["ok"])
                        self.log("TIKTOK: sessiya təhlükəsiz faylda saxlanıldı — "
                                 "pəncərə avtomatik bağlandı. Artıq export bitəndə "
                                 "yükləmə headless gedəcək.")
                    else:
                        self.session_label.configure(
                            text="GİRİŞ ALINMADI", text_color=DECOY["error"])
                        self.log("TIKTOK XƏTA: " + str(capture.error))
                elif kind == "session-expired":
                    self.session_label.configure(
                        text="SESSİYA BİTİB", text_color=DECOY["warn"])
                elif kind == "done":
                    self.progress.set(1.0)
                    self.status.configure(text=str(payload))
                    self.eta_label.configure(text="")
                    self.export_btn.configure(state="normal")
                    self.cancel_btn.configure(state="disabled")
                elif kind == "error":
                    self.status.configure(text="XƏTA — log-a baxın")
                    self.log("XƏTA: " + str(payload))
                    self.export_btn.configure(state="normal")
                    self.cancel_btn.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(90, self._pump)


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #


def launch(ffmpeg: Optional[str] = None, ffprobe: Optional[str] = None) -> bool:
    """Password gate -> Decoy window.  Returns ``False`` if it cannot start."""
    try:
        from .lock import request_access

        if not request_access():
            print("Giriş alınmadı — proqram bağlandı.", file=sys.stderr)
            return False
    except Exception as exc:  # no display / broken Tk
        print(f"Giriş ekranı açıla bilmədi: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return False
    try:
        engine = ReelForge(ffmpeg, ffprobe)
    except ToolchainError as exc:
        print(f"XƏTA: {exc}", file=sys.stderr)
        return False
    try:
        app = DecoyApp(engine)
    except Exception as exc:  # no display / broken Tk
        print(f"GUI açıla bilmədi: {type(exc).__name__}: {exc}", file=sys.stderr)
        return False
    app.protocol("WM_DELETE_WINDOW", app.destroy)
    try:
        app.mainloop()
    except KeyboardInterrupt:  # pragma: no cover
        pass
    return True
