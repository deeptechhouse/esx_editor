"""
core.sample — a sample slot header (mono 40 B / stereo 44 B).

FORMAT (TDD §2.3, VERIFIED)
    Offsets are BYTE offsets relative to ADDR_SAMPLE_DATA, not frame counts.
    Empty slot sentinel: offset fields == 0xFFFFFFFF.

SAMPLE TUNE (TDD §2.3 / §5.4, VERIFIED)
    A packed 16-bit field carrying TWO concerns at once:
        bit 15    : sign
        bits 8..14: whole semitones (0..127)
        bits 0..7 : hundredths (0..99)
    Stored tune = rate compensation + musical transposition. The UI must show
    MUSICAL tune (0.00 for an untransposed sample at any storage rate):
        musical_tune = stored_tune - 12 * log2(rate / 44100)

INVARIANTS (TDD §3.2)
    Sample names are exactly 8 bytes (the setter pads/truncates).
"""

from __future__ import annotations


class SampleSlot:
    """One sample header. `stereo` selects the 44-byte layout and slot pool.

    Undecoded header bytes are retained verbatim so the slot round-trips even
    though not every field is interpreted yet (TDD §4.1).
    """

    __slots__ = ("_raw", "_stereo", "_index")

    def __init__(self, raw: bytes, stereo: bool, index: int):
        self._raw = bytearray(raw)
        self._stereo = stereo
        self._index = index

    @property
    def index(self) -> int:
        return self._index

    @property
    def stereo(self) -> bool:
        return self._stereo

    @property
    def empty(self) -> bool:
        """True if the slot's offset fields hold the empty sentinel."""
        raise NotImplementedError

    @property
    def name(self) -> str:
        """The 8-byte name decoded for display (raw bytes, trailing pad stripped)."""
        raise NotImplementedError

    def set_name(self, value: str) -> None:
        """Set the slot name; pads/truncates to exactly 8 bytes (invariant)."""
        raise NotImplementedError

    @property
    def name_bytes(self) -> bytes:
        raise NotImplementedError

    @property
    def offset_start(self) -> int:
        """Start byte offset of channel 1 PCM, relative to ADDR_SAMPLE_DATA."""
        raise NotImplementedError

    @property
    def offset_end(self) -> int:
        raise NotImplementedError

    @property
    def sample_rate(self) -> int:
        """The sample's ORIGINAL rate as stored in the header."""
        raise NotImplementedError

    @property
    def stored_tune(self) -> float:
        """The raw packed tune value (compensation + transposition)."""
        raise NotImplementedError

    def musical_tune(self) -> float:
        """Transposition with rate-compensation removed (0.00 = untransposed)."""
        raise NotImplementedError

    def to_bytes(self) -> bytes:
        """Serialize to the 40- or 44-byte on-disk header."""
        raise NotImplementedError

    @classmethod
    def from_bytes(cls, raw: bytes, stereo: bool, index: int) -> "SampleSlot":
        raise NotImplementedError
