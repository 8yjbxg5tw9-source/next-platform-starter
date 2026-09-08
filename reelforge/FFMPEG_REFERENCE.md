# FFmpeg əmr və parametrlər kitabçası

Bütün əmrlər bu repozitordakı kod tərəfindən **həqiqətən yaradılan** əmrlərdir
(`python -m reelforge.cli <fayl> -p <preset> --dry-run` ilə eyni çıxışı görürsünüz).

Mündəricat: [ortaq bayraqlar](#ortaq) · [presetlər](#presetlər) · [-vf zənciri](#vf) ·
[RIFE](#rife) · [QA](#qa) · [parametrlərin izahı](#izah)

---

<a name="ortaq"></a>
## 1. Hər encode-da istifadə olunan ortaq bayraqlar

```text
ffmpeg -hide_banner -nostdin -nostats -progress pipe:1 -y \
  -i <mənbə> -map 0:v:0 -map 0:a:0? -sn -dn \
  -vf "<zəncir>" -fps_mode cfr -r <fps> \
  ... <çıxış>.mp4
```

| Bayraq | Nə üçün |
|---|---|
| `-nostdin` | GUI/CLI stdin-i tutmasın, proses asılı qalmasın |
| `-progress pipe:1` | Progress bar + ETA (stdout-da `out_time_us=`, `fps=`, `speed=`) |
| `-map 0:a:0?` | Audio varsa götür, yoxsa xəta vermə (`?`) |
| `-sn -dn` | Subtitr/data axınlarını at (platformalar onsuz da silir) |
| `-fps_mode cfr` | **Sabit** kadr sürəti (FFmpeg < 5.1-də `-vsync cfr`) |
| `-r <fps>` | Konteyner zaman bazasını da hədəf FPS-ə bağlayır |

---

<a name="presetlər"></a>
## 2. Presetlər

### 2.1 Fast Conversion — `-p fast`

```bash
ffmpeg -hide_banner -nostdin -nostats -progress pipe:1 -y \
  -i clip.mp4 -map 0:v:0 -map 0:a:0? -sn -dn \
  -vf "fps=60:round=near,format=yuv420p,setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv" \
  -fps_mode cfr -r 60 \
  -c:v libx264 -preset fast -profile:v high -level:v 4.2 -pix_fmt yuv420p -crf 20 \
  -g 60 -keyint_min 60 -sc_threshold 0 -bf 2 \
  -x264-params keyint=60:min-keyint=60:scenecut=0 \
  -color_primaries bt709 -color_trc bt709 -colorspace bt709 -color_range tv \
  -c:a aac -b:a 320k -ar 48000 -ac 2 \
  -movflags +faststart -max_muxing_queue_size 1024 clip__fast_60fps.mp4
```

### 2.2 Safe Mode (TikTok Bypass) — `-p safe`

Yuxarıdakı əmrdən fərqləri: `-preset slow`, `-crf 17`, `-tune film`, `-vf`-də `cas=strength=0.5`.

```bash
  -vf "fps=60:round=near,cas=strength=0.5,format=yuv420p,setparams=...:range=tv" \
  -c:v libx264 -preset slow -profile:v high -level:v 4.2 -pix_fmt yuv420p -crf 17 \
  -g 60 -keyint_min 60 -sc_threshold 0 -bf 2 -tune film \
  -x264-params keyint=60:min-keyint=60:scenecut=0
```

> **Niyə işləyir:** TikTok/Instagram transcoder-ləri qeyri-sabit GOP və VFR görən
> faylları "yenidən normallaşdırır" (çox vaxt 30 FPS-ə). `-g 60 -keyint_min 60
> -sc_threshold 0` + `-x264-params scenecut=0` + `-fps_mode cfr` faylı **sabit,
> proqnozlaşdırıla bilən** edir: 60 FPS-də hər 1 saniyədə tam 1 IDR.

### 2.3 Ultra 120FPS Mode — `-p ultra120` (2 fayl)

60FPS variantı:

```bash
  -vf "minterpolate=fps=60:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1:scd=fdiff:scd_threshold=8,\
fps=60:round=near,cas=strength=0.6,format=yuv420p,setparams=..." \
  -r 60 -c:v libx264 -preset slow -profile:v high -level:v 4.2 -crf 18 \
  -g 60 -keyint_min 60 -sc_threshold 0 -bf 2 -tune film ...
```

120FPS variantı:

```bash
  -vf "minterpolate=fps=120:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1:scd=fdiff:scd_threshold=8,\
fps=120:round=near,cas=strength=0.8,format=yuv420p,setparams=..." \
  -r 120 -c:v libx264 -preset slow -profile:v high -level:v 5.1 -crf 17 \
  -g 120 -keyint_min 120 -sc_threshold 0 -bf 2 -tune film \
  -x264-params keyint=120:min-keyint=120:scenecut=0 ...
```

> `level 5.1` — 120 FPS 1080p H.264 üçün `4.2` kifayət etmir.
> RIFE tapılanda `minterpolate` əvəzinə [bölmə 4](#rife)-dəki zəncir işləyir.

### 2.4 Cinematic Motion Blur — `-p motionblur`

```bash
  -vf "minterpolate=fps=120:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1:scd=fdiff:scd_threshold=8,\
tmix=frames=2:weights=1 1,fps=60:round=near,cas=strength=0.6,format=yuv420p,setparams=..." \
  -r 60 -crf 18 -preset slow -g 60 -keyint_min 60 -sc_threshold 0 ...
```

Məntiq: **2× oversample (120) → `tmix` ilə 2 kadrı birləşdir → 60-a endir**.
Bu, real kameradakı **180° shutter** effektidir ( shutter = `frames / target_fps` ).

Alternativlər (kod avtomatik seçir):

| Filtr | Əmr | Qeyd |
|---|---|---|
| `tmix` | `tmix=frames=2:weights=1 1` | kadr sayını saxlayır (default) |
| `tblend` | `tblend=all_mode=average` | kadr sayını yarıya endirir → sonra `fps` |
| `mblur` | `mblur=0.5` | hər build-də yoxdur; yoxdursa `tmix`-ə düşür |

### 2.5 Archive Master — `-p master`

```bash
  -vf "format=yuv420p,setparams=..." -fps_mode cfr -r <mənbə fps> \
  -c:v libx264 -preset veryslow -profile:v high -pix_fmt yuv420p -crf 12 \
  -g <2×fps> -keyint_min <2×fps> -sc_threshold 0 ...
```

### 2.6 HEVC variantı (`--codec hevc`)

```bash
  -c:v libx265 -preset slow -profile:v main -level:v 5.0 -pix_fmt yuv420p -crf 18 \
  -g 60 -keyint_min 60 -sc_threshold 0 -bf 2 -tune film \
  -tag:v hvc1 \
  -x265-params keyint=60:min-keyint=60:scenecut=0:log-level=error
```

`-tag:v hvc1` olmadan HEVC faylları Safari/QuickTime/iPhone-da oxunmur.

---

<a name="vf"></a>
## 3. `-vf` zəncirinin qurulması (sabit sıra)

```
[1] scale/crop/pad    →  [2] HDR tonemap  →  [3] interpolyasiya  →  [4] motion blur
    → [5] fps lock  →  [6] sharpen  →  [7] format=yuv420p  →  [8] setparams
```

**[1] Kadr ölçüsü** (`--fit`)

```text
keep     → (tək ölçülər cütə yuvarlaqlaşdırılır) scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1
cover    → scale=1080:1920:force_original_aspect_ratio=increase:flags=lanczos,crop=1080:1920,setsar=1
contain  → scale=1080:1920:force_original_aspect_ratio=decrease:flags=lanczos,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1
stretch  → scale=1080:1920:flags=lanczos,setsar=1
```

**[2] HDR → SDR** (mənbə PQ/HLG olduqda avtomatik)

```text
zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=bt709:range=tv
```

**[3] İnterpolyasiya** (`--interp-quality fast|balanced|quality`)

```text
fast     → minterpolate=fps=<N>:mi_mode=blend:scd=none
balanced → minterpolate=fps=<N>:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1:scd=fdiff:scd_threshold=8
quality  → minterpolate=fps=<N>:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1:scd=fdiff:scd_threshold=6:mb_size=8
```

**[5] FPS kilidi:** `fps=<target>:round=near` (VFR mənbəni də CFR-ə salır)

**[6] Kəskinlik**

```text
cas      → cas=strength=0.8
unsharp  → unsharp=luma_msize_x=5:luma_msize_y=5:luma_amount=0.8:chroma_msize_x=5:chroma_msize_y=5:chroma_amount=0
```

**[7-8] Format + rəng metadata**

```text
format=yuv420p,setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv
```

---

<a name="rife"></a>
## 4. RIFE zənciri (rife-ncnn-vulkan tapıldıqda)

```bash
# 1) itkisiz PNG çıxarış (interpolyasiya sıxılmış kadr üzərində işləməsin)
ffmpeg -hide_banner -nostdin -nostats -progress pipe:1 -y -i clip.mp4 -map 0:v:0 \
  -fps_mode passthrough -qscale:v 1 -q:v 1 -start_number 1 work/frames_in/%08d.png

# 2) RIFE — diqqət: -n MİSİL DEYİL, HƏDƏF KADR SAYIDIR
#    30fps/90 kadr → 120fps  =  -n 360
rife-ncnn-vulkan -i work/frames_in -o work/frames_rife -n 360 -m ~/rife/models/rife-v4.6 -f %08d.png -j 2:2:2

# 3) encoder PNG-ləri 120fps kimi oxuyur, audio mənbədən götürülür
ffmpeg ... -framerate 120 -i work/frames_rife/%08d.png -i clip.mp4 \
  -map 0:v:0 -map 1:a:0? -vf "fps=120:round=near,cas=strength=0.8,format=yuv420p,setparams=..." \
  -crf 17 -g 120 -keyint_min 120 -sc_threshold 0 ...
```

**VapourSynth yolu** (`vspipe` varsa) — proqramın yaratdığı `.vpy`:

```python
clip = core.ffms2.Source(source=SOURCE)            # və ya lsmas / bestsource
clip = clip.resize.Point(format=vs.RGBS, matrix_in_s="709")
clip = rife.RIFE(clip, model=5, fps_num=4, fps_den=1, gpu_thread=2)   # vs-mlrt fallback: factor_num/den
clip = clip.resize.Point(format=vs.YUV420P8, matrix_s="709")
```

```bash
vspipe --y4m reelforge_rife.vpy - | ffmpeg -f y4m -i pipe:0 -c:v ffv1 -level 3 -pix_fmt yuv420p rife_intermediate.mkv
```

Ara fayl **FFV1 (itkisiz)** olduğu üçün yeganə itkili mərhələ son CRF encode-dur.

---

<a name="qa"></a>
## 5. QA (hər çıxışdan sonra avtomatik)

```bash
# media məlumatı
ffprobe -v error -print_format json -show_format -show_streams out.mp4
# ffprobe yoxdursa:  ffmpeg -hide_banner -i out.mp4   (banner parse olunur)

# keyframe intervalları (GOP yoxlanışı)
ffmpeg -hide_banner -nostdin -nostats -i out.mp4 -map 0:v:0 \
  -vf "select='eq(pict_type\,I)',showinfo" -an -f null -

# dəqiq kadr sayı
ffmpeg -hide_banner -nostdin -i out.mp4 -map 0:v:0 -f null -
```

`VerifyReport` bunları yoxlayır: FPS (±0.5), kodek, `yuv420p`, `bt709`,
keyframe intervallarının `gop / fps`-ə uyğunluğu.

---

<a name="izah"></a>
## 6. Parametrlərin qısa izahı

| Parametr | Dəyər | Səbəb |
|---|---|---|
| `-c:v libx264 -profile:v high` | H.264 High | Bütün platformaların qəbul etdiyi maksimum uyğunluq |
| `-pix_fmt yuv420p` | 8-bit 4:2:0 | Platforma tələbi; başqa format re-encode deməkdir |
| `-crf 17…20` | sabit keyfiyyət | "Minimal sıxılma": 17 ≈ vizual itkisiz, 20 = sürətli rejim |
| `-preset slow` / `fast` | encoder səyi | Eyni CRF-də daha kiçik və daha təmiz fayl |
| `-g` = `-keyint_min` = `fps` | 1 saniyəlik GOP | Sabit struktur → transcoder faylı pozmur |
| `-sc_threshold 0` + `scenecut=0` | səhnə kəsilməsində IDR qadağası | GOP həqiqətən sabit qalır |
| `-bf 2` | 2 B-kadr | Sıxılma səmərəsi; `-bf 0` yalnız problem olarsa |
| `-color_primaries/-color_trc/-colorspace bt709` | rəng etiketi | Etiket yoxdursa platforma BT.601 saya bilər → rəng sürüşür |
| `-color_range tv` | limited range | Tam diapazon (pc) solğun/qara basıqlığı yaradır |
| `-c:a aac -b:a 320k -ar 48000 -ac 2` | audio | AAC-LC limiti 6144 bit/kadr → 48kHz-də real maksimum **288 kbps** (proqram xəbərdarlıq verir; əsl 320k üçün `--audio-rate 96000`) |
| `-movflags +faststart` | moov əvvəldə | Veb/telefonda dərhal oynama |
| `-max_muxing_queue_size 1024` | filter zənciri üçün təhlükəsizlik | Uzun zəncirlərdə "too many packets buffered" xətasının qarşısı |
