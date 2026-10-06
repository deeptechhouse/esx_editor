#!/usr/bin/env python3
"""
hw_session.py — one-command batch runner for the six ESX-1 hardware-checklist
                items in research/HARDWARE_CHECKLIST.md.

WHAT THIS IS FOR
    The six open questions in the TDD (§12) can only be *closed* on the physical
    machine — they need button presses and card saves this program cannot make.
    What this program does do:

      1. Extract every answer the banks ALREADY on the card can give.
      2. Route each saved bank to the right check by a filename tag, so a whole
         hardware session's worth of saves is evaluated in one command.
      3. Print, per item, whether it is RESOLVED, PARTIAL, or still NEEDS_HW,
         and — for the ones still open — the exact physical procedure to run.

FILENAME TAGGING (case-insensitive substring in the .esx filename)
    pitch    -> item 1  (a PITCH-knob motion recording)
    stereo   -> item 2  (a bank containing a stereo sample)
    rename   -> item 3  (a bank with a sample renamed on the machine)
    psg      -> item 4  (a Save-PSG file: pattern/song/global, no sample area)
    twicea   -> item 5  (first of two unchanged Save-All files)
    twiceb   -> item 5  (second of two unchanged Save-All files)
    Untagged banks still feed the charset and stale-header checks.

USAGE
    python3 hw_session.py                     # scans /Volumes/Untitled if mounted
    python3 hw_session.py DIR                 # scans a directory of .esx files
    python3 hw_session.py A.esx B.esx ...     # explicit files

DESIGN
    One HardwareCheck subclass per item (SOLID: each check is independently
    testable and new items can be added without touching the runner). The
    HardwareSession only discovers banks and orchestrates; it knows nothing
    about any individual check's logic.
"""

from __future__ import annotations

import os
import sys
import abc
import glob
import struct
import collections
from typing import Iterable, Sequence

import layout as L
from esx_probe import EsxBank

# --- Adjustable ------------------------------------------------------------
# Where a mounted ESX SmartMedia card usually appears on macOS.
DEFAULT_CARD_PATH = "/Volumes/Untitled"

# Motion target ids whose name is "<part> Pitch" in the 313-entry operation
# table (research/motion_operation_table_313.tsv). Item 1 needs one of these
# to carry a real recorded sweep.
PITCH_TARGET_IDS = frozenset({4, 36, 68, 100, 132, 164, 196, 228, 260, 356, 388, 420})

# The character whose presence in the dial's set decides the sharp-key policy
# in the a08C#m… naming convention (item 3).
SHARP_BYTE = 0x23  # '#'


# ===========================================================================
# Result value object
# ===========================================================================
class CheckResult:
    """Immutable outcome of one hardware check.

    status is one of:
        RESOLVED     the loaded banks conclusively answer the question
        PARTIAL      some evidence present, but a hardware confirmation remains
        NEEDS_HW     no relevant bank was supplied; the question is untouched
    """

    RESOLVED = "RESOLVED"
    PARTIAL = "PARTIAL"
    NEEDS_HW = "NEEDS_HW"

    __slots__ = ("_status", "_summary", "_details", "_next_action")

    # O(d) time, O(d) space — d = detail lines
    def __init__(
        self,
        status: str,
        summary: str,
        details: Sequence[str] = (),
        next_action: str = "",
    ):
        self._status = status
        self._summary = summary
        self._details = tuple(details)
        self._next_action = next_action

    @property
    # O(1) time, O(1) space
    def status(self) -> str:
        return self._status

    @property
    # O(1) time, O(1) space
    def summary(self) -> str:
        return self._summary

    @property
    # O(1) time, O(1) space
    def details(self) -> tuple[str, ...]:
        return self._details

    @property
    # O(1) time, O(1) space
    def next_action(self) -> str:
        return self._next_action


# ===========================================================================
# Loaded-bank value object
# ===========================================================================
class LoadedBank:
    """A parsed bank plus the raw bytes and the lower-cased filename tag set.

    `bank` is None when the file could not be parsed by the full-layout reader
    (a Save-PSG file legitimately cannot be — that is itself a finding).
    """

    __slots__ = ("_path", "_raw", "_bank", "_parse_error")

    # O(n) time, O(n) space — n = bytes in the bank file (read once, parsed once)
    def __init__(self, path: str):
        self._path = path
        with open(path, "rb") as f:
            self._raw = f.read()
        self._bank = None
        self._parse_error = None
        try:
            self._bank = EsxBank(self._raw)
        except Exception as exc:  # noqa: BLE001 — reported, not hidden
            self._parse_error = str(exc)

    @property
    # O(1) time, O(1) space
    def path(self) -> str:
        return self._path

    @property
    # O(1) time, O(1) space
    def name(self) -> str:
        return os.path.basename(self._path)

    @property
    # O(1) time, O(1) space
    def raw(self) -> bytes:
        return self._raw

    @property
    # O(1) time, O(1) space
    def bank(self):
        return self._bank

    @property
    # O(1) time, O(1) space
    def parse_error(self) -> str | None:
        return self._parse_error

    @property
    # O(1) time, O(1) space
    def size(self) -> int:
        return len(self._raw)

    # O(1) time, O(1) space
    def has_tag(self, tag: str) -> bool:
        return tag in self.name.lower()

    # O(n) time, O(n) space — n = bytes in the bank (serialised then compared)
    def round_trips(self) -> bool:
        """True if parse->serialize reproduces the file byte-for-byte."""
        return self._bank is not None and self._bank.to_bytes() == self._raw


# ===========================================================================
# Check base class
# ===========================================================================
class HardwareCheck(abc.ABC):
    """One checklist item. Subclasses implement evaluate()."""

    #: 1-based item number in HARDWARE_CHECKLIST.md
    item_no: int = 0
    #: short human title
    title: str = ""
    #: the physical procedure, shown when the item still needs hardware
    procedure: tuple[str, ...] = ()

    @abc.abstractmethod
    # O(b) time, O(1) space — b = banks supplied
    def evaluate(self, banks: Sequence[LoadedBank]) -> CheckResult: ...

    # -- shared helpers -----------------------------------------------------
    @staticmethod
    # O(b) time, O(b) space — b = banks supplied
    def _tagged(banks: Sequence[LoadedBank], tag: str) -> list[LoadedBank]:
        # O(b) time, O(b) space — b = banks supplied
        return [b for b in banks if b.has_tag(tag)]


# ===========================================================================
# Item 1 — Pitch value mapping
# ===========================================================================
class PitchMappingCheck(HardwareCheck):
    item_no = 1
    title = "Pitch value mapping (gates the motion editor's Pitch target)"
    procedure = (
        "Pick an empty pattern; assign any sample to Drum 1.",
        "Motion-record the PITCH knob: MOTION SEQ > SMOOTH > REC > PLAY,",
        "  then sweep PITCH slowly from min to max across one full cycle.",
        "Save All to card named e.g. PITCH_sweep.esx.",
        "Re-run this tool; the sweep's min/max reveal the true endpoints.",
    )

    # O(b) time, O(1) space — b = banks supplied (k = 256 patterns x 24 slots x 128 steps each, at most 256 distinct values sorted)
    def evaluate(self, banks: Sequence[LoadedBank]) -> CheckResult:
        values: collections.Counter = collections.Counter()
        slots_found = 0
        # O(b) time, O(1) space — b = banks supplied (k = 256 patterns x 24 slots x 128 steps each)
        for lb in banks:
            if lb.bank is None:
                continue
            # O(k) time, O(1) space — k = 256 patterns x 24 slots x 128 steps
            for pat in lb.bank.patterns:
                # O(k) time, O(1) space — k = 24 slots x 128 steps
                for slot in pat.motion:
                    if slot.in_use and slot.target in PITCH_TARGET_IDS:
                        slots_found += 1
                        # O(k) time, O(1) space — k = 128 motion steps
                        for v in slot.values:
                            if v != L.MOTION_VALUE_DISABLED:
                                values[v] += 1
        if not slots_found:
            return CheckResult(
                CheckResult.NEEDS_HW,
                "No Pitch motion slot found in any supplied bank.",
                next_action="Record a PITCH-knob sweep (see procedure).",
            )

        lo, hi = min(values), max(values)
        bands = self._contiguous_bands(sorted(values))
        details = [
            f"{slots_found} Pitch motion slot(s) carrying data.",
            f"observed value range: {lo}..{hi}",
            # O(v) time, O(v) space — v = contiguous bands (at most 256 byte values)
            "contiguous bands: " + ", ".join(f"{a}-{b}" for a, b in bands),
        ]
        # A single contiguous, monotonic-capable band spanning most of 0..127
        # (or a clean signed split) is what resolves the encoding.
        if len(bands) == 1:
            status = CheckResult.RESOLVED
            summary = f"Single band {lo}..{hi} — encoding is a plain ramp."
        else:
            status = CheckResult.PARTIAL
            summary = (
                f"{len(bands)} disjoint bands — inspect for a signed "
                f"split vs. unused values."
            )
        return CheckResult(status, summary, details)

    @staticmethod
    # O(v) time, O(v) space — v = distinct values passed in (at most 256)
    def _contiguous_bands(vals: list[int]) -> list[tuple[int, int]]:
        bands: list[tuple[int, int]] = []
        # O(v) time, O(v) space — v = distinct values passed in (at most 256)
        for v in vals:
            if bands and v == bands[-1][1] + 1:
                bands[-1] = (bands[-1][0], v)
            else:
                bands.append((v, v))
        return bands


# ===========================================================================
# Item 2 — Stereo sample header
# ===========================================================================
class StereoHeaderCheck(HardwareCheck):
    item_no = 2
    title = "Stereo sample header (gates stereo import)"
    procedure = (
        "Get one STEREO sample into the machine (sample the audio input in",
        "  stereo, or load a stereo WAV from card).",
        "Save All to card named e.g. STEREO_test.esx.",
        "Re-run this tool: it must report a non-zero stereo count AND the",
        "  bank must still round-trip byte-identically.",
    )

    # O(b) time, O(1) space — b = banks supplied (k = 128 stereo slots each)
    def evaluate(self, banks: Sequence[LoadedBank]) -> CheckResult:
        best = None
        # O(b) time, O(1) space — b = banks supplied (k = 384 sample slots each)
        for lb in banks:
            if lb.bank is None:
                continue
            # O(k) time, O(k) space — k = 384 sample slots
            stereo_used = [s for s in lb.bank.samples if s.stereo and not s.empty]
            if stereo_used:
                best = (lb, stereo_used)
                break
        if best is None:
            return CheckResult(
                CheckResult.NEEDS_HW,
                "No populated stereo sample in any supplied bank "
                "(all corpus banks are mono-only).",
                next_action="Save a bank containing a stereo sample.",
            )

        lb, stereo_used = best
        rt = lb.round_trips()
        details = [
            f"{lb.name}: {len(stereo_used)} stereo sample(s) in use",
            f"round-trip byte-identical: {'yes' if rt else 'NO'}",
        ]
        if rt:
            return CheckResult(
                CheckResult.RESOLVED,
                "Stereo bank round-trips — 44-byte header layout confirmed.",
                details,
            )
        return CheckResult(
            CheckResult.PARTIAL,
            "Stereo sample present but bank does NOT round-trip — "
            "stereo header layout needs correction before shipping import.",
            details,
            next_action="Diff against a mono save to localise the stereo fields.",
        )


# ===========================================================================
# Item 3 — Displayable character set
# ===========================================================================
class CharsetCheck(HardwareCheck):
    item_no = 3
    title = "Displayable character set (affects the naming convention)"
    procedure = (
        "SHIFT+WRITE/RENAME a sample; dial through EVERY character the machine",
        "  offers, using all 8 positions to capture the full set.",
        "Save All to card named e.g. RENAME_charset.esx.",
        "Re-run this tool: it reports the exact byte set and whether '#' exists.",
    )

    # O(b) time, O(1) space — b = banks supplied (k = 384 slots x 8 name bytes each)
    def evaluate(self, banks: Sequence[LoadedBank]) -> CheckResult:
        seen: collections.Counter = collections.Counter()
        # O(b) time, O(1) space — b = banks supplied (k = 384 slots x 8 name bytes each)
        for lb in banks:
            if lb.bank is None:
                continue
            # O(k) time, O(1) space — k = 384 slots x 8 name bytes
            for s in lb.bank.samples:
                if not s.empty:
                    seen.update(s.name_bytes)
        if not seen:
            return CheckResult(
                CheckResult.NEEDS_HW,
                "No sample names to inspect.",
                next_action="Save a bank with at least one named sample.",
            )

        # O(v log v) time, O(v) space — v = distinct name bytes (at most 256)
        charset = "".join(chr(b) for b in sorted(seen) if 32 <= b < 127)
        has_sharp = SHARP_BYTE in seen
        # O(b) time, O(1) space — b = banks supplied
        has_rename_bank = any(b.has_tag("rename") for b in banks)
        details = [
            f"distinct printable bytes ({len(charset)}): {charset}",
            f"'#' (0x23) present: {'YES' if has_sharp else 'no'}",
        ]
        if not has_rename_bank:
            return CheckResult(
                CheckResult.PARTIAL,
                "Charset derived from imported WAV names, NOT typed on the "
                "machine — cannot yet confirm what the dial offers.",
                details,
                next_action="Do a machine RENAME dialling every character.",
            )
        status = CheckResult.RESOLVED
        summary = "Dial charset captured. " + (
            "'#' available — sharp keys OK."
            if has_sharp
            else "NO '#' — naming policy must substitute s/b for #/♭."
        )
        return CheckResult(status, summary, details)


# ===========================================================================
# Item 4 — PSG save variant
# ===========================================================================
class PsgSaveCheck(HardwareCheck):
    item_no = 4
    title = "PSG save variant (codec robustness)"
    procedure = (
        "GLOBAL > CARD > Save > choose PSG (not All) > save as e.g. PSG_test.esx.",
        "Re-run this tool: it confirms the short no-sample-area file is handled.",
    )

    # O(b) time, O(b) space — b = banks supplied
    def evaluate(self, banks: Sequence[LoadedBank]) -> CheckResult:
        psg = self._tagged(banks, "psg")
        # Also auto-detect: any file shorter than the All-save minimum.
        # Membership by identity through a set, not `b not in psg` on the list:
        # the list scan made this quadratic in the bank count. LoadedBank has no
        # __eq__, so the list test was already an identity test -- same result.
        # O(p) time, O(p) space — p = PSG-tagged banks
        psg_ids = {id(b) for b in psg}
        # O(b) time, O(b) space — b = banks supplied (set lookup per bank)
        short = [b for b in banks if b.size < L.SIZE_FILE_MIN and id(b) not in psg_ids]
        candidates = psg + short
        if not candidates:
            return CheckResult(
                CheckResult.NEEDS_HW,
                "No PSG (short, no-sample-area) file supplied.",
                next_action="Do a Save-PSG on the machine.",
            )

        lb = candidates[0]
        has_magic1 = lb.raw.startswith(L.MAGIC_HEAD)
        details = [
            f"{lb.name}: {lb.size:,} B (All-save min is {L.SIZE_FILE_MIN:,} B)",
            f"KORG magic at 0x0: {'yes' if has_magic1 else 'NO'}",
        ]
        if lb.parse_error is not None:
            details.append(f"full-layout reader rejects it: {lb.parse_error}")
            return CheckResult(
                CheckResult.PARTIAL,
                "PSG file obtained — confirms the codec needs a dedicated "
                "PSG-length parse path (the full-layout reader assumes a "
                "sample area).",
                details,
                next_action="Implement a PSG branch in codec/reader.py.",
            )
        return CheckResult(
            CheckResult.RESOLVED, "PSG file parsed by the current reader.", details
        )


# ===========================================================================
# Item 5 — Two identical saves: are the unknown regions real state?
# ===========================================================================
class TwiceSavedCheck(HardwareCheck):
    item_no = 5
    title = "Unchanged double-save (are 'unknown' regions real state?)"
    procedure = (
        "Save All as TWICEA.esx; change NOTHING; Save All again as TWICEB.esx.",
        "Re-run this tool: it diffs them by region.",
        "Ideal result: byte-identical. Any differing run is named by region.",
    )

    # O(b + n) time, O(b + n) space — b = banks supplied; n = bytes in each TWICE bank (r = 15 regions per differing byte)
    def evaluate(self, banks: Sequence[LoadedBank]) -> CheckResult:
        a = self._tagged(banks, "twicea")
        b = self._tagged(banks, "twiceb")
        if not (a and b):
            return CheckResult(
                CheckResult.NEEDS_HW,
                "Need both TWICEA and TWICEB saves (unchanged between them).",
                next_action="Save All twice with nothing changed.",
            )

        ba, bb = a[0], b[0]
        if len(ba.raw) != len(bb.raw):
            return CheckResult(
                CheckResult.PARTIAL,
                f"Files differ in length ({len(ba.raw):,} vs {len(bb.raw):,}).",
                [f"{ba.name} vs {bb.name}"],
            )

        # O(n) time, O(n) space — n = bytes in each TWICE bank
        diffs = [i for i in range(len(ba.raw)) if ba.raw[i] != bb.raw[i]]
        if not diffs:
            return CheckResult(
                CheckResult.RESOLVED,
                "Byte-identical — writer may treat all regions as stable state.",
                [f"{ba.name} == {bb.name}"],
            )

        regions = collections.Counter()
        # Build the region map once, not once per differing byte (it was
        # rebuilt inside _region_name for every offset).
        region_map = L.region_map()
        # O(n) time, O(1) space — n = differing bytes, at most bytes in the bank (r = 15 regions each)
        for off in diffs:
            regions[self._region_name(off, region_map)] += 1
        details = [
            f"{len(diffs):,} differing byte(s) across " f"{len(regions)} region(s):"
        ]
        # O(r) time, O(r) space — r = 15 named regions
        details += [f"  {r}: {n:,} B" for r, n in regions.most_common()]
        # O(r) time, O(1) space — r = 15 named regions
        only_unknown = all(r.startswith("unknown") for r in regions)
        return CheckResult(
            CheckResult.RESOLVED if only_unknown else CheckResult.PARTIAL,
            (
                "Differences confined to unknown regions — they are scratch, "
                "writer can relax."
                if only_unknown
                else "Differences reach DECODED regions — investigate before "
                "relaxing the writer."
            ),
            details,
        )

    @staticmethod
    # O(r) time, O(r) space — r = 15 named regions (map built only when not passed in)
    def _region_name(off: int, region_map=None) -> str:
        # region_map: pass L.region_map() in when calling in a loop; built
        # here when omitted so single lookups stay one-liners.
        # O(r) time, O(1) space — r = 15 named regions
        for name, start, end, _ in region_map or L.region_map():
            if start <= off and (end is None or off < end):
                return name
        return "?"


# ===========================================================================
# Item 6 — Stale sample headers
# ===========================================================================
class StaleHeaderCheck(HardwareCheck):
    item_no = 6
    title = "Stale sample headers (repair vs. refuse policy)"
    procedure = (
        "Put a bank with out-of-range headers (e.g. e4.esx) on a card.",
        "Load it on the ESX-1 and observe: clean load, error, or silent gaps?",
        "Record the outcome — it decides whether the editor repairs or refuses.",
    )

    # O(b) time, O(b) space — b = banks supplied (k = 384 sample slots each)
    def evaluate(self, banks: Sequence[LoadedBank]) -> CheckResult:
        offenders = []
        # O(b) time, O(b) space — b = banks supplied (k = 384 sample slots each)
        for lb in banks:
            if lb.bank is None:
                continue
            pcm_len = lb.size - L.ADDR_SAMPLE_DATA
            # O(k) time, O(k) space — k = 384 sample slots
            used = [s for s in lb.bank.samples if not s.empty]
            # O(k) time, O(k) space — k = 384 sample slots
            oob = [
                s for s in used if s.offset_start > pcm_len or s.offset_end > pcm_len
            ]
            if oob:
                offenders.append(
                    (
                        lb,
                        len(oob),
                        len(used),
                        # O(k) time, O(1) space — k = 384 sample slots
                        max(s.offset_end for s in oob),
                        pcm_len,
                    )
                )
        if not offenders:
            return CheckResult(
                CheckResult.NEEDS_HW,
                "No bank with stale headers supplied to test on hardware.",
                next_action="Load a stale-header bank on the machine.",
            )

        details = []
        # O(b) time, O(b) space — b = offending banks
        for lb, n_oob, n_used, hi_end, pcm in offenders:
            details.append(
                f"{lb.name}: {n_oob}/{n_used} headers point outside the "
                f"{pcm:,}-B PCM region (highest end {hi_end:,})."
            )
        return CheckResult(
            CheckResult.PARTIAL,
            "Stale-header bank(s) identified and characterised. The load "
            "behaviour itself can only be observed on the device.",
            details,
            next_action="Load the bank on the ESX-1 and record what happens.",
        )


# ===========================================================================
# Orchestrator
# ===========================================================================
class HardwareSession:
    """Discovers banks and runs every registered check against them."""

    # O(c) time, O(c) space — c = checks registered
    def __init__(self, checks: Iterable[HardwareCheck] | None = None):
        self._checks: list[HardwareCheck] = (
            list(checks)
            if checks
            else [
                PitchMappingCheck(),
                StereoHeaderCheck(),
                CharsetCheck(),
                PsgSaveCheck(),
                TwiceSavedCheck(),
                StaleHeaderCheck(),
            ]
        )

    @staticmethod
    # O(f log f) time, O(f) space — f = .esx files found across the targets (each directory listing sorted)
    def discover(args: Sequence[str]) -> list[str]:
        """Turn CLI args (files, dirs, or nothing) into a list of .esx paths."""
        paths: list[str] = []
        targets = (
            list(args)
            if args
            else ([DEFAULT_CARD_PATH] if os.path.isdir(DEFAULT_CARD_PATH) else [])
        )
        # O(f log f) time, O(f) space — f = .esx files found across the targets
        for t in targets:
            if os.path.isdir(t):
                # Skip macOS AppleDouble sidecars (._name).
                # O(f log f) time, O(f) space — f = .esx files in this directory
                paths += [
                    p
                    for p in sorted(glob.glob(os.path.join(t, "*.esx")))
                    if not os.path.basename(p).startswith("._")
                ]
            elif os.path.isfile(t):
                paths.append(t)
        return paths

    # O(c * N) time, O(N) space — N = total bytes across all banks; c = 6 checks, each a pass over the banks
    def run(self, paths: Sequence[str]) -> int:
        banks: list[LoadedBank] = []
        # O(N) time, O(N) space — N = total bytes across all banks
        for p in paths:
            try:
                banks.append(LoadedBank(p))
            except Exception as exc:  # noqa: BLE001
                print(f"  ! could not read {p}: {exc}")

        print("=" * 72)
        print("ESX-1 HARDWARE CHECKLIST — BATCH REPORT")
        print("=" * 72)
        if not banks:
            print("\nNo .esx banks found. Mount the card or pass files/dirs.\n")
            self._print_all_procedures()
            return 2

        print(f"\nBanks loaded ({len(banks)}):")
        # O(N) time, O(n) space — N = total bytes across all banks (one round-trip each); n = bytes in the largest bank
        for lb in banks:
            tag = "PSG?" if lb.size < L.SIZE_FILE_MIN else "All"
            rt = (
                "ok"
                if lb.round_trips()
                else ("PARSE-FAIL" if lb.bank is None else "DIFF")
            )
            print(f"  {lb.name:<28} {lb.size:>12,} B  [{tag}]  round-trip:{rt}")

        counts = collections.Counter()
        # O(c * N) time, O(n) space — c = 6 checks; N = total bytes across all banks; n = bytes in the largest bank
        for chk in self._checks:
            res = chk.evaluate(banks)
            counts[res.status] += 1
            self._print_result(chk, res)

        print("\n" + "=" * 72)
        print(
            f"SUMMARY:  RESOLVED {counts[CheckResult.RESOLVED]}   "
            f"PARTIAL {counts[CheckResult.PARTIAL]}   "
            f"NEEDS_HW {counts[CheckResult.NEEDS_HW]}   "
            f"(of {len(self._checks)} items)"
        )
        print("=" * 72)
        # Exit non-zero while anything is still open, so CI/automation can gate.
        return 0 if counts[CheckResult.RESOLVED] == len(self._checks) else 1

    # -- printing -----------------------------------------------------------
    @staticmethod
    # O(d) time, O(1) space — d = detail lines plus procedure steps
    def _print_result(chk: HardwareCheck, res: CheckResult) -> None:
        print(f"\n[{res.status:8}] item {chk.item_no} — {chk.title}")
        print(f"    {res.summary}")
        # O(d) time, O(1) space — d = detail lines
        for d in res.details:
            print(f"      · {d}")
        if res.status != CheckResult.RESOLVED:
            if res.next_action:
                print(f"    NEXT: {res.next_action}")
            if chk.procedure:
                print("    PROCEDURE:")
                # O(s) time, O(1) space — s = procedure steps
                for step in chk.procedure:
                    print(f"      {step}")

    # O(c * s) time, O(1) space — c = 6 checks; s = procedure steps per check (at most 5)
    def _print_all_procedures(self) -> None:
        print("Physical procedures for all six items:\n")
        # O(c * s) time, O(1) space — c = 6 checks; s = procedure steps per check (at most 5)
        for chk in self._checks:
            print(f"item {chk.item_no} — {chk.title}")
            # O(s) time, O(1) space — s = procedure steps (at most 5)
            for step in chk.procedure:
                print(f"  {step}")
            print()


# O(c * N + f log f) time, O(N) space — N = total bytes across all banks; c = 6 checks; f = .esx files discovered
def main(argv: Sequence[str]) -> int:
    session = HardwareSession()
    paths = session.discover(argv[1:])
    return session.run(paths)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
