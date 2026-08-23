"""
ui.motion.editor — canvas + tools + picker + 24-slot budget (TDD §8.5).

Refuses to assign a 25th slot (loud, never silent). Warns before replacing a
populated target. Start-Point helper shows seconds-per-step when a duration
is supplied.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from codec.operation_table import MotionTarget, OperationTable
from core.motion import MotionDomain, MotionSlot
from core.pattern import Pattern
from ui.motion import tools
from ui.motion.canvas import MotionCanvas
from ui.motion.picker import TargetPicker
from ui.theme import PALETTE

TOOL_BUTTONS = (
    ("pencil", "Pencil"),
    ("eraser", "Eraser"),
    ("line", "Line"),
    ("ramp", "Ramp"),
    ("sine", "Sine"),
    ("tri", "Tri"),
    ("saw", "Saw"),
    ("square", "Square"),
    ("snh", "S&H"),
    ("invert", "Invert"),
    ("smooth", "Smooth"),
    ("random", "Random"),
    ("clear", "Clear"),
)

RESEARCH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "research",
)


def domain_for(target: MotionTarget) -> MotionDomain:
    return MotionDomain(target.kind, target.option_count, target.forced_trig)


class MotionEditor(QWidget):
    slotChanged = Signal()
    assignmentRefused = Signal(str)

    def __init__(self, parent=None, *, table: OperationTable | None = None):
        super().__init__(parent)
        self._table = table or OperationTable.load(RESEARCH)
        self._slots: list[MotionSlot] = [MotionSlot.empty() for _ in range(24)]
        self._index = 0
        self._target: MotionTarget | None = None
        self._sample_duration_s: float | None = None

        self.canvas = MotionCanvas(self, slot=self._slots[0], length=64)
        self.picker = TargetPicker(self._table)
        self.picker.targetSelected.connect(self._on_target)
        self.canvas.changed.connect(self.slotChanged)

        self._budget = QLabel("0/24 used")
        self._budget.setStyleSheet(f"color: {PALETTE.lcd};")
        self._start_help = QLabel("")
        self._start_help.setStyleSheet(f"color: {PALETTE.muted};")

        self._length = QSpinBox()
        self._length.setRange(1, 128)
        self._length.setValue(64)
        self._length.valueChanged.connect(self.canvas.set_length)

        self._trig = QCheckBox("TRIG HOLD")
        self._trig.toggled.connect(self.canvas.set_trig_hold)

        self._slot_box = QComboBox()
        for i in range(24):
            self._slot_box.addItem(f"slot {i + 1}")
        self._slot_box.currentIndexChanged.connect(self._on_slot_index)

        tools_row = QHBoxLayout()
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for name, label in TOOL_BUTTONS:
            btn = QPushButton(label)
            btn.setCheckable(name in ("pencil", "eraser", "line"))
            btn.clicked.connect(lambda _c=False, n=name: self._on_tool(n))
            tools_row.addWidget(btn)
            if name in ("pencil", "eraser", "line"):
                self._group.addButton(btn)
                if name == "pencil":
                    btn.setChecked(True)

        top = QHBoxLayout()
        top.addWidget(QLabel("Length"))
        top.addWidget(self._length)
        top.addWidget(self._trig)
        top.addWidget(self._slot_box)
        top.addWidget(self._budget)
        top.addWidget(self._start_help, 1)

        body = QHBoxLayout()
        body.addWidget(self.picker, 1)
        body.addWidget(self.canvas, 3)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addLayout(tools_row)
        layout.addLayout(body)
        self._refresh_budget()

    def bind_pattern(self, pattern: Pattern) -> None:
        """Edit the pattern's 24 motion slots in place."""
        self._slots = list(pattern.motion_slots())
        self._index = 0
        self._slot_box.setCurrentIndex(0)
        self.canvas.set_slot(self._slots[0], self.canvas.domain)
        self._refresh_budget()

    def set_sample_duration(self, seconds: float | None) -> None:
        self._sample_duration_s = seconds
        self._refresh_start_help()

    def _on_slot_index(self, index: int) -> None:
        self._index = index
        slot = self._slots[index]
        target = self._table.get_or_none(slot.target)
        domain = domain_for(target) if target else MotionDomain.continuous()
        self._target = target
        self.canvas.set_slot(slot, domain)

    def _on_target(self, target: MotionTarget) -> None:
        slot = self._slots[self._index]
        used = sum(1 for s in self._slots if s.in_use)
        assigning_new = not slot.in_use
        if assigning_new and used >= 24:
            msg = "all 24 motion slots are used — refuse, not a silent drop"
            self.assignmentRefused.emit(msg)
            QMessageBox.warning(self, "Motion slots full", msg)
            return
        if slot.in_use and slot.target != target.target_id:
            reply = QMessageBox.question(
                self,
                "Replace motion target",
                "Re-assigning a populated slot erases it on the hardware. Replace?",
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        slot.set_target(target.target_id)
        self._target = target
        self.canvas.set_slot(slot, domain_for(target))
        self._refresh_budget()
        self._refresh_start_help()
        self.slotChanged.emit()

    def _on_tool(self, name: str) -> None:
        slot, domain, n = self.canvas.slot, self.canvas.domain, self.canvas.length
        if name in ("pencil", "eraser", "line"):
            self.canvas.set_tool(name)
            return
        if name == "ramp":
            tools.ramp(slot, domain, 0, 127, length=n)
        elif name in tools.SHAPES:
            tools.lfo(slot, domain, name, length=n)
        elif name == "snh":
            tools.sample_and_hold(slot, domain, length=n)
        elif name == "invert":
            tools.invert(slot, domain, length=n)
        elif name == "smooth":
            tools.smooth(slot, domain, length=n)
        elif name == "random":
            tools.randomise(slot, domain, length=n)
        elif name == "clear":
            tools.clear(slot, domain, length=n)
        self.canvas.update()
        self.slotChanged.emit()

    def _refresh_budget(self) -> None:
        used = sum(1 for s in self._slots if s.in_use)
        self._budget.setText(f"{used}/24 used")
        self._budget.setStyleSheet(
            f"color: {PALETTE.red if used >= 24 else PALETTE.lcd};"
        )

    def _refresh_start_help(self) -> None:
        if (
            self._target
            and "START POINT" in self._target.name.upper()
            and self._sample_duration_s
        ):
            step_s = self._sample_duration_s / 128.0
            self._start_help.setText(f"Start Point: {step_s:.2f}s per step")
        else:
            self._start_help.setText("")
