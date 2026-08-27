"""
midi.null — the no-MIDI implementation.

Used when mido/python-rtmidi are absent, so the UI has an object to talk to
instead of a None it must special-case at every call site. It reports
`available = False`, which is what the Learn button reads to disable itself.
"""

from __future__ import annotations

from midi.ports import ControlChange


class NullMidiInput:
    """Satisfies MidiInput, receives nothing, never raises."""

    __slots__ = ("_reason",)

    def __init__(self, reason: str = "no MIDI backend installed"):
        self._reason = reason

    @property
    def available(self) -> bool:
        return False

    @property
    def reason(self) -> str:
        """Why MIDI is unavailable, in words a user can act on."""
        return self._reason

    def ports(self) -> tuple[str, ...]:
        return ()

    def open(self, port: str) -> None:
        return None

    def close(self) -> None:
        return None

    @property
    def is_open(self) -> bool:
        return False

    def poll(self) -> tuple[ControlChange, ...]:
        return ()
