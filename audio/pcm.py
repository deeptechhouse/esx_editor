"""
audio.pcm — turning decoded audio into the bytes the ESX-1 stores.

ENDIANNESS (VERIFIED 2026-08-23)
    The PCM region is 16-bit signed **big-endian**. WAV is little-endian, so
    every import must byte-swap. This is not taken on the documentation's word:
    reading a real sample both ways gives a lag-1 autocorrelation of +0.98
    big-endian versus +0.19 little-endian, and big-endian wins on 20 of 20
    samples tested. Audio is strongly correlated sample to sample; a wrong
    byte order turns it into something close to noise. Getting this backwards
    would produce a bank that loads and plays pure static.

WHY THE PURE FUNCTIONS ARE SEPARATE FROM THE ADAPTER
    `swap_endianness`, `fold_to_mono` and `split_stereo` are total functions on
    bytes with no I/O, so they can be property-tested exhaustively. The adapter
    is a thin shell that reads a file and calls them.
"""

from __future__ import annotations

import array
import wave

from core.errors import InvariantError

#: The file stores 16-bit frames; 8-bit input is zero-expanded on import.
BYTES_PER_SAMPLE = 2


def swap_endianness(data: bytes) -> bytes:
    """Swap every 16-bit word. Its own inverse.

    Used in both directions: little-endian WAV -> big-endian ESX on import,
    and back again on export.
    """
    if len(data) % BYTES_PER_SAMPLE:
        raise InvariantError(
            f"PCM is {len(data)} bytes; 16-bit frames are always an even count"
        )
    words = array.array("h")
    words.frombytes(data)
    words.byteswap()
    return words.tobytes()


def fold_to_mono(interleaved: bytes, channels: int) -> bytes:
    """Average interleaved native-endian 16-bit frames down to one channel.

    Averaging rather than dropping a channel: discarding the right channel
    loses anything panned there, which on a stereo drum loop can be half the
    kit. Averaging is what "fold to mono" means everywhere else in the app.
    """
    if channels < 1:
        raise InvariantError(f"channels must be >= 1, got {channels}")
    if channels == 1:
        return interleaved
    words = array.array("h")
    words.frombytes(interleaved)
    if len(words) % channels:
        raise InvariantError(
            f"{len(words)} samples do not divide into {channels} channels"
        )
    out = array.array("h", bytes(len(words) // channels * BYTES_PER_SAMPLE))
    for frame in range(len(words) // channels):
        base = frame * channels
        out[frame] = sum(words[base : base + channels]) // channels
    return out.tobytes()


def split_stereo(interleaved: bytes) -> tuple[bytes, bytes]:
    """De-interleave native-endian 16-bit stereo into (left, right).

    The ESX stores a stereo sample as two SEPARATE contiguous ranges, not as
    interleaved frames — hence the two channel-offset pairs in the header.
    """
    words = array.array("h")
    words.frombytes(interleaved)
    if len(words) % 2:
        raise InvariantError("stereo data must contain an even number of samples")
    left = array.array("h", words[0::2])
    right = array.array("h", words[1::2])
    return left.tobytes(), right.tobytes()


def expand_8bit(data: bytes) -> bytes:
    """Zero-expand unsigned 8-bit PCM to signed 16-bit (manual p.88).

    The hardware accepts 8-bit input and widens it on import; doing the same
    offline keeps the two paths equivalent.
    """
    out = array.array("h", bytes(len(data) * BYTES_PER_SAMPLE))
    for i, byte in enumerate(data):
        out[i] = (byte - 128) << 8
    return out.tobytes()


class WavPcmReader:
    """Reads a WAV file into ESX-ready big-endian PCM.

    Handles the two bit depths the hardware accepts (8 and 16) and folds or
    splits channels as asked. Anything else raises rather than guessing.
    """

    def read(
        self, path: str, *, channels: int = 1
    ) -> tuple[bytes | tuple[bytes, bytes], int, int]:
        """Return (pcm, source_rate, source_channels).

        `channels=1` returns one mono big-endian block. `channels=2` returns a
        (left, right) pair of big-endian blocks, which is the shape a stereo
        slot's two ranges need.
        """
        if channels not in (1, 2):
            raise InvariantError(f"channels must be 1 or 2, got {channels}")
        try:
            with wave.open(path, "rb") as w:
                width = w.getsampwidth()
                src_channels = w.getnchannels()
                rate = w.getframerate()
                frames = w.readframes(w.getnframes())
        except wave.Error as exc:
            raise InvariantError(f"{path!r} is not a readable WAV: {exc}") from exc

        if width == 1:
            frames = expand_8bit(frames)
        elif width != BYTES_PER_SAMPLE:
            raise InvariantError(
                f"{path!r} is {width * 8}-bit; the hardware accepts 8 or 16 "
                "(manual p.88)"
            )

        if channels == 1:
            mono = fold_to_mono(frames, src_channels)
            return swap_endianness(mono), rate, src_channels

        if src_channels == 1:
            # A mono source asked for as stereo: both channels are the same.
            block = swap_endianness(frames)
            return (block, block), rate, src_channels
        if src_channels != 2:
            raise InvariantError(
                f"{path!r} has {src_channels} channels; cannot make a stereo pair"
            )
        left, right = split_stereo(frames)
        return (swap_endianness(left), swap_endianness(right)), rate, src_channels
