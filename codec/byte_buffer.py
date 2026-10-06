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

    # O(n) time, O(n) space — n = bytes in data (copied unless already immutable bytes)
    def __init__(self, data: bytes):
        self._data = bytes(data)
        self._pos = 0

    # O(1) time, O(1) space
    @property
    def pos(self) -> int:
        return self._pos

    # O(1) time, O(1) space
    @property
    def size(self) -> int:
        return len(self._data)

    # O(1) time, O(1) space
    @property
    def remaining(self) -> int:
        return len(self._data) - self._pos

    # O(1) time, O(1) space
    def seek(self, pos: int) -> None:
        """Move the cursor to an absolute offset. Raises on out-of-range."""
        if not (0 <= pos <= len(self._data)):
            raise ValueError(f"seek {pos} out of range 0..{len(self._data)}")
        self._pos = pos

    # O(k) time, O(k) space — k = bytes requested (the slice is a copy)
    def read(self, n: int) -> bytes:
        """Read `n` raw bytes and advance the cursor."""
        if n < 0 or self._pos + n > len(self._data):
            raise ValueError(f"read {n} at {self._pos} exceeds size {len(self._data)}")
        out = self._data[self._pos : self._pos + n]
        self._pos += n
        return out

    # O(k) time, O(k) space — k = bytes requested (the slice is a copy)
    def read_at(self, pos: int, n: int) -> bytes:
        """Read `n` bytes at an absolute offset WITHOUT moving the cursor."""
        if pos < 0 or n < 0 or pos + n > len(self._data):
            raise ValueError(f"read_at {n} at {pos} exceeds size {len(self._data)}")
        return self._data[pos : pos + n]

    # O(1) time, O(1) space
    def read_u8(self) -> int:
        return self.read(1)[0]

    # O(1) time, O(1) space
    def read_u16(self) -> int:
        """Read a big-endian unsigned 16-bit integer."""
        return int.from_bytes(self.read(2), "big")

    # O(1) time, O(1) space
    def read_u32(self) -> int:
        """Read a big-endian unsigned 32-bit integer."""
        return int.from_bytes(self.read(4), "big")

    # O(k) time, O(k) space — k = field width in bytes
    def read_ascii(self, n: int) -> bytes:
        """Read a fixed-width raw name field (no decoding, no terminator)."""
        return self.read(n)


class ByteWriter:
    """An append-only growable buffer that mirrors ByteReader's encodings."""

    __slots__ = ("_buf",)

    # O(1) time, O(1) space
    def __init__(self) -> None:
        self._buf = bytearray()

    # O(1) time, O(1) space
    def __len__(self) -> int:
        return len(self._buf)

    # O(k) time, O(k) space — k = bytes appended (amortised, the bytearray grows geometrically)
    def write(self, data: bytes) -> None:
        """Append raw bytes."""
        self._buf += data

    # O(1) time, O(1) space
    def write_u8(self, value: int) -> None:
        if not (0 <= value <= 0xFF):
            raise ValueError(f"u8 {value} out of range")
        self._buf.append(value)

    # O(1) time, O(1) space
    def write_u16(self, value: int) -> None:
        """Append a big-endian unsigned 16-bit integer."""
        if not (0 <= value <= 0xFFFF):
            raise ValueError(f"u16 {value} out of range")
        self._buf += value.to_bytes(2, "big")

    # O(1) time, O(1) space
    def write_u32(self, value: int) -> None:
        """Append a big-endian unsigned 32-bit integer."""
        if not (0 <= value <= 0xFFFFFFFF):
            raise ValueError(f"u32 {value} out of range")
        self._buf += value.to_bytes(4, "big")

    # O(w) time, O(w) space — w = field width in bytes
    def write_ascii(self, raw: bytes, width: int, pad: int = 0x20) -> None:
        """Append a fixed-width name field, right-padding/truncating to `width`."""
        self._buf += raw[:width].ljust(width, bytes([pad]))

    # O(n) time, O(n) space — n = bytes written so far
    def getvalue(self) -> bytes:
        """Return an immutable copy of everything written so far."""
        return bytes(self._buf)
