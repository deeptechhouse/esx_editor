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

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
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
from midi.factory import describe as describe_midi
from midi.factory import midi_input
from ui.midi_names import CHANNEL_MODE_FIRST, cc_label
from ui.theme import PALETTE, SPACE, TYPE

#: How often Learn drains the MIDI input, in ms. Fast enough that a knob nudge
#: registers instantly; slow enough to be free.
LEARN_POLL_MS = 30
#: Learn gives up after this long rather than listening forever, so a forgotten
#: armed row cannot silently capture a stray message an hour later.
LEARN_TIMEOUT_MS = 15_000

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

        # CC assign: the knob, the CC that drives it, and a per-row Learn.
        self.midi = midi_input()
        self._learning_row: int | None = None
        self._learn_timer = QTimer(self)
        self._learn_timer.setInterval(LEARN_POLL_MS)
        self._learn_timer.timeout.connect(self._poll_midi)
        self._learn_deadline = QTimer(self)
        self._learn_deadline.setSingleShot(True)
        self._learn_deadline.setInterval(LEARN_TIMEOUT_MS)
        self._learn_deadline.timeout.connect(lambda: self.stop_learn(captured=False))

        self.cc = QTableWidget(0, 4)
        self.cc.setHorizontalHeaderLabels(["#", "knob", "CC number", ""])
        self.cc.verticalHeader().setVisible(False)
        self.cc.setAlternatingRowColors(True)
        self.cc.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.cc.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        self.cc.horizontalHeader().setStretchLastSection(False)

        self._notes_caption = QLabel(
            "Drum note numbers — VERIFIED against the manual's factory table "
            "(p.90). Parts sharing a note sound together, which is deliberate."
        )
        self._notes_caption.setStyleSheet(f"color: {PALETTE.muted};")
        self._notes_caption.setWordWrap(True)
        self._cc_caption = QLabel(
            "Pick a CC from the list, or press Learn and move the control on "
            "your MIDI device. Row order confirmed against an independent "
            "editor, 33 of 33."
        )
        self._cc_caption.setStyleSheet(f"color: {PALETTE.muted};")
        self._cc_caption.setWordWrap(True)
        # Two knobs on one CC is legal and occasionally wanted, so this warns
        # rather than refuses — but it is the likeliest way a remap goes wrong.
        self._cc_warning = QLabel("")
        self._cc_warning.setStyleSheet(f"color: {PALETTE.amber};")
        self._cc_warning.setWordWrap(True)
        self._midi_status = QLabel(describe_midi())
        self._midi_status.setStyleSheet(f"color: {PALETTE.muted};")
        self._midi_status.setWordWrap(True)
        self.rescan_button = QPushButton("Rescan MIDI")
        self.rescan_button.setToolTip(
            "Look for MIDI inputs again — use after plugging a device in."
        )
        self.rescan_button.clicked.connect(self.rescan_midi)

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
        midi_row = QHBoxLayout()
        midi_row.addWidget(self._midi_status, 1)
        midi_row.addWidget(self.rescan_button)
        right.addLayout(midi_row)

        tables = QHBoxLayout()
        tables.addLayout(left, 1)
        tables.addLayout(right, 1)

        layout = QVBoxLayout(self)
        layout.addLayout(head)
        layout.addWidget(self._headline)
        layout.addWidget(self._detail)
        layout.addLayout(tables, 5)
        layout.addWidget(QLabel("Undecoded remainder"))
        layout.addWidget(self.dump, 1)
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

            picker = QComboBox()
            # Every legal CC is offered, named where the MIDI spec names one.
            # The list is the form the user asked for; the numbers are what
            # actually travel down the cable.
            for number in range(MAX_CC + 1):
                picker.addItem(cc_label(number), number)
            picker.setCurrentIndex(params.cc_assignment(row))
            picker.currentIndexChanged.connect(
                lambda index, r=row: self._set_cc(r, index)
            )
            self.cc.setCellWidget(row, 2, picker)

            learn = QPushButton("Learn")
            learn.setCheckable(True)
            learn.setEnabled(self.midi.available)
            learn.setToolTip(
                "Arm this row, then move the control on your MIDI device."
                if self.midi.available
                else self._unavailable_reason()
            )
            learn.clicked.connect(lambda _=False, r=row: self.toggle_learn(r))
            self.cc.setCellWidget(row, 3, learn)

        self.cc.resizeColumnsToContents()
        self.cc.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        # resizeColumnsToContents measures ITEMS, not cell widgets, so the
        # Learn column came out narrower than its own buttons and rendered
        # them as "ear". Size it from the widget that actually lives there,
        # and from the wider of its two captions so it does not jump when the
        # button switches to "Listening…".
        probe = QPushButton("Listening…")
        self.cc.setColumnWidth(3, probe.sizeHint().width() + SPACE.md)
        probe.deleteLater()
        self._refresh_cc_warning()

    # -- MIDI Learn ----------------------------------------------------------

    def _unavailable_reason(self) -> str:
        """Why Learn is off, according to the input THIS view holds.

        Not describe_midi(): that re-probes the process-wide factory, which can
        disagree with the injected input — and a button must explain the object
        it is actually wired to, or the explanation is fiction.
        """
        reason = getattr(self.midi, "reason", "")
        return reason or describe_midi()

    def rescan_midi(self) -> None:
        """Re-probe the MIDI stack, for a device plugged in after launch."""
        from midi import factory

        factory._backend_error.cache_clear()
        self.stop_learn(captured=False)
        self.midi = factory.midi_input()
        self._midi_status.setText(describe_midi())
        self.reload()

    def toggle_learn(self, row: int) -> None:
        """Arm `row` for the next control change, or disarm it if already armed.

        Only one row can be armed at a time. Arming a second would make the
        next knob move ambiguous, and silently picking one of them is exactly
        the kind of guess this project does not make.
        """
        if self._learning_row == row:
            self.stop_learn(captured=False)
            return
        self.stop_learn(captured=False)
        if not self.midi.available:
            return
        names = self.midi.ports()
        if not names:
            self._midi_status.setText(
                "No MIDI input connected. Plug a device in and press Rescan MIDI."
            )
            self._set_learn_checked(row, False)
            return
        try:
            self.midi.open(names[0])
        except Exception as exc:  # a device can vanish between listing and open
            self._midi_status.setText(f"Could not open {names[0]}: {exc}")
            self._set_learn_checked(row, False)
            return
        self._learning_row = row
        self._set_learn_checked(row, True)
        self._midi_status.setText(
            f"Listening on {names[0]} — move the control for {CC_ASSIGN_NAMES[row]}."
        )
        self._learn_timer.start()
        self._learn_deadline.start()

    def stop_learn(self, *, captured: bool) -> None:
        """Disarm, close the port, and say what happened."""
        self._learn_timer.stop()
        self._learn_deadline.stop()
        row = self._learning_row
        self._learning_row = None
        if row is not None:
            self._set_learn_checked(row, False)
            if not captured:
                self._midi_status.setText(describe_midi())
        self.midi.close()

    def _set_learn_checked(self, row: int, checked: bool) -> None:
        button = self.cc.cellWidget(row, 3)
        if button is not None:
            button.setChecked(checked)
            button.setText("Listening…" if checked else "Learn")

    def _poll_midi(self) -> None:
        row = self._learning_row
        if row is None:
            return
        messages = self.midi.poll()
        if not messages:
            return
        # First message wins. A knob sweep sends hundreds; they are all the
        # same control, and the first one already answered the question.
        first = messages[0]
        params = self.globals_or_none()
        if params is not None:
            params.set_cc_assignment(row, first.number)
            picker = self.cc.cellWidget(row, 2)
            if picker is not None:
                picker.blockSignals(True)
                picker.setCurrentIndex(first.number)
                picker.blockSignals(False)
            self._refresh_cc_warning()
            self.globalsEdited.emit()
        self.stop_learn(captured=True)
        self._midi_status.setText(
            f"{CC_ASSIGN_NAMES[row]} → CC {first.number} "
            f"(channel {first.display_channel}). "
            + (
                "Note: that is a reserved channel-mode number."
                if first.number >= CHANNEL_MODE_FIRST
                else ""
            )
        )

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
        """The picker's index IS the CC number — the list is 0..127 in order."""
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
