"""Network client: payload shape + every failure maps to a clean message."""

from __future__ import annotations

import io
import json
import socket
import urllib.error
import urllib.request

import pytest

from akai.net import OFFLINE_MESSAGE, AuthClient, LicenseError, sha256_hex

HWID = "AKAI-98F2-41A7-B800"


class _FakeResponse:
    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self) -> bytes:
        return self._body


def test_login_payload_sends_digest_not_plaintext(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse({"ok": True, "token": "t1", "username": "demo"})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    result = AuthClient("http://srv:8000").login("demo", "pin123", HWID)

    assert result["token"] == "t1"
    assert captured["body"]["password_hash"] == sha256_hex("pin123")
    assert "pin123" not in json.dumps(captured["body"])
    assert captured["body"]["hwid"] == HWID
    assert captured["body"]["username"] == "demo"


def _http_error(monkeypatch, code: int, detail: str) -> None:
    body = io.BytesIO(json.dumps({"detail": detail}).encode("utf-8"))

    def raise_error(request, timeout=None):
        raise urllib.error.HTTPError("http://srv/api/v1/login", code,
                                     "err", {}, body)

    monkeypatch.setattr(urllib.request, "urlopen", raise_error)


def test_hwid_mismatch_message_is_surfaced_verbatim(monkeypatch):
    _http_error(monkeypatch, 403, "Bu abunəlik başqa cihazda aktivdir!")
    with pytest.raises(LicenseError) as info:
        AuthClient("http://srv:8000").login("demo", "pin", HWID)
    assert str(info.value) == "Bu abunəlik başqa cihazda aktivdir!"


def test_expired_subscription_message(monkeypatch):
    _http_error(monkeypatch, 403, "Abunəlik müddəti bitmişdir.")
    with pytest.raises(LicenseError) as info:
        AuthClient("http://srv:8000").login("demo", "pin", HWID)
    assert str(info.value) == "Abunəlik müddəti bitmişdir."


def test_bad_credentials_message(monkeypatch):
    _http_error(monkeypatch, 401, "İstifadəçi adı və ya şifrə yanlışdır.")
    with pytest.raises(LicenseError) as info:
        AuthClient("http://srv:8000").login("demo", "x", HWID)
    assert "yanlışdır" in str(info.value)


def test_http_error_without_json_stays_readable(monkeypatch):
    body = io.BytesIO(b"<html>gateway</html>")

    def raise_error(request, timeout=None):
        raise urllib.error.HTTPError("u", 502, "bad gw", {}, body)

    monkeypatch.setattr(urllib.request, "urlopen", raise_error)
    with pytest.raises(LicenseError) as info:
        AuthClient("http://srv:8000").login("demo", "x", HWID)
    assert "502" in str(info.value)


@pytest.mark.parametrize("exc", [
    urllib.error.URLError("connection refused"),
    socket.timeout("timed out"),
    ConnectionResetError("reset"),
    OSError("network unreachable"),
])
def test_transport_failures_map_to_offline_message(monkeypatch, exc):
    def raise_error(request, timeout=None):
        raise exc

    monkeypatch.setattr(urllib.request, "urlopen", raise_error)
    with pytest.raises(LicenseError) as info:
        AuthClient("http://srv:8000").login("demo", "x", HWID)
    assert str(info.value) == OFFLINE_MESSAGE
    assert str(info.value) == "Sistem xətası: Lisenziya doğrulana bilmədi"


def test_verify_never_raises(monkeypatch):
    def raise_error(request, timeout=None):
        raise urllib.error.URLError("down")

    monkeypatch.setattr(urllib.request, "urlopen", raise_error)
    assert AuthClient("http://srv:8000").verify("tok") is False


def test_server_url_override(tmp_path, monkeypatch):
    (tmp_path / "server.txt").write_text("https://lic.example.com/",
                                         encoding="utf-8")
    monkeypatch.setattr("akai.config.BASE_DIR", tmp_path)
    assert AuthClient().base_url == "https://lic.example.com"
