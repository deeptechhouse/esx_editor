"""
codec.operation_table — the 313 motion targets and their value domains.

WHAT A MOTION TARGET IS
    A motion slot drives ONE parameter, identified by a 16-bit id (TDD §8.1).
    The id indexes a 313-entry table mapping id -> human name (e.g.
    "Drum4 Filter Cutoff") and, via the domain table, -> how its stored bytes
    are interpreted (continuous 0-127, bipolar, boolean, or an enum of knob
    positions) and how it plays back (SMOOTH vs forced TRIG HOLD).

SOURCES (loaded at construction, never hardcoded here)
    research/motion_operation_table_313.tsv  — id -> name
    research/motion_target_domains.tsv        — name/group -> kind, options, smooth
    research/motion_byte_encodings.md         — the verified encodings prose

WHY DOMAINS MATTER (TDD §8.3)
    Discrete parameters store KNOB POSITIONS, not option indices:
        value = index * ceil(128 / N)      # N = number of options
    Writing 0,1,2,3 into a Filter Type field yields banks that load but behave
    wrongly. `MotionDomain` (core.motion) does the snapping; this table supplies
    the N and kind per target.
"""

from __future__ import annotations

from typing import Iterator, Sequence


class MotionTarget:
    """Immutable description of one motion target id."""

    __slots__ = ("_target_id", "_name", "_group", "_kind",
                 "_option_count", "_forced_trig")

    # kind is one of: "continuous" | "bipolar" | "boolean" | "enum"
    def __init__(self, target_id: int, name: str, group: str, kind: str,
                 option_count: int, forced_trig: bool):
        self._target_id = target_id
        self._name = name
        self._group = group
        self._kind = kind
        self._option_count = option_count
        self._forced_trig = forced_trig

    @property
    def target_id(self) -> int:
        return self._target_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def group(self) -> str:
        """UI grouping: Part Common / Filter / Modulation / Effects (TDD §8.5)."""
        return self._group

    @property
    def kind(self) -> str:
        return self._kind

    @property
    def option_count(self) -> int:
        """N for discrete kinds (boolean=2, enum=N); 0 for continuous/bipolar."""
        return self._option_count

    @property
    def forced_trig(self) -> bool:
        """True if this target always plays back stepped, even under SMOOTH."""
        return self._forced_trig


class OperationTable:
    """The full 313-target table, loaded from the research TSVs."""

    __slots__ = ("_by_id",)

    def __init__(self, by_id: dict[int, MotionTarget]):
        self._by_id = dict(by_id)

    @classmethod
    def load(cls, research_dir: str) -> "OperationTable":
        """Build the table from the TSV/markdown sources in `research_dir`.

        Raises FileNotFoundError if the sources are missing and CodecError if
        the row count does not match the expected 313 targets.
        """
        raise NotImplementedError

    def get(self, target_id: int) -> MotionTarget:
        """Return the target for an id, or raise KeyError if unknown."""
        raise NotImplementedError

    def get_or_none(self, target_id: int) -> MotionTarget | None:
        """Return the target for an id, or None if it is not in the table."""
        raise NotImplementedError

    def is_known(self, target_id: int) -> bool:
        raise NotImplementedError

    def targets_for_part(self, part_kind: str) -> Sequence[MotionTarget]:
        """Targets a given part type may automate (TDD §8.5 target picker).

        Accent offers only LEVEL; audio-in hides Pitch/Start/Reverse; keyboard
        swaps Pitch for Glide and adds OSC EDIT 1/2.
        """
        raise NotImplementedError

    def __iter__(self) -> Iterator[MotionTarget]:
        raise NotImplementedError

    def __len__(self) -> int:
        return len(self._by_id)
