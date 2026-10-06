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
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
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
    FACTORY_DRUM_NOTES,
    MAX_CC,
    MAX_NOTE,
    NUM_CC_ASSIGN,
    note_name,
)
from midi.factory import describe as describe_midi
from midi.factory import midi_input
from midi.ports import ControlChange, NoteOn
from ui.midi_names import CHANNEL_MODE_FIRST, cc_label, note_choice_label
from ui.theme import PALETTE, SPACE, TYPE
from ui.widgets.lazy_choice import LazyChoiceBox

#: How often Learn drains the MIDI input, in ms. Fast enough that a knob nudge
#: registers instantly; slow enough to be free.
LEARN_POLL_MS = 30
#: Learn gives up after this long rather than listening forever, so a forgotten
#: armed row cannot silently capture a stray message an hour later.
LEARN_TIMEOUT_MS = 15_000

#: Bytes per line in the dump.
DUMP_STRIDE = 16


# O(d) time, O(d) space — d = bytes dumped
def hex_dump(data: bytes, base: int = 0, stride: int = DUMP_STRIDE) -> str:
    """Classic offset / hex / ASCII dump. Pure function — easy to unit-test."""
    lines = []
    # O(d) time, O(d) space — d = bytes dumped (d / w lines of w bytes)
    for start in range(0, len(data), stride):
        chunk = data[start : start + stride]
        # bigo-lint: disable=BIGO006 — amortised: each line's join walks only its own w-byte chunk, so every byte is visited once overall
        # O(w) time, O(w) space — w = stride bytes per line (DUMP_STRIDE, 16 by default)
        hexed = " ".join(f"{b:02x}" for b in chunk).ljust(stride * 3 - 1)
        # bigo-lint: disable=BIGO006 — amortised: each line's join walks only its own w-byte chunk, so every byte is visited once overall
        # O(w) time, O(w) space — w = stride bytes per line (DUMP_STRIDE, 16 by default)
        ascii_ = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{base + start:08X}  {hexed}  |{ascii_}|")
    return "\n".join(lines)


class GlobalView(QWidget):
    """Edit the bank-wide MIDI mapping; report the rest of the block honestly."""

    globalsEdited = Signal()

    # O(p) time, O(p) space — p = MIDI input ports, enumerated only when the input gives no reason (no bank is bound yet)
    def __init__(self, parent=None):
        super().__init__(parent)
        self._bank: Bank | None = None
        self._loading = False

        # Drum note numbers: part, the note it answers to, and a per-row Learn.
        self.notes = QTableWidget(0, 3)
        self.notes.setHorizontalHeaderLabels(["part", "note", ""])
        self.notes.verticalHeader().setVisible(False)
        self.notes.setAlternatingRowColors(True)
        # The last column holds Learn buttons at a fixed width; stretching it
        # made a 290 px column of small buttons.
        self.notes.horizontalHeader().setStretchLastSection(False)

        # CC assign: the knob, the CC that drives it, and a per-row Learn.
        self.midi = midi_input()
        # Which single row is armed, as (which table, row index). One at a
        # time across BOTH tables: two armed rows would make the next gesture
        # ambiguous, and silently picking one is the kind of guess this project
        # does not make.
        self._learning: tuple[str, int] | None = None
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
            "Pick a note from the list (C-1 to G9, the machine's full range), "
            "or press Learn and hit the pad or key on your MIDI device. "
            "VERIFIED against the manual's factory table (p.90)."
        )
        self._notes_caption.setStyleSheet(f"color: {PALETTE.muted};")
        self._notes_caption.setWordWrap(True)
        self._notes_warning = QLabel("")
        self._notes_warning.setStyleSheet(f"color: {PALETTE.amber};")
        self._notes_warning.setWordWrap(True)
        self.factory_notes_button = QPushButton("Factory notes")
        self.factory_notes_button.setToolTip(
            "Restore the manual's printed factory assignments:\n"
            "Drum1 C2, Drum2 D2, Drum3 E2 … Audio in C0."
        )
        self.factory_notes_button.clicked.connect(self.reset_drum_notes)
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
        # Deliberately NOT describe_midi(): that enumerates the MIDI hardware,
        # and building a tab must never block on a device. CoreMIDI enumeration
        # hung the test suite from here — a view's constructor has no business
        # talking to hardware. Devices are listed when the user asks (Rescan)
        # or when a Learn actually needs one.
        self._midi_status = QLabel(self._idle_status())
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
        left.addWidget(self._notes_warning)
        left.addWidget(self.notes, 1)
        notes_tools = QHBoxLayout()
        notes_tools.addStretch(1)
        notes_tools.addWidget(self.factory_notes_button)
        left.addLayout(notes_tools)

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
    # O((r + q)·(v + p)) time, O((r + q)·v) space — r = 13 drum-note rows; q = 33 CC rows; v = 128 picker values; p = MIDI input ports, enumerated per Learn row only when the input gives no reason
    def bind_bank(self, bank: Bank | None) -> None:
        self._bank = bank
        self.reload()

    # O(1) time, O(1) space
    def block_bytes(self) -> bytes:
        """The raw global block, or b'' when no bank is open."""
        if self._bank is None:
            return b""
        return self._bank.globals.to_bytes()

    # O(1) time, O(1) space
    def globals_or_none(self):
        return None if self._bank is None else self._bank.globals

    # O((r + q)·(v + p)) time, O((r + q)·v) space — r = 13 drum-note rows; q = 33 CC rows; v = 128 picker values; p = MIDI input ports, enumerated per Learn row only when the input gives no reason
    def reload(self) -> None:
        self._loading = True
        try:
            self._reload()
        finally:
            self._loading = False

    # O((r + q)·(v + p)) time, O((r + q)·v) space — r = 13 drum-note rows; q = 33 CC rows; v = 128 picker values; p = MIDI input ports, enumerated per Learn row only when the input gives no reason
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

    # O(r·(v + p)) time, O(r·v) space — r = 13 drum-note rows; v = 128 note values per picker; p = MIDI input ports, enumerated per row only when the input gives no reason
    def _fill_notes(self) -> None:
        params = self.globals_or_none()
        if params is None:
            return
        self.notes.setRowCount(len(DRUM_NOTE_PARTS))
        # O(r·(v + p)) time, O(r·v) space — r = 13 drum-note rows; v = 128 note values per picker; p = MIDI input ports, enumerated per row only when the input gives no reason
        for row, part in enumerate(DRUM_NOTE_PARTS):
            self.notes.setItem(row, 0, _cell(part))

            # Every note the machine accepts: C-1 to G9 (manual p.90), which
            # is the whole MIDI range. Listing all of them means never having
            # to know that C2 is 36. Built on first open — see LazyChoiceBox.
            picker = LazyChoiceBox(
                range(MAX_NOTE + 1),
                lambda n: note_choice_label(n, note_name(n)),
            )
            picker.set_value(params.drum_note(row))
            picker.valueChanged.connect(lambda value, r=row: self._set_note(r, value))
            self.notes.setCellWidget(row, 1, picker)

            learn = QPushButton("Learn")
            learn.setCheckable(True)
            learn.setEnabled(self.midi.available)
            learn.setToolTip(
                "Arm this part, then hit the pad or key on your MIDI device."
                if self.midi.available
                else self._unavailable_reason()
            )
            learn.clicked.connect(lambda _=False, r=row: self.toggle_learn("note", r))
            self.notes.setCellWidget(row, 2, learn)

        self.notes.resizeColumnsToContents()
        self.notes.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.notes.setColumnWidth(2, self._learn_column_width())
        self._refresh_notes_warning()

    # O((r + q)·(v + p)) time, O((r + q)·v) space — r = 13 drum-note rows; q = 33 CC rows; v = 128 picker values; p = MIDI input ports, enumerated per Learn row only when the input gives no reason
    def reset_drum_notes(self) -> None:
        """Restore the manual's factory table and redraw."""
        params = self.globals_or_none()
        if params is None or params.drum_notes() == FACTORY_DRUM_NOTES:
            return
        params.reset_drum_notes()
        self.reload()
        self.globalsEdited.emit()

    # O(r log r) time, O(r) space — r = 13 drum-note parts
    def _refresh_notes_warning(self) -> None:
        params = self.globals_or_none()
        if params is None:
            self._notes_warning.setText("")
            return
        clashes = params.duplicate_drum_notes()
        if not clashes:
            self._notes_warning.setText("")
            return
        # O(r log r) time, O(r) space — r = 13 drum-note parts (sorted clashes)
        shared = "; ".join(
            f"{note_name(number)} triggers "
            # O(r) time, O(r) space — r = parts sharing this note (at most 13)
            + " + ".join(DRUM_NOTE_PARTS[p] for p in parts)
            for number, parts in sorted(clashes.items())
        )
        self._notes_warning.setText(
            f"Shared: {shared}. The manual says these sound together — "
            "deliberate, but check it is meant."
        )

    # O(1) time, O(1) space
    def _learn_column_width(self) -> int:
        """Width for a Learn column, from the button rather than the header.

        resizeColumnsToContents measures ITEMS, not cell widgets, so a column
        of buttons comes out narrower than the buttons in it. Measured from the
        wider of the two captions so the column does not jump when a row arms.
        """
        probe = QPushButton("Listening…")
        width = probe.sizeHint().width() + SPACE.md
        probe.deleteLater()
        return width

    # O(q·(v + p)) time, O(q·v) space — q = 33 CC rows; v = 128 CC values per picker; p = MIDI input ports, enumerated per row only when the input gives no reason
    def _fill_cc(self) -> None:
        params = self.globals_or_none()
        if params is None:
            return
        self.cc.setRowCount(NUM_CC_ASSIGN)
        # O(q·(v + p)) time, O(q·v) space — q = 33 CC rows; v = 128 CC values per picker; p = MIDI input ports, enumerated per row only when the input gives no reason
        for row in range(NUM_CC_ASSIGN):
            self.cc.setItem(row, 0, _cell(f"{row + 1}"))
            self.cc.setItem(row, 1, _cell(CC_ASSIGN_NAMES[row]))

            # Every legal CC is offered, named where the MIDI spec names one.
            # The list is the form the user asked for; the numbers are what
            # actually travel down the cable.
            picker = LazyChoiceBox(range(MAX_CC + 1), cc_label)
            picker.set_value(params.cc_assignment(row))
            picker.valueChanged.connect(lambda value, r=row: self._set_cc(r, value))
            self.cc.setCellWidget(row, 2, picker)

            learn = QPushButton("Learn")
            learn.setCheckable(True)
            learn.setEnabled(self.midi.available)
            learn.setToolTip(
                "Arm this row, then move the control on your MIDI device."
                if self.midi.available
                else self._unavailable_reason()
            )
            learn.clicked.connect(lambda _=False, r=row: self.toggle_learn("cc", r))
            self.cc.setCellWidget(row, 3, learn)

        self.cc.resizeColumnsToContents()
        self.cc.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        self.cc.setColumnWidth(3, self._learn_column_width())
        self._refresh_cc_warning()

    # -- MIDI Learn ----------------------------------------------------------

    # O(q log q) time, O(q) space — q = 33 CC rows
    def _refresh_cc_warning(self) -> None:
        params = self.globals_or_none()
        if params is None:
            self._cc_warning.setText("")
            return
        clashes = params.duplicate_cc_rows()
        if not clashes:
            self._cc_warning.setText("")
            return
        # O(q log q) time, O(q) space — q = 33 CC rows (sorted clashes)
        shared = "; ".join(
            # O(q) time, O(q) space — q = knobs sharing this CC (at most 33)
            f"CC {cc} drives " + " + ".join(CC_ASSIGN_NAMES[r] for r in rows)
            for cc, rows in sorted(clashes.items())
        )
        self._cc_warning.setText(f"Shared: {shared}. Legal, but check it is meant.")

    # O(p) time, O(p) space — p = MIDI input ports, enumerated only when the input gives no reason
    def _idle_status(self) -> str:
        """Status line that costs nothing — no device enumeration."""
        if not self.midi.available:
            return self._unavailable_reason()
        return "MIDI Learn ready — press Rescan MIDI to list connected devices."

    # O(p) time, O(p) space — p = MIDI input ports enumerated by describe_midi() when the input gives no reason
    def _unavailable_reason(self) -> str:
        """Why Learn is off, according to the input THIS view holds.

        Not describe_midi(): that re-probes the process-wide factory, which can
        disagree with the injected input — and a button must explain the object
        it is actually wired to, or the explanation is fiction.
        """
        reason = getattr(self.midi, "reason", "")
        return reason or describe_midi()

    # O(p + (r + q)·(v + p)) time, O((r + q)·v + p) space — r = 13 drum-note rows; q = 33 CC rows; v = 128 picker values; p = MIDI input ports, enumerated per Learn row only when the input gives no reason
    def rescan_midi(self) -> None:
        """Re-probe the MIDI stack, for a device plugged in after launch."""
        from midi import factory

        factory._backend_error.cache_clear()
        self.stop_learn(captured=False)
        self.midi = factory.midi_input()
        # Rescan is the one place enumeration is expected, because the user
        # asked for it and is waiting for the answer.
        self._midi_status.setText(describe_midi())
        self.reload()

    # O(p) time, O(p) space — p = MIDI input ports listed
    def toggle_learn(self, kind: str, row: int) -> None:
        """Arm one row for the next matching gesture, or disarm it.

        `kind` is "cc" (listen for a knob) or "note" (listen for a pad). The
        armed row ignores the other kind entirely, so nudging a knob cannot
        set a drum note and hitting a pad cannot set a CC.
        """
        if self._learning == (kind, row):
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
            self._set_learn_checked(kind, row, False)
            return
        try:
            self.midi.open(names[0])
        except Exception as exc:  # a device can vanish between listing and open
            self._midi_status.setText(f"Could not open {names[0]}: {exc}")
            self._set_learn_checked(kind, row, False)
            return
        self._learning = (kind, row)
        self._set_learn_checked(kind, row, True)
        target = CC_ASSIGN_NAMES[row] if kind == "cc" else DRUM_NOTE_PARTS[row]
        gesture = "move the control" if kind == "cc" else "hit the pad or key"
        self._midi_status.setText(f"Listening on {names[0]} — {gesture} for {target}.")
        self._learn_timer.start()
        self._learn_deadline.start()

    # O(p) time, O(p) space — p = MIDI input ports, enumerated only when the input gives no reason
    def stop_learn(self, *, captured: bool) -> None:
        """Disarm, close the port, and say what happened."""
        self._learn_timer.stop()
        self._learn_deadline.stop()
        armed = self._learning
        self._learning = None
        if armed is not None:
            self._set_learn_checked(armed[0], armed[1], False)
            if not captured:
                self._midi_status.setText(self._idle_status())
        self.midi.close()

    # O(1) time, O(1) space
    def _learn_button(self, kind: str, row: int):
        table, column = (self.cc, 3) if kind == "cc" else (self.notes, 2)
        return table.cellWidget(row, column)

    # O(1) time, O(1) space
    def _set_learn_checked(self, kind: str, row: int, checked: bool) -> None:
        button = self._learn_button(kind, row)
        if button is not None:
            button.setChecked(checked)
            button.setText("Listening…" if checked else "Learn")

    # O(n + p) time, O(n + p) space — n = MIDI messages queued since the last 30 ms poll; p = MIDI input ports, enumerated only on the no-bank path
    def _poll_midi(self) -> None:
        if self._learning is None:
            return
        kind, row = self._learning
        wanted = ControlChange if kind == "cc" else NoteOn
        # Filter by kind BEFORE taking the first: a controller that sends a CC
        # alongside every pad hit would otherwise capture the wrong one.
        # O(n) time, O(n) space — n = MIDI messages queued since the last poll
        matching = [m for m in self.midi.poll() if isinstance(m, wanted)]
        if not matching:
            return
        first = matching[0]
        params = self.globals_or_none()
        if params is None:
            self.stop_learn(captured=False)
            return
        if kind == "cc":
            params.set_cc_assignment(row, first.number)
            self._sync_picker(self.cc, row, 2, first.number)
            self._refresh_cc_warning()
            note = (
                "  Note: that is a reserved channel-mode number."
                if first.number >= CHANNEL_MODE_FIRST
                else ""
            )
            summary = (
                f"{CC_ASSIGN_NAMES[row]} → CC {first.number} "
                f"(channel {first.display_channel}).{note}"
            )
        else:
            params.set_drum_note(row, first.number)
            self._sync_picker(self.notes, row, 1, first.number)
            self._refresh_notes_warning()
            summary = (
                f"{DRUM_NOTE_PARTS[row]} → {note_name(first.number)} "
                f"({first.number}, channel {first.display_channel})."
            )
        self.globalsEdited.emit()
        self.stop_learn(captured=True)
        self._midi_status.setText(summary)

    @staticmethod
    # O(v) time, O(1) space — v = 128 picker values (index lookup once the list is built)
    def _sync_picker(table, row: int, column: int, value: int) -> None:
        """Move a picker to match the model without re-entering the edit path."""
        picker = table.cellWidget(row, column)
        if picker is not None:
            picker.set_value(value)

    # O(r) time, O(r) space — r = 13 drum-note parts (clash refresh)
    def _set_note(self, part: int, value: int) -> None:
        params = self.globals_or_none()
        if params is None or self._loading or params.drum_note(part) == value:
            return
        params.set_drum_note(part, value)
        self._refresh_notes_warning()
        self.globalsEdited.emit()

    # O(q) time, O(q) space — q = 33 CC rows (clash refresh)
    def _set_cc(self, row: int, value: int) -> None:
        params = self.globals_or_none()
        if params is None or self._loading or params.cc_assignment(row) == value:
            return
        params.set_cc_assignment(row, value)
        self._refresh_cc_warning()
        self.globalsEdited.emit()


# O(1) time, O(1) space
def _cell(text: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    return item
