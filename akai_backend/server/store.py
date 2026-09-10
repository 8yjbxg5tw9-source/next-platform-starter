"""Subscription store backed by ``users.json``.

The file is the single source of truth managed by the administrator.  All
reads/writes go through a lock so concurrent logins cannot corrupt it, and
sensitive fields (password, HWID) are stored as SHA-256 digests.
"""

from __future__ import annotations

import datetime as dt
import json
import threading
from pathlib import Path
from typing import Dict, Optional

from .security import sha256_hex

#: machine-readable reasons returned by :meth:`UserStore.check_login`
BAD_CREDENTIALS = "bad_credentials"
HWID_MISMATCH = "hwid_mismatch"
SUBSCRIPTION_EXPIRED = "subscription_expired"
ACCOUNT_DISABLED = "account_disabled"


def _parse_date(value: Optional[str]) -> Optional[dt.date]:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(str(value))
    except ValueError:
        return None


class UserStore:
    """Thread-safe accessor for the subscriber database."""

    def __init__(self, path: Path):
        self._path = Path(path)
        self._lock = threading.RLock()
        self._users: Dict[str, dict] = {}
        self.reload()

    # -- persistence --------------------------------------------------------
    def reload(self) -> None:
        with self._lock:
            if not self._path.exists():
                self._users = {}
                return
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            self._users = {
                str(entry.get("username", "")).lower(): entry
                for entry in raw.get("users", [])
                if entry.get("username")
            }

    def _dump(self) -> None:
        payload = {"users": list(self._users.values())}
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(self._path)

    # -- queries ------------------------------------------------------------
    def get(self, username: str) -> Optional[dict]:
        with self._lock:
            return self._users.get(str(username).lower())

    def check_login(self, username: str, password_hash: str,
                    hwid_hash: str) -> tuple[bool, str, dict]:
        """Validate credentials, device lock and subscription window.

        Returns ``(ok, reason, record)``; ``reason`` is empty on success.
        A record whose ``hwid`` field is still empty gets bound to the
        calling device on first successful login.
        """
        with self._lock:
            record = self._users.get(str(username).lower())
            if record is None or not str(record.get("password", "")):
                return False, BAD_CREDENTIALS, {}
            if not hmac_equal(str(record["password"]), password_hash):
                return False, BAD_CREDENTIALS, {}
            if str(record.get("status", "active")).lower() not in ("active", "aktiv"):
                return False, ACCOUNT_DISABLED, {}
            expires = _parse_date(record.get("expires_at"))
            if expires is not None and expires < dt.date.today():
                return False, SUBSCRIPTION_EXPIRED, {}

            stored_hwid = str(record.get("hwid", "") or "")
            if stored_hwid:
                if not hmac_equal(stored_hwid, hwid_hash):
                    return False, HWID_MISMATCH, {}
            else:
                record["hwid"] = hwid_hash   # first login binds the device
                self._dump()
            return True, "", record

    def add_user(self, username: str, password: str, hwid: str = "",
                 days: Optional[int] = None, status: str = "active") -> dict:
        """Admin helper: store digests only, never plaintext secrets."""
        with self._lock:
            expires: Optional[str] = None
            if days:
                expires = (dt.date.today() + dt.timedelta(days=int(days))).isoformat()
            record = {
                "username": str(username).lower(),
                "password": sha256_hex(password),
                "hwid": sha256_hex(hwid) if hwid else "",
                "status": status,
                "expires_at": expires,
            }
            self._users[record["username"]] = record
            self._dump()
            return record

    def renew(self, username: str, days: Optional[int] = None) -> Optional[dict]:
        """Admin helper: change only the expiry date of an existing user.

        Password and bound HWID stay untouched, so a running subscription
        can be extended (or made unlimited with ``days=0``) without forcing
        the customer to re-bind their device.
        """
        with self._lock:
            record = self._users.get(str(username).lower())
            if record is None:
                return None
            record["expires_at"] = (
                (dt.date.today() + dt.timedelta(days=int(days))).isoformat()
                if days else None
            )
            self._dump()
            return record

    def list_users(self) -> list:
        with self._lock:
            return [
                {
                    "username": rec.get("username"),
                    "hwid_bound": bool(rec.get("hwid")),
                    "status": rec.get("status"),
                    "expires_at": rec.get("expires_at"),
                }
                for rec in self._users.values()
            ]


def hmac_equal(a: str, b: str) -> bool:
    """Constant-time digest comparison."""
    import hmac as _hmac
    return _hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
