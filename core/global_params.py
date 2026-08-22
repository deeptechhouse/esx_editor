"""
core.global_params — the 192-byte global parameter block (TDD §2.1).

Global settings that apply to the whole bank/instrument: master tempo mode,
MIDI channel and filters, metronome, etc. Only the fields the app edits are
decoded; the remainder round-trips verbatim (TDD §4.1).
"""

from __future__ import annotations


class GlobalParameters:
    """The bank-wide global settings block."""

    __slots__ = ("_raw",)

    def __init__(self, raw: bytes):
        self._raw = bytearray(raw)

    @property
    def midi_channel(self) -> int:
        raise NotImplementedError

    def to_bytes(self) -> bytes:
        """Serialize back to the 192-byte block."""
        raise NotImplementedError

    @classmethod
    def from_bytes(cls, raw: bytes) -> "GlobalParameters":
        raise NotImplementedError
