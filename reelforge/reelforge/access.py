"""Startup access control — pure logic, no Tk.

The Decoy window is protected by a local password gate
(:mod:`reelforge.gui.lock`).  This module holds the *only* secret-handling
code and is deliberately GUI-free so it can be unit-tested:

* the password is never stored in plaintext — only its SHA-256 digest;
* :func:`verify_password` strips surrounding whitespace and compares
  digests (``hmac.compare_digest`` keeps the comparison timing-stable).

The default password is the owner's; to change it, replace
:data:`PASSWORD_SHA256` with the SHA-256 digest of the new one — the
plaintext must never appear in this file (a test enforces that).
"""

from __future__ import annotations

import hashlib
import hmac

#: SHA-256 digest of the owner's startup password (plaintext is NOT here)
PASSWORD_SHA256 = (
    "283317b6198ae5dbfe4cfa565139e996e1f5bc6ff3fcc9b2b369c7559a52212f"
)

#: wrong entries allowed before the gate closes itself
MAX_ATTEMPTS = 3


def verify_password(candidate: object) -> bool:
    """True when ``candidate`` (after strip) matches the stored digest."""
    if candidate is None:
        return False
    text = str(candidate).strip()
    if not text:
        return False
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return hmac.compare_digest(digest, PASSWORD_SHA256)


def attempts_message(remaining: int) -> str:
    """What the gate shows after a wrong entry."""
    if remaining <= 0:
        return "Həddindən artıq yanlış cəhd — proqram bağlanır."
    if remaining == 1:
        return "Yanlış şifrə! Son cəhd."
    return f"Yanlış şifrə! {remaining} cəhd qalıb."
