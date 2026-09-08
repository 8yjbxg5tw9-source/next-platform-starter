"""In-app TikTok session capture — "LOGIN TO TIKTOK" (Auto-Session Capture).

Replaces manual ``cookies.txt`` handling: the user presses one button, an
internal (Playwright-driven) Chromium window opens at ``tiktok.com/login``,
and the moment the login cookies appear the app

1. grabs the browser ``storage_state`` (all cookies + localStorage),
2. reads the profile username,
3. saves everything to ``~/.reelforge/tiktok_session.json`` (chmod 600),
4. closes the window by itself.

The GUI then shows ``LOGGED IN ✓ @username``.  Whatever TikTok offers
(QR code, password, 2FA/SMS) happens inside that window — the app never
sees the password and never asks for codes, which is exactly why this is
the quietest, extension-free login method.

Uploads (:mod:`reelforge.upload`) reuse this session **headless**: no
browser window opens during export.  When TikTok expires the session the
upload returns :data:`SESSION_EXPIRED` instead of crashing, and the user
simply presses LOGIN TO TIKTOK again.

Pure Python + optional Playwright: no Tk imports, fully unit-testable.
"""

from __future__ import annotations

import json
import os
import re
import stat
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

LOGIN_URL = "https://www.tiktok.com/login"
PROFILE_URL = "https://www.tiktok.com/@me"

#: cookies TikTok sets only for an authenticated session
LOGIN_COOKIE_NAMES = ("sessionid", "sessionid_ss", "sid_tt")

SESSION_FILENAME = "tiktok_session.json"

#: shown in the LOG box when TikTok has invalidated the saved session
SESSION_EXPIRED = "Sessiya yenilənməlidir"

LogCallback = Callable[[str], None]


# --------------------------------------------------------------------------- #
# storage
# --------------------------------------------------------------------------- #


def session_dir() -> Path:
    """Where the session file lives (user-local, survives updates)."""
    return Path.home() / ".reelforge"


def session_path() -> Path:
    return session_dir() / SESSION_FILENAME


def load_session() -> Optional[Dict[str, Any]]:
    """Return the saved session dict, or ``None`` when absent/unreadable."""
    path = session_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("storage_state"), dict):
        return None
    return data


def save_session(storage_state: Dict[str, Any], username: str = "") -> Path:
    """Persist a Playwright ``storage_state`` payload (owner-read/write only)."""
    path = session_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "username": username,
        "captured_at": time.time(),
        "storage_state": storage_state,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # 0600
    except OSError:  # pragma: no cover - e.g. Windows ACL differences
        pass
    return path


def clear_session() -> bool:
    try:
        session_path().unlink()
        return True
    except OSError:
        return False


# --------------------------------------------------------------------------- #
# status
# --------------------------------------------------------------------------- #


def _auth_cookies(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    cookies = data.get("storage_state", {}).get("cookies", [])
    return [c for c in cookies if c.get("name") in LOGIN_COOKIE_NAMES and c.get("value")]


def session_expired(data: Dict[str, Any]) -> bool:
    """True when no valid auth cookie remains in the saved state."""
    cookies = _auth_cookies(data)
    if not cookies:
        return True
    now = time.time()
    for cookie in cookies:
        expires = cookie.get("expires", -1)
        try:
            expires = float(expires)
        except (TypeError, ValueError):
            expires = -1.0
        if expires < 0 or expires > now:  # -1 = browser-session cookie
            return False
    return True


def session_info() -> Dict[str, Any]:
    """``{logged_in, username, expired, path}`` snapshot for the GUI."""
    path = session_path()
    data = load_session()
    if data is None:
        return {"logged_in": False, "username": "", "expired": False, "path": path}
    expired = session_expired(data)
    return {
        "logged_in": not expired,
        "username": str(data.get("username") or ""),
        "expired": expired,
        "path": path,
    }


def is_logged_in() -> bool:
    return session_info()["logged_in"]


# --------------------------------------------------------------------------- #
# capture
# --------------------------------------------------------------------------- #


@dataclass
class CaptureResult:
    """Outcome of one LOGIN TO TIKTOK attempt — errors are data, not exceptions."""

    ok: bool = False
    username: str = ""
    error: Optional[str] = None
    path: Optional[Path] = None
    logs: List[str] = field(default_factory=list)


def _detect_username(page, log: LogCallback) -> str:
    """Best-effort @username read (profile redirect); '' on any failure."""
    try:
        page.goto(PROFILE_URL, timeout=30_000)
        match = re.search(r"/@([^/?#]+)", page.url)
        if match:
            return match.group(1)
    except Exception:  # pragma: no cover - network/DOM variability
        pass
    log("profil adı oxunmadı (giriş uğurludur)")
    return ""


def capture_session(
    *,
    log_callback: Optional[LogCallback] = None,
    timeout: float = 300.0,
    headless: bool = False,
    poll: float = 2.0,
) -> CaptureResult:
    """Open the login window, wait for the user, save the session, close.

    **Never raises** — every failure (no Playwright, no Chromium, user closed
    the window, timeout) comes back as ``CaptureResult(ok=False, error=...)``
    so the GUI can log it and stay alive.
    """
    result = CaptureResult()

    def log(message: str) -> None:
        result.logs.append(message)
        if callable(log_callback):
            try:
                log_callback(message)
            except Exception:  # pragma: no cover - UI code must never kill a job
                pass

    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception as exc:
        result.error = (
            f"Playwright quraşdırılmayıb: {type(exc).__name__}: {exc} — "
            "pip install playwright && playwright install chromium"
        )
        return result

    try:
        with sync_playwright() as pw:
            try:
                browser = pw.chromium.launch(headless=headless)
            except Exception as exc:
                result.error = (
                    f"Chromium açılmadı: {type(exc).__name__}: {exc} — "
                    "'playwright install chromium' əmrini bir dəfə icra edin"
                )
                return result
            try:
                context = browser.new_context(viewport={"width": 1100, "height": 800})
                page = context.new_page()
                log("Daxili brauzer açılır: tiktok.com/login …")
                page.goto(LOGIN_URL, timeout=60_000)
                log("Pəncərədə hesabınıza daxil olun (QR / şifrə / 2FA) — "
                    "proqram arxa planda gözləyir…")
                deadline = time.monotonic() + timeout
                logged = False
                while time.monotonic() < deadline:
                    try:
                        cookies = context.cookies("https://www.tiktok.com")
                    except Exception:
                        break  # user closed the window
                    if any(
                        c.get("name") in LOGIN_COOKIE_NAMES and c.get("value")
                        for c in cookies
                    ):
                        logged = True
                        break
                    time.sleep(poll)
                if not logged:
                    result.error = (
                        "Giriş tamamlanmadı — vaxt bitdi və ya pəncərə bağlandı. "
                        "LOGIN TO TIKTOK düyməsini yenidən basın."
                    )
                    return result
                log("Giriş aşkarlandı — sessiya təhlükəsiz faylda saxlanılır…")
                username = _detect_username(page, log)
                path = save_session(context.storage_state(), username)
                result.ok = True
                result.username = username
                result.path = path
                log(f"Sessiya saxlanıldı: {path}"
                    + (f" (@{username})" if username else ""))
            finally:
                try:
                    browser.close()  # pəncərə avtomatik bağlanır
                except Exception:  # pragma: no cover - already closed by user
                    pass
                log("Brauzer pəncərəsi bağlandı.")
    except Exception as exc:  # defensive: GUI must not crash
        result.ok = False
        result.error = f"{type(exc).__name__}: {exc}"
    return result
