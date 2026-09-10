"""HWID format, determinism and fallback behaviour."""

from __future__ import annotations

import re

from akai.hwid import compute_hwid

PATTERN = re.compile(r"AKAI-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}")


def test_hwid_format():
    assert PATTERN.fullmatch(compute_hwid({"board": "B1", "cpu": "C1"}))


def test_hwid_is_deterministic():
    ids = {"board": "ASUS-X570", "cpu": "BFEBFBFF000806F1"}
    assert compute_hwid(ids) == compute_hwid(ids)


def test_different_hardware_yields_different_hwid():
    assert (compute_hwid({"board": "A", "cpu": "C"})
            != compute_hwid({"board": "A", "cpu": "D"}))


def test_key_order_does_not_matter():
    assert (compute_hwid({"board": "A", "cpu": "C"})
            == compute_hwid({"cpu": "C", "board": "A"}))


def test_empty_identifiers_still_produce_valid_code():
    assert PATTERN.fullmatch(compute_hwid({}))


def test_hwid_never_contains_plaintext_identifiers():
    hwid = compute_hwid({"board": "SECRET-SERIAL", "cpu": "SECRET-CPU"})
    assert "SECRET" not in hwid
