"""``python -m reelforge`` -> Decoy-style GUI, with a CLI fallback.

The GUI needs a display and Tk; when neither is available (SSH session, CI
container, macOS without python-tk) we fall back to the headless CLI so the
package is still usable as ``python -m reelforge clip.mp4 -p safe``.

``python -m reelforge --advanced`` opens the 3-column studio window instead
(``reelforge.gui.app``), which exposes every option the CLI has.
"""

from __future__ import annotations

import sys


def _launch_gui(advanced: bool, args: list) -> int:
    module = "reelforge.gui.app" if advanced else "reelforge.gui.decoy"
    try:
        from importlib import import_module

        launch = import_module(module).launch
    except Exception as exc:  # no Tk / no customtkinter / no DISPLAY
        print(
            "GUI açıla bilmədi: "
            f"{type(exc).__name__}: {exc}\n"
            "CLI rejiminə keçilir. İstifadə: python -m reelforge.cli --help",
            file=sys.stderr,
        )
        from .cli import main as cli_main

        return cli_main(["--diagnostics"])
    return 0 if launch(*args) else 1


def main() -> int:
    argv = list(sys.argv[1:])

    if "--advanced" in argv:
        argv.remove("--advanced")
        return _launch_gui(True, argv)

    if not argv:
        return _launch_gui(False, [])

    from .cli import main as cli_main

    return cli_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
