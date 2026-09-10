"""Generates ``assets/icon.ico`` (multi-size) for the exe title bar/taskbar.

Run once:  python assets/make_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

SIZES = (16, 24, 32, 48, 64, 128, 256)
ACCENT = (229, 50, 45)
DARK = (16, 17, 20)


def make_frame(size: int) -> Image.Image:
    scale = 8
    big = size * scale
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    margin = big // 16
    draw.rounded_rectangle(
        [margin, margin, big - margin, big - margin],
        radius=big // 5, fill=DARK, outline=ACCENT, width=max(2, big // 40))
    # stylised "A": two strokes meeting at the top + crossbar
    left = big * 0.30
    right = big * 0.70
    top = big * 0.26
    bottom = big * 0.76
    thickness = big // 11
    draw.line([(big / 2, top), (left, bottom)], fill=ACCENT, width=thickness)
    draw.line([(big / 2, top), (right, bottom)], fill=ACCENT, width=thickness)
    bar_y = big * 0.60
    draw.line([(left + (big / 2 - left) * 0.42, bar_y),
               (right - (right - big / 2) * 0.42, bar_y)],
              fill=ACCENT, width=max(2, thickness // 2))
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    out = Path(__file__).with_name("icon.ico")
    frames = [make_frame(s) for s in SIZES]
    frames[-1].save(out, format="ICO",
                    sizes=[(s, s) for s in SIZES],
                    append_images=frames[:-1])
    print(f"written: {out}")


if __name__ == "__main__":
    main()
