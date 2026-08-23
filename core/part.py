"""
core.part — the parts inside a pattern and their step sequence data.

PART TYPES (TDD §2.2 / §3.1)
    A pattern holds 16 parts of five kinds, each a different on-disk size:
        Drum x9 (34 B), Keyboard x2 (274 B), StretchSlice x3 (32 B),
        AudioIn x1 (156 B), Accent x1 (18 B).
    Only the fields the model edits are decoded; the rest of each part
    round-trips verbatim (TDD §4.1). WF2 keeps every part byte-exact.
"""

from __future__ import annotations

import struct

from core.errors import InvariantError

# Part kinds (used by the operation table's target picker, TDD §8.5).
KIND_DRUM = "drum"
KIND_KEYBOARD = "keyboard"
KIND_STRETCHSLICE = "stretchslice"
KIND_AUDIOIN = "audioin"
KIND_ACCENT = "accent"

#: Part kinds that play a sample slot. Audio-in takes the live input and accent
#: is a per-step emphasis track; neither references the sample table.
SAMPLE_PLAYING_KINDS = frozenset({KIND_DRUM, KIND_KEYBOARD, KIND_STRETCHSLICE})

#: The sample slot index is a big-endian u16 at the start of the part chunk.
SAMPLE_NUMBER_OFFSET = 0
NUM_SAMPLE_SLOTS = 384


#: Where each part kind's 16-byte trigger bitmap sits inside its chunk, and how
#: many steps it holds. VERIFIED 2026-08-23 against 468 drum and 156 stretch /
#: slice parts in corpus/Chronic-Interactive.esx.
#:
#: EVIDENCE
#:   - Both windows are END-ALIGNED: 18+16 == 34 (drum chunk) and
#:     16+16 == 32 (stretch chunk).
#:   - The two 8-byte halves are byte-identical on 468/468 and 156/156 parts,
#:     which is what a 64-step pattern written into a 128-step field looks like.
#:   - Read LSB-first, hits concentrate on the quarter-note grid at 1.85x
#:     uniform, and step 0 is the single most-triggered step (244 hits, versus
#:     29 for step 1). Read MSB-first the busiest step is step 7 — a 16th-note
#:     offbeat — and grid concentration inverts to 0.5x. Real drum programming
#:     puts hits on the beat, so LSB-first is the reading.
#:
#: Keyboard, audio-in and accent parts are NOT here: keyboard stores note data
#: rather than a trigger bitmap (its bits show no grid concentration at all,
#: 0.80x), and the other two showed no usable signal.
SEQUENCE_OFFSETS: dict[str, int] = {
    KIND_DRUM: 18,
    KIND_STRETCHSLICE: 16,
}
SEQUENCE_BYTES = 16
NUM_STEPS = SEQUENCE_BYTES * 8  # 128


class SequenceData:
    """The per-step trigger bitmap for one part, LSB-first."""

    __slots__ = ("_steps",)

    def __init__(self, steps: bytes):
        if len(steps) != SEQUENCE_BYTES:
            raise InvariantError(
                f"sequence data must be {SEQUENCE_BYTES} bytes, got {len(steps)}"
            )
        self._steps = bytearray(steps)

    @property
    def steps(self) -> bytes:
        """Defensive copy of the raw per-step bytes."""
        return bytes(self._steps)

    def _locate(self, step: int) -> tuple[int, int]:
        if not (0 <= step < NUM_STEPS):
            raise InvariantError(f"step {step} out of range 0..{NUM_STEPS - 1}")
        return step // 8, step % 8

    def is_active(self, step: int) -> bool:
        """True if the given step triggers."""
        index, bit = self._locate(step)
        return bool((self._steps[index] >> bit) & 1)

    def set_active(self, step: int, active: bool) -> None:
        """Turn one step on or off."""
        index, bit = self._locate(step)
        if active:
            self._steps[index] |= 1 << bit
        else:
            self._steps[index] &= ~(1 << bit) & 0xFF

    def active_steps(self) -> tuple[int, ...]:
        """Every triggering step, ascending."""
        return tuple(i for i in range(NUM_STEPS) if self.is_active(i))

    def count(self) -> int:
        return sum(bin(byte).count("1") for byte in self._steps)


class Part:
    """One part in a pattern. `kind` is one of the KIND_* constants.

    Retains the full raw part bytes so undecoded fields survive a round-trip;
    decoded accessors are layered on top as the format is understood.
    """

    __slots__ = ("_kind", "_index", "_raw")

    def __init__(self, kind: str, index: int, raw: bytes):
        self._kind = kind
        self._index = index
        self._raw = bytearray(raw)

    @property
    def kind(self) -> str:
        return self._kind

    @property
    def index(self) -> int:
        return self._index

    @property
    def sample_number(self) -> int:
        """Which sample slot this part plays (VERIFIED 2026-08-23).

        A big-endian u16 at part offset 0, indexing the 384-slot table.

        EVIDENCE
            Across every sample-playing part in corpus/Chronic-Interactive.esx —
            468 drum, 104 keyboard, 156 stretch/slice — this field points at an
            OCCUPIED slot 728 times out of 728. The bank has 100 occupied slots
            of 384, so a wrong field would land on an empty one constantly.

        Audio-in and accent parts do not play a sample and raise instead: their
        offset 0 holds something else (a constant 127, and values above 10,000
        respectively), and returning that as a slot index would be a lie.
        """
        if self._kind not in SAMPLE_PLAYING_KINDS:
            raise NotImplementedError(
                f"a {self._kind} part does not play a sample slot; its first "
                "two bytes are some other field"
            )
        return struct.unpack_from(">H", self._raw, SAMPLE_NUMBER_OFFSET)[0]

    def set_sample_number(self, slot_index: int) -> None:
        """Point this part at a sample slot."""
        if self._kind not in SAMPLE_PLAYING_KINDS:
            raise NotImplementedError(
                f"a {self._kind} part does not play a sample slot"
            )
        if not (0 <= slot_index < NUM_SAMPLE_SLOTS):
            raise InvariantError(
                f"slot {slot_index} out of range 0..{NUM_SAMPLE_SLOTS - 1}"
            )
        struct.pack_into(">H", self._raw, SAMPLE_NUMBER_OFFSET, slot_index)

    def has_sequence(self) -> bool:
        """Whether this part kind's trigger bitmap has been located."""
        return self._kind in SEQUENCE_OFFSETS

    def sequence(self) -> SequenceData:
        """The part's step trigger bitmap.

        Raises NotImplementedError for keyboard / audio-in / accent parts, whose
        step data is not a plain trigger bitmap and has not been located.
        """
        offset = SEQUENCE_OFFSETS.get(self._kind)
        if offset is None:
            raise NotImplementedError(
                f"the step data for a {self._kind} part is not decoded: its bits "
                "show no grid concentration, so it is not a trigger bitmap"
            )
        return SequenceData(bytes(self._raw[offset : offset + SEQUENCE_BYTES]))

    def write_sequence(self, sequence: SequenceData) -> None:
        """Write a modified trigger bitmap back into the part chunk."""
        offset = SEQUENCE_OFFSETS.get(self._kind)
        if offset is None:
            raise NotImplementedError(
                f"the step data for a {self._kind} part is not decoded"
            )
        self._raw[offset : offset + SEQUENCE_BYTES] = sequence.steps

    def to_bytes(self) -> bytes:
        return bytes(self._raw)

    @classmethod
    def from_bytes(cls, kind: str, index: int, raw: bytes) -> Part:
        if not raw:
            raise InvariantError("part raw bytes must be non-empty")
        return cls(kind, index, raw)
