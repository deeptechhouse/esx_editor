"""
workspace.limits — oversize-sample policy (TDD §6.4).

Three independent questions per candidate sample, deliberately kept apart:
    1. Will it FIT?           -> capacity check, can be a hard BLOCK
    2. Is it WORTH ANALYSING? -> long files skip key detection (correctness,
                                 not speed: a global key for a long recording is
                                 meaningless and would mislabel the file)
    3. Should we WARN?        -> dismissible, "ignore for all" mutes a CODE

Ported in contract form from spike_a/limits.py.
"""

from __future__ import annotations

import os
from collections.abc import Sequence

import codec.layout as L
from workspace.budget import TIERS, BudgetCalculator


class Severity:
    """Finding severities."""

    OK = "ok"
    NOTICE = "notice"  # informational, no dialog
    WARN = "warn"  # dismissible, supports "ignore for all"
    BLOCK = "block"  # cannot proceed -- physically will not fit


# Warning codes that all mean "this sample is big" -> one mute action (TDD §6.4).
SIZE_WARNING_CODES = frozenset({"large_sample", "large_source", "dominant_sample"})


class Finding:
    """One thing worth telling the user about a candidate sample."""

    __slots__ = ("_level", "_code", "_message", "_dismissible")

    # O(1) time, O(1) space
    def __init__(self, level: str, code: str, message: str, dismissible: bool = True):
        self._level = level
        self._code = code
        self._message = message
        # BLOCK findings are never dismissible: the audio genuinely cannot fit.
        self._dismissible = dismissible and level != Severity.BLOCK

    @property
    # O(1) time, O(1) space
    def level(self) -> str:
        return self._level

    @property
    # O(1) time, O(1) space
    def code(self) -> str:
        return self._code

    @property
    # O(1) time, O(1) space
    def message(self) -> str:
        return self._message

    @property
    # O(1) time, O(1) space
    def dismissible(self) -> bool:
        return self._dismissible

    # O(1) time, O(1) space
    def __repr__(self) -> str:
        return f"<{self._level}:{self._code}>"


class WarningPolicy:
    """Tracks which warning CODES the user has chosen to stop seeing.

    'Ignore for all' suppresses a code, not an individual sample. BLOCK findings
    are never suppressible; ignoring them would produce an unwritable bank.
    """

    __slots__ = ("_muted",)

    # O(1) time, O(1) space
    def __init__(self) -> None:
        self._muted: set[str] = set()

    # O(1) time, O(1) space
    def mute(self, code: str) -> None:
        self._muted.add(code)

    # O(k) time, O(k) space — k = 3 size-warning codes (fixed)
    def mute_size_warnings(self) -> None:
        """One click: stop warning about large samples entirely."""
        self._muted.update(SIZE_WARNING_CODES)

    # O(1) time, O(1) space
    def unmute(self, code: str) -> None:
        self._muted.discard(code)

    @property
    # O(m log m) time, O(m) space — m = muted codes (sorted on every read)
    def muted(self) -> tuple[str, ...]:
        return tuple(sorted(self._muted))

    # O(n) time, O(n) space — n = findings (mute check is a set lookup)
    def visible(self, findings: Sequence[Finding]) -> tuple[Finding, ...]:
        """Findings that survive the mute set (BLOCK always survives)."""
        # O(n) time, O(n) space — n = findings
        return tuple(
            f
            for f in findings
            if f.level != Severity.OK and not (f.dismissible and f.code in self._muted)
        )


class SampleLimitPolicy:
    """Evaluates a candidate sample against the fit/analysis/warn rules."""

    __slots__ = (
        "_analysis_max_s",
        "_warn_bank_frac",
        "_max_single_frac",
        "_warn_source_bytes",
        "_partial_analysis_s",
        "_capacity",
        "_calc",
    )

    # Defaults match spike_a/limits.py CONFIG (TDD §6.4 / §6.5).
    ANALYSIS_MAX_SECONDS = 30.0
    WARN_BANK_FRACTION = 0.10
    MAX_SINGLE_SAMPLE_FRACTION = 0.80
    WARN_SOURCE_BYTES = 20 * 1024 * 1024
    PARTIAL_ANALYSIS_SECONDS = 30.0

    # O(1) time, O(1) space
    def __init__(
        self,
        analysis_max_seconds: float = ANALYSIS_MAX_SECONDS,
        warn_bank_fraction: float = WARN_BANK_FRACTION,
        max_single_fraction: float = MAX_SINGLE_SAMPLE_FRACTION,
        warn_source_bytes: int = WARN_SOURCE_BYTES,
        partial_analysis_seconds: float = PARTIAL_ANALYSIS_SECONDS,
        capacity: int | None = None,
    ):
        self._analysis_max_s = analysis_max_seconds
        self._warn_bank_frac = warn_bank_fraction
        self._max_single_frac = max_single_fraction
        self._warn_source_bytes = warn_source_bytes
        self._partial_analysis_s = partial_analysis_seconds
        self._capacity = L.MAX_SAMPLE_BYTES if capacity is None else capacity
        self._calc = BudgetCalculator()

    # O(t) time, O(1) space — t = 5 quality tiers (fixed TIERS ladder)
    def check_sample(
        self,
        path: str,
        duration_s: float,
        channels: int,
        target_rate: int,
        used_bytes: int = 0,
    ) -> tuple[tuple[Finding, ...], bool]:
        """Return (findings, analyse_ok).

        `used_bytes` is how much of the bank is already spoken for, so the fit
        check reflects real remaining space. analyse_ok is False for files past
        the analysis length limit (TDD §6.5). BLOCK messages name the concrete
        fixes that would work (fold to mono, drop a tier, trim) per TDD §6.4.
        """
        findings: list[Finding] = []
        cost = self._calc.cost_bytes(duration_s, target_rate, channels)
        free = self._capacity - used_bytes
        single_cap = int(self._capacity * self._max_single_frac)

        if cost > single_cap:
            frames = int(round(duration_s * target_rate))
            fixes: list[str] = []
            if channels > 1 and (frames * 2) <= single_cap:
                fixes.append("fold to mono")
            # O(t) time, O(1) space — t = 4 lower quality tiers (fixed TIERS[1:])
            for label, rate in TIERS[1:]:
                if int(round(duration_s * rate)) * 2 <= single_cap:
                    fixes.append(f"drop to {label} ({rate} Hz) mono")
                    break
            fixes.append(f"trim to {single_cap / (44100 * 2):.0f}s at CD mono")
            findings.append(
                Finding(
                    Severity.BLOCK,
                    "exceeds_single_cap",
                    f"{duration_s:.1f}s at {target_rate} Hz needs {cost:,} B. One sample "
                    f"may use at most {self._max_single_frac:.0%} of sample memory "
                    f"({single_cap:,} B), leaving {1 - self._max_single_frac:.0%} free. "
                    f"Options: " + "; ".join(fixes) + ".",
                    dismissible=False,
                )
            )
        elif cost > self._capacity * self._warn_bank_frac and cost > single_cap * 0.5:
            steps = duration_s / 128.0
            findings.append(
                Finding(
                    Severity.WARN,
                    "dominant_sample",
                    f"uses {cost:,} B — {100 * cost / self._capacity:.0f}% of the bank, "
                    f"leaving {self._capacity - cost:,} B "
                    f"({(self._capacity - cost) / (44100 * 2):.0f}s at CD mono) for "
                    f"everything else. Motion-sequencing Start Point across its 128 "
                    f"positions moves ~{steps:.2f}s per step.",
                )
            )
        elif cost > free:
            findings.append(
                Finding(
                    Severity.BLOCK,
                    "exceeds_free",
                    f"needs {cost:,} B but only {free:,} B remain in this bank.",
                    dismissible=False,
                )
            )
        elif cost > self._capacity * self._warn_bank_frac:
            findings.append(
                Finding(
                    Severity.WARN,
                    "large_sample",
                    f"uses {cost:,} B — {100 * cost / self._capacity:.0f}% of the whole bank.",
                )
            )

        try:
            src = os.path.getsize(path)
            if src > self._warn_source_bytes:
                findings.append(
                    Finding(
                        Severity.WARN,
                        "large_source",
                        f"source file is {src / 1048576:.1f} MB.",
                    )
                )
        except OSError:
            pass

        analyse_ok = duration_s <= self._analysis_max_s
        if not analyse_ok:
            findings.append(
                Finding(
                    Severity.NOTICE,
                    "analysis_skipped",
                    f"{duration_s:.1f}s exceeds the {self._analysis_max_s:.0f}s analysis "
                    f"limit — key detection skipped, no key appended. A single key for a "
                    f"recording this long would not be meaningful. You can analyse the "
                    f"first {self._partial_analysis_s:.0f}s explicitly if you want one.",
                )
            )

        if not findings:
            findings.append(Finding(Severity.OK, "ok", "fine"))
        return tuple(findings), analyse_ok
