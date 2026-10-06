"""
core.sample — a sample slot header (mono 40 B / stereo 44 B).

FORMAT (TDD §2.3, VERIFIED)
    Offsets are BYTE offsets relative to ADDR_SAMPLE_DATA, not frame counts.
    Empty slot sentinel: offset fields == 0xFFFFFFFF.

INVARIANTS (TDD §3.2)
    Sample names are exactly 8 bytes (the setter pads/truncates).

WF2 NOTE
    The header round-trips byte-exact (raw retained). Only the fields the
    validator and budget need are decoded here. The STEREO sample-rate field
    offset is unconfirmed (see research/CODEC_FINDINGS_LOG.md); `sample_rate`
    is only trustworthy for mono slots for now.
"""

from __future__ import annotations

import math
import struct

import codec.layout as L
from core.errors import InvariantError

EMPTY_OFFSET = 0xFFFFFFFF
NAME_LEN = 8
MONO_SIZE = 40
STEREO_SIZE = 44


class SampleSlot:
    """One sample header. `stereo` selects the 44-byte layout and slot pool."""

    __slots__ = ("_raw", "_stereo", "_index")

    # O(1) time, O(1) space
    def __init__(self, raw: bytes, stereo: bool, index: int):
        expected = STEREO_SIZE if stereo else MONO_SIZE
        if len(raw) != expected:
            raise InvariantError(
                f"{'stereo' if stereo else 'mono'} sample header must be "
                f"{expected} bytes, got {len(raw)}"
            )
        self._raw = bytearray(raw)
        self._stereo = stereo
        self._index = index

    @property
    # O(1) time, O(1) space
    def index(self) -> int:
        return self._index

    @property
    # O(1) time, O(1) space
    def stereo(self) -> bool:
        return self._stereo

    @property
    # O(1) time, O(1) space
    def empty(self) -> bool:
        """True if the slot's channel-1 offset holds the empty sentinel."""
        return struct.unpack_from(">I", self._raw, 8)[0] == EMPTY_OFFSET

    @property
    # O(1) time, O(1) space
    def name_bytes(self) -> bytes:
        return bytes(self._raw[:NAME_LEN])

    @property
    # O(1) time, O(1) space
    def name(self) -> str:
        return self.name_bytes.decode("ascii", "replace").rstrip("\x00 ")

    # O(v) time, O(v) space — v = characters in the supplied name (encoded before truncation)
    def set_name(self, value: str) -> None:
        """Set the slot name; pads/truncates to exactly 8 bytes (invariant)."""
        raw = value.encode("ascii", "replace")[:NAME_LEN].ljust(NAME_LEN, b" ")
        if len(raw) != NAME_LEN:
            raise InvariantError("sample name must encode to exactly 8 bytes")
        self._raw[:NAME_LEN] = raw

    @property
    # O(1) time, O(1) space
    def offset_start(self) -> int:
        """Start byte offset of channel 1 PCM, relative to ADDR_SAMPLE_DATA."""
        return struct.unpack_from(">I", self._raw, 8)[0]

    @property
    # O(1) time, O(1) space
    def offset_end(self) -> int:
        return struct.unpack_from(">I", self._raw, 12)[0]

    # O(1) time, O(1) space
    def set_range(self, start: int, end: int) -> None:
        """Set the PCM byte range this slot points at.

        Writes BOTH offset pairs the header carries: channel-1 start/end and
        the separate start/end fields. They agree on every real bank observed;
        writing only one would produce a header no machine ever wrote.
        """
        if start < 0 or end < start:
            raise InvariantError(f"invalid PCM range {start}..{end}")
        if end > L.MAX_SAMPLE_BYTES:
            raise InvariantError(
                f"end {end} exceeds sample memory {L.MAX_SAMPLE_BYTES}"
            )
        if self._stereo:
            raise InvariantError(
                "use set_stereo_ranges() for a stereo slot: it carries two "
                "channel-offset pairs, and writing only one would produce a "
                "header no machine ever wrote"
            )
        struct.pack_into(">I", self._raw, L.SMP_OFF_CH1_START, start)
        struct.pack_into(">I", self._raw, L.SMP_OFF_CH1_END, end)
        struct.pack_into(">I", self._raw, L.MONO_OFF_START, start)
        struct.pack_into(">I", self._raw, L.MONO_OFF_END, end)
        struct.pack_into(">I", self._raw, L.MONO_OFF_LOOP_START, start)

    # O(k) time, O(1) space — k = 2 channel ranges
    def set_stereo_ranges(
        self, ch1: tuple[int, int], ch2: tuple[int, int], *, frames: int
    ) -> None:
        """Set both channel ranges on a stereo slot (VERIFIED layout).

        `frames` is the play length written to the start/end fields, which on
        every observed stereo slot count FRAMES, not bytes, and start at 0.
        """
        if not self._stereo:
            raise InvariantError("set_stereo_ranges() is for stereo slots only")
        # O(k) time, O(1) space — k = 2 channel ranges
        for start, end in (ch1, ch2):
            if start < 0 or end < start:
                raise InvariantError(f"invalid PCM range {start}..{end}")
            if end > L.MAX_SAMPLE_BYTES:
                raise InvariantError(f"end {end} exceeds sample memory")
        if (ch1[1] - ch1[0]) != (ch2[1] - ch2[0]):
            raise InvariantError(
                "the two channels must be the same length "
                f"({ch1[1] - ch1[0]} vs {ch2[1] - ch2[0]})"
            )
        struct.pack_into(">I", self._raw, L.SMP_OFF_CH1_START, ch1[0])
        struct.pack_into(">I", self._raw, L.SMP_OFF_CH1_END, ch1[1])
        struct.pack_into(">I", self._raw, L.STEREO_OFF_CH2_START, ch2[0])
        struct.pack_into(">I", self._raw, L.STEREO_OFF_CH2_END, ch2[1])
        struct.pack_into(">I", self._raw, L.STEREO_OFF_START, 0)
        struct.pack_into(">I", self._raw, L.STEREO_OFF_END, frames)

    # O(1) time, O(1) space
    def set_sample_rate(self, rate: int) -> None:
        """Set the ORIGINAL sample rate (mono header, offset 28)."""
        if not (L.MIN_IMPORT_RATE_HZ <= rate <= L.MAX_IMPORT_RATE_HZ):
            raise InvariantError(
                f"rate {rate} outside {L.MIN_IMPORT_RATE_HZ}-{L.MAX_IMPORT_RATE_HZ} Hz"
            )
        struct.pack_into(">I", self._raw, self._rate_offset, rate)

    # O(1) time, O(1) space
    def clear(self) -> None:
        """Restore the empty-slot form: the machine's own sentinel, name blanked."""
        self._raw[:NAME_LEN] = b" " * NAME_LEN
        struct.pack_into(">I", self._raw, L.SMP_OFF_CH1_START, EMPTY_OFFSET)
        struct.pack_into(">I", self._raw, L.SMP_OFF_CH1_END, EMPTY_OFFSET)
        struct.pack_into(">I", self._raw, 16, EMPTY_OFFSET)
        struct.pack_into(">I", self._raw, 20, EMPTY_OFFSET)

    @property
    # O(1) time, O(1) space
    def _rate_offset(self) -> int:
        return L.STEREO_OFF_SAMPLE_RATE if self._stereo else L.MONO_OFF_SAMPLE_RATE

    @property
    # O(1) time, O(1) space
    def _tune_offset(self) -> int:
        return L.STEREO_OFF_SAMPLE_TUNE if self._stereo else L.MONO_OFF_SAMPLE_TUNE

    @property
    # O(1) time, O(1) space
    def sample_rate(self) -> int:
        """The sample's ORIGINAL rate, before any conversion.

        Both pools are VERIFIED: mono at 28, stereo at 32. The stereo offset
        was established 2026-08-23 against the 40 populated stereo slots in
        Chronic-Interactive.esx, correcting the TDD's blank-slot inference.
        """
        return struct.unpack_from(">I", self._raw, self._rate_offset)[0]

    @property
    # O(1) time, O(1) space
    def audio_range(self) -> tuple[int, int]:
        """(start, end) of the AUDIO, skipping the 16-byte block header.

        offset_start/offset_end bracket the whole block. Slicing the PCM with
        those and calling it audio includes the header, which decodes as a
        colossal sample value at the very start of every sound.
        """
        return (self.offset_start + L.PCM_BLOCK_HEADER_LEN, self.offset_end)

    @property
    # O(1) time, O(1) space
    def audio_bytes(self) -> int:
        """Length of the audio alone."""
        return max(0, self.offset_end - self.offset_start - L.PCM_BLOCK_HEADER_LEN)

    @property
    # O(1) time, O(1) space
    def frames(self) -> int:
        """Number of 16-bit frames in this slot's audio."""
        return self.audio_bytes // 2

    @property
    # O(1) time, O(1) space
    def channel2_range(self) -> tuple[int, int] | None:
        """(start, end) of the second channel's PCM, or None for a mono slot."""
        if not self._stereo:
            return None
        return (
            struct.unpack_from(">I", self._raw, L.STEREO_OFF_CH2_START)[0],
            struct.unpack_from(">I", self._raw, L.STEREO_OFF_CH2_END)[0],
        )

    @property
    # O(1) time, O(1) space
    def stored_tune(self) -> float:
        """Sample Tune in semitones, as stored (TDD 2.3, VERIFIED packing).

            bit 15   : sign
            bits 8-14: whole semitones
            bits 0-7 : hundredths

        This value carries TWO concerns at once: the pitch compensation the
        machine applies because the sample is not at 44.1 kHz, PLUS whatever
        musical transposition the user dialled in. Use musical_tune() to
        separate them.
        """
        packed = struct.unpack_from(">H", self._raw, self._tune_offset)[0]
        semitones = (packed >> L.TUNE_SEMITONE_SHIFT) & L.TUNE_SEMITONE_MASK
        hundredths = packed & L.TUNE_HUNDREDTHS_MASK
        magnitude = semitones + hundredths / 100.0
        return -magnitude if packed & L.TUNE_SIGN_BIT else magnitude

    # O(1) time, O(1) space
    def rate_compensation(self) -> float:
        """The tune the machine owes purely to the sample's rate.

        12 * log2(rate / 44100). Confirmed against factory data: the minimum
        tune observed at each stored rate equals this to the hundredth
        (24,000 Hz -> all six samples exactly -10.53).
        """
        rate = self.sample_rate
        if rate <= 0:
            raise InvariantError(f"slot {self._index} has a non-positive rate {rate}")
        return 12.0 * math.log2(rate / L.SAMPLE_RATE_HZ)

    # O(1) time, O(1) space
    def musical_tune(self) -> float:
        """Transposition with rate compensation removed.

        Zero means "plays at its natural pitch", whatever rate it was stored
        at. This is the number a user actually means by "transpose"; the raw
        field is not, which is why it is not surfaced directly.
        """
        return self.stored_tune - self.rate_compensation()

    # O(1) time, O(1) space
    def set_musical_tune(self, semitones: float) -> None:
        """Set the musical transposition, re-adding the rate compensation."""
        total = semitones + self.rate_compensation()
        magnitude = abs(total)
        whole = int(magnitude)
        hundredths = int(round((magnitude - whole) * 100))
        if hundredths >= 100:
            whole += 1
            hundredths -= 100
        if whole > L.TUNE_SEMITONE_MASK:
            raise InvariantError(
                f"tune {total:+.2f} semitones exceeds the field's "
                f"+/-{L.TUNE_SEMITONE_MASK} semitone range"
            )
        packed = (whole << L.TUNE_SEMITONE_SHIFT) | hundredths
        if total < 0:
            packed |= L.TUNE_SIGN_BIT
        struct.pack_into(">H", self._raw, self._tune_offset, packed)

    # O(1) time, O(1) space
    def to_bytes(self) -> bytes:
        return bytes(self._raw)

    @classmethod
    # O(1) time, O(1) space
    def from_bytes(cls, raw: bytes, stereo: bool, index: int) -> SampleSlot:
        return cls(raw, stereo, index)
