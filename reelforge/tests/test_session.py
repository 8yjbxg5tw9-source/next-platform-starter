"""Tests for the Auto-Session Capture module (no browser, no network).

Covers the pure parts: session storage round-trip, expiry logic, file
permissions, and the guarantee that ``capture_session()`` degrades to a
``CaptureResult(ok=False, error=...)`` instead of raising.
"""

from __future__ import annotations

import os
import sys
import time

import pytest

from reelforge import session as session_mod


@pytest.fixture(autouse=True)
def _tmp_session_dir(tmp_path, monkeypatch):
    """Never touch the real ~/.reelforge during tests."""
    monkeypatch.setattr(session_mod, "session_dir", lambda: tmp_path)


def _state(cookies):
    return {"cookies": cookies, "origins": []}


# --------------------------------------------------------------------------- #
# storage
# --------------------------------------------------------------------------- #


def test_save_load_roundtrip():
    state = _state([{"name": "sessionid", "value": "abc",
                     "domain": ".tiktok.com", "path": "/", "expires": -1}])
    path = session_mod.save_session(state, "reeluser")
    assert path == session_mod.session_dir() / session_mod.SESSION_FILENAME

    data = session_mod.load_session()
    assert data["username"] == "reeluser"
    assert data["storage_state"] == state
    assert data["captured_at"] <= time.time()

    info = session_mod.session_info()
    assert info["logged_in"] is True
    assert info["username"] == "reeluser"
    assert session_mod.is_logged_in()

    assert session_mod.clear_session() is True
    assert session_mod.is_logged_in() is False
    assert session_mod.load_session() is None


@pytest.mark.skipif(os.name != "posix", reason="chmod semantics")
def test_session_file_is_owner_read_write_only():
    path = session_mod.save_session(_state([]), "u")
    assert path.stat().st_mode & 0o777 == 0o600


def test_session_info_absent():
    info = session_mod.session_info()
    assert info["logged_in"] is False
    assert info["expired"] is False
    assert info["path"] == session_mod.session_dir() / session_mod.SESSION_FILENAME


def test_load_session_ignores_garbage_file():
    path = session_mod.session_dir() / session_mod.SESSION_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not json {{{", encoding="utf-8")
    assert session_mod.load_session() is None
    assert session_mod.is_logged_in() is False


# --------------------------------------------------------------------------- #
# expiry logic
# --------------------------------------------------------------------------- #


def test_expired_cookie_marks_session_dead():
    session_mod.save_session(_state([
        {"name": "sessionid", "value": "x", "expires": time.time() - 100},
    ]))
    assert session_mod.session_expired(session_mod.load_session()) is True
    info = session_mod.session_info()
    assert info["logged_in"] is False and info["expired"] is True


def test_valid_future_cookie_is_logged_in():
    session_mod.save_session(_state([
        {"name": "sid_tt", "value": "x", "expires": time.time() + 10_000},
    ]))
    assert session_mod.is_logged_in() is True


def test_browser_session_cookie_counts_as_valid():
    session_mod.save_session(_state([
        {"name": "sessionid_ss", "value": "x", "expires": -1},
    ]))
    assert session_mod.is_logged_in() is True


def test_non_auth_cookies_do_not_count():
    session_mod.save_session(_state([
        {"name": "tt_csrf_token", "value": "x", "expires": time.time() + 9999},
        {"name": "msToken", "value": "y", "expires": -1},
    ]))
    assert session_mod.is_logged_in() is False


# --------------------------------------------------------------------------- #
# capture: degrades gracefully without Playwright
# --------------------------------------------------------------------------- #


def test_capture_without_playwright_returns_error_data(monkeypatch):
    """No Playwright installed -> CaptureResult(ok=False), never an exception."""
    monkeypatch.setitem(sys.modules, "playwright.sync_api", None)
    seen = []
    result = session_mod.capture_session(log_callback=seen.append)
    assert result.ok is False
    assert "playwright" in result.error.lower()
    assert "pip install" in result.error
