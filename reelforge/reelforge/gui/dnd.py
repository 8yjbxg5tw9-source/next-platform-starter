"""Optional drag-and-drop support.

``tkinterdnd2`` is an optional extra (it ships a patched Tk).  When it is not
installed the GUI still works — the drop zone turns into a plain "click to
browse" panel, so a missing dependency can never make the app unusable.
"""

from __future__ import annotations

from typing import Callable, List

DND_AVAILABLE = False
_TkinterDnD = None
DND_FILES = None

try:  # pragma: no cover - depends on the local environment
    from tkinterdnd2 import DND_FILES as _DND_FILES  # type: ignore
    from tkinterdnd2 import TkinterDnD as _TkinterDnD  # type: ignore

    DND_AVAILABLE = True
    DND_FILES = _DND_FILES
except Exception:  # pragma: no cover
    DND_AVAILABLE = False


def enable_on(root) -> bool:
    """Turn an existing ``ctk.CTk`` window into a drop target.

    This is the recipe CustomTkinter documents for TkinterDnD: the Tk root is
    a CTk window, and the DnD extension is loaded onto it afterwards, so the
    process keeps a single root and CTk's DPI scaling stays intact.
    """
    if not DND_AVAILABLE or _TkinterDnD is None:  # pragma: no cover
        return False
    try:  # pragma: no cover - requires tkinterdnd2
        root.TkdndVersion = _TkinterDnD._require(root)
        return True
    except Exception:
        return False


def register_drop_target(widget, callback: Callable[[List[str]], None]) -> bool:
    """Make ``widget`` accept dropped files.  Returns ``True`` on success."""
    if not DND_AVAILABLE or DND_FILES is None:  # pragma: no cover
        return False
    try:  # pragma: no cover - requires tkinterdnd2
        widget.drop_target_register(DND_FILES)

        def _handler(event) -> None:
            callback(parse_dnd_paths(event.data))

        widget.dnd_bind("<<Drop>>", _handler)
        return True
    except Exception:
        return False


def parse_dnd_paths(data: str) -> List[str]:
    """``{C:/my dir/a.mp4} /tmp/b.mp4`` -> ``['C:/my dir/a.mp4', '/tmp/b.mp4']``

    tkinterdnd2 wraps every path that contains a space in braces; a naive
    ``split()`` would shred those paths apart.
    """
    out: List[str] = []
    text = str(data or "").strip()
    i = 0
    while i < len(text):
        char = text[i]
        if char.isspace():
            i += 1
            continue
        if char == "{":
            end = text.find("}", i + 1)
            if end == -1:
                out.append(text[i + 1:])
                break
            out.append(text[i + 1:end])
            i = end + 1
            continue
        end = i
        while end < len(text) and not text[end].isspace():
            end += 1
        out.append(text[i:end])
        i = end
    return [p for p in out if p]
