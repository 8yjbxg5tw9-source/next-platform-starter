"""Optional TikTok auto-upload after a render finishes.

Pure-Python module: no Tk, no rendering logic.  The GUI calls
:meth:`reelforge.pipeline.ReelForge.upload` from its worker thread once the
export succeeds.  **Nothing here raises for an expected failure** (missing
``cookies.txt``, no uploader installed, network/session error): problems come
back as ``UploadResult(ok=False, error=...)`` so the window can paint the
message into its LOG box instead of crashing.

Backends (auto-detected, first available wins)
----------------------------------------------

1. ``tiktok-uploader`` — Python package (browser automation via Playwright).
   ``pip install tiktok-uploader && playwright install chromium``
2. ``tiktok-uploader`` CLI — the same project's ``tiktok-uploader`` executable
   found on ``PATH``; this is the route that works from a frozen ``.exe``.
3. ``playwright`` — minimal direct automation, used when the package above is
   absent but Playwright is installed.

Authentication is cookie-based: log into tiktok.com in a normal browser,
export ``cookies.txt`` (e.g. with the "Get cookies.txt" extension) and drop it
next to the program, next to the rendered video, or point the
``REELFORGE_TIKTOK_COOKIES`` environment variable at it.

The rendered file is posted **as-is** — no re-encode — so the anti-compression
quality of the export survives end to end.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from importlib import import_module
from importlib.util import find_spec
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

#: environment variable with an explicit cookies.txt path
COOKIE_ENV = "REELFORGE_TIKTOK_COOKIES"

#: file names searched (in this order) inside every candidate directory
COOKIE_FILENAMES: Tuple[str, ...] = (
    "cookies.txt",
    "tiktok_cookies.txt",
    "tiktok-cookies.txt",
)

TIKTOK_URL = "https://www.tiktok.com"
TIKTOK_UPLOAD_URL = TIKTOK_URL + "/upload"

#: TikTok web upload limit (~4 GB)
MAX_UPLOAD_BYTES = 4 * 1024 ** 3

BACKEND_PACKAGE = "tiktok-uploader"
BACKEND_CLI = "tiktok-uploader-cli"
BACKEND_PLAYWRIGHT = "playwright"

LogCallback = Callable[[str], None]


class UploadError(RuntimeError):
    """Expected, user-facing upload failure (never crashes the app)."""


# --------------------------------------------------------------------------- #
# data types
# --------------------------------------------------------------------------- #


@dataclass
class UploadRequest:
    """Everything the GUI collects for one automatic upload."""

    path: Path
    description: str = ""
    cookies: Optional[Path] = None
    proxy: Optional[str] = None
    headless: bool = True
    timeout: float = 900.0
    backend: str = "auto"  # auto | tiktok-uploader | tiktok-uploader-cli | playwright


@dataclass
class UploadResult:
    """Outcome of one upload attempt — errors are data, not exceptions."""

    ok: bool = False
    backend: str = ""
    url: str = ""
    error: Optional[str] = None
    cookies: Optional[Path] = None
    command: List[str] = field(default_factory=list)
    logs: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "backend": self.backend,
            "url": self.url,
            "error": self.error,
            "cookies": str(self.cookies) if self.cookies else None,
            "command": self.command,
            "logs": list(self.logs),
        }


# --------------------------------------------------------------------------- #
# cookie discovery
# --------------------------------------------------------------------------- #


def app_dirs() -> List[Path]:
    """Directories where a user would sensibly drop ``cookies.txt``."""
    dirs: List[Path] = []
    if getattr(sys, "frozen", False):  # PyInstaller build
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            dirs.append(Path(meipass))
        dirs.append(Path(sys.executable).resolve().parent)
    dirs.append(Path(__file__).resolve().parent.parent)  # project root
    dirs.append(Path.cwd())
    ordered: List[Path] = []
    seen = set()
    for directory in dirs:
        key = str(directory)
        if key not in seen:
            seen.add(key)
            ordered.append(directory)
    return ordered


def find_cookies(
    explicit: Optional[str | Path] = None,
    video: Optional[str | Path] = None,
    extra_dirs: Optional[List[str | Path]] = None,
) -> Optional[Path]:
    """Locate a Netscape cookies file.

    Priority: explicit path -> ``REELFORGE_TIKTOK_COOKIES`` -> next to the
    rendered video -> next to the app/exe -> current working directory.
    """
    candidates: List[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    env = os.environ.get(COOKIE_ENV, "").strip()
    if env:
        candidates.append(Path(env).expanduser())

    search_dirs: List[Path] = []
    if video is not None:
        search_dirs.append(Path(video).expanduser().resolve().parent)
    search_dirs.extend(app_dirs())
    for extra in extra_dirs or []:
        search_dirs.append(Path(extra))
    for directory in search_dirs:
        for name in COOKIE_FILENAMES:
            candidates.append(directory / name)

    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate
        except OSError:  # pragma: no cover - unreadable mount etc.
            continue
    return None


def parse_cookies_file(path: str | Path) -> List[Dict[str, Any]]:
    """Parse a Netscape ``cookies.txt`` into Playwright-ready dicts."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    rows: List[Dict[str, Any]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        http_only = line.startswith("#HttpOnly_")
        if line.startswith("#") and not http_only:
            continue
        if http_only:
            line = line[len("#HttpOnly_"):]
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        domain, _flag, cpath, secure, expiry, name, value = parts[:7]
        row: Dict[str, Any] = {
            "name": name,
            "value": value,
            "domain": domain or ".tiktok.com",
            "path": cpath or "/",
            "secure": secure.strip().upper() in ("TRUE", "1"),
            "httpOnly": http_only,
        }
        try:
            row["expires"] = float(expiry)
        except ValueError:
            pass  # session cookie
        rows.append(row)
    return rows


# --------------------------------------------------------------------------- #
# backend discovery
# --------------------------------------------------------------------------- #


def _module_present(name: str) -> bool:
    """Importable?  (find_spec never executes the module.)"""
    try:
        return find_spec(name) is not None
    except (ImportError, ValueError):  # pragma: no cover - broken installs
        return False


def available_backends() -> List[Tuple[str, bool, str]]:
    """``(name, ok, reason)`` for every supported upload route."""
    results: List[Tuple[str, bool, str]] = []
    if _module_present("tiktok_uploader"):
        results.append((BACKEND_PACKAGE, True, "python paketi (Playwright avtomatlaşdırması)"))
    else:
        results.append(
            (BACKEND_PACKAGE, False, "quraşdırılmayıb — pip install tiktok-uploader")
        )
    cli = shutil.which("tiktok-uploader")
    results.append((BACKEND_CLI, bool(cli), cli or "PATH-da 'tiktok-uploader' exe yoxdur"))
    if _module_present("playwright"):
        results.append((BACKEND_PLAYWRIGHT, True, "birbaşa Playwright avtomatlaşdırması"))
    else:
        results.append((BACKEND_PLAYWRIGHT, False, "quraşdırılmayıb — pip install playwright"))
    return results


def choose_backend(preferred: str = "auto") -> Optional[str]:
    """Resolve ``preferred`` (or the first available backend); ``None`` = impossible."""
    backends = available_backends()
    if preferred and preferred != "auto":
        for name, ok, _reason in backends:
            if name == preferred:
                return name if ok else None
        return None
    for name, ok, _reason in backends:
        if ok:
            return name
    return None


def describe() -> str:
    """Human-readable availability block for the LOG box."""
    lines = ["TikTok uploader backendləri:"]
    for name, ok, reason in available_backends():
        lines.append(f"  - {name}: {'OK' if ok else 'yox'} ({reason})")
    cookies = find_cookies()
    lines.append(f"  cookies: {cookies if cookies else 'tapılmadı'}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# backends
# --------------------------------------------------------------------------- #


def _upload_via_tiktok_uploader(
    request: UploadRequest,
    video: Path,
    cookies: Path,
    result: UploadResult,
    log: LogCallback,
) -> None:
    """Backend 1: the ``tiktok-uploader`` Python package."""
    try:
        mod = import_module("tiktok_uploader.upload")
    except Exception as exc:
        raise UploadError(
            f"tiktok_uploader import olunmadı: {type(exc).__name__}: {exc} — "
            "pip install tiktok-uploader && playwright install chromium"
        ) from exc
    log("TikTok brauzer sessiyası açılır (ilk dəfə brauzer endirilməsi uzun çəkə bilər)…")
    if hasattr(mod, "TikTokUploader"):  # >= 1.2 API
        kwargs: Dict[str, Any] = {"cookies": str(cookies), "headless": request.headless}
        if request.proxy:
            kwargs["proxy"] = request.proxy
        uploader = mod.TikTokUploader(**kwargs)
        failed = uploader.upload_video(str(video), description=request.description)
        if isinstance(failed, (list, tuple)) and failed:
            raise UploadError(f"tiktok-uploader uğursuz video bildirdi: {list(failed)!r}")
    else:  # older function API
        kwargs = {
            "description": request.description,
            "cookies": str(cookies),
            "headless": request.headless,
        }
        if request.proxy:
            kwargs["proxy"] = request.proxy
        mod.upload_video(str(video), **kwargs)
    result.ok = True
    result.url = TIKTOK_URL


def _upload_via_cli(
    request: UploadRequest,
    video: Path,
    cookies: Path,
    result: UploadResult,
    log: LogCallback,
) -> None:
    """Backend 2: the ``tiktok-uploader`` CLI on PATH (works from a frozen exe)."""
    exe = shutil.which("tiktok-uploader") or "tiktok-uploader"
    argv = [exe, "-v", str(video), "-d", request.description, "-c", str(cookies)]
    if request.headless:
        argv.append("--headless")
    if request.proxy:
        argv += ["--proxy", request.proxy]
    result.command = argv
    log("CLI: " + " ".join(shlex.quote(part) for part in argv))
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=request.timeout,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired as exc:
        raise UploadError(
            f"Yükləmə {request.timeout:.0f}s ərzində bitmədi — internet/sessiya yoxlanın."
        ) from exc
    tail = [
        line.strip()
        for line in (proc.stderr or "").splitlines() + (proc.stdout or "").splitlines()
        if line.strip()
    ][-12:]
    for line in tail:
        log("  " + line)
    if proc.returncode != 0:
        raise UploadError(
            f"tiktok-uploader CLI xəta kodu {proc.returncode} qaytardı: "
            + " | ".join(tail[-3:])
        )
    result.ok = True
    result.url = TIKTOK_URL


def _upload_via_playwright(
    request: UploadRequest,
    video: Path,
    cookies: Path,
    result: UploadResult,
    log: LogCallback,
) -> None:
    """Backend 3: minimal direct Playwright automation.

    Fallback for machines with Playwright but without ``tiktok-uploader``.
    Selectors follow the TikTok web upload page (2026); if TikTok changes its
    DOM this fails loudly in the LOG box — the app itself never crashes.
    """
    rows = parse_cookies_file(cookies)
    if not rows:
        raise UploadError("cookies.txt oxunmadı (Netscape formatı gözlənilir)")
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception as exc:
        raise UploadError(
            f"playwright import olunmadı: {type(exc).__name__}: {exc} — "
            "pip install playwright && playwright install chromium"
        ) from exc

    proxy = {"server": request.proxy} if request.proxy else None
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=request.headless, proxy=proxy)
        try:
            context = browser.new_context(viewport={"width": 1280, "height": 900})
            context.add_cookies(rows)
            page = context.new_page()
            log("TikTok upload səhifəsi açılır…")
            page.goto(TIKTOK_UPLOAD_URL, timeout=60_000, wait_until="domcontentloaded")
            log("Video faylı seçilir…")
            page.set_input_files('input[type="file"]', str(video), timeout=60_000)
            page.wait_for_selector(
                'div[data-text="true"], .public-DraftEditor-content', timeout=240_000
            )
            if request.description:
                editor = page.locator(
                    'div[data-text="true"], .public-DraftEditor-content'
                ).first
                editor.click()
                editor.type(request.description, delay=15)
            log("Paylaş düyməsi axtarılır…")
            page.locator(
                'button:has-text("Post"), button:has-text("Paylaş"), button:has-text("Göndər")'
            ).first.click(timeout=30_000)
            page.wait_for_url(f"{TIKTOK_URL}/**", timeout=300_000)
            result.ok = True
            result.url = page.url
            log(f"Yükləndi: {page.url}")
        finally:
            browser.close()


_BACKEND_RUNNERS: Dict[str, Callable[..., None]] = {
    BACKEND_PACKAGE: _upload_via_tiktok_uploader,
    BACKEND_CLI: _upload_via_cli,
    BACKEND_PLAYWRIGHT: _upload_via_playwright,
}


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #


def upload(
    request: UploadRequest,
    *,
    log_callback: Optional[LogCallback] = None,
) -> UploadResult:
    """Run one upload attempt.  **Never raises** — failures land in ``error``."""
    result = UploadResult()

    def log(message: str) -> None:
        result.logs.append(message)
        if callable(log_callback):
            try:
                log_callback(message)
            except Exception:  # pragma: no cover - UI code must never kill a job
                pass

    try:
        video = Path(request.path).expanduser()
        if not video.is_file():
            raise UploadError(f"Yüklənəcək fayl tapılmadı: {video}")
        size = video.stat().st_size
        if size <= 0:
            raise UploadError(f"Fayl boşdur: {video}")
        if size > MAX_UPLOAD_BYTES:
            raise UploadError(
                f"Fayl {size / 1e9:.2f} GB — TikTok web yükləmə həddi ~4 GB-dır."
            )
        if video.suffix.lower() not in {".mp4", ".mov", ".webm"}:
            log(f"! qeyri-standart konteyner '{video.suffix}' — TikTok .mp4 gözləyir")

        cookies = find_cookies(request.cookies, video=video)
        if cookies is None:
            raise UploadError(
                "cookies.txt tapılmadı — TikTok-a avtomatik giriş mümkün deyil. "
                "Brauzerdə tiktok.com-a daxil olun, cookies faylını ixrac edin "
                "(məs. 'Get cookies.txt' genişlənməsi) və buralardan birinə qoyun: "
                + " · ".join(str(d) for d in app_dirs()[:4])
                + f" — və ya {COOKIE_ENV} env dəyişənini təyin edin."
            )
        result.cookies = cookies
        log(f"cookies faylı: {cookies}")

        backend = choose_backend(request.backend)
        if backend is None:
            if request.backend != "auto":
                raise UploadError(
                    f"'{request.backend}' backend mövcud deyil. " + describe()
                )
            raise UploadError(
                "TikTok uploader tapılmadı — quraşdırın: "
                "pip install tiktok-uploader && playwright install chromium"
            )
        result.backend = backend
        log(f"backend: {backend} · açıqlama: {request.description or '(boş)'}")
        _BACKEND_RUNNERS[backend](request, video, cookies, result, log)
    except UploadError as exc:
        result.ok = False
        result.error = str(exc)
    except Exception as exc:  # network / session / DOM errors — GUI must not crash
        result.ok = False
        result.error = f"{type(exc).__name__}: {exc}"
        log(f"gözlənilməz xəta: {result.error}")
    return result
