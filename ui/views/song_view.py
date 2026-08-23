"""Song view — honest report on the still-undecoded song area (TDD §2.1 / §10.1).

WHY THIS VIEW SHOWS BYTES, NOT SONGS
    `Bank.songs()` is deliberately empty. WF2 kept the whole span between the
    pattern area and the mono sample headers inside the verbatim raw region
    "mid", which is what makes the round-trip gate byte-identical. The 64 song
    blocks and the shared song-event area live inside that span, undecoded.
    Inventing a song decoder here would be a guess written into the UI, so the
    view reports what is actually known: the region is preserved, here is how
    big it is, and here are the bytes at the VERIFIED region offsets.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem,
)

from core.bank import Bank
from ui.theme import PALETTE
import codec.layout as L


#: First byte of the verbatim "mid" raw region, i.e. just past the patterns.
MID_START = L.ADDR_PATTERN_DATA + L.NUM_PATTERNS * L.CHUNK_PATTERN
#: How many leading bytes of each 528-byte song block the table previews.
PREVIEW_BYTES = 16


class SongView(QWidget):
    """Read-only report on the song / song-event area."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bank: Bank | None = None

        self._headline = QLabel("")
        self._headline.setStyleSheet(f"color: {PALETTE.lcd};")
        self._headline.setWordWrap(True)
        self._detail = QLabel("")
        self._detail.setStyleSheet(f"color: {PALETTE.muted};")
        self._detail.setWordWrap(True)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(
            ["song", "file offset", f"first {PREVIEW_BYTES} bytes (undecoded)"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)

        head = QHBoxLayout()
        head.addWidget(QLabel("Songs"))
        head.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addLayout(head)
        layout.addWidget(self._headline)
        layout.addWidget(self._detail)
        layout.addWidget(self.table)
        self.reload()

    # -- binding ------------------------------------------------------------
    def bind_bank(self, bank: Bank | None) -> None:
        self._bank = bank
        self.reload()

    def mid_region_size(self) -> int:
        """Bytes of the verbatim region that carries the song area (0 if none)."""
        if self._bank is None or not self._bank.raw_regions.has("mid"):
            return 0
        return len(self._bank.raw_regions.get("mid"))

    def reload(self) -> None:
        self.table.setRowCount(0)
        if self._bank is None:
            self._headline.setText("no bank")
            self._detail.setText("")
            return

        decoded = len(self._bank.songs())
        mid = self.mid_region_size()
        if mid == 0:
            self._headline.setText(
                f"{L.NUM_SONGS} songs + events preserved verbatim — decode later.")
            self._detail.setText(
                "This bank has no 'mid' region (PSG save), so the song area is "
                "held inside the whole-image raw region instead. Nothing is lost; "
                "the writer replays it byte for byte.")
            return

        self._headline.setText(
            f"{L.NUM_SONGS} songs + events preserved verbatim — decode later. "
            f"{decoded} decoded so far.")
        self._detail.setText(
            f"Raw region 'mid' holds {mid:,} B (file 0x{MID_START:X}–"
            f"0x{MID_START + mid:X}). Songs begin at 0x{L.ADDR_SONG_DATA:X} "
            f"({L.NUM_SONGS} × {L.CHUNK_SONG} B = "
            f"{L.NUM_SONGS * L.CHUNK_SONG:,} B); the shared event area begins at "
            f"0x{L.ADDR_SONG_EVENT_DATA:X} ({L.CHUNK_SONG_EVENT} B per event, "
            f"max {L.MAX_SONG_EVENTS:,}). No field offsets inside a song block "
            "are proven, so none are shown as values.")
        self._fill_rows(self._bank.raw_regions.get("mid"))

    # -- internals ----------------------------------------------------------
    def _fill_rows(self, mid: bytes) -> None:
        base = L.ADDR_SONG_DATA - MID_START
        rows = []
        for i in range(L.NUM_SONGS):
            start = base + i * L.CHUNK_SONG
            if start < 0 or start + PREVIEW_BYTES > len(mid):
                break
            rows.append((i, L.ADDR_SONG_DATA + i * L.CHUNK_SONG,
                         mid[start:start + PREVIEW_BYTES].hex(" ")))
        self.table.setRowCount(len(rows))
        for row, (i, addr, hexed) in enumerate(rows):
            for col, text in enumerate((f"{i:02d}", f"0x{addr:X}", hexed)):
                item = QTableWidgetItem(text)
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(row, col, item)
        self.table.resizeColumnsToContents()
