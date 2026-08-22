"""
core.errors — exceptions raised when a domain invariant is violated.

WHY
    The domain model refuses to hold illegal state (TDD §3.2). Every constructor
    and mutator that enforces an invariant raises InvariantError with a message
    naming the invariant, so callers and tests get a precise, catchable signal
    rather than a generic ValueError buried among unrelated ones.
"""

from __future__ import annotations


class InvariantError(ValueError):
    """A domain invariant would be violated by the attempted operation.

    Examples (TDD §3.2):
        - a Pattern given other than exactly 24 motion slots
        - a MotionSlot given other than exactly 128 values
        - a sample name that is not exactly 8 bytes
        - committing sample PCM that would exceed 25,165,824 B
        - any attempt to modify an unknown region
    """
