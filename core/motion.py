"""
core.motion — MotionSlot (the data) and MotionDomain (how a target's values
are interpreted, snapped, and rendered).

DATA MODEL (TDD §8.1, VERIFIED)
    A MotionSlot is 130 bytes: uint16 big-endian target id + 128 value bytes,
    24 slots per pattern at pattern offset 1160.
        target == 0xFFFF  -> slot unused
        value  == 0x80    -> Disabl ("do not update at this step")

THREE STATES OF A STEP (TDD §8.2)
    A step is a value, or Disabl, or beyond the pattern length. The editor
    renders Disabl as a GAP, never as zero -- zero is musically the opposite of
    leaving a parameter alone.

VALUE DOMAINS (TDD §8.3, VERIFIED)
    Discrete targets store KNOB POSITIONS: value = index * ceil(128 / N).
        N=2 -> {0,64}   N=3 -> {0,43,86}   N=4 -> {0,32,64,96}
    Continuous targets store 0-127 directly; bipolar centre at zero.

PLAYBACK MODE (TDD §8.4)
    Some targets always play stepped even under SMOOTH (forced TRIG HOLD). The
    domain carries that flag so the canvas draws latched staircases where the
    hardware would, instead of curves it will never produce.
"""

from __future__ import annotations

from core.errors import InvariantError


class MotionDomain:
    """How one target's stored bytes map to musical values, and back.

    Constructed from a codec.operation_table.MotionTarget. Encapsulates the
    kind (continuous/bipolar/boolean/enum), the option count N for discrete
    kinds, and the forced-TRIG flag.
    """

    __slots__ = ("_kind", "_option_count", "_forced_trig")

    def __init__(self, kind: str, option_count: int, forced_trig: bool):
        self._kind = kind
        self._option_count = option_count
        self._forced_trig = forced_trig

    @property
    def kind(self) -> str:
        return self._kind

    @property
    def forced_trig(self) -> bool:
        return self._forced_trig

    def encode(self, value: int) -> int:
        """Musical/option value -> stored byte (0-127).

        For discrete kinds this snaps an option index to its knob position via
        value = index * ceil(128 / N). For continuous/bipolar it validates the
        range and returns the byte unchanged. Raises InvariantError on an
        out-of-domain value.
        """
        raise NotImplementedError

    def decode(self, stored: int) -> int:
        """Stored byte -> musical/option value (inverse of encode)."""
        raise NotImplementedError

    def legal_values(self) -> tuple[int, ...]:
        """The stored bytes this domain permits (for snapping/UI). Continuous
        returns the full 0-127 range; enum/boolean return only knob positions."""
        raise NotImplementedError


class MotionSlot:
    """One motion sequence: a target parameter + one value per step.

    Invariants (TDD §3.2):
        - always exactly 128 values
        - each value is 0-127 or the Disabl sentinel (0x80)
    """

    __slots__ = ("_target", "_values")

    DISABLED = 0x80          # per-step "do not update" sentinel
    EMPTY_TARGET = 0xFFFF    # slot is unused
    NUM_STEPS = 128

    def __init__(self, target: int, values: bytes):
        if len(values) != self.NUM_STEPS:
            raise InvariantError(
                f"motion needs exactly {self.NUM_STEPS} values, got {len(values)}")
        self._target = target
        self._values = bytearray(values)

    @property
    def target(self) -> int:
        return self._target

    @property
    def values(self) -> bytes:
        """Defensive copy -- callers cannot mutate internal state."""
        return bytes(self._values)

    @property
    def in_use(self) -> bool:
        return self._target != self.EMPTY_TARGET

    def set_step(self, step: int, value: int | None,
                 domain: "MotionDomain") -> None:
        """Set one step. `value=None` means Disabl.

        The domain snaps discrete targets to legal knob positions, so a caller
        cannot write 1 into a Filter Type field that only accepts 0/32/64/96.
        Raises InvariantError if step is out of range.
        """
        raise NotImplementedError

    def get_step(self, step: int) -> int:
        """Return the raw stored byte at a step (may be the Disabl sentinel)."""
        raise NotImplementedError

    def is_disabled(self, step: int) -> bool:
        raise NotImplementedError

    def clear(self) -> None:
        """Mark the slot unused and fill every step with Disabl."""
        raise NotImplementedError

    def to_bytes(self) -> bytes:
        """Serialize to the 130-byte on-disk form (uint16 target + 128 values)."""
        raise NotImplementedError

    @classmethod
    def from_bytes(cls, raw: bytes) -> "MotionSlot":
        """Parse the 130-byte on-disk form."""
        raise NotImplementedError
