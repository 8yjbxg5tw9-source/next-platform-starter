"""Dark theme tokens for the GUI (single source of truth for colours).

The Decoy window uses a **red-toned "hacker terminal"** look: near-black
backgrounds with a red tint, neon-red accents, sharp corners and monospace
fonts everywhere — like a root shell that renders videos.
"""

from __future__ import annotations

import os
import sys
from typing import Dict

#: Base palette — used by the advanced studio window (``gui/app.py``)
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

FONT_FAMILY = "Segoe UI" if os.name == "nt" else "Helvetica"

#: monospace family for the hacker look (per platform)
if os.name == "nt":
    MONO_FAMILY = "Consolas"
elif sys.platform == "darwin":
    MONO_FAMILY = "Menlo"
else:
    MONO_FAMILY = "DejaVu Sans Mono"

FONTS = {
    "title": (FONT_FAMILY, 22, "bold"),
    "h2": (FONT_FAMILY, 15, "bold"),
    "body": (FONT_FAMILY, 13),
    "small": (FONT_FAMILY, 11),
    "mono": (MONO_FAMILY, 12),
}

APPEARANCE_MODE = "dark"
COLOR_THEME = "dark-blue"


# --------------------------------------------------------------------------- #
# Decoy palette: red-toned hacker terminal — near-black + neon red, sharp
# --------------------------------------------------------------------------- #

DECOY: Dict[str, str] = {
    "bg": "#0a0406",           # window background (near-black, red tint)
    "panel": "#140709",        # section panels (dark oxblood)
    "panel_2": "#1d0b0e",      # nested surfaces (tier cards, inputs)
    "line": "#3d1219",         # hairline borders (dark red)
    "text": "#ffe9ea",         # off-white text
    "text_dim": "#b08a8e",     # muted rose
    "accent": "#e50914",       # neon red (primary action)
    "accent_hi": "#ff2f3a",    # bright red (hover / active text)
    "accent_lo": "#7c0710",    # deep red (pressed / selected tile)
    "cyan": "#ff6b74",         # status highlight (kept key name; now coral-red)
    "ok": "#3ddc84",           # green = success (contrast pop)
    "warn": "#ffb020",
    "error": "#ff1f3d",
}

#: sharp corners everywhere -> the "yığcam, kəskin kənarlı" look
SHARP = 0
SOFT = 4

#: everything monospace -> terminal / hacker aesthetic
DECOY_FONTS = {
    "logo": (MONO_FAMILY, 19, "bold"),
    "logo_sub": (MONO_FAMILY, 10),
    "section": (MONO_FAMILY, 11, "bold"),
    "tier": (MONO_FAMILY, 12, "bold"),
    "tier_sub": (MONO_FAMILY, 9),
    "body": (MONO_FAMILY, 12),
    "small": (MONO_FAMILY, 10),
    "button": (MONO_FAMILY, 14, "bold"),
    "mono": (MONO_FAMILY, 10),
}
