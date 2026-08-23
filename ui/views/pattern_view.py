"""Pattern view — 256 patterns, 16 parts, 3 FX, motion n/24 (TDD §10.1).

Tempo / length / last-step field offsets are unproven, so the 16-byte header
is shown as hex rather than invented numbers. Name, parts, FX, and motion
budget are live and editable where the model already allows.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

import codec.layout as L
from core.bank import Bank
from core.pattern import MAX_TEMPO, MIN_TEMPO, NUM_FX_TYPES, Pattern
from ui.theme import PALETTE
from ui.widgets.step_grid import StepGrid


class PatternView(QWidget):
    patternSelected = Signal(int)
    patternEdited = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bank: Bank | None = None
        self._index = 0
        self._loading = False
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._on_row)
        self._name = QLineEdit()
        self._name.setMaxLength(8)
        self._name.editingFinished.connect(self._rename)
        self._tempo = QDoubleSpinBox()
        self._tempo.setDecimals(1)
        self._tempo.setSingleStep(0.1)
        self._tempo.setRange(MIN_TEMPO, MAX_TEMPO)
        self._tempo.setSuffix(" BPM")
        self._tempo.setKeyboardTracking(False)
        self._tempo.valueChanged.connect(self._retempo)
        self._header = QLabel("")
        self._header.setStyleSheet(f"color: {PALETTE.muted};")
        self._steps_label = QLabel("Steps")
        self.steps = StepGrid()
        self.steps.stepToggled.connect(self._on_step_toggled)
        self._part_row = 0
        self._motion = QLabel(f"0/{L.NUM_PARAMETERS_MOTION} motion")
        self._motion.setStyleSheet(f"color: {PALETTE.lcd};")
        self.parts = QTableWidget(0, 5)
        self.parts.setHorizontalHeaderLabels(["#", "kind", "sample", "name", "steps"])
        self.parts.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.parts.currentCellChanged.connect(self._on_part_row)
        self.parts.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.parts.verticalHeader().setVisible(False)
        self.parts.setAlternatingRowColors(True)
        # Give the slack to the name column: stretching whatever is
        # last makes an offset or a count absurdly wide.
        self.parts.horizontalHeader().setStretchLastSection(False)
        self.parts.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )
        self.fx = QTableWidget(0, 3)
        self.fx.setHorizontalHeaderLabels(["FX", "type", "motion"])
        self.fx.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.fx.verticalHeader().setVisible(False)
        self.fx.setAlternatingRowColors(True)
        # Give the slack to the name column: stretching whatever is
        # last makes an offset or a count absurdly wide.
        self.fx.horizontalHeader().setStretchLastSection(False)
        self.fx.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )

        detail = QVBoxLayout()
        row = QHBoxLayout()
        row.addWidget(QLabel("Name"))
        row.addWidget(self._name)
        row.addWidget(QLabel("Tempo"))
        row.addWidget(self._tempo)
        row.addWidget(self._motion)
        detail.addLayout(row)
        detail.addWidget(self._header)
        detail.addWidget(QLabel("Parts"))
        detail.addWidget(self.parts)
        detail.addWidget(self._steps_label)
        detail.addWidget(self.steps)
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

    def current_part(self):
        """The selected Part, or None."""
        pat = self.current_pattern()
        if pat is None:
            return None
        parts = pat.parts()
        if 0 <= self._part_row < len(parts):
            return parts[self._part_row]
        return None

    def _on_part_row(self, row: int, _col: int = 0, *_args) -> None:
        if row < 0:
            return
        self._part_row = row
        self._show_steps()

    def _show_steps(self) -> None:
        """Load the selected part's trigger bitmap into the grid."""
        part = self.current_part()
        self._loading = True
        try:
            if part is None or not part.has_sequence():
                self.steps.setEnabled(False)
                kind = part.kind if part is not None else "—"
                self._steps_label.setText(
                    f"Steps — not decoded for a {kind} part"
                    if part is not None
                    else "Steps"
                )
                for i in range(StepGrid.NUM_STEPS):
                    self.steps.set_step(i, False)
                return
            self.steps.setEnabled(True)
            sequence = part.sequence()
            for i in range(StepGrid.NUM_STEPS):
                self.steps.set_step(i, sequence.is_active(i))
            self._steps_label.setText(
                f"Steps — part {self._part_row} ({part.kind}), "
                f"{sequence.count()} triggering"
            )
        finally:
            self._loading = False

    def _on_step_toggled(self, index: int, on: bool) -> None:
        if self._loading:
            return
        part = self.current_part()
        if part is None or not part.has_sequence():
            return
        sequence = part.sequence()
        sequence.set_active(index, on)
        part.write_sequence(sequence)
        self._show_steps()
        self.patternEdited.emit()

    def _retempo(self, value: float) -> None:
        pat = self.current_pattern()
        if pat is None or self._loading:
            return
        if abs(pat.header.tempo - value) < 0.001:
            return
        pat.header.set_tempo(value)
        self.patternEdited.emit()

    def _show(self, pat: Pattern | None) -> None:
        self.parts.setRowCount(0)
        self.fx.setRowCount(0)
        self._loading = True
        try:
            self._populate(pat)
        finally:
            self._loading = False

    def _populate(self, pat: Pattern | None) -> None:
        if pat is None:
            self._name.setText("")
            self._tempo.setEnabled(False)
            self._header.setText("no pattern")
            self._motion.setText(f"0/{L.NUM_PARAMETERS_MOTION} motion")
            return
        self._name.setText(pat.name)
        self._tempo.setEnabled(True)
        self._tempo.setValue(pat.header.tempo)
        raw = pat.header.to_bytes()
        # Tempo is decoded (VERIFIED); length / beat / last step are not, and
        # every named pattern in the corpus shares the same bytes there, so
        # there is nothing to correlate a meaning against. Show the raw header
        # rather than invent them.
        self._header.setText(
            "header 16 B — tempo decoded; length/beat/last-step still unproven: "
            f"{raw.hex(' ')}"
        )
        self._motion.setText(
            f"{pat.motion_slots_used()}/{L.NUM_PARAMETERS_MOTION} motion"
        )
        parts = pat.parts()
        self.parts.setRowCount(len(parts))
        samples = self._bank.samples() if self._bank is not None else ()
        for i, part in enumerate(parts):
            try:
                number = part.sample_number
                slot_text = str(number)
                name = samples[number].name if number < len(samples) else ""
            except NotImplementedError:
                # Audio-in and accent parts do not reference a sample slot.
                slot_text, name = "—", ""
            try:
                steps = str(part.sequence().count())
            except NotImplementedError:
                steps = "—"
            for col, text in enumerate((str(i), part.kind, slot_text, name, steps)):
                self.parts.setItem(i, col, QTableWidgetItem(text))
        self._show_steps()
        units = pat.fx_units()
        self.fx.setRowCount(len(units))
        for i, fx in enumerate(units):
            # Show the index, not a name: the manual lists 16 effect types but
            # gives no index->name mapping, and its two orderings disagree.
            vals = (
                f"FX{i + 1}",
                f"type {fx.fx_type} of {NUM_FX_TYPES}",
                "on" if fx.motion_enabled else "off",
            )
            for col, text in enumerate(vals):
                self.fx.setItem(i, col, QTableWidgetItem(text))
