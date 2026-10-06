"""
ui.widgets.lazy_choice — a dropdown that builds its options on first use.

WHY THIS EXISTS
    The Global tab offers a choice of all 128 MIDI notes for each of 13 drum
    parts, and all 128 control changes for each of 33 knobs: 46 dropdowns of
    128 options. Building those eagerly cost 0.3 s every time the view was
    constructed, which the app pays on every bank open and the test suite pays
    ninety-odd times.

    None of that work is needed until someone opens a list. What makes a cell
    read as editable is the dropdown arrow and the current value — not the 127
    options hidden behind it. So the widget shows one item, and fills the rest
    the first time it is opened.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox


class LazyChoiceBox(QComboBox):
    """A combo over `values`, labelled by `label`, populated on first popup.

    Callers work in VALUES, never in row indices: `value()` and `set_value()`
    mean the same thing whether or not the list has been built yet, which is
    the whole point of hiding the laziness.
    """

    valueChanged = Signal(int)

    # O(n) time, O(n) space — n = option values offered
    def __init__(
        self,
        values: Sequence[int],
        label: Callable[[int], str],
        parent=None,
    ):
        super().__init__(parent)
        self._values = tuple(values)
        self._label = label
        self._filled = False
        self._quiet = False
        self._value = self._values[0] if self._values else 0
        self._show_only_current()
        self.currentIndexChanged.connect(self._on_index_changed)

    # -- value ---------------------------------------------------------------

    # O(1) time, O(1) space
    def value(self) -> int:
        return self._value

    # O(n) time, O(1) space — n = option values offered (a linear index lookup once the list is filled)
    def set_value(self, value: int) -> None:
        """Set the selection without emitting valueChanged."""
        if value == self._value and self.count():
            return
        self._value = value
        self._quiet = True
        try:
            if self._filled:
                self.setCurrentIndex(self._values.index(value))
            else:
                self._show_only_current()
        finally:
            self._quiet = False

    # -- laziness ------------------------------------------------------------

    # O(n) time, O(n) space — n = option values offered (first open fills the list)
    def showPopup(self) -> None:  # noqa: N802 - Qt's name
        self.ensure_filled()
        super().showPopup()

    # O(n) time, O(n) space — n = option values offered
    def ensure_filled(self) -> None:
        """Build the full option list. Idempotent; safe to call from tests."""
        if self._filled:
            return
        self._quiet = True
        try:
            self.clear()
            # O(n) time, O(n) space — n = option values offered
            for value in self._values:
                self.addItem(self._label(value), value)
            self._filled = True
            self.setCurrentIndex(self._values.index(self._value))
        finally:
            self._quiet = False

    @property
    # O(1) time, O(1) space
    def is_filled(self) -> bool:
        return self._filled

    # -- internals -----------------------------------------------------------

    # O(1) time, O(1) space
    def _show_only_current(self) -> None:
        self.clear()
        self.addItem(self._label(self._value), self._value)
        self.setCurrentIndex(0)

    # O(1) time, O(1) space
    def _on_index_changed(self, index: int) -> None:
        if self._quiet or index < 0:
            return
        value = self.currentData()
        if value is None or value == self._value:
            return
        self._value = value
        self.valueChanged.emit(value)
