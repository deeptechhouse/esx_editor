"""
core.bank — Bank (the whole in-memory model) and RawRegions (verbatim bytes).

Bank is the aggregate root: global params, 256 patterns, 384 sample slots, the
raw PCM, and RawRegions holding every byte the codec has not decoded.

RAW REGIONS (TDD §4.1, §3.2)
    The documented unknown regions AND every other undecoded span (the magic
    header, the whole song/song-event area, the slice/trailer area) are held
    here as read-only bytes. There is deliberately NO setter, so the invariant
    "unknown regions are never modified" is enforced structurally. The writer
    replays them verbatim, which is what guarantees byte-identical round-trips.

SAVE TYPE (TDD §2.5)
    A Bank remembers whether it came from a Save-All or a Save-PSG image so the
    writer emits the same form. A PSG bank keeps its whole image verbatim under
    the "psg_image" raw region until the PSG layout is decoded in a later WF.

CAPACITY INVARIANT (TDD §3.2)
    Total committed PCM must never exceed 25,165,824 B.
"""

from __future__ import annotations

import struct
from typing import Sequence

from core.errors import InvariantError
from core.global_params import GlobalParameters
from core.pattern import Pattern
from core.song import Song
from core.sample import SampleSlot
import codec.layout as L


SAVE_ALL = "all"
SAVE_PSG = "psg"


class RawRegions:
    """Read-only container for every undecoded byte range, keyed by name."""

    __slots__ = ("_regions",)

    def __init__(self, regions: dict[str, bytes]):
        self._regions = {k: bytes(v) for k, v in regions.items()}

    def names(self) -> tuple[str, ...]:
        return tuple(self._regions.keys())

    def has(self, name: str) -> bool:
        return name in self._regions

    def get(self, name: str) -> bytes:
        """Return the verbatim bytes for a named region (a copy)."""
        try:
            return bytes(self._regions[name])
        except KeyError:
            raise KeyError(f"no raw region named {name!r}") from None


class Bank:
    """The complete, editable model of one .esx bank."""

    __slots__ = ("_globals", "_patterns", "_songs", "_samples",
                 "_pcm", "_raw", "_save_type")

    NUM_PATTERNS = L.NUM_PATTERNS
    NUM_SONGS = L.NUM_SONGS
    NUM_SAMPLES = L.NUM_SAMPLES
    NUM_SAMPLES_MONO = L.NUM_SAMPLES_MONO
    MAX_PCM_BYTES = L.MAX_SAMPLE_BYTES       # 25,165,824

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
        """Immutable view of the patterns."""
        return tuple(self._patterns)

    def songs(self) -> tuple[Song, ...]:
        """Immutable view of the songs.

        WF2 keeps the song area inside RawRegions ('mid') verbatim, so this is
        empty until song decoding is implemented; the data is never lost.
        """
        return tuple(self._songs)

    def samples(self) -> tuple[SampleSlot, ...]:
        """Immutable view of the 384 sample slots (256 mono + 128 stereo)."""
        return tuple(self._samples)

    @property
    def raw_regions(self) -> RawRegions:
        return self._raw

    @property
    def pcm(self) -> bytes:
        """The raw PCM region (channel data appended after currentOffset)."""
        return self._pcm

    # -- sample-area bookkeeping -------------------------------------------
    def sample_area_header(self) -> tuple[int, int, int]:
        """Return (num_mono, num_stereo, current_offset) from the magic-2 block.

        These live inside the verbatim 'mid' region; this reads them without
        modifying anything. Raises InvariantError for a PSG bank (no sample area).
        """
        if self._save_type == SAVE_PSG or not self._raw.has("mid"):
            raise InvariantError("bank has no sample area (PSG save)")
        mid = self._raw.get("mid")
        mid_start = L.ADDR_PATTERN_DATA + L.NUM_PATTERNS * L.CHUNK_PATTERN
        n_mono = struct.unpack_from(">I", mid, L.ADDR_NUM_MONO_SAMPLES - mid_start)[0]
        n_ster = struct.unpack_from(">I", mid, L.ADDR_NUM_STEREO_SAMPLES - mid_start)[0]
        cur = struct.unpack_from(">I", mid, L.ADDR_CURRENT_OFFSET - mid_start)[0]
        return n_mono, n_ster, cur

    def pcm_used_bytes(self) -> int:
        """Total PCM currently committed (from currentOffset)."""
        try:
            return self.sample_area_header()[2]
        except InvariantError:
            return len(self._pcm)

    def pcm_free_bytes(self) -> int:
        """MAX_PCM_BYTES minus pcm_used_bytes()."""
        return self.MAX_PCM_BYTES - self.pcm_used_bytes()

    def commit_sample(self, slot_index: int, pcm: bytes,
                      *, stereo: bool, sample_rate: int, name: str) -> None:
        """Append PCM at currentOffset and write the slot header.

        Enforces the capacity invariant before mutating. Full implementation
        (offset allocation, header write-back, count update) lands with the
        staging workflow; the capacity guard is active now.
        """
        if len(pcm) > self.pcm_free_bytes():
            raise InvariantError(
                f"sample of {len(pcm):,} B exceeds free space "
                f"{self.pcm_free_bytes():,} B (cap {self.MAX_PCM_BYTES:,} B)")
        raise NotImplementedError("sample commit lands with the staging workflow")

    def clear_sample(self, slot_index: int) -> None:
        raise NotImplementedError("sample clear lands with the staging workflow")
