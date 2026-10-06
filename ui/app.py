"""Application entry point: QApplication + theme + MainWindow.

FLOW
    main() → QApplication → apply_theme() → MainWindow().show() → app.exec()

SMOKE-TEST MODE (packaging only)
    With ESX_SMOKE_TEST=1 set, main() builds the whole window, prints which
    audio/MIDI backends it found, and exits 0 instead of entering the event
    loop. `packaging/macos/build_app.sh` runs the frozen .app this way so a
    module or data file PyInstaller missed fails the BUILD, not the user's
    first double-click. Unset (the normal case), nothing here changes.
"""

from __future__ import annotations

import os
import sys

from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow
from ui.theme import apply as apply_theme


# O(1) time, O(1) space — b = 4 backend lines printed (fixed)
def _report_backends() -> None:
    """Print what the (possibly frozen) app can do — read by build_app.sh's log."""
    from audio.factory import detect_capabilities
    from midi.factory import describe

    caps = detect_capabilities()
    print("smoke: any-format import:", caps.can_convert_any_format)
    print("smoke: key detection:   ", caps.can_detect_key)
    print("smoke: note detection:  ", caps.can_detect_note)
    print("smoke:", describe())


# O(1) time, O(1) space — w = 1 window built, wiring only
def main(argv: list[str] | None = None) -> int:
    args = sys.argv if argv is None else argv
    app = QApplication.instance() or QApplication(args)
    apply_theme(app)
    win = MainWindow()
    win.show()
    if os.environ.get("ESX_SMOKE_TEST"):
        _report_backends()
        return 0
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
