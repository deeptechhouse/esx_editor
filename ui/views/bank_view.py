"""Bank view — 384 sample slots, mono/stereo pools, usage meter (TDD §10.1)."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

import codec.layout as L
from core.bank import Bank
from core.errors import InvariantError
from ui.theme import PALETTE
from ui.widgets.budget_meter import BudgetMeter


class BankView(QWidget):
    #: A slot was renamed. The shell turns this into mark_dirty + chrome refresh.
    sampleEdited = Signal()

    #: Column holding the editable slot name.
    NAME_COLUMN = 1

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bank: Bank | None = None
        self._loading = False
        self.meter = BudgetMeter()
        self._counts = QLabel("mono 0/256   stereo 0/128")
        self._counts.setStyleSheet(f"color: {PALETTE.lcd};")
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["#", "name", "pool", "rate", "tune", "start", "end"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        # The name column is editable in place; everything else is derived
        # from the file and must not be typed over.
        self.table.setEditTriggers(
            QTableWidget.EditTrigger.DoubleClicked
            | QTableWidget.EditTrigger.EditKeyPressed
        )
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        # Give the slack to the name column: stretching whatever is
        # last makes an offset or a count absurdly wide.
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        head = QHBoxLayout()
        head.addWidget(QLabel("Sample memory"))
        head.addWidget(self.meter, 1)
        head.addWidget(self._counts)
        layout = QVBoxLayout(self)
        layout.addLayout(head)
        layout.addWidget(self.table)

    @staticmethod
    def _tune_text(slot) -> str:
        """Musical transposition, with rate compensation removed.

        The stored field mixes two concerns; the number a user means by
        "transpose" is the one with the rate compensation taken back out. An
        unreadable rate makes the whole calculation meaningless, so say so
        rather than print a number derived from nonsense.
        """
        try:
            return f"{slot.musical_tune():+.2f}"
        except InvariantError:
            return "—"

    def bind_bank(self, bank: Bank | None) -> None:
        self._bank = bank
        self.reload()

    def _on_item_changed(self, item) -> None:
        """Write an edited slot name back into the bank.

        The hardware field is exactly 8 bytes, so the model pads or truncates;
        the cell is then rewritten with what was actually stored rather than
        what was typed, so the table never shows a name the file does not have.
        """
        if self._loading or self._bank is None:
            return
        if item.column() != self.NAME_COLUMN:
            return
        slots = [s for s in self._bank.samples() if not s.empty]
        if not (0 <= item.row() < len(slots)):
            return
        slot = slots[item.row()]
        try:
            slot.set_name(item.text())
        except InvariantError:
            pass
        self._loading = True
        try:
            item.setText(slot.name)
        finally:
            self._loading = False
        self.sampleEdited.emit()

    def reload(self) -> None:
        self._loading = True
        try:
            self._reload()
        finally:
            self._loading = False

    def _reload(self) -> None:
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
            # The stereo rate offset was unconfirmed until 2026-08-23, when the
            # 40 populated stereo slots in Chronic-Interactive.esx settled it.
            # Both pools now read their real rate (see codec/layout.py).
            vals = (
                str(s.index),
                s.name,
                pool,
                str(s.sample_rate),
                self._tune_text(s),
                f"0x{s.offset_start:X}",
                f"0x{s.offset_end:X}",
            )
            for col, text in enumerate(vals):
                item = QTableWidgetItem(text)
                if col != self.NAME_COLUMN:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                )
                self.table.setItem(row, col, item)
        self.table.resizeColumnsToContents()
