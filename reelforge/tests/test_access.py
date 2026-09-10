"""Tests for the startup password gate (pure logic — no Tk needed)."""

from __future__ import annotations

from pathlib import Path

from reelforge import access
from reelforge.access import (
    MAX_ATTEMPTS,
    PASSWORD_SHA256,
    attempts_message,
    verify_password,
)


def test_correct_password_is_accepted():
    assert verify_password("husu1234") is True


def test_correct_password_with_surrounding_whitespace():
    assert verify_password("  husu1234\n") is True


def test_wrong_passwords_are_rejected():
    for bad in ("husu123", "husu12345", "HUSU1234", "Husu1234", "12345678",
                "password", "husu 1234", "husu1234!"):
        assert verify_password(bad) is False, bad


def test_empty_and_none_are_rejected():
    assert verify_password("") is False
    assert verify_password("   ") is False
    assert verify_password(None) is False


def test_non_string_input_does_not_crash():
    assert verify_password(12345678) is False


def test_plaintext_password_is_not_stored_in_source():
    """The digest lives in access.py — the plaintext must not."""
    source = Path(access.__file__).read_text(encoding="utf-8")
    assert "husu1234" not in source
    assert len(PASSWORD_SHA256) == 64


def test_attempts_messages():
    assert MAX_ATTEMPTS == 3
    assert "2 cəhd qalıb" in attempts_message(2)
    assert "Son cəhd" in attempts_message(1)
    assert "bağlanır" in attempts_message(0)
    assert "bağlanır" in attempts_message(-1)
