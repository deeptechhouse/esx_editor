"""KnobDial — 0–127 rotary control painted as an amber LCD knob.

Emits valueChanged(int). Discrete snapping is the caller's job (MotionDomain);
this widget only stores and paints a raw 0–127 position.
"""

from __future__ import annotations

import math

from PySide6.QtCore import Qt, Signal, QPointF
from PySide6.QtGui import QColor, QPainter, QPen, QMouseEvent
from PySide6.QtWidgets import QWidget

from ui.theme import PALETTE, SPACE


class KnobDial(QWidget):
    valueChanged = Signal(int)

    def __init__(self, parent=None, *, value: int = 0, minimum: int = 0,
                 maximum: int = 127):
        super().__init__(parent)
        self._min = minimum
        self._max = maximum
        self._value = max(minimum, min(maximum, value))
        self.setMinimumSize(48, 48)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    @property
    def value(self) -> int:
        return self._value

    def setValue(self, value: int) -> None:  # noqa: N802  (Qt naming)
        clamped = max(self._min, min(self._max, int(value)))
        if clamped != self._value:
            self._value = clamped
            self.valueChanged.emit(self._value)
            self.update()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        step = 8 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
        if event.key() in (Qt.Key.Key_Right, Qt.Key.Key_Up):
            self.setValue(self._value + step)
        elif event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Down):
            self.setValue(self._value - step)
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._apply_pos(event.position())

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._apply_pos(event.position())

    def _apply_pos(self, pos: QPointF) -> None:
        c = self.rect().center()
        angle = math.atan2(pos.y() - c.y(), pos.x() - c.x())  # -pi..pi, 0 = east
        # Sweep a 270° arc from 7-o'clock to 5-o'clock.
        start = math.radians(135)
        sweep = math.radians(270)
        a = (angle - start) % (2 * math.pi)
        t = max(0.0, min(1.0, a / sweep))
        span = self._max - self._min
        self.setValue(self._min + round(t * span))

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = min(self.width(), self.height()) - 6
        box = self.rect().adjusted(
            (self.width() - r) // 2, (self.height() - r) // 2,
            -(self.width() - r) // 2, -(self.height() - r) // 2)
        p.setPen(QPen(QColor(PALETTE.line), 2))
        p.setBrush(QColor(PALETTE.panel2))
        p.drawEllipse(box)

        span = max(1, self._max - self._min)
        t = (self._value - self._min) / span
        start = math.radians(135)
        sweep = math.radians(270)
        ang = start + t * sweep
        cx, cy = box.center().x(), box.center().y()
        rad = r / 2 - 6
        x = cx + rad * math.cos(ang)
        y = cy + rad * math.sin(ang)
        p.setPen(QPen(QColor(PALETTE.amber), 3))
        p.drawLine(QPointF(cx, cy), QPointF(x, y))

        if self.hasFocus():
            p.setPen(QPen(QColor(PALETTE.amber), SPACE.focus))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(self.rect().adjusted(1, 1, -1, -1))
        p.end()
