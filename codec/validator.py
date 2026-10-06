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

from collections.abc import Sequence

import codec.layout as L
from codec.operation_table import OperationTable
from core.bank import SAVE_PSG, Bank


class Finding:
    """One coherence problem found in a bank."""

    # severity: "error" (bank is self-contradictory) | "warning" | "info"
    __slots__ = ("_severity", "_code", "_message")

    # O(1) time, O(1) space
    def __init__(self, severity: str, code: str, message: str):
        self._severity = severity
        self._code = code
        self._message = message

    # O(1) time, O(1) space
    @property
    def severity(self) -> str:
        return self._severity

    # O(1) time, O(1) space
    @property
    def code(self) -> str:
        return self._code

    # O(1) time, O(1) space
    @property
    def message(self) -> str:
        return self._message

    # O(1) time, O(1) space
    def __repr__(self) -> str:
        return f"<{self._severity}:{self._code}>"


class ValidationReport:
    """The immutable result of validating a bank."""

    __slots__ = ("_findings",)

    # O(f) time, O(f) space — f = findings
    def __init__(self, findings: Sequence[Finding]):
        self._findings = tuple(findings)

    # O(1) time, O(1) space
    @property
    def findings(self) -> tuple[Finding, ...]:
        return self._findings

    # O(f) time, O(f) space — f = findings
    @property
    def ok(self) -> bool:
        """True if there are no error-severity findings."""
        return not self.errors()

    # O(f) time, O(f) space — f = findings
    def errors(self) -> tuple[Finding, ...]:
        # O(f) time, O(f) space — f = findings
        return tuple(f for f in self._findings if f.severity == "error")

    # O(f) time, O(f) space — f = findings
    def warnings(self) -> tuple[Finding, ...]:
        # O(f) time, O(f) space — f = findings
        return tuple(f for f in self._findings if f.severity == "warning")

    # O(1) time, O(1) space
    def __len__(self) -> int:
        return len(self._findings)


class BankValidator:
    """Runs the coherence checks a bank makes about itself."""

    __slots__ = ("_ops",)

    # O(1) time, O(1) space
    def __init__(self, operation_table: OperationTable | None = None):
        self._ops = operation_table

    # O(b + p*k) time, O(b + f) space — b = PCM bytes (bank.pcm hands back a copy), p = patterns, k = 24 motion slots per pattern, f = findings
    def validate(self, bank: Bank) -> ValidationReport:
        """Return a report of every coherence problem found. Never mutates."""
        findings: list[Finding] = []
        if bank.save_type == SAVE_PSG:
            # A PSG save has no sample area; only motion coherence is checkable.
            self._check_motion(bank, findings)
            return ValidationReport(findings)

        self._check_samples(bank, findings)
        self._check_motion(bank, findings)
        return ValidationReport(findings)

    # O(b + s) time, O(b + f) space — b = PCM bytes (len(bank.pcm) copies it), s = 384 sample slots, f = findings
    def _check_samples(self, bank: Bank, findings: list[Finding]) -> None:
        n_mono_hdr, n_stereo_hdr, current_offset = bank.sample_area_header()
        pcm_len = len(bank.pcm)
        samples = bank.samples()
        mono = samples[: L.NUM_SAMPLES_MONO]
        stereo = samples[L.NUM_SAMPLES_MONO :]

        # O(m) time, O(1) space — m = 256 mono slots
        occ_mono = sum(1 for s in mono if not s.empty)
        # O(t) time, O(1) space — t = 128 stereo slots
        occ_stereo = sum(1 for s in stereo if not s.empty)
        if occ_mono != n_mono_hdr:
            findings.append(
                Finding(
                    "warning",
                    "mono_count_mismatch",
                    f"header says {n_mono_hdr} mono samples but {occ_mono} slots occupied",
                )
            )
        if occ_stereo != n_stereo_hdr:
            findings.append(
                Finding(
                    "warning",
                    "stereo_count_mismatch",
                    f"header says {n_stereo_hdr} stereo samples but {occ_stereo} slots occupied",
                )
            )

        highest_end = 0
        # O(s) time, O(f) space — s = 384 sample slots, f = findings appended
        for s in samples:
            if s.empty:
                continue
            start, end = s.offset_start, s.offset_end
            highest_end = max(highest_end, end)
            if end < start:
                findings.append(
                    Finding(
                        "error",
                        "reversed_offsets",
                        f"sample slot {s.index} ({'stereo' if s.stereo else 'mono'}) "
                        f"end 0x{end:X} < start 0x{start:X}",
                    )
                )
            if end > pcm_len:
                findings.append(
                    Finding(
                        "error",
                        "offset_past_eof",
                        f"sample slot {s.index} ({'stereo' if s.stereo else 'mono'}) "
                        f"end 0x{end:X} exceeds PCM length 0x{pcm_len:X}",
                    )
                )
            # Sample-rate range is only trustworthy for mono (stereo rate offset
            # is unconfirmed -- see research/CODEC_FINDINGS_LOG.md).
            if not s.stereo:
                rate = s.sample_rate
                if not (L.MIN_IMPORT_RATE_HZ <= rate <= L.MAX_IMPORT_RATE_HZ):
                    findings.append(
                        Finding(
                            "warning",
                            "rate_out_of_range",
                            f"sample slot {s.index} rate {rate} Hz outside "
                            f"{L.MIN_IMPORT_RATE_HZ}-{L.MAX_IMPORT_RATE_HZ} Hz",
                        )
                    )

        if current_offset < highest_end:
            findings.append(
                Finding(
                    "error",
                    "current_offset_low",
                    f"currentOffset 0x{current_offset:X} below highest sample end "
                    f"0x{highest_end:X}",
                )
            )
        if current_offset > pcm_len:
            findings.append(
                Finding(
                    "warning",
                    "current_offset_past_eof",
                    f"currentOffset 0x{current_offset:X} exceeds PCM length 0x{pcm_len:X}",
                )
            )
        if pcm_len > L.MAX_SAMPLE_BYTES:
            findings.append(
                Finding(
                    "error",
                    "pcm_over_capacity",
                    f"PCM {pcm_len:,} B exceeds capacity {L.MAX_SAMPLE_BYTES:,} B",
                )
            )

    # O(p*k) time, O(f) space — p = patterns, k = 24 motion slots per pattern, f = findings
    def _check_motion(self, bank: Bank, findings: list[Finding]) -> None:
        if self._ops is None:
            return
        # O(p*k) time, O(f) space — p = patterns (256, or 0 in a PSG), k = 24 motion slots each, f = findings
        for p_idx, pattern in enumerate(bank.patterns()):
            # O(k) time, O(f) space — k = 24 motion slots in this pattern, f = findings appended
            for slot in pattern.motion_slots():
                if not slot.in_use:
                    continue
                if not self._ops.is_known(slot.target):
                    findings.append(
                        Finding(
                            "warning",
                            "unknown_motion_target",
                            f"pattern {p_idx} uses unknown motion target "
                            f"0x{slot.target:04X}",
                        )
                    )
