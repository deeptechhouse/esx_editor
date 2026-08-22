"""
codec.reader — bytes -> core.Bank.

CONTRACT
    read(b) parses a valid .esx image into a fully-populated core.Bank. Every
    region the model understands is decoded; every region it does not is stored
    verbatim on the Bank's RawRegions so the writer can replay it (TDD §4.1).

    Parsing NEVER validates coherence. A bank can be self-contradictory (e.g.
    sample headers pointing outside the file) and still parse successfully; that
    is codec.validator's job, deliberately kept separate (TDD §4.4).

TWO SAVE TYPES (TDD §2.5)
    Save All  -> full image with a sample area (>= SIZE_FILE_MIN).
    Save PSG  -> pattern/song/global only, no sample area; a much shorter file.
    The reader detects which it is and populates the Bank accordingly. A naive
    minimum-size check would wrongly reject a valid PSG file.
"""

from __future__ import annotations

from core.bank import Bank


class BankReader:
    """Parses .esx bytes into a core.Bank, preserving undecoded regions."""

    __slots__ = ()

    def read(self, data: bytes) -> Bank:
        """Parse a full .esx image (All-save) into a Bank.

        Raises codec.FormatError if the magic numbers, region sizes, or file
        length are structurally invalid.
        """
        raise NotImplementedError

    def read_psg(self, data: bytes) -> Bank:
        """Parse a Save-PSG image (no sample area) into a Bank.

        The returned Bank has empty sample slots and a flag marking it PSG so
        the writer emits the same short form.
        """
        raise NotImplementedError

    def read_auto(self, data: bytes) -> Bank:
        """Detect All vs PSG by structure and dispatch to the right parser."""
        raise NotImplementedError

    def read_file(self, path: str) -> Bank:
        """Convenience: read bytes from a path, then read_auto()."""
        raise NotImplementedError

    def is_psg(self, data: bytes) -> bool:
        """True if the bytes look like a Save-PSG (no sample area) file."""
        raise NotImplementedError
