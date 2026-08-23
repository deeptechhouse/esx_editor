"""
ui.wizard.context — the one object every wizard page shares (TDD §09).

WHY A CONTEXT OBJECT
    A QWizard page must not reach sideways into other pages, and it must not
    own the bank. WizardContext is the small composition root the wizard hands
    to every page: the live BankSession (which is itself the only place codec/
    is imported), the staging model, and a callback the shell uses to refresh
    its chrome when a page changes the bank. Pages read it; they never build
    reader/writer/template themselves.
"""

from __future__ import annotations

from typing import Callable

from ui.session import BankSession
from workspace.staging import StagingBank


class WizardContext:
    """Shared, mutable state for one run of the guided setup."""

    __slots__ = ("_session", "_staging_bank", "_on_changed")

    def __init__(self, session: BankSession,
                 staging_bank: StagingBank | None = None,
                 on_changed: Callable[[], None] | None = None):
        self._session = session
        self._staging_bank = staging_bank
        self._on_changed = on_changed

    @property
    def session(self) -> BankSession:
        return self._session

    @property
    def staging_bank(self) -> StagingBank | None:
        """The staging model, or None until the Add-samples page builds one."""
        return self._staging_bank

    def adopt_staging_bank(self, bank: StagingBank) -> None:
        """Record the staging model the Add-samples page ended up rendering."""
        self._staging_bank = bank

    def staged_samples(self) -> tuple:
        """Every staged sample, or an empty tuple before staging exists."""
        if self._staging_bank is None:
            return ()
        return self._staging_bank.samples()

    def first_pattern(self):
        """Pattern 0 of the open bank, or None."""
        bank = self._session.bank
        if bank is None:
            return None
        patterns = bank.patterns()
        return patterns[0] if patterns else None

    def notify_changed(self) -> None:
        """Tell the shell the bank or its dirty flag moved."""
        if self._on_changed is not None:
            self._on_changed()
