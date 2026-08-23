"""
ui.wizard.wizard — the guided setup QWizard (TDD §09).

Eleven pages, every one skippable, driven by one shared WizardContext. The
wizard owns no bank state of its own: it renders and mutates the BankSession
the shell already owns, so closing it leaves the main window looking at exactly
what the wizard left behind.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QWizard

from ui.session import BankSession
from ui.wizard.context import WizardContext
from ui.wizard.pages import PAGE_CLASSES
from workspace.staging import StagingBank

#: TDD §09 fixes the flow at eleven screens.
PAGE_COUNT = len(PAGE_CLASSES)


class SetupWizard(QWizard):
    """The eleven-screen guided setup."""

    def __init__(
        self,
        session: BankSession,
        staging_bank: StagingBank | None = None,
        on_changed: Callable[[], None] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("ESX Bank Studio — guided setup")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage, True)
        self.setOption(QWizard.WizardOption.IndependentPages, False)
        self.resize(860, 660)

        self._ctx = WizardContext(session, staging_bank, on_changed)
        self._pages = [cls(self._ctx) for cls in PAGE_CLASSES]
        for page in self._pages:
            self.addPage(page)

    @property
    def context(self) -> WizardContext:
        return self._ctx

    def pages(self) -> tuple:
        """The eleven page objects, in flow order."""
        return tuple(self._pages)

    def page_at(self, index: int):
        """The page at a 0-based flow position."""
        return self._pages[index]

    def staging_bank(self) -> StagingBank | None:
        """The staging model the Add-samples page ended up rendering."""
        return self._ctx.staging_bank
