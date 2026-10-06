#!/usr/bin/env python3
"""
Evaluate the hardware test banks after they have been round-tripped through a
real ESX-1 — the return half of deploy/make_hw_test_banks.py.

WHAT QUESTION THIS ANSWERS, AND WHAT IT DOES NOT
    The generator writes eight banks, each making exactly one change. Loading
    them on the machine answers "did the machine understand what we wrote?" —
    and only your eyes and ears can answer that. A tempo reading 133.0 on the
    display is evidence this program cannot gather.

    This script answers the OTHER half, which the eyeball test cannot reach:
    after the machine has loaded a bank and saved it back, is our change STILL
    THERE? A machine that silently normalises, repairs, or drops a field will
    look fine on the display and betray itself only in the bytes coming back.
    Both halves are needed. Neither substitutes for the other, and the report
    says so every time it runs, because the temptation to read a wall of green
    as "the hardware test passed" is exactly how a wrong write ships.

FLOW
    main() -> ReadBackSession.load_manifest()   what each bank must still show
           -> ReadBackSession.match()           returned files -> test names
           -> ReadBackSession.evaluate()        one TestOutcome per bank
           -> ReadBackSession.report()

USAGE
    # 1. Generate, copy to the card, load each one on the machine.
    python3 deploy/make_hw_test_banks.py --source BANK.esx --out hw_test

    # 2. On the machine, after loading each bank: Save All back to the card
    #    under ANY name — the routing is by the tN prefix, so t3_sample.esx,
    #    T3.ESX and "t3 back.esx" all land on test t3_sample.
    # 3. Copy the returned files off the card, then:
    python3 deploy/hw_readback.py hw_test hw_test/readback

MATCHING IS DELIBERATELY LOOSE
    The ESX-1 names files itself and 8.3-uppercases them, so an exact-name
    match would fail on nearly every real session and report "you did not do
    the test" to someone who did. A returned file is routed by the first
    tN token in its name; anything unroutable is listed rather than ignored,
    because a file you cannot explain is a finding too.

ADDING A NEW PROBE KIND
    Subclass Probe, set `kind` to the string make_hw_test_banks.py passes to
    expect(), implement read(). Registration is automatic via __init_subclass__.
    The generator is the only place that says WHAT to look for; this file is
    the only place that says HOW to read it. Keep it that way — a second copy
    of an expected value is a second chance to be wrong about it.
"""

from __future__ import annotations

import abc
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from codec.reader import BankReader  # noqa: E402

#: Routes a returned filename to a test. Matches t0..t9 as a whole token, so
#: "t3_sample.esx", "T3.ESX" and "T3BACK.ESX" all route, but "output3.esx"
#: does not.
TEST_TOKEN = re.compile(r"(?:^|[^a-z0-9])(t[0-9])(?:[^0-9]|$)", re.IGNORECASE)


# ===========================================================================
# Probes — one per `kind` the generator emits
# ===========================================================================
class Probe(abc.ABC):
    """Reads back one fact a returned bank must still show.

    Subclasses are pure readers: given a parsed Bank and the params the
    generator recorded, return the value as it stands now. Comparison and
    reporting are someone else's job, so a probe stays trivially testable.
    """

    #: The `kind` string used by make_hw_test_banks.py's expect().
    kind: str = ""

    _registry: dict[str, Probe] = {}

    # O(1) time, O(1) space
    def __init_subclass__(cls, **kwargs) -> None:
        # Self-registration: adding a probe never means editing a lookup table
        # somewhere else, which is the usual way a new kind gets silently
        # dropped on the floor.
        super().__init_subclass__(**kwargs)
        if cls.kind:
            Probe._registry[cls.kind] = cls()

    @staticmethod
    # O(1) time, O(1) space
    def for_kind(kind: str) -> Probe | None:
        return Probe._registry.get(kind)

    @abc.abstractmethod
    # O(1) time, O(1) space
    def read(self, bank, params: dict):
        """Return the current value, or raise to signal 'could not read'."""

    # O(1) time, O(1) space
    def describe(self, params: dict) -> str:
        """Human label for the report line. Override where coordinates help."""
        return self.kind


class PatternTempoProbe(Probe):
    kind = "pattern_tempo"

    # O(p) time, O(p) space — p = 256 patterns (fixed ESX-1 bank size, patterns() copies the tuple)
    def read(self, bank, params):
        return bank.patterns()[params["pattern"]].header.tempo

    # O(1) time, O(1) space
    def describe(self, params):
        return f"pattern {params['pattern'] + 1:02d} tempo"


class StepActiveProbe(Probe):
    kind = "step_active"

    # O(p) time, O(p) space — p = 256 patterns (patterns() tuple copy, the step bitmap is a fixed 16 bytes)
    def read(self, bank, params):
        part = bank.patterns()[params["pattern"]].parts()[params["part"]]
        return part.sequence().is_active(params["step"])

    # O(1) time, O(1) space
    def describe(self, params):
        return (
            f"pattern {params['pattern'] + 1:02d} part {params['part'] + 1} "
            f"step {params['step']} trigger"
        )


class PartSampleNumberProbe(Probe):
    kind = "part_sample_number"

    # O(p) time, O(p) space — p = 256 patterns (patterns() tuple copy)
    def read(self, bank, params):
        return bank.patterns()[params["pattern"]].parts()[params["part"]].sample_number

    # O(1) time, O(1) space
    def describe(self, params):
        return (
            f"pattern {params['pattern'] + 1:02d} part {params['part'] + 1} "
            "sample number"
        )


class SampleNameProbe(Probe):
    kind = "sample_name"

    # O(s) time, O(s) space — s = 384 sample slots (fixed, samples() copies the tuple)
    def read(self, bank, params):
        return bank.samples()[params["slot"]].name

    # O(1) time, O(1) space
    def describe(self, params):
        return f"sample {params['slot']:03d} name"


class SampleRateProbe(Probe):
    kind = "sample_rate"

    # O(s) time, O(s) space — s = 384 sample slots (fixed, samples() copies the tuple)
    def read(self, bank, params):
        return bank.samples()[params["slot"]].sample_rate

    # O(1) time, O(1) space
    def describe(self, params):
        return f"sample {params['slot']:03d} rate"


class SampleBytesProbe(Probe):
    kind = "sample_bytes"

    # O(s) time, O(s) space — s = 384 sample slots (fixed, samples() copies the tuple)
    def read(self, bank, params):
        return bank.samples()[params["slot"]].audio_bytes

    # O(1) time, O(1) space
    def describe(self, params):
        return f"sample {params['slot']:03d} length in bytes"


class MotionStoredProbe(Probe):
    kind = "motion_stored"

    # O(p + v) time, O(p + v) space — p = 256 patterns (fixed tuple copy); v = values listed in the expectation
    def read(self, bank, params):
        slot = bank.patterns()[params["pattern"]].motion_slots()[params["slot"]]
        # O(v) time, O(v) space — v = values listed in the expectation (get_step is a constant-time index)
        return [slot.get_step(step) for step in range(len(params["value"]))]

    # O(1) time, O(1) space
    def describe(self, params):
        return (
            f"pattern {params['pattern'] + 1:02d} motion slot "
            f"{params['slot']} stored values"
        )


class SongNameProbe(Probe):
    kind = "song_name"

    # O(g) time, O(g) space — g = 64 songs (fixed, songs() copies the tuple)
    def read(self, bank, params):
        return bank.songs()[params["slot"]].name

    # O(1) time, O(1) space
    def describe(self, params):
        return f"song {params['slot'] + 1:02d} name"


class SongChainProbe(Probe):
    kind = "song_chain"

    # O(g + c) time, O(g + c) space — g = 64 songs (fixed tuple copy); c = patterns in this song's chain
    def read(self, bank, params):
        # chain is a tuple property; the manifest stores JSON lists, so compare
        # like for like rather than making the caller remember the difference.
        return list(bank.songs()[params["slot"]].chain)

    # O(1) time, O(1) space
    def describe(self, params):
        return f"song {params['slot'] + 1:02d} pattern chain"


class CcAssignmentsProbe(Probe):
    kind = "cc_assignments"

    # O(r) time, O(r) space — r = 33 CC assign rows (fixed)
    def read(self, bank, params):
        return list(bank.globals.cc_assignments())

    # O(1) time, O(1) space
    def describe(self, params):
        return "MIDI CC assign table (all 33 rows)"


# ===========================================================================
# Outcomes
# ===========================================================================
class ProbeOutcome:
    """One expectation, and what the returned bank actually shows."""

    HOLDS = "HOLDS"
    CHANGED = "CHANGED"
    UNREADABLE = "UNREADABLE"

    __slots__ = ("_label", "_status", "_expected", "_actual", "_note")

    # O(1) time, O(1) space
    def __init__(self, label, status, expected=None, actual=None, note=""):
        self._label = label
        self._status = status
        self._expected = expected
        self._actual = actual
        self._note = note

    @property
    # O(1) time, O(1) space
    def label(self) -> str:
        return self._label

    @property
    # O(1) time, O(1) space
    def status(self) -> str:
        return self._status

    @property
    # O(1) time, O(1) space
    def holds(self) -> bool:
        return self._status == self.HOLDS

    # O(w) time, O(w) space — w = characters rendered by _fmt (lists cut to 8 items per level)
    def line(self) -> str:
        if self.holds:
            return f"      ok    {self._label} = {_fmt(self._actual)}"
        if self._status == self.UNREADABLE:
            return f"      ????  {self._label} — {self._note}"
        return (
            f"      CHANGED {self._label}\n"
            f"              we wrote  {_fmt(self._expected)}\n"
            f"              came back {_fmt(self._actual)}"
        )


class TestOutcome:
    """Everything learned about one tN bank's return trip."""

    __slots__ = ("_name", "_summary", "_path", "_probes", "_delta", "_error")

    # O(q) time, O(q) space — q = probe outcomes passed in (tuple copy)
    def __init__(self, name, summary, path, probes, delta, error=""):
        self._name = name
        self._summary = summary
        self._path = path
        self._probes = tuple(probes)
        self._delta = delta
        self._error = error

    @property
    # O(1) time, O(1) space
    def name(self) -> str:
        return self._name

    @property
    # O(1) time, O(1) space
    def returned(self) -> bool:
        return self._path is not None

    @property
    # O(q) time, O(1) space — q = probe outcomes in this test
    def clean(self) -> bool:
        """Came back, parsed, and every expectation still holds."""
        # O(q) time, O(1) space — q = probe outcomes, short-circuits on the first failure
        return self.returned and not self._error and all(p.holds for p in self._probes)

    # O(c) time, O(c) space — c = characters in the rendered report (one line per probe)
    def report(self) -> str:
        head = f"  {self._name:<12} {self._summary}"
        if not self.returned:
            return (
                head
                + "\n      not returned — this test was not done, or the save is missing."
            )
        lines = [head, f"      file: {os.path.basename(self._path)}"]
        if self._error:
            lines.append(f"      COULD NOT READ: {self._error}")
            lines.append("      That is itself a finding: the machine wrote something")
            lines.append("      this codec cannot parse. Keep the file.")
            return "\n".join(lines)
        if self._delta is not None:
            plural = "byte differs" if self._delta == 1 else "bytes differ"
            if self._delta == 0:
                lines.append(
                    "      identical to what we wrote — the machine changed nothing."
                )
            else:
                lines.append(
                    f"      {self._delta:,} {plural} from what we wrote "
                    "(see below for whether it matters)"
                )
        # O(c) time, O(c) space — c = characters across the rendered probe lines
        lines += [p.line() for p in self._probes]
        return "\n".join(lines)


# ===========================================================================
# Session
# ===========================================================================
class ReadBackSession:
    """Matches returned banks to their tests and evaluates every expectation."""

    # O(1) time, O(1) space
    def __init__(self, generated_dir: str, returned_dir: str):
        self._generated = generated_dir
        self._returned = returned_dir
        self._manifest: dict = {}
        self._unmatched: list[str] = []

    # O(m) time, O(m) space — m = bytes in manifest.json
    def load_manifest(self) -> dict:
        path = os.path.join(self._generated, "manifest.json")
        if not os.path.exists(path):
            raise SystemExit(
                f"no manifest.json in {self._generated!r}.\n"
                "Generate the banks first:\n"
                "  python3 deploy/make_hw_test_banks.py --source BANK.esx "
                f"--out {self._generated}"
            )
        with open(path, encoding="utf-8") as fh:
            self._manifest = json.load(fh)
        return self._manifest

    # O(f log f + t) time, O(f + t) space — f = entries in the returned directory; t = tests in the manifest
    def match(self) -> dict[str, str]:
        """Route each returned .esx to a test name by its tN token."""
        by_test: dict[str, str] = {}
        # Index tests by their 2-character tN token once, instead of scanning
        # every test name for every returned file (that was files x tests).
        # setdefault keeps the FIRST test in manifest order per token, which is
        # exactly what the old next(t for t in tests if t.startswith(token))
        # returned — token is always 2 chars, so startswith == t[:2] equality.
        by_token: dict[str, str] = {}
        # O(t) time, O(t) space — t = tests in the manifest
        for test_name in self._manifest.get("tests", {}):
            by_token.setdefault(test_name[:2], test_name)
        # NOT glob("*.esx"): fnmatch is case-sensitive on posix whatever the
        # filesystem does, and the ESX-1 writes uppercase 8.3 names — so the
        # obvious version silently finds nothing after a real session and
        # reports "you did not do the test" to someone who did.
        # O(f log f) time, O(f) space — f = entries in the returned directory (sorted once)
        files = [
            os.path.join(self._returned, n)
            for n in sorted(os.listdir(self._returned))
            if n.lower().endswith(".esx")
            # macOS writes ._name AppleDouble sidecars onto FAT cards; they are
            # not banks and reading one looks like a corrupt save.
            and not n.startswith("._")
        ]
        # O(f) time, O(f) space — f = returned banks, each one regex search on its filename and a dict lookup
        for path in files:
            m = TEST_TOKEN.search(os.path.basename(path))
            if not m:
                self._unmatched.append(path)
                continue
            name = by_token.get(m.group(1).lower())
            if name is None:
                self._unmatched.append(path)
            else:
                # First match wins; a second save of the same test is listed
                # rather than silently overriding the first.
                by_test.setdefault(name, path)
        return by_test

    # O(t log t + B + E) time, O(b + E) space — t = tests in the manifest; B = bytes across all returned and generated banks; E = expectations across all tests; b = bytes in the largest single bank
    def evaluate(self, by_test: dict[str, str]) -> list[TestOutcome]:
        reader = BankReader()
        outcomes = []
        # O(t log t + B + E) time, O(b + E) space — t = tests; B = bytes across all banks read; E = expectations; b = largest single bank (one parsed at a time)
        for name, spec in sorted(self._manifest.get("tests", {}).items()):
            path = by_test.get(name)
            if path is None:
                outcomes.append(TestOutcome(name, spec["summary"], None, (), None))
                continue

            returned = open(path, "rb").read()
            delta = self._byte_delta(spec, returned)
            try:
                bank = reader.read_auto(returned)
            except Exception as exc:  # noqa: BLE001
                outcomes.append(
                    TestOutcome(
                        name,
                        spec["summary"],
                        path,
                        (),
                        delta,
                        f"{type(exc).__name__}: {exc}",
                    )
                )
                continue

            # O(e) time, O(e) space — e = expectations for this test (each probe touches a fixed 256/384-entry tuple)
            probes = [self._run_probe(bank, e) for e in spec.get("expect", [])]
            outcomes.append(TestOutcome(name, spec["summary"], path, probes, delta))
        return outcomes

    # O(b) time, O(b) space — b = bytes in the larger of the two banks (ours is read into memory)
    def _byte_delta(self, spec: dict, returned: bytes) -> int | None:
        """How many bytes differ from the bank we put ON the card."""
        original = os.path.join(self._generated, spec["file"])
        if not os.path.exists(original):
            return None
        ours = open(original, "rb").read()
        # O(b) time, O(1) space — b = bytes in the shorter bank
        n = sum(
            1 for i in range(min(len(ours), len(returned))) if ours[i] != returned[i]
        )
        return n + abs(len(ours) - len(returned))

    @staticmethod
    # O(k + v) time, O(k + v) space — k = keys in the expectation; v = items in its value (probe tuple copies are fixed-size)
    def _run_probe(bank, expectation: dict) -> ProbeOutcome:
        kind = expectation.get("kind", "?")
        # O(k) time, O(k) space — k = keys in the expectation
        params = {k: v for k, v in expectation.items() if k != "kind"}
        probe = Probe.for_kind(kind)
        if probe is None:
            return ProbeOutcome(
                kind,
                ProbeOutcome.UNREADABLE,
                note=f"no probe implements kind {kind!r} — add one to hw_readback.py",
            )
        label = probe.describe(params)
        try:
            actual = probe.read(bank, params)
        except NotImplementedError as exc:
            # An undecoded field is the codec being honest, not a hardware
            # result. Say which, so it is not read as a machine failure.
            return ProbeOutcome(
                label,
                ProbeOutcome.UNREADABLE,
                note=f"field is undecoded in this codec ({exc})",
            )
        except Exception as exc:  # noqa: BLE001
            return ProbeOutcome(
                label,
                ProbeOutcome.UNREADABLE,
                note=f"{type(exc).__name__}: {exc}",
            )
        expected = params.get("value")
        holds = _equal(expected, actual)
        return ProbeOutcome(
            label,
            ProbeOutcome.HOLDS if holds else ProbeOutcome.CHANGED,
            expected,
            actual,
        )

    # O(c + Q) time, O(o) space — c = characters printed; Q = probe outcomes across all tests; o = outcomes
    def report(self, outcomes: list[TestOutcome]) -> int:
        print("=" * 72)
        print("ESX-1 HARDWARE TEST — RETURN TRIP REPORT")
        print("=" * 72)
        print(f"\ngenerated: {self._generated}")
        print(f"returned:  {self._returned}\n")

        # O(c) time, O(1) space — c = characters of the rendered outcome reports
        for outcome in outcomes:
            print(outcome.report())
            print()

        if self._unmatched:
            print("Returned files that could not be routed to a test:")
            # O(u) time, O(1) space — u = returned files that matched no test
            for path in self._unmatched:
                print(f"  {os.path.basename(path)}")
            print(
                "  (routing is by a tN token in the filename — rename, or pass\n"
                "   the file to spike_a/hw_session.py if it is a checklist save.)\n"
            )

        # O(o) time, O(o) space — o = outcomes
        done = [o for o in outcomes if o.returned]
        # O(o + Q) time, O(o) space — o = returned outcomes; Q = their probe outcomes (clean scans each one's probes)
        clean = [o for o in done if o.clean]
        print("=" * 72)
        print(
            f"SUMMARY:  {len(clean)} preserved   "
            f"{len(done) - len(clean)} altered/unreadable   "
            f"{len(outcomes) - len(done)} not returned   (of {len(outcomes)})"
        )
        print("=" * 72)
        print(
            "\nREMEMBER: this only proves the machine PRESERVED what we wrote.\n"
            "Whether it UNDERSTOOD it — the tempo on the display, the step you\n"
            "hear, the song order it plays — is the eyeball half, and only you\n"
            "can record that. Write it down while the device is still out."
        )
        # Non-zero while anything is outstanding, so this can gate automation.
        return 0 if done and len(clean) == len(outcomes) else 1


# O(v) time, O(d) space — v = elements across both nested values; d = nesting depth (recursion stack)
def _equal(expected, actual) -> bool:
    """Compare a manifest value (JSON types) with a live value.

    JSON has no tuples and one number type, so a straight `==` would call an
    otherwise-perfect tuple or int/float pair a mismatch and send someone back
    to the hardware for nothing.
    """
    if isinstance(expected, (list, tuple)) and isinstance(actual, (list, tuple)):
        # O(v) time, O(d) space — v = elements across both nested values; d = nesting depth
        return len(expected) == len(actual) and all(
            _equal(e, a) for e, a in zip(expected, actual, strict=False)
        )
    if isinstance(expected, bool) or isinstance(actual, bool):
        return bool(expected) == bool(actual)
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return abs(float(expected) - float(actual)) < 1e-6
    return expected == actual


# O(w) time, O(w) space — w = characters in the result (lists are cut to 8 items per level, so long lists do not grow it)
def _fmt(value) -> str:
    """Short, readable rendering — long lists are truncated, not wrapped."""
    if isinstance(value, (list, tuple)):
        # O(w) time, O(w) space — w = characters in the rendered first 8 items
        body = ", ".join(_fmt(v) for v in value[:8])
        return f"[{body}{', …' if len(value) > 8 else ''}]"
    if isinstance(value, str):
        return repr(value)
    return str(value)


# O(t log t + f log f + B + E) time, O(b + E + f + m) space — t = tests; f = returned files; B = bytes across all banks; E = expectations; b = largest bank; m = manifest bytes
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Check whether an ESX-1 preserved what this editor wrote.",
    )
    parser.add_argument(
        "generated",
        nargs="?",
        default="hw_test",
        help="directory the banks were generated into (holds manifest.json)",
    )
    parser.add_argument(
        "returned",
        nargs="?",
        default=None,
        help="directory of banks saved back off the machine "
        "(default: <generated>/readback)",
    )
    args = parser.parse_args(argv)
    returned = args.returned or os.path.join(args.generated, "readback")

    if not os.path.isdir(returned):
        raise SystemExit(
            f"no such directory: {returned!r}\n"
            "Copy the banks you saved back off the card into it first."
        )

    session = ReadBackSession(args.generated, returned)
    session.load_manifest()
    return session.report(session.evaluate(session.match()))


if __name__ == "__main__":
    raise SystemExit(main())
