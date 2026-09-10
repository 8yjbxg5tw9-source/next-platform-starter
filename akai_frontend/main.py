"""Akai entry point.

Boot order: logging (so nothing is lost) -> login window -> main panel.
``tkinter.TkVersion`` is checked up front to give a readable error on
stripped-down systems instead of a stack trace.
"""

from __future__ import annotations

import sys

import customtkinter as ctk

# Avtomatik ekran miqyaslamasını tam ədədə sabitləyir (DPI scaling xətalarının qarşısını alır)
try:
    ctk.deactivate_automatic_dpi_awareness()
except Exception:
    pass

from akai.config import APP_NAME, APP_VERSION, log, setup_logging


def main() -> int:
    setup_logging()
    log().info("%s %s starting (python %s)", APP_NAME, APP_VERSION,
               sys.version.split()[0])
    try:
        import tkinter as tk

        if tk.TkVersion < 8.6:  # pragma: no cover - ancient runtime
            raise RuntimeError("Tkinter 8.6+ tələb olunur")
    except (ImportError, RuntimeError) as exc:
        message = f"Python/Tkinter quraşdırılmayıb: {exc}"
        print(message, file=sys.stderr)
        log().error(message)
        return 1

    from akai.ui_login import LoginWindow
    from akai.ui_main import MainWindow

    holder: dict = {}

    def on_success(session: dict) -> None:
        holder["session"] = session

    login = LoginWindow(on_success=on_success)
    login.mainloop()
    if "session" not in holder:
        return 1

    app = MainWindow(session=holder["session"])
    app.mainloop()
    log().info("clean exit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
