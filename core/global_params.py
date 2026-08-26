"""
core.global_params — the 192-byte global parameter block (TDD §2.1).

Bank-wide settings. The block is held verbatim and decoded fields are patched
into it, so the bytes that are still unknown survive a read/modify/write by
construction rather than by remembering to copy them.

WHAT IS DECODED, AND ON WHAT EVIDENCE

  +10..+22  DRUM NOTE NUMBERS — 13 bytes, one MIDI note per part.
            **VERIFIED.** The manual (p.90, "Assigning the drum note numbers")
            prints the factory table, and all thirteen bytes match it exactly
            under Korg's naming (C-1 = 0):

              Drum1 C2=36  Drum2 D2=38  Drum3 E2=40  Drum4 F2=41  Drum5 G2=43
              Drum6A F#2=42  Drum6B A#2=46  Drum7A C#3=49  Drum7B D#3=51
              Stretch1 A-1=9  Stretch2 A#-1=10  Slice B-1=11  Audio in C0=12

            Thirteen independent values in a published order is not a
            coincidence; this is a proof, not a fit.

  +23..+55  CC ASSIGN TABLE — 33 bytes, one MIDI control-change number per
            knob (manual p.91, "Assigning a MIDI Control Change Number to a
            knob": available for the keyboard parts and the effects; every
            other part is fixed NRPN).

            **LOCATED, NOT YET NAMED.** That this is the CC table is solid: it
            is 33 consecutive bytes, every one a legal CC number, sitting
            directly after the note table and directly before a run of zeros,
            and it holds exactly the numbers a synth voice uses — 74 (cutoff),
            71 (resonance), 5 (portamento), 7 (volume), 10 (pan), 91/93 (sends).

            WHICH ROW IS WHICH KNOB is not yet established. Every corpus bank
            carries the identical factory table, so nothing varies and the
            order cannot be derived from the data. Rows are therefore numbered,
            never labelled with a knob name this codebase cannot prove.
            deploy/make_hw_test_banks.py writes a probe bank that reads the
            mapping off the machine in one pass. See research/HARDWARE_CHECKLIST.md.

STILL UNDECODED
    +0..+9 and everything from +56 hold MIDI channel, tempo mode, metronome and
    more. They are preserved verbatim and have no accessors.
"""

from __future__ import annotations

from core.errors import InvariantError

SIZE = 192

#: Drum note numbers: one byte per part, in the manual's own part order.
DRUM_NOTE_OFFSET = 10
DRUM_NOTE_PARTS = (
    "Drum1",
    "Drum2",
    "Drum3",
    "Drum4",
    "Drum5",
    "Drum6A",
    "Drum6B",
    "Drum7A",
    "Drum7B",
    "Stretch1",
    "Stretch2",
    "Slice",
    "Audio in",
)
NUM_DRUM_NOTES = len(DRUM_NOTE_PARTS)

#: CC assign table: one control-change number per assignable knob.
CC_ASSIGN_OFFSET = 23
NUM_CC_ASSIGN = 33
MAX_CC = 127
MAX_NOTE = 127

_NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def note_name(number: int) -> str:
    """MIDI note number -> the name the ESX-1 displays (Korg naming, C-1 = 0).

    The machine shows note NAMES, not numbers, so anything a human reads has to
    go through here or the editor and the device disagree on the same byte.
    """
    if not (0 <= number <= MAX_NOTE):
        raise InvariantError(f"note number {number} out of range 0..{MAX_NOTE}")
    return f"{_NOTE_NAMES[number % 12]}{number // 12 - 1}"


class GlobalParameters:
    """The bank-wide global settings block (192 bytes)."""

    __slots__ = ("_raw",)

    def __init__(self, raw: bytes):
        if len(raw) != SIZE:
            raise InvariantError(
                f"global parameters block must be {SIZE} bytes, got {len(raw)}"
            )
        self._raw = bytearray(raw)

    # -- drum note numbers (VERIFIED) ---------------------------------------

    def drum_notes(self) -> tuple[int, ...]:
        """The 13 note numbers, in DRUM_NOTE_PARTS order."""
        start = DRUM_NOTE_OFFSET
        return tuple(self._raw[start : start + NUM_DRUM_NOTES])

    def drum_note(self, part: int) -> int:
        self._check_part(part)
        return self._raw[DRUM_NOTE_OFFSET + part]

    def set_drum_note(self, part: int, number: int) -> None:
        """Assign one part's MIDI note number.

        Duplicates are allowed on purpose: the manual states that parts sharing
        a note number sound together, which is a real technique, not a mistake.
        """
        self._check_part(part)
        if not (0 <= number <= MAX_NOTE):
            raise InvariantError(f"note number {number} out of range 0..{MAX_NOTE}")
        self._raw[DRUM_NOTE_OFFSET + part] = number

    def drum_note_name(self, part: int) -> str:
        return note_name(self.drum_note(part))

    def _check_part(self, part: int) -> None:
        if not (0 <= part < NUM_DRUM_NOTES):
            raise InvariantError(
                f"drum note part {part} out of range 0..{NUM_DRUM_NOTES - 1}"
            )

    # -- CC assign table (LOCATED; rows not yet named) ----------------------

    def cc_assignments(self) -> tuple[int, ...]:
        """The 33 assigned control-change numbers, in stored order."""
        start = CC_ASSIGN_OFFSET
        return tuple(self._raw[start : start + NUM_CC_ASSIGN])

    def cc_assignment(self, row: int) -> int:
        self._check_row(row)
        return self._raw[CC_ASSIGN_OFFSET + row]

    def set_cc_assignment(self, row: int, cc: int) -> None:
        """Set one row's control-change number.

        Rows are positions in the stored table, not knob names: which knob each
        row drives is not established yet, and labelling them here would be a
        guess written into a file the machine reads.
        """
        self._check_row(row)
        if not (0 <= cc <= MAX_CC):
            raise InvariantError(f"control change number {cc} out of range 0..{MAX_CC}")
        self._raw[CC_ASSIGN_OFFSET + row] = cc

    def _check_row(self, row: int) -> None:
        if not (0 <= row < NUM_CC_ASSIGN):
            raise InvariantError(
                f"CC assign row {row} out of range 0..{NUM_CC_ASSIGN - 1}"
            )

    @property
    def midi_channel(self) -> int:
        """Not decoded: it is one of the ten bytes before the note table, and
        every corpus bank carries the same value, so it cannot be located."""
        raise NotImplementedError(
            "midi_channel is not decoded: it lives in +0..+9, which is "
            "identical in every corpus bank. Change it on the machine, save, "
            "and diff - see research/HARDWARE_CHECKLIST.md."
        )

    # -- codec io ------------------------------------------------------------

    def to_bytes(self) -> bytes:
        """Serialize back to the 192-byte block."""
        return bytes(self._raw)

    @classmethod
    def from_bytes(cls, raw: bytes) -> GlobalParameters:
        return cls(raw)
