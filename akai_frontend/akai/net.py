"""License server client (standard library only — small .exe footprint).

The password never travels in plaintext: its SHA-256 digest is sent and the
server compares digests.  All transport failures surface as
:class:`LicenseError` with a user-readable Azerbaijani message, so the GUI
can show a dialog instead of crashing.
"""

from __future__ import annotations

import hashlib
import json
import socket
import urllib.error
import urllib.request
from typing import Any, Dict

from .config import log, server_url

OFFLINE_MESSAGE = "Sistem xətası: Lisenziya doğrulana bilmədi"


class LicenseError(RuntimeError):
    """User-facing licensing / transport problem."""


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class AuthClient:
    def __init__(self, base_url: str | None = None, timeout: float = 8.0):
        self.base_url = (base_url or server_url()).rstrip("/")
        self.timeout = timeout

    # -- plumbing -----------------------------------------------------------
    def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "User-Agent": "AkaiClient/1.0"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = json.loads(exc.read().decode("utf-8")).get("detail", "")
            except (OSError, ValueError):
                detail = ""
            raise LicenseError(detail or f"Server xətası: HTTP {exc.code}") from exc
        except (urllib.error.URLError, socket.timeout, ConnectionError, OSError) as exc:
            log().warning("Lisenziya serverinə çatmaq olmadı: %s", exc)
            raise LicenseError(OFFLINE_MESSAGE) from exc

    # -- public API ---------------------------------------------------------
    def login(self, username: str, password: str, hwid: str) -> Dict[str, Any]:
        """Returns the server payload (``token``, ``expires_at``) on success."""
        return self._post("/api/v1/login", {
            "username": username,
            "password_hash": sha256_hex(password),
            "hwid": hwid,
        })

    def verify(self, token: str) -> bool:
        request = urllib.request.Request(
            f"{self.base_url}/api/v1/verify",
            headers={"Authorization": f"Bearer {token}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                return bool(json.loads(resp.read().decode("utf-8")).get("ok"))
        except (urllib.error.URLError, socket.timeout, ConnectionError,
                OSError, ValueError):
            return False
