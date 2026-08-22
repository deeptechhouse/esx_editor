"""
workspace — staging, quality budgeting, oversize policy, and temp lifecycle.

This package sits between the UI and the domain model: it turns dropped audio
files into committed samples (TDD §07), keeps the live 25 MB scoreboard exact
(TDD §06), applies the oversize policy (TDD §6.4), and owns the crash-safe temp
session directory. It depends on audio.ports and core, never on the UI.
"""

from .limits import Severity, Finding, WarningPolicy, SampleLimitPolicy

__all__ = ["Severity", "Finding", "WarningPolicy", "SampleLimitPolicy"]
