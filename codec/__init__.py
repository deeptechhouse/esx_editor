"""
codec — the .esx binary codec for ESX Bank Studio.

WHAT LIVES HERE
    Everything that turns a Korg ESX-1 `.esx` file into the in-memory
    `core.Bank` model and back again, plus the tools that reason about the
    bytes: the layout constants, a big-endian cursor, the reader, the writer,
    the coherence validator, the motion operation table, and the blank-bank
    template.

THE GOVERNING PRINCIPLE (TDD §4.1)
    Anything not decoded is preserved verbatim. The reader stores undecoded
    regions as raw bytes; the writer replays them untouched. This is what makes
    byte-identical round-tripping achievable before the format is fully
    understood, and it is why partial decoding is safe to ship.

THE CONTRACT (TDD §4.2)
    writer(reader(b)) == b   for every valid bank, byte for byte.

STATUS
    WF2/WF3: reader, writer, byte_buffer, operation_table, validator, and
    template are implemented. The round-trip gate (writer(reader(b)) == b) is
    green on the corpus and covered by tests. Some semantic field decoders and
    the sample-commit path remain deferred (documented as NotImplementedError).
"""

from .errors import CodecError, FormatError, RoundTripError

__all__ = ["CodecError", "FormatError", "RoundTripError"]
