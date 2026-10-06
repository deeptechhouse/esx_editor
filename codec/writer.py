"""
codec.writer — core.Bank -> bytes, with mandatory write-side safety.

THE GATE (TDD §4.2)
    writer(reader(b)) == b   for every valid bank, byte for byte.
    Undecoded regions are replayed verbatim from the Bank's RawRegions.

WRITE-SIDE SAFETY (TDD §4.5 — MANDATORY, never optional)
    write_file():
      1. Never write in place. Serialize to a temp file in the destination dir.
      2. Verify by re-reading: parse the temp file and re-serialize; the bytes
         must match what was intended.
      3. Atomic replace with os.replace only after verification passes.
      4. Keep the previous version as name.esx.bak.
      5. Refuse to write a bank that fails validate() unless explicitly overridden.
    A verification mismatch raises codec.RoundTripError and aborts before any
    existing file is touched.
"""

from __future__ import annotations

import os
import tempfile

import codec.layout as L
from codec.errors import CodecError, RoundTripError
from core.bank import SAVE_PSG, Bank


class BankWriter:
    """Serializes a core.Bank back to .esx bytes and writes it safely."""

    __slots__ = ()

    # O(n) time, O(n) space — n = bytes in the output image
    def write(self, bank: Bank) -> bytes:
        """Serialize a Bank to a complete .esx image (in memory).

        Emits an All-save or a PSG image depending on the Bank's save type.
        Guarantees byte-identity for any Bank produced by BankReader.
        """
        if bank.save_type == SAVE_PSG:
            return bank.raw_regions.get("psg_image")

        raw = bank.raw_regions
        out = bytearray()
        out += raw.get("magic")
        out += bank.globals.to_bytes()
        out += raw.get("unknown_1")
        # O(P) time, O(P) space — P = 256 patterns, each a fixed 4280-byte chunk
        for pattern in bank.patterns():
            out += pattern.to_bytes()
        out += raw.get("pre_songs")
        # O(G) time, O(G) space — G = 64 songs, each a fixed 528-byte block
        for song in bank.songs():
            out += song.to_bytes()
        out += raw.get("post_songs")
        out += raw.get("magic2")
        out += bank.sample_area.to_bytes()
        out += raw.get("hdr_gap")

        samples = bank.samples()
        # O(M) time, O(M) space — M = 256 mono headers, each 40 bytes
        for slot in samples[: L.NUM_SAMPLES_MONO]:
            out += slot.to_bytes()
        if raw.has("gap_hdr"):
            out += raw.get("gap_hdr")
        # O(S) time, O(S) space — S = 128 stereo headers, each 44 bytes
        for slot in samples[L.NUM_SAMPLES_MONO :]:
            out += slot.to_bytes()
        out += raw.get("tail")
        out += bank.pcm
        return bytes(out)

    # O(n) time, O(n) space — n = bytes in the bank image (validate, serialise, write, re-read, re-serialise: a constant number of passes)
    def write_file(
        self,
        bank: Bank,
        path: str,
        *,
        keep_backup: bool = True,
        allow_invalid: bool = False,
    ) -> None:
        """Write a Bank to `path` using the mandatory safety protocol.

        Refuses to write a bank that fails coherence validation unless
        `allow_invalid=True` (TDD §4.5). Raises codec.RoundTripError if re-read
        verification fails. The existing file is only replaced after both checks
        pass; the previous version is preserved as <path>.bak when keep_backup
        is True.
        """
        # 0. refuse to write an incoherent bank unless explicitly overridden.
        #    (Motion-target coherence needs an OperationTable and is checked by
        #    callers that have one; the sample/offset coherence checked here does
        #    not, so the default guard is meaningful on its own.)
        if not allow_invalid:
            from codec.validator import BankValidator

            report = BankValidator().validate(bank)
            if not report.ok:
                # O(f log f) time, O(f) space — f = error findings (deduplicated, then sorted for the message)
                codes = ", ".join(sorted({f.code for f in report.errors()}))
                raise CodecError(
                    f"refusing to write an incoherent bank "
                    f"({len(report.errors())} error(s): {codes}); "
                    f"pass allow_invalid=True to override"
                )

        data = self.write(bank)

        # 1. serialize to a temp file in the SAME directory (atomic-replace-safe)
        dest_dir = os.path.dirname(os.path.abspath(path))
        fd, tmp_created = tempfile.mkstemp(suffix=".esx.tmp", dir=dest_dir)
        # `tmp` is cleared once the file has been moved into place, so the
        # finally-block knows there is nothing left to clean up.
        tmp: str | None = tmp_created
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)

            # 2. verify by re-reading the temp file
            from codec.reader import BankReader

            reread = BankReader().read_auto(_read_bytes(tmp_created))
            if self.write(reread) != data:
                raise RoundTripError(
                    "re-read of the written file did not reproduce the intended "
                    "bytes; aborting before touching the existing file"
                )

            # 4. keep a backup of the previous version
            if keep_backup and os.path.exists(path):
                bak = path + ".bak"
                _replace(path, bak)

            # 3. atomic replace
            _replace(tmp_created, path)
            tmp = None
        finally:
            if tmp is not None and os.path.exists(tmp):
                os.unlink(tmp)


# O(n) time, O(n) space — n = bytes in the file
def _read_bytes(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


# O(1) time, O(1) space
def _replace(src: str, dst: str) -> None:
    try:
        os.replace(src, dst)
    except OSError as exc:  # pragma: no cover
        raise CodecError(f"atomic replace failed: {exc}") from exc
