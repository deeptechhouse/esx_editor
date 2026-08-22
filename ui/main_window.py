"""
ui.main_window — the application shell: menus, tabs, status, session (TDD §10.1).

View tabs are placeholders in WF4; WF6 fills Bank/Staging/Pattern/Song/Global
and WF5 fills Motion. The shell already wires File→New/Open/Save against
BankSession so later views only have to bind to the live Bank.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QMainWindow, QTabWidget, QFileDialog, QMessageBox, QLabel,
)

from codec.errors import CodecError
from ui.session import BankSession
from ui.theme import PALETTE
from ui.widgets.budget_meter import BudgetMeter
from ui.widgets.placeholder import PlaceholderView


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

    def __init__(self, session: BankSession | None = None, parent=None):
        super().__init__(parent)
        self.session = session or BankSession()
        self.setWindowTitle(APP_TITLE)
        self.resize(1100, 720)
        self._build_tabs()
        self._build_menus()
        self._build_status()
        self._refresh_chrome()

    def _build_tabs(self) -> None:
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        for name, hint in TABS:
            self.tabs.addTab(PlaceholderView(name, hint), name)
        self.setCentralWidget(self.tabs)

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        self._act("New bank", file_menu, self._on_new, QKeySequence.StandardKey.New)
        self._act("Open…", file_menu, self._on_open, QKeySequence.StandardKey.Open)
        self._act("Save", file_menu, self._on_save, QKeySequence.StandardKey.Save)
        self._act("Save As…", file_menu, self._on_save_as,
                  QKeySequence.StandardKey.SaveAs)
        file_menu.addSeparator()
        self._act("Quit", file_menu, self.close, QKeySequence.StandardKey.Quit)

        edit_menu = self.menuBar().addMenu("&Edit")
        edit_menu.addAction(QAction("(views land in later workflows)", self))

        view_menu = self.menuBar().addMenu("&View")
        for i, (name, _) in enumerate(TABS):
            act = QAction(name, self)
            act.setShortcut(QKeySequence(f"Ctrl+{i + 1}"))
            act.triggered.connect(lambda _checked=False, idx=i: self.tabs.setCurrentIndex(idx))
            view_menu.addAction(act)

        help_menu = self.menuBar().addMenu("&Help")
        self._act("About", help_menu, self._on_about)

    def _act(self, text, menu, slot, shortcut=None) -> QAction:
        act = QAction(text, self)
        if shortcut is not None:
            act.setShortcut(shortcut)
        act.triggered.connect(slot)
        menu.addAction(act)
        return act

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

    def _refresh_chrome(self) -> None:
        path = self.session.path
        name = os.path.basename(path) if path else (
            "untitled.esx" if self.session.is_open else "no bank")
        dirty = "•" if self.session.dirty else ""
        self.setWindowTitle(f"{APP_TITLE} — {name}{dirty}")
        self._path_label.setText(path or name)
        self._dirty_label.setText("modified" if self.session.dirty else "")
        self.meter.set_used(self.session.pcm_used())

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

    def _on_open(self) -> None:
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Open ESX bank", "", "ESX banks (*.esx);;All files (*)")
        if not path:
            return
        try:
            self.session.open_path(path)
        except (CodecError, OSError) as exc:
            QMessageBox.warning(self, "Open failed", str(exc))
            return
        self.bankChanged.emit()
        self._refresh_chrome()

    def _on_save(self) -> None:
        if self.session.path:
            self._write(self.session.path)
        else:
            self._on_save_as()

    def _on_save_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save ESX bank", "", "ESX banks (*.esx)")
        if path:
            self._write(path)

    def _write(self, path: str) -> None:
        try:
            self.session.save(path)
        except CodecError as exc:
            QMessageBox.warning(self, "Save refused", str(exc))
            return
        self._refresh_chrome()

    def _on_about(self) -> None:
        QMessageBox.about(
            self, "About ESX Bank Studio",
            "Offline editor for Korg Electribe SX (.esx) banks.\n"
            "Personal use, never commercial.")

    def _confirm_discard(self) -> bool:
        if not self.session.dirty:
            return True
        reply = QMessageBox.question(
            self, "Unsaved changes",
            "The current bank has unsaved changes. Discard them?",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
        )
        return reply == QMessageBox.StandardButton.Discard

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._confirm_discard():
            event.accept()
        else:
            event.ignore()
