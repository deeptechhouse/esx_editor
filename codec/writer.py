"""
codec.writer — core.Bank -> bytes, with mandatory write-side safety.

THE GATE (TDD §4.2)
    writer(reader(b)) == b   for every valid bank, byte for byte.
    Undecoded regions are replayed verbatim from the Bank's RawRegions.

WRITE-SIDE SAFETY (TDD §4.5 — MANDATORY, never optional)
    write_file() must:
      1. Never write in place. Serialize to a temp file in the destination dir.
      2. Verify by re-reading: parse the temp file and compare to the model.
      3. Atomic replace with os.replace only after verification passes.
      4. Keep the previous version as name.esx.bak until the user confirms.
      5. Refuse to write a bank that fails validate() unless explicitly overridden.
    A verification mismatch raises codec.RoundTripError and aborts before any
    existing file is touched.
"""

from __future__ import annotations

from core.bank import Bank


class BankWriter:
    """Serializes a core.Bank back to .esx bytes and writes it safely."""

    __slots__ = ()

    def write(self, bank: Bank) -> bytes:
        """Serialize a Bank to a complete .esx image (in memory).

        Emits an All-save or a PSG image depending on the Bank's save type.
        Guarantees byte-identity for any Bank produced by BankReader.
        """
        raise NotImplementedError

    def write_file(self, bank: Bank, path: str,
                   *, keep_backup: bool = True,
                   allow_invalid: bool = False) -> None:
        """Write a Bank to `path` using the mandatory safety protocol.

        Raises codec.RoundTripError if the re-read verification fails, and
        codec.CodecError if the bank fails validation and allow_invalid is
        False. The existing file is only replaced after verification passes.
        """
        raise NotImplementedError
