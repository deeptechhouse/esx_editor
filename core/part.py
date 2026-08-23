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

from core.errors import InvariantError

# Part kinds (used by the operation table's target picker, TDD §8.5).
KIND_DRUM = "drum"
KIND_KEYBOARD = "keyboard"
KIND_STRETCHSLICE = "stretchslice"
KIND_AUDIOIN = "audioin"
KIND_ACCENT = "accent"


class SequenceData:
    """The per-step trigger/note data for one part (up to 128 steps)."""

    __slots__ = ("_steps",)

    def __init__(self, steps: bytes):
        self._steps = bytearray(steps)

    @property
    def steps(self) -> bytes:
        """Defensive copy of the raw per-step bytes."""
        return bytes(self._steps)

    def is_active(self, step: int) -> bool:
        """True if the given step triggers. (Decode deferred to a later WF.)"""
        raise NotImplementedError

    def set_active(self, step: int, active: bool) -> None:
        raise NotImplementedError


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
        """Which sample slot this part plays. (Decode deferred to a later WF.)"""
        raise NotImplementedError

    def sequence(self) -> SequenceData:
        """The part's step sequence data. (Decode deferred to a later WF.)"""
        raise NotImplementedError

    def to_bytes(self) -> bytes:
        return bytes(self._raw)

    @classmethod
    def from_bytes(cls, kind: str, index: int, raw: bytes) -> Part:
        if not raw:
            raise InvariantError("part raw bytes must be non-empty")
        return cls(kind, index, raw)
