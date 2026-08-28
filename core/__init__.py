"""
core — the pure-Python domain model for an ESX-1 bank.

WHAT LIVES HERE
    Plain objects with NO I/O: Bank and everything it contains. The whole model
    is unit-testable without touching a file.     The codec turns bytes into these
    objects and back; the UI edits them. Nothing here imports Qt or any codec
    *logic*; the only codec dependency is `codec.layout`, a pure declarative
    table of byte offsets that is the format's single source of truth (importing
    it here avoids duplicating offsets, per TDD §04.6).

DESIGN RULES (TDD §03, project encapsulation standard)
    - Fields are private (`_name`); behaviour is exposed through methods and
      @property. No public mutable state.
    - Collections are returned as defensive copies or immutable views.
    - Invariants are enforced in constructors and mutators, raising
      InvariantError (see core.errors) rather than silently accepting bad state.

CLASS MAP (TDD §3.1)
    Bank
     ├── GlobalParameters
     ├── Pattern x256  (PatternHeader, Part x16, FxUnit x3, MotionSlot x24)
     ├── Song x64      (name, tempo, an ordered chain of pattern indices)
     ├── SampleSlot x384  (256 mono + 128 stereo)
     └── RawRegions    (the unknown regions + anything undecoded)
"""

from .errors import InvariantError

__all__ = ["InvariantError"]
