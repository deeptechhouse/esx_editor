"""StepGrid — 16×8 orange step keys (128 steps, the hardware's max).

Click (or Space on a focused cell) toggles a step. Emits stepToggled(index, on).
Beyond `length` steps are drawn dimmed (pattern-length masking, TDD §8.1).
"""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ui.theme import PALETTE, SPACE

COLS = 16
ROWS = 8
NUM_STEPS = COLS * ROWS  # 128


class StepGrid(QWidget):
    stepToggled = Signal(int, bool)

    #: The hardware's maximum, exposed so callers do not re-derive it.
    NUM_STEPS = NUM_STEPS
    COLS = COLS
    ROWS = ROWS

    def __init__(self, parent=None, *, length: int = NUM_STEPS):
        super().__init__(parent)
        self._on = [False] * NUM_STEPS
        self._length = max(1, min(NUM_STEPS, length))
        self._focus = 0
        self.setMinimumSize(COLS * 18, ROWS * 18)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def set_length(self, length: int) -> None:
        self._length = max(1, min(NUM_STEPS, length))
        self.update()

    def set_step(self, index: int, on: bool) -> None:
        if not (0 <= index < NUM_STEPS):
            return
        if self._on[index] != bool(on):
            self._on[index] = bool(on)
            self.stepToggled.emit(index, self._on[index])
            self.update()

    def is_on(self, index: int) -> bool:
        return bool(self._on[index])

    def steps(self) -> tuple[bool, ...]:
        return tuple(self._on)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        idx = self._index_at(event.position().toPoint())
        if idx is not None:
            self._focus = idx
            self.set_step(idx, not self._on[idx])
            self.setFocus()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        key = event.key()
        if key in (Qt.Key.Key_Space, Qt.Key.Key_Return):
            self.set_step(self._focus, not self._on[self._focus])
        elif key == Qt.Key.Key_Right:
            self._focus = min(NUM_STEPS - 1, self._focus + 1)
            self.update()
        elif key == Qt.Key.Key_Left:
            self._focus = max(0, self._focus - 1)
            self.update()
        elif key == Qt.Key.Key_Down:
            self._focus = min(NUM_STEPS - 1, self._focus + COLS)
            self.update()
        elif key == Qt.Key.Key_Up:
            self._focus = max(0, self._focus - COLS)
            self.update()
        else:
            super().keyPressEvent(event)

    def _index_at(self, pos) -> int | None:
        cell_w = self.width() / COLS
        cell_h = self.height() / ROWS
        col = int(pos.x() // cell_w)
        row = int(pos.y() // cell_h)
        if 0 <= col < COLS and 0 <= row < ROWS:
            return row * COLS + col
        return None

    def _cell_rect(self, index: int) -> QRect:
        row, col = divmod(index, COLS)
        cell_w = self.width() / COLS
        cell_h = self.height() / ROWS
        return QRect(
            int(col * cell_w) + 1,
            int(row * cell_h) + 1,
            int(cell_w) - 2,
            int(cell_h) - 2,
        )

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(PALETTE.chassis))
        for i in range(NUM_STEPS):
            r = self._cell_rect(i)
            beyond = i >= self._length
            if self._on[i]:
                color = QColor(PALETTE.step)
            elif beyond:
                color = QColor(PALETTE.panel2)
            else:
                color = QColor(PALETTE.panel)
            p.fillRect(r, color)
            if i == self._focus and self.hasFocus():
                p.setPen(QPen(QColor(PALETTE.amber), SPACE.focus))
            else:
                p.setPen(QPen(QColor(PALETTE.line), 1))
            p.drawRect(r)
        p.end()
