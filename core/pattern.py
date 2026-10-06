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

import struct
from collections.abc import Sequence

import codec.layout as L
from core.errors import InvariantError
from core.motion import MotionSlot
from core.part import (
    KIND_ACCENT,
    KIND_AUDIOIN,
    KIND_DRUM,
    KIND_KEYBOARD,
    KIND_STRETCHSLICE,
    Part,
)

NAME_LEN = 8


# O(1) time, O(1) space
def pattern_label(index: int) -> str:
    """Machine display for a pattern index: A.01 - D.64 (manual p.2914).

    The machine does NOT number patterns 1-256. Anywhere a pattern index is
    shown to a human it goes through here, so the editor and the device agree.
    """
    if not (0 <= index < 256):
        raise InvariantError(f"pattern index {index} out of range 0..255")
    return f"{'ABCD'[index // 64]}.{index % 64 + 1:02d}"


HEADER_LEN = 16

# (kind, on-disk offset, count, chunk size) for the 16 parts, in file order.
_PART_GROUPS = (
    (KIND_DRUM, L.PAT_OFF_PARTS_DRUM, L.NUM_PARTS_DRUM, L.CHUNK_PARTS_DRUM),
    (
        KIND_KEYBOARD,
        L.PAT_OFF_PARTS_KEYBOARD,
        L.NUM_PARTS_KEYBOARD,
        L.CHUNK_PARTS_KEYBOARD,
    ),
    (
        KIND_STRETCHSLICE,
        L.PAT_OFF_PARTS_STRETCHSLICE,
        L.NUM_PARTS_STRETCHSLICE,
        L.CHUNK_PARTS_STRETCHSLICE,
    ),
    (KIND_AUDIOIN, L.PAT_OFF_PARTS_AUDIOIN, L.NUM_PARTS_AUDIOIN, L.CHUNK_PARTS_AUDIOIN),
    (KIND_ACCENT, L.PAT_OFF_PARTS_ACCENT, L.NUM_PARTS_ACCENT, L.CHUNK_PARTS_ACCENT),
)


#: Tempo lives in the first two bytes of the header, scaled by 128.
TEMPO_OFFSET = 0
TEMPO_SCALE = 128.0
MIN_TEMPO = 20.0
MAX_TEMPO = 300.0

_UNDECODED_MESSAGE = (
    "{field} is not decoded: every named pattern in the corpus shares the same "
    "header bytes 2, 4, 5, 6 and 7, so there is no variation to correlate a "
    "meaning against. Byte 3 varies (1, 3, 19, 67, 131 — low bits 1 or 3 plus "
    "at most one of bits 4/6/7) but not enough to assign fields. Closing this "
    "needs a hardware diff: change one setting on one pattern, Save All, and "
    "compare. See research/HARDWARE_CHECKLIST.md."
)


class PatternHeader:
    """Tempo, length, beat, last step, swing, and roll for one pattern.

    Retained byte-exact in WF2; individual field decoders land in the
    pattern-view workflow.
    """

    __slots__ = ("_raw",)

    # O(1) time, O(1) space
    def __init__(self, raw: bytes):
        if len(raw) != HEADER_LEN:
            raise InvariantError(
                f"pattern header must be {HEADER_LEN} bytes, got {len(raw)}"
            )
        self._raw = bytearray(raw)

    @property
    # O(1) time, O(1) space
    def tempo(self) -> float:
        """Pattern tempo in BPM (VERIFIED 2026-08-23).

        Stored as a big-endian u16 at header offset 0, in units of 1/128 BPM.

        EVIDENCE
            Across 1,024 pattern headers in four banks, this reading yields 19
            of 20 distinct values as EXACT integer BPMs — 69, 72, 80, 82, 84,
            85, 86, 89, 90, 91, 92, 95, 98, 100, 120, 124, 128, 134, 144 — every
            one inside the documented 20.0-300.0 range. The default header, on
            the blank template and on two untouched banks, is exactly 120.0,
            which is the machine's own default.

            The competing reading (byte 0 doubled) is ruled out by the odd
            tempos: 69, 85, 89, 91 and 95 cannot be produced by doubling a byte.
            They come from the low byte being 0x80, i.e. exactly +1.00 BPM at a
            1/128 scale.

        The stored resolution (1/128 BPM) is finer than the 0.1 BPM the display
        shows, so a value need not land on a tenth.
        """
        raw = struct.unpack_from(">H", self._raw, TEMPO_OFFSET)[0]
        return raw / TEMPO_SCALE

    # O(1) time, O(1) space
    def set_tempo(self, bpm: float) -> None:
        """Set the tempo, clamped to nothing — out of range raises."""
        if not (MIN_TEMPO <= bpm <= MAX_TEMPO):
            raise InvariantError(
                f"tempo {bpm} outside the hardware's {MIN_TEMPO}-{MAX_TEMPO} BPM"
            )
        struct.pack_into(">H", self._raw, TEMPO_OFFSET, int(round(bpm * TEMPO_SCALE)))

    @property
    # O(1) time, O(1) space
    def length_bars(self) -> int:
        """NOT DECODED — see the class docstring. Raises deliberately."""
        raise NotImplementedError(_UNDECODED_MESSAGE.format(field="length_bars"))

    @property
    # O(1) time, O(1) space
    def last_step(self) -> int:
        """NOT DECODED — see the class docstring. Raises deliberately."""
        raise NotImplementedError(_UNDECODED_MESSAGE.format(field="last_step"))

    @property
    # O(1) time, O(1) space
    def playable_steps(self) -> int:
        """last_step * length_bars, capped at 128 (TDD §8.1).

        Blocked on both of its inputs.
        """
        raise NotImplementedError(_UNDECODED_MESSAGE.format(field="playable_steps"))

    # O(1) time, O(1) space
    def to_bytes(self) -> bytes:
        return bytes(self._raw)


#: The ESX-1 has 16 effect types (manual p.51, "one of the 16 effect types").
#: Corpus data agrees: fx_type spans 0..14 across the named patterns of three
#: banks, consistent with 0..15.
NUM_FX_TYPES = 16

#: The sixteen names, from the manual. Order here is the manual's ROUTING
#: grouping (p.52), which is NOT necessarily the machine's dial order — and the
#: manual's parameter section (p.53 onward) lists them in a different order
#: again. So this is a reference list, deliberately NOT an index->name map:
#: showing "type 10 = GRAIN SHIFTER" would be a guess the user could not tell
#: from a fact. Closing it needs one hardware pass: set FX1 to each type in
#: turn, Save All, and read back the byte.
FX_TYPE_NAMES = (
    "CHO/FLG",
    "PHASER",
    "RING MOD",
    "COMPRESSOR",
    "DECIMATOR",
    "EQ",
    "LPF",
    "HPF",
    "REVERB",
    "MOD DELAY",
    "GRAIN SHIFTER",
    "TALKING MOD",
    "PITCH SHIFTER",
    "DISTORTION",
    "BPM SYNC DELAY",
    "SHORT DELAY",
)


class FxUnit:
    """One of three FX units: {type, edit1, edit2, motionSW} (4 bytes)."""

    __slots__ = ("_raw",)

    # O(1) time, O(1) space
    def __init__(self, raw: bytes):
        if len(raw) != L.CHUNK_PARAMETERS_FX:
            raise InvariantError(
                f"fx unit must be {L.CHUNK_PARAMETERS_FX} bytes, got {len(raw)}"
            )
        self._raw = bytearray(raw)

    @property
    # O(1) time, O(1) space
    def fx_type(self) -> int:
        return self._raw[0]

    @property
    # O(1) time, O(1) space
    def motion_enabled(self) -> bool:
        return bool(self._raw[3])

    # O(1) time, O(1) space
    def to_bytes(self) -> bytes:
        return bytes(self._raw)


class Pattern:
    """One 4280-byte pattern: name, header, 16 parts, 3 FX units, 24 motion slots."""

    __slots__ = ("_name", "_header", "_parts", "_fx", "_motion")

    NUM_MOTION_SLOTS = L.NUM_PARAMETERS_MOTION  # 24

    # O(K + M) time, O(K + M) space — K = 16 parts; M = 24 motion slots
    def __init__(
        self,
        name: bytes,
        header: PatternHeader,
        parts: Sequence[Part],
        fx: Sequence[FxUnit],
        motion: Sequence[MotionSlot],
    ):
        if len(name) != NAME_LEN:
            raise InvariantError(f"pattern name must be {NAME_LEN} bytes")
        if len(motion) != self.NUM_MOTION_SLOTS:
            raise InvariantError(
                f"a pattern holds exactly {self.NUM_MOTION_SLOTS} motion slots, "
                f"got {len(motion)}"
            )
        self._name = bytes(name)
        self._header = header
        self._parts = tuple(parts)
        self._fx = tuple(fx)
        self._motion = list(motion)

    @property
    # O(1) time, O(1) space
    def name(self) -> str:
        return self._name.decode("ascii", "replace").rstrip("\x00 ")

    # O(v) time, O(v) space — v = characters in the supplied name (encoded before truncation)
    def set_name(self, value: str) -> None:
        """Set the 8-byte pattern name (pads/truncates)."""
        raw = value.encode("ascii", "replace")[:NAME_LEN].ljust(NAME_LEN, b" ")
        self._name = bytes(raw)

    @property
    # O(1) time, O(1) space
    def header(self) -> PatternHeader:
        return self._header

    # O(1) time, O(1) space
    def parts(self) -> tuple[Part, ...]:
        """Immutable view of the 16 parts, in file order."""
        return self._parts

    # O(1) time, O(1) space
    def fx_units(self) -> tuple[FxUnit, ...]:
        return self._fx

    # O(M) time, O(M) space — M = 24 motion slots
    def motion_slots(self) -> tuple[MotionSlot, ...]:
        """Immutable view of exactly 24 motion slots."""
        return tuple(self._motion)

    # O(1) time, O(1) space
    def replace_motion(self, index: int, slot: MotionSlot) -> None:
        """Replace one motion slot in place (slots are replaced, never appended)."""
        if not (0 <= index < self.NUM_MOTION_SLOTS):
            raise InvariantError(
                f"motion index {index} out of range 0..{self.NUM_MOTION_SLOTS - 1}"
            )
        self._motion[index] = slot

    # O(M) time, O(1) space — M = 24 motion slots
    def motion_slots_used(self) -> int:
        """How many of the 24 slots are in use (for the n/24 budget display)."""
        # O(M) time, O(1) space — M = 24 motion slots
        return sum(1 for m in self._motion if m.in_use)

    # O(B) time, O(B) space — B = 4,280 bytes per pattern chunk
    def to_bytes(self) -> bytes:
        """Serialize to the 4280-byte chunk."""
        out = bytearray(self._name)
        out += self._header.to_bytes()
        # O(B) time, O(B) space — B = 1,136 bytes across the 16 part chunks
        for part in self._parts:
            out += part.to_bytes()
        # O(F) time, O(F) space — F = 3 FX units of 4 bytes
        for fx in self._fx:
            out += fx.to_bytes()
        # O(M) time, O(M) space — M = 24 motion slots of 130 bytes
        for slot in self._motion:
            out += slot.to_bytes()
        if len(out) != L.CHUNK_PATTERN:
            raise InvariantError(
                f"serialized pattern is {len(out)} bytes, expected {L.CHUNK_PATTERN}"
            )
        return bytes(out)

    @classmethod
    # O(B) time, O(B) space — B = 4,280 bytes per pattern chunk
    def from_bytes(cls, raw: bytes) -> Pattern:
        if len(raw) != L.CHUNK_PATTERN:
            raise InvariantError(
                f"pattern chunk must be {L.CHUNK_PATTERN} bytes, got {len(raw)}"
            )
        name = raw[:NAME_LEN]
        header = PatternHeader(raw[NAME_LEN : NAME_LEN + HEADER_LEN])
        parts: list[Part] = []
        # O(B) time, O(B) space — B = 1,136 bytes across the 16 part chunks
        for kind, base, count, size in _PART_GROUPS:
            # O(B) time, O(B) space — B = 1,136 bytes across the 16 part chunks (one group's share)
            for i in range(count):
                off = base + i * size
                parts.append(Part.from_bytes(kind, i, raw[off : off + size]))
        # O(F) time, O(F) space — F = 3 FX units of 4 bytes
        fx = [
            FxUnit(
                raw[
                    L.PAT_OFF_PARAMETERS_FX
                    + i * L.CHUNK_PARAMETERS_FX : L.PAT_OFF_PARAMETERS_FX
                    + (i + 1) * L.CHUNK_PARAMETERS_FX
                ]
            )
            for i in range(L.NUM_PARAMETERS_FX)
        ]
        motion = []
        # O(M) time, O(M) space — M = 24 motion slots of 130 bytes
        for i in range(L.NUM_PARAMETERS_MOTION):
            off = L.PAT_OFF_PARAMETERS_MOTION + i * L.CHUNK_PARAMETERS_MOTION
            motion.append(
                MotionSlot.from_bytes(raw[off : off + L.CHUNK_PARAMETERS_MOTION])
            )
        return cls(name, header, parts, fx, motion)
