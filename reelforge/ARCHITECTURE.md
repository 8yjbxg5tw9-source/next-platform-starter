# ReelForge — Arxitektura

Bu sənəd proqramın **addım-addım strukturunu** izah edir: hansı modul nəyə cavabdehdir,
məlumat axını necə gedir və yeni funksiya harada əlavə olunur.

---

## 0. Qatlar (layers)

```
┌─────────────────────────────────────────────────────────────┐
│  UI qatı                                                    │
│  gui/decoy.py (Decoy-stil) · gui/app.py (studio) · cli.py   │
│  → yalnız göstərir və hadisə göndərir, məntiq saxlamır      │
│  → widget dəyərləri uistate.UIState-ə yığılır               │
├─────────────────────────────────────────────────────────────┤
│  Orkestrasiya qatı                                          │
│  pipeline.py  →  Pipeline.run()  /  ReelForge (fasad)       │
│  → probe → plan → execute → verify → report                 │
├─────────────────────────────────────────────────────────────┤
│  Qərar qatı (saf funksiyalar, subprocess YOX)               │
│  presets.py · filters.py · encode.py · interpolate.py       │
│  → preset → RenderTarget → FilterGraph → argv               │
├─────────────────────────────────────────────────────────────┤
│  Sistem qatı                                                │
│  toolchain.py (FFmpegRunner, capability) · probe.py         │
│  → yeganə subprocess icra edən yer                          │
└─────────────────────────────────────────────────────────────┘
```

**Qayda:** `models.py` və qərar qatı heç nə icra etmir. Buna görə də bütün
FFmpeg əmr sətirləri `--dry-run` ilə göstərilə, unit testlərlə yoxlanıla və
terminala kopyalana bilir. `gui/` heç vaxt `pipeline`-dən başqa modula toxunmur.

---

## 1. Modul-modul struktur

### `models.py` — məlumat tipi
| Tip | Nədir |
|---|---|
| `Codec`, `FitMode`, `SharpenMode`, `MotionBlurMode`, `InterpolationEngineKind`, `ColorTag` | `str`-əsaslı enumerasiyalar (CLI/GUI birbaşa istifadə edir) |
| `StreamInfo` / `MediaInfo` | probe nəticəsi; `.fps`, `.resolution`, `.is_hdr`, `.has_audio` |
| `RenderTarget` | **bir çıxış faylı** üçün bütün parametrlər: fps, crf, gop, preset, sharpen, blur, oversample |
| `JobOptions` | istifadəçinin seçimi (output dir, fit, audio, threads, override-lar) |
| `ProgressInfo` | progress bar üçün: percent, step, fps, speed, eta |
| `VerifyReport`, `RenderOutput`, `JobResult` | QA nəticəsi və hesabat |

### `presets.py` — rejimlər
`Preset.specs` = `TargetSpec` korteji. `Preset.build_targets(opts, info)` bunları
`RenderTarget`-a çevirir və bu qaydaları tətbiq edir:

* `dual_output=False` → yalnız ən yüksək FPS variantı
* mənbə artıq hədəf FPS-dədirsə → interpolyasiya söndürülür (artıq keyfiyyət itkisi verməmək üçün)
* HEVC seçilərsə → `profile=main`, `level` FPS-ə görə
* `>60fps` → H.264 `level 5.1`
* `opts.crf_override / codec / fps_override / interpolation_override` preset-dən üstündür

### `toolchain.py` — sistem
* `find_executable()` → PATH → `/usr/local/bin`, Homebrew, Windows qovluqları → `REELFORGE_FFMPEG` → `imageio-ffmpeg` wheel
* `Toolchain` → versiya, `filters`, `encoders`; feature flag-lər (`supports_fps_mode`, `supports_cas`, `supports_mblur`, `supports_zscale`, `supports_hevc`)
* `FFmpegRunner.run()` → `-progress pipe:1` axınını oxuyur, `ProgressInfo` yaradır,
  stderr-i log faylına + GUI-yə ötürür, `threading.Event` ilə **ləğv** edir (SIGTERM → SIGKILL)

### `probe.py` — media analizi
* `probe()` → `ffprobe -v error -print_format json -show_format -show_streams`
* `ffprobe` yoxdursa → `ffmpeg -hide_banner -i` bannerinin regex ilə oxunması (`parse_ffmpeg_banner`)
* `keyframe_gaps()` → `select='eq(pict_type\,I)',showinfo` ilə keyframe zamanları (GOP QA üçün)
* `count_frames()` → `-f null` ilə dəqiq kadr sayı

### `filters.py` — `-vf` zənciri
Hər addım ayrı saf funksiyadır və **sabit ardıcıllıqla** birləşir:

```
geometry → (HDR tonemap) → interpolation → motion blur → fps lock → sharpen → format → setparams
```

Bu ardıcıllıq keyfiyyət üçün vacibdir: interpolyasiya miqyas dəyişməsindən **sonra**
(az piksel = sürətli), kəskinlik blurdan **sonra**, `format=yuv420p` isə ən sonda olur.

### `encode.py` — encode əmri
`build_encode_plan()` argv qaytarır: input/map, `-vf`, CFR, kodek bloku, rəng
metadata, audio, konteyner bayraqları. Burada həm də **AAC bitrate limiti** hesablanır
(`6144 bit/frame` → 48kHz-də maksimum 288kbps) və istifadəçiyə xəbərdarlıq yazılır.

### `interpolate.py` — mühərriklər
| Mühərrik | Necə işləyir | Mövcudluq şərti |
|---|---|---|
| `RifeNcnnEngine` | PNG çıxar → `rife-ncnn-vulkan -n <hədəf kadr>` → encoder PNG-ləri oxuyur | binary + `*.param` model qovluğu |
| `VapourSynthRifeEngine` | `.vpy` yaradır → `vspipe --y4m - \| ffmpeg -c:v ffv1` (pipe, shell yox) | `vspipe` |
| `MinterpolateEngine` | `-vf minterpolate=...` (əlavə proses yoxdur) | `minterpolate` filtri |

`resolve()` AUTO siyasətini yerinə yetirir; `plan_for()` mühərrik işləməsə
**minterpolate-a düşür** və bunu log-a yazır. Bütün mühərriklər `InterpolationPlan`
qaytarır — heç biri subprocess icra etmir.

### `pipeline.py` — zəncir
`Pipeline.run()`:

1. log/hesabat yolları, `FFmpegRunner` açılır
2. `probe()` → `MediaInfo`
3. `plan()` → hər çıxış üçün (target, engine, plan, workdir) + ümumi addım sayı
4. hər target üçün: əvvəlcədən addımlar (extract/RIFE) → `build_filter_plan()` →
   `build_encode_plan()` → `runner.run()` → `verify()`
5. `.reelforge_tmp` təmizlənir (`--keep-temp` ilə saxlanıla bilər)
6. JSON hesabat yazılır

`Pipeline._run_pipe()` iki prosesi shell olmadan birləşdirir
(`vspipe.stdout → ffmpeg.stdin`), stderr-i müvəqqəti fayla yığıb xəta halında göstərir.

### `gui/` — interfeys
* `theme.py` — rəng/şrift tokenləri (`PALETTE` = studio, `DECOY` = tünd neon bənövşəyi)
* `dnd.py` — `tkinterdnd2` **opsional**: `enable_on(root)` ilə CTk pəncərəsinə DnD
  yüklənir; paket yoxdursa drop-zone sadəcə kliklə açılır
* `decoy.py` — `DecoyApp(ctk.CTk)`: tək sütunlu Decoy-stil pəncərə (header → drop
  zone → 4 tier kartı → custom controls → export zone → log). Widget-lar
  `collect_state()` ilə `UIState`-ə yığılır, `state.build(toolchain)` preset +
  `JobOptions` qaytarır, iş worker thread-də gedir.
* `app.py` — `ReelForgeApp(ctk.CTk)`: 3 sütunlu geniş UI (fayl siyahısı / presetlər /
  bütün parametrlər), toplu emal üçün.

### `uistate.py` — UI ↔ backend körpüsü
Saf Python: `UIState` (widget snapshot) → `(Preset, JobOptions)`. Hər widget-ın
hansı FFmpeg bayrağına çevrildiyi burada müəyyən olunur və `tests/test_uistate.py`
tərəfindən yoxlanılır — buna görə də pəncərəni açmadan "düymə → əmr" əlaqəsini
test etmək mümkündür. `blur_strength_to_params()` slayderi `tmix` kadr sayına,
`resolve_codec()` isə NVENC/HEVC seçimini mövcud encoder-ə çevirir (yoxdursa
H.264-ə düşür və qeyd yazır).

---

## 2. Məlumat axını (Ultra 120FPS, RIFE tapılmadıqda)

```
JobOptions + Presets.ULTRA_120
   └─ build_targets() → [RenderTarget(60), RenderTarget(120)]
        └─ resolve(AUTO) → MinterpolateEngine (RIFE yoxdur → qeyd log-a)
             └─ build_filter_plan():
                  "minterpolate=fps=120:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1:scd=fdiff:scd_threshold=8,
                   fps=120:round=near,cas=strength=0.8,format=yuv420p,
                   setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv"
                  └─ build_encode_plan() → argv
                       └─ FFmpegRunner.run() → ProgressInfo → GUI bar
                            └─ verify() → VerifyReport(fps=120, gop=[1.0, 1.0])
                                 └─ JobResult → JSON + log
```

---

## 3. Genişləndirmə

**Yeni preset:**

```python
# presets.py
SLOWMO = Preset(
    id="slowmo", label="Slow Motion 240FPS", tagline="4× yavaş",
    description="...",
    specs=(TargetSpec(fps=240, suffix="slow", label="240FPS", crf=18,
                      x264_preset="slow", interpolation=InterpolationEngineKind.AUTO,
                      sharpen=SharpenMode.CAS, sharpen_amount=0.7),),
)
ALL_PRESETS += (SLOWMO,)          # Presets.ALL / --preset slowmo avtomatik işləyir
```

**Yeni interpolyasiya mühərriki:** `InterpolationEngine`-dən törədin,
`available()` və `plan()` yazın, `resolve()`-dakı `candidates` siyahısına əlavə edin.

**Yeni filtr:** `filters.py`-də saf funksiya yazıb `build_filter_plan()`-də lazımi
yerə `graph.add(...)` çağırın — sıra sənədləşdirilib.

---

## 4. Dizayn qərarları

| Qərar | Səbəb |
|---|---|
| Qərar qatı saf funksiyalardır | Əmr sətirləri test oluna/çap oluna bilir; GUI-də "Əmrləri göstər" mümkündür |
| `ffprobe` + `ffmpeg -i` fallback | Statik/minimum build-lərdə (məs. `imageio-ffmpeg`) proqram işləməyə davam edir |
| Capability yoxlanışı (filters/encoders) | `cas`, `mblur`, `zscale`, `libx265` hər build-də yoxdur → sessiz xəta əvəzinə alternativ + qeyd |
| CRF, iki-pass yox | Sosial platformalar onsuz da re-encode edir; CRF 17-20 sabit keyfiyyət verir, fayl ölçüsü məzmundan asılıdır |
| `-sc_threshold 0` + `-x264-params scenecut=0` | Həm AVOption, həm x264 səviyyəsində: GOP həqiqətən sabit qalır |
| Ara fayllar PNG / FFV1 | İnterpolyasiya itkili kadr üzərində işləməsin; yeganə itkili mərhələ son encode olsun |
| QA addımı | TikTok-a yükləməzdən əvvəl FPS/kodek/GOP-un həqiqətən yazıldığı yoxlanılır |
