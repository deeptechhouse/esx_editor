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

            **NAMED.** An independent editor (SawLoop) lists its 33 knob names
            with their control-change numbers, and that list matches the stored
            bytes **33 out of 33, position for position, in all four banks**.
            Thirty-three values in exact sequence is not a coincidence, so the
            row ORDER is proven even though the knob NAMES are taken on that
            editor's authority rather than measured here.

            The order is internally coherent, which is the cheap sanity check:
            the modulation block, then the filter block, then the per-part
            controls, then effects 1-3 each as TYPE / EDIT1 / EDIT2 / MOTION
            SEQ, then FX CHAIN. Groups do not interleave.

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

#: The manual's printed factory table (p.90), in DRUM_NOTE_PARTS order. This is
#: the same data the decode was VERIFIED against, kept as a constant so "reset
#: to factory" restores a published table rather than whatever happened to be
#: in the bank the template came from.
FACTORY_DRUM_NOTES = (36, 38, 40, 41, 43, 42, 46, 49, 51, 9, 10, 11, 12)

#: The machine's own range for a drum note: C-1 to G9 (manual p.90), which is
#: the whole MIDI note range. Stated as a constant because "0..127" and
#: "C-1..G9" are the same thing said to two different audiences.
MIN_NOTE = 0

#: CC assign table: one control-change number per assignable knob.
CC_ASSIGN_OFFSET = 23

#: The knob each row drives, in stored order. Names are SawLoop's; the ORDER is
#: proven by all 33 of its numbers matching the factory bytes position for
#: position in every bank. Kept as a flat tuple, not a dict, because the row
#: INDEX is the on-disk identity — a name is a label for a position, never the
#: key to it.
CC_ASSIGN_NAMES = (
    "MOD SPEED",
    "MOD DEPTH",
    "MOD TYPE",
    "MOD DEST",
    "MOD BPMSYNC",
    "FILTER CUTOFF",
    "FILTER RESONANCE",
    "FILTER EGINT",
    "FILTER TYPE",
    "GLIDE",
    "PAN",
    "EG TIME",
    "LEVEL",
    "START POINT",
    "AMP EG",
    "ROLL",
    "REVERSE",
    "EFFECT SEND",
    "EFFECT SELECT",
    "PART MOTION SEQ",
    "FX1 TYPE",
    "FX1 EDIT1",
    "FX1 EDIT2",
    "FX1 MOTION SEQ",
    "FX2 TYPE",
    "FX2 EDIT1",
    "FX2 EDIT2",
    "FX2 MOTION SEQ",
    "FX3 TYPE",
    "FX3 EDIT1",
    "FX3 EDIT2",
    "FX3 MOTION SEQ",
    "FX CHAIN",
)
NUM_CC_ASSIGN = len(CC_ASSIGN_NAMES)
MAX_CC = 127
MAX_NOTE = 127

_NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def _normalise(name: str) -> str:
    """Fold case and collapse whitespace, so "Filter  Cutoff" finds its row."""
    return " ".join(name.split()).upper()


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

    def reset_drum_notes(self) -> None:
        """Restore the manual's printed factory assignments."""
        for part, number in enumerate(FACTORY_DRUM_NOTES):
            self.set_drum_note(part, number)

    def duplicate_drum_notes(self) -> dict[int, tuple[int, ...]]:
        """Note numbers assigned to more than one part -> those parts.

        The manual states parts sharing a note sound together when driven from
        an external device, so this is a legitimate setup and not an error. It
        is surfaced for the same reason the CC clash is: it is the likeliest
        way a mapping session goes quietly wrong.
        """
        seen: dict[int, list[int]] = {}
        for part, number in enumerate(self.drum_notes()):
            seen.setdefault(number, []).append(part)
        return {n: tuple(parts) for n, parts in seen.items() if len(parts) > 1}

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

    def cc_name(self, row: int) -> str:
        """The knob this row drives."""
        self._check_row(row)
        return CC_ASSIGN_NAMES[row]

    def cc_row_for(self, name: str) -> int:
        """Row index for a knob name, matched case- and space-insensitively.

        The machine and SawLoop disagree on spacing in places, and nobody types
        "FILTER RESONANCE" exactly; normalising here keeps that irritation out
        of every caller.
        """
        wanted = _normalise(name)
        for row, knob in enumerate(CC_ASSIGN_NAMES):
            if _normalise(knob) == wanted:
                return row
        raise InvariantError(
            f"no assignable knob named {name!r}; "
            f"the {NUM_CC_ASSIGN} names are {', '.join(CC_ASSIGN_NAMES)}"
        )

    def cc_for(self, name: str) -> int:
        """The control-change number currently driving a named knob."""
        return self.cc_assignment(self.cc_row_for(name))

    def set_cc_for(self, name: str, cc: int) -> None:
        """Point a named knob at a control-change number."""
        self.set_cc_assignment(self.cc_row_for(name), cc)

    def duplicate_cc_rows(self) -> dict[int, tuple[int, ...]]:
        """Control-change numbers driving more than one knob -> those rows.

        Not an error: one controller knob moving two parameters is a legitimate
        thing to set up on purpose. It is surfaced because it is also the most
        likely way a remapping session goes quietly wrong.
        """
        seen: dict[int, list[int]] = {}
        for row, cc in enumerate(self.cc_assignments()):
            seen.setdefault(cc, []).append(row)
        return {cc: tuple(rows) for cc, rows in seen.items() if len(rows) > 1}

    def set_cc_assignment(self, row: int, cc: int) -> None:
        """Set one row's control-change number.

        Addressed by row, because the row index is the on-disk identity; the
        name is a label for a position. set_cc_for() is the by-name front door.
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
