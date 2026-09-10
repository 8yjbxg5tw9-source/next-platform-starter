# Akai — Müştəri Tətbiqi (Front-end)

CustomTkinter əsaslı, tünd dizaynlı video bərpa/upscale tətbiqi. Girişdə
HWID ilə lisenziya yoxlanılır; render istifadəçinin öz GPU/CPU-sunda gedir.

## Qovluq strukturu

```
akai_frontend/
├── main.py               # giriş nöqtəsi
├── akai.spec             # PyInstaller konfiqurasiyası
├── requirements.txt
├── akai/
│   ├── config.py         # yollar, app_debug.log, crash guard
│   ├── hwid.py           # AKAI-XXXX-XXXX-XXXX cihaz kodu
│   ├── net.py            # lisenziya serveri klienti (urllib)
│   ├── ffmpeg_tools.py   # ffmpeg axtarışı + probe
│   ├── engine.py         # cihaz aşkarı, VRAM tiling, render thread
│   ├── ui_login.py       # giriş ekranı
│   └── ui_main.py        # əsas panel
├── assets/icon.ico       # pəncərə/taskbar ikonu
└── models/               # ONNX modelləri (ayrıca paylanır, git-də deyil)
```

## İşə salmaq (kod kimi)

```bash
pip install -r requirements.txt
python main.py
```

Server ünvanı: exe-nin yanında `server.txt` faylı (məs. `https://lic.sizin-domen.com`)
və ya `AKAI_SERVER` env dəyişəni. Fayl yoxdursa `http://127.0.0.1:8000`.

## EXE yığmaq (Windows)

```bash
pip install -r requirements.txt pyinstaller
pyinstaller akai.spec --noconfirm
# nəticə: dist/Akai.exe
```

* `akai.spec` ikonu (`assets/icon.ico`), `assets/` qovluğunu və
  customtkinter tema fayllarını paketə daxil edir; konsol pəncərəsi açılmır.
* ffmpeg-i istifadəçiyə ayrıca quraşdırtmamaq üçün Windows ffmpeg.exe-ni
  spec-dəki `datas` sətrini açaraq paketə qatın, yaxud `imageio-ffmpeg`
  pip paketini `requirements.txt`-də saxlayın (avtomatik tapılır).
* AI modellərini (onnxruntime + torch) paketə qatırsınızsa `excludes`
  siyahısından çıxarın və `models/*.onnx` fayllarını `datas`-a əlavə edin.

## Abunə axını (admin üçün)

1. Müştəri ödənişdən sonra tətbiqin giriş ekranındakı **HWID**-ni
   (`AKAI-XXXX-XXXX-XXXX` formatında) WhatsApp ilə göndərir.
2. Admin serverdə: `python tools/add_user.py --username ad --password pin --hwid AKAI-... --days 365`
3. Müştəri istifadəçi adı/şifrə ilə daxil olur; şifrə serverə yalnız
   SHA-256 kimi gedir, HWID serverdə digest kimi saxlanılır.
4. Eyni abunəlik başqa cihazdan sınanarsa: *"Bu abunəlik başqa cihazda aktivdir!"*

## Davamlılıq

* Bütün kritik yollar try/except-dədir; gözlənilməz xəta `app_debug.log`-a
  düşür, pəncərə bağlanmır.
* Server əlçatmaz olduqda: *"Sistem xətası: Lisenziya doğrulana bilmədi"*.
* Render ayrıca thread-dədir — GUI donmur; **Dayandır** ffmpeg-i bağlayır və
  `torch.cuda.empty_cache()` ilə VRAM-i azad edir.
* GPU yoxdursa CPU fallback işləyir və istifadəçiyə xəbərdarlıq göstərilir.
* Bütün yollar `pathlib` + UTF-8 — Az/Tr/Ru simvollu fayl adları təhlükəsizdir.

## Testlər

```bash
python -m pytest tests/ -q
```

Süni intellekt yox — klassik filtr zənciri (lanczos/hqdn3d/cas/unsharp/
minterpolate) bütün sistemlərdə işləyir; ONNX modelləri əlavə olunanda AI
yolu tiling ilə avtomatik aktivləşir.
