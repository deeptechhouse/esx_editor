#!/usr/bin/env python3
"""
esx_probe.py — Spike A harness for the Korg ESX-1 .esx bank format.

WHAT THIS IS FOR
    Spike A has one acceptance gate: parse a real .esx file into a structured
    model, serialize that model back to bytes, and get a BYTE-IDENTICAL result.
    Until that passes, no offset in the design can be trusted.

    It also reports what is actually inside a bank, which is how we answer the
    remaining unknowns (the `Disabl` motion sentinel, bipolar encoding, and the
    displayable character set).

USAGE
    python3 esx_probe.py inspect  BANK.esx          # structure + contents report
    python3 esx_probe.py verify   BANK.esx [...]    # the round-trip gate
    python3 esx_probe.py motion   BANK.esx          # dump motion slots in use
    python3 esx_probe.py names    BANK.esx [...]    # collect name-field bytes
    python3 esx_probe.py diff     A.esx B.esx       # byte diff, grouped by region

    `diff` is the workhorse for hardware verification: save a bank, change ONE
    thing on the machine, save again, and diff the two files.

ADJUSTABLE PARAMETERS
    All offsets and sizes live in layout.py -- change them there, not here.
    DIFF_MAX_RUNS below caps how many differing byte-runs `diff` prints.
"""

import sys
import struct
import collections
import layout as L

# --- Adjustable: how many differing runs `diff` prints before truncating -----
DIFF_MAX_RUNS = 40
# --- Adjustable: how many bytes of context to show around each differing run -
DIFF_CONTEXT = 0


# ===========================================================================
# Model
# ===========================================================================
class MotionSlot:
    """One motion sequence: which parameter it drives, plus one value per step.

    Binary form is 130 bytes: a big-endian uint16 target id, then 128 bytes.
    """

    __slots__ = ("target", "values")

    # O(1) time, O(1) space
    def __init__(self, target, values):
        self.target = target  # int, indexes the 313-entry operation table
        self.values = values  # bytes, length 128

    @classmethod
    # O(k) time, O(k) space — k = 128 motion steps copied
    def from_bytes(cls, b):
        assert len(b) == L.CHUNK_PARAMETERS_MOTION, len(b)
        (target,) = struct.unpack_from(">H", b, 0)
        return cls(target, b[2:])

    # O(k) time, O(k) space — k = 130 bytes per motion slot
    def to_bytes(self):
        return struct.pack(">H", self.target) + self.values

    @property
    # O(1) time, O(1) space
    def in_use(self):
        # An unused slot is marked by target 0xFFFF (observed in a real bank).
        return self.target != L.MOTION_TARGET_EMPTY

    @property
    # O(k) time, O(1) space — k = 128 motion steps
    def all_disabled(self):
        """True if every step is the `Disabl` sentinel (0x80)."""
        # O(k) time, O(1) space — k = 128 motion steps
        return all(v == L.MOTION_VALUE_DISABLED for v in self.values)

    # O(k) time, O(1) space — k = 128 motion steps (at most 256 distinct byte values)
    def value_histogram(self):
        return collections.Counter(self.values)


class Pattern:
    """One 4280-byte pattern. Everything except the motion block is kept raw
    for now -- Spike A only needs motion decoded; the rest round-trips as bytes.
    """

    __slots__ = ("raw_head", "motion")

    # O(1) time, O(1) space
    def __init__(self, raw_head, motion):
        self.raw_head = raw_head  # bytes 0..1159 (header, parts, fx)
        self.motion = motion  # list[MotionSlot], length 24

    @classmethod
    # O(k) time, O(k) space — k = 4280 bytes per pattern
    def from_bytes(cls, b):
        assert len(b) == L.CHUNK_PATTERN, len(b)
        head = b[: L.PAT_OFF_PARAMETERS_MOTION]
        slots = []
        # O(k) time, O(k) space — k = 24 slots x 130 bytes
        for i in range(L.NUM_PARAMETERS_MOTION):
            off = L.PAT_OFF_PARAMETERS_MOTION + i * L.CHUNK_PARAMETERS_MOTION
            slots.append(
                MotionSlot.from_bytes(b[off : off + L.CHUNK_PARAMETERS_MOTION])
            )
        return cls(head, slots)

    # O(k) time, O(k) space — k = 4280 bytes per pattern
    def to_bytes(self):
        out = bytearray(self.raw_head)
        # O(k) time, O(k) space — k = 24 slots x 130 bytes (bytearray += is amortised constant per byte)
        for slot in self.motion:
            out += slot.to_bytes()
        assert len(out) == L.CHUNK_PATTERN, len(out)
        return bytes(out)


class SampleHeader:
    """A mono (40 B) or stereo (44 B) sample slot header.

    Only the fields Spike A needs are decoded; the rest round-trips as raw bytes
    so we can prove byte-identity without having decoded everything yet.
    """

    __slots__ = ("raw", "stereo", "index")

    # O(1) time, O(1) space
    def __init__(self, raw, stereo, index):
        self.raw = raw
        self.stereo = stereo
        self.index = index

    @property
    # O(1) time, O(1) space
    def name_bytes(self):
        return self.raw[: L.SAMPLE_NAME_LEN]

    @property
    # O(1) time, O(1) space
    def name(self):
        return self.name_bytes.decode("ascii", "replace").rstrip("\x00 ")

    @property
    # O(1) time, O(1) space
    def offset_start(self):
        return struct.unpack_from(">I", self.raw, 8)[0]

    @property
    # O(1) time, O(1) space
    def offset_end(self):
        return struct.unpack_from(">I", self.raw, 12)[0]

    @property
    # O(1) time, O(1) space
    def empty(self):
        return (
            self.offset_start == L.EMPTY_OFFSET
            or self.offset_start == 0
            and self.offset_end == 0
        )

    @property
    # O(1) time, O(1) space
    def sample_rate(self):
        # bytes 28..31 on the mono header: the sample's ORIGINAL rate.
        return struct.unpack_from(">I", self.raw, 28)[0]

    # O(1) time, O(1) space
    def to_bytes(self):
        return self.raw


class EsxBank:
    """A whole .esx bank, parsed into regions.

    The design rule that makes round-tripping safe: anything we have not decoded
    is stored as raw bytes and written back untouched. That includes the four
    documented "unknown" regions AND any region we simply have not got to yet.
    """

    # O(n) time, O(n) space — n = bytes in the bank (every region sliced once)
    def __init__(self, data):
        self.size = len(data)
        self._raw = data  # kept for diffing/reference
        self.pre = data[: L.ADDR_PATTERN_DATA]  # magic + globals + unknown_1

        self.patterns = []
        # O(k) time, O(k) space — k = 256 patterns x 4280 bytes
        for i in range(L.NUM_PATTERNS):
            off = L.ADDR_PATTERN_DATA + i * L.CHUNK_PATTERN
            self.patterns.append(Pattern.from_bytes(data[off : off + L.CHUNK_PATTERN]))

        pat_end = L.ADDR_PATTERN_DATA + L.NUM_PATTERNS * L.CHUNK_PATTERN
        # Everything from end-of-patterns to the mono sample headers stays raw:
        # unknown_2, songs, song events, unknown_3, magic_2 + counts.
        self.mid = data[pat_end : L.ADDR_SAMPLE_HEADER_MONO]

        self.samples = []
        # O(k) time, O(k) space — k = 256 mono headers x 40 bytes
        for i in range(L.NUM_SAMPLES_MONO):
            off = L.ADDR_SAMPLE_HEADER_MONO + i * L.CHUNK_SAMPLE_HEADER_MONO
            self.samples.append(
                SampleHeader(data[off : off + L.CHUNK_SAMPLE_HEADER_MONO], False, i)
            )
        # O(k) time, O(k) space — k = 128 stereo headers x 44 bytes
        for i in range(L.NUM_SAMPLES_STEREO):
            off = L.ADDR_SAMPLE_HEADER_STEREO + i * L.CHUNK_SAMPLE_HEADER_STEREO
            self.samples.append(
                SampleHeader(
                    data[off : off + L.CHUNK_SAMPLE_HEADER_STEREO],
                    True,
                    L.NUM_SAMPLES_MONO + i,
                )
            )

        mono_end = (
            L.ADDR_SAMPLE_HEADER_MONO + L.NUM_SAMPLES_MONO * L.CHUNK_SAMPLE_HEADER_MONO
        )
        stereo_end = (
            L.ADDR_SAMPLE_HEADER_STEREO
            + L.NUM_SAMPLES_STEREO * L.CHUNK_SAMPLE_HEADER_STEREO
        )
        # Gap between the two header tables (mono_end .. stereo start) and
        # everything from stereo_end to the PCM data: kept raw.
        self.gap_hdr = data[mono_end : L.ADDR_SAMPLE_HEADER_STEREO]
        self.tail_hdr = data[stereo_end : L.ADDR_SAMPLE_DATA]
        self.pcm = data[L.ADDR_SAMPLE_DATA :]

    # -- serialization ------------------------------------------------------
    # O(n) time, O(n) space — n = bytes in the bank (bytearray += is amortised constant per byte)
    def to_bytes(self):
        out = bytearray()
        out += self.pre
        # O(k) time, O(k) space — k = 256 patterns x 4280 bytes
        for p in self.patterns:
            out += p.to_bytes()
        out += self.mid
        # O(k) time, O(k) space — k = 256 mono headers x 40 bytes
        for s in self.samples[: L.NUM_SAMPLES_MONO]:
            out += s.to_bytes()
        out += self.gap_hdr
        # O(k) time, O(k) space — k = 128 stereo headers x 44 bytes
        for s in self.samples[L.NUM_SAMPLES_MONO :]:
            out += s.to_bytes()
        out += self.tail_hdr
        out += self.pcm
        return bytes(out)

    # -- validation ---------------------------------------------------------
    # O(1) time, O(1) space
    def structural_errors(self):
        """Return a list of human-readable problems; empty list means OK."""
        errs = []
        d = self._raw
        if not d.startswith(L.MAGIC_HEAD):
            errs.append(f"missing KORG magic at 0x0 (found {d[:4]!r})")
        if L.MAGIC_1_TAIL not in d[:0x20]:
            errs.append("missing 'ESX' tag in first 32 bytes")
        if len(d) > L.ADDR_MAGIC_2 + 16:
            m2 = d[L.ADDR_MAGIC_2 : L.ADDR_MAGIC_2 + 16]
            if not m2.startswith(L.MAGIC_HEAD):
                errs.append(
                    f"missing KORG magic at 0x{L.ADDR_MAGIC_2:X} (found {m2[:4]!r})"
                )
            if L.MAGIC_2_TAIL not in m2:
                errs.append("missing 'BPS' tag in sample-area header")
        if len(d) < L.SIZE_FILE_MIN:
            errs.append(
                f"file shorter than minimum 0x{L.SIZE_FILE_MIN:X} (is 0x{len(d):X})"
            )
        if len(d) > L.SIZE_FILE_MAX:
            errs.append(
                f"file longer than maximum 0x{L.SIZE_FILE_MAX:X} (is 0x{len(d):X})"
            )
        return errs


# ===========================================================================
# Commands
# ===========================================================================
# O(n) time, O(n) space — n = bytes in the file
def _load(path):
    with open(path, "rb") as f:
        return f.read()


# O(N) time, O(n) space — N = total bytes across all banks; n = bytes in the largest bank
def cmd_inspect(paths):
    # O(N) time, O(n) space — N = total bytes across all banks; n = bytes in the largest bank
    for path in paths:
        data = _load(path)
        print(f"\n=== {path} ===")
        print(f"size: {len(data):,} bytes (0x{len(data):X})")
        bank = EsxBank(data)
        errs = bank.structural_errors()
        print("structure:", "OK" if not errs else "PROBLEMS")
        # O(1) time, O(1) space
        for e in errs:
            print("  !", e)

        print("\nregion map:")
        # O(k) time, O(1) space — k = 15 regions in the map
        for name, start, end, note in L.region_map():
            end_s = f"0x{end:08X}" if end is not None else f"0x{len(data):08X}*"
            size = (end if end is not None else len(data)) - start
            print(f"  {name:18} 0x{start:08X}..{end_s}  {size:>10,} B   {note}")

        # O(k) time, O(k) space — k = 384 sample slots
        used = [s for s in bank.samples if not s.empty]
        # O(k) time, O(k) space — k = 384 sample slots
        mono_used = [s for s in used if not s.stereo]
        print(
            f"\nsamples: {len(used)}/{L.NUM_SAMPLES} used "
            f"({len(mono_used)} mono, {len(used) - len(mono_used)} stereo)"
        )
        # O(k) time, O(1) space — k = 12 samples printed at most
        for s in used[:12]:
            print(
                f"  [{s.index:3}] {'S' if s.stereo else 'M'} "
                f"{s.name!r:12} rate={s.sample_rate}"
            )
        if len(used) > 12:
            print(f"  ... and {len(used) - 12} more")

        # O(k) time, O(k) space — k = 256 patterns x 24 motion slots
        pats_motion = [
            (i, sum(1 for m in p.motion if m.in_use))
            for i, p in enumerate(bank.patterns)
        ]
        # O(k) time, O(1) space — k = 256 patterns
        total_motion = sum(n for _, n in pats_motion)
        # O(k) time, O(k) space — k = 256 patterns
        nonzero = [(i, n) for i, n in pats_motion if n]
        print(
            f"\nmotion slots in use: {total_motion} across "
            f"{len(nonzero)} patterns (max {L.NUM_PARAMETERS_MOTION}/pattern)"
        )
        # O(k) time, O(1) space — k = 10 patterns printed at most
        for i, n in nonzero[:10]:
            print(f"  pattern {i:3}: {n} slot(s)")


# O(N) time, O(n) space — N = total bytes across all banks; n = bytes in the largest bank
def cmd_verify(paths):
    """THE SPIKE A GATE: parse -> serialize -> must be byte-identical."""
    ok = True
    # O(N) time, O(n) space — N = total bytes across all banks; n = bytes in the largest bank
    for path in paths:
        data = _load(path)
        bank = EsxBank(data)
        errs = bank.structural_errors()
        out = bank.to_bytes()
        same = out == data
        status = "PASS" if same and not errs else "FAIL"
        if not same or errs:
            ok = False
        print(f"[{status}] {path}  ({len(data):,} B)")
        # O(1) time, O(1) space
        for e in errs:
            print(f"         structural: {e}")
        if not same:
            if len(out) != len(data):
                print(f"         length differs: got {len(out):,}, want {len(data):,}")
            # bigo-lint: disable=BIGO006 — amortised: each bank's bytes are compared once, so summed over the outer loop this is N
            # O(n) time, O(1) space — n = bytes in the bank
            n = sum(1 for a, b in zip(out, data) if a != b)
            print(f"         {n:,} differing bytes")
            # O(k) time, O(1) space — k = 5 diffs shown, each mapped against r = 15 regions
            for off, a, b in _first_diffs(data, out, 5):
                print(
                    f"           @0x{off:08X} orig={a:02X} rebuilt={b:02X} "
                    f"({_which_region(off)})"
                )
    print("\nROUND-TRIP GATE:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


# O(N) time, O(n) space — N = total bytes across all banks; n = bytes in the largest bank
def cmd_motion(paths):
    """Dump motion slots. Used to hunt the `Disabl` sentinel: look for a value
    that appears in otherwise-varying slots and never behaves like real data."""
    # O(N) time, O(n) space — N = total bytes across all banks; n = bytes in the largest bank
    for path in paths:
        data = _load(path)
        bank = EsxBank(data)
        print(f"\n=== motion in {path} ===")
        allvals = collections.Counter()
        shown = 0
        # O(k) time, O(1) space — k = 256 patterns x 24 slots x 128 steps (sorting at most 20 slots of 128 values)
        for pi, p in enumerate(bank.patterns):
            # O(k) time, O(1) space — k = 24 slots x 128 steps
            for si, slot in enumerate(p.motion):
                if not slot.in_use:
                    continue
                allvals.update(slot.values)
                if shown < 20:
                    uniq = sorted(set(slot.values))
                    print(
                        f"  pat {pi:3} slot {si:2}  target={slot.target:4}  "
                        f"distinct={len(uniq):3}  "
                        f"min={min(slot.values):3} max={max(slot.values):3}"
                    )
                    shown += 1
        if allvals:
            print("\n  value frequency across all in-use slots (top 12):")
            # O(k) time, O(1) space — k = 12 most common values
            for v, c in allvals.most_common(12):
                print(f"    {v:3} (0x{v:02X}): {c:,}")
            print(
                "\n  HINT: a value that dominates and never appears mid-curve "
                "is the likely `Disabl` sentinel."
            )
        else:
            print("  (no motion data in this bank)")


# O(N) time, O(n) space — N = total bytes across all banks; n = bytes in the largest bank
def cmd_names(paths):
    """Collect every distinct byte used in sample-name fields.

    This is how we derive the displayable character set empirically.
    """
    seen = collections.Counter()
    # O(N) time, O(n) space — N = total bytes across all banks; n = bytes in the largest bank
    for path in paths:
        bank = EsxBank(_load(path))
        # O(k) time, O(1) space — k = 384 sample slots x 8 name bytes
        for s in bank.samples:
            if s.empty:
                continue
            seen.update(s.name_bytes)
    print("distinct bytes used in sample-name fields:")
    printable = []
    # O(k log k) time, O(k) space — k = at most 256 distinct byte values
    for b, c in sorted(seen.items()):
        ch = chr(b) if 32 <= b < 127 else "."
        printable.append(ch)
        print(f"  0x{b:02X} {ch!r:5} x{c}")
    print("\nas a set:", "".join(sorted(set(printable))))


# O(n) time, O(n) space — n = bytes in the larger bank (runs <= n, each mapped against r = 15 regions)
def cmd_diff(paths):
    """Byte-diff two banks, grouped by region. The hardware-verification tool."""
    if len(paths) != 2:
        print("diff needs exactly two files")
        return 2
    a, b = _load(paths[0]), _load(paths[1])
    print(f"A: {paths[0]} ({len(a):,} B)")
    print(f"B: {paths[1]} ({len(b):,} B)")
    if len(a) != len(b):
        print(f"!! lengths differ by {abs(len(a)-len(b)):,} bytes")
    runs = _diff_runs(a, b)
    if not runs:
        print("\nfiles are byte-identical")
        return 0
    byregion = collections.Counter()
    # O(n) time, O(1) space — n = bytes in the bank (runs <= n; r = 15 regions per lookup)
    for start, end in runs:
        byregion[_which_region(start)] += end - start
    # O(n) time, O(1) space — n = differing runs, at most bytes in the bank
    print(f"\n{len(runs)} differing run(s), {sum(e-s for s,e in runs):,} bytes total")
    print("\nby region:")
    # O(r) time, O(1) space — r = 15 named regions
    for r, n in byregion.most_common():
        print(f"  {r:20} {n:,} bytes")
    print(f"\nfirst {min(len(runs), DIFF_MAX_RUNS)} run(s):")
    # O(n) time, O(n) space — n = bytes in the bank (at most 40 runs printed, whose total length is at most n)
    for start, end in runs[:DIFF_MAX_RUNS]:
        av = a[start:end].hex(" ")
        bv = b[start:end].hex(" ")
        cap = 24
        print(f"  @0x{start:08X} +{end-start:<4} [{_which_region(start)}]")
        print(f"      A: {av[:cap*3]}{'...' if len(av) > cap*3 else ''}")
        print(f"      B: {bv[:cap*3]}{'...' if len(bv) > cap*3 else ''}")
    return 0


# ===========================================================================
# Helpers
# ===========================================================================
# O(n) time, O(k) space — n = bytes compared; k = diffs requested
def _first_diffs(a, b, n):
    out = []
    # O(n) time, O(k) space — n = bytes compared; k = diffs requested
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            out.append((i, x, y))
            if len(out) >= n:
                break
    return out


# O(n) time, O(n) space — n = bytes in the shorter bank
def _diff_runs(a, b):
    """Group differing bytes into contiguous runs -> [(start, end_exclusive)]."""
    runs = []
    start = None
    # O(n) time, O(n) space — n = bytes in the shorter bank
    for i in range(min(len(a), len(b))):
        if a[i] != b[i]:
            if start is None:
                start = i
        elif start is not None:
            runs.append((start, i))
            start = None
    if start is not None:
        runs.append((start, min(len(a), len(b))))
    return runs


_REGIONS = None


# O(r) time, O(1) space — r = 15 named regions
def _which_region(off):
    """Map a byte offset to a named region, e.g. 'patterns[37].motion[2]'."""
    global _REGIONS
    if _REGIONS is None:
        _REGIONS = L.region_map()
    # O(r) time, O(1) space — r = 15 named regions
    for name, start, end, _ in _REGIONS:
        if end is None or start <= off < end:
            if off < start:
                continue
            if name == "patterns":
                idx = (off - start) // L.CHUNK_PATTERN
                within = (off - start) % L.CHUNK_PATTERN
                if within >= L.PAT_OFF_PARAMETERS_MOTION:
                    m = (
                        within - L.PAT_OFF_PARAMETERS_MOTION
                    ) // L.CHUNK_PARAMETERS_MOTION
                    mb = (
                        within - L.PAT_OFF_PARAMETERS_MOTION
                    ) % L.CHUNK_PARAMETERS_MOTION
                    kind = "target" if mb < 2 else f"step{mb-2}"
                    return f"patterns[{idx}].motion[{m}].{kind}"
                if within >= L.PAT_OFF_PARAMETERS_FX:
                    return f"patterns[{idx}].fx[{(within-L.PAT_OFF_PARAMETERS_FX)//4}]"
                return f"patterns[{idx}]+{within}"
            if name == "sample_hdr_mono":
                idx = (off - start) // L.CHUNK_SAMPLE_HEADER_MONO
                within = (off - start) % L.CHUNK_SAMPLE_HEADER_MONO
                return f"sample[{idx}]+{within}" + (".name" if within < 8 else "")
            if name == "sample_hdr_stereo":
                idx = (off - start) // L.CHUNK_SAMPLE_HEADER_STEREO
                within = (off - start) % L.CHUNK_SAMPLE_HEADER_STEREO
                return f"sample[{256+idx}]+{within}" + (".name" if within < 8 else "")
            return name
    return "?"


# O(N) time, O(n) space — N = total bytes across all banks; n = bytes in the largest bank
def cmd_validate(paths):
    """Consistency-check a bank beyond mere structure.

    Round-tripping proves we can read and rewrite a file. It does NOT prove the
    file is internally coherent -- a bank can be self-contradictory and still
    round-trip perfectly. This checks the claims the file makes about itself.
    """
    rc = 0
    # O(N) time, O(n) space — N = total bytes across all banks; n = bytes in the largest bank
    for path in paths:
        data = _load(path)
        bank = EsxBank(data)
        pcm_len = len(data) - L.ADDR_SAMPLE_DATA
        cur = struct.unpack_from(">I", data, L.ADDR_CURRENT_OFFSET)[0]
        n_mono = struct.unpack_from(">I", data, L.ADDR_NUM_MONO_SAMPLES)[0]
        n_ster = struct.unpack_from(">I", data, L.ADDR_NUM_STEREO_SAMPLES)[0]

        problems = []
        # O(k) time, O(k) space — k = 384 sample slots
        used = [s for s in bank.samples if not s.empty]
        # O(k) time, O(k) space — k = 384 sample slots
        used_mono = [s for s in used if not s.stereo]
        # O(k) time, O(k) space — k = 384 sample slots
        used_ster = [s for s in used if s.stereo]
        if len(used_mono) != n_mono:
            problems.append(
                f"header claims {n_mono} mono samples, found {len(used_mono)}"
            )
        if len(used_ster) != n_ster:
            problems.append(
                f"header claims {n_ster} stereo samples, found {len(used_ster)}"
            )

        oob, inverted = [], []
        # O(k) time, O(k) space — k = 384 sample slots
        for s in used:
            st, en = s.offset_start, s.offset_end
            if st > pcm_len or en > pcm_len:
                oob.append(s)
            elif en < st:
                inverted.append(s)
        if oob:
            problems.append(
                f"{len(oob)} sample(s) point OUTSIDE the {pcm_len:,}-byte PCM region "
                # O(k) time, O(1) space — k = 384 sample slots
                f"(highest end {max(s.offset_end for s in oob):,})"
            )
        if inverted:
            problems.append(f"{len(inverted)} sample(s) have end < start")

        # O(k) time, O(k) space — k = 384 sample slots
        in_range = [
            s
            for s in used
            if s.offset_end <= pcm_len and s.offset_end >= s.offset_start
        ]
        if in_range:
            # O(k) time, O(1) space — k = 384 sample slots
            mx = max(s.offset_end for s in in_range)
            if cur < mx:
                problems.append(
                    f"currentOffset {cur:,} is below the highest sample end {mx:,}"
                )
        if pcm_len < cur:
            problems.append(
                f"PCM region {pcm_len:,} is smaller than currentOffset {cur:,}"
            )

        # The manual (p.88) accepts any rate from 11,025 to 96,000 Hz -- it is a
        # RANGE, not a fixed list. Korg's own factory bank uses 31,250 Hz.
        # O(k) time, O(k) space — k = 384 sample slots
        bad_rate = [
            s
            for s in used
            if not (L.MIN_IMPORT_RATE_HZ <= s.sample_rate <= L.MAX_IMPORT_RATE_HZ)
        ]
        if bad_rate:
            problems.append(
                f"{len(bad_rate)} sample(s) with out-of-range sample rate "
                f"(e.g. slot {bad_rate[0].index} = {bad_rate[0].sample_rate})"
            )

        print(f"\n=== {path} ===")
        print(
            f"  PCM region {pcm_len:,} B | currentOffset {cur:,} | "
            f"{len(used)} sample slot(s) in use"
        )
        if not problems:
            print("  CONSISTENT — no problems found")
        else:
            rc = 1
            print(f"  {len(problems)} PROBLEM(S):")
            # O(k) time, O(1) space — k = 6 problem kinds at most
            for p in problems:
                print(f"    ! {p}")
            if oob:
                print("\n  first out-of-range slots:")
                # O(k) time, O(1) space — k = 8 slots printed at most
                for s in oob[:8]:
                    print(
                        f"    [{s.index:3}] {s.name!r:12} "
                        f"start={s.offset_start:,} end={s.offset_end:,}"
                    )
                print(
                    "  These headers reference audio that is not present in the file."
                )
    return rc


COMMANDS = {
    "inspect": cmd_inspect,
    "verify": cmd_verify,
    "validate": cmd_validate,
    "motion": cmd_motion,
    "names": cmd_names,
    "diff": cmd_diff,
}


# O(N) time, O(n) space — N = total bytes across all banks named; n = bytes in the largest bank
def main(argv):
    if len(argv) < 3 or argv[1] not in COMMANDS:
        print(__doc__)
        print("commands:", ", ".join(COMMANDS))
        return 2
    return COMMANDS[argv[1]](argv[2:]) or 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
