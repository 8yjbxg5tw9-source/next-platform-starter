# ReelForge — TikTok / Reels / Shorts üçün 60-120FPS Studio

**Decoy 60FPS** funksionallığının Python reimplementasiyası + iki əlavə:
**120FPS Interpolation** (RIFE AI və ya FFmpeg `minterpolate`) və **HQ Transcoding**
(CRF 17-20, sabit GOP, bt709, `+faststart`).

* CustomTkinter ilə müasir **dark mode** GUI, **drag-and-drop** dəstəyi
* Bütün emal `subprocess` vasitəsilə **FFmpeg** əmrləri ilə
* **TikTok anti-compression** məntiqi: `h264 High` / `HEVC`, `yuv420p`, `bt709`, CRF 17-20, AAC 320k
* **Safe Mode GOP**: `-g 60 -keyint_min 60 -sc_threshold 0` (TikTok-un 30FPS-ə endirməsinin qarşısı)
* **Ultra 120FPS**: RIFE (rife-ncnn-vulkan / VapourSynth) → yoxdursa `minterpolate`
* **Cinematic Motion Blur**: 2× oversample + `tmix` / `tblend` (+ `mblur` varsa)
* Hər iş üçün **QA yoxlanışı** və **JSON hesabat**: FPS, kodek, profil, piksel formatı, keyframe intervalları
* GUI, CLI və Python API — eyni backend

---

## 1. Quraşdırma

```bash
# 1) FFmpeg lazımdır (yeganə məcburi asılılıq)
#    Windows: winget install Gyan.FFmpeg
#    macOS:   brew install ffmpeg
#    Debian:  sudo apt install ffmpeg

# 2) Python paketi
cd reelforge
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt                       # customtkinter + tkinterdnd2
# və ya: pip install -e ".[gui,dev]"

# 3) Yoxlama
python -m reelforge.cli --diagnostics
```

`--diagnostics` belə bir çıxış verir:

```
ffmpeg 7.0.2 @ /usr/local/bin/ffmpeg
ffprobe: /usr/local/bin/ffprobe
filters: 486 | encoders: 187
libx264=True libx265=True minterpolate=True tmix=True cas=True mblur=False zscale=True
İnterpolyasiya mühərrikləri:
  - rife-ncnn-vulkan: yox (rife-ncnn-vulkan tapılmadı (PATH / REELFORGE_RIFE))
  - vapoursynth-rife: yox (vspipe tapılmadı)
  - minterpolate: OK (ffmpeg minterpolate hazırdır)
```

> **Qeyd:** `ffprobe` yoxdursa proqram `ffmpeg -i` bannerini oxuyaraq eyni məlumatı
> alır (fallback). `imageio-ffmpeg` pip paketi quraşdırılıbsa, onun statik
> `ffmpeg` binary-si avtomatik tapılır.

---

## 2. İstifadə

### GUI

```bash
python -m reelforge            # Decoy stilində tünd UI (default)
python -m reelforge --advanced # 3 sütunlu "studio" UI (bütün CLI parametrləri)
```

Decoy-stil pəncərə (520×860, `#0d0d0d` fon, `#7b2cbf` neon bənövşəyi, kəskin kənarlar):

```
┌────────────────────────────────────────────┐
│ DECOY 120FPS PRO      v1.0.0 · RIFE AI     │ header (+ ffmpeg versiyası)
├────────────────────────────────────────────┤
│        DRAG & DROP VIDEO HERE              │ input zone
│            [ SELECT VIDEO ]                │ (tkinterdnd2 varsa sürüklə-burax)
│ clip.mp4 · 1080x1920 · 30.00fps · 12.4s    │
├────────────────────────────────────────────┤
│ RENDER TIER                                │
│ [ TURBO TIER    ] [ SAFE MODE TIER ]       │ 2×2 tier kartları
│ [ STUDIO TIER   ] [ ULTRA 120FPS   ]       │ (seçilən = bənövşəyi çərçivə)
├────────────────────────────────────────────┤
│ CUSTOM CONTROLS                            │
│ MOTION BLUR  [switch] ────o──── 60·4 frames│
│ SHARPENING   [switch] CAS filter           │
│ OUTPUT FPS   [ 60 FPS | 120 FPS | SOURCE ] │
│ RESOLUTION   [ SOURCE / 1080x1920 / ... ]  │
│ CODEC        [ H.264 | NVENC | HEVC ]      │
│ OUTPUT       [ /path ] [ BROWSE ]          │
├────────────────────────────────────────────┤
│ [################-----------] 62%          │ export zone
│ Encoding…                       ETA 12s    │
│ [      EXPORT / CONVERT      ] [ CANCEL ]  │
├────────────────────────────────────────────┤
│ LOG (kompakt konsol)                       │
└────────────────────────────────────────────┘
```

Status mətni fazalara görə dəyişir: `Ready` → `Analyzing…` → `Extracting frames…`
→ `Applying RIFE 120FPS…` → `Encoding…` → `Done`.

* `tkinterdnd2` yoxdursa drag-and-drop söndürülür, proqram işləməyə davam edir.
* Pəncərədə heç bir emal məntiqi yoxdur: widget-lar `UIState`-ə yığılır, qərarı
  `presets/filters/encode` verir (bütün düymə→FFmpeg bayraq əlaqəsi test olunub).

### CLI

```bash
# TikTok Safe Mode (60FPS, CRF 17, sabit GOP)
python -m reelforge.cli clip.mp4 -p safe

# Ultra 120FPS — həm 60FPS, həm 120FPS variantı yazılır
python -m reelforge.cli clip.mp4 -p ultra120 -o out/

# Tək fayl (yalnız 120FPS), HEVC master, 1080x1920 cover-crop
python -m reelforge.cli clip.mp4 -p ultra120 --codec hevc --no-dual \
    --fit cover --width 1080 --height 1920 -o out/

# Cinematic motion blur (60FPS, 180° shutter)
python -m reelforge.cli clip.mp4 -p motionblur

# Toplu emal + əmrləri əvvəlcədən görmək
python -m reelforge.cli *.mov -p safe --dry-run

# JSON hesabat
python -m reelforge.cli clip.mp4 -p safe --json
```

Əsas CLI bayraqları: `-p/--preset`, `-o/--out`, `--codec h264|hevc`, `--crf`,
`--interp auto|rife|minterpolate|none`, `--fps`, `--fit keep|cover|contain|stretch`,
`--width/--height`, `--interp-quality fast|balanced|quality`, `--audio-bitrate`,
`--audio-rate`, `--threads`, `--hwaccel`, `--no-dual`, `--no-verify`, `--keep-temp`,
`--dry-run`, `--json`, `--rife`, `--rife-model`.

### Python API

```python
from reelforge import ReelForge, Presets, JobOptions

app = ReelForge()                                  # ffmpeg/ffprobe tapır
info = app.probe("clip.mp4")
print(info.summary())                              # 1080x1920 @ 30.000fps | h264 (yuv420p) | aac 48000Hz

result = app.run(
    "clip.mp4",
    Presets.ULTRA_120,
    JobOptions(output_dir="out", codec="hevc", crf_override=18),
)
for out in result.succeeded:
    print(out.path, out.target.fps, out.verify.keyframe_gaps)
```

---

## 3. Rejimler (presets)

| Preset (tier) | FPS | Kodek | CRF | x264 | GOP | İnterpolyasiya | Blur |
|---|---|---|---|---|---|---|---|
| **Turbo Tier** | 60 | H.264 High | 21 | `veryfast` | 60 (1s) | yoxdur | yoxdur |
| **Safe Mode Tier** | 60 | H.264 High | 17 | `slow` | 60 (1s), `-sc_threshold 0` | yoxdur | CAS 0.5 |
| **Studio Tier** | 60 | H.264 High | 14 | `slow` | 60 (1s) | yoxdur | CAS 0.6 |
| **Ultra 120FPS Tier** | 60 + 120 | H.264 High | 18 / 17 | `slow` | 1s | RIFE → `minterpolate` | CAS 0.6 / 0.8 |
| _Fast Conversion_ | 60 | H.264 High | 20 | `fast` | 60 (1s) | yoxdur | yoxdur |
| _Cinematic Motion Blur_ | 60 | H.264 High | 18 | `slow` | 1s | `minterpolate` 2× | `tmix` 2 kadr |
| _Archive Master_ | mənbə FPS | H.264 High | 12 | `veryslow` | 2s | yoxdur | yoxdur |

İtalikdəki son üç preset CLI-dən əlçatandır (`--list-presets`); pəncərədəki tier
seçimi ilk dördünü göstərir.

**Studio Tier** əlavə olaraq VBV tavanı yazır: `-maxrate 50000k -bufsize 100000k`
(yüksək bitrate, amma platformanın rədd etməyəcəyi qədər məhdud).

**NVENC (GPU):** `hevc_nvenc -preset p6 -tune hq -rc vbr -cq <CRF> -b:v 0
-no-scenecut 1 -forced-idr 1 -tag:v hvc1`. GPU tapılmırsa proqram avtomatik
H.264-ə keçir və bunu log-a yazır.

**Custom controls** birbaşa FFmpeg-ə belə təsir edir:

| Widget | Nəticə |
|---|---|
| Motion blur OFF | zəncirdə blur filtri yoxdur |
| Motion blur 1-25 / 26-50 / 51-75 / 76-100 | `tmix=frames=2 / 3 / 4 / 5` + 2× oversample |
| Sharpening ON / OFF | `cas=strength=0.7` / filtsiz |
| Output FPS 60 / 120 / SOURCE | `-r 60`, `-r 120` (`-g` da uyğunlaşır) / mənbə FPS |
| Resolution 1080x1920 | `scale=…increase,crop=1080:1920,setsar=1` |
| Codec H.264 / NVENC / HEVC | `libx264` / `hevc_nvenc` / `libx265 -tag:v hvc1` |

---

## 4. Avtomatik əməliyyat zənciri (pipeline)

```
fayl(lar) → probe (ffprobe / ffmpeg -i)
          → mühərrik seçimi (RIFE varsa RIFE, yoxsa minterpolate)
          → [interpolyasiya]  (PNG ardıcıllığı + RIFE  və ya  -vf minterpolate)
          → [-vf zənciri]  scale/crop/pad → (HDR tonemap) → interp → blur → fps → CAS → yuv420p → bt709
          → encode: CRF + sabit GOP + bt709 + AAC + faststart
          → QA: FPS / kodek / profil / pix_fmt / keyframe intervalları
          → JSON hesabat + log faylı
```

Çıxış adlandırması: `<mənbə>__<preset>_<fps>fps.mp4`
Hesabat: `<mənbə>__reelforge_<tarix>.json` · Log: `<mənbə>__reelforge_<tarix>.log`

---

## 5. RIFE AI quraşdırma (opsional)

RIFE tapılmasa proqram avtomatik olaraq `minterpolate`-a keçir və bunu log-a yazır.

**Variant A — rife-ncnn-vulkan (tövsiyə olunur, Vulkan GPU lazımdır)**

```bash
# https://github.com/nihui/rife-ncnn-vulkan/releases — arxivdə modellər də var
unzip rife-ncnn-vulkan-*.zip -d ~/rife
export PATH="$HOME/rife:$PATH"          # modellər ~/rife/models/ içində olmalıdır
python -m reelforge.cli --diagnostics   # "RIFE AI hazırdır" yazmalıdır
```

Proqram `-i frames_in -o frames_out -n <hədəf kadr sayı> -m <model>` şəklində çağırır;
`-n` **misil yox, mütləq kadr sayıdır** (30fps → 120fps üçün `kadr_sayı × 4`).

**Variant B — VapourSynth + VapourSynth-RIFE-ncnn-Vulkan**

`vspipe` PATH-da olarsa istifadə olunur. Proqram `.vpy` skriptini özü yaradır
(`rife.RIFE(..., fps_num, fps_den)`, ehtiyat variant `vsmlrt.RIFE`), çıxışı FFV1
(itkisiz) ara fayla yazır — beləliklə **yeganə itkili mərhələ son CRF encode olur**.

---

## 6. Testlər

```bash
pip install pytest
pytest                       # 157 test
```

`tests/test_uistate.py` pəncərənin hər widget-ını (tier, motion blur slayder,
sharpening, FPS, resolution, codec) birbaşa FFmpeg əmr bayraqları ilə yoxlayır —
GUI-ni açmadan "düymə → əmr" əlaqəsi test olunur.

Testlərin bir hissəsi **real ffmpeg** ilə işləyir: klip yaradır, `safe`,
`ultra120`, `motionblur`, `fast` presetlərini həqiqətən encode edir və nəticəni
yenidən oxuyub yoxlayır — FPS, kadr sayı, 1 saniyəlik GOP, `yuv420p`, `bt709` və
hətta **qonşu kadrların piksel fərqi** (interpolyasiya həqiqətən yeni kadr yaradır,
yoxsa sadəcə dublikat edir?). ffmpeg tapılmayan mühitdə bu testlər `skip` olunur.

```
156 passed, 1 skipped in 64.82s
```

> 1 `skip` = GUI modulunun import testi: bu mühitdə `tkinter` (python3-tk) yoxdur.

---

## 7. Fayl strukturu

```
reelforge/
├── README.md · ARCHITECTURE.md · FFMPEG_REFERENCE.md
├── pyproject.toml · requirements.txt
├── reelforge/
│   ├── __init__.py        public API (ReelForge, Presets, JobOptions, ...)
│   ├── __main__.py        python -m reelforge  (GUI, fallback CLI)
│   ├── cli.py             argparse CLI
│   ├── models.py          dataclass/enumerasiyalar (MediaInfo, RenderTarget, JobOptions ...)
│   ├── presets.py         7 preset (4 UI tier + 3 CLI) + build_targets()
│   ├── toolchain.py       ffmpeg/ffprobe tapılması, capability, FFmpegRunner (progress/cancel)
│   ├── probe.py           ffprobe JSON + `ffmpeg -i` fallback, keyframe/frame analizi
│   ├── filters.py         -vf zəncirinin qurulması
│   ├── encode.py          encode əmrinin qurulması (CRF/GOP/bt709/audio)
│   ├── interpolate.py     RIFE (ncnn + VapourSynth) və minterpolate mühərrikləri
│   ├── pipeline.py        Pipeline + ReelForge fasadı, QA verify
│   ├── uistate.py         UI widget → preset/JobOptions xəritəsi (saf Python, testli)
│   └── gui/               decoy.py (Decoy-stil UI) · app.py (studio UI) · theme.py · dnd.py
└── tests/                 unit + real-ffmpeg e2e testləri
```

Detallı modul təsviri üçün [`ARCHITECTURE.md`](ARCHITECTURE.md),
dəqiq FFmpeg əmrləri üçün [`FFMPEG_REFERENCE.md`](FFMPEG_REFERENCE.md).
