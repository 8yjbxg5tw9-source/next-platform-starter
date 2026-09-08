"""``python -m reelforge`` -> GUI, with an automatic fallback to the CLI.

The GUI needs a display and Tk; when neither is available (SSH session, CI
container, macOS without python-tk) we fall back to the headless CLI so the
package is still usable as ``python -m reelforge clip.mp4 -p safe``.
"""

from __future__ import annotations

import sys


def main() -> int:
    args = sys.argv[1:]
    if not args:
        try:
            from .gui.app import launch
        except Exception as exc:  # no Tk / no customtkinter / no DISPLAY
            print(
                "GUI açıla bilmədi: "
                f"{type(exc).__name__}: {exc}\n"
                "CLI rejiminə keçilir. İstifadə: python -m reelforge.cli --help",
                file=sys.stderr,
            )
            from .cli import main as cli_main

            return cli_main(["--diagnostics"])
        return 0 if launch() else 1

    from .cli import main as cli_main

    return cli_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
