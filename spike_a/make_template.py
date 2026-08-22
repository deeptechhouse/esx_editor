#!/usr/bin/env python3
"""
make_template.py — derive the blank bank the app ships with.

WHY THE APP NEEDS THIS
    Five regions of the .esx format were never decoded. Synthesising a bank
    from zeros risks a file the hardware rejects or silently misreads, so
    "New bank" must mean "load a blank template the hardware itself wrote,
    then edit it" (TDD section 04.3).

    That template is the ONLY .esx the shipped application needs. The corpus
    banks are test fixtures for the round-trip gate -- development and CI
    assets, never bundled with the app.

WHY IT IS DERIVED, NOT COPIED
    Two reasons, and the second is the important one:

    1. Size. A blank template is 2,424,848 bytes (SIZE_FILE_MIN); a factory
       bank is 20 MB, almost all of it sample audio the template doesn't need.

    2. COPYRIGHT. `ESX-Factory-Data.esx` is Korg's factory content -- 200
       samples they own. It is fine as a local test fixture, but bundling it
       into an application would redistribute Korg's audio. Deriving the
       template from a user-authored bank with every sample stripped avoids
       that entirely.

HOW IT WORKS
    Every byte outside the sample area is preserved verbatim -- including all
    five unknown regions, which is the whole point. Sample slots are set to
    the machine's OWN empty representation, copied from a genuinely empty slot
    in the source bank rather than synthesised, so the template contains only
    byte patterns the ESX-1 itself produced.

USAGE
    python3 make_template.py SOURCE.esx [-o default.esx]

ADJUSTABLE PARAMETERS
    BLANK_PATTERN_NAMES  also blank the 8-byte pattern name fields
"""

import sys
import struct
import argparse
from pathlib import Path

import layout as L

# --- Adjustable: blank pattern names as well as samples --------------------
BLANK_PATTERN_NAMES = True


def find_empty_header(data: bytes, table_addr: int, count: int, size: int) -> bytes | None:
    """Return the raw bytes of the first genuinely empty slot in a header table.

    We copy the machine's own empty-slot representation rather than inventing
    one, so the template only ever contains byte patterns the ESX-1 wrote.
    """
    for i in range(count):
        off = table_addr + i * size
        start = struct.unpack_from(">I", data, off + 8)[0]
        if start == L.EMPTY_OFFSET:
            return data[off:off + size]
    return None


def make_template(data: bytes) -> tuple[bytes, dict]:
    """Strip every sample from a bank, preserving everything else byte-for-byte."""
    buf = bytearray(data)
    stats = {}

    # --- find the machine's own empty-slot bytes for each table ------------
    empty_mono = find_empty_header(
        data, L.ADDR_SAMPLE_HEADER_MONO, L.NUM_SAMPLES_MONO, L.CHUNK_SAMPLE_HEADER_MONO)
    empty_stereo = find_empty_header(
        data, L.ADDR_SAMPLE_HEADER_STEREO, L.NUM_SAMPLES_STEREO, L.CHUNK_SAMPLE_HEADER_STEREO)
    if empty_mono is None or empty_stereo is None:
        raise SystemExit(
            "source bank has no empty slot to copy an empty-header pattern from; "
            "use a bank with at least one free mono and one free stereo slot")

    # --- overwrite every sample slot with that empty pattern ---------------
    cleared = 0
    for i in range(L.NUM_SAMPLES_MONO):
        off = L.ADDR_SAMPLE_HEADER_MONO + i * L.CHUNK_SAMPLE_HEADER_MONO
        if buf[off:off + L.CHUNK_SAMPLE_HEADER_MONO] != empty_mono:
            cleared += 1
        buf[off:off + L.CHUNK_SAMPLE_HEADER_MONO] = empty_mono
    for i in range(L.NUM_SAMPLES_STEREO):
        off = L.ADDR_SAMPLE_HEADER_STEREO + i * L.CHUNK_SAMPLE_HEADER_STEREO
        if buf[off:off + L.CHUNK_SAMPLE_HEADER_STEREO] != empty_stereo:
            cleared += 1
        buf[off:off + L.CHUNK_SAMPLE_HEADER_STEREO] = empty_stereo
    stats["slots_cleared"] = cleared

    # --- reset the sample-area bookkeeping ---------------------------------
    struct.pack_into(">I", buf, L.ADDR_NUM_MONO_SAMPLES, 0)
    struct.pack_into(">I", buf, L.ADDR_NUM_STEREO_SAMPLES, 0)
    struct.pack_into(">I", buf, L.ADDR_CURRENT_OFFSET, 0)

    # --- optionally blank pattern names ------------------------------------
    if BLANK_PATTERN_NAMES:
        blanked = 0
        for p in range(L.NUM_PATTERNS):
            off = L.ADDR_PATTERN_DATA + p * L.CHUNK_PATTERN
            if buf[off:off + L.PATTERN_NAME_LEN] != b" " * L.PATTERN_NAME_LEN:
                blanked += 1
            buf[off:off + L.PATTERN_NAME_LEN] = b" " * L.PATTERN_NAME_LEN
        stats["pattern_names_blanked"] = blanked

    # --- truncate the PCM region to the bare 16-byte trailer ---------------
    # Everything before ADDR_SAMPLE_DATA -- including all five unknown
    # regions and the slice table -- is carried through untouched.
    out = bytes(buf[:L.SIZE_FILE_MIN])
    stats["size_before"] = len(data)
    stats["size_after"] = len(out)
    return out, stats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", help="a real .esx bank to derive the template from")
    ap.add_argument("-o", "--output", default="default.esx")
    args = ap.parse_args()

    data = Path(args.source).read_bytes()
    out, stats = make_template(data)
    Path(args.output).write_bytes(out)

    print(f"source : {args.source}  ({stats['size_before']:,} B)")
    print(f"output : {args.output}  ({stats['size_after']:,} B)")
    print(f"  sample slots cleared    : {stats['slots_cleared']}")
    if "pattern_names_blanked" in stats:
        print(f"  pattern names blanked   : {stats['pattern_names_blanked']}")
    saved = stats["size_before"] - stats["size_after"]
    print(f"  size reduction          : {saved:,} B "
          f"({100*saved/stats['size_before']:.1f}%)")
    print("\n  All five unknown regions and the slice table preserved verbatim.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
