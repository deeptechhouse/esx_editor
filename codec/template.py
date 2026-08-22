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

from core.bank import Bank

# The blank template ships alongside this module as a data file.
TEMPLATE_FILENAME = "default.esx"


class BankTemplate:
    """Provides the embedded blank bank used by 'New bank'."""

    __slots__ = ()

    def blank_bytes(self) -> bytes:
        """Return the raw bytes of the bundled blank template."""
        raise NotImplementedError

    def new_bank(self) -> Bank:
        """Parse the bundled template into a fresh, editable Bank."""
        raise NotImplementedError
