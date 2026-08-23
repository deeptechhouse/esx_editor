"""Pattern view — 256 patterns, 16 parts, 3 FX, motion n/24 (TDD §10.1).

Tempo / length / last-step field offsets are unproven, so the 16-byte header
is shown as hex rather than invented numbers. Name, parts, FX, and motion
budget are live and editable where the model already allows.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QListWidget, QLabel, QLineEdit,
    QTableWidget, QTableWidgetItem,
)

from core.bank import Bank
from core.pattern import Pattern
from ui.theme import PALETTE
import codec.layout as L


class PatternView(QWidget):
    patternSelected = Signal(int)
    patternEdited = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bank: Bank | None = None
        self._index = 0
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._on_row)
        self._name = QLineEdit()
        self._name.setMaxLength(8)
        self._name.editingFinished.connect(self._rename)
        self._header = QLabel("")
        self._header.setStyleSheet(f"color: {PALETTE.muted};")
        self._motion = QLabel(f"0/{L.NUM_PARAMETERS_MOTION} motion")
        self._motion.setStyleSheet(f"color: {PALETTE.lcd};")
        self.parts = QTableWidget(0, 3)
        self.parts.setHorizontalHeaderLabels(["#", "kind", "index"])
        self.parts.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.parts.verticalHeader().setVisible(False)
        self.parts.setAlternatingRowColors(True)
        self.parts.horizontalHeader().setStretchLastSection(True)
        self.fx = QTableWidget(0, 3)
        self.fx.setHorizontalHeaderLabels(["FX", "type", "motion"])
        self.fx.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.fx.verticalHeader().setVisible(False)
        self.fx.setAlternatingRowColors(True)
        self.fx.horizontalHeader().setStretchLastSection(True)

        detail = QVBoxLayout()
        row = QHBoxLayout()
        row.addWidget(QLabel("Name"))
        row.addWidget(self._name)
        row.addWidget(self._motion)
        detail.addLayout(row)
        detail.addWidget(self._header)
        detail.addWidget(QLabel("Parts"))
        detail.addWidget(self.parts)
        detail.addWidget(QLabel("FX units"))
        detail.addWidget(self.fx)

        layout = QHBoxLayout(self)
        layout.addWidget(self.list, 1)
        layout.addLayout(detail, 2)

    def bind_bank(self, bank: Bank | None) -> None:
        self._bank = bank
        self.list.blockSignals(True)
        self.list.clear()
        if bank is not None:
            for i, p in enumerate(bank.patterns()):
                label = p.name or f"P{i:03d}"
                self.list.addItem(f"{i:03d}  {label}")
        self.list.blockSignals(False)
        if self.list.count():
            self.list.setCurrentRow(0)
        else:
            self._show(None)

    @property
    def current_index(self) -> int:
        """0-based index of the selected pattern (-1 when nothing is selected)."""
        return self._index

    def current_pattern(self) -> Pattern | None:
        if self._bank is None:
            return None
        pats = self._bank.patterns()
        if 0 <= self._index < len(pats):
            return pats[self._index]
        return None

    def _on_row(self, row: int) -> None:
        self._index = row
        self._show(self.current_pattern())
        if row >= 0:
            self.patternSelected.emit(row)

    def _rename(self) -> None:
        pat = self.current_pattern()
        if pat is None:
            return
        pat.set_name(self._name.text())
        item = self.list.currentItem()
        if item:
            item.setText(f"{self._index:03d}  {pat.name}")
        self.patternEdited.emit()

    def _show(self, pat: Pattern | None) -> None:
        self.parts.setRowCount(0)
        self.fx.setRowCount(0)
        if pat is None:
            self._name.setText("")
            self._header.setText("no pattern")
            self._motion.setText(f"0/{L.NUM_PARAMETERS_MOTION} motion")
            return
        self._name.setText(pat.name)
        raw = pat.header.to_bytes()
        self._header.setText(
            "header 16 B (tempo/length/beat unread — offsets unproven): "
            f"{raw.hex(' ')}")
        self._motion.setText(
            f"{pat.motion_slots_used()}/{L.NUM_PARAMETERS_MOTION} motion")
        parts = pat.parts()
        self.parts.setRowCount(len(parts))
        for i, part in enumerate(parts):
            for col, text in enumerate((str(i), part.kind, str(part.index))):
                self.parts.setItem(i, col, QTableWidgetItem(text))
        units = pat.fx_units()
        self.fx.setRowCount(len(units))
        for i, fx in enumerate(units):
            vals = (f"FX{i + 1}", str(fx.fx_type),
                    "on" if fx.motion_enabled else "off")
            for col, text in enumerate(vals):
                self.fx.setItem(i, col, QTableWidgetItem(text))
