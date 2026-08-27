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

    @property
    def display_channel(self) -> int:
        """The channel as every hardware display shows it: 1-16, not 0-15."""
        return self.channel + 1


@runtime_checkable
class MidiInput(Protocol):
    """A source of incoming control-change messages.

    POLLED, NOT CALLBACK-DRIVEN. A callback from the MIDI backend arrives on
    the backend's own thread, and touching Qt widgets from a non-GUI thread is
    undefined behaviour that shows up as a crash weeks later. Polling from a
    Qt timer keeps everything on one thread; at a 30 ms tick nobody can move a
    knob fast enough to notice the difference.
    """

    @property
    def available(self) -> bool:
        """False when no MIDI stack is installed — the app still runs."""

    def ports(self) -> tuple[str, ...]:
        """Names of the MIDI inputs currently attached."""

    def open(self, port: str) -> None:
        """Start listening on a port. Re-opening switches ports."""

    def close(self) -> None:
        """Stop listening. Safe to call when nothing is open."""

    @property
    def is_open(self) -> bool: ...

    def poll(self) -> tuple[ControlChange, ...]:
        """Every control change since the last call, oldest first.

        Returns empty when nothing arrived or nothing is open. Never blocks.
        """
