"""
midi — MIDI input, behind a port, for MIDI Learn.

WHY A PORT AND NOT A DIRECT IMPORT
    Same reason as audio/: the app must run with no MIDI stack installed and
    say so, rather than fail to start. `mido` and `python-rtmidi` are optional
    extras (requirements-midi.txt); without them the Learn button is disabled
    and explains why, and every other feature is unaffected.

RECEIVE ONLY
    Nothing here transmits. A MIDI OUT could change the state of a connected
    instrument, and this app's entire promise is that it does not alter things
    the user did not ask it to. Learn listens; that is all it needs.
"""

from midi.ports import ControlChange, MidiInput

__all__ = ["ControlChange", "MidiInput"]
