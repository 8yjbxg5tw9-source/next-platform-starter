"""GUI font sizes must be whole numbers.

Tk's font engine only accepts integer point sizes; a float like 13.5
survives pyflakes and py_compile but explodes at runtime with
``TclError: expected integer but got "-13.5"`` the moment the window is
built.  This test parses the real UI sources and fails on any fractional
size passed to ``ctk.CTkFont``.
"""

from __future__ import annotations

import ast
from pathlib import Path

UI_FILES = [Path(__file__).resolve().parents[1] / "akai" / name
            for name in ("ui_login.py", "ui_main.py")]


def _ctkfont_sizes(tree: ast.Module):
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "CTkFont"
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)):
            yield node.args[1].value, node.lineno


def test_all_ctkfont_sizes_are_integers():
    for path in UI_FILES:
        assert path.exists(), path
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for size, line in _ctkfont_sizes(tree):
            assert isinstance(size, int) and not isinstance(size, bool), (
                f"{path.name}:{line} — CTkFont size {size} must be an "
                f"integer (Tk raises TclError on floats)")
