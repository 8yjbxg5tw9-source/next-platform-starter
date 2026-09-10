"""Cryptographic helpers: credential digests and short-lived session tokens.

Passwords and hardware fingerprints never leave this layer in plaintext:
the database stores SHA-256 digests only, and authenticated clients receive
an HMAC-signed bearer token with a limited lifetime.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from pathlib import Path
from typing import Optional

#: default lifetime of an issued session token (seconds)
TOKEN_TTL = 6 * 3600

_SECRET_FILE_ENV = "AKAI_SECRET_FILE"


def sha256_hex(text: str) -> str:
    """Stable UTF-8 SHA-256 digest used for passwords and HWIDs."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_secret(path: Optional[Path] = None) -> bytes:
    """Read (or create on first run) the server signing secret."""
    if path is None:
        env = os.environ.get(_SECRET_FILE_ENV, "").strip()
        path = Path(env) if env else Path(__file__).resolve().parent.parent / "secret.key"
    path = Path(path)
    if path.exists():
        return path.read_bytes()
    secret = os.urandom(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(secret)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return secret


def issue_token(secret: bytes, username: str, ttl: int = TOKEN_TTL) -> str:
    """Return ``payload.signature`` — a stateless, expiring session token."""
    payload = base64.urlsafe_b64encode(
        json.dumps({"u": username, "exp": int(time.time()) + ttl},
                   separators=(",", ":")).encode("utf-8")
    ).rstrip(b"=")
    signature = hmac.new(secret, payload, hashlib.sha256).hexdigest()
    return f"{payload.decode('ascii')}.{signature}"


def verify_token(secret: bytes, token: str) -> Optional[dict]:
    """Decode a token; ``None`` when the signature or expiry is invalid."""
    try:
        payload_b64, signature = token.rsplit(".", 1)
        expected = hmac.new(secret, payload_b64.encode("ascii"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            return None
        padding = "=" * (-len(payload_b64) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload_b64 + padding))
        if int(data.get("exp", 0)) < int(time.time()):
            return None
        return data
    except (ValueError, KeyError, TypeError):
        return None
