"""GUI package (CustomTkinter).  Imported lazily so the backend works headless."""

from __future__ import annotations

__all__ = ["launch"]


def launch(*args, **kwargs) -> bool:  # pragma: no cover - thin re-export
    from .app import launch as _launch

    return _launch(*args, **kwargs)
