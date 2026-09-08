"""Tests for the optional TikTok upload path — no network, no browser.

Every backend call is stubbed; what is verified is the *wiring*: cookie
discovery priority, backend selection, argv construction, and the guarantee
that ``upload()`` converts failures into ``UploadResult(ok=False)`` instead of
raising (so the GUI can log them without crashing).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from reelforge import session as session_mod
from reelforge import upload as upload_mod
from reelforge.uistate import UIState, status_text
from reelforge.upload import (
    BACKEND_CLI,
    BACKEND_PACKAGE,
    BACKEND_SESSION,
    COOKIE_ENV,
    UploadRequest,
    choose_backend,
    find_cookies,
    parse_cookies_file,
    upload,
)


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _no_real_backends(monkeypatch):
    """No cookies env, no CLI on PATH, no packages, no captured session."""
    monkeypatch.delenv(COOKIE_ENV, raising=False)
    monkeypatch.setattr(upload_mod.shutil, "which", lambda _name: None)
    monkeypatch.setattr(upload_mod, "_module_present", lambda _name: False)
    monkeypatch.setattr(session_mod, "is_logged_in", lambda: False)
    monkeypatch.setattr(session_mod, "load_session", lambda: None)


@pytest.fixture
def video(tmp_path: Path) -> Path:
    path = tmp_path / "out" / "clip__ultra120_120fps.mp4"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00" * 64)
    return path


def _fake_backend(result_ok: bool = True, error: Exception | None = None):
    def runner(request, video, cookies, result, log):
        if error is not None:
            raise error
        result.ok = result_ok
        result.url = "https://www.tiktok.com/@me/video/1"
        log("backend işlədi")
    return runner


def _backend_available(monkeypatch, name: str = BACKEND_PACKAGE):
    monkeypatch.setattr(
        upload_mod, "available_backends",
        lambda: [(name, True, "test")],
    )
    monkeypatch.setitem(upload_mod._BACKEND_RUNNERS, name, _fake_backend())


# --------------------------------------------------------------------------- #
# cookie discovery
# --------------------------------------------------------------------------- #


def test_find_cookies_priority_explicit_env_video_appdir(tmp_path, monkeypatch):
    explicit = tmp_path / "explicit.txt"
    explicit.write_text("x")
    env_file = tmp_path / "env.txt"
    env_file.write_text("x")
    monkeypatch.setenv(COOKIE_ENV, str(env_file))
    monkeypatch.setattr(upload_mod, "app_dirs", lambda: [tmp_path])
    # explicit path always wins
    assert find_cookies(explicit) == explicit
    # env var wins over app dirs
    assert find_cookies() == env_file


def test_find_cookies_next_to_video(tmp_path, monkeypatch):
    monkeypatch.setattr(upload_mod, "app_dirs", lambda: [tmp_path / "empty"])
    (tmp_path / "empty").mkdir()
    video = tmp_path / "out" / "clip.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"x")
    cookies = tmp_path / "out" / "cookies.txt"
    cookies.write_text("netscape")
    assert find_cookies(video=video) == cookies


def test_find_cookies_none_when_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(upload_mod, "app_dirs", lambda: [tmp_path / "empty"])
    monkeypatch.chdir(tmp_path)
    assert find_cookies(video=tmp_path / "missing.mp4") is None


def test_parse_cookies_file_netscape(tmp_path):
    path = tmp_path / "cookies.txt"
    path.write_text(
        "# Netscape HTTP Cookie File\n"
        "\n"
        ".tiktok.com\tTRUE\t/\tTRUE\t1893456000\tsessionid\tABC123\n"
        "#HttpOnly_.tiktok.com\tTRUE\t/\tTRUE\t1893456000\ttt-target-idc\tsig\n"
        "malformed line without tabs\n"
        ".tiktok.com\tTRUE\t/\tFALSE\t0\tmsToken\ttok\n",
        encoding="utf-8",
    )
    rows = parse_cookies_file(path)
    assert [r["name"] for r in rows] == ["sessionid", "tt-target-idc", "msToken"]
    assert rows[0]["domain"] == ".tiktok.com"
    assert rows[0]["secure"] is True
    assert rows[0]["expires"] == 1893456000.0
    assert rows[1]["httpOnly"] is True
    assert rows[2]["secure"] is False
    assert "expires" in rows[2] and rows[2]["expires"] == 0.0


# --------------------------------------------------------------------------- #
# backend selection
# --------------------------------------------------------------------------- #


def test_available_backends_lists_all_four_session_first():
    names = [name for name, _ok, _reason in upload_mod.available_backends()]
    assert names == [BACKEND_SESSION, BACKEND_PACKAGE, BACKEND_CLI, "playwright"]


def test_session_backend_first_when_logged_in(monkeypatch):
    monkeypatch.setattr(session_mod, "is_logged_in", lambda: True)
    monkeypatch.setattr(upload_mod, "_module_present", lambda name: name == "playwright")
    assert choose_backend() == BACKEND_SESSION


def test_choose_backend_auto_picks_first_available(monkeypatch):
    monkeypatch.setattr(
        upload_mod, "available_backends",
        lambda: [(BACKEND_PACKAGE, False, "yox"), (BACKEND_CLI, True, "/x/tiktok-uploader"),
                 ("playwright", True, "ok")],
    )
    assert choose_backend() == BACKEND_CLI
    assert choose_backend("playwright") == "playwright"
    assert choose_backend(BACKEND_PACKAGE) is None   # requested but not ok
    assert choose_backend("nonexistent") is None


def test_choose_backend_none_when_nothing_installed():
    assert choose_backend() is None  # autouse fixture: everything unavailable


# --------------------------------------------------------------------------- #
# upload(): failures are data, never exceptions
# --------------------------------------------------------------------------- #


def test_upload_missing_file(video, monkeypatch):
    monkeypatch.setitem(
        upload_mod._BACKEND_RUNNERS, BACKEND_PACKAGE,
        lambda *a, **k: pytest.fail("backend must not run"),
    )
    res = upload(UploadRequest(path=video.parent / "nope.mp4"))
    assert res.ok is False
    assert "tapılmadı" in res.error


def test_upload_missing_auth_mentions_login_button(video, monkeypatch):
    monkeypatch.setattr(upload_mod, "app_dirs", lambda: [video.parent / "empty"])
    monkeypatch.chdir(video.parent)
    monkeypatch.setattr(
        upload_mod, "_module_present", lambda name: name == "tiktok_uploader")
    res = upload(UploadRequest(path=video, description="#fyp"))
    assert res.ok is False
    assert "LOGIN TO TIKTOK" in res.error
    assert "cookies.txt" in res.error


def test_upload_missing_backend_is_reported(video, tmp_path, monkeypatch):
    (video.parent / "cookies.txt").write_text("netscape")
    monkeypatch.setattr(upload_mod, "app_dirs", lambda: [video.parent])
    res = upload(UploadRequest(path=video))
    assert res.ok is False
    assert "pip install playwright" in res.error


def test_upload_uses_captured_session_headless(video, monkeypatch):
    """Auto-Session Capture: no cookies.txt needed, session backend wins."""
    monkeypatch.setattr(session_mod, "is_logged_in", lambda: True)
    monkeypatch.setattr(session_mod, "session_info",
                        lambda: {"logged_in": True, "username": "reeluser",
                                 "expired": False, "path": video})
    monkeypatch.setattr(
        upload_mod, "_module_present", lambda name: name == "playwright")

    def fake_session_runner(request, _video, cookies, result, log):
        assert cookies is None          # legacy cookies path untouched
        result.ok = True
        result.url = "https://www.tiktok.com/@reeluser/video/9"
        log("headless upload tamam")

    monkeypatch.setitem(upload_mod._BACKEND_RUNNERS, BACKEND_SESSION, fake_session_runner)
    res = upload(UploadRequest(path=video, description="#fyp"))
    assert res.ok is True
    assert res.backend == BACKEND_SESSION
    assert res.cookies is None
    assert any("daxili sessiya istifadə olunur @reeluser" in line for line in res.logs)
    assert any("re-encode olunmur" in line for line in res.logs)


def test_upload_expired_session_is_reported(video, monkeypatch):
    monkeypatch.setattr(session_mod, "is_logged_in", lambda: True)
    monkeypatch.setattr(session_mod, "session_info",
                        lambda: {"logged_in": True, "username": "",
                                 "expired": False, "path": video})
    monkeypatch.setattr(session_mod, "load_session", lambda: None)  # vanished
    monkeypatch.setattr(
        upload_mod, "_module_present", lambda name: name == "playwright")
    res = upload(UploadRequest(path=video))
    assert res.ok is False
    assert "Sessiya yenilənməlidir" in res.error
    assert "LOGIN TO TIKTOK" in res.error


def test_session_like_failure_gets_renew_hint(video, monkeypatch):
    (video.parent / "cookies.txt").write_text("netscape")
    monkeypatch.setattr(upload_mod, "app_dirs", lambda: [video.parent])
    monkeypatch.setattr(
        upload_mod, "available_backends", lambda: [(BACKEND_PACKAGE, True, "test")])

    def http_401(request, _v, _c, result, log):
        raise RuntimeError("server said 401 Unauthorized")

    monkeypatch.setitem(upload_mod._BACKEND_RUNNERS, BACKEND_PACKAGE, http_401)
    res = upload(UploadRequest(path=video))
    assert res.ok is False
    assert res.error.startswith("Sessiya yenilənməlidir")
    assert "401" in res.error


def test_upload_happy_path_logs_everything(video, monkeypatch):
    (video.parent / "cookies.txt").write_text("netscape")
    monkeypatch.setattr(upload_mod, "app_dirs", lambda: [video.parent])
    _backend_available(monkeypatch)
    seen = []
    res = upload(
        UploadRequest(path=video, description="#120fps"),
        log_callback=seen.append,
    )
    assert res.ok is True
    assert res.backend == BACKEND_PACKAGE
    assert res.url.startswith("https://www.tiktok.com")
    assert res.cookies == video.parent / "cookies.txt"
    assert any("backend işlədi" in line for line in res.logs)
    assert seen == res.logs          # GUI log_callback receives the same lines


def test_upload_network_error_does_not_raise(video, monkeypatch):
    (video.parent / "cookies.txt").write_text("netscape")
    monkeypatch.setattr(upload_mod, "app_dirs", lambda: [video.parent])
    monkeypatch.setattr(
        upload_mod, "available_backends", lambda: [(BACKEND_PACKAGE, True, "test")])
    monkeypatch.setitem(
        upload_mod._BACKEND_RUNNERS, BACKEND_PACKAGE,
        _fake_backend(error=ConnectionError("internet yoxdur")),
    )
    res = upload(UploadRequest(path=video))
    assert res.ok is False
    assert "internet yoxdur" in res.error
    assert any("gözlənilməz xəta" in line for line in res.logs)


def test_upload_requested_backend_unavailable(video, monkeypatch):
    (video.parent / "cookies.txt").write_text("netscape")
    monkeypatch.setattr(upload_mod, "app_dirs", lambda: [video.parent])
    res = upload(UploadRequest(path=video, backend="playwright"))
    assert res.ok is False
    assert "playwright" in res.error


# --------------------------------------------------------------------------- #
# CLI backend argv + exit codes
# --------------------------------------------------------------------------- #


def _use_cli(monkeypatch):
    monkeypatch.setattr(
        upload_mod, "available_backends",
        lambda: [(BACKEND_CLI, True, "/usr/bin/tiktok-uploader")])
    monkeypatch.setattr(upload_mod.shutil, "which",
                        lambda name: "/usr/bin/tiktok-uploader" if name == "tiktok-uploader" else None)


def test_cli_backend_builds_expected_argv(video, monkeypatch):
    (video.parent / "cookies.txt").write_text("netscape")
    monkeypatch.setattr(upload_mod, "app_dirs", lambda: [video.parent])
    _use_cli(monkeypatch)
    recorded = {}

    def fake_run(argv, **kwargs):
        recorded["argv"] = argv
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(upload_mod.subprocess, "run", fake_run)
    res = upload(UploadRequest(path=video, description="salam #fyp", headless=True))
    assert res.ok is True
    argv = recorded["argv"]
    assert argv[0] == "/usr/bin/tiktok-uploader"
    assert argv[1:3] == ["-v", str(video)]
    assert argv[3:5] == ["-d", "salam #fyp"]
    assert argv[5:7] == ["-c", str(video.parent / "cookies.txt")]
    assert "--headless" in argv


def test_cli_backend_nonzero_exit_is_an_error(video, monkeypatch):
    (video.parent / "cookies.txt").write_text("netscape")
    monkeypatch.setattr(upload_mod, "app_dirs", lambda: [video.parent])
    _use_cli(monkeypatch)
    monkeypatch.setattr(
        upload_mod.subprocess, "run",
        lambda argv, **kwargs: SimpleNamespace(
            returncode=2, stdout="", stderr="login failed\nsession expired\n"))
    res = upload(UploadRequest(path=video))
    assert res.ok is False
    assert "xəta kodu 2" in res.error
    assert "session expired" in res.error
    assert any("login failed" in line for line in res.logs)


# --------------------------------------------------------------------------- #
# UI wiring (headless parts)
# --------------------------------------------------------------------------- #


def test_uistate_upload_request_disabled_by_default(video):
    state = UIState()
    assert state.tiktok_enabled is False
    assert state.upload_request(video) is None


def test_uistate_upload_request_enabled(video):
    state = UIState(tiktok_enabled=True, tiktok_description="  #120fps #reelforge  ")
    req = state.upload_request(video)
    assert isinstance(req, UploadRequest)
    assert req.path == video
    assert req.description == "#120fps #reelforge"


def test_status_text_has_upload_phase():
    assert "TikTok" in status_text("upload")


def test_reelforge_facade_delegates(video, toolchain, monkeypatch):
    """ReelForge.upload() -> upload.upload() with the engine's log callback."""
    from reelforge import pipeline as pipeline_mod

    seen = {}

    def fake_upload(request, *, log_callback=None):
        seen["request"] = request
        seen["log_callback"] = log_callback
        return upload_mod.UploadResult(ok=True, backend="fake")

    monkeypatch.setattr(upload_mod, "upload", fake_upload)
    engine = pipeline_mod.ReelForge(str(toolchain.ffmpeg), str(toolchain.ffprobe))
    engine.log_callback = lambda _msg: None
    result = engine.upload(video, description="#test")
    assert result.ok is True
    assert seen["request"].path == video
    assert seen["request"].description == "#test"
    assert seen["log_callback"] is engine.log_callback
