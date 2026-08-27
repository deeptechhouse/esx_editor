"""Global view — the 192-byte global block: MIDI mapping, plus the rest as hex.

TWO KINDS OF FIELD, SHOWN DIFFERENTLY
    The drum note numbers are VERIFIED against the manual's printed factory
    table, all thirteen of them, so they get a real editor.

    The CC assign table is named: an independent editor's knob list matches the
    stored bytes 33/33 position for position, in every bank. Each row shows the
    knob it drives, and the number is editable — which is the whole point, since
    the reason to touch this table is to make a controller that does not follow
    the ESX-1's default map work with it.

    Everything else in the block is undecoded and stays a hex dump. Rendering a
    "MIDI channel: 1" spinbox would be a guess presented as fact, and the user
    would have no way to tell.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

import codec.layout as L
from core.bank import Bank
from core.global_params import (
    CC_ASSIGN_NAMES,
    CC_ASSIGN_OFFSET,
    DRUM_NOTE_OFFSET,
    DRUM_NOTE_PARTS,
    MAX_CC,
    MAX_NOTE,
    NUM_CC_ASSIGN,
    note_name,
)
from ui.theme import PALETTE, TYPE

#: Bytes per line in the dump.
DUMP_STRIDE = 16


def hex_dump(data: bytes, base: int = 0, stride: int = DUMP_STRIDE) -> str:
    """Classic offset / hex / ASCII dump. Pure function — easy to unit-test."""
    lines = []
    for start in range(0, len(data), stride):
        chunk = data[start : start + stride]
        hexed = " ".join(f"{b:02x}" for b in chunk).ljust(stride * 3 - 1)
        ascii_ = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{base + start:08X}  {hexed}  |{ascii_}|")
    return "\n".join(lines)


class GlobalView(QWidget):
    """Edit the bank-wide MIDI mapping; report the rest of the block honestly."""

    globalsEdited = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bank: Bank | None = None
        self._loading = False

        # Drum note numbers: part name, editable note number, note name.
        self.notes = QTableWidget(0, 3)
        self.notes.setHorizontalHeaderLabels(["part", "note no.", "note"])
        self.notes.verticalHeader().setVisible(False)
        self.notes.setAlternatingRowColors(True)
        self.notes.horizontalHeader().setStretchLastSection(True)

        # CC assign: the knob, and the CC number that drives it.
        self.cc = QTableWidget(0, 3)
        self.cc.setHorizontalHeaderLabels(["#", "knob", "CC number"])
        self.cc.verticalHeader().setVisible(False)
        self.cc.setAlternatingRowColors(True)
        self.cc.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.cc.horizontalHeader().setStretchLastSection(False)

        self._notes_caption = QLabel(
            "Drum note numbers — VERIFIED against the manual's factory table "
            "(p.90). Parts sharing a note sound together, which is deliberate."
        )
        self._notes_caption.setStyleSheet(f"color: {PALETTE.muted};")
        self._notes_caption.setWordWrap(True)
        self._cc_caption = QLabel(
            "CC assign — point any knob at the control-change number your "
            "controller already sends. Row order confirmed against an "
            "independent editor, 33 of 33."
        )
        self._cc_caption.setStyleSheet(f"color: {PALETTE.muted};")
        self._cc_caption.setWordWrap(True)
        # Two knobs on one CC is legal and occasionally wanted, so this warns
        # rather than refuses — but it is the likeliest way a remap goes wrong.
        self._cc_warning = QLabel("")
        self._cc_warning.setStyleSheet(f"color: {PALETTE.amber};")
        self._cc_warning.setWordWrap(True)

        self._headline = QLabel("")
        self._headline.setStyleSheet(f"color: {PALETTE.lcd};")
        self._headline.setWordWrap(True)
        self._detail = QLabel("")
        self._detail.setStyleSheet(f"color: {PALETTE.muted};")
        self._detail.setWordWrap(True)

        self.dump = QPlainTextEdit()
        self.dump.setReadOnly(True)
        self.dump.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.dump.setStyleSheet(
            f"font-family: {TYPE.lcd}; font-size: {TYPE.size_lcd}px; "
            f"color: {PALETTE.lcd}; background: {PALETTE.lcd_bg};"
        )

        head = QHBoxLayout()
        head.addWidget(QLabel("Global parameters"))
        head.addStretch(1)

        left = QVBoxLayout()
        left.addWidget(QLabel("Drum note numbers"))
        left.addWidget(self._notes_caption)
        left.addWidget(self.notes, 1)

        right = QVBoxLayout()
        right.addWidget(QLabel("MIDI CC assign"))
        right.addWidget(self._cc_caption)
        right.addWidget(self._cc_warning)
        right.addWidget(self.cc, 1)

        tables = QHBoxLayout()
        tables.addLayout(left, 1)
        tables.addLayout(right, 1)

        layout = QVBoxLayout(self)
        layout.addLayout(head)
        layout.addWidget(self._headline)
        layout.addWidget(self._detail)
        layout.addLayout(tables, 3)
        layout.addWidget(QLabel("Undecoded remainder"))
        layout.addWidget(self.dump, 2)
        self.reload()

    # -- binding ------------------------------------------------------------
    def bind_bank(self, bank: Bank | None) -> None:
        self._bank = bank
        self.reload()

    def block_bytes(self) -> bytes:
        """The raw global block, or b'' when no bank is open."""
        if self._bank is None:
            return b""
        return self._bank.globals.to_bytes()

    def globals_or_none(self):
        return None if self._bank is None else self._bank.globals

    def reload(self) -> None:
        self._loading = True
        try:
            self._reload()
        finally:
            self._loading = False

    def _reload(self) -> None:
        raw = self.block_bytes()
        if not raw:
            self._headline.setText("no bank")
            self._detail.setText("")
            self.dump.setPlainText("")
            self.notes.setRowCount(0)
            self.cc.setRowCount(0)
            return
        self._fill_notes()
        self._fill_cc()
        self._headline.setText(
            f"{len(raw)} B global block at 0x{L.ADDR_GLOBAL_PARAMETERS:X} — "
            f"drum notes at +{DRUM_NOTE_OFFSET}, CC assign at "
            f"+{CC_ASSIGN_OFFSET}; the rest is retained verbatim."
        )
        self._detail.setText(
            "MIDI channel, tempo mode and metronome are still not decoded: "
            "GlobalParameters.midi_channel raises rather than return a guess. "
            "The dump below is the whole block as the machine wrote it — the "
            "two tables above are windows into it, not a separate copy."
        )
        self.dump.setPlainText(hex_dump(raw, L.ADDR_GLOBAL_PARAMETERS))

    # -- tables --------------------------------------------------------------

    def _fill_notes(self) -> None:
        params = self.globals_or_none()
        if params is None:
            return
        self.notes.setRowCount(len(DRUM_NOTE_PARTS))
        for row, part in enumerate(DRUM_NOTE_PARTS):
            self.notes.setItem(row, 0, _cell(part))
            spin = QSpinBox()
            spin.setRange(0, MAX_NOTE)
            spin.setValue(params.drum_note(row))
            spin.setKeyboardTracking(False)
            spin.valueChanged.connect(lambda value, r=row: self._set_note(r, value))
            self.notes.setCellWidget(row, 1, spin)
            self.notes.setItem(row, 2, _cell(params.drum_note_name(row)))
        self.notes.resizeColumnsToContents()

    def _fill_cc(self) -> None:
        params = self.globals_or_none()
        if params is None:
            return
        self.cc.setRowCount(NUM_CC_ASSIGN)
        for row in range(NUM_CC_ASSIGN):
            self.cc.setItem(row, 0, _cell(f"{row + 1}"))
            self.cc.setItem(row, 1, _cell(CC_ASSIGN_NAMES[row]))
            spin = QSpinBox()
            spin.setRange(0, MAX_CC)
            spin.setValue(params.cc_assignment(row))
            spin.setKeyboardTracking(False)
            spin.valueChanged.connect(lambda value, r=row: self._set_cc(r, value))
            self.cc.setCellWidget(row, 2, spin)
        self.cc.resizeColumnsToContents()
        self._refresh_cc_warning()

    def _refresh_cc_warning(self) -> None:
        params = self.globals_or_none()
        if params is None:
            self._cc_warning.setText("")
            return
        clashes = params.duplicate_cc_rows()
        if not clashes:
            self._cc_warning.setText("")
            return
        shared = "; ".join(
            f"CC {cc} drives " + " + ".join(CC_ASSIGN_NAMES[r] for r in rows)
            for cc, rows in sorted(clashes.items())
        )
        self._cc_warning.setText(f"Shared: {shared}. Legal, but check it is meant.")

    # -- edits ---------------------------------------------------------------

    def _set_note(self, part: int, value: int) -> None:
        params = self.globals_or_none()
        if params is None or self._loading or params.drum_note(part) == value:
            return
        params.set_drum_note(part, value)
        item = self.notes.item(part, 2)
        if item is not None:
            item.setText(note_name(value))
        self.globalsEdited.emit()

    def _set_cc(self, row: int, value: int) -> None:
        params = self.globals_or_none()
        if params is None or self._loading or params.cc_assignment(row) == value:
            return
        params.set_cc_assignment(row, value)
        self._refresh_cc_warning()
        self.globalsEdited.emit()


def _cell(text: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    return item
