"""
ui.wizard — the eleven-screen guided setup (TDD §09).

The wizard states the decision AND the reasoning on every screen, because the
ESX-1's own two-line display is what makes these choices opaque in the first
place. Every screen is skippable: `isComplete()` is True everywhere, so an
experienced user can walk straight to Validate & write.
"""

from .context import WizardContext
from .wizard import PAGE_COUNT, SetupWizard

__all__ = ["SetupWizard", "WizardContext", "PAGE_COUNT"]
