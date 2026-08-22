"""
layout.py — the single source of truth for the Korg ESX-1 .esx binary layout.

WHERE THESE NUMBERS COME FROM
    Reverse-engineered by Jeff / SKRATCHDOT.COM in `open-electribe-editor`
    (EPL-1.0), file EsxUtil.java, recovered from git tag v1.2.0. Cross-checked
    against the Korg ESX-1 Owner's Manual where the manual documents a limit.
    PROVEN by the Spike A round-trip gate on three real banks.

WHY A SEPARATE MODULE
    Every offset in the project is defined exactly once, here. If a value turns
    out to be wrong, it gets fixed in one place. Nothing else hardcodes offsets.

A NOTE ON "UNKNOWN" REGIONS
    Four regions of the file were never decoded. We do not need to understand
    them -- we only need to never damage them. The reader stores them verbatim
    and the writer plays them back unchanged. See UNKNOWN_REGIONS below.

PORTING NOTE (WF1)
    Ported verbatim from spike_a/layout.py. Do not edit the constants here
    without re-running the Spike A round-trip gate on the corpus.
"""

# ---------------------------------------------------------------------------
# File-level magic numbers
# ---------------------------------------------------------------------------
# Two "KORG" signatures appear in the file. The first identifies the whole bank,
# the second marks the start of the sample (BPS) area.
ADDR_MAGIC_1 = 0x00000000          # b"KORG" .... 0x71 "ESX"
ADDR_MAGIC_2 = 0x001B0000          # b"KORG" .... 0x71 "BPS"
MAGIC_1_TAIL = b"ESX"
MAGIC_2_TAIL = b"BPS"
MAGIC_HEAD = b"KORG"

# ---------------------------------------------------------------------------
# Top-level region offsets (absolute byte positions in the file)
# ---------------------------------------------------------------------------
ADDR_GLOBAL_PARAMETERS = 0x00000020
ADDR_UNKNOWN_1         = 0x000000E0
ADDR_PATTERN_DATA      = 0x00000200
ADDR_UNKNOWN_2         = 0x0010BA00
ADDR_SONG_DATA         = 0x00130000
ADDR_SONG_EVENT_DATA   = 0x00138400
ADDR_UNKNOWN_3         = 0x0015F500
ADDR_NUM_MONO_SAMPLES  = 0x001B0020   # 4 bytes
ADDR_NUM_STEREO_SAMPLES= 0x001B0024   # 4 bytes
ADDR_CURRENT_OFFSET    = 0x001B0028   # 4 bytes (also reported as free space)
ADDR_SAMPLE_HEADER_MONO   = 0x001B0100
ADDR_SAMPLE_HEADER_STEREO = 0x001B2900
ADDR_UNKNOWN_4         = 0x001B3F00
ADDR_SLICE_DATA        = 0x001B4200
ADDR_SAMPLE_DATA       = 0x00250000   # raw PCM begins here and runs to EOF

# ---------------------------------------------------------------------------
# Chunk sizes (bytes per record)
# ---------------------------------------------------------------------------
CHUNK_GLOBAL_PARAMETERS   = 192
CHUNK_PATTERN             = 4280
CHUNK_SONG                = 528
CHUNK_SONG_EVENT          = 8
CHUNK_SAMPLE_HEADER_MONO  = 40
CHUNK_SAMPLE_HEADER_STEREO= 44
CHUNK_PARAMETERS_FX       = 4
CHUNK_PARAMETERS_MOTION   = 130
CHUNK_SLICE_DATA          = 2048

# ---------------------------------------------------------------------------
# Record counts
# ---------------------------------------------------------------------------
NUM_PATTERNS       = 256
NUM_SONGS          = 64
NUM_SAMPLES_MONO   = 256
NUM_SAMPLES_STEREO = 128
NUM_SAMPLES        = NUM_SAMPLES_MONO + NUM_SAMPLES_STEREO   # 384
NUM_PARAMETERS_FX  = 3
NUM_PARAMETERS_MOTION = 24        # motion slots per pattern (manual: 24)
NUM_MOTION_STEPS   = 128          # one value per step; max steps = 16 x 8 bars
NUM_SLICE_DATA     = 256
MAX_SONG_EVENTS    = 20000

# ---------------------------------------------------------------------------
# Offsets *within* one 4280-byte pattern chunk
# ---------------------------------------------------------------------------
PAT_OFF_PARTS_DRUM         = 24     # 9 parts x 34 bytes
PAT_OFF_PARTS_KEYBOARD     = 330    # 2 parts x 274 bytes
PAT_OFF_PARTS_STRETCHSLICE = 878    # 3 parts x 32 bytes
PAT_OFF_PARTS_AUDIOIN      = 974    # 1 part  x 156 bytes
PAT_OFF_PARTS_ACCENT       = 1130   # 1 part  x 18 bytes
PAT_OFF_PARAMETERS_FX      = 1148   # 3 x 4 bytes
PAT_OFF_PARAMETERS_MOTION  = 1160   # 24 x 130 bytes -> ends exactly at 4280

CHUNK_PARTS_DRUM         = 34
CHUNK_PARTS_KEYBOARD     = 274
CHUNK_PARTS_STRETCHSLICE = 32
CHUNK_PARTS_AUDIOIN      = 156
CHUNK_PARTS_ACCENT       = 18

NUM_PARTS_DRUM         = 9
NUM_PARTS_KEYBOARD     = 2
NUM_PARTS_STRETCHSLICE = 3
NUM_PARTS_AUDIOIN      = 1
NUM_PARTS_ACCENT       = 1

# ---------------------------------------------------------------------------
# Sample memory limits (from EsxUtil + confirmed by the manual Specifications)
# ---------------------------------------------------------------------------
SAMPLE_RATE_HZ        = 44100
# The machine ACCEPTS any rate in this range on import and compensates pitch via
# Sample Tune (manual p.88). It does not require 44.1 kHz. Korg's own factory
# bank ships samples at 31,250 / 32,000 / 44,100 Hz.
MIN_IMPORT_RATE_HZ    = 11025
MAX_IMPORT_RATE_HZ    = 96000
BYTES_PER_FRAME       = 2                    # 16-bit mono
MAX_SAMPLE_FRAMES     = 0xC00000             # 12,582,912
MAX_SAMPLE_BYTES      = MAX_SAMPLE_FRAMES * BYTES_PER_FRAME
MAX_SAMPLE_SECONDS    = MAX_SAMPLE_FRAMES / SAMPLE_RATE_HZ   # ~285.3 s

SIZE_FILE_MIN = 0x00250010
SIZE_FILE_MAX = SIZE_FILE_MIN + MAX_SAMPLE_BYTES

# Empty-slot sentinel written into a sample header's offset fields.
EMPTY_OFFSET = 0xFFFFFFFF

# --- Motion sentinels, observed in a real bank (a3jan26.esx, Spike A) --------
# An UNUSED motion slot has target 0xFFFF and all 128 value bytes set to 0x80.
MOTION_TARGET_EMPTY = 0xFFFF
# 0x80 = 128 is the per-step `Disabl` sentinel: "do not update at this step".
# PROVEN in ESX-Factory-Data.esx -- e.g. pattern 3 slot 0 (Drum4 Filter Cutoff)
# holds 128 for steps 0-5, a real sweep for steps 6-63, then 128 from step 64
# onward because that pattern is only 64 steps long.
MOTION_VALUE_DISABLED = 0x80


def discrete_step(n_options):
    """Byte spacing for a discrete motion parameter with `n_options` choices.

    Discrete parameters are stored as KNOB POSITIONS, not option indices: the
    0-127 knob range is split into N zones and the zone base value is stored.
    Verified against real banks:
        N=2 (Roll, Reverse, FX Send, Amp EG) -> {0, 64}
        N=3 (Effect Select)                  -> {0, 43, 86}
        N=4 (Filter Type)                    -> {0, 32, 64, 96}
    """
    return -(-128 // n_options)          # ceil(128 / n_options)


def encode_discrete(index, n_options):
    """Option index -> stored byte."""
    return index * discrete_step(n_options)


def decode_discrete(value, n_options):
    """Stored byte -> option index."""
    return value // discrete_step(n_options)

# Pattern chunks also begin with an 8-byte name field, space-padded (0x20),
# same width as the sample name field. Confirmed in a real bank.
PATTERN_NAME_LEN = 8

# Sample name field: bytes 0..7 of every sample header. Fixed width, raw bytes,
# no terminator. Confirmed by the manual (p.34, "up to eight characters").
SAMPLE_NAME_LEN = 8

# ---------------------------------------------------------------------------
# Unknown regions -- preserved verbatim, never interpreted.
# Each entry is (name, start, end) where end is exclusive.
# The end of each is the start of the next known region.
# ---------------------------------------------------------------------------
# Discovered during Spike A, 2026-08-09: slice data ends at 0x234200
# (0x1B4200 + 256*2048) but PCM does not begin until 0x250000, leaving a
# ~114 KB gap that the reference project never names. Preserve it like the rest.
ADDR_UNKNOWN_5 = ADDR_SLICE_DATA + NUM_SLICE_DATA * CHUNK_SLICE_DATA  # 0x234200

UNKNOWN_REGIONS = [
    ("unknown_1", ADDR_UNKNOWN_1, ADDR_PATTERN_DATA),
    ("unknown_2", ADDR_UNKNOWN_2, ADDR_SONG_DATA),
    ("unknown_3", ADDR_UNKNOWN_3, ADDR_MAGIC_2),
    ("unknown_4", ADDR_UNKNOWN_4, ADDR_SLICE_DATA),
    ("unknown_5", ADDR_UNKNOWN_5, ADDR_SAMPLE_DATA),
]


def region_map():
    """Return the full ordered region map as (name, start, end, note) tuples.

    `end` is exclusive. The final sample-data region has end=None because it
    runs to whatever the file's actual length is.
    """
    pat_end = ADDR_PATTERN_DATA + NUM_PATTERNS * CHUNK_PATTERN
    song_end = ADDR_SONG_DATA + NUM_SONGS * CHUNK_SONG
    mono_end = ADDR_SAMPLE_HEADER_MONO + NUM_SAMPLES_MONO * CHUNK_SAMPLE_HEADER_MONO
    stereo_end = ADDR_SAMPLE_HEADER_STEREO + NUM_SAMPLES_STEREO * CHUNK_SAMPLE_HEADER_STEREO
    slice_end = ADDR_SLICE_DATA + NUM_SLICE_DATA * CHUNK_SLICE_DATA
    return [
        ("magic_1",        ADDR_MAGIC_1,             ADDR_GLOBAL_PARAMETERS, "KORG..ESX"),
        ("global_params",  ADDR_GLOBAL_PARAMETERS,   ADDR_UNKNOWN_1,         "192 B"),
        ("unknown_1",      ADDR_UNKNOWN_1,           ADDR_PATTERN_DATA,      "preserve"),
        ("patterns",       ADDR_PATTERN_DATA,        pat_end,                f"{NUM_PATTERNS}x{CHUNK_PATTERN}"),
        ("unknown_2",      ADDR_UNKNOWN_2,           ADDR_SONG_DATA,         "preserve"),
        ("songs",          ADDR_SONG_DATA,           song_end,               f"{NUM_SONGS}x{CHUNK_SONG}"),
        ("song_events",    ADDR_SONG_EVENT_DATA,     ADDR_UNKNOWN_3,         "8 B each"),
        ("unknown_3",      ADDR_UNKNOWN_3,           ADDR_MAGIC_2,           "preserve"),
        ("magic_2",        ADDR_MAGIC_2,             ADDR_SAMPLE_HEADER_MONO, "KORG..BPS + counts"),
        ("sample_hdr_mono",   ADDR_SAMPLE_HEADER_MONO,   mono_end,   f"{NUM_SAMPLES_MONO}x{CHUNK_SAMPLE_HEADER_MONO}"),
        ("sample_hdr_stereo", ADDR_SAMPLE_HEADER_STEREO, stereo_end, f"{NUM_SAMPLES_STEREO}x{CHUNK_SAMPLE_HEADER_STEREO}"),
        ("unknown_4",      ADDR_UNKNOWN_4,           ADDR_SLICE_DATA,        "preserve"),
        ("slices",         ADDR_SLICE_DATA,          slice_end,              f"{NUM_SLICE_DATA}x{CHUNK_SLICE_DATA}"),
        ("unknown_5",      ADDR_UNKNOWN_5,           ADDR_SAMPLE_DATA,       "preserve (undocumented)"),
        ("sample_data",    ADDR_SAMPLE_DATA,         None,                   "raw PCM to EOF"),
    ]
