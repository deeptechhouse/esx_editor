"""
ui.motion.picker — 313-target list filtered by part kind (TDD §8.5).

Grouped as Part Common / Filter / Modulation / Effects. Accent is LEVEL only.
Pitch is hidden until the hardware mapping is proven.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QComboBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from codec.operation_table import OperationTable
from core.part import (
    KIND_ACCENT,
    KIND_AUDIOIN,
    KIND_DRUM,
    KIND_KEYBOARD,
    KIND_STRETCHSLICE,
)
from ui.theme import PALETTE

PART_KINDS = (
    (KIND_DRUM, "Drum"),
    (KIND_KEYBOARD, "Keyboard"),
    (KIND_STRETCHSLICE, "Stretch / Slice"),
    (KIND_AUDIOIN, "Audio In"),
    (KIND_ACCENT, "Accent"),
)

SECTIONS = ("Part Common", "Filter", "Modulation", "Effects")


class TargetPicker(QWidget):
    targetSelected = Signal(object)  # MotionTarget
    partKindChanged = Signal(str)

    def __init__(self, table: OperationTable, parent=None):
        super().__init__(parent)
        self._table = table
        self._kind = KIND_DRUM
        self._combo = QComboBox()
        for kind, label in PART_KINDS:
            self._combo.addItem(label, kind)
        self._combo.currentIndexChanged.connect(self._on_kind)
        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.itemClicked.connect(self._on_item)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._combo)
        layout.addWidget(self._tree)
        self._rebuild()

    @property
    def part_kind(self) -> str:
        return self._kind

    def set_part_kind(self, kind: str) -> None:
        idx = self._combo.findData(kind)
        if idx >= 0:
            self._combo.setCurrentIndex(idx)

    def _on_kind(self) -> None:
        self._kind = self._combo.currentData()
        self._rebuild()
        self.partKindChanged.emit(self._kind)

    def _rebuild(self) -> None:
        self._tree.clear()
        groups = {s: QTreeWidgetItem([s]) for s in SECTIONS}
        for item in groups.values():
            item.setForeground(0, QBrush(QColor(PALETTE.lcd)))
            self._tree.addTopLevelItem(item)
        for t in self._table.targets_for_part(self._kind):
            section = self._table.section_of(t)
            parent = groups.get(section, groups["Part Common"])
            child = QTreeWidgetItem([t.name])
            child.setData(0, 32, t.target_id)  # Qt.UserRole
            parent.addChild(child)
        self._tree.expandAll()

    def _on_item(self, item: QTreeWidgetItem, _col: int) -> None:
        tid = item.data(0, 32)
        if tid is None:
            return
        target = self._table.get_or_none(int(tid))
        if target is not None:
            self.targetSelected.emit(target)

    def visible_names(self) -> tuple[str, ...]:
        """Test helper: every leaf currently shown."""
        names: list[str] = []
        for i in range(self._tree.topLevelItemCount()):
            top = self._tree.topLevelItem(i)
            for j in range(top.childCount()):
                names.append(top.child(j).text(0))
        return tuple(names)
