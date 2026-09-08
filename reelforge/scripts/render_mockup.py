"""Render a pixel preview of the Decoy-style window without needing Tk.

The sandbox (and CI) usually has no display, so this script draws the exact
layout of ``reelforge/gui/decoy.py`` with Pillow, using the *same* colour
tokens from ``reelforge/gui/theme.py`` — the mockup cannot drift from the real
palette because it imports it.

    python scripts/render_mockup.py docs/ui_mockup.png
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from reelforge.gui.theme import DECOY  # noqa: E402

SCALE = 2                # render at 2x for a crisp image
W, H = 520, 860

FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
)
BOLD_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
)


def _load(paths, size: int) -> ImageFont.FreeTypeFont:
    for path in paths:
        if Path(path).exists():
            return ImageFont.truetype(path, size * SCALE)
    return ImageFont.load_default()


def main(out_path: str = "docs/ui_mockup.png") -> None:
    img = Image.new("RGB", (W * SCALE, H * SCALE), DECOY["bg"])
    d = ImageDraw.Draw(img)

    logo = _load(BOLD_CANDIDATES, 20)
    bold = _load(BOLD_CANDIDATES, 13)
    small_bold = _load(BOLD_CANDIDATES, 10)
    body = _load(FONT_CANDIDATES, 12)
    small = _load(FONT_CANDIDATES, 10)

    def s(*vals: float) -> tuple:
        return tuple(int(v * SCALE) for v in vals)

    def rect(box, fill=None, outline=None, width=1):
        d.rectangle(s(*box), fill=fill, outline=outline,
                    width=width * SCALE if outline else 0)

    def text(xy, value, font, fill):
        d.text(s(*xy), value, font=font, fill=fill)

    def panel(y0: int, height: int, title: str) -> int:
        rect((10, y0, 510, y0 + height), fill=DECOY["panel"], outline=DECOY["line"])
        text((22, y0 + 9), title, small_bold, DECOY["accent_hi"])
        return y0 + height

    # ---- header -----------------------------------------------------------
    rect((10, 10, 510, 72), fill=DECOY["panel"], outline=DECOY["line"])
    text((24, 22), "DECOY 120FPS PRO", logo, DECOY["accent_hi"])
    text((24, 50), "v1.0.0 · RIFE AI ENGINE · FFMPEG", small, DECOY["text_dim"])
    text((404, 26), "ffmpeg 7.0.2", small, DECOY["cyan"])

    # ---- input ------------------------------------------------------------
    y = 80
    panel(y, 196, "INPUT")
    rect((22, y + 28, 498, y + 140), fill=DECOY["bg"], outline=DECOY["accent"], width=2)
    text((158, y + 52), "DRAG & DROP VIDEO HERE", bold, DECOY["text"])
    rect((190, y + 84, 330, y + 114), fill=DECOY["accent"])
    text((212, y + 92), "SELECT VIDEO", body, "#ffffff")
    text((22, y + 150), "clip.mp4 · 1080x1920 · 30.00fps · 12.4s", small, DECOY["text_dim"])

    # ---- tiers ------------------------------------------------------------
    y = 284
    panel(y, 150, "RENDER TIER")
    tiers = [
        ("TURBO TIER", "Sürətli 60FPS rendering", False),
        ("SAFE MODE TIER", "TikTok Anti-Compression · GOP Bypass", False),
        ("STUDIO TIER", "Maksimum keyfiyyət · High Bitrate", False),
        ("ULTRA 120FPS TIER", "AI RIFE interpolyasiya · 120FPS", True),
    ]
    for index, (title, sub, active) in enumerate(tiers):
        col, row = index % 2, index // 2
        x0 = 22 + col * 242
        y0 = y + 28 + row * 58
        rect((x0, y0, x0 + 234, y0 + 52),
             fill=DECOY["accent_lo"] if active else DECOY["panel_2"],
             outline=DECOY["accent"] if active else DECOY["line"],
             width=2 if active else 1)
        text((x0 + 10, y0 + 8), title, bold, DECOY["text"])
        text((x0 + 10, y0 + 28), sub, small,
             DECOY["accent_hi"] if active else DECOY["text_dim"])

    # ---- custom controls --------------------------------------------------
    y = 442
    panel(y, 216, "CUSTOM CONTROLS")
    rows = y + 28

    # motion blur: switch + slider + value
    text((22, rows + 4), "MOTION BLUR", small_bold, DECOY["text_dim"])
    rect((140, rows + 4, 176, rows + 20), fill=DECOY["accent"])
    d.ellipse(s(160, rows + 2, 178, rows + 20), fill="#ffffff")
    rect((190, rows + 10, 380, rows + 16), fill=DECOY["line"])
    rect((190, rows + 10, 300, rows + 16), fill=DECOY["accent"])
    d.ellipse(s(292, rows + 4, 308, rows + 22), fill=DECOY["accent_hi"])
    text((392, rows + 4), "60 · 4 frames", small, DECOY["accent_hi"])
    rows += 32

    # sharpening
    text((22, rows + 4), "SHARPENING", small_bold, DECOY["text_dim"])
    rect((140, rows + 4, 176, rows + 20), fill=DECOY["accent"])
    d.ellipse(s(160, rows + 2, 178, rows + 20), fill="#ffffff")
    text((186, rows + 4), "CAS filter", small, DECOY["text_dim"])
    rows += 32

    def segmented(label: str, options: list, selected: str) -> None:
        nonlocal rows
        text((22, rows + 4), label, small_bold, DECOY["text_dim"])
        width = 340 // len(options)
        x0 = 500 - 340
        rect((x0, rows, 500, rows + 26), fill=DECOY["line"])
        for i, option in enumerate(options):
            ox = x0 + i * width
            if option == selected:
                rect((ox + 1, rows + 1, ox + width - 1, rows + 25), fill=DECOY["accent"])
            text((ox + 12, rows + 6), option, small,
                 "#ffffff" if option == selected else DECOY["text_dim"])
        rows += 32

    segmented("OUTPUT FPS", ["60 FPS", "120 FPS", "SOURCE"], "120 FPS")
    segmented("CODEC", ["H.264", "NVENC", "HEVC"], "H.264")

    # resolution dropdown
    text((22, rows + 4), "RESOLUTION", small_bold, DECOY["text_dim"])
    rect((300, rows, 500, rows + 26), fill=DECOY["panel_2"], outline=DECOY["line"])
    text((312, rows + 6), "1080x1920 (9:16)", small, DECOY["text"])
    d.polygon(s(478, rows + 10, 490, rows + 10, 484, rows + 18), fill=DECOY["accent_hi"])
    rows += 32

    # output dir
    text((22, rows + 4), "OUTPUT", small_bold, DECOY["text_dim"])
    rect((140, rows, 404, rows + 26), fill=DECOY["panel_2"], outline=DECOY["line"])
    text((150, rows + 6), "/Users/you/Movies/exports", small, DECOY["text_dim"])
    rect((412, rows, 500, rows + 26), fill=DECOY["panel_2"])
    text((428, rows + 6), "BROWSE", small, DECOY["text_dim"])

    # ---- export -----------------------------------------------------------
    y = 666
    panel(y, 132, "EXPORT")
    rect((22, y + 28, 498, y + 40), fill=DECOY["line"])
    rect((22, y + 28, 320, y + 40), fill=DECOY["accent"])
    text((22, y + 46), "Encoding…  62.0%", body, DECOY["cyan"])
    text((430, y + 48), "ETA 12s", small, DECOY["text_dim"])
    rect((22, y + 70, 396, y + 116), fill=DECOY["accent"])
    text((118, y + 84), "EXPORT / CONVERT", bold, "#ffffff")
    rect((404, y + 70, 498, y + 116), fill=DECOY["panel_2"])
    text((424, y + 86), "CANCEL", small, DECOY["text_dim"])

    # ---- log --------------------------------------------------------------
    y = 806
    panel(y, 44, "LOG")
    text((22, y + 24), "İnterpolyasiya mühərriki: minterpolate — ffmpeg hazırdır",
         small, DECOY["text_dim"])

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    print(f"mockup yazıldı: {out} ({img.size[0]}x{img.size[1]})")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "docs/ui_mockup.png")
