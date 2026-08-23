"""
Part decoding: sample number and the step trigger bitmap.

Both were established from real bank data on 2026-08-23, and both have an
independent cross-check that makes them proof rather than inference:

  - `sample_number` points at an OCCUPIED slot on 728 of 728 sample-playing
    parts. And because Chronic-Interactive.esx names its samples after their own
    slot index ('00'..'99'), the decoded number can be checked against the name:
    672 of 672 match exactly.
  - The bitmap's LSB-first bit order is settled by where the hits land. Read
    LSB-first, step 0 is the single most-triggered step and the quarter-note
    grid carries 1.85x its uniform share. Read MSB-first the busiest step is a
    16th-note offbeat and the concentration inverts.
"""

from __future__ import annotations

import pytest

import codec.layout as L
from codec.reader import BankReader
from codec.writer import BankWriter
from core.errors import InvariantError
from core.part import (
    NUM_STEPS,
    SAMPLE_PLAYING_KINDS,
    SEQUENCE_BYTES,
    SEQUENCE_OFFSETS,
    SequenceData,
)
from tests.synthetic import build


def a_bank():
    return BankReader().read_auto(build())


# -- SequenceData, the pure bitmap -------------------------------------------
def test_sequence_round_trips_every_step() -> None:
    seq = SequenceData(bytes(SEQUENCE_BYTES))
    assert seq.count() == 0
    for step in range(NUM_STEPS):
        seq.set_active(step, True)
        assert seq.is_active(step)
    assert seq.count() == NUM_STEPS == 128
    assert seq.active_steps() == tuple(range(NUM_STEPS))
    for step in range(NUM_STEPS):
        seq.set_active(step, False)
    assert seq.count() == 0


def test_sequence_uses_lsb_first_bit_order() -> None:
    """Step 0 is the LOW bit of byte 0 — settled by where real hits land."""
    seq = SequenceData(bytes(SEQUENCE_BYTES))
    seq.set_active(0, True)
    assert seq.steps[0] == 0b00000001
    seq.set_active(0, False)
    seq.set_active(7, True)
    assert seq.steps[0] == 0b10000000
    seq.set_active(7, False)
    seq.set_active(8, True)
    assert seq.steps[1] == 0b00000001


def test_sequence_setting_a_step_leaves_its_neighbours_alone() -> None:
    seq = SequenceData(bytes(SEQUENCE_BYTES))
    for step in (0, 4, 8, 12):
        seq.set_active(step, True)
    seq.set_active(4, False)
    assert seq.active_steps() == (0, 8, 12)


def test_sequence_refuses_an_out_of_range_step() -> None:
    seq = SequenceData(bytes(SEQUENCE_BYTES))
    for bad in (-1, NUM_STEPS, 1000):
        with pytest.raises(InvariantError, match="out of range"):
            seq.is_active(bad)
        with pytest.raises(InvariantError, match="out of range"):
            seq.set_active(bad, True)


def test_sequence_refuses_a_wrong_sized_buffer() -> None:
    with pytest.raises(InvariantError, match="16 bytes"):
        SequenceData(b"\x00" * 8)


# -- Part.sample_number -------------------------------------------------------
def test_sample_number_reads_and_writes() -> None:
    bank = a_bank()
    part = bank.patterns()[0].parts()[0]
    assert part.kind in SAMPLE_PLAYING_KINDS
    part.set_sample_number(42)
    assert part.sample_number == 42
    part.set_sample_number(383)
    assert part.sample_number == 383


def test_sample_number_refuses_an_impossible_slot() -> None:
    part = a_bank().patterns()[0].parts()[0]
    for bad in (-1, 384, 70000):
        with pytest.raises(InvariantError, match="out of range"):
            part.set_sample_number(bad)


def test_parts_without_a_sample_refuse_rather_than_lie() -> None:
    """Audio-in takes the live input; accent is an emphasis track."""
    parts = a_bank().patterns()[0].parts()
    non_sample = [p for p in parts if p.kind not in SAMPLE_PLAYING_KINDS]
    assert non_sample, "every pattern has an audio-in and an accent part"
    for part in non_sample:
        with pytest.raises(NotImplementedError, match="does not play a sample"):
            _ = part.sample_number
        with pytest.raises(NotImplementedError):
            part.set_sample_number(0)


def test_sequence_is_only_offered_where_it_was_located() -> None:
    parts = a_bank().patterns()[0].parts()
    for part in parts:
        if part.kind in SEQUENCE_OFFSETS:
            assert part.has_sequence()
            assert isinstance(part.sequence(), SequenceData)
        else:
            assert not part.has_sequence()
            with pytest.raises(NotImplementedError, match="not decoded"):
                part.sequence()


def test_part_edits_survive_a_write(tmp_path) -> None:
    bank = a_bank()
    part = bank.patterns()[2].parts()[0]
    part.set_sample_number(17)
    sequence = part.sequence()
    for step in (0, 4, 8, 12):
        sequence.set_active(step, True)
    part.write_sequence(sequence)

    data = BankWriter().write(bank)
    again = BankReader().read_auto(data)
    reread = again.patterns()[2].parts()[0]
    assert reread.sample_number == 17
    assert reread.sequence().active_steps() == (0, 4, 8, 12)
    assert BankWriter().write(again) == data


def test_writing_a_sequence_touches_only_its_own_bytes() -> None:
    bank = a_bank()
    part = bank.patterns()[0].parts()[0]
    before = part.to_bytes()
    sequence = part.sequence()
    sequence.set_active(3, True)
    part.write_sequence(sequence)
    after = part.to_bytes()
    changed = {i for i in range(len(before)) if before[i] != after[i]}
    offset = SEQUENCE_OFFSETS[part.kind]
    assert changed <= set(range(offset, offset + SEQUENCE_BYTES))


# -- the evidence, against real banks -----------------------------------------
@pytest.mark.corpus
def test_every_sample_number_points_at_an_occupied_slot(bank) -> None:
    """The decisive test: a wrong field would land on empty slots constantly."""
    samples = bank.samples()
    checked = hits = 0
    for pattern in bank.patterns():
        if not pattern.name.strip():
            continue
        for part in pattern.parts():
            if part.kind not in SAMPLE_PLAYING_KINDS:
                continue
            checked += 1
            hits += not samples[part.sample_number].empty
    if checked == 0:
        pytest.skip("this corpus bank has no named patterns")
    assert hits == checked, f"only {hits}/{checked} point at an occupied slot"


@pytest.mark.corpus
def test_sample_number_matches_the_slot_name_where_the_name_is_its_index(
    stereo_bank,
) -> None:
    """Chronic-Interactive.esx names its samples '00'..'99' — a free oracle."""
    samples = stereo_bank.samples()
    checked = matched = 0
    for pattern in stereo_bank.patterns():
        if not pattern.name.strip():
            continue
        for part in pattern.parts():
            if part.kind not in SAMPLE_PLAYING_KINDS:
                continue
            name = samples[part.sample_number].name.strip()
            if name.isdigit():
                checked += 1
                matched += int(name) == part.sample_number
    if checked < 50:
        pytest.skip("this bank does not name samples after their index")
    assert matched == checked, f"only {matched}/{checked} matched"


@pytest.mark.corpus
def test_the_two_halves_of_every_real_bitmap_are_identical(stereo_bank) -> None:
    """64 steps written into a 128-step field — 468/468 and 156/156 on record."""
    checked = same = 0
    for pattern in stereo_bank.patterns():
        if not pattern.name.strip():
            continue
        for part in pattern.parts():
            if not part.has_sequence():
                continue
            raw = part.sequence().steps
            checked += 1
            same += raw[:8] == raw[8:]
    assert checked > 100
    assert same == checked


@pytest.mark.corpus
def test_real_triggers_land_on_the_beat(stereo_bank) -> None:
    """The evidence for LSB-first, re-measured.

    A wrong bit order scatters hits onto 16th-note offbeats. This is the test
    that would catch a bit-order regression; nothing else would.
    """
    hits = [0] * NUM_STEPS
    for pattern in stereo_bank.patterns():
        if not pattern.name.strip():
            continue
        for part in pattern.parts():
            if not part.has_sequence():
                continue
            for step in part.sequence().active_steps():
                hits[step] += 1
    assert sum(hits) > 1000, "need real data to measure"
    assert hits.index(max(hits)) == 0, "the downbeat must be the busiest step"
    on_grid = sum(hits[i] for i in range(0, NUM_STEPS, 4)) / (NUM_STEPS / 4)
    off_grid = sum(hits[i] for i in range(NUM_STEPS) if i % 4) / (NUM_STEPS * 3 / 4)
    assert on_grid > off_grid * 1.5, (
        f"quarter-note grid {on_grid:.1f}/slot vs off-grid {off_grid:.1f}/slot; "
        "the bit order may be wrong"
    )


@pytest.mark.corpus
def test_part_edits_do_not_disturb_the_rest_of_a_real_bank(coherent_bank) -> None:
    pattern = coherent_bank.patterns()[0]
    others = [p.to_bytes() for p in coherent_bank.patterns()[1:6]]
    part = next(p for p in pattern.parts() if p.has_sequence())
    sequence = part.sequence()
    sequence.set_active(5, not sequence.is_active(5))
    part.write_sequence(sequence)
    assert [p.to_bytes() for p in coherent_bank.patterns()[1:6]] == others
    assert len(pattern.to_bytes()) == L.CHUNK_PATTERN
