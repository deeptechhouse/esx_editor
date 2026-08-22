"""
workspace.errors — exceptions raised by the staging/budget layer.

Separated from core.InvariantError (illegal domain state) and codec.FormatError
(unparseable bytes): a staging error means "this candidate cannot enter the
bank", not "the bank itself is corrupt".
"""

from __future__ import annotations

from typing import Sequence


class WorkspaceError(Exception):
    """Base class for every error originating in the workspace layer."""


class StagingBlockedError(WorkspaceError):
    """A candidate sample hit a BLOCK-level limit and was not added.

    Carries the findings so the UI can present the concrete fixes (fold to
    mono, drop a tier, trim) rather than a generic 'too big'.
    """

    def __init__(self, findings: Sequence[object], message: str | None = None):
        self.findings = tuple(findings)
        codes = ", ".join(
            getattr(f, "code", "?") for f in self.findings
            if getattr(f, "level", None) == "block")
        super().__init__(message or f"sample blocked ({codes})")
