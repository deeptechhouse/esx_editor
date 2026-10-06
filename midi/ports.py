"""
midi.ports — the MIDI input contract, and the one message type Learn needs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class ControlChange:
    """One control-change message: which knob moved, on which channel, to what.

    Frozen because it is evidence of something that already happened; nothing
    downstream has any business editing it.
    """

    channel: int  # 0-15 as MIDI numbers them; displays are 1-16
    number: int  # 0-127, the CC this app assigns
    value: int  # 0-127

    # O(1) time, O(1) space
    @property
    def display_channel(self) -> int:
        """The channel as every hardware display shows it: 1-16, not 0-15."""
        return self.channel + 1


@dataclass(frozen=True)
class NoteOn:
    """One note-on: which key or pad was struck, on which channel, how hard.

    A note-on with velocity 0 is a note-OFF by MIDI convention and is never
    turned into one of these — Learn must not capture the release of a pad as
    though it were the strike.
    """

    channel: int  # 0-15 as MIDI numbers them; displays are 1-16
    number: int  # 0-127, the note this app assigns to a drum part
    velocity: int  # 1-127; zero would mean note-off

    # O(1) time, O(1) space
    @property
    def display_channel(self) -> int:
        return self.channel + 1


#: What poll() can return. Kept as a union rather than a common base class:
#: the two carry different payloads (a value versus a velocity) and callers
#: always want one kind or the other, never "an event".
MidiEvent = ControlChange | NoteOn


@runtime_checkable
class MidiInput(Protocol):
    """A source of incoming control-change messages.

    POLLED, NOT CALLBACK-DRIVEN. A callback from the MIDI backend arrives on
    the backend's own thread, and touching Qt widgets from a non-GUI thread is
    undefined behaviour that shows up as a crash weeks later. Polling from a
    Qt timer keeps everything on one thread; at a 30 ms tick nobody can move a
    knob fast enough to notice the difference.
    """

    # O(1) time, O(1) space
    @property
    def available(self) -> bool:
        """False when no MIDI stack is installed — the app still runs."""

    # O(q) time, O(q) space — q = attached MIDI input ports
    def ports(self) -> tuple[str, ...]:
        """Names of the MIDI inputs currently attached."""

    # O(1) time, O(1) space
    def open(self, port: str) -> None:
        """Start listening on a port. Re-opening switches ports."""

    # O(1) time, O(1) space
    def close(self) -> None:
        """Stop listening. Safe to call when nothing is open."""

    # O(1) time, O(1) space
    @property
    def is_open(self) -> bool: ...

    # O(p) time, O(p) space — p = messages pending since the last call (adapters may cap what they keep)
    def poll(self) -> tuple[MidiEvent, ...]:
        """Every control change and note-on since the last call, oldest first.

        Returns empty when nothing arrived or nothing is open. Never blocks.
        Callers filter for the kind they are learning — a CC row ignores pads,
        a drum-note row ignores knobs, so one armed row cannot be triggered by
        the wrong gesture.
        """
