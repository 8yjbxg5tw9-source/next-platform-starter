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
