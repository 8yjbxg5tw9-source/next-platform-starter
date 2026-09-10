"""Renders static PNG mockups of the two Akai screens (docs/)."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "docs"
OUT.mkdir(exist_ok=True)

BG = (27, 30, 34)
CARD = (35, 39, 44)
DARK = (21, 23, 28)
RED = (229, 50, 45)
GREY = (154, 160, 166)
TXT = (231, 235, 240)
BTN = (43, 47, 54)


def font(size: int, bold: bool = False):
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    for base in ("/usr/share/fonts/truetype/dejavu/",
                 "/usr/share/fonts/dejavu/"):
        p = Path(base) / name
        if p.exists():
            return ImageFont.truetype(str(p), size)
    return ImageFont.load_default()


def rrect(d, box, r, fill=None, outline=None, w=1):
    d.rounded_rectangle(box, radius=r, fill=fill, outline=outline, width=w)


def text(d, xy, s, f, fill=TXT):
    d.text(xy, s, font=f, fill=fill)


# ---------------------------------------------------------------- login ----
def login_screen() -> Image.Image:
    img = Image.new("RGB", (520, 640), BG)
    d = ImageDraw.Draw(img)
    rrect(d, (28, 24, 492, 616), 14, fill=CARD)
    f_title = font(34, True)
    w = d.textlength("Akai", font=f_title)
    text(d, (260 - w / 2, 54), "Akai", f_title, RED)
    f_sub = font(14)
    w = d.textlength("AI Video Enhancer", font=f_sub)
    text(d, (260 - w / 2, 96), "AI Video Enhancer", f_sub, GREY)

    rrect(d, (64, 148, 456, 192), 8, fill=DARK)
    text(d, (78, 160), "İstifadəçi adı", font(13), GREY)
    rrect(d, (64, 204, 456, 248), 8, fill=DARK)
    text(d, (78, 216), "Şifrə", font(13), GREY)

    rrect(d, (64, 266, 456, 312), 8, fill=RED)
    f_btn = font(16, True)
    w = d.textlength("Giriş", font=f_btn)
    text(d, (260 - w / 2, 278), "Giriş", f_btn, (255, 255, 255))

    rrect(d, (64, 336, 456, 428), 10, fill=DARK)
    text(d, (76, 346), "Sizin HWID (abunə üçün göndərin):", font(12), GREY)
    text(d, (76, 372), "AKAI-98F2-41A7-B800", font(16), RED)
    text(d, (76, 400), "board: 98XX-A7 · cpu: BFEBFBFF", font(11),
         (107, 113, 120))
    rrect(d, (64, 434, 456, 464), 8, fill=BTN)
    f_s = font(12)
    w = d.textlength("HWID-ni kopyala", font=f_s)
    text(d, (260 - w / 2, 442), "HWID-ni kopyala", f_s, TXT)

    f_wa = font(13)
    line = "Əgər abunə olmaq istəyirsinizsə, +994 10 310 09 29"
    line2 = "nömrəsinə WhatsApp-dan yazın."
    text(d, (260 - d.textlength(line, font=f_wa) / 2, 540), line, f_wa,
         (199, 204, 212))
    text(d, (260 - d.textlength(line2, font=f_wa) / 2, 562), line2, f_wa,
         (199, 204, 212))
    return img


# ---------------------------------------------------------------- main -----
def main_screen() -> Image.Image:
    img = Image.new("RGB", (1060, 720), BG)
    d = ImageDraw.Draw(img)

    # left panel
    rrect(d, (14, 14, 640, 706), 12, fill=DARK)
    text(d, (28, 26), "Video seçilməyib — sürüşdürün və ya Seçin",
         font(13), TXT)
    rrect(d, (470, 22, 560, 52), 8, fill=BTN)
    text(d, (486, 30), "Fayl seç", font(12), TXT)
    rrect(d, (568, 22, 628, 52), 8, fill=BTN)
    text(d, (578, 30), "Önizləmə", font(11), TXT)
    rrect(d, (26, 62, 628, 560), 8, fill=(14, 16, 20))
    f_p = font(14)
    text(d, (300, 300), "Preview", f_p, GREY)
    rrect(d, (26, 576, 628, 592), 8, fill=BTN)
    rrect(d, (26, 576, 330, 592), 8, fill=RED)
    text(d, (28, 602), "Render gedir… 45%", font(12), GREY)
    rrect(d, (26, 630, 320, 674), 8, fill=RED)
    f_b = font(15, True)
    text(d, (140, 642), "RENDER", f_b, (255, 255, 255))
    rrect(d, (332, 630, 628, 674), 8, fill=BTN)
    w = d.textlength("Dayandır", font=f_b)
    text(d, (480 - w / 2, 642), "Dayandır", f_b, TXT)

    # right settings
    rrect(d, (654, 14, 1046, 706), 12, fill=CARD)
    text(d, (670, 26), "Parametrlər", font(14, True), TXT)
    y = 58
    text(d, (670, y), "PROTEUS — Bərpa modeli", font(13, True), RED)
    y += 26
    rrect(d, (670, y, 850, y + 30), 8, fill=RED)
    text(d, (700, y + 7), "Auto", font(12, True), (255, 255, 255))
    rrect(d, (850, y, 1030, y + 30), 8, fill=BTN)
    text(d, (890, y + 7), "Fine-Tune", font(12), TXT)
    y += 44
    for label in ("Revert Compression", "Recover Details", "Sharpen",
                  "Reduce Noise", "Dehaloing"):
        text(d, (670, y), f"{label}: 40", font(12), GREY)
        rrect(d, (670, y + 20, 1030, y + 28), 4, fill=BTN)
        rrect(d, (670, y + 20, 810, y + 28), 4, fill=RED)
        y += 44
    text(d, (670, y), "○ Motion Deblur", font(12), TXT)
    y += 34
    text(d, (670, y), "UPSCALE — Hədəf ölçü", font(13, True), RED)
    y += 26
    x = 670
    for val in ("1080p", "4K", "8K", "CUSTOM"):
        w = d.textlength(val, font=font(12)) + 24
        fill = RED if val == "4K" else BTN
        rrect(d, (x, y, x + w, y + 30), 8, fill=fill)
        text(d, (x + 12, y + 7), val, font(12), (255, 255, 255)
             if val == "4K" else TXT)
        x += w + 6
    y += 44
    text(d, (670, y), "RENDER — Kadr & Kodlayıcı", font(13, True), RED)
    y += 26
    x = 670
    for val in ("Off", "60 fps", "120 fps"):
        w = d.textlength(val, font=font(12)) + 24
        rrect(d, (x, y, x + w, y + 30), 8, fill=BTN)
        text(d, (x + 12, y + 7), val, font(12), TXT)
        x += w + 6
    y += 40
    x = 670
    for val in ("H.264", "H.265", "ProRes"):
        w = d.textlength(val, font=font(12)) + 24
        fill = RED if val == "H.264" else BTN
        rrect(d, (x, y, x + w, y + 30), 8, fill=fill)
        text(d, (x + 12, y + 7), val, font(12), (255, 255, 255)
             if val == "H.264" else TXT)
        x += w + 6
    y += 44
    text(d, (670, y), "GPU / VRAM", font(13, True), RED)
    y += 26
    text(d, (670, y), "Cihaz: NVIDIA GeForce RTX 3060", font(12), TXT)
    text(d, (670, y + 20), "Növ: CUDA · 12288 MB VRAM", font(12), GREY)
    return img


if __name__ == "__main__":
    login_screen().save(OUT / "ekran_login.png")
    main_screen().save(OUT / "ekran_main.png")
    print("written:", sorted(p.name for p in OUT.glob("*.png")))
