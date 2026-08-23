"""Global view — the 192-byte global parameter block, shown honestly (TDD §2.1).

WHY A HEX DUMP AND NOT FIELDS
    The block round-trips byte-exact, but no individual field offset inside it
    is proven: `GlobalParameters.midi_channel` still raises NotImplementedError
    on purpose. Rendering a "MIDI channel: 1" spinbox here would be a guess
    presented as fact, and the user would have no way to tell. So the view
    states the size, states that the block is retained verbatim, and dumps the
    bytes so a hardware diff can identify fields later.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPlainTextEdit,
)

from core.bank import Bank
from ui.theme import PALETTE, TYPE
import codec.layout as L


#: Bytes per line in the dump.
DUMP_STRIDE = 16


def hex_dump(data: bytes, base: int = 0, stride: int = DUMP_STRIDE) -> str:
    """Classic offset / hex / ASCII dump. Pure function — easy to unit-test."""
    lines = []
    for start in range(0, len(data), stride):
        chunk = data[start:start + stride]
        hexed = " ".join(f"{b:02x}" for b in chunk).ljust(stride * 3 - 1)
        ascii_ = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{base + start:08X}  {hexed}  |{ascii_}|")
    return "\n".join(lines)


class GlobalView(QWidget):
    """Read-only report on the bank-wide global parameter block."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bank: Bank | None = None

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
            f"color: {PALETTE.lcd}; background: {PALETTE.lcd_bg};")

        head = QHBoxLayout()
        head.addWidget(QLabel("Global parameters"))
        head.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addLayout(head)
        layout.addWidget(self._headline)
        layout.addWidget(self._detail)
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

    def reload(self) -> None:
        raw = self.block_bytes()
        if not raw:
            self._headline.setText("no bank")
            self._detail.setText("")
            self.dump.setPlainText("")
            return
        self._headline.setText(
            f"{len(raw)} B global block retained verbatim at "
            f"0x{L.ADDR_GLOBAL_PARAMETERS:X} — field offsets unproven.")
        self._detail.setText(
            "MIDI channel, tempo mode, metronome and the rest are not decoded: "
            "GlobalParameters.midi_channel raises NotImplementedError rather "
            "than return a guess. The bytes below are what the machine wrote "
            "and what the writer replays unchanged.")
        self.dump.setPlainText(hex_dump(raw, L.ADDR_GLOBAL_PARAMETERS))
