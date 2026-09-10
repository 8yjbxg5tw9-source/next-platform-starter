"""Render a pixel preview of the Decoy-style window without needing Tk.

The sandbox (and CI) usually has no display, so this script draws the exact
layout of ``reelforge/gui/decoy.py`` with Pillow, using the *same* colour
tokens from ``reelforge/gui/theme.py`` — the mockup cannot drift from the real
palette because it imports it.

    python scripts/render_mockup.py docs/ui_mockup.png docs/lock_mockup.png
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from reelforge.gui.theme import DECOY  # noqa: E402

SCALE = 2                # render at 2x for a crisp image
W, H = 1060, 700         # matches decoy.py geometry

FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Menlo.ttc",
    "C:/Windows/Fonts/consola.ttf",
)
BOLD_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Menlo.ttc",
    "C:/Windows/Fonts/consolab.ttf",
)


def _load(paths, size: int) -> ImageFont.FreeTypeFont:
    for path in paths:
        if Path(path).exists():
            return ImageFont.truetype(path, size * SCALE)
    return ImageFont.load_default()


class Canvas:
    """Small helper so both mockups share drawing primitives."""

    def __init__(self, width: int, height: int):
        self.img = Image.new("RGB", (width * SCALE, height * SCALE), DECOY["bg"])
        self.d = ImageDraw.Draw(self.img)
        self.logo = _load(BOLD_CANDIDATES, 19)
        self.bold = _load(BOLD_CANDIDATES, 12)
        self.small_bold = _load(BOLD_CANDIDATES, 10)
        self.body = _load(FONT_CANDIDATES, 12)
        self.small = _load(FONT_CANDIDATES, 10)
        self.tiny = _load(FONT_CANDIDATES, 9)

    def s(self, *vals: float) -> tuple:
        return tuple(int(v * SCALE) for v in vals)

    def rect(self, box, fill=None, outline=None, width=1):
        self.d.rectangle(self.s(*box), fill=fill, outline=outline,
                         width=width * SCALE if outline else 0)

    def text(self, xy, value, font, fill):
        self.d.text(self.s(*xy), value, font=font, fill=fill)

    def switch(self, x, y, on=True):
        self.rect((x, y, x + 36, y + 16), fill=DECOY["accent"] if on else DECOY["line"])
        knob = (x + 19, y - 1, x + 37, y + 17) if on else (x - 1, y - 1, x + 17, y + 17)
        self.d.ellipse(self.s(*knob), fill="#ffffff")

    def save(self, out_path: str) -> None:
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        self.img.save(out)
        print(f"mockup yazıldı: {out} ({self.img.size[0]}x{self.img.size[1]})")


def main_window(out_path: str) -> None:
    c = Canvas(W, H)

    def panel(x0, y0, x1, y1, title):
        c.rect((x0, y0, x1, y1), fill=DECOY["panel"], outline=DECOY["line"])
        c.text((x0 + 12, y0 + 8), f"» {title}", c.small_bold, DECOY["accent_hi"])

    # ---- header -----------------------------------------------------------
    c.rect((10, 10, 1050, 64), fill=DECOY["panel"], outline=DECOY["accent_lo"])
    c.text((22, 18), "█ DECOY 120FPS PRO", c.logo, DECOY["accent_hi"])
    c.text((22, 44), "v1.0.0 · root@reelforge:~# rife-engine --120fps --anti-compression",
           c.tiny, DECOY["text_dim"])
    c.text((928, 26), "● ffmpeg 7.0.2", c.small, DECOY["ok"])

    LX0, LX1 = 10, 572          # left column
    RX0, RX1 = 580, 1050        # right column

    # ---- INPUT ------------------------------------------------------------
    y = 72
    panel(LX0, y, LX1, y + 150, "INPUT")
    c.rect((LX0 + 12, y + 28, LX1 - 12, y + 116), fill=DECOY["bg"],
           outline=DECOY["accent_lo"], width=2)
    c.text((LX0 + 158, y + 44), "DRAG & DROP VIDEO HERE", c.bold, DECOY["text"])
    c.rect((LX0 + 200, y + 70, LX0 + 360, y + 96), fill=DECOY["accent"])
    c.text((LX0 + 216, y + 76), "[ SELECT VIDEO ]", c.small, "#ffffff")
    c.text((LX0 + 12, y + 124), "> clip.mp4 · 1080x1920 · 30.00fps · 12.4s",
           c.small, DECOY["text_dim"])

    # ---- RENDER TIER ------------------------------------------------------
    y = 230
    panel(LX0, y, LX1, y + 152, "RENDER TIER")
    tiers = [
        ("TURBO TIER", "Sürətli 60FPS rendering", False),
        ("SAFE MODE TIER", "Anti-Compression · GOP Bypass", False),
        ("STUDIO TIER", "Maksimum keyfiyyət · High Bitrate", False),
        ("ULTRA 120FPS TIER", "AI RIFE interpolyasiya · 120FPS", True),
    ]
    for index, (title, sub, active) in enumerate(tiers):
        col, row = index % 2, index // 2
        x0 = LX0 + 12 + col * 272
        y0 = y + 28 + row * 58
        c.rect((x0, y0, x0 + 264, y0 + 52),
               fill=DECOY["accent_lo"] if active else DECOY["panel_2"],
               outline=DECOY["accent"] if active else DECOY["line"],
               width=2 if active else 1)
        c.text((x0 + 10, y0 + 8), title, c.bold, DECOY["text"])
        c.text((x0 + 10, y0 + 28), sub, c.tiny,
               DECOY["accent_hi"] if active else DECOY["text_dim"])

    # ---- CUSTOM CONTROLS --------------------------------------------------
    y = 390
    panel(LX0, y, LX1, y + 300, "CUSTOM CONTROLS")
    rows = y + 28

    c.text((LX0 + 12, rows + 3), "MOTION BLUR", c.small_bold, DECOY["text_dim"])
    c.switch(LX0 + 130, rows + 2, on=True)
    c.rect((LX0 + 180, rows + 8, LX0 + 420, rows + 14), fill=DECOY["line"])
    c.rect((LX0 + 180, rows + 8, LX0 + 290, rows + 14), fill=DECOY["accent"])
    c.d.ellipse(c.s(LX0 + 282, rows + 2, LX0 + 298, rows + 20), fill=DECOY["accent_hi"])
    c.text((LX0 + 430, rows + 3), "40 · 3 frames", c.small, DECOY["accent_hi"])
    rows += 30

    c.text((LX0 + 12, rows + 3), "SHARPENING", c.small_bold, DECOY["text_dim"])
    c.switch(LX0 + 130, rows + 2, on=True)
    c.text((LX0 + 178, rows + 3), "CAS filter", c.small, DECOY["text_dim"])
    rows += 30

    def segmented(label, options, selected, x_right=None):
        nonlocal rows
        x_right = x_right or LX1 - 12
        c.text((LX0 + 12, rows + 3), label, c.small_bold, DECOY["text_dim"])
        total = 240
        width = total // len(options)
        x0 = x_right - total
        c.rect((x0, rows, x_right, rows + 24), fill=DECOY["line"])
        for i, option in enumerate(options):
            ox = x0 + i * width
            if option == selected:
                c.rect((ox + 1, rows + 1, ox + width - 1, rows + 23), fill=DECOY["accent"])
            c.text((ox + 8, rows + 5), option, c.small,
                   "#ffffff" if option == selected else DECOY["text_dim"])
        rows += 30

    segmented("OUTPUT FPS", ["60 FPS", "120 FPS", "SOURCE"], "120 FPS")
    segmented("CODEC", ["H.264", "NVENC", "HEVC"], "H.264")

    c.text((LX0 + 12, rows + 3), "RESOLUTION", c.small_bold, DECOY["text_dim"])
    c.rect((LX1 - 212, rows, LX1 - 12, rows + 24), fill=DECOY["panel_2"],
           outline=DECOY["line"])
    c.text((LX1 - 202, rows + 5), "1080x1920 (9:16)", c.small, DECOY["text"])
    c.d.polygon(c.s(LX1 - 34, rows + 9, LX1 - 22, rows + 9, LX1 - 28, rows + 17),
                fill=DECOY["accent_hi"])
    rows += 30

    c.text((LX0 + 12, rows + 3), "OUTPUT", c.small_bold, DECOY["text_dim"])
    c.rect((LX0 + 130, rows, LX0 + 452, rows + 24), fill=DECOY["panel_2"],
           outline=DECOY["line"])
    c.text((LX0 + 138, rows + 5), "mənbə ilə eyni qovluq", c.small, DECOY["text_dim"])
    c.rect((LX0 + 460, rows, LX1 - 12, rows + 24), fill=DECOY["panel_2"])
    c.text((LX0 + 472, rows + 5), "BROWSE", c.small, DECOY["text_dim"])
    rows += 30

    c.text((LX0 + 12, rows + 3), "TIKTOK", c.small_bold, DECOY["text_dim"])
    c.switch(LX0 + 130, rows + 2, on=True)
    c.text((LX0 + 178, rows + 3), "AUTO-UPLOAD TO TIKTOK", c.small, DECOY["text_dim"])
    rows += 30

    c.text((LX0 + 12, rows + 3), "HESAB", c.small_bold, DECOY["text_dim"])
    c.rect((LX0 + 130, rows, LX0 + 280, rows + 24), fill=DECOY["accent"])
    c.text((LX0 + 140, rows + 5), "[ LOGIN TO TIKTOK ]", c.small, "#ffffff")
    c.text((LX0 + 292, rows + 5), "LOGGED IN ✓ @reeluser", c.small, DECOY["ok"])
    rows += 30

    c.text((LX0 + 12, rows + 3), "DESCRIPTION", c.small_bold, DECOY["text_dim"])
    c.rect((LX0 + 130, rows, LX1 - 12, rows + 24), fill=DECOY["panel_2"],
           outline=DECOY["line"])
    c.text((LX0 + 138, rows + 5), "#fyp #120fps  · açıqlama / hashtag",
           c.small, DECOY["text_dim"])

    # ---- EXPORT -----------------------------------------------------------
    y = 72
    panel(RX0, y, RX1, y + 178, "EXPORT")
    c.rect((RX0 + 12, y + 28, RX1 - 12, y + 40), fill=DECOY["line"])
    c.rect((RX0 + 12, y + 28, RX0 + 300, y + 40), fill=DECOY["accent"])
    c.text((RX0 + 12, y + 48), "Encoding…  62.0%", c.body, DECOY["cyan"])
    c.text((RX1 - 70, y + 50), "ETA 12s", c.small, DECOY["text_dim"])
    c.rect((RX0 + 12, y + 76, RX1 - 12, y + 122), fill=DECOY["accent"])
    c.text((RX0 + 150, y + 90), "▶  EXPORT / CONVERT", c.bold, "#ffffff")
    c.rect((RX0 + 12, y + 130, RX1 - 12, y + 160), fill=DECOY["panel_2"])
    c.text((RX0 + 210, y + 138), "CANCEL", c.small, DECOY["text_dim"])

    # ---- SYSTEM LOG (terminal) --------------------------------------------
    y = 258
    panel(RX0, y, RX1, 690, "SYSTEM LOG")
    c.rect((RX0 + 12, y + 26, RX1 - 12, 678), fill="#050203")
    log_lines = [
        ("[12:04:02] ffmpeg 7.0.2 · minterpolate/tmix/cas OK", DECOY["text_dim"]),
        ("[12:04:02] TikTok sessiyası: LOGGED IN ✓ @reeluser", DECOY["ok"]),
        ("[12:04:05] Tier: ULTRA 120FPS TIER — AI RIFE · 120FPS", DECOY["text_dim"]),
        ("[12:04:31] engine=minterpolate", DECOY["cyan"]),
        ("[12:04:44] Fayl: clip__ultra120_120fps.mp4", DECOY["text_dim"]),
        ("[12:04:44] Render Bitti ✓", DECOY["ok"]),
        ("[12:04:45] TikTok-a yüklənir… (headless, re-encode yox)", DECOY["cyan"]),
        ("[12:04:52] TikTok ✓ uğurla yükləndi → tiktok.com/@reeluser", DECOY["ok"]),
        ("[12:04:52] Done · clip__ultra120_120fps.mp4 · TikTok ✓", DECOY["ok"]),
        ("[12:04:52] █", DECOY["accent_hi"]),
    ]
    for i, (line, color) in enumerate(log_lines):
        c.text((RX0 + 22, y + 34 + i * 20), line, c.small, color)

    c.save(out_path)


def lock_window(out_path: str) -> None:
    """The startup password gate (460x420 in lock.py)."""
    c = Canvas(460, 420)
    c.rect((16, 16, 444, 404), fill=DECOY["panel"], outline=DECOY["accent"], width=2)
    c.text((78, 34), "█▓▒░ REELFORGE SECURE TERMINAL ░▒▓█", c.small_bold,
           DECOY["accent_hi"])
    c.text((166, 54), "DECOY 120FPS PRO · v1.0.0", c.tiny, DECOY["text_dim"])
    banner = [
        " ██▀███  ▓█████ ▓█████  ▒█████   ███▄ ▄███▓",
        "▓██ ▒ ██▒▓█   ▀ ▓█   ▀ ▒██▒  ██▒▓██▒▀█▀ ██▒",
        "▓██ ░▄█ ▒▒███   ▒███   ▒██░  ██▒▓██    ▓██░",
    ]
    for i, line in enumerate(banner):
        c.text((64, 76 + i * 16), line, c.tiny, DECOY["accent"])
    c.text((128, 138), "> AUTHENTICATION REQUIRED_", c.body, DECOY["text"])
    c.rect((90, 168, 370, 202), fill=DECOY["bg"], outline=DECOY["line"], width=2)
    c.text((100, 178), "●●●●●●●●", c.body, DECOY["text"])
    c.rect((140, 218, 320, 254), fill=DECOY["accent"])
    c.text((176, 228), "[  UNLOCK  ]", c.bold, "#ffffff")
    c.text((168, 268), "Yanlış şifrə! 2 cəhd qalıb.", c.small, DECOY["error"])
    c.text((184, 292), "3 cəhd · Esc = çıxış", c.small, DECOY["text_dim"])
    c.save(out_path)


if __name__ == "__main__":
    main_window(sys.argv[1] if len(sys.argv) > 1 else "docs/ui_mockup.png")
    lock_window(sys.argv[2] if len(sys.argv) > 2 else "docs/lock_mockup.png")
