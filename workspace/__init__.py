"""
workspace — staging, quality budgeting, oversize policy, and temp lifecycle.

This package sits between the UI and the domain model: it turns dropped audio
files into committed samples (TDD §07), keeps the live 25 MB scoreboard exact
(TDD §06), applies the oversize policy (TDD §6.4), and owns the crash-safe temp
session directory. It depends on audio.ports and core, never on the UI.
"""

from .budget import CAPACITY, DEFAULT_RATE, TIERS, BudgetCalculator, BudgetItem
from .errors import StagingBlockedError, WorkspaceError
from .limits import Finding, SampleLimitPolicy, Severity, WarningPolicy
from .naming import classical, pack_slot_name, staging_filename
from .staging import SessionWorkspace, StagingBank, StagingSample

__all__ = [
    "WorkspaceError",
    "StagingBlockedError",
    "Severity",
    "Finding",
    "WarningPolicy",
    "SampleLimitPolicy",
    "BudgetCalculator",
    "BudgetItem",
    "TIERS",
    "DEFAULT_RATE",
    "CAPACITY",
    "pack_slot_name",
    "staging_filename",
    "classical",
    "SessionWorkspace",
    "StagingSample",
    "StagingBank",
]
