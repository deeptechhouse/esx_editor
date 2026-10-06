"""
ui.session — composition root for the open bank (TDD §10.2).

Widgets never import codec/. This object is the one place the shell talks to
the reader/writer/template. It holds the live core.Bank, the path, and the
dirty flag, and exposes intent methods the menus call.
"""

from __future__ import annotations

from codec.errors import CodecError
from codec.reader import BankReader
from codec.template import BankTemplate
from codec.validator import BankValidator, ValidationReport
from codec.writer import BankWriter
from core.bank import Bank


class BankSession:
    """The currently-open bank and its on-disk path."""

    # O(1) time, O(1) space
    def __init__(self) -> None:
        self._bank: Bank | None = None
        self._path: str | None = None
        self._dirty = False
        self._reader = BankReader()
        self._writer = BankWriter()
        self._template = BankTemplate()
        self._validator = BankValidator()

    @property
    # O(1) time, O(1) space
    def bank(self) -> Bank | None:
        return self._bank

    @property
    # O(1) time, O(1) space
    def path(self) -> str | None:
        return self._path

    @property
    # O(1) time, O(1) space
    def dirty(self) -> bool:
        return self._dirty

    @property
    # O(1) time, O(1) space
    def is_open(self) -> bool:
        return self._bank is not None

    # O(1) time, O(1) space
    def mark_dirty(self) -> None:
        self._dirty = True

    # O(B) time, O(B) space — B = bytes in the embedded blank template
    def new_bank(self) -> Bank:
        """Load the embedded blank template. Raises CodecError if missing."""
        self._bank = self._template.new_bank()
        self._path = None
        self._dirty = True
        return self._bank

    # O(B) time, O(B) space — B = bytes in the bank file (fixed regions + up to 24 MiB of PCM)
    def open_path(self, path: str) -> Bank:
        """Parse a bank from disk and make it the session's open document.

        Clears the dirty flag: what was just read is by definition unmodified,
        so an open must not leave the window claiming unsaved changes.
        """
        self._bank = self._reader.read_file(path)
        self._path = path
        self._dirty = False
        return self._bank

    # O(B) time, O(B) space — B = bytes in the bank file (fixed regions + up to 24 MiB of PCM) (the validator copies the PCM)
    def validation_report(self):
        """Coherence report for the open bank, or None when nothing is open.

        Exposed so the shell can tell a user WHAT is incoherent instead of
        repeating the writer's refusal verbatim.
        """
        if self._bank is None:
            return None
        from codec.validator import BankValidator

        return BankValidator().validate(self._bank)

    # O(B) time, O(B) space — B = bytes in the bank file (fixed regions + up to 24 MiB of PCM) (validate, write, re-read verify)
    def save(self, path: str | None = None, *, allow_invalid: bool = False) -> str:
        """Write the bank. Uses `path` or the current path. Returns the path used."""
        if self._bank is None:
            raise CodecError("no bank is open")
        dest = path or self._path
        if not dest:
            raise CodecError("no path to save to")
        self._writer.write_file(self._bank, dest, allow_invalid=allow_invalid)
        self._path = dest
        self._dirty = False
        return dest

    # O(B) time, O(B) space — B = bytes in the bank file (fixed regions + up to 24 MiB of PCM) (the validator copies the PCM)
    def validate(self) -> ValidationReport:
        """Coherence-check the open bank (TDD §4.4).

        Kept here rather than in a view so no widget has to import codec/: the
        wizard's Validate & write screen asks the session, and the session is
        already the single composition root for reader/writer/template.
        Raises CodecError when nothing is open.
        """
        if self._bank is None:
            raise CodecError("no bank is open")
        return self._validator.validate(self._bank)

    # O(m) time, O(m) space — m = PCM bytes, copied only if pcm_used_bytes() raises (the normal path is constant)
    def pcm_used(self) -> int:
        if self._bank is None:
            return 0
        try:
            return self._bank.pcm_used_bytes()
        except Exception:
            return len(self._bank.pcm)
