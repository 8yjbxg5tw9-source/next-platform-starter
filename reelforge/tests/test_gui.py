"""GUI-layer tests that do not need a display.

The window itself needs Tk; these cover the pure parts (drag-and-drop payload
parsing, theme tokens) and verify that the GUI module at least imports when
CustomTkinter/Tk are installed.
"""

from __future__ import annotations

import importlib.util

import pytest

from reelforge.gui import dnd, theme
from reelforge.models import ensure_video_files


def test_dnd_payload_with_braced_paths():
    """tkinterdnd2 wraps paths containing spaces in braces."""
    assert dnd.parse_dnd_paths("{C:/my dir/a.mp4} /tmp/b.mp4") == [
        "C:/my dir/a.mp4",
        "/tmp/b.mp4",
    ]


def test_dnd_payload_plain_and_repeated_spaces():
    assert dnd.parse_dnd_paths("/a/1.mp4") == ["/a/1.mp4"]
    assert dnd.parse_dnd_paths("  /a/1.mp4    /b/2.mp4  ") == ["/a/1.mp4", "/b/2.mp4"]
    assert dnd.parse_dnd_paths("") == []


def test_dnd_payload_unterminated_brace_does_not_crash():
    assert dnd.parse_dnd_paths("{/tmp/x.mp4") == ["/tmp/x.mp4"]


def test_dnd_payload_multiple_braces():
    assert dnd.parse_dnd_paths("{/tmp/a b/1.mp4} {/tmp/c d/2.mov}") == [
        "/tmp/a b/1.mp4",
        "/tmp/c d/2.mov",
    ]


def test_ensure_video_files_strips_dnd_braces(tmp_path):
    video = tmp_path / "my clip.mp4"
    video.write_bytes(b"x")
    other = tmp_path / "notes.txt"
    other.write_text("hi")
    picked = ensure_video_files([f"{{{video}}}", str(other), "/nope/missing.mp4"])
    assert picked == [video]


def test_theme_tokens_are_complete():
    for key in ("bg", "surface", "text", "accent", "accent_2", "error"):
        assert theme.PALETTE[key].startswith("#")
    assert theme.APPEARANCE_MODE == "dark"
    for name in ("title", "h2", "body", "small", "mono"):
        family, size = theme.FONTS[name][:2]
        assert isinstance(family, str) and size > 0


@pytest.mark.skipif(
    importlib.util.find_spec("tkinter") is None
    or importlib.util.find_spec("customtkinter") is None,
    reason="tkinter / customtkinter quraşdırılmayıb",
)
def test_gui_module_imports():
    import reelforge.gui.app as app_module

    assert hasattr(app_module, "launch")
    assert hasattr(app_module, "ReelForgeApp")
