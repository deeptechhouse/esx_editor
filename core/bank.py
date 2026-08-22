"""
core.bank — Bank (the whole in-memory model) and RawRegions (verbatim bytes).

Bank is the aggregate root: global params, 256 patterns, 64 songs, 384 sample
slots, the raw PCM, and RawRegions holding every byte the codec has not decoded.

RAW REGIONS (TDD §4.1, §3.2)
    The five documented unknown regions AND anything else undecoded are held
    here as read-only bytes. There is deliberately NO setter: the invariant
    "unknown regions are never modified" is enforced by the absence of any way
    to change them. The writer replays them verbatim.

SAVE TYPE
    A Bank remembers whether it came from a Save-All or a Save-PSG image so the
    writer emits the same form (TDD §2.5).

CAPACITY INVARIANT (TDD §3.2)
    Total committed PCM must never exceed 25,165,824 B; commit_sample() raises
    InvariantError BEFORE mutating if a sample would overflow the budget.
"""

from __future__ import annotations

from typing import Sequence

from core.global_params import GlobalParameters
from core.pattern import Pattern
from core.song import Song
from core.sample import SampleSlot


SAVE_ALL = "all"
SAVE_PSG = "psg"


class RawRegions:
    """Read-only container for every undecoded byte range, keyed by name.

    Exposes bytes only; there is no mutator, which is how the "never modify an
    unknown region" invariant is enforced structurally (TDD §3.2).
    """

    __slots__ = ("_regions",)

    def __init__(self, regions: dict[str, bytes]):
        self._regions = {k: bytes(v) for k, v in regions.items()}

    def names(self) -> tuple[str, ...]:
        return tuple(self._regions.keys())

    def get(self, name: str) -> bytes:
        """Return the verbatim bytes for a named region (a copy)."""
        raise NotImplementedError


class Bank:
    """The complete, editable model of one .esx bank."""

    __slots__ = ("_globals", "_patterns", "_songs", "_samples",
                 "_pcm", "_raw", "_save_type")

    NUM_PATTERNS = 256
    NUM_SONGS = 64
    NUM_SAMPLES = 384
    MAX_PCM_BYTES = 0xC00000 * 2       # 25,165,824

    def __init__(self, globals_: GlobalParameters,
                 patterns: Sequence[Pattern], songs: Sequence[Song],
                 samples: Sequence[SampleSlot], pcm: bytes,
                 raw: RawRegions, save_type: str = SAVE_ALL):
        self._globals = globals_
        self._patterns = list(patterns)
        self._songs = list(songs)
        self._samples = list(samples)
        self._pcm = bytes(pcm)
        self._raw = raw
        self._save_type = save_type

    @property
    def save_type(self) -> str:
        """SAVE_ALL or SAVE_PSG (TDD §2.5)."""
        return self._save_type

    @property
    def globals(self) -> GlobalParameters:
        return self._globals

    def patterns(self) -> tuple[Pattern, ...]:
        """Immutable view of the 256 patterns."""
        return tuple(self._patterns)

    def songs(self) -> tuple[Song, ...]:
        return tuple(self._songs)

    def samples(self) -> tuple[SampleSlot, ...]:
        """Immutable view of the 384 sample slots (256 mono + 128 stereo)."""
        return tuple(self._samples)

    @property
    def raw_regions(self) -> RawRegions:
        return self._raw

    def pcm_used_bytes(self) -> int:
        """Total PCM currently committed."""
        raise NotImplementedError

    def pcm_free_bytes(self) -> int:
        """MAX_PCM_BYTES minus pcm_used_bytes()."""
        raise NotImplementedError

    def commit_sample(self, slot_index: int, pcm: bytes,
                      *, stereo: bool, sample_rate: int, name: str) -> None:
        """Append PCM at currentOffset and write the slot header.

        Raises InvariantError BEFORE any mutation if the sample would push total
        PCM past MAX_PCM_BYTES (TDD §3.2). Offsets follow the verified
        allocation rule next_start = align_up(previous_end + 2, 4).
        """
        raise NotImplementedError

    def clear_sample(self, slot_index: int) -> None:
        """Mark a sample slot empty. PCM compaction is a separate explicit step."""
        raise NotImplementedError
