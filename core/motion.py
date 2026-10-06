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

import struct

from core.errors import InvariantError


class MotionDomain:
    """How one target's stored bytes map to musical values, and back.

    Constructed from a codec.operation_table.MotionTarget. Encapsulates the
    kind (continuous/bipolar/boolean/enum), the option count N for discrete
    kinds, and the forced-TRIG flag.
    """

    __slots__ = ("_kind", "_option_count", "_forced_trig")

    CONTINUOUS = "continuous"
    BIPOLAR = "bipolar"
    BOOLEAN = "boolean"
    ENUM = "enum"

    # O(1) time, O(1) space
    def __init__(self, kind: str, option_count: int, forced_trig: bool):
        self._kind = kind
        self._option_count = option_count
        self._forced_trig = forced_trig
        if kind in (self.BOOLEAN, self.ENUM):
            self._reject_inexpressible_option_count()

    # O(1) time, O(1) space
    def _reject_inexpressible_option_count(self) -> None:
        """Refuse an option count the VERIFIED rule cannot express.

        `value = i * ceil(128 / N)` is PROVEN for N = 2, 3, 4 (Spike A, against
        297 populated slots). Extrapolated to larger N it eventually produces
        bytes outside the 0-127 knob range: N=14 tops out at 130, and twelve
        values of N — 17, 18, 33..42 — produce exactly **128**, which is the
        Disabl sentinel. Writing that would silently turn an option index into
        "do not update this step", and nothing downstream could tell.

        The shipped 313-target table only uses N = 2 and N = 4, so this is not
        reachable today. It is still refused rather than clamped, because a
        clamp would break `decode(encode(i)) == i` and would be a guess at a
        rule we have no data for. If a real target ever needs such an N, the
        encoding must be established on hardware first.
        """
        if self._option_count < 1:
            raise InvariantError("discrete domain needs option_count >= 1")
        step = -(-128 // self._option_count)
        top = step * (self._option_count - 1)
        if top > 127:
            raise InvariantError(
                f"option_count {self._option_count} is not expressible by the "
                f"verified rule i * ceil(128/N): the top option would store as "
                f"{top}, outside the 0-127 knob range"
                + (" and colliding with the Disabl sentinel 128" if top == 128 else "")
                + ". The encoding for this option count is unproven."
            )

    @property
    # O(1) time, O(1) space
    def kind(self) -> str:
        return self._kind

    @property
    # O(1) time, O(1) space
    def forced_trig(self) -> bool:
        return self._forced_trig

    # O(1) time, O(1) space
    def _step(self) -> int:
        """Byte spacing per option for a discrete kind: ceil(128 / N)."""
        if self._option_count < 1:
            raise InvariantError("discrete domain needs option_count >= 1")
        return -(-128 // self._option_count)

    # O(1) time, O(1) space
    def encode(self, value: int) -> int:
        """Musical/option value -> stored byte (0-127).

        For discrete kinds this snaps an option index to its knob position via
        value = index * ceil(128 / N). For continuous/bipolar it validates the
        range and returns the byte unchanged. Raises InvariantError on an
        out-of-domain value.
        """
        if self._kind in (self.BOOLEAN, self.ENUM):
            if not (0 <= value < self._option_count):
                raise InvariantError(
                    f"option index {value} out of range 0..{self._option_count - 1}"
                )
            return value * self._step()
        # continuous / bipolar are stored as a raw 0..127 byte
        if not (0 <= value <= 127):
            raise InvariantError(f"continuous value {value} out of range 0..127")
        return value

    # O(1) time, O(1) space
    def decode(self, stored: int) -> int:
        """Stored byte -> musical/option value (inverse of encode)."""
        if self._kind in (self.BOOLEAN, self.ENUM):
            return stored // self._step()
        return stored

    # O(N) time, O(N) space — N = stored values in the domain (the option count, at most 128 because __init__ rejects anything larger, or 128 for continuous)
    def legal_values(self) -> tuple[int, ...]:
        """The stored bytes this domain permits (for snapping/UI)."""
        if self._kind in (self.BOOLEAN, self.ENUM):
            step = self._step()
            # O(N) time, O(N) space — N = option count (at most 128, enforced in __init__)
            return tuple(i * step for i in range(self._option_count))
        return tuple(range(128))

    # O(N) time, O(N) space — N = stored values in the domain (the option count, at most 128 because __init__ rejects anything larger, or 128 for continuous) (builds legal_values, then a min over it)
    def snap_stored(self, raw: int) -> int:
        """Clamp a raw 0–127 to a legal stored byte for this domain.

        Discrete kinds snap to the nearest knob position (i * ceil(128/N));
        continuous/bipolar clamp to 0–127 with no extra snap. Never returns the
        Disabl sentinel — that is a third state, not a value.
        """
        raw = max(0, min(127, int(raw)))
        if self._kind not in (self.BOOLEAN, self.ENUM):
            return raw
        legal = self.legal_values()
        return min(legal, key=lambda v: abs(v - raw))

    # O(1) time, O(1) space
    def is_discrete(self) -> bool:
        return self._kind in (self.BOOLEAN, self.ENUM)

    @classmethod
    # O(1) time, O(1) space
    def continuous(cls, forced_trig: bool = False) -> MotionDomain:
        return cls(cls.CONTINUOUS, 0, forced_trig)

    @classmethod
    # O(1) time, O(1) space
    def discrete(cls, option_count: int, forced_trig: bool = True) -> MotionDomain:
        return cls(cls.ENUM, option_count, forced_trig)


class MotionSlot:
    """One motion sequence: a target parameter + one value per step.

    Invariants (TDD §3.2):
        - always exactly 128 values
        - each value is 0-127 or the Disabl sentinel (0x80)
    """

    __slots__ = ("_target", "_values")

    DISABLED = 0x80  # per-step "do not update" sentinel
    EMPTY_TARGET = 0xFFFF  # slot is unused
    NUM_STEPS = 128
    CHUNK_SIZE = 130  # 2-byte target + 128 values

    # O(T) time, O(T) space — T = 128 steps (copied into a bytearray)
    def __init__(self, target: int, values: bytes):
        if len(values) != self.NUM_STEPS:
            raise InvariantError(
                f"motion needs exactly {self.NUM_STEPS} values, got {len(values)}"
            )
        if not (0 <= target <= 0xFFFF):
            raise InvariantError(f"motion target {target} out of uint16 range")
        self._target = target
        self._values = bytearray(values)

    @property
    # O(1) time, O(1) space
    def target(self) -> int:
        return self._target

    @property
    # O(T) time, O(T) space — T = 128 steps (defensive copy)
    def values(self) -> bytes:
        """Defensive copy -- callers cannot mutate internal state."""
        return bytes(self._values)

    @property
    # O(1) time, O(1) space
    def in_use(self) -> bool:
        return self._target != self.EMPTY_TARGET

    # O(1) time, O(1) space
    def set_target(self, target: int) -> None:
        if not (0 <= target <= 0xFFFF):
            raise InvariantError(f"motion target {target} out of uint16 range")
        self._target = target

    # O(1) time, O(1) space
    def set_step(self, step: int, value: int | None, domain: MotionDomain) -> None:
        """Set one step. `value=None` means Disabl.

        The domain snaps discrete targets to legal knob positions, so a caller
        cannot write 1 into a Filter Type field that only accepts 0/32/64/96.
        Raises InvariantError if step is out of range.
        """
        if not (0 <= step < self.NUM_STEPS):
            raise InvariantError(f"step {step} out of range 0..{self.NUM_STEPS - 1}")
        self._values[step] = self.DISABLED if value is None else domain.encode(value)

    # O(N) time, O(N) space — N = stored values in the domain (the option count, at most 128 because __init__ rejects anything larger, or 128 for continuous) (via snap_stored)
    def write_stored(
        self,
        step: int,
        stored: int | None,
        domain: MotionDomain,
        *,
        length: int = NUM_STEPS,
    ) -> None:
        """Write a raw 0–127 (or None=Disabl), snapping discrete targets.

        Steps at or beyond `length` are masked and left untouched (TDD §8.2 / §8.5).
        """
        if not (0 <= step < self.NUM_STEPS):
            raise InvariantError(f"step {step} out of range 0..{self.NUM_STEPS - 1}")
        if step >= length:
            return
        if stored is None:
            self._values[step] = self.DISABLED
            return
        snapped = domain.snap_stored(stored)
        if domain.is_discrete():
            self.set_step(step, domain.decode(snapped), domain)
        else:
            self.set_step(step, snapped, domain)

    @classmethod
    # O(T) time, O(T) space — T = 128 steps
    def empty(cls) -> MotionSlot:
        return cls(cls.EMPTY_TARGET, bytes([cls.DISABLED] * cls.NUM_STEPS))

    # O(1) time, O(1) space
    def get_step(self, step: int) -> int:
        """Return the raw stored byte at a step (may be the Disabl sentinel)."""
        if not (0 <= step < self.NUM_STEPS):
            raise InvariantError(f"step {step} out of range 0..{self.NUM_STEPS - 1}")
        return self._values[step]

    # O(1) time, O(1) space
    def is_disabled(self, step: int) -> bool:
        return self.get_step(step) == self.DISABLED

    # O(T) time, O(T) space — T = 128 steps
    def clear(self) -> None:
        """Mark the slot unused and fill every step with Disabl."""
        self._target = self.EMPTY_TARGET
        self._values = bytearray([self.DISABLED] * self.NUM_STEPS)

    # O(T) time, O(T) space — T = 128 steps
    def to_bytes(self) -> bytes:
        """Serialize to the 130-byte on-disk form (uint16 target + 128 values)."""
        return struct.pack(">H", self._target) + bytes(self._values)

    @classmethod
    # O(T) time, O(T) space — T = 128 steps
    def from_bytes(cls, raw: bytes) -> MotionSlot:
        """Parse the 130-byte on-disk form."""
        if len(raw) != cls.CHUNK_SIZE:
            raise InvariantError(
                f"motion chunk must be {cls.CHUNK_SIZE} bytes, got {len(raw)}"
            )
        (target,) = struct.unpack_from(">H", raw, 0)
        return cls(target, raw[2:])
