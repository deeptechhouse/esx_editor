"""
midi.factory — pick a MidiInput, or explain why there isn't one.

Mirrors audio.factory: probe once, cache the answer, and hand back a working
object either way so callers never branch on None.
"""

from __future__ import annotations

import importlib.util
from functools import lru_cache

from midi.null import NullMidiInput
from midi.ports import MidiInput


# O(d) time, O(1) space — d = sys.path entries find_spec searches (first call only, cached after)
@lru_cache(maxsize=1)
def _backend_error() -> str:
    """Empty when a MIDI backend is INSTALLED; else why not.

    Deliberately checks for the module without importing it. Importing mido
    pulls in python-rtmidi, which opens a CoreMIDI client and starts its run
    loop — and that happens the moment a view is constructed, whether or not
    anyone ever presses Learn.

    That is not hypothetical: it deadlocked the test suite. Run alone, the
    librosa key tests take 11 seconds; run after a view had initialised
    CoreMIDI, one of them hung indefinitely. Two frameworks each starting
    threads at import time is a bad trade for a feature nobody has asked for
    yet. So: cheap existence check here, real import deferred to the first
    call that genuinely needs a device.
    """
    if importlib.util.find_spec("mido") is None:
        return "mido is not installed (pip install -r requirements-midi.txt)"
    return ""


# O(d) time, O(1) space — d = sys.path entries find_spec searches (first call only, cached after)
def midi_input() -> MidiInput:
    """A live MidiInput, or a Null one carrying the reason it is not live."""
    error = _backend_error()
    if error:
        return NullMidiInput(error)
    from midi.mido_adapter import MidoMidiInput

    return MidoMidiInput()


# O(d + q) time, O(q) space — d = sys.path entries searched (first call only), q = characters across attached input-port names
def describe() -> str:
    """One line for the UI: what MIDI can do here right now."""
    error = _backend_error()
    if error:
        return f"MIDI Learn unavailable — {error}"
    names = midi_input().ports()
    if not names:
        return "MIDI Learn ready — no input device connected yet"
    return f"MIDI Learn ready — {len(names)} input(s): {', '.join(names)}"
