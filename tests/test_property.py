"""
Property tests — invariants that must hold for EVERY input, not just examples.

WHY THESE PARTICULAR PROPERTIES
    The example-based suite proves the codec works on the inputs we thought of.
    These prove the parts where a missed edge case corrupts a bank: the motion
    encodings (a wrong snap writes a value the hardware never produces), the
    budget arithmetic (an off-by-two breaks the allocation rule and overlaps two
    samples' PCM), and the name packing (a 7- or 9-byte name shifts every field
    after it in the header).
"""

from __future__ import annotations

import math

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

import codec.layout as L
from codec.byte_buffer import ByteReader, ByteWriter
from core.motion import MotionDomain, MotionSlot
from core.pattern import Pattern
from core.sample import SampleSlot
from workspace.budget import CAPACITY, BudgetCalculator
from workspace.naming import CAMELOT, SLOT_NAME_LEN, classical, pack_slot_name


#: One synthetic pattern chunk, built once. Building a whole 2.4 MB bank per
#: hypothesis example blows the deadline for no extra coverage.
def _pattern_chunk() -> bytes:
    from tests.synthetic import build

    return build(pcm_bytes=64)[
        L.ADDR_PATTERN_DATA : L.ADDR_PATTERN_DATA + L.CHUNK_PATTERN
    ]


_PATTERN_CHUNK = _pattern_chunk()

#: Option counts the verified rule i * ceil(128/N) can actually express.
#: Everything else is refused by MotionDomain (see the N=17 -> 128 collision).
EXPRESSIBLE = tuple(n for n in range(2, 65) if (-(-128 // n)) * (n - 1) <= 127)
OPTION_COUNTS = st.sampled_from(EXPRESSIBLE)
#: The ones the shipped 313-target table actually uses.
REAL_OPTION_COUNTS = st.sampled_from([2, 3, 4])
STORED = st.integers(min_value=0, max_value=127)
STEPS = st.integers(min_value=0, max_value=L.NUM_MOTION_STEPS - 1)


# -- motion domains -----------------------------------------------------------
@given(n=OPTION_COUNTS, index=st.integers(min_value=0, max_value=63))
def test_discrete_encode_decode_round_trips(n: int, index: int) -> None:
    """decode(encode(i)) == i for every legal option index."""
    assume(index < n)
    dom = MotionDomain.discrete(n)
    assert dom.decode(dom.encode(index)) == index


@given(n=OPTION_COUNTS)
def test_discrete_encoding_matches_the_verified_rule(n: int) -> None:
    """Stored bytes are i * ceil(128/N) — knob positions, never ordinals."""
    dom = MotionDomain.discrete(n)
    step = math.ceil(128 / n)
    assert dom.legal_values() == tuple(i * step for i in range(n))
    # The three encodings proven against real banks in Spike A.
    assert MotionDomain.discrete(2).legal_values() == (0, 64)
    assert MotionDomain.discrete(3).legal_values() == (0, 43, 86)
    assert MotionDomain.discrete(4).legal_values() == (0, 32, 64, 96)


@given(n=OPTION_COUNTS, raw=st.integers(min_value=-500, max_value=500))
def test_snap_always_lands_on_a_legal_value(n: int, raw: int) -> None:
    """Snapping any integer — including out-of-range — yields a legal byte."""
    dom = MotionDomain.discrete(n)
    snapped = dom.snap_stored(raw)
    assert snapped in dom.legal_values()
    assert 0 <= snapped <= 127
    assert snapped != L.MOTION_VALUE_DISABLED, "Disabl is a state, not a value"


@given(n=st.sampled_from([n for n in range(2, 65) if (-(-128 // n)) * (n - 1) > 127]))
def test_inexpressible_option_counts_are_refused_not_guessed(n: int) -> None:
    """N=17 would store the top option as 128 — the Disabl sentinel.

    The i * ceil(128/N) rule is PROVEN only for N = 2, 3, 4. Extrapolating it
    far enough produces bytes outside the knob range, and for twelve values of
    N produces exactly 128, which would silently mean "do not update". The
    domain refuses rather than emit a byte the hardware never writes.
    """
    from core.errors import InvariantError

    with pytest.raises(InvariantError):
        MotionDomain.discrete(n)


@given(n=REAL_OPTION_COUNTS)
def test_no_legal_value_can_ever_be_the_disabl_sentinel(n: int) -> None:
    dom = MotionDomain.discrete(n)
    assert L.MOTION_VALUE_DISABLED not in dom.legal_values()
    assert max(dom.legal_values()) <= 127


@given(n=OPTION_COUNTS, raw=STORED)
def test_snap_is_idempotent(n: int, raw: int) -> None:
    dom = MotionDomain.discrete(n)
    once = dom.snap_stored(raw)
    assert dom.snap_stored(once) == once


@given(n=OPTION_COUNTS, raw=STORED)
def test_snap_picks_the_nearest_legal_value(n: int, raw: int) -> None:
    dom = MotionDomain.discrete(n)
    snapped = dom.snap_stored(raw)
    best = min(abs(v - raw) for v in dom.legal_values())
    assert abs(snapped - raw) == best


@given(raw=st.integers(min_value=-500, max_value=500))
def test_continuous_snap_clamps_without_snapping(raw: int) -> None:
    dom = MotionDomain.continuous()
    assert dom.snap_stored(raw) == max(0, min(127, raw))


# -- motion slots -------------------------------------------------------------
@given(step=STEPS, stored=STORED, length=st.integers(min_value=1, max_value=128))
def test_write_stored_respects_the_length_mask(
    step: int, stored: int, length: int
) -> None:
    """A write beyond the pattern length must leave the byte as Disabl."""
    assume(stored != L.MOTION_VALUE_DISABLED)
    dom = MotionDomain.continuous()
    slot = MotionSlot.empty()
    slot.write_stored(step, stored, dom, length=length)
    if step < length:
        assert slot.get_step(step) == stored
        assert not slot.is_disabled(step)
    else:
        assert slot.is_disabled(step)


@given(step=STEPS)
def test_clearing_a_step_restores_the_disabl_sentinel(step: int) -> None:
    dom = MotionDomain.continuous()
    slot = MotionSlot.empty()
    slot.write_stored(step, 100, dom, length=128)
    assert slot.get_step(step) == 100
    slot.write_stored(step, None, dom, length=128)
    assert slot.is_disabled(step)
    assert slot.get_step(step) == L.MOTION_VALUE_DISABLED


@given(target=st.integers(min_value=0, max_value=0xFFFE))
def test_slot_bytes_round_trip(target: int) -> None:
    """to_bytes/from_bytes are exact inverses for any target and value set."""
    dom = MotionDomain.continuous()
    slot = MotionSlot.empty()
    slot.set_target(target)
    for i in range(0, 128, 7):
        slot.write_stored(i, i % 128, dom, length=128)
    raw = slot.to_bytes()
    assert len(raw) == L.CHUNK_PARAMETERS_MOTION == 130
    again = MotionSlot.from_bytes(raw)
    assert again.to_bytes() == raw
    assert again.target == target


def test_empty_slot_is_the_unused_form() -> None:
    """An unused slot is target 0xFFFF with all 128 values Disabl."""
    raw = MotionSlot.empty().to_bytes()
    assert raw[:2] == b"\xff\xff"
    assert set(raw[2:]) == {L.MOTION_VALUE_DISABLED}
    assert not MotionSlot.from_bytes(raw).in_use


# -- budget arithmetic --------------------------------------------------------
@given(
    n=st.integers(min_value=0, max_value=1 << 30),
    boundary=st.sampled_from([2, 4, 8, 16]),
)
def test_align_up_is_the_smallest_aligned_value_at_or_above_n(
    n: int, boundary: int
) -> None:
    out = BudgetCalculator.align_up(n, boundary)
    assert out % boundary == 0
    assert out >= n
    assert out - n < boundary


@given(
    duration=st.floats(min_value=0.0, max_value=280.0, allow_nan=False),
    rate=st.integers(min_value=L.MIN_IMPORT_RATE_HZ, max_value=L.MAX_IMPORT_RATE_HZ),
    channels=st.integers(min_value=1, max_value=2),
)
def test_cost_follows_the_verified_allocation_rule(
    duration: float, rate: int, channels: int
) -> None:
    """cost = align_up(frames * 2 * channels + 2, 4) — measured on 279 samples."""
    calc = BudgetCalculator()
    cost = calc.cost_bytes(duration, rate, channels)
    frames = int(round(duration * rate))
    assert cost == BudgetCalculator.align_up(frames * 2 * channels + 2, 4)
    assert cost % 4 == 0
    assert cost >= 4


@given(
    a=st.floats(min_value=0.0, max_value=100.0, allow_nan=False),
    b=st.floats(min_value=0.0, max_value=100.0, allow_nan=False),
    rate=st.sampled_from([22050, 32000, 44100, 48000]),
)
def test_cost_is_monotonic_in_duration(a: float, b: float, rate: int) -> None:
    calc = BudgetCalculator()
    lo, hi = min(a, b), max(a, b)
    assert calc.cost_bytes(lo, rate, 1) <= calc.cost_bytes(hi, rate, 1)


@given(rate=st.sampled_from([22050, 32000, 44100, 48000]), channels=st.integers(1, 2))
def test_seconds_available_fits_inside_capacity(rate: int, channels: int) -> None:
    calc = BudgetCalculator()
    seconds = calc.seconds_available(rate, channels)
    assert calc.cost_bytes(seconds, rate, channels) <= CAPACITY + 4


# -- naming -------------------------------------------------------------------
NAME_TEXT = st.text(
    alphabet=st.characters(min_codepoint=32, max_codepoint=126), min_size=0, max_size=60
)


@given(basename=NAME_TEXT, style=st.sampled_from(["short", "long", "camelot"]))
def test_packed_name_is_always_exactly_eight_characters(
    basename: str, style: str
) -> None:
    """The header field is 8 bytes; a 7- or 9-char name shifts every later field."""
    assert len(pack_slot_name(basename, None, style)) == SLOT_NAME_LEN == 8


@given(
    basename=NAME_TEXT,
    camelot=st.sampled_from(sorted(CAMELOT)),
    style=st.sampled_from(["short", "long", "camelot"]),
)
def test_packed_name_with_a_key_is_still_eight(
    basename: str, camelot: str, style: str
) -> None:
    packed = pack_slot_name(basename, camelot, style)
    assert len(packed) == SLOT_NAME_LEN
    assert packed[0] == camelot[-1].lower()
    assert packed[1:3] == camelot[:-1].zfill(2)


@given(camelot=st.sampled_from(sorted(CAMELOT)))
def test_camelot_and_classical_are_a_bijection(camelot: str) -> None:
    """Both notations derive from one estimate, so they cannot disagree."""
    short = classical(camelot, "short")
    long_ = classical(camelot, "long")
    minor = camelot.endswith("A")
    assert short.endswith("m") is minor
    assert long_.endswith("min" if minor else "maj")
    assert long_.startswith(short[:-1] if minor else short)


@given(bad=st.text(min_size=1, max_size=5))
def test_unknown_camelot_raises_rather_than_packing_garbage(bad: str) -> None:
    assume(bad not in CAMELOT)
    with pytest.raises(ValueError):
        pack_slot_name("anything", bad)


# -- name fields in the file --------------------------------------------------
@given(name=NAME_TEXT)
def test_sample_name_always_occupies_exactly_eight_bytes(name: str) -> None:
    raw = bytearray(L.CHUNK_SAMPLE_HEADER_MONO)
    raw[8:12] = b"\x00\x00\x00\x00"
    slot = SampleSlot(bytes(raw), False, 0)
    slot.set_name(name)
    assert len(slot.name_bytes) == L.SAMPLE_NAME_LEN == 8
    assert len(slot.to_bytes()) == L.CHUNK_SAMPLE_HEADER_MONO


@given(name=NAME_TEXT)
def test_pattern_name_always_occupies_exactly_eight_bytes(name: str) -> None:
    pat = Pattern.from_bytes(_PATTERN_CHUNK)
    pat.set_name(name)
    assert len(pat.to_bytes()) == L.CHUNK_PATTERN
    assert len(pat.to_bytes()[: L.PATTERN_NAME_LEN]) == 8


# -- byte buffer --------------------------------------------------------------
@given(
    values=st.lists(
        st.integers(min_value=0, max_value=0xFFFFFFFF), min_size=0, max_size=40
    )
)
def test_byte_writer_and_reader_are_inverses(values: list[int]) -> None:
    w = ByteWriter()
    for v in values:
        w.write_u32(v)
    data = w.getvalue()
    assert len(data) == 4 * len(values)
    r = ByteReader(data)
    assert [r.read_u32() for _ in values] == values
    assert r.remaining == 0


@given(data=st.binary(min_size=0, max_size=200), pos=st.integers(0, 200))
def test_reader_never_reads_past_the_end(data: bytes, pos: int) -> None:
    r = ByteReader(data)
    if pos > len(data):
        with pytest.raises(ValueError):
            r.seek(pos)
    else:
        r.seek(pos)
        assert r.remaining == len(data) - pos


# -- the synthetic bank itself ------------------------------------------------
@settings(max_examples=8, deadline=None)
@given(
    num_mono=st.integers(min_value=0, max_value=6),
    pcm=st.integers(min_value=64, max_value=8192),
)
@pytest.mark.slow
def test_synthetic_bank_always_round_trips_and_validates(
    num_mono: int, pcm: int
) -> None:
    """Any shape of synthetic bank must be coherent and byte-stable."""
    from codec.operation_table import OperationTable
    from codec.reader import BankReader
    from codec.validator import BankValidator
    from codec.writer import BankWriter
    from tests.synthetic import build

    data = build(num_mono=num_mono, pcm_bytes=pcm)
    bank = BankReader().read_auto(data)
    assert BankWriter().write(bank) == data
    report = BankValidator(OperationTable.load("research")).validate(bank)
    assert report.ok, [f.message for f in report.errors()]
