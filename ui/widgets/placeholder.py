"""PlaceholderView — reserved pane for a WF6 view (bank/staging/pattern/…)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ui.theme import PALETTE


class PlaceholderView(QWidget):
    def __init__(self, title: str, hint: str = "", parent=None):
        super().__init__(parent)
        self._title = title
        layout = QVBoxLayout(self)
        heading = QLabel(title)
        heading.setProperty("role", "lcd")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        heading.setStyleSheet(f"color: {PALETTE.lcd}; font-size: 16px;")
        body = QLabel(hint or "This view lands in a later workflow.")
        body.setProperty("role", "muted")
        body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body.setStyleSheet(f"color: {PALETTE.muted};")
        body.setWordWrap(True)
        layout.addStretch(1)
        layout.addWidget(heading)
        layout.addWidget(body)
        layout.addStretch(2)
