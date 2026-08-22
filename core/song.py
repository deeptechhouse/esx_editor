"""
core.song — Song (528 B) and SongEvent (8 B).

FORMAT (TDD §2.1)
    64 songs of 528 bytes, followed by a shared song-event area of 8-byte
    events (max 20,000 total across all songs). A song arranges patterns into a
    performance; events carry the per-step arrangement data.
"""

from __future__ import annotations

from typing import Sequence


class SongEvent:
    """One 8-byte song event."""

    __slots__ = ("_raw",)

    def __init__(self, raw: bytes):
        self._raw = bytes(raw)

    @property
    def raw(self) -> bytes:
        return self._raw

    def to_bytes(self) -> bytes:
        raise NotImplementedError


class Song:
    """One 528-byte song plus its ordered events."""

    __slots__ = ("_raw", "_events")

    def __init__(self, raw: bytes, events: Sequence[SongEvent] = ()):
        self._raw = bytearray(raw)
        self._events = list(events)

    @property
    def name(self) -> str:
        raise NotImplementedError

    def events(self) -> tuple[SongEvent, ...]:
        """Immutable view of this song's events."""
        return tuple(self._events)

    def to_bytes(self) -> bytes:
        raise NotImplementedError

    @classmethod
    def from_bytes(cls, raw: bytes) -> "Song":
        raise NotImplementedError
