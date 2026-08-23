"""
codec.reader — bytes -> core.Bank.

CONTRACT
    read(b) parses a valid .esx image into a core.Bank. Every region the model
    understands is decoded; every region it does not is stored verbatim on the
    Bank's RawRegions so the writer can replay it (TDD §4.1). Parsing NEVER
    validates coherence (that is codec.validator, TDD §4.4).

DECOMPOSITION (guarantees byte-identity with codec.writer)
    pre    = [0x0 .. ADDR_PATTERN_DATA)   magic + globals + unknown_1
    patterns x256
    mid    = [pat_end .. ADDR_MAGIC_2)   unknown_2 + songs + song_events +
             unknown_3  (verbatim)
    magic2 = [ADDR_MAGIC_2 .. ADDR_NUM_MONO_SAMPLES)   (verbatim)
    counts = [ADDR_NUM_MONO_SAMPLES .. +12)   DECODED into Bank.sample_area:
             num_mono, num_stereo, currentOffset. Decoded rather than kept
             verbatim because committing a sample must update them.
    hdr_gap= [counts_end .. ADDR_SAMPLE_HEADER_MONO)   (verbatim)
    mono   sample headers x256
    stereo sample headers x128
    tail   = [stereo_end .. ADDR_SAMPLE_DATA)   unknown_4 + slices + unknown_5
    pcm    = [ADDR_SAMPLE_DATA .. EOF)

TWO SAVE TYPES (TDD §2.5)
    Save All -> full image (>= SIZE_FILE_MIN). Save PSG -> shorter, no sample
    area. read_auto detects which. A PSG image is retained verbatim until the
    PSG layout is decoded in a later workflow.
"""

from __future__ import annotations

import codec.layout as L
from codec.errors import FormatError
from core.bank import SAVE_ALL, SAVE_PSG, Bank, RawRegions, SampleArea
from core.global_params import GlobalParameters
from core.pattern import Pattern
from core.sample import SampleSlot


class BankReader:
    """Parses .esx bytes into a core.Bank, preserving undecoded regions."""

    __slots__ = ()

    def read(self, data: bytes) -> Bank:
        """Parse a full .esx image (All-save) into a Bank.

        Raises codec.FormatError if the magic numbers, region sizes, or file
        length are structurally invalid.
        """
        if len(data) < L.SIZE_FILE_MIN:
            raise FormatError(
                f"file is 0x{len(data):X} bytes, below All-save minimum "
                f"0x{L.SIZE_FILE_MIN:X} (a PSG save? use read_auto)"
            )
        if not data.startswith(L.MAGIC_HEAD):
            raise FormatError(f"missing KORG magic at 0x0 (found {data[:4]!r})")
        if L.MAGIC_1_TAIL not in data[:0x20]:
            raise FormatError("missing 'ESX' tag in first 32 bytes")
        m2 = data[L.ADDR_MAGIC_2 : L.ADDR_MAGIC_2 + 16]
        if not m2.startswith(L.MAGIC_HEAD) or L.MAGIC_2_TAIL not in m2:
            raise FormatError("missing KORG..BPS sample-area header at 0x1B0000")

        pat_end = L.ADDR_PATTERN_DATA + L.NUM_PATTERNS * L.CHUNK_PATTERN
        mono_end = (
            L.ADDR_SAMPLE_HEADER_MONO + L.NUM_SAMPLES_MONO * L.CHUNK_SAMPLE_HEADER_MONO
        )
        stereo_end = (
            L.ADDR_SAMPLE_HEADER_STEREO
            + L.NUM_SAMPLES_STEREO * L.CHUNK_SAMPLE_HEADER_STEREO
        )

        globals_ = GlobalParameters(data[L.ADDR_GLOBAL_PARAMETERS : L.ADDR_UNKNOWN_1])

        patterns = []
        for i in range(L.NUM_PATTERNS):
            off = L.ADDR_PATTERN_DATA + i * L.CHUNK_PATTERN
            patterns.append(Pattern.from_bytes(data[off : off + L.CHUNK_PATTERN]))

        samples = []
        for i in range(L.NUM_SAMPLES_MONO):
            off = L.ADDR_SAMPLE_HEADER_MONO + i * L.CHUNK_SAMPLE_HEADER_MONO
            samples.append(
                SampleSlot(data[off : off + L.CHUNK_SAMPLE_HEADER_MONO], False, i)
            )
        for i in range(L.NUM_SAMPLES_STEREO):
            off = L.ADDR_SAMPLE_HEADER_STEREO + i * L.CHUNK_SAMPLE_HEADER_STEREO
            samples.append(
                SampleSlot(
                    data[off : off + L.CHUNK_SAMPLE_HEADER_STEREO],
                    True,
                    L.NUM_SAMPLES_MONO + i,
                )
            )

        counts_at = L.ADDR_NUM_MONO_SAMPLES
        counts_end = counts_at + 12
        raw = RawRegions(
            {
                "magic": data[L.ADDR_MAGIC_1 : L.ADDR_GLOBAL_PARAMETERS],
                "unknown_1": data[L.ADDR_UNKNOWN_1 : L.ADDR_PATTERN_DATA],
                "mid": data[pat_end : L.ADDR_MAGIC_2],
                "magic2": data[L.ADDR_MAGIC_2 : counts_at],
                "hdr_gap": data[counts_end : L.ADDR_SAMPLE_HEADER_MONO],
                "gap_hdr": data[mono_end : L.ADDR_SAMPLE_HEADER_STEREO],
                "tail": data[stereo_end : L.ADDR_SAMPLE_DATA],
            }
        )
        sample_area = SampleArea.from_bytes(data[counts_at:counts_end])
        pcm = data[L.ADDR_SAMPLE_DATA :]
        return Bank(globals_, patterns, [], samples, pcm, raw, SAVE_ALL, sample_area)

    def read_psg(self, data: bytes) -> Bank:
        """Parse a Save-PSG image (no sample area) into a Bank.

        The whole image is retained verbatim under the 'psg_image' raw region;
        the writer emits it unchanged. Full PSG decoding is a later workflow.
        """
        if not data.startswith(L.MAGIC_HEAD):
            raise FormatError(f"missing KORG magic at 0x0 (found {data[:4]!r})")
        raw = RawRegions({"psg_image": data})
        globals_ = (
            GlobalParameters(data[L.ADDR_GLOBAL_PARAMETERS : L.ADDR_UNKNOWN_1])
            if len(data) >= L.ADDR_UNKNOWN_1
            else GlobalParameters(b"\x00" * 192)
        )
        return Bank(globals_, [], [], [], b"", raw, SAVE_PSG)

    def read_auto(self, data: bytes) -> Bank:
        """Detect All vs PSG by structure and dispatch to the right parser."""
        return self.read_psg(data) if self.is_psg(data) else self.read(data)

    def read_file(self, path: str) -> Bank:
        """Convenience: read bytes from a path, then read_auto()."""
        with open(path, "rb") as f:
            return self.read_auto(f.read())

    def is_psg(self, data: bytes) -> bool:
        """True if the bytes look like a Save-PSG (no sample area) file.

        A PSG save omits the sample area, so the file is shorter than the
        All-save minimum. (Refined once a real PSG file is captured; see
        research/HARDWARE_CHECKLIST.md item 4.)
        """
        return len(data) < L.SIZE_FILE_MIN
