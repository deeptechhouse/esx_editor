"""
core.song — Song (528 B) and SongEvent (8 B).

FORMAT (TDD §2.1)
    64 songs of 528 bytes, followed by a shared song-event area of 8-byte
    events (max 20,000 total across all songs). A song arranges patterns into a
    performance; events carry the per-step arrangement data.

READ-ONLY, DELIBERATELY
    The song area is still replayed VERBATIM by the writer, from the "mid" raw
    region. These objects are built for display only and have no setters: a
    Song you could edit but not save would be worse than none at all. Song
    editing waits on the format being decoded.

WHAT IS DECODED, AND ON WHAT EVIDENCE
    Only the first nine bytes of the 528 carry anything at all. Across all four
    corpus banks, every one of the 256 song blocks is byte-identical and the
    ONLY non-zero offsets are 0..8:

        0..7   name, 8 bytes, space-padded (0x20) — the same convention the
               pattern chunk and the sample header both use
        8..9   tempo, big-endian u16 at 1/128 BPM — 0x3C00 = 120.0

    The tempo reading is supported three ways: the bytes decode to exactly
    120.0 under the scale independently VERIFIED against 1,024 pattern headers;
    an independent editor (SawLoop) reports "Tempo 120.0" for all 64 songs of
    the same bank; and the field sits at the same offset relative to the name
    as the pattern header's tempo does. It is DOCUMENTED rather than VERIFIED,
    because every observed song is at the default and no varying value has been
    seen.

    Tempo Lock, Song Length, Mute Hold, Next Song and the event count are named
    by that editor but live somewhere in the 519 bytes that are zero in every
    bank, so they cannot be located. They raise.
"""

from __future__ import annotations

import struct
from collections.abc import Sequence

import codec.layout as L
from core.errors import InvariantError

#: Offsets inside the 528-byte song block. See the module docstring for the
#: evidence; only these two are decodable from the available data.
SONG_OFF_NAME = 0
SONG_NAME_LEN = 8
SONG_OFF_TEMPO = 8
SONG_TEMPO_SCALE = 128.0

_UNDECODED = (
    "{field} is not decoded: it lives somewhere in the 519 bytes of the song "
    "block that are ZERO in every one of the 256 song blocks across all four "
    "corpus banks. Nothing varies, so nothing can be located. Save one real "
    "song on the hardware and it falls out immediately — see "
    "research/HARDWARE_CHECKLIST.md item 2b."
)


class SongEvent:
    """One 8-byte song event.

    NOT DECODED. No corpus bank contains a single song event — an independent
    editor reports "There are no song events configured for this file" for the
    same bank — so there is no data to decode from.
    """

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
        """Song name, 8 bytes space-padded (DOCUMENTED — see module docstring)."""
        raw = bytes(self._raw[SONG_OFF_NAME : SONG_OFF_NAME + SONG_NAME_LEN])
        return raw.decode("ascii", "replace").rstrip("\x00 ")

    @property
    def tempo(self) -> float:
        """Song tempo in BPM, big-endian u16 at 1/128 (DOCUMENTED)."""
        raw = struct.unpack_from(">H", self._raw, SONG_OFF_TEMPO)[0]
        return raw / SONG_TEMPO_SCALE

    @property
    def is_blank(self) -> bool:
        """True when the block matches the untouched form the corpus shows."""
        return not any(self._raw[9:])

    @property
    def tempo_lock(self) -> bool:
        raise NotImplementedError(_UNDECODED.format(field="tempo_lock"))

    @property
    def length(self) -> int:
        raise NotImplementedError(_UNDECODED.format(field="length"))

    @property
    def mute_hold(self) -> bool:
        raise NotImplementedError(_UNDECODED.format(field="mute_hold"))

    @property
    def next_song(self) -> int:
        raise NotImplementedError(_UNDECODED.format(field="next_song"))

    def events(self) -> tuple[SongEvent, ...]:
        """Immutable view of this song's events."""
        return tuple(self._events)

    def to_bytes(self) -> bytes:
        """The verbatim 528 bytes. Present for inspection, not for writing.

        The writer emits the song area from the raw "mid" region, never from
        these objects, so this is a copy of what was read.
        """
        return bytes(self._raw)

    @classmethod
    def from_bytes(cls, raw: bytes) -> Song:
        if len(raw) != L.CHUNK_SONG:
            raise InvariantError(
                f"a song block is {L.CHUNK_SONG} bytes, got {len(raw)}"
            )
        return cls(raw)
