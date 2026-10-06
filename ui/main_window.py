"""
ui.main_window — the application shell: menus, tabs, status, session (TDD §10.1).

WF6 replaced the placeholder panes with the real views. The shell is the wiring
layer and nothing else: it owns the BankSession (the single place codec/ is
imported), and on every bank change it hands the live core.Bank to each view's
`bind_bank`. Views render and emit intent; the shell turns intent into session
calls and chrome refreshes.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QTabWidget,
)

from codec.errors import CodecError
from ui.motion.editor import MotionEditor
from ui.session import BankSession
from ui.theme import PALETTE
from ui.views import BankView, GlobalView, PatternView, SongView, StagingView
from ui.widgets.budget_meter import BudgetMeter
from ui.wizard import SetupWizard
from workspace import card

APP_TITLE = "ESX Bank Studio"

TABS = (
    ("Bank", "384 sample slots and the usage meter."),
    ("Staging", "Drop files here to convert, analyse, and name them."),
    ("Pattern", "Parts, sequence grid, and FX units."),
    ("Motion", "Drawable motion-sequence canvas."),
    ("Song", "Song arrangement and events."),
    ("Global", "Bank-wide parameters and MIDI."),
)


class MainWindow(QMainWindow):
    bankChanged = Signal()

    # O(t + e + s + m + P·c + G·g) time, O(t + e + s + m + P·c + G·g) space — t = motion targets MotionEditor loads (313 shipped); e = entries swept under the staging temp root; s = sample slots (384); m = PCM bytes, copied only if pcm_used_bytes() raises; P = patterns in the bank (256 on the ESX-1); c = 4,280 bytes per pattern chunk; G = songs (64); g = 528 bytes per song block
    def __init__(self, session: BankSession | None = None, parent=None):
        super().__init__(parent)
        self.session = session or BankSession()
        self.setWindowTitle(APP_TITLE)
        self.resize(1100, 720)
        self._wizard: SetupWizard | None = None
        self._build_tabs()
        self._build_menus()
        self._build_status()
        self.bankChanged.connect(self._bind_views)
        self._refresh_chrome()
        self._bind_views()

    # -- construction -------------------------------------------------------
    # O(t + e) time, O(t + e) space — t = motion targets MotionEditor loads (313 shipped); e = entries swept under the staging temp root
    def _build_tabs(self) -> None:
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.bank_view = BankView()
        self.staging_view = StagingView()
        self.pattern_view = PatternView()
        self.motion_editor = MotionEditor()
        self.song_view = SongView()
        self.global_view = GlobalView()
        self.views = {
            "Bank": self.bank_view,
            "Staging": self.staging_view,
            "Pattern": self.pattern_view,
            "Motion": self.motion_editor,
            "Song": self.song_view,
            "Global": self.global_view,
        }
        # O(k) time, O(1) space — k = 6 tabs
        for name, _hint in TABS:
            self.tabs.addTab(self.views[name], name)
        self.setCentralWidget(self.tabs)

        # intent -> session. Widgets never touch the session themselves.
        self.pattern_view.patternSelected.connect(self._on_pattern_selected)
        self.pattern_view.patternEdited.connect(self._on_bank_edited)
        self.staging_view.samplesChanged.connect(self._on_staging_changed)
        self.bank_view.sampleEdited.connect(self._on_bank_edited)
        self.song_view.songEdited.connect(self._on_bank_edited)
        self.global_view.globalsEdited.connect(self._on_bank_edited)

    # O(k) time, O(k) space — k = 6 tabs (one View-menu action each)
    def _build_menus(self) -> None:
        # Keep Python references to the menus: PySide does not own the wrappers
        # returned by addMenu(), so a garbage-collected QMenu wrapper makes the
        # menu unreachable from code even while it still renders.
        self.menus: dict[str, object] = {}
        file_menu = self.menuBar().addMenu("&File")
        self.menus["File"] = file_menu
        self._act("New bank", file_menu, self._on_new, QKeySequence.StandardKey.New)
        self._act("Open…", file_menu, self._on_open, QKeySequence.StandardKey.Open)
        self._act("Save", file_menu, self._on_save, QKeySequence.StandardKey.Save)
        self._act(
            "Save As…", file_menu, self._on_save_as, QKeySequence.StandardKey.SaveAs
        )
        file_menu.addSeparator()
        self._act("Guided setup…", file_menu, self.open_wizard)
        self._act("Card overview…", file_menu, self.show_card_overview)
        file_menu.addSeparator()
        self._act("Quit", file_menu, self.close, QKeySequence.StandardKey.Quit)

        edit_menu = self.menuBar().addMenu("&Edit")
        self.menus["Edit"] = edit_menu
        self._act("Clear staging", edit_menu, self._on_clear_staging)

        view_menu = self.menuBar().addMenu("&View")
        self.menus["View"] = view_menu
        # O(k) time, O(k) space — k = 6 tabs
        for i, (name, _) in enumerate(TABS):
            act = QAction(name, self)
            act.setShortcut(QKeySequence(f"Ctrl+{i + 1}"))
            act.triggered.connect(
                lambda _checked=False, idx=i: self.tabs.setCurrentIndex(idx)
            )
            view_menu.addAction(act)

        help_menu = self.menuBar().addMenu("&Help")
        self.menus["Help"] = help_menu
        self._act("About", help_menu, self._on_about)

    # O(1) time, O(1) space
    def _act(self, text, menu, slot, shortcut=None) -> QAction:
        act = QAction(text, self)
        if shortcut is not None:
            act.setShortcut(shortcut)
        act.triggered.connect(slot)
        menu.addAction(act)
        return act

    # O(1) time, O(1) space
    def _build_status(self) -> None:
        self._path_label = QLabel("no bank")
        self._path_label.setProperty("role", "muted")
        self._dirty_label = QLabel("")
        self._dirty_label.setStyleSheet(f"color: {PALETTE.amber};")
        self.meter = BudgetMeter()
        self.meter.setMaximumWidth(320)
        self.statusBar().addWidget(self._path_label, 1)
        self.statusBar().addPermanentWidget(self._dirty_label)
        self.statusBar().addPermanentWidget(self.meter)

    # -- binding ------------------------------------------------------------
    # O(m) time, O(m) space — m = PCM bytes, copied only on BankSession.pcm_used()'s fallback path (the normal path is constant)
    def _refresh_chrome(self) -> None:
        path = self.session.path
        name = (
            os.path.basename(path)
            if path
            else ("untitled.esx" if self.session.is_open else "no bank")
        )
        dirty = "•" if self.session.dirty else ""
        self.setWindowTitle(f"{APP_TITLE} — {name}{dirty}")
        self._path_label.setText(path or name)
        self._dirty_label.setText("modified" if self.session.dirty else "")
        self.meter.set_used(self.session.pcm_used())

    # O(s + m + P·c + G·g) time, O(s + m + P·c + G·g) space — s = sample slots (384); m = PCM bytes, copied only if pcm_used_bytes() raises; P = patterns in the bank (256 on the ESX-1); c = 4,280 bytes per pattern chunk; G = songs (64); g = 528 bytes per song block
    def _bind_views(self) -> None:
        """Hand the live bank to every view, then re-bind the motion editor."""
        bank = self.session.bank
        self.bank_view.bind_bank(bank)
        self.pattern_view.bind_bank(bank)
        self.song_view.bind_bank(bank)
        self.global_view.bind_bank(bank)
        self._bind_motion()

    # O(P + k) time, O(P) space — P = patterns in the bank (tuple copy); k = 24 motion slots bound
    def _bind_motion(self) -> None:
        bank = self.session.bank
        if bank is None:
            return
        patterns = bank.patterns()
        if patterns:
            index = min(max(self.pattern_view.current_index, 0), len(patterns) - 1)
            self.motion_editor.bind_pattern(patterns[index])

    # -- intent from the views ---------------------------------------------
    # O(P + k) time, O(P) space — P = patterns in the bank (tuple copy); k = 24 motion slots bound
    def _on_pattern_selected(self, row: int) -> None:
        bank = self.session.bank
        if bank is None:
            return
        patterns = bank.patterns()
        if 0 <= row < len(patterns):
            self.motion_editor.bind_pattern(patterns[row])

    # O(m) time, O(m) space — m = PCM bytes, copied only on pcm_used()'s fallback path (see _refresh_chrome)
    def _on_bank_edited(self) -> None:
        """A view mutated the bank (pattern rename, …)."""
        self.session.mark_dirty()
        self._refresh_chrome()

    # O(m) time, O(m) space — m = PCM bytes, copied only on pcm_used()'s fallback path (see _refresh_chrome)
    def _on_staging_changed(self) -> None:
        self.session.mark_dirty()
        self._refresh_chrome()

    # O(f) time, O(1) space — f = converted files removed from the staging session dir
    def _on_clear_staging(self) -> None:
        self.staging_view.clear_staging()

    # -- menu actions -------------------------------------------------------
    # O(w) time, O(w) space — w = 11 wizard pages constructed (each fills itself when shown)
    def open_wizard(self) -> SetupWizard:
        """Open the eleven-screen guided setup on the live session."""
        wizard = SetupWizard(
            self.session,
            staging_bank=self.staging_view.bank,
            on_changed=self._on_wizard_changed,
            parent=self,
        )
        self._wizard = wizard
        wizard.finished.connect(lambda _result: self._on_wizard_changed())
        wizard.show()
        return wizard

    # O(f log f) time, O(f) space — f = entries in the chosen directory (card.scan sorts them)
    def show_card_overview(self, directory: str | None = None) -> str:
        """List the banks on a card (or any folder) and how full it is.

        The budget meter shows the machine's 24 MB sample RAM. That is a
        different limit from the card's, and a 128 MB card holds about four
        full-size banks — so "how much room is left on the card" needs its own
        answer rather than being inferred from the meter.
        """
        if directory is None:
            directory = QFileDialog.getExistingDirectory(
                self, "Choose the card (or a folder of .esx banks)"
            )
            if not directory:
                return ""
        contents = card.scan(directory, card.detect_capacity(directory))
        lines = [contents.summary(), ""]
        if not contents.banks:
            lines.append("No .esx banks here.")
        # O(b) time, O(b) space — b = .esx banks found in the directory
        for bank in contents.banks:
            if not bank.readable:
                lines.append(f"{bank.name}  —  not a readable bank")
                continue
            lines.append(
                f"{bank.name}   {bank.size / 1_048_576:6.2f} MiB   "
                f"{bank.samples:3d} samples "
                f"({bank.num_mono} mono + {bank.num_stereo} stereo)   "
                f"{bank.ram_fraction * 100:.0f}% of sampler RAM"
            )
        text = "\n".join(lines)
        QMessageBox.information(self, f"Card — {directory}", text)
        return text

    # O(f log f) time, O(f) space — f = entries in the destination directory (card.scan sorts them)
    def card_warning_for(self, path: str) -> str:
        """Warn if saving to `path` would not fit on its card. '' when fine."""
        directory = os.path.dirname(os.path.abspath(path))
        contents = card.scan(directory, card.detect_capacity(directory))
        existing = os.path.getsize(path) if os.path.exists(path) else 0
        needed = (
            card.MAX_BANK_BYTES
            if self.session.bank is None
            else (card.FIXED_BYTES + self.session.pcm_used() + 16)
        )
        if needed - existing <= contents.free + existing:
            return ""
        return (
            f"This bank needs about {needed / 1_048_576:.1f} MiB but only "
            f"{(contents.free + existing) / 1_048_576:.1f} MiB is free there.\n\n"
            "The ESX-1 accepts 4–128 MB cards; delete a bank or use a larger card."
        )

    # O(s + m + P·c + G·g + n) time, O(s + m + P·c + G·g + n) space — s = sample slots (384); m = PCM bytes, copied only if pcm_used_bytes() raises; P = patterns in the bank (256 on the ESX-1); c = 4,280 bytes per pattern chunk; G = songs (64); g = 528 bytes per song block; n = staged samples redrawn
    def _on_wizard_changed(self) -> None:
        self.bankChanged.emit()
        self.staging_view.reload()
        self._refresh_chrome()

    # O(B) time, O(B) space — B = bytes in the bank file (fixed regions + up to 24 MiB of PCM)
    def _on_new(self) -> None:
        if not self._confirm_discard():
            return
        try:
            self.session.new_bank()
        except CodecError as exc:
            QMessageBox.warning(self, "New bank", str(exc))
            return
        self.bankChanged.emit()
        self._refresh_chrome()

    # O(B) time, O(B) space — B = bytes in the bank file (fixed regions + up to 24 MiB of PCM)
    def _on_open(self) -> None:
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Open ESX bank", "", "ESX banks (*.esx);;All files (*)"
        )
        if not path:
            return
        self.open_path(path)

    # O(B) time, O(B) space — B = bytes in the bank file (fixed regions + up to 24 MiB of PCM)
    def open_path(self, path: str) -> bool:
        """Open a bank by path. Returns False and warns on failure."""
        try:
            self.session.open_path(path)
        except (CodecError, OSError) as exc:
            QMessageBox.warning(self, "Open failed", str(exc))
            return False
        self.bankChanged.emit()
        self._refresh_chrome()
        return True

    # O(B + f log f) time, O(B + f) space — B = bytes in the bank file (fixed regions + up to 24 MiB of PCM); f = entries in the destination directory
    def _on_save(self) -> None:
        if self.session.path:
            self._write(self.session.path)
        else:
            self._on_save_as()

    # O(B + f log f) time, O(B + f) space — B = bytes in the bank file (fixed regions + up to 24 MiB of PCM); f = entries in the destination directory
    def _on_save_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save ESX bank", "", "ESX banks (*.esx)"
        )
        if path:
            self._write(path)

    # O(B + f log f) time, O(B + f) space — B = bytes in the bank file (fixed regions + up to 24 MiB of PCM); f = entries in the destination directory (card check)
    def _write(self, path: str) -> None:
        warning = self.card_warning_for(path)
        if warning:
            reply = QMessageBox.question(
                self,
                "Not enough room",
                warning + "\n\nTry the write anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        try:
            self.session.save(path)
        except CodecError as exc:
            if not self._offer_forced_save(path, exc):
                return
        self._refresh_chrome()

    # O(B + r log r) time, O(B + r) space — B = bytes in the bank file (fixed regions + up to 24 MiB of PCM); r = coherence findings reported
    def _offer_forced_save(self, path: str, exc: CodecError) -> bool:
        """Refused for incoherence — explain it and let the user decide.

        The guard itself is right: a bank whose offsets contradict its own
        headers should not be written by accident. But the refusal used to end
        at "pass allow_invalid=True", which is an instruction to a programmer
        shown to someone holding a mouse — and e4.esx, a real bank off the
        user's own card, trips it. A dead end on a file the machine itself
        wrote is not safety, it is a wall.

        So: still refuse by default, still require an explicit second act, but
        make that act possible. Returns True if the write went through.
        """
        report = self.session.validation_report()
        if report is None:
            QMessageBox.warning(self, "Save refused", str(exc))
            return False

        # O(r log r) time, O(r) space — r = coherence findings (dedupe, then sort the codes)
        codes = sorted({f.code for f in report.errors()})
        detail = (
            f"This bank has {len(report.errors())} coherence problem(s): "
            f"{', '.join(codes)}.\n\n"
            "They were almost certainly already there when the bank was "
            "opened — the editor does not create them. Saving preserves them "
            "rather than repairing them, because a repair would be a guess "
            "about what the machine meant.\n\n"
            "Save anyway, keeping the problems as they are?"
        )
        reply = QMessageBox.question(
            self,
            "Bank has existing problems",
            detail,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return False
        try:
            self.session.save(path, allow_invalid=True)
        except CodecError as second:
            QMessageBox.warning(self, "Save failed", str(second))
            return False
        return True

    # O(1) time, O(1) space
    def _on_about(self) -> None:
        QMessageBox.about(
            self,
            "About ESX Bank Studio",
            "Offline editor for Korg Electribe SX (.esx) banks.\n"
            "Personal use, never commercial.",
        )

    # O(1) time, O(1) space
    def _confirm_discard(self) -> bool:
        if not self.session.dirty:
            return True
        reply = QMessageBox.question(
            self,
            "Unsaved changes",
            "The current bank has unsaved changes. Discard them?",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
        )
        return reply == QMessageBox.StandardButton.Discard

    # O(1) time, O(1) space
    def closeEvent(self, event) -> None:  # noqa: N802
        if self._confirm_discard():
            event.accept()
        else:
            event.ignore()
