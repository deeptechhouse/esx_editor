#!/usr/bin/env python3
"""
sysex_analyse.py — decode a captured ESX-1 SysEx dump.

THE PROBLEM SYSEX CREATES
    MIDI data bytes must have the high bit clear (0x00-0x7F); 0x80+ is reserved
    for status bytes. So 8-bit payload cannot be sent raw. Korg -- like most
    manufacturers -- packs it 7 payload bytes at a time:

        [MSB byte] [d0&0x7F] [d1&0x7F] ... [d6&0x7F]

    where MSB byte bit n holds the high bit of payload byte n. Eight
    transmitted bytes therefore carry seven real bytes.

HOW WE KNOW IF WE GOT IT RIGHT
    We already parse .esx files byte-exactly, so we know precisely what a
    pattern bank should contain: 64 patterns x 4280 bytes = 273,920 bytes.
    If unpacking yields exactly that, the encoding is confirmed -- no guessing.

    Better still, the decoded patterns can be compared field-by-field against
    a bank we already parse, which validates the dump layout for free.

USAGE
    python3 sysex_analyse.py dumps/capture_01.syx
    python3 sysex_analyse.py dumps/capture_01.syx --compare ../corpus/a3jan26.esx
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "spike_a"))
try:
    import layout as L
except ImportError:
    L = None

KORG_ID = 0x42
ESX_FAMILY = 0x71


def split_sysex(data: bytes) -> list[bytes]:
    """Split a raw capture into individual F0..F7 messages."""
    msgs, i = [], 0
    while True:
        s = data.find(0xF0, i)
        if s < 0:
            break
        e = data.find(0xF7, s)
        if e < 0:
            msgs.append(data[s:])          # truncated tail
            break
        msgs.append(data[s:e + 1])
        i = e + 1
    return msgs


def unpack_7bit(payload: bytes) -> bytes:
    """Korg/Roland-style 8-in-7 expansion. See module docstring."""
    out = bytearray()
    for g in range(0, len(payload), 8):
        group = payload[g:g + 8]
        if len(group) < 2:
            break
        msbs = group[0]
        for n, b in enumerate(group[1:]):
            out.append(b | (0x80 if (msbs >> n) & 1 else 0))
    return bytes(out)


def analyse(path: Path, compare: Path | None) -> int:
    data = path.read_bytes()
    msgs = split_sysex(data)
    print(f"file    : {path}  ({len(data):,} bytes)")
    print(f"messages: {len(msgs)}")
    if not msgs:
        print("  no SysEx framing (F0..F7) found")
        return 1

    for i, m in enumerate(msgs[:8]):
        head = " ".join(f"{b:02X}" for b in m[:8])
        print(f"\n  [{i}] {len(m):,} bytes   header: {head} ...")
        if len(m) > 4 and m[1] == KORG_ID:
            print(f"       Korg 0x42 | channel {(m[2] & 0x0F) + 1} | "
                  f"family 0x{m[3]:02X}"
                  + (" = ESX-1" if m[3] == ESX_FAMILY else " (UNEXPECTED)")
                  + f" | function 0x{m[4]:02X}")
        else:
            print(f"       manufacturer 0x{m[1]:02X} — not Korg")

    if len(msgs) > 8:
        print(f"\n  ... and {len(msgs)-8} more message(s)")

    # ---- try to unpack the largest message -------------------------------
    big = max(msgs, key=len)
    print(f"\n=== unpacking largest message ({len(big):,} bytes) ===")
    for hdr in (5, 6, 7):
        body = big[hdr:-1] if big[-1] == 0xF7 else big[hdr:]
        dec = unpack_7bit(body)
        note = ""
        if L is not None:
            for label, expect in (
                ("one pattern", L.CHUNK_PATTERN),
                ("64 patterns", 64 * L.CHUNK_PATTERN),
                ("256 patterns", L.NUM_PATTERNS * L.CHUNK_PATTERN),
                ("global", L.CHUNK_GLOBAL_PARAMETERS),
                ("one song", L.CHUNK_SONG),
            ):
                if dec and abs(len(dec) - expect) <= 8:
                    note = f"   <-- matches {label} ({expect:,})"
        print(f"  header {hdr} bytes -> payload {len(body):,} -> decoded "
              f"{len(dec):,} bytes{note}")

    # ---- optional comparison against a known bank -------------------------
    if compare and L is not None:
        ref = compare.read_bytes()
        pat0 = ref[L.ADDR_PATTERN_DATA:L.ADDR_PATTERN_DATA + L.CHUNK_PATTERN]
        print(f"\n=== searching decoded data for pattern 0 of {compare.name} ===")
        for hdr in (5, 6, 7):
            body = big[hdr:-1] if big[-1] == 0xF7 else big[hdr:]
            dec = unpack_7bit(body)
            # Match on the 8-byte pattern name + a chunk of header, which is
            # distinctive enough to locate without matching the whole 4280 B.
            probe = pat0[:24]
            idx = dec.find(probe)
            print(f"  header {hdr}: pattern-0 signature "
                  + (f"FOUND at offset {idx}" if idx >= 0 else "not found"))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("capture")
    ap.add_argument("--compare", default=None,
                    help="a .esx bank to look for known pattern data in")
    a = ap.parse_args()
    return analyse(Path(a.capture), Path(a.compare) if a.compare else None)


if __name__ == "__main__":
    sys.exit(main())
