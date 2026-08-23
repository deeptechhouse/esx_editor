"""Bank view — 384 sample slots, mono/stereo pools, usage meter (TDD §10.1)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

import codec.layout as L
from core.bank import Bank
from ui.theme import PALETTE
from ui.widgets.budget_meter import BudgetMeter


class BankView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._bank: Bank | None = None
        self.meter = BudgetMeter()
        self._counts = QLabel("mono 0/256   stereo 0/128")
        self._counts.setStyleSheet(f"color: {PALETTE.lcd};")
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["#", "name", "pool", "rate", "start", "end"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        head = QHBoxLayout()
        head.addWidget(QLabel("Sample memory"))
        head.addWidget(self.meter, 1)
        head.addWidget(self._counts)
        layout = QVBoxLayout(self)
        layout.addLayout(head)
        layout.addWidget(self.table)

    def bind_bank(self, bank: Bank | None) -> None:
        self._bank = bank
        self.reload()

    def reload(self) -> None:
        self.table.setRowCount(0)
        if self._bank is None:
            self.meter.set_used(0)
            self._counts.setText("no bank")
            return
        try:
            used = self._bank.pcm_used_bytes()
        except Exception:
            used = len(self._bank.pcm)
        self.meter.set_used(used)
        samples = self._bank.samples()
        mono = samples[: L.NUM_SAMPLES_MONO]
        stereo = samples[L.NUM_SAMPLES_MONO :]
        n_m = sum(1 for s in mono if not s.empty)
        n_s = sum(1 for s in stereo if not s.empty)
        self._counts.setText(
            f"mono {n_m}/{L.NUM_SAMPLES_MONO}   stereo {n_s}/{L.NUM_SAMPLES_STEREO}"
        )
        occupied = [s for s in samples if not s.empty]
        self.table.setRowCount(len(occupied))
        for row, s in enumerate(occupied):
            pool = "stereo" if s.stereo else "mono"
            rate = "—" if s.stereo else str(s.sample_rate)
            vals = (
                str(s.index),
                s.name,
                pool,
                rate,
                f"0x{s.offset_start:X}",
                f"0x{s.offset_end:X}",
            )
            for col, text in enumerate(vals):
                item = QTableWidgetItem(text)
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                )
                self.table.setItem(row, col, item)
        self.table.resizeColumnsToContents()
