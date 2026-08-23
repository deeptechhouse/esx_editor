"""BudgetMeter — live 25 MB scoreboard (TDD §6.1 / §10.1).

Renders used/capacity as an LCD-style bar plus remaining seconds at CD mono.
Widgets only paint; callers push numbers via set_used().
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ui.theme import PALETTE, SPACE
from workspace.budget import CAPACITY, DEFAULT_RATE


class BudgetMeter(QWidget):
    """Horizontal usage bar for sample memory."""

    def __init__(self, parent=None, *, capacity: int = CAPACITY):
        super().__init__(parent)
        self._used = 0
        self._capacity = capacity
        self.setMinimumHeight(28)
        self.setMinimumWidth(180)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setToolTip("sample memory used / 25 165 824 B")

    def set_used(self, used: int) -> None:
        self._used = max(0, used)
        self.update()

    @property
    def used(self) -> int:
        return self._used

    @property
    def fraction(self) -> float:
        return 0.0 if self._capacity <= 0 else self._used / self._capacity

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect().adjusted(1, 4, -1, -4)
        p.fillRect(r, QColor(PALETTE.chassis))
        p.setPen(QPen(QColor(PALETTE.line), 1))
        p.drawRoundedRect(r, SPACE.radius, SPACE.radius)

        frac = max(0.0, min(self.fraction, 1.0))
        fill = r.adjusted(2, 2, -2, -2)
        fill.setWidth(max(0, int(fill.width() * frac)))
        over = self._used > self._capacity
        p.fillRect(fill, QColor(PALETTE.red if over else PALETTE.amber))

        remain_s = max(0, self._capacity - self._used) / (DEFAULT_RATE * 2)
        label = (
            f"{self._used / 1_048_576:.1f} / "
            f"{self._capacity / 1_048_576:.1f} MB   "
            f"{remain_s:.0f}s CD left"
        )
        p.setPen(QColor(PALETTE.txt if not over else PALETTE.red))
        p.setFont(self.font())
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, label)
        p.end()
