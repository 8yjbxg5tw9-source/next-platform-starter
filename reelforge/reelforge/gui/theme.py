"""Dark theme tokens for the GUI (single source of truth for colours)."""

from __future__ import annotations

from typing import Dict

#: Base palette — a slightly blue-tinted dark UI, TikTok-ish accent
PALETTE: Dict[str, str] = {
    "bg": "#0f1115",
    "surface": "#171a21",
    "surface_2": "#1e222b",
    "surface_3": "#262b36",
    "border": "#2f3542",
    "text": "#e7ebf2",
    "text_dim": "#9aa4b2",
    "accent": "#00e5c0",       # mint (TikTok secondary)
    "accent_2": "#fe2c55",     # red (TikTok primary)
    "warn": "#ffb020",
    "ok": "#3ddc84",
    "error": "#ff5c5c",
}

FONT_FAMILY = "Segoe UI" if __import__("os").name == "nt" else "Helvetica"
FONTS = {
    "title": (FONT_FAMILY, 22, "bold"),
    "h2": (FONT_FAMILY, 15, "bold"),
    "body": (FONT_FAMILY, 13),
    "small": (FONT_FAMILY, 11),
    "mono": ("Consolas" if __import__("os").name == "nt" else "Menlo", 12),
}

APPEARANCE_MODE = "dark"
COLOR_THEME = "dark-blue"


# --------------------------------------------------------------------------- #
# Decoy-style palette: near-black shell + neon purple accents, sharp corners
# --------------------------------------------------------------------------- #

DECOY: Dict[str, str] = {
    "bg": "#0d0d0d",           # window background
    "panel": "#121212",        # section panels
    "panel_2": "#171717",      # nested surfaces (tier cards, log)
    "line": "#262626",         # hairline borders
    "text": "#f2f2f2",
    "text_dim": "#8a8a8a",
    "accent": "#7b2cbf",       # neon purple
    "accent_hi": "#9d4edd",    # lighter purple (hover / gradient end)
    "accent_lo": "#5a189a",    # darker purple (gradient start / pressed)
    "cyan": "#4cc9f0",         # secondary neon
    "ok": "#3ddc84",
    "warn": "#ffb020",
    "error": "#ff4d6d",
}

#: sharp corners everywhere -> the "yığcam, kəskin kənarlı" look
SHARP = 0
SOFT = 4

DECOY_FONTS = {
    "logo": (FONT_FAMILY, 20, "bold"),
    "logo_sub": ("Consolas" if __import__("os").name == "nt" else "Menlo", 11),
    "section": (FONT_FAMILY, 11, "bold"),
    "tier": (FONT_FAMILY, 13, "bold"),
    "tier_sub": (FONT_FAMILY, 10),
    "body": (FONT_FAMILY, 12),
    "small": (FONT_FAMILY, 10),
    "button": (FONT_FAMILY, 14, "bold"),
    "mono": ("Consolas" if __import__("os").name == "nt" else "Menlo", 11),
}
