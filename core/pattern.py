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

NOTE ON LAYOUT CONSTANTS
    from_bytes/to_bytes read the structural offsets from codec.layout, the
    single source of truth for the format. layout.py is pure declarative data
    (no logic), so this does not couple the domain model to codec behaviour.
"""

from __future__ import annotations

from typing import Sequence

from core.errors import InvariantError
from core.part import (
    Part, KIND_DRUM, KIND_KEYBOARD, KIND_STRETCHSLICE, KIND_AUDIOIN, KIND_ACCENT,
)
from core.motion import MotionSlot
import codec.layout as L

NAME_LEN = 8
HEADER_LEN = 16

# (kind, on-disk offset, count, chunk size) for the 16 parts, in file order.
_PART_GROUPS = (
    (KIND_DRUM,         L.PAT_OFF_PARTS_DRUM,         L.NUM_PARTS_DRUM,         L.CHUNK_PARTS_DRUM),
    (KIND_KEYBOARD,     L.PAT_OFF_PARTS_KEYBOARD,     L.NUM_PARTS_KEYBOARD,     L.CHUNK_PARTS_KEYBOARD),
    (KIND_STRETCHSLICE, L.PAT_OFF_PARTS_STRETCHSLICE, L.NUM_PARTS_STRETCHSLICE, L.CHUNK_PARTS_STRETCHSLICE),
    (KIND_AUDIOIN,      L.PAT_OFF_PARTS_AUDIOIN,      L.NUM_PARTS_AUDIOIN,      L.CHUNK_PARTS_AUDIOIN),
    (KIND_ACCENT,       L.PAT_OFF_PARTS_ACCENT,       L.NUM_PARTS_ACCENT,       L.CHUNK_PARTS_ACCENT),
)


class PatternHeader:
    """Tempo, length, beat, last step, swing, and roll for one pattern.

    Retained byte-exact in WF2; individual field decoders land in the
    pattern-view workflow.
    """

    __slots__ = ("_raw",)

    def __init__(self, raw: bytes):
        if len(raw) != HEADER_LEN:
            raise InvariantError(
                f"pattern header must be {HEADER_LEN} bytes, got {len(raw)}")
        self._raw = bytearray(raw)

    @property
    def tempo(self) -> float:
        raise NotImplementedError

    @property
    def length_bars(self) -> int:
        raise NotImplementedError

    @property
    def last_step(self) -> int:
        raise NotImplementedError

    @property
    def playable_steps(self) -> int:
        """last_step * length_bars, capped at 128 (TDD §8.1)."""
        raise NotImplementedError

    def to_bytes(self) -> bytes:
        return bytes(self._raw)


class FxUnit:
    """One of three FX units: {type, edit1, edit2, motionSW} (4 bytes)."""

    __slots__ = ("_raw",)

    def __init__(self, raw: bytes):
        if len(raw) != L.CHUNK_PARAMETERS_FX:
            raise InvariantError(
                f"fx unit must be {L.CHUNK_PARAMETERS_FX} bytes, got {len(raw)}")
        self._raw = bytearray(raw)

    @property
    def fx_type(self) -> int:
        return self._raw[0]

    @property
    def motion_enabled(self) -> bool:
        return bool(self._raw[3])

    def to_bytes(self) -> bytes:
        return bytes(self._raw)


class Pattern:
    """One 4280-byte pattern: name, header, 16 parts, 3 FX units, 24 motion slots."""

    __slots__ = ("_name", "_header", "_parts", "_fx", "_motion")

    NUM_MOTION_SLOTS = L.NUM_PARAMETERS_MOTION   # 24

    def __init__(self, name: bytes, header: PatternHeader,
                 parts: Sequence[Part], fx: Sequence[FxUnit],
                 motion: Sequence[MotionSlot]):
        if len(name) != NAME_LEN:
            raise InvariantError(f"pattern name must be {NAME_LEN} bytes")
        if len(motion) != self.NUM_MOTION_SLOTS:
            raise InvariantError(
                f"a pattern holds exactly {self.NUM_MOTION_SLOTS} motion slots, "
                f"got {len(motion)}")
        self._name = bytes(name)
        self._header = header
        self._parts = tuple(parts)
        self._fx = tuple(fx)
        self._motion = list(motion)

    @property
    def name(self) -> str:
        return self._name.decode("ascii", "replace").rstrip("\x00 ")

    def set_name(self, value: str) -> None:
        """Set the 8-byte pattern name (pads/truncates)."""
        raw = value.encode("ascii", "replace")[:NAME_LEN].ljust(NAME_LEN, b" ")
        self._name = bytes(raw)

    @property
    def header(self) -> PatternHeader:
        return self._header

    def parts(self) -> tuple[Part, ...]:
        """Immutable view of the 16 parts, in file order."""
        return self._parts

    def fx_units(self) -> tuple[FxUnit, ...]:
        return self._fx

    def motion_slots(self) -> tuple[MotionSlot, ...]:
        """Immutable view of exactly 24 motion slots."""
        return tuple(self._motion)

    def replace_motion(self, index: int, slot: MotionSlot) -> None:
        """Replace one motion slot in place (slots are replaced, never appended)."""
        if not (0 <= index < self.NUM_MOTION_SLOTS):
            raise InvariantError(
                f"motion index {index} out of range 0..{self.NUM_MOTION_SLOTS-1}")
        self._motion[index] = slot

    def motion_slots_used(self) -> int:
        """How many of the 24 slots are in use (for the n/24 budget display)."""
        return sum(1 for m in self._motion if m.in_use)

    def to_bytes(self) -> bytes:
        """Serialize to the 4280-byte chunk."""
        out = bytearray(self._name)
        out += self._header.to_bytes()
        for part in self._parts:
            out += part.to_bytes()
        for fx in self._fx:
            out += fx.to_bytes()
        for slot in self._motion:
            out += slot.to_bytes()
        if len(out) != L.CHUNK_PATTERN:
            raise InvariantError(
                f"serialized pattern is {len(out)} bytes, expected {L.CHUNK_PATTERN}")
        return bytes(out)

    @classmethod
    def from_bytes(cls, raw: bytes) -> "Pattern":
        if len(raw) != L.CHUNK_PATTERN:
            raise InvariantError(
                f"pattern chunk must be {L.CHUNK_PATTERN} bytes, got {len(raw)}")
        name = raw[:NAME_LEN]
        header = PatternHeader(raw[NAME_LEN:NAME_LEN + HEADER_LEN])
        parts: list[Part] = []
        for kind, base, count, size in _PART_GROUPS:
            for i in range(count):
                off = base + i * size
                parts.append(Part.from_bytes(kind, i, raw[off:off + size]))
        fx = [FxUnit(raw[L.PAT_OFF_PARAMETERS_FX + i * L.CHUNK_PARAMETERS_FX:
                         L.PAT_OFF_PARAMETERS_FX + (i + 1) * L.CHUNK_PARAMETERS_FX])
              for i in range(L.NUM_PARAMETERS_FX)]
        motion = []
        for i in range(L.NUM_PARAMETERS_MOTION):
            off = L.PAT_OFF_PARAMETERS_MOTION + i * L.CHUNK_PARAMETERS_MOTION
            motion.append(MotionSlot.from_bytes(raw[off:off + L.CHUNK_PARAMETERS_MOTION]))
        return cls(name, header, parts, fx, motion)
