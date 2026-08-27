"""
midi.mido_adapter — MidiInput backed by mido + python-rtmidi.

WHY mido AND NOT rtmidi DIRECTLY
    spike_midi/sysex_capture.py already chose mido, and one MIDI dependency
    across the project beats two. mido also normalises message parsing, so this
    adapter deals in named fields rather than raw status bytes.

RECEIVE ONLY, STRUCTURALLY
    Only `open_input` is ever called. There is no code path here that can
    transmit, which is a stronger guarantee than a comment asking nobody to.
"""

from __future__ import annotations

from midi.ports import ControlChange, MidiEvent, NoteOn

#: How many pending messages one poll will drain. A knob sweep can generate
#: hundreds; Learn only needs to know WHICH control moved, so draining a bounded
#: number keeps a fast sweep from stalling the GUI tick. Anything beyond this is
#: dropped on purpose — it is the same control, still.
MAX_PER_POLL = 64


class MidoMidiInput:
    """Polled MIDI input over mido's CoreMIDI/ALSA/WinMM backend."""

    __slots__ = ("_port", "_name")

    def __init__(self):
        self._port = None
        self._name = ""

    @property
    def available(self) -> bool:
        return True

    def ports(self) -> tuple[str, ...]:
        import mido

        try:
            return tuple(mido.get_input_names())
        except Exception:
            # A backend can fail at enumeration time (no CoreMIDI server, a
            # yanked USB device). No ports is the honest answer, not a crash.
            return ()

    def open(self, port: str) -> None:
        import mido

        self.close()
        self._port = mido.open_input(port)
        self._name = port

    def close(self) -> None:
        if self._port is not None:
            try:
                self._port.close()
            finally:
                self._port = None
                self._name = ""

    @property
    def is_open(self) -> bool:
        return self._port is not None

    @property
    def port_name(self) -> str:
        return self._name

    def poll(self) -> tuple[MidiEvent, ...]:
        if self._port is None:
            return ()
        found: list[MidiEvent] = []
        try:
            for message in self._port.iter_pending():
                if message.type == "control_change":
                    found.append(
                        ControlChange(message.channel, message.control, message.value)
                    )
                elif message.type == "note_on" and message.velocity > 0:
                    # Velocity 0 is a note-off on most controllers; capturing
                    # it would mean the pad's RELEASE set the mapping.
                    found.append(
                        NoteOn(message.channel, message.note, message.velocity)
                    )
                else:
                    continue
                if len(found) >= MAX_PER_POLL:
                    break
        except Exception:
            # A device unplugged mid-poll raises from the backend. Drop the
            # port rather than let a hardware event become a traceback.
            self.close()
        return tuple(found)
