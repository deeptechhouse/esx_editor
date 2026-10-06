"""
core.song — Song (528 B): name, tempo, and the ordered chain of patterns.

FORMAT (TDD §2.1)
    64 songs of 528 bytes at ADDR_SONG_DATA. A song arranges patterns into a
    performance: it is a *chain* — an ordered list of pattern indices the
    machine plays one after another.

WHAT IS DECODED, AND ON WHAT EVIDENCE
    Until WF17 every song block in every corpus bank was byte-identical and
    untouched, so only the name and tempo could be located. A bank saved on the
    hardware **with a song in it** settled the rest. Diffing it against the
    same bank saved without one changed exactly 20 bytes in the whole 8.5 MB
    image, all of them inside the song area:

        offset   default   with song   meaning
        0..7     8x 0x20   "bib1\\0\\0\\0\\0"  name (blank pads with SPACE,
                                        a named song pads with NUL)
        8..9     3C 00     3C 00       tempo, big-endian u16 at 1/128 BPM
        11       00        03          chain length MINUS ONE
        16..19   00 00     01 00 03 05 chain: one pattern index per position

    Two readings of that fit the bytes; this one is chosen on three grounds:

      * A chain position holding **0** proves indices are 0-based. If they were
        1-based, position 1 would decode to pattern -1.
      * `length - 1` is what makes the untouched default (byte 11 = 0) mean a
        1-position song, and an independent editor (SawLoop) reports exactly
        "Song Length 1" for those untouched songs. On the hardware a song
        always has at least one position, never zero.
      * The alternative — a lone unknown byte at 16 with the chain starting at
        17 — would make the default song zero-length, contradicting both.

    Positions past the chain length are ZERO in the saved bank, so shortening
    a chain zeroes its tail here too.

STILL UNDECODED
    Tempo Lock, Mute Hold and Next Song are named by SawLoop but sit in bytes
    that are zero both with and without a song, so they still raise. Bytes
    12..15 are likewise zero in every observation. They are never written — a
    Song patches only the fields above into the block it was read from, so an
    unknown byte is preserved by construction, not by remembering to.

    The area the TDD labelled "song events" is NOT song events: adding a
    four-pattern song changed nothing in it, and it is already non-zero in
    banks that contain no songs at all. See research/CODEC_FINDINGS_LOG.md.
"""

from __future__ import annotations

import struct
from collections.abc import Sequence

import codec.layout as L
from core.errors import InvariantError
from core.pattern import pattern_label

#: Offsets inside the 528-byte song block. See the module docstring for the
#: evidence behind each one.
SONG_OFF_NAME = 0
SONG_NAME_LEN = 8
SONG_OFF_TEMPO = 8
SONG_TEMPO_SCALE = 128.0
#: Chain length, stored MINUS ONE. Read as a big-endian u16 so the high byte is
#: written explicitly; it has never been observed non-zero, and cannot be for a
#: chain of at most 256 positions.
SONG_OFF_LENGTH = 10
#: First chain position. One byte per position, 0-based pattern index.
SONG_OFF_CHAIN = 16
#: The chain area runs to the end of the block; the length field caps it well
#: short of that, at one position per pattern in the bank.
MAX_CHAIN = L.NUM_PATTERNS
#: Blank songs pad the name with SPACE; the machine pads a named one with NUL.
NAME_PAD_BLANK = 0x20
NAME_PAD_NAMED = 0x00

MIN_TEMPO = 20.0
MAX_TEMPO = 300.0

_UNDECODED = (
    "{field} is not decoded. It is zero in every song block of every corpus "
    "bank AND in the one bank saved on hardware with a song in it, so nothing "
    "varies and nothing can be located. SawLoop names the field but reports "
    "the default for it too. See research/HARDWARE_CHECKLIST.md."
)


class Song:
    """One 528-byte song: a name, a tempo, and an ordered chain of patterns.

    Holds the block it was read from and patches only the decoded fields, so
    the undecoded bytes survive a read/modify/write untouched by construction.
    """

    __slots__ = ("_raw",)

    # O(B) time, O(B) space — B = 528 bytes per song block
    def __init__(self, raw: bytes):
        if len(raw) != L.CHUNK_SONG:
            raise InvariantError(
                f"a song block is {L.CHUNK_SONG} bytes, got {len(raw)}"
            )
        self._raw = bytearray(raw)

    # ---------------------------------------------------------------- name

    @property
    # O(1) time, O(1) space
    def name(self) -> str:
        raw = bytes(self._raw[SONG_OFF_NAME : SONG_OFF_NAME + SONG_NAME_LEN])
        return raw.decode("ascii", "replace").rstrip("\x00 ")

    # O(v) time, O(v) space — v = characters in the supplied name (encoded before truncation)
    def set_name(self, name: str) -> None:
        """Set the 8-character name, NUL-padded as the machine writes it."""
        encoded = name.encode("ascii", "replace")[:SONG_NAME_LEN]
        padded = encoded.ljust(SONG_NAME_LEN, bytes([NAME_PAD_NAMED]))
        self._raw[SONG_OFF_NAME : SONG_OFF_NAME + SONG_NAME_LEN] = padded

    # --------------------------------------------------------------- tempo

    @property
    # O(1) time, O(1) space
    def tempo(self) -> float:
        """Song tempo in BPM (big-endian u16 at 1/128)."""
        return struct.unpack_from(">H", self._raw, SONG_OFF_TEMPO)[0] / SONG_TEMPO_SCALE

    # O(1) time, O(1) space
    def set_tempo(self, bpm: float) -> None:
        if not (MIN_TEMPO <= bpm <= MAX_TEMPO):
            raise InvariantError(
                f"tempo {bpm} out of the machine's range {MIN_TEMPO}-{MAX_TEMPO} BPM"
            )
        stored = int(round(bpm * SONG_TEMPO_SCALE))
        struct.pack_into(">H", self._raw, SONG_OFF_TEMPO, stored)

    # --------------------------------------------------------------- chain

    @property
    # O(1) time, O(1) space
    def length(self) -> int:
        """Number of positions in the chain (stored minus one; never zero)."""
        return struct.unpack_from(">H", self._raw, SONG_OFF_LENGTH)[0] + 1

    @property
    # O(c) time, O(c) space — c = chain length (at most 256 positions)
    def chain(self) -> tuple[int, ...]:
        """The ordered pattern indices this song plays."""
        n = self.length
        start = SONG_OFF_CHAIN
        return tuple(self._raw[start : start + n])

    # O(c) time, O(c) space — c = chain length (at most 256 positions)
    def chain_labels(self) -> tuple[str, ...]:
        """The chain as the machine displays it: A.01 - D.64."""
        # O(c) time, O(c) space — c = chain length (at most 256 positions)
        return tuple(pattern_label(i) for i in self.chain)

    # O(c + B) time, O(c + B) space — c = positions supplied by the caller; B = 528 bytes per song block (the zero-padded chain tail)
    def set_chain(self, patterns: Sequence[int]) -> None:
        """Replace the chain. Zeroes the tail, as the hardware's save does.

        A song always plays at least one pattern, so an empty chain is refused
        rather than silently stored as the machine's 1-position default.
        """
        items = list(patterns)
        if not items:
            raise InvariantError(
                "a song plays at least one pattern; use clear() to blank the song"
            )
        if len(items) > MAX_CHAIN:
            raise InvariantError(
                f"a song chain holds at most {MAX_CHAIN} positions, got {len(items)}"
            )
        # O(c) time, O(1) space — c = positions supplied by the caller
        for index in items:
            if not (0 <= index < L.NUM_PATTERNS):
                raise InvariantError(
                    f"pattern index {index} out of range 0..{L.NUM_PATTERNS - 1}"
                )
        struct.pack_into(">H", self._raw, SONG_OFF_LENGTH, len(items) - 1)
        tail = L.CHUNK_SONG - SONG_OFF_CHAIN
        self._raw[SONG_OFF_CHAIN:] = bytes(items).ljust(tail, b"\x00")

    # O(c + B) time, O(c + B) space — c = chain length (list.insert shifts the tail); B = 528 bytes per song block
    def insert_pattern(self, position: int, index: int) -> None:
        chain = list(self.chain)
        chain.insert(position, index)
        self.set_chain(chain)

    # O(c + B) time, O(c + B) space — c = chain length; B = 528 bytes per song block
    def append_pattern(self, index: int) -> None:
        self.set_chain([*self.chain, index])

    # O(c + B) time, O(c + B) space — c = chain length (del shifts the tail); B = 528 bytes per song block
    def remove_position(self, position: int) -> None:
        """Drop one position from the chain.

        Refuses to remove the last one: the machine has no zero-length song,
        and storing one would encode as the 1-position default anyway — a
        silent lie about what the user asked for. clear() is the way to blank
        a song.
        """
        chain = list(self.chain)
        if not (0 <= position < len(chain)):
            raise InvariantError(
                f"position {position} out of range 0..{len(chain) - 1}"
            )
        if len(chain) == 1:
            raise InvariantError(
                "a song plays at least one pattern; use clear() to blank the song"
            )
        del chain[position]
        self.set_chain(chain)

    # O(c + B) time, O(c + B) space — c = chain length (pop/insert shift the tail); B = 528 bytes per song block
    def move_position(self, position: int, delta: int) -> None:
        """Move one position up or down the chain, clamped at the ends."""
        chain = list(self.chain)
        if not (0 <= position < len(chain)):
            raise InvariantError(
                f"position {position} out of range 0..{len(chain) - 1}"
            )
        target = max(0, min(len(chain) - 1, position + delta))
        chain.insert(target, chain.pop(position))
        self.set_chain(chain)

    # --------------------------------------------------------------- state

    @classmethod
    # O(B) time, O(B) space — B = 528 bytes per song block
    def default_bytes(cls) -> bytes:
        """The untouched block the machine ships: blank name, 120 BPM, 1 x A.01."""
        blk = bytearray(L.CHUNK_SONG)
        blk[SONG_OFF_NAME : SONG_OFF_NAME + SONG_NAME_LEN] = bytes(
            [NAME_PAD_BLANK] * SONG_NAME_LEN
        )
        struct.pack_into(">H", blk, SONG_OFF_TEMPO, int(120.0 * SONG_TEMPO_SCALE))
        return bytes(blk)

    @property
    # O(B) time, O(B) space — B = 528 bytes per song block
    def is_blank(self) -> bool:
        """True when the block is byte-for-byte the untouched default."""
        return bytes(self._raw) == self.default_bytes()

    # O(B) time, O(B) space — B = 528 bytes per song block
    def clear(self) -> None:
        """Reset to the untouched default, including any undecoded bytes."""
        self._raw = bytearray(self.default_bytes())

    @property
    # O(1) time, O(1) space
    def tempo_lock(self) -> bool:
        raise NotImplementedError(_UNDECODED.format(field="tempo_lock"))

    @property
    # O(1) time, O(1) space
    def mute_hold(self) -> bool:
        raise NotImplementedError(_UNDECODED.format(field="mute_hold"))

    @property
    # O(1) time, O(1) space
    def next_song(self) -> int:
        raise NotImplementedError(_UNDECODED.format(field="next_song"))

    # ------------------------------------------------------------ codec io

    # O(B) time, O(B) space — B = 528 bytes per song block
    def to_bytes(self) -> bytes:
        return bytes(self._raw)

    @classmethod
    # O(B) time, O(B) space — B = 528 bytes per song block
    def from_bytes(cls, raw: bytes) -> Song:
        return cls(raw)

    @classmethod
    # O(B) time, O(B) space — B = 528 bytes per song block
    def blank(cls) -> Song:
        return cls(cls.default_bytes())
