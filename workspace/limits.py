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

from typing import Sequence


class Severity:
    """Finding severities."""
    OK = "ok"
    NOTICE = "notice"      # informational, no dialog
    WARN = "warn"          # dismissible, supports "ignore for all"
    BLOCK = "block"        # cannot proceed -- physically will not fit


# Warning codes that all mean "this sample is big" -> one mute action (TDD §6.4).
SIZE_WARNING_CODES = frozenset({"large_sample", "large_source", "dominant_sample"})


class Finding:
    """One thing worth telling the user about a candidate sample."""

    __slots__ = ("_level", "_code", "_message", "_dismissible")

    def __init__(self, level: str, code: str, message: str,
                 dismissible: bool = True):
        self._level = level
        self._code = code
        self._message = message
        # BLOCK findings are never dismissible: the audio genuinely cannot fit.
        self._dismissible = dismissible and level != Severity.BLOCK

    @property
    def level(self) -> str:
        return self._level

    @property
    def code(self) -> str:
        return self._code

    @property
    def message(self) -> str:
        return self._message

    @property
    def dismissible(self) -> bool:
        return self._dismissible

    def __repr__(self) -> str:
        return f"<{self._level}:{self._code}>"


class WarningPolicy:
    """Tracks which warning CODES the user has chosen to stop seeing.

    'Ignore for all' suppresses a code, not an individual sample. BLOCK findings
    are never suppressible; ignoring them would produce an unwritable bank.
    """

    __slots__ = ("_muted",)

    def __init__(self) -> None:
        self._muted: set[str] = set()

    def mute(self, code: str) -> None:
        raise NotImplementedError

    def mute_size_warnings(self) -> None:
        """One click: stop warning about large samples entirely."""
        raise NotImplementedError

    def unmute(self, code: str) -> None:
        raise NotImplementedError

    @property
    def muted(self) -> tuple[str, ...]:
        return tuple(sorted(self._muted))

    def visible(self, findings: Sequence[Finding]) -> tuple[Finding, ...]:
        """Findings that survive the mute set (BLOCK always survives)."""
        raise NotImplementedError


class SampleLimitPolicy:
    """Evaluates a candidate sample against the fit/analysis/warn rules."""

    __slots__ = ()

    def check_sample(self, path: str, duration_s: float, channels: int,
                     target_rate: int, used_bytes: int = 0
                     ) -> tuple[tuple[Finding, ...], bool]:
        """Return (findings, analyse_ok).

        `used_bytes` is how much of the bank is already spoken for, so the fit
        check reflects real remaining space. analyse_ok is False for files past
        the analysis length limit (TDD §6.5). BLOCK messages name the concrete
        fixes that would work (fold to mono, drop a tier, trim) per TDD §6.4.
        """
        raise NotImplementedError
