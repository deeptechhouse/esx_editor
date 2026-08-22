"""
core.global_params — the 192-byte global parameter block (TDD §2.1).

Global settings that apply to the whole bank/instrument. WF2 retains the block
byte-exact so it round-trips; individual field decoders (MIDI channel, tempo
mode, metronome, etc.) are layered on in the global-view workflow.
"""

from __future__ import annotations

from core.errors import InvariantError

SIZE = 192


class GlobalParameters:
    """The bank-wide global settings block (192 bytes, retained verbatim)."""

    __slots__ = ("_raw",)

    def __init__(self, raw: bytes):
        if len(raw) != SIZE:
            raise InvariantError(
                f"global parameters block must be {SIZE} bytes, got {len(raw)}")
        self._raw = bytearray(raw)

    @property
    def midi_channel(self) -> int:
        """(Field decode deferred to the global-view workflow.)"""
        raise NotImplementedError

    def to_bytes(self) -> bytes:
        """Serialize back to the 192-byte block."""
        return bytes(self._raw)

    @classmethod
    def from_bytes(cls, raw: bytes) -> "GlobalParameters":
        return cls(raw)
