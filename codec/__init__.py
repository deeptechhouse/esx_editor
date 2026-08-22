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
    WF1 contract freeze: signatures, docstrings, invariants, and exceptions are
    frozen; bodies raise NotImplementedError. Implementation is a later workflow.
"""

from .errors import CodecError, FormatError, RoundTripError

__all__ = ["CodecError", "FormatError", "RoundTripError"]
