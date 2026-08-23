"""
A coherent synthetic .esx bank, built in memory.

WHY THIS EXISTS
    `*.esx` is gitignored — the corpus banks are large binaries and carry
    Korg factory-derived audio. So on CI, and on any fresh clone, every
    corpus-dependent test skips, and the round-trip gate would skip with them.
    That is the one test that must never silently stop running.

    This module builds a bank that is structurally valid AND coherent (the
    validator returns no errors), so the gate, the golden hashes, and the
    integration tests all have something real to run against everywhere.

WHAT IT PROVES AND WHAT IT DOES NOT
    It proves the reader and writer are exact inverses, that the validator
    accepts a well-formed bank, and that the whole open -> edit -> write ->
    re-read cycle holds. It does NOT prove the offsets are right — only a bank
    a real ESX-1 wrote can do that, which is why the corpus tests still run
    whenever the banks are present.
"""

from __future__ import annotations

import hashlib
import struct

import codec.layout as L

#: Deterministic filler seed. Changing it changes every golden hash.
SEED = b"esx-bank-studio-synthetic-v1"

#: Sample rate written into every synthetic slot (inside the legal range).
RATE_HZ = 44100

#: The 16-byte pattern header a real machine writes for an untouched pattern,
#: observed identically on the blank template, on e5.esx, and on 204 of the 256
#: patterns in Chronic-Interactive.esx. Bytes 0..1 are tempo at 1/128 BPM:
#: 0x3C00 / 128 = 120.0, the machine's default.
DEFAULT_PATTERN_HEADER = bytes.fromhex(
    "3c00000000 0f003c 00007fff7fff7fff".replace(" ", "")
)

#: Motion targets used by pattern 0. Both exist in the 313-target table, so the
#: validator's unknown_motion_target check passes.
MOTION_TARGET_FX1_EDIT1 = 485
MOTION_TARGET_DRUM1_LEVEL = 6


def _filler(size: int) -> bytearray:
    """Deterministic non-zero filler, so undecoded regions are not all zeros.

    Zeros would let a writer bug that drops a region pass unnoticed; a
    distinctive pattern makes a dropped region show up as a diff.
    """
    digest = hashlib.sha256(SEED).digest()
    return bytearray(digest[i % len(digest)] ^ (i & 0xFF) for i in range(size))


def build(
    *,
    num_mono: int = 3,
    num_stereo: int = 0,
    pcm_bytes: int = 4096,
    motion_slots: int = 2,
    named_patterns: int = 4,
) -> bytes:
    """Return a complete, coherent Save-All image.

    `num_mono` slots are filled with contiguous, 4-byte-aligned PCM ranges
    following the VERIFIED allocation rule, so the validator's offset and
    currentOffset checks all pass.
    """
    if pcm_bytes < 16:
        raise ValueError("pcm_bytes must leave room for the 16-byte trailer")
    size = L.ADDR_SAMPLE_DATA + pcm_bytes
    buf = _filler(size)

    # -- magic ---------------------------------------------------------------
    buf[0:4] = L.MAGIC_HEAD
    buf[4:8] = b"\x00\x00\x00\x00"
    buf[8] = 0x71
    buf[9:12] = L.MAGIC_1_TAIL
    buf[12] = 0x00
    m2 = L.ADDR_MAGIC_2
    buf[m2 : m2 + 4] = L.MAGIC_HEAD
    buf[m2 + 4 : m2 + 8] = b"\x00\x00\x00\x00"
    buf[m2 + 8] = 0x71
    buf[m2 + 9 : m2 + 12] = L.MAGIC_2_TAIL
    buf[m2 + 12] = 0x20  # trailing space, not a null

    # -- patterns ------------------------------------------------------------
    for p in range(L.NUM_PATTERNS):
        base = L.ADDR_PATTERN_DATA + p * L.CHUNK_PATTERN
        # Only the first few patterns are named. A real bank is mostly blank —
        # 204 of 256 in the busiest corpus bank — and naming all 256 made every
        # pattern chunk unique, which broke "what does this bank's blank
        # pattern look like" for anything relying on the fixture.
        name = f"PAT{p:05d}"[:8] if p < named_patterns else " " * 8
        buf[base : base + L.PATTERN_NAME_LEN] = name.encode("ascii")
        # Use the machine's own default header rather than filler: a fixture
        # that does not look like a real bank is a weaker fixture.
        header_at = base + L.PATTERN_NAME_LEN
        buf[header_at : header_at + len(DEFAULT_PATTERN_HEADER)] = (
            DEFAULT_PATTERN_HEADER
        )
        # Zero the part and FX area. Filler there decodes as a part triggering
        # on ~half its steps and pointing at a random sample slot, which is not
        # what a blank pattern looks like and made every fixture-based
        # assertion start from noise.
        buf[base + L.PAT_OFF_PARTS_DRUM : base + L.PAT_OFF_PARAMETERS_MOTION] = bytes(
            L.PAT_OFF_PARAMETERS_MOTION - L.PAT_OFF_PARTS_DRUM
        )
        # Every motion slot starts unused: target 0xFFFF, all values Disabl.
        for s in range(L.NUM_PARAMETERS_MOTION):
            off = base + L.PAT_OFF_PARAMETERS_MOTION + s * L.CHUNK_PARAMETERS_MOTION
            struct.pack_into(">H", buf, off, L.MOTION_TARGET_EMPTY)
            buf[off + 2 : off + 2 + L.NUM_MOTION_STEPS] = bytes(
                [L.MOTION_VALUE_DISABLED] * L.NUM_MOTION_STEPS
            )

    # Pattern 0 gets real motion so the gate exercises a populated slot.
    base0 = L.ADDR_PATTERN_DATA + L.PAT_OFF_PARAMETERS_MOTION
    targets = (MOTION_TARGET_FX1_EDIT1, MOTION_TARGET_DRUM1_LEVEL)
    for s in range(min(motion_slots, len(targets))):
        off = base0 + s * L.CHUNK_PARAMETERS_MOTION
        struct.pack_into(">H", buf, off, targets[s])
        # A ramp over the first 64 steps; Disabl beyond the pattern length.
        values = [(i * 2) % 128 for i in range(64)] + [L.MOTION_VALUE_DISABLED] * 64
        buf[off + 2 : off + 2 + L.NUM_MOTION_STEPS] = bytes(values)

    # -- sample headers ------------------------------------------------------
    # Every slot empty first: the sentinel lives in the channel-1 start field.
    for i in range(L.NUM_SAMPLES_MONO):
        off = L.ADDR_SAMPLE_HEADER_MONO + i * L.CHUNK_SAMPLE_HEADER_MONO
        buf[off : off + L.CHUNK_SAMPLE_HEADER_MONO] = bytes(L.CHUNK_SAMPLE_HEADER_MONO)
        struct.pack_into(">I", buf, off + 8, L.EMPTY_OFFSET)
    for i in range(L.NUM_SAMPLES_STEREO):
        off = L.ADDR_SAMPLE_HEADER_STEREO + i * L.CHUNK_SAMPLE_HEADER_STEREO
        buf[off : off + L.CHUNK_SAMPLE_HEADER_STEREO] = bytes(
            L.CHUNK_SAMPLE_HEADER_STEREO
        )
        struct.pack_into(">I", buf, off + 8, L.EMPTY_OFFSET)

    # Fill num_mono slots using the VERIFIED allocation rule:
    #   next_start = align_up(previous_end + 2, 4)
    cursor = 0
    highest_end = 0
    per_sample = max(4, (pcm_bytes - 16) // max(num_mono, 1) - 8) & ~1
    for i in range(num_mono):
        off = L.ADDR_SAMPLE_HEADER_MONO + i * L.CHUNK_SAMPLE_HEADER_MONO
        start = cursor
        end = start + per_sample
        buf[off : off + 8] = f"SYN{i:05d}"[:8].encode("ascii")
        struct.pack_into(">I", buf, off + 8, start)  # channel 1 start
        struct.pack_into(">I", buf, off + 12, end)  # channel 1 end
        struct.pack_into(">I", buf, off + 16, start)  # start
        struct.pack_into(">I", buf, off + 20, end)  # end
        struct.pack_into(">I", buf, off + 24, start)  # loop start
        struct.pack_into(">I", buf, off + 28, RATE_HZ)
        highest_end = max(highest_end, end)
        cursor = (end + 2 + 3) & ~3

    if num_stereo:
        raise NotImplementedError(
            "no stereo bank has ever been round-tripped (hardware checklist "
            "item 2); a synthetic stereo fixture would assert an unproven layout"
        )

    # -- counts + currentOffset ---------------------------------------------
    struct.pack_into(">I", buf, L.ADDR_NUM_MONO_SAMPLES, num_mono)
    struct.pack_into(">I", buf, L.ADDR_NUM_STEREO_SAMPLES, num_stereo)
    struct.pack_into(
        ">I", buf, L.ADDR_CURRENT_OFFSET, highest_end + 2 if num_mono else 0
    )

    return bytes(buf)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
