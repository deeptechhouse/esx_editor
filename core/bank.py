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
from collections.abc import Sequence

import codec.layout as L
from core.errors import InvariantError
from core.global_params import GlobalParameters
from core.pattern import Pattern
from core.sample import SampleSlot
from core.song import Song

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


class SampleArea:
    """The decoded sample-area header: two counts and the PCM write cursor.

    WHY THIS IS NOT A RAW REGION
        These twelve bytes at 0x1B0020..0x1B002B are VERIFIED (TDD §2.1), not
        unknown — but the reader originally swept them into the verbatim "mid"
        blob along with the songs and the undecoded gaps. That made them
        unwritable, and committing a sample is impossible without updating
        them: the counts say how many slots are occupied and currentOffset says
        where the next sample's PCM goes.

        So they are decoded here. "Unknown regions are never modified" still
        holds structurally — RawRegions still has no setter. This is simply no
        longer an unknown region, and pretending it was one blocked the feature
        the whole app exists for.
    """

    __slots__ = ("_num_mono", "_num_stereo", "_current_offset")

    def __init__(self, num_mono: int, num_stereo: int, current_offset: int):
        self._num_mono = num_mono
        self._num_stereo = num_stereo
        self._current_offset = current_offset

    @property
    def num_mono(self) -> int:
        return self._num_mono

    @property
    def num_stereo(self) -> int:
        return self._num_stereo

    @property
    def current_offset(self) -> int:
        """Byte offset (relative to ADDR_SAMPLE_DATA) of the next free write."""
        return self._current_offset

    def set_counts(self, num_mono: int, num_stereo: int) -> None:
        if num_mono < 0 or num_mono > L.NUM_SAMPLES_MONO:
            raise InvariantError(f"mono count {num_mono} out of range")
        if num_stereo < 0 or num_stereo > L.NUM_SAMPLES_STEREO:
            raise InvariantError(f"stereo count {num_stereo} out of range")
        self._num_mono = num_mono
        self._num_stereo = num_stereo

    def set_current_offset(self, value: int) -> None:
        if value < 0 or value > L.MAX_SAMPLE_BYTES:
            raise InvariantError(
                f"currentOffset {value} outside 0..{L.MAX_SAMPLE_BYTES}"
            )
        self._current_offset = value

    def to_bytes(self) -> bytes:
        """The 12 bytes as they appear at ADDR_NUM_MONO_SAMPLES."""
        return struct.pack(
            ">III", self._num_mono, self._num_stereo, self._current_offset
        )

    @classmethod
    def from_bytes(cls, raw: bytes) -> SampleArea:
        if len(raw) != 12:
            raise InvariantError(f"sample-area header must be 12 bytes, got {len(raw)}")
        return cls(*struct.unpack(">III", raw))

    @classmethod
    def empty(cls) -> SampleArea:
        return cls(0, 0, 0)


class Bank:
    """The complete, editable model of one .esx bank."""

    __slots__ = (
        "_globals",
        "_patterns",
        "_songs",
        "_samples",
        "_pcm",
        "_raw",
        "_save_type",
        "_sample_area",
        "_trailer",
    )

    NUM_PATTERNS = L.NUM_PATTERNS
    NUM_SONGS = L.NUM_SONGS
    NUM_SAMPLES = L.NUM_SAMPLES
    NUM_SAMPLES_MONO = L.NUM_SAMPLES_MONO
    MAX_PCM_BYTES = L.MAX_SAMPLE_BYTES  # 25,165,824

    def __init__(
        self,
        globals_: GlobalParameters,
        patterns: Sequence[Pattern],
        songs: Sequence[Song],
        samples: Sequence[SampleSlot],
        pcm: bytes,
        raw: RawRegions,
        save_type: str = SAVE_ALL,
        sample_area: SampleArea | None = None,
    ):
        self._globals = globals_
        self._patterns = list(patterns)
        self._songs = list(songs)
        self._samples = list(samples)
        self._pcm = bytearray(pcm)
        self._raw = raw
        self._save_type = save_type
        self._sample_area = sample_area or SampleArea.empty()
        # The 16-byte PCM trailer, captured where the bank says it lives rather
        # than from the tail of the region: after a commit the tail is sample
        # data, so reading it back then would silently store PCM as a trailer.
        cursor = self._sample_area.current_offset
        tail = bytes(self._pcm[cursor : cursor + L.PCM_TRAILER_LEN])
        self._trailer = (
            tail if len(tail) == L.PCM_TRAILER_LEN else L.PCM_TRAILER_DEFAULT
        )

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
        """The raw PCM region (a defensive copy)."""
        return bytes(self._pcm)

    @property
    def sample_area(self) -> SampleArea:
        """Decoded counts + currentOffset (TDD §2.1)."""
        return self._sample_area

    # -- sample-area bookkeeping -------------------------------------------
    def sample_area_header(self) -> tuple[int, int, int]:
        """Return (num_mono, num_stereo, current_offset).

        Reads the decoded SampleArea. Raises InvariantError for a PSG bank,
        which has no sample area at all.
        """
        if self._save_type == SAVE_PSG:
            raise InvariantError("bank has no sample area (PSG save)")
        area = self._sample_area
        return area.num_mono, area.num_stereo, area.current_offset

    def pcm_used_bytes(self) -> int:
        """Total PCM currently committed (from currentOffset)."""
        try:
            return self.sample_area_header()[2]
        except InvariantError:
            return len(self._pcm)

    def pcm_free_bytes(self) -> int:
        """MAX_PCM_BYTES minus pcm_used_bytes()."""
        return self.MAX_PCM_BYTES - self.pcm_used_bytes()

    def commit_sample(
        self,
        slot_index: int,
        pcm: bytes,
        *,
        stereo: bool,
        sample_rate: int,
        name: str,
        musical_tune: float = 0.0,
    ) -> None:
        """Append PCM and write the slot header (TDD §2.3, §3.2).

        ALLOCATION RULE (VERIFIED across 279 factory + user samples)
            next_start = align_up(previous_end + 2, 4)
            currentOffset = highest_end + 2
        The new sample is written at the current write cursor, so committing
        never relocates an existing sample and never invalidates an offset that
        something else already points at.

        Enforces the capacity invariant before mutating anything: on refusal
        the bank is exactly as it was.
        """
        if self._save_type == SAVE_PSG:
            raise InvariantError("a PSG bank has no sample area to commit into")
        if not (0 <= slot_index < L.NUM_SAMPLES):
            raise InvariantError(f"slot {slot_index} out of range 0..{L.NUM_SAMPLES-1}")
        slot = self._samples[slot_index]
        if slot.stereo != stereo:
            pool = "stereo" if slot.stereo else "mono"
            raise InvariantError(
                f"slot {slot_index} is a {pool} slot; "
                f"a {'stereo' if stereo else 'mono'} sample cannot go there "
                "(the pools are separate header tables)"
            )
        if not slot.empty:
            raise InvariantError(
                f"slot {slot_index} is occupied by {slot.name!r}; "
                "clear it first (clearing never moves other samples)"
            )
        if not (L.MIN_IMPORT_RATE_HZ <= sample_rate <= L.MAX_IMPORT_RATE_HZ):
            raise InvariantError(
                f"sample rate {sample_rate} outside the hardware's accepted "
                f"{L.MIN_IMPORT_RATE_HZ}-{L.MAX_IMPORT_RATE_HZ} Hz"
            )
        if len(pcm) % 2:
            raise InvariantError(
                f"PCM is {len(pcm)} bytes; 16-bit frames are always an even count"
            )
        if len(pcm) > self.pcm_free_bytes():
            raise InvariantError(
                f"sample of {len(pcm):,} B exceeds free space "
                f"{self.pcm_free_bytes():,} B (cap {self.MAX_PCM_BYTES:,} B)"
            )

        start = self._next_start()
        end = start + len(pcm)
        if end > self.MAX_PCM_BYTES:
            raise InvariantError(
                f"sample would end at {end:,} B, past the {self.MAX_PCM_BYTES:,} B cap"
            )

        # Grow the PCM region to reach `start` (the allocation rule leaves 2-4
        # byte alignment gaps between samples; they are padding, not data).
        if len(self._pcm) < start:
            self._pcm.extend(b"\x00" * (start - len(self._pcm)))
        self._pcm[start:end] = pcm
        if len(self._pcm) < end:
            self._pcm.extend(b"\x00" * (end - len(self._pcm)))

        slot.set_name(name)
        slot.set_range(start, end)
        slot.set_sample_rate(sample_rate)
        # Sample Tune carries the rate compensation the machine owes plus any
        # musical offset. Defaulting musical_tune to 0 reproduces exactly what
        # the hardware writes on import: 134 of the 140 occupied slots in
        # Chronic-Interactive.esx decode to a musical tune of 0.00.
        slot.set_musical_tune(musical_tune)

        self._sample_area.set_current_offset(self._next_offset())
        self._recount()
        self._sync_trailer()

    def clear_sample(self, slot_index: int) -> None:
        """Empty a slot. The PCM it referenced is NOT reclaimed.

        Reclaiming would mean moving every later sample and rewriting its
        offsets — a whole-bank rewrite triggered by a delete, which is exactly
        the kind of operation that corrupts banks. Use compact_pcm() to reclaim
        deliberately, as its own explicit step.
        """
        if not (0 <= slot_index < L.NUM_SAMPLES):
            raise InvariantError(f"slot {slot_index} out of range 0..{L.NUM_SAMPLES-1}")
        self._samples[slot_index].clear()
        self._sample_area.set_current_offset(self._next_offset())
        self._recount()
        self._sync_trailer()

    def compact_pcm(self) -> int:
        """Rewrite the PCM region with no gaps; return the bytes reclaimed.

        Every occupied slot is relocated in slot order following the same
        allocation rule, and its header offsets are rewritten to match. Safe
        because the offsets are the only references into the PCM region — the
        pattern data addresses samples by slot number, not by byte offset.
        """
        if self._save_type == SAVE_PSG:
            raise InvariantError("a PSG bank has no PCM to compact")
        before = len(self._pcm)
        occupied = [s for s in self._samples if not s.empty]
        chunks = [
            (s, bytes(self._pcm[s.offset_start : s.offset_end])) for s in occupied
        ]
        rebuilt = bytearray()
        for slot, data in chunks:
            start = _align_up(len(rebuilt) + 2, 4) if rebuilt else 0
            rebuilt.extend(b"\x00" * (start - len(rebuilt)))
            rebuilt.extend(data)
            slot.set_range(start, start + len(data))
        self._pcm = rebuilt
        self._sample_area.set_current_offset(self._next_offset())
        self._recount()
        self._sync_trailer()
        return before - len(self._pcm)

    # -- internals ----------------------------------------------------------
    def _highest_end(self) -> int:
        """The furthest byte any occupied slot reaches into the PCM region.

        A stereo slot occupies TWO ranges, and `offset_end` is only channel 1's.
        Taking that as the high-water mark places the next sample on top of an
        existing sample's second channel — which is exactly what happened on
        Chronic-Interactive.esx (40 stereo slots) before this accounted for it.
        """
        highest = 0
        for slot in self._samples:
            if slot.empty:
                continue
            highest = max(highest, slot.offset_end)
            ch2 = slot.channel2_range
            if ch2 is not None:
                highest = max(highest, ch2[1])
        return highest

    def _next_start(self) -> int:
        """align_up(highest_end + 2, 4), or 0 for the first sample."""
        highest = self._highest_end()
        return _align_up(highest + L.PCM_GAP, L.PCM_ALIGN) if highest else 0

    def _next_offset(self) -> int:
        """currentOffset = align_up(highest_end + 2, 4); 0 when no sample exists.

        Refined 2026-08-23: the documented rule was `highest_end + 2`, which
        holds on e5.esx only because its highest end happens to be 4-aligned.
        Chronic-Interactive.esx needs the align_up (6,112,872 -> 6,112,876).
        """
        return self._next_start()

    def _sync_trailer(self) -> None:
        """Keep the 16-byte PCM trailer consistent with currentOffset.

        VERIFIED 2026-08-23: on all four corpus banks the PCM region is exactly
        currentOffset + 16 bytes, and bytes 4..7 of that trailer are a
        big-endian copy of currentOffset itself:

            80 00 7f ff | <currentOffset u32> | 01 7f ff fe | 00 ff ff ff
                          ^^^^^^^^^^^^^^^^^^

        Chronic 0x005D466C = 6,112,876; e5 0x00BAFA34 = 12,253,748; e4
        0x001FC388 = 2,081,672 — each equal to that bank's currentOffset.
        Committing a sample without updating this would leave the file
        internally contradictory, so the trailer is carried and patched rather
        than regenerated: the surrounding bytes stay exactly as the machine
        wrote them.
        """
        cursor = self._sample_area.current_offset
        if cursor < self._highest_end():
            raise InvariantError(
                f"refusing to place the PCM trailer at {cursor}, which is inside "
                f"sample data ending at {self._highest_end()}"
            )
        trailer = bytearray(self._trailer)
        struct.pack_into(">I", trailer, L.PCM_TRAILER_OFF_CURRENT, cursor)
        self._trailer = bytes(trailer)
        del self._pcm[cursor:]
        if len(self._pcm) < cursor:
            self._pcm.extend(b"\x00" * (cursor - len(self._pcm)))
        self._pcm.extend(trailer)

    def _recount(self) -> None:
        mono = sum(1 for s in self._samples[: L.NUM_SAMPLES_MONO] if not s.empty)
        stereo = sum(1 for s in self._samples[L.NUM_SAMPLES_MONO :] if not s.empty)
        self._sample_area.set_counts(mono, stereo)


def _align_up(value: int, boundary: int) -> int:
    """Smallest multiple of `boundary` at or above `value`."""
    return -(-value // boundary) * boundary
