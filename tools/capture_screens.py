#!/usr/bin/env python3
"""
Capture the documentation screenshots that HUMAN_TESTING.html embeds.

WHY THIS IS A SCRIPT AND NOT A MANUAL CHORE
    The screenshots are the only part of the testing document that cannot be
    checked by the test suite, so they are the part that silently goes stale.
    They already had: the tab shots predated the status bar's "sampler RAM"
    relabel and the pattern view's Clear/Copy buttons, so the document showed a
    build that no longer existed. Regenerating is now one command, which is the
    only version of "keep them current" that survives contact with a deadline.

    Run it after any UI change that alters what a tab looks like:

        QT_QPA_PLATFORM=offscreen PYTHONPATH="$PWD" python3 tools/capture_screens.py

    Offscreen is deliberate: it needs no display, so it works over SSH and in
    CI. Qt prints a "missing font family Sans Serif" warning under offscreen
    only; the app itself resolves fonts properly under cocoa.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

#: The bank the shots are taken against. It carries real songs, so the Song tab
#: shows a populated chain rather than 64 identical defaults.
DEFAULT_BANK = "corpus/Chronic-Interactive-song.esx"
DEFAULT_OUT = "deploy/screens"
WINDOW = (1300, 800)

#: Tab label -> output filename, numbered as HUMAN_TESTING.html refers to them.
TAB_SHOTS = {
    "Bank": "tab_1_bank.png",
    "Staging": "tab_2_staging.png",
    "Pattern": "tab_3_pattern.png",
    "Motion": "tab_4_motion.png",
    "Song": "tab_5_song.png",
    "Global": "tab_6_global.png",
}


# O(b + v) time, O(b + v) space — b = bytes of the bank opened; v = views in the window (shots are a fixed 6 tabs + 11 wizard pages at 1300x800)
def capture(bank_path: str, out_dir: str, *, wizard: bool = True) -> list[str]:
    """Write one PNG per tab (and per wizard page) and return the paths."""
    from PySide6.QtWidgets import QApplication

    from ui.main_window import MainWindow
    from ui.theme import apply as apply_theme

    app = QApplication.instance() or QApplication(["capture"])
    apply_theme(app)
    window = MainWindow()
    window.resize(*WINDOW)
    if not window.open_path(bank_path):
        raise SystemExit(f"could not open {bank_path}")

    written = []
    # Tab label -> index, built once rather than list.index() per shot.
    # O(v) time, O(v) space — v = views (tabs) in the main window
    tab_index = {label: i for i, label in enumerate(window.views)}
    # O(t) time, O(t) space — t = 6 tab shots in TAB_SHOTS, each a fixed 1300x800 grab
    for label, filename in TAB_SHOTS.items():
        window.tabs.setCurrentIndex(tab_index[label])
        if label == "Song":
            # Select a song with a real chain; song 1 is the populated one.
            window.song_view.list.setCurrentRow(0)
        app.processEvents()
        path = os.path.join(out_dir, filename)
        window.grab().save(path)
        written.append(path)

    if wizard:
        written += _capture_wizard(window, app, out_dir)

    # The captures dirty nothing, but constructing views can set the flag;
    # clear it so closing does not raise an unsaved-changes prompt.
    window.session._dirty = False
    window.close()
    return written


# O(w) time, O(w) space — w = wizard pages, each a fixed 1300x800 grab
def _capture_wizard(window, app, out_dir: str) -> list[str]:
    """One shot per wizard page, walked in order with every page skipped.

    Every page is skippable by design (TDD §09), so the walk never needs to
    supply input — which is what makes the capture reproducible.
    """
    wizard = window.open_wizard()
    wizard.resize(*WINDOW)
    written = []
    # O(w) time, O(w) space — w = wizard pages
    for number, page_id in enumerate(wizard.pageIds(), start=1):
        wizard.setStartId(page_id)
        wizard.restart()
        app.processEvents()
        path = os.path.join(out_dir, f"wizard_{number:02d}.png")
        wizard.grab().save(path)
        written.append(path)
    wizard.close()
    return written


# O(b + v) time, O(b + v) space — b = bytes of the bank opened; v = views in the window (see capture)
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bank", default=DEFAULT_BANK)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument(
        "--no-wizard", action="store_true", help="tabs only, skip the 11 pages"
    )
    args = parser.parse_args(argv)

    os.makedirs(args.out, exist_ok=True)
    # O(b + v) time, O(b + v) space — b = bank bytes; v = window views (the print loop is over the fixed shot list)
    for path in capture(args.bank, args.out, wizard=not args.no_wizard):
        print(f"  wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
