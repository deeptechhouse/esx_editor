"""
codec.byte_buffer — big-endian cursors over immutable and growable bytes.

WHY THIS EXISTS
    The .esx format is a fixed-layout image of big-endian integers at absolute
    offsets (TDD §02). Reading and writing it with bare struct calls scatters
    endianness and offset arithmetic across the codebase. These two small
    classes centralise it: `ByteReader` advances a cursor over a `bytes`;
    `ByteWriter` appends to a growable buffer. Both are big-endian by contract.

CONTRACT
    Every multi-byte integer is big-endian. Signed 16-bit values use two's
    complement. `read_ascii`/`write_ascii` never interpret bytes as text beyond
    fixed-width slicing -- name fields are raw bytes with no terminator.
"""

from __future__ import annotations


class ByteReader:
    """A forward/seekable cursor over an immutable byte image."""

    __slots__ = ("_data", "_pos")

    def __init__(self, data: bytes):
        self._data = bytes(data)
        self._pos = 0

    @property
    def pos(self) -> int:
        return self._pos

    @property
    def size(self) -> int:
        return len(self._data)

    @property
    def remaining(self) -> int:
        return len(self._data) - self._pos

    def seek(self, pos: int) -> None:
        """Move the cursor to an absolute offset. Raises on out-of-range."""
        raise NotImplementedError

    def read(self, n: int) -> bytes:
        """Read `n` raw bytes and advance the cursor."""
        raise NotImplementedError

    def read_at(self, pos: int, n: int) -> bytes:
        """Read `n` bytes at an absolute offset WITHOUT moving the cursor."""
        raise NotImplementedError

    def read_u8(self) -> int:
        raise NotImplementedError

    def read_u16(self) -> int:
        """Read a big-endian unsigned 16-bit integer."""
        raise NotImplementedError

    def read_u32(self) -> int:
        """Read a big-endian unsigned 32-bit integer."""
        raise NotImplementedError

    def read_ascii(self, n: int) -> bytes:
        """Read a fixed-width raw name field (no decoding, no terminator)."""
        raise NotImplementedError


class ByteWriter:
    """An append-only growable buffer that mirrors ByteReader's encodings."""

    __slots__ = ("_buf",)

    def __init__(self) -> None:
        self._buf = bytearray()

    def __len__(self) -> int:
        return len(self._buf)

    def write(self, data: bytes) -> None:
        """Append raw bytes."""
        raise NotImplementedError

    def write_u8(self, value: int) -> None:
        raise NotImplementedError

    def write_u16(self, value: int) -> None:
        """Append a big-endian unsigned 16-bit integer."""
        raise NotImplementedError

    def write_u32(self, value: int) -> None:
        """Append a big-endian unsigned 32-bit integer."""
        raise NotImplementedError

    def write_ascii(self, raw: bytes, width: int, pad: int = 0x20) -> None:
        """Append a fixed-width name field, right-padding/truncating to `width`."""
        raise NotImplementedError

    def getvalue(self) -> bytes:
        """Return an immutable copy of everything written so far."""
        return bytes(self._buf)
