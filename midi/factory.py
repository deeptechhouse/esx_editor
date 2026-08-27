"""
midi.factory — pick a MidiInput, or explain why there isn't one.

Mirrors audio.factory: probe once, cache the answer, and hand back a working
object either way so callers never branch on None.
"""

from __future__ import annotations

from functools import lru_cache

from midi.null import NullMidiInput
from midi.ports import MidiInput


@lru_cache(maxsize=1)
def _backend_error() -> str:
    """Empty when a MIDI backend imports and initialises; else why not.

    Cached because probing costs an import and a backend handshake, and the
    answer cannot change without restarting the app.
    """
    try:
        import mido
    except ImportError:
        return "mido is not installed (pip install -r requirements-midi.txt)"
    try:
        mido.get_input_names()
    except Exception as exc:
        return f"MIDI backend unavailable: {type(exc).__name__}: {exc}"
    return ""


def midi_input() -> MidiInput:
    """A live MidiInput, or a Null one carrying the reason it is not live."""
    error = _backend_error()
    if error:
        return NullMidiInput(error)
    from midi.mido_adapter import MidoMidiInput

    return MidoMidiInput()


def describe() -> str:
    """One line for the UI: what MIDI can do here right now."""
    error = _backend_error()
    if error:
        return f"MIDI Learn unavailable — {error}"
    names = midi_input().ports()
    if not names:
        return "MIDI Learn ready — no input device connected yet"
    return f"MIDI Learn ready — {len(names)} input(s): {', '.join(names)}"
