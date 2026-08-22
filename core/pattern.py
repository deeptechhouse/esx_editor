"""
core.pattern — Pattern, PatternHeader, and FxUnit.

PATTERN CHUNK (4280 B, TDD §2.2, VERIFIED)
      0  name              8 B, space-padded
      8  header            16 B (tempo, length, beat, lastStep, swing, roll)
     24  drum parts        9 x 34
    330  keyboard parts    2 x 274
    878  stretch/slice     3 x 32
    974  audio-in          1 x 156
   1130  accent            1 x 18
   1148  fx parameters     3 x 4  {type, edit1, edit2, motionSW}
   1160  motion sequences  24 x 130  -> ends exactly at 4280

INVARIANTS (TDD §3.2)
    - a Pattern always holds exactly 24 motion slots (replaced, never appended)
    - the playable step count is lastStep x patternLength, capped at 128
"""

from __future__ import annotations

from typing import Sequence

from core.part import Part
from core.motion import MotionSlot


class PatternHeader:
    """Tempo, length, beat, last step, swing, and roll for one pattern."""

    __slots__ = ("_raw",)

    def __init__(self, raw: bytes):
        self._raw = bytearray(raw)

    @property
    def tempo(self) -> float:
        raise NotImplementedError

    @property
    def length_bars(self) -> int:
        """Pattern length in bars (1..8)."""
        raise NotImplementedError

    @property
    def last_step(self) -> int:
        """Last step per bar (1..16)."""
        raise NotImplementedError

    @property
    def playable_steps(self) -> int:
        """last_step * length_bars, capped at 128 (TDD §8.1)."""
        raise NotImplementedError

    def to_bytes(self) -> bytes:
        raise NotImplementedError


class FxUnit:
    """One of three FX units: {type, edit1, edit2, motionSW} (4 bytes)."""

    __slots__ = ("_raw",)

    def __init__(self, raw: bytes):
        self._raw = bytearray(raw)

    @property
    def fx_type(self) -> int:
        raise NotImplementedError

    @property
    def motion_enabled(self) -> bool:
        raise NotImplementedError

    def to_bytes(self) -> bytes:
        raise NotImplementedError


class Pattern:
    """One 4280-byte pattern: name, header, 16 parts, 3 FX units, 24 motion slots.

    Undecoded bytes are retained verbatim (TDD §4.1). The 24-motion-slot
    invariant is enforced here.
    """

    __slots__ = ("_name", "_header", "_parts", "_fx", "_motion", "_raw_rest")

    NUM_MOTION_SLOTS = 24

    def __init__(self, name: bytes, header: PatternHeader,
                 parts: Sequence[Part], fx: Sequence[FxUnit],
                 motion: Sequence[MotionSlot], raw_rest: bytes = b""):
        self._name = bytes(name)
        self._header = header
        self._parts = tuple(parts)
        self._fx = tuple(fx)
        self._motion = list(motion)
        self._raw_rest = bytes(raw_rest)

    @property
    def name(self) -> str:
        raise NotImplementedError

    def set_name(self, value: str) -> None:
        """Set the 8-byte pattern name (pads/truncates)."""
        raise NotImplementedError

    @property
    def header(self) -> PatternHeader:
        return self._header

    def parts(self) -> tuple[Part, ...]:
        """Immutable view of the 16 parts."""
        return self._parts

    def fx_units(self) -> tuple[FxUnit, ...]:
        return self._fx

    def motion_slots(self) -> tuple[MotionSlot, ...]:
        """Immutable view of exactly 24 motion slots."""
        return tuple(self._motion)

    def replace_motion(self, index: int, slot: MotionSlot) -> None:
        """Replace one motion slot in place (slots are replaced, never appended).

        Raises InvariantError if index is outside 0..23.
        """
        raise NotImplementedError

    def motion_slots_used(self) -> int:
        """How many of the 24 slots are in use (for the n/24 budget display)."""
        raise NotImplementedError

    def to_bytes(self) -> bytes:
        """Serialize to the 4280-byte chunk."""
        raise NotImplementedError

    @classmethod
    def from_bytes(cls, raw: bytes) -> "Pattern":
        raise NotImplementedError
