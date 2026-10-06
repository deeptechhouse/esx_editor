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

from collections.abc import Callable, Sequence

import codec.layout as L

# The quality ladder offered in the UI (label, rate). TDD §6.3.
TIERS: tuple[tuple[str, int], ...] = (
    ("CD", 44100),
    ("Broadcast", 32000),
    ("Radio", 22050),
    ("Lo-fi", 16000),
    ("Telephone", 11025),
)
DEFAULT_RATE = 44100
CAPACITY = L.MAX_SAMPLE_BYTES  # 25,165,824 bytes


class BudgetItem:
    """One sample under consideration: its duration, source rate, channels."""

    __slots__ = ("_name", "_duration_s", "_source_rate", "_channels")

    # O(1) time, O(1) space
    def __init__(self, name: str, duration_s: float, source_rate: int, channels: int):
        self._name = name
        self._duration_s = duration_s
        self._source_rate = source_rate
        self._channels = channels

    @property
    # O(1) time, O(1) space
    def name(self) -> str:
        return self._name

    @property
    # O(1) time, O(1) space
    def duration_s(self) -> float:
        return self._duration_s

    @property
    # O(1) time, O(1) space
    def channels(self) -> int:
        return self._channels


class BudgetCalculator:
    """Computes exact memory cost and 'what-if' ladders without re-encoding."""

    __slots__ = ()

    @staticmethod
    # O(1) time, O(1) space
    def align_up(n: int, boundary: int) -> int:
        if boundary <= 0:
            raise ValueError(f"alignment boundary must be > 0, got {boundary}")
        return ((n + boundary - 1) // boundary) * boundary

    # O(1) time, O(1) space
    def cost_bytes(self, duration_s: float, rate: int, channels: int = 1) -> int:
        """Exact bytes a sample consumes, block header included.

            align_up(16 + frames*2*channels + 2, 4)

        The 16 is the PCM block header every sample carries (see
        codec.layout). It was missing until 2026-08-23, which under-counted
        every sample by 16 bytes — small per sample, but 384 of them is 6 KB of
        phantom free space, and the scoreboard's whole job is to be exact.

        Verified against real allocation: sample 0 of Chronic-Interactive.esx is
        8,488 frames and the next sample starts at 16,996 — which is
        align_up(16 + 16,976 + 2, 4).
        """
        if duration_s < 0 or rate <= 0 or channels < 1:
            raise ValueError(
                f"invalid cost inputs: duration={duration_s} rate={rate} ch={channels}"
            )
        frames = int(round(duration_s * rate))
        raw = frames * 2 * channels
        return self.align_up(L.PCM_BLOCK_HEADER_LEN + raw + 2, 4)

    # O(n) time, O(1) space — n = items (rate_for is called once per item and assumed constant-time)
    def total_cost(
        self, items: Sequence[BudgetItem], rate_for: Callable[[str], int] | None = None
    ) -> int:
        """Sum the cost of every item; rate_for(name)->rate overrides the default."""
        lookup = rate_for or (lambda _name: DEFAULT_RATE)
        # O(n) time, O(1) space — n = items
        return sum(
            self.cost_bytes(item.duration_s, lookup(item.name), item.channels)
            for item in items
        )

    # O(1) time, O(1) space
    def seconds_available(self, rate: int, channels: int = 1) -> float:
        """Seconds of audio that fit in an empty bank at this rate."""
        if rate <= 0 or channels < 1:
            raise ValueError(f"invalid rate/channels: {rate}/{channels}")
        return CAPACITY / (rate * 2 * channels)

    # O(1) time, O(1) space
    def remaining_bytes(self, used: int) -> int:
        """Bytes still free given a currently-used total (may be negative)."""
        return CAPACITY - used
