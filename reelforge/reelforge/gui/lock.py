"""Startup lock screen — hacker-style password gate (red terminal look).

``request_access()`` opens a small modal window **before** the main Decoy
window exists: masked password entry, 3 attempts, Enter to submit, Esc to
quit.  All password handling lives in :mod:`reelforge.access` (SHA-256
digest, no plaintext); this module is only the UI shell.
"""

from __future__ import annotations

import sys

try:
    import customtkinter as ctk
except ImportError as exc:  # pragma: no cover - user-facing guidance
    raise ImportError(
        "CustomTkinter quraşdırılmayıb:  pip install customtkinter  "
        "(Linux-da əlavə olaraq python3-tk lazımdır)"
    ) from exc

from ..access import MAX_ATTEMPTS, attempts_message, verify_password
from .theme import APPEARANCE_MODE, COLOR_THEME, DECOY, DECOY_FONTS, SHARP

ctk.set_appearance_mode(APPEARANCE_MODE)
ctk.set_default_color_theme(COLOR_THEME)

BANNER = r"""
 ██▀███  ▓█████ ▓█████  ▒█████   ███▄ ▄███▓
▓██ ▒ ██▒▓█   ▀ ▓█   ▀ ▒██▒  ██▒▓██▒▀█▀ ██▒
▓██ ░▄█ ▒▒███   ▒███   ▒██░  ██▒▓██    ▓██░
"""


class LockScreen(ctk.CTk):
    """Modal gate: correct password -> authorized, otherwise it stays shut."""

    def __init__(self) -> None:
        super().__init__()
        self.authorized = False
        self.attempts = MAX_ATTEMPTS

        self.title("REELFORGE — GİRİŞ")
        self.geometry("460x420")
        self.resizable(False, False)
        self.configure(fg_color=DECOY["bg"])
        self.grid_columnconfigure(0, weight=1)

        frame = ctk.CTkFrame(self, fg_color=DECOY["panel"], corner_radius=SHARP,
                             border_width=2, border_color=DECOY["accent"])
        frame.grid(row=0, column=0, sticky="nsew", padx=16, pady=16)
        frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(frame, text="█▓▒░ REELFORGE SECURE TERMINAL ░▒▓█",
                     font=DECOY_FONTS["section"],
                     text_color=DECOY["accent_hi"]).grid(
            row=0, column=0, pady=(18, 2))
        ctk.CTkLabel(frame, text="DECOY 120FPS PRO · v1.0.0",
                     font=DECOY_FONTS["small"],
                     text_color=DECOY["text_dim"]).grid(row=1, column=0)

        ctk.CTkLabel(frame, text=BANNER, font=(DECOY_FONTS["mono"][0], 9),
                     text_color=DECOY["accent"], justify="left").grid(
            row=2, column=0, pady=(6, 0))

        ctk.CTkLabel(frame, text="> AUTHENTICATION REQUIRED_",
                     font=DECOY_FONTS["body"],
                     text_color=DECOY["text"]).grid(row=3, column=0, pady=(8, 6))

        self.entry = ctk.CTkEntry(
            frame, width=280, height=34, show="●", corner_radius=SHARP,
            fg_color=DECOY["bg"], border_color=DECOY["line"], border_width=2,
            text_color=DECOY["text"], font=DECOY_FONTS["body"],
            placeholder_text="şifrəni daxil edin")
        self.entry.grid(row=4, column=0, pady=(2, 8))
        self.entry.bind("<Return>", lambda _e: self._submit())

        self.button = ctk.CTkButton(
            frame, text="[  UNLOCK  ]", width=180, height=36, corner_radius=SHARP,
            fg_color=DECOY["accent"], hover_color=DECOY["accent_hi"],
            text_color="#ffffff", font=DECOY_FONTS["button"], command=self._submit)
        self.button.grid(row=5, column=0, pady=(0, 6))

        self.feedback = ctk.CTkLabel(frame, text="", font=DECOY_FONTS["small"],
                                     text_color=DECOY["error"])
        self.feedback.grid(row=6, column=0, pady=(0, 4))

        ctk.CTkLabel(frame, text=f"{MAX_ATTEMPTS} cəhd · Esc = çıxış",
                     font=DECOY_FONTS["small"],
                     text_color=DECOY["text_dim"]).grid(row=7, column=0, pady=(0, 14))

        self.bind("<Escape>", lambda _e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.after(80, lambda: self.entry.focus_set())

    # ------------------------------------------------------------------ logic
    def _submit(self) -> None:
        candidate = self.entry.get()
        if verify_password(candidate):
            self.authorized = True
            self.destroy()
            return
        self.attempts -= 1
        self.entry.delete(0, "end")
        if self.attempts <= 0:
            self.feedback.configure(text=attempts_message(0))
            self.after(1200, self.destroy)   # qısa mesaj, sonra bağlanır
            self.entry.configure(state="disabled")
            self.button.configure(state="disabled")
            return
        self.feedback.configure(text=attempts_message(self.attempts))


def request_access() -> bool:
    """Show the gate; return ``True`` only after the correct password."""
    try:
        screen = LockScreen()
    except Exception as exc:  # no display / broken Tk
        print(f"Giriş ekranı açıla bilmədi: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return False
    screen.mainloop()
    return screen.authorized
