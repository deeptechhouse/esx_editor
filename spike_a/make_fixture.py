#!/usr/bin/env python3
"""
make_fixture.py — generate synthetic .esx files for testing the probe harness.

WHY SYNTHETIC FIXTURES
    They prove the parser and serializer are exact inverses of each other, and
    they let `diff` be tested with a known single-byte change. They do NOT prove
    the offsets are correct -- only a real bank from the hardware can do that.

USAGE
    python3 make_fixture.py            # writes synthetic.esx and synthetic_b.esx

ADJUSTABLE PARAMETERS
    SEED       changes the deterministic fill pattern
    CHANGED_STEP  which motion step differs between the two files
"""
import struct, hashlib, sys
import layout as L

SEED = b"esx-spike-a"
CHANGED_STEP = 37

def build():
    size = L.ADDR_SAMPLE_DATA + 0x10
    buf = bytearray(size)
    h = hashlib.sha256(SEED).digest()
    for i in range(size):
        buf[i] = h[i % 32] ^ (i & 0xFF)
    buf[0:4] = b"KORG"; buf[8] = 0x71; buf[9:12] = b"ESX"
    m2 = L.ADDR_MAGIC_2
    buf[m2:m2+4] = b"KORG"; buf[m2+8] = 0x71; buf[m2+9:m2+12] = b"BPS"

    m0 = L.ADDR_PATTERN_DATA + L.PAT_OFF_PARAMETERS_MOTION
    struct.pack_into(">H", buf, m0, 485)                    # FX1 Edit1
    buf[m0+2:m0+130] = bytes((i*2) % 128 for i in range(128))
    m1 = m0 + L.CHUNK_PARAMETERS_MOTION
    struct.pack_into(">H", buf, m1, 4)                      # Drum1 Pitch
    buf[m1+2:m1+130] = bytes(64 for _ in range(128))

    s0 = L.ADDR_SAMPLE_HEADER_MONO
    buf[s0:s0+8] = b"a08KDRUM"
    struct.pack_into(">I", buf, s0+8, 0)
    struct.pack_into(">I", buf, s0+12, 1000)
    struct.pack_into(">I", buf, s0+28, 44100)
    s1 = s0 + L.CHUNK_SAMPLE_HEADER_MONO
    struct.pack_into(">I", buf, s1+8, L.EMPTY_OFFSET)
    struct.pack_into(">I", buf, s1+12, L.EMPTY_OFFSET)
    return buf, m0

if __name__ == "__main__":
    buf, m0 = build()
    open("synthetic.esx","wb").write(bytes(buf))
    b2 = bytearray(buf); b2[m0+2+CHANGED_STEP] = 0x7F
    open("synthetic_b.esx","wb").write(bytes(b2))
    print(f"wrote synthetic.esx and synthetic_b.esx ({len(buf):,} B each);"
          f" they differ at motion step {CHANGED_STEP}")
