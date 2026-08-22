"""
ui.motion.canvas — drawable 128-step envelope (TDD §8.5).

Three visual states per step:
    value          — plotted (polyline if SMOOTH, staircase if TRIG / forced-TRIG)
    Disabl (0x80)  — a GAP, never zero
    beyond length  — dimmed, read-only

Y is the target's stored-byte domain (0–127), not a raw index. Discrete
domains snap on write via MotionSlot.write_stored. Pitch is not exposed by
the picker; if a Pitch domain were bound, writes still go through snap_stored
(0–127) — we refuse to invent a 0–255 mapping.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QPointF, QRectF
from PySide6.QtGui import QColor, QPainter, QPen, QMouseEvent
from PySide6.QtWidgets import QWidget

from core.motion import MotionDomain, MotionSlot
from ui.motion import tools
from ui.theme import PALETTE, SPACE


class MotionCanvas(QWidget):
    """Paints one MotionSlot and writes through the tool primitives."""

    changed = Signal()

    def __init__(self, parent=None, *,
                 slot: MotionSlot | None = None,
                 domain: MotionDomain | None = None,
                 length: int = 64):
        super().__init__(parent)
        self._slot = slot or MotionSlot.empty()
        self._domain = domain or MotionDomain.continuous()
        self._length = max(1, min(MotionSlot.NUM_STEPS, length))
        self._trig_hold = False
        self._tool = "pencil"
        self._drawing = False
        self._anchor: tuple[int, int] | None = None
        self.setMinimumSize(320, 160)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

    @property
    def slot(self) -> MotionSlot:
        return self._slot

    @property
    def domain(self) -> MotionDomain:
        return self._domain

    @property
    def length(self) -> int:
        return self._length

    def set_slot(self, slot: MotionSlot, domain: MotionDomain) -> None:
        self._slot = slot
        self._domain = domain
        self.update()

    def set_length(self, length: int) -> None:
        self._length = max(1, min(MotionSlot.NUM_STEPS, length))
        self.update()

    def set_trig_hold(self, stepped: bool) -> None:
        self._trig_hold = bool(stepped)
        self.update()

    def set_tool(self, name: str) -> None:
        self._tool = name

    def _stepped(self) -> bool:
        return self._domain.forced_trig or self._trig_hold

    def _cell_w(self) -> float:
        return self.width() / MotionSlot.NUM_STEPS

    def _pos_to_step_value(self, pos) -> tuple[int, int]:
        step = int(pos.x() / self._cell_w())
        step = max(0, min(MotionSlot.NUM_STEPS - 1, step))
        y = 1.0 - (pos.y() / max(1, self.height()))
        value = max(0, min(127, int(round(y * 127))))
        return step, value

    def apply_pencil(self, step: int, value: int) -> None:
        tools.write_step(self._slot, step, value, self._domain, length=self._length)
        self.changed.emit()
        self.update()

    def apply_eraser(self, step: int) -> None:
        tools.eraser(self._slot, step, self._domain, length=self._length)
        self.changed.emit()
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(PALETTE.lcd_bg))
        w, h = self.width(), self.height()
        cell = self._cell_w()

        # Mask: beyond-length region
        mask_x = self._length * cell
        if mask_x < w:
            p.fillRect(QRectF(mask_x, 0, w - mask_x, h), QColor(PALETTE.chassis))

        # Centre line for bipolar (64)
        if self._domain.kind == MotionDomain.BIPOLAR:
            p.setPen(QPen(QColor(PALETTE.line), 1, Qt.PenStyle.DotLine))
            p.drawLine(QPointF(0, h * (1 - 64 / 127)), QPointF(w, h * (1 - 64 / 127)))

        p.setPen(QPen(QColor(PALETTE.line), 1))
        for bar in range(0, MotionSlot.NUM_STEPS, 16):
            x = bar * cell
            p.drawLine(QPointF(x, 0), QPointF(x, h))

        # Plot enabled steps; break the path on Disabl (a gap, never zero).
        stepped = self._stepped()
        color = QColor(PALETTE.amber if not stepped else PALETTE.step)
        p.setPen(QPen(color, 2))
        last: QPointF | None = None
        for i in range(self._length):
            if self._slot.is_disabled(i):
                last = None
                continue
            v = self._slot.get_step(i)
            x = (i + 0.5) * cell
            y = h * (1 - v / 127)
            pt = QPointF(x, y)
            if stepped:
                if last is not None:
                    # latch: horizontal to this step, then vertical
                    p.drawLine(last, QPointF(x, last.y()))
                    p.drawLine(QPointF(x, last.y()), pt)
                else:
                    p.drawPoint(pt)
            else:
                if last is not None:
                    p.drawLine(last, pt)
                else:
                    p.drawPoint(pt)
            last = pt
            # tick mark
            p.fillRect(QRectF(x - 2, y - 2, 4, 4), color)

        if self.hasFocus():
            p.setPen(QPen(QColor(PALETTE.amber), SPACE.focus))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(self.rect().adjusted(1, 1, -1, -1))
        p.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        step, value = self._pos_to_step_value(event.position())
        self._drawing = True
        self._anchor = (step, value)
        if event.button() == Qt.MouseButton.RightButton or self._tool == "eraser":
            self.apply_eraser(step)
        elif self._tool == "pencil":
            self.apply_pencil(step, value)
        self.setFocus()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if not self._drawing:
            return
        step, value = self._pos_to_step_value(event.position())
        if event.buttons() & Qt.MouseButton.RightButton or self._tool == "eraser":
            self.apply_eraser(step)
        elif self._tool == "pencil":
            self.apply_pencil(step, value)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drawing and self._tool == "line" and self._anchor is not None:
            step, value = self._pos_to_step_value(event.position())
            x0, y0 = self._anchor
            tools.line(self._slot, self._domain, x0, y0, step, value,
                       length=self._length)
            self.changed.emit()
            self.update()
        self._drawing = False
        self._anchor = None
