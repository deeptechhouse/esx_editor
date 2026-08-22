"""
codec.validator — coherence checking, independent of parsing (TDD §4.4).

WHY SEPARATE FROM THE READER
    Round-tripping proves we can read and rewrite a file; it does NOT prove the
    file is internally coherent. One real corpus bank round-trips perfectly yet
    has 80 of 233 sample headers pointing outside the file. So validation is its
    own layer, run on demand, that checks the claims a bank makes about itself.

WHAT IT CHECKS
    - header sample counts vs. occupied slots
    - every sample's start/end inside the PCM region, and end >= start
    - currentOffset >= highest sample end
    - sample rates within 11,025 - 96,000 Hz
    - motion targets within the known operation table

POLICY
    Findings are REPORTED, never auto-repaired. Repair is an explicit user
    action with a preview of what would change (TDD §4.4).
"""

from __future__ import annotations

from typing import Sequence

from core.bank import Bank
from codec.operation_table import OperationTable


class Finding:
    """One coherence problem found in a bank."""

    # severity: "error" (bank is self-contradictory) | "warning" | "info"
    __slots__ = ("_severity", "_code", "_message")

    def __init__(self, severity: str, code: str, message: str):
        self._severity = severity
        self._code = code
        self._message = message

    @property
    def severity(self) -> str:
        return self._severity

    @property
    def code(self) -> str:
        return self._code

    @property
    def message(self) -> str:
        return self._message

    def __repr__(self) -> str:
        return f"<{self._severity}:{self._code}>"


class ValidationReport:
    """The immutable result of validating a bank."""

    __slots__ = ("_findings",)

    def __init__(self, findings: Sequence[Finding]):
        self._findings = tuple(findings)

    @property
    def findings(self) -> tuple[Finding, ...]:
        return self._findings

    @property
    def ok(self) -> bool:
        """True if there are no error-severity findings."""
        raise NotImplementedError

    def errors(self) -> tuple[Finding, ...]:
        raise NotImplementedError

    def warnings(self) -> tuple[Finding, ...]:
        raise NotImplementedError


class BankValidator:
    """Runs the coherence checks a bank makes about itself."""

    __slots__ = ("_ops",)

    def __init__(self, operation_table: OperationTable):
        self._ops = operation_table

    def validate(self, bank: Bank) -> ValidationReport:
        """Return a report of every coherence problem found. Never mutates."""
        raise NotImplementedError
