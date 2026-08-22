"""
workspace.budget — the exact sample-memory scoreboard (TDD §06).

WHY IT IS EXACT, NOT AN ESTIMATE
    The .esx stores uncompressed 16-bit PCM: no codec, no VBR. So cost is
    closed-form and needs only the duration (read from the header, no decode):
        frames = round(duration_s * rate)
        cost   = align_up(frames * 2 * channels + 2, 4)   # allocation rule
    Uncertainty is +/-1 frame of resampler rounding (+/-2 bytes on 25 MB).

Ported in contract form from spike_a/budget.py; bodies land in a later workflow.
"""

from __future__ import annotations

from typing import Sequence


# The quality ladder offered in the UI (label, rate). TDD §6.3.
TIERS: tuple[tuple[str, int], ...] = (
    ("CD", 44100),
    ("Broadcast", 32000),
    ("Radio", 22050),
    ("Lo-fi", 16000),
    ("Telephone", 11025),
)
DEFAULT_RATE = 44100


class BudgetItem:
    """One sample under consideration: its duration, source rate, channels."""

    __slots__ = ("_name", "_duration_s", "_source_rate", "_channels")

    def __init__(self, name: str, duration_s: float,
                 source_rate: int, channels: int):
        self._name = name
        self._duration_s = duration_s
        self._source_rate = source_rate
        self._channels = channels

    @property
    def name(self) -> str:
        return self._name

    @property
    def duration_s(self) -> float:
        return self._duration_s

    @property
    def channels(self) -> int:
        return self._channels


class BudgetCalculator:
    """Computes exact memory cost and 'what-if' ladders without re-encoding."""

    __slots__ = ()

    @staticmethod
    def align_up(n: int, boundary: int) -> int:
        raise NotImplementedError

    def cost_bytes(self, duration_s: float, rate: int, channels: int = 1) -> int:
        """Exact bytes a sample occupies at a rate: align_up(frames*2*ch + 2, 4)."""
        raise NotImplementedError

    def total_cost(self, items: Sequence[BudgetItem],
                   rate_for=None) -> int:
        """Sum the cost of every item; rate_for(name)->rate overrides the default."""
        raise NotImplementedError

    def seconds_available(self, rate: int, channels: int = 1) -> float:
        """Seconds of audio that fit in an empty bank at this rate."""
        raise NotImplementedError
