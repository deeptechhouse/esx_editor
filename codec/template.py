"""
codec.template — the blank bank that "New bank" loads (TDD §4.3).

WHY NOT ZEROS
    Five regions of the format are undecoded. Synthesising a bank from zeros
    risks a file the hardware rejects or silently misreads. "New" therefore
    means "load an embedded blank template a real machine wrote, then edit it",
    so unknown bytes always originate from a bank the ESX-1 itself produced.

HOW THE TEMPLATE IS MADE
    spike_a/make_template.py derives it from a user-authored bank by stripping
    every sample (copying the machine's own empty-slot bytes) and truncating the
    PCM region to the bare 16-byte trailer. It is bundled as data next to this
    module (see TEMPLATE_FILENAME). Korg factory audio is NEVER bundled.
"""

from __future__ import annotations

import os

from core.bank import Bank

# The blank template ships alongside this module as a data file.
TEMPLATE_FILENAME = "default.esx"


class BankTemplate:
    """Provides the embedded blank bank used by 'New bank'."""

    __slots__ = ()

    # O(1) time, O(1) space
    def _candidate_paths(self) -> tuple[str, ...]:
        """Where to look for the bundled blank template, in priority order.

        Bundled next to this module in a shipped build; falls back to the
        spike_a copy in a dev checkout. (.esx files are gitignored, so the
        template is bundled as build data rather than committed source.)
        """
        here = os.path.dirname(os.path.abspath(__file__))
        project = os.path.dirname(here)
        return (
            os.path.join(here, TEMPLATE_FILENAME),
            os.path.join(project, "spike_a", TEMPLATE_FILENAME),
        )

    # O(n) time, O(n) space — n = bytes in the template file
    def blank_bytes(self) -> bytes:
        """Return the raw bytes of the bundled blank template."""
        # O(n) time, O(n) space — n = bytes of the template read (at most 2 candidate paths are checked)
        for path in self._candidate_paths():
            if os.path.exists(path):
                with open(path, "rb") as f:
                    return f.read()
        from codec.errors import CodecError

        raise CodecError(
            f"blank template {TEMPLATE_FILENAME!r} not found in "
            f"{self._candidate_paths()}"
        )

    # O(n) time, O(n) space — n = bytes in the template image
    def new_bank(self) -> Bank:
        """Parse the bundled template into a fresh, editable Bank."""
        from codec.reader import BankReader

        return BankReader().read_auto(self.blank_bytes())
