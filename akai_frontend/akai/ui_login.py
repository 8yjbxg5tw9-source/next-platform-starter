"""Login window: credentials, HWID display, license check.

Login runs in a worker thread (``net.AuthClient`` has an 8 s timeout) and
results are marshalled back with ``after()`` so the window never freezes and
a dead server can never hang the process.
"""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox
from typing import Callable, Dict, Optional

import customtkinter as ctk

from .config import ICON_PATH, WHATSAPP_TEXT, log
from .hwid import collect_identifiers, compute_hwid
from .net import OFFLINE_MESSAGE, AuthClient, LicenseError

ACCENT = "#e5322d"


def _apply_icon(window) -> None:
    if not ICON_PATH.exists():
        return
    try:
        window.iconbitmap(str(ICON_PATH))  # Windows title bar + taskbar
    except tk.TclError:
        try:  # Linux/X11 fallback
            photo = tk.PhotoImage(file=str(ICON_PATH))
            window.tk.call("wm", "iconphoto", window._w, photo)
        except tk.TclError:
            pass


def _safe_hwid() -> str:
    try:
        return compute_hwid()
    except Exception:  # noqa: BLE001 - never block login on HWID read
        log().exception("HWID oxuna bilmədi")
        return compute_hwid({"fallback": "akai-device"})


class LoginWindow(ctk.CTk):
    """Shown at startup; ``on_success(session)`` opens the main panel."""

    def __init__(self, on_success: Callable[[Dict], None]):
        super().__init__()
        self.on_success = on_success

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")
        self.title("Akai")
        self.geometry("520x640")
        self.minsize(520, 640)
        _apply_icon(self)

        self.session: Optional[Dict] = None
        self._hwid = _safe_hwid()
        self._busy = False
        self._build()

    # -- layout ---------------------------------------------------------------
    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        card = ctk.CTkFrame(self, corner_radius=14)
        card.grid(row=0, column=0, sticky="nsew", padx=28, pady=24)
        card.grid_columnconfigure(0, weight=1)

        title = ctk.CTkLabel(card, text="Akai",
                             font=ctk.CTkFont("Segoe UI Semibold", 34),
                             text_color=ACCENT)
        title.grid(row=0, column=0, pady=(30, 4))
        ctk.CTkLabel(card, text="AI Video Enhancer",
                     font=ctk.CTkFont("Segoe UI", 14),
                     text_color="#9aa0a6").grid(row=1, column=0)

        self.username = ctk.CTkEntry(card, placeholder_text="İstifadəçi adı",
                                     height=44)
        self.username.grid(row=2, column=0, sticky="ew", padx=36, pady=(26, 12))
        self.password = ctk.CTkEntry(card, placeholder_text="Şifrə",
                                     height=44, show="•")
        self.password.grid(row=3, column=0, sticky="ew", padx=36, pady=(0, 18))
        self.password.bind("<Return>", lambda _e: self._start_login())

        self.login_btn = ctk.CTkButton(card, text="Giriş", height=46,
                                       fg_color=ACCENT, hover_color="#b8221e",
                                       font=ctk.CTkFont("Segoe UI Semibold", 16),
                                       command=self._start_login)
        self.login_btn.grid(row=4, column=0, sticky="ew", padx=36)

        # --- HWID block ------------------------------------------------------
        hwid_box = ctk.CTkFrame(card, fg_color="#15171c", corner_radius=10)
        hwid_box.grid(row=5, column=0, sticky="ew", padx=36, pady=(24, 6))
        hwid_box.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(hwid_box, text="Sizin HWID (abunə üçün göndərin):",
                     anchor="w", font=ctk.CTkFont("Segoe UI", 12),
                     text_color="#9aa0a6").grid(row=0, column=0, sticky="ew",
                                                padx=12, pady=(10, 2))
        ids = collect_identifiers()
        detail = " · ".join(f"{k}: {v[:14]}" for k, v in sorted(ids.items()))
        self.hwid_entry = ctk.CTkEntry(hwid_box, font=ctk.CTkFont("Consolas", 15),
                                       text_color=ACCENT)
        self.hwid_entry.insert(0, self._hwid)
        self.hwid_entry.configure(state="disabled")
        self.hwid_entry.grid(row=1, column=0, sticky="ew", padx=12)
        ctk.CTkLabel(hwid_box, text=detail or "Cihaz identifikatoru",
                     anchor="w", font=ctk.CTkFont("Segoe UI", 11),
                     text_color="#6b7178").grid(row=2, column=0, sticky="ew",
                                                padx=12, pady=(2, 10))
        ctk.CTkButton(card, text="HWID-ni kopyala", height=30,
                      fg_color="#2b2f36", hover_color="#3a3f47",
                      command=self._copy_hwid).grid(row=6, column=0,
                                                    sticky="ew", padx=36,
                                                    pady=(6, 0))

        self.status = ctk.CTkLabel(card, text="", font=ctk.CTkFont("Segoe UI", 12),
                                   text_color=ACCENT)
        self.status.grid(row=7, column=0, pady=(16, 0))

        ctk.CTkLabel(card, text=WHATSAPP_TEXT, wraplength=400, justify="center",
                     font=ctk.CTkFont("Segoe UI", 12.5),
                     text_color="#c7ccd4").grid(row=8, column=0,
                                                pady=(20, 26))

    # -- actions ----------------------------------------------------------------
    def _copy_hwid(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self._hwid)
        self._set_status("HWID kopyalandı.")

    def _set_status(self, message: str) -> None:
        self.after(0, lambda: self.status.configure(text=message))

    def _start_login(self) -> None:
        if self._busy:
            return
        username = self.username.get().strip()
        password = self.password.get()
        if not username or not password:
            self._set_status("İstifadəçi adı və şifrəni daxil edin.")
            return
        self._busy = True
        self.after(0, lambda: self.login_btn.configure(
            state="disabled", text="Yoxlanılır…"))
        threading.Thread(target=self._login_worker,
                         args=(username, password), daemon=True).start()

    def _login_worker(self, username: str, password: str) -> None:
        try:
            payload = AuthClient().login(username, password, self._hwid)
        except LicenseError as exc:
            log().warning("login refused: %s", exc)
            self._set_status(str(exc))
            self.after(0, self._reset_button)
            return
        except Exception:  # noqa: BLE001 - defensive net layer
            log().exception("login crashed")
            self._set_status(OFFLINE_MESSAGE)
            self.after(0, self._reset_button)
            return
        self.session = payload
        self._set_status(f"Xoş gəlmisiniz, {payload.get('username', username)}!")
        self.after(120, self._open_main)

    def _reset_button(self) -> None:
        self._busy = False
        self.login_btn.configure(state="normal", text="Giriş")

    def _open_main(self) -> None:
        session = self.session or {}
        self.destroy()
        try:
            self.on_success(session)
        except Exception:  # noqa: BLE001 - never crash on panel handoff
            log().exception("main panel açılmadı")
            messagebox.showerror("Akai", OFFLINE_MESSAGE)
