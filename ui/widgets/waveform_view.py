"""WaveformView — paints a peak envelope. No audio decode, no I/O.

Callers push a sequence of peak samples in 0..1 (or -1..1); the widget only
draws. The staging view (WF6) will feed it from converted copies.
"""

from __future__ import annotations

from typing import Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QWidget

from ui.theme import PALETTE


class WaveformView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._peaks: tuple[float, ...] = ()
        self.setMinimumHeight(48)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def set_peaks(self, peaks: Sequence[float]) -> None:
        self._peaks = tuple(max(-1.0, min(1.0, float(x))) for x in peaks)
        self.update()

    @property
    def peaks(self) -> tuple[float, ...]:
        return self._peaks

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(PALETTE.lcd_bg))
        if not self._peaks:
            p.setPen(QColor(PALETTE.muted))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "no waveform")
            p.end()
            return
        w, h = self.width(), self.height()
        mid = h / 2
        n = len(self._peaks)
        poly = QPolygonF()
        for i, peak in enumerate(self._peaks):
            x = i * w / max(1, n - 1)
            y = mid - abs(peak) * (mid - 2)
            poly.append(QPointF(x, y))
        for i, peak in enumerate(reversed(self._peaks)):
            x = (n - 1 - i) * w / max(1, n - 1)
            y = mid + abs(peak) * (mid - 2)
            poly.append(QPointF(x, y))
        p.setPen(QPen(QColor(PALETTE.lcd), 1))
        p.setBrush(QColor(PALETTE.amber_dim))
        p.drawPolygon(poly)
        p.end()
