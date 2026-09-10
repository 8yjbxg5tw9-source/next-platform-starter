# Akai — License Server (Back-end)

Bu qovluq **yalnız serverdə** qalır və müştəriyə verilmir. FastAPI əsaslı
lisenziya API-si: istifadəçi adı + şifrə (SHA-256) + HWID üçlüyünü `users.json`
ilə yoxlayır, uyğunsuzluqda girişə icazə vermir.

## Quraşdırma

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn server.main:app --host 0.0.0.0 --port 8000
```

İstehsalatda mütləq **HTTPS** arxasında işlədin (nginx/Caddy + TLS), çünki
müştəri şifrənin SHA-256 hash'ini göndərir.

## Abunəçi əlavə etmək (administrator)

```bash
# HWID-ni müştəri WhatsApp-la göndərir (məs. AKAI-98F2-41A7-B800):
python tools/add_user.py --username ahmed_01 --password pin1234 \
    --hwid AKAI-98F2-41A7-B800 --days 365

# HWID hələ bilinmirsə: boş buraxın — ilk uğurlu girişdə cihaz avtomatik
# bağlanacaq, o andan etibarən başqa cihazdan giriş 403 alacaq:
python tools/add_user.py --username ahmed_01 --password pin1234 --days 365

python tools/add_user.py --list
```

`users.json`-a heç vaxt plaintext şifrə/HWID yazılmır — alət yalnız SHA-256
digest saxlayır.

## API

| Metod | Yol             | Təyinat                                       |
|-------|-----------------|-----------------------------------------------|
| POST  | `/api/v1/login` | `{username, password_hash, hwid}` → token     |
| GET   | `/api/v1/verify`| `Authorization: Bearer <token>` yoxlaması     |
| GET   | `/api/v1/health`| liveness                                      |

Xəta kodları: `401` yanlış şifrə; `403` — "Bu abunəlik başqa cihazda
aktivdir!" / "Abunəlik müddəti bitmişdir." / hesab deaktiv.

## Təhlükəsizlik qeydləri

* Şifrə və HWID yalnız SHA-256 digest kimi saxlanılır və müqayisə olunur.
* Sessiya tokenləri HMAC-SHA256 imzalıdır, 6 saat sonra bitir (`secret.key`
  ilk işə düşmədə yaranır, `AKAI_SECRET_FILE` ilə dəyişdirilə bilər).
* `users.json` yazılması atomdur (`.tmp` → rename), paralel girişlərdə
  zədələnmir (`threading.RLock`).

## Testlər

```bash
python -m pytest tests/ -q
```
