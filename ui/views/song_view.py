"""Song view — 64 songs, each an ordered chain of patterns (TDD §2.1 / §10.1).

A song on this machine is a playlist: positions 1..N, each naming one of the
256 patterns, played in order. That chain is what this view edits. Name, tempo
and the chain are decoded (see core.song for the evidence); tempo lock, mute
hold and next-song are still zero in every bank ever seen, so they are absent
here rather than guessed at.

Patterns are shown the way the machine's display shows them — A.01 to D.64 —
because telling someone to check "pattern 132" when the device says C.05 wastes
their time at the hardware.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

import codec.layout as L
from core.bank import Bank
from core.pattern import pattern_label
from core.song import MAX_CHAIN, MAX_TEMPO, MIN_TEMPO, SONG_NAME_LEN
from ui.theme import PALETTE


class SongView(QWidget):
    """Edit the 64 songs: name, tempo, and the chain of patterns each plays."""

    songEdited = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bank: Bank | None = None
        self._index = 0
        self._loading = False

        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._on_row)

        self._name = QLineEdit()
        self._name.setMaxLength(SONG_NAME_LEN)
        self._name.setPlaceholderText("song name")
        self._name.editingFinished.connect(self._rename)

        self._tempo = QDoubleSpinBox()
        self._tempo.setDecimals(1)
        self._tempo.setSingleStep(0.1)
        self._tempo.setRange(MIN_TEMPO, MAX_TEMPO)
        self._tempo.setSuffix(" BPM")
        self._tempo.setKeyboardTracking(False)
        self._tempo.valueChanged.connect(self._retempo)

        self.clear_button = QPushButton("Clear song")
        self.clear_button.setToolTip(
            "Reset this song to the machine's untouched default:\n"
            "blank name, 120.0 BPM, one position playing A.01."
        )
        self.clear_button.clicked.connect(self.clear_song)

        # The chain: one row per position, in play order.
        self.chain = QTableWidget(0, 3)
        self.chain.setHorizontalHeaderLabels(["position", "pattern", "name"])
        self.chain.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.chain.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.chain.verticalHeader().setVisible(False)
        self.chain.setAlternatingRowColors(True)
        self.chain.horizontalHeader().setStretchLastSection(False)
        # Stretch the pattern NAME, not the A.01 label: stretching a
        # four-character column makes it absurdly wide.
        self.chain.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )

        self.pattern_picker = QComboBox()
        self._fill_picker(())
        self.add_button = QPushButton("Add")
        self.add_button.setToolTip("Append the chosen pattern to the end of the chain.")
        self.add_button.clicked.connect(self.add_pattern)
        self.remove_button = QPushButton("Remove")
        self.remove_button.setToolTip("Drop the selected position from the chain.")
        self.remove_button.clicked.connect(self.remove_position)
        self.up_button = QPushButton("↑")
        self.up_button.setToolTip("Move the selected position earlier.")
        self.up_button.clicked.connect(lambda: self.move_position(-1))
        self.down_button = QPushButton("↓")
        self.down_button.setToolTip("Move the selected position later.")
        self.down_button.clicked.connect(lambda: self.move_position(1))

        self._headline = QLabel("")
        self._headline.setStyleSheet(f"color: {PALETTE.lcd};")
        self._headline.setWordWrap(True)
        self._detail = QLabel("")
        self._detail.setStyleSheet(f"color: {PALETTE.muted};")
        self._detail.setWordWrap(True)

        meta = QHBoxLayout()
        meta.addWidget(QLabel("Name"))
        meta.addWidget(self._name)
        meta.addWidget(QLabel("Tempo"))
        meta.addWidget(self._tempo)
        meta.addWidget(self.clear_button)
        meta.addStretch(1)

        tools = QHBoxLayout()
        tools.addWidget(self.pattern_picker)
        tools.addWidget(self.add_button)
        tools.addWidget(self.remove_button)
        tools.addWidget(self.up_button)
        tools.addWidget(self.down_button)
        tools.addStretch(1)

        right = QVBoxLayout()
        right.addLayout(meta)
        right.addWidget(self._headline)
        right.addWidget(self.chain)
        right.addLayout(tools)
        right.addWidget(self._detail)

        body = QHBoxLayout(self)
        body.addWidget(self.list, 1)
        body.addLayout(right, 3)
        self.reload()

    # -- binding ------------------------------------------------------------

    def bind_bank(self, bank: Bank | None) -> None:
        self._bank = bank
        self._index = 0
        self.reload()

    def song(self):
        """The selected Song, or None when no bank is loaded."""
        if self._bank is None:
            return None
        songs = self._bank.songs()
        if not (0 <= self._index < len(songs)):
            return None
        return songs[self._index]

    def reload(self) -> None:
        self._loading = True
        try:
            self._fill_picker(self._bank.patterns() if self._bank else ())
            self._fill_list()
            self._fill_detail()
        finally:
            self._loading = False

    # -- internals ----------------------------------------------------------

    def _fill_picker(self, patterns) -> None:
        """Offer patterns as the machine names them, with their own 8-char name."""
        current = self.pattern_picker.currentData()
        self.pattern_picker.clear()
        for i in range(L.NUM_PATTERNS):
            name = patterns[i].name if i < len(patterns) else ""
            label = f"{pattern_label(i)}  {name}" if name else pattern_label(i)
            self.pattern_picker.addItem(label, i)
        if current is not None:
            self.pattern_picker.setCurrentIndex(int(current))

    def _fill_list(self) -> None:
        row = self.list.currentRow()
        self.list.clear()
        if self._bank is None:
            self._headline.setText("no bank")
            return
        for i, song in enumerate(self._bank.songs()):
            label = song.name or "— unnamed —"
            mark = "" if song.is_blank else f"  ({song.length})"
            self.list.addItem(f"{i + 1:02d}  {label}{mark}")
        if self.list.count():
            self.list.setCurrentRow(max(0, min(row, self.list.count() - 1)))

    def _fill_detail(self) -> None:
        song = self.song()
        for w in (
            self._name,
            self._tempo,
            self.clear_button,
            self.add_button,
            self.remove_button,
            self.up_button,
            self.down_button,
            self.pattern_picker,
        ):
            w.setEnabled(song is not None)
        if song is None:
            self.chain.setRowCount(0)
            self._headline.setText("no bank")
            self._detail.setText("")
            return

        self._name.setText(song.name)
        self._tempo.setValue(song.tempo)
        chain = song.chain
        labels = song.chain_labels()
        patterns = self._bank.patterns() if self._bank is not None else ()
        self.chain.setRowCount(len(labels))
        for row, (index, label) in enumerate(zip(chain, labels, strict=True)):
            name = patterns[index].name if index < len(patterns) else ""
            for col, text in enumerate((f"{row + 1}", label, name)):
                item = QTableWidgetItem(text)
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                )
                self.chain.setItem(row, col, item)
        self.chain.resizeColumnsToContents()

        state = "untouched default" if song.is_blank else "edited"
        self._headline.setText(
            f"Song {self._index + 1:02d} — {len(labels)} position"
            f"{'' if len(labels) == 1 else 's'}, {song.tempo:.1f} BPM ({state})."
        )
        self._detail.setText(
            f"A song chains up to {MAX_CHAIN} positions, each naming one of the "
            f"{L.NUM_PATTERNS} patterns. Name, tempo and the chain are decoded "
            "from a bank saved on the hardware with a song in it; tempo lock, "
            "mute hold and next-song are zero in every bank seen so far, so "
            "this editor leaves them alone rather than guessing at them."
        )

    # -- edits --------------------------------------------------------------

    def _on_row(self, row: int) -> None:
        if row < 0:
            return
        self._index = row
        if not self._loading:
            self._fill_detail()

    def _edited(self) -> None:
        # Refilling the list and the fields writes to widgets that have signals
        # on them; the guard stops a redraw from looking like a second edit.
        self._loading = True
        try:
            self._fill_list()
            self._fill_detail()
        finally:
            self._loading = False
        self.songEdited.emit()

    def _rename(self) -> None:
        song = self.song()
        if song is None or self._loading:
            return
        if self._name.text() == song.name:
            return
        song.set_name(self._name.text())
        self._edited()

    def _retempo(self, value: float) -> None:
        song = self.song()
        if song is None or self._loading:
            return
        if abs(song.tempo - value) < 1e-9:
            return
        song.set_tempo(value)
        self._edited()

    def selected_position(self) -> int:
        return self.chain.currentRow()

    def add_pattern(self) -> None:
        song = self.song()
        if song is None:
            return
        index = self.pattern_picker.currentData()
        try:
            song.append_pattern(int(index))
        except Exception as exc:  # invariant: chain is full
            QMessageBox.warning(self, "Cannot add", str(exc))
            return
        self._edited()
        self.chain.setCurrentCell(song.length - 1, 0)

    def remove_position(self) -> None:
        song = self.song()
        position = self.selected_position()
        if song is None or position < 0:
            return
        try:
            song.remove_position(position)
        except Exception as exc:  # invariant: a song plays at least one pattern
            QMessageBox.warning(self, "Cannot remove", str(exc))
            return
        self._edited()
        self.chain.setCurrentCell(min(position, song.length - 1), 0)

    def move_position(self, delta: int) -> None:
        song = self.song()
        position = self.selected_position()
        if song is None or position < 0:
            return
        song.move_position(position, delta)
        target = max(0, min(song.length - 1, position + delta))
        self._edited()
        self.chain.setCurrentCell(target, 0)

    def clear_song(self) -> None:
        song = self.song()
        if song is None:
            return
        answer = QMessageBox.question(
            self,
            "Clear song",
            f"Reset song {self._index + 1:02d} to the machine's default "
            "(blank name, 120.0 BPM, one position playing A.01)?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        song.clear()
        self._edited()
