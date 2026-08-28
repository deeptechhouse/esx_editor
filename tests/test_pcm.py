"""
PCM conversion — the byte order that decides whether a bank plays or hisses.

The ESX stores 16-bit signed BIG-endian; WAV is little-endian. Getting this
backwards produces a file that loads fine, validates fine, round-trips fine —
and plays static. There is no test downstream of here that would catch it,
which is why the endianness has its own evidence-based test rather than a
comment citing the spec.
"""

from __future__ import annotations

import array
import struct
import wave

import pytest
from hypothesis import given
from hypothesis import strategies as st

from audio.pcm import (
    WavPcmReader,
    expand_8bit,
    fold_to_mono,
    split_stereo,
    swap_endianness,
)
from core.errors import InvariantError

SAMPLES = st.lists(
    st.integers(min_value=-32768, max_value=32767), min_size=0, max_size=200
)


def write_wav(path, samples, *, channels=1, rate=44100, width=2):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        if width == 2:
            w.writeframes(array.array("h", samples).tobytes())
        else:
            w.writeframes(bytes(samples))
    return str(path)


# -- pure functions -----------------------------------------------------------
@given(values=SAMPLES)
def test_swap_endianness_is_its_own_inverse(values: list[int]) -> None:
    data = array.array("h", values).tobytes()
    assert swap_endianness(swap_endianness(data)) == data


@given(values=SAMPLES)
def test_swap_endianness_produces_big_endian_words(values: list[int]) -> None:
    data = array.array("h", values).tobytes()
    swapped = swap_endianness(data)
    if values:
        assert struct.unpack(f">{len(values)}h", swapped) == tuple(values) or True
        # Read back big-endian and compare to the native-order originals.
        assert list(struct.unpack(f">{len(values)}h", swapped)) == list(
            array.array("h", data)
        )


def test_swap_endianness_refuses_an_odd_length() -> None:
    with pytest.raises(InvariantError, match="even"):
        swap_endianness(b"\x01\x02\x03")


@given(left=SAMPLES, right=SAMPLES)
def test_split_stereo_deinterleaves(left: list[int], right: list[int]) -> None:
    n = min(len(left), len(right))
    left, right = left[:n], right[:n]
    interleaved = array.array(
        "h", [v for pair in zip(left, right, strict=False) for v in pair]
    ).tobytes()
    got_l, got_r = split_stereo(interleaved)
    assert list(array.array("h", got_l)) == left
    assert list(array.array("h", got_r)) == right


def test_split_stereo_refuses_an_odd_sample_count() -> None:
    with pytest.raises(InvariantError, match="even"):
        split_stereo(array.array("h", [1, 2, 3]).tobytes())


def test_fold_to_mono_averages_rather_than_dropping_a_channel() -> None:
    """Dropping the right channel loses whatever was panned there."""
    interleaved = array.array("h", [100, 200, -100, -300]).tobytes()
    folded = fold_to_mono(interleaved, 2)
    assert list(array.array("h", folded)) == [150, -200]


@given(values=SAMPLES)
def test_fold_to_mono_is_identity_for_one_channel(values: list[int]) -> None:
    data = array.array("h", values).tobytes()
    assert fold_to_mono(data, 1) == data


def test_fold_to_mono_refuses_a_ragged_frame_count() -> None:
    with pytest.raises(InvariantError, match="divide"):
        fold_to_mono(array.array("h", [1, 2, 3]).tobytes(), 2)


def test_fold_to_mono_refuses_zero_channels() -> None:
    with pytest.raises(InvariantError, match="channels"):
        fold_to_mono(b"", 0)


def test_expand_8bit_centres_and_widens() -> None:
    """8-bit input is unsigned and centred on 128 (manual p.88)."""
    widened = array.array("h")
    widened.frombytes(expand_8bit(bytes([0, 128, 255])))
    assert list(widened) == [-32768, 0, 32512]


# -- the reader ---------------------------------------------------------------
def test_reader_returns_big_endian_bytes(tmp_path) -> None:
    values = [0, 1, 256, -1, 32767, -32768]
    path = write_wav(tmp_path / "be.wav", values)
    pcm, rate, channels = WavPcmReader().read(path, channels=1)
    assert rate == 44100 and channels == 1
    assert list(struct.unpack(f">{len(values)}h", pcm)) == values
    # ...and NOT little-endian, unless the values happen to be palindromic.
    assert list(struct.unpack(f"<{len(values)}h", pcm)) != values


def test_reader_folds_a_stereo_source_to_mono(tmp_path) -> None:
    path = write_wav(tmp_path / "st.wav", [100, 200, -100, -300], channels=2)
    pcm, _rate, channels = WavPcmReader().read(path, channels=1)
    assert channels == 2
    assert list(struct.unpack(">2h", pcm)) == [150, -200]


def test_reader_splits_a_stereo_source_into_two_blocks(tmp_path) -> None:
    """A stereo slot stores two SEPARATE ranges, not interleaved frames."""
    path = write_wav(tmp_path / "st2.wav", [1, -1, 2, -2, 3, -3], channels=2)
    (left, right), _rate, channels = WavPcmReader().read(path, channels=2)
    assert channels == 2
    assert list(struct.unpack(">3h", left)) == [1, 2, 3]
    assert list(struct.unpack(">3h", right)) == [-1, -2, -3]


def test_reader_duplicates_a_mono_source_asked_for_as_stereo(tmp_path) -> None:
    path = write_wav(tmp_path / "mono.wav", [5, 6, 7])
    (left, right), _rate, channels = WavPcmReader().read(path, channels=2)
    assert channels == 1
    assert left == right


def test_reader_widens_8_bit_input(tmp_path) -> None:
    path = write_wav(tmp_path / "eight.wav", [0, 128, 255], width=1)
    pcm, _rate, _channels = WavPcmReader().read(path, channels=1)
    assert list(struct.unpack(">3h", pcm)) == [-32768, 0, 32512]


def test_reader_refuses_an_unsupported_bit_depth(tmp_path) -> None:
    path = str(tmp_path / "24.wav")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(3)
        w.setframerate(44100)
        w.writeframes(b"\x00" * 9)
    with pytest.raises(InvariantError, match="24-bit"):
        WavPcmReader().read(path)


def test_reader_refuses_a_non_wav(tmp_path) -> None:
    bad = tmp_path / "no.wav"
    bad.write_bytes(b"not a wav at all")
    with pytest.raises(InvariantError, match="not a readable WAV"):
        WavPcmReader().read(str(bad))


def test_reader_refuses_an_odd_channel_request(tmp_path) -> None:
    path = write_wav(tmp_path / "ok.wav", [1, 2])
    with pytest.raises(InvariantError, match="1 or 2"):
        WavPcmReader().read(path, channels=3)


# -- the evidence for big-endian, against real audio --------------------------
@pytest.mark.corpus
def test_real_bank_pcm_is_big_endian(bank) -> None:
    """Read a real sample both ways; audio is correlated, wrong-endian is not.

    This is the test that would catch a byte-order regression. Nothing
    downstream would: a little-endian bank still round-trips and still
    validates. It just plays static.
    """
    occupied = [s for s in bank.samples() if not s.empty]
    pcm = bank.pcm
    tested = wins = 0
    for slot in occupied[:12]:
        chunk = bytes(pcm[slot.offset_start : slot.offset_end])[:40000]
        count = len(chunk) // 2
        if count < 500:
            continue
        tested += 1
        be = struct.unpack(f">{count}h", chunk[: count * 2])
        le = struct.unpack(f"<{count}h", chunk[: count * 2])
        if _lag1(be) > _lag1(le):
            wins += 1
    if tested == 0:
        pytest.skip("no sample long enough to measure")
    assert wins == tested, f"big-endian won only {wins}/{tested}"


def _lag1(values) -> float:
    mean = sum(values) / len(values)
    num = sum(
        (values[i] - mean) * (values[i + 1] - mean) for i in range(len(values) - 1)
    )
    den = sum((v - mean) ** 2 for v in values)
    return num / den if den else 0.0
