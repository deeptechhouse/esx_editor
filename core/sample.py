"""
core.sample — a sample slot header (mono 40 B / stereo 44 B).

FORMAT (TDD §2.3, VERIFIED)
    Offsets are BYTE offsets relative to ADDR_SAMPLE_DATA, not frame counts.
    Empty slot sentinel: offset fields == 0xFFFFFFFF.

INVARIANTS (TDD §3.2)
    Sample names are exactly 8 bytes (the setter pads/truncates).

WF2 NOTE
    The header round-trips byte-exact (raw retained). Only the fields the
    validator and budget need are decoded here. The STEREO sample-rate field
    offset is unconfirmed (see research/CODEC_FINDINGS_LOG.md); `sample_rate`
    is only trustworthy for mono slots for now.
"""

from __future__ import annotations

import struct

from core.errors import InvariantError

EMPTY_OFFSET = 0xFFFFFFFF
NAME_LEN = 8
MONO_SIZE = 40
STEREO_SIZE = 44


class SampleSlot:
    """One sample header. `stereo` selects the 44-byte layout and slot pool."""

    __slots__ = ("_raw", "_stereo", "_index")

    def __init__(self, raw: bytes, stereo: bool, index: int):
        expected = STEREO_SIZE if stereo else MONO_SIZE
        if len(raw) != expected:
            raise InvariantError(
                f"{'stereo' if stereo else 'mono'} sample header must be "
                f"{expected} bytes, got {len(raw)}"
            )
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
        """True if the slot's channel-1 offset holds the empty sentinel."""
        return struct.unpack_from(">I", self._raw, 8)[0] == EMPTY_OFFSET

    @property
    def name_bytes(self) -> bytes:
        return bytes(self._raw[:NAME_LEN])

    @property
    def name(self) -> str:
        return self.name_bytes.decode("ascii", "replace").rstrip("\x00 ")

    def set_name(self, value: str) -> None:
        """Set the slot name; pads/truncates to exactly 8 bytes (invariant)."""
        raw = value.encode("ascii", "replace")[:NAME_LEN].ljust(NAME_LEN, b" ")
        if len(raw) != NAME_LEN:
            raise InvariantError("sample name must encode to exactly 8 bytes")
        self._raw[:NAME_LEN] = raw

    @property
    def offset_start(self) -> int:
        """Start byte offset of channel 1 PCM, relative to ADDR_SAMPLE_DATA."""
        return struct.unpack_from(">I", self._raw, 8)[0]

    @property
    def offset_end(self) -> int:
        return struct.unpack_from(">I", self._raw, 12)[0]

    @property
    def sample_rate(self) -> int:
        """The sample's ORIGINAL rate (mono header, offset 28).

        Trustworthy for mono only; the stereo rate offset is unconfirmed.
        """
        return struct.unpack_from(">I", self._raw, 28)[0]

    @property
    def stored_tune(self) -> float:
        """The raw packed tune value. (Full decode deferred to a later WF.)"""
        raise NotImplementedError

    def musical_tune(self) -> float:
        """Transposition with rate-compensation removed (deferred to a later WF)."""
        raise NotImplementedError

    def to_bytes(self) -> bytes:
        return bytes(self._raw)

    @classmethod
    def from_bytes(cls, raw: bytes, stereo: bool, index: int) -> SampleSlot:
        return cls(raw, stereo, index)
