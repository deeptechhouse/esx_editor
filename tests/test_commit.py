"""
Committing a sample into a bank — the thing the app exists to do.

Until now the staging bank could cost and name a sample but not put it
anywhere: `Bank.commit_sample` raised. These tests cover the allocation rule,
every refusal path, and the two bookkeeping fields a commit has to keep
consistent (the sample-area counts and the PCM trailer).

They also pin the stereo header layout, which was established from real data on
2026-08-23 and CORRECTS the TDD — see codec/layout.py for the evidence.
"""

from __future__ import annotations

import struct

import pytest

import codec.layout as L
from codec.reader import BankReader
from codec.validator import BankValidator
from codec.writer import BankWriter
from core.errors import InvariantError
from tests.synthetic import build


def empty_bank(pcm_bytes: int = 16):
    return BankReader().read_auto(build(num_mono=0, pcm_bytes=pcm_bytes))


def loaded_bank(num_mono: int = 3):
    return BankReader().read_auto(build(num_mono=num_mono))


# -- the happy path -----------------------------------------------------------
def test_commit_writes_pcm_header_and_counts() -> None:
    bank = empty_bank()
    payload = bytes(range(256)) * 4
    bank.commit_sample(0, payload, stereo=False, sample_rate=44100, name="KICK01")

    slot = bank.samples()[0]
    assert not slot.empty
    assert slot.name.strip() == "KICK01"
    assert slot.sample_rate == 44100
    # The slot brackets the whole BLOCK; the audio starts 16 bytes in.
    assert bytes(bank.pcm[slice(*slot.audio_range)]) == payload
    assert slot.audio_bytes == len(payload)
    assert bank.sample_area_header()[:2] == (1, 0)


def test_commit_follows_the_verified_allocation_rule() -> None:
    """next_start = align_up(previous_end + 2, 4)."""
    bank = empty_bank()
    first = b"\x01\x02" * 501  # 1002 B — deliberately not 4-aligned
    second = b"\x03\x04" * 10
    bank.commit_sample(0, first, stereo=False, sample_rate=44100, name="A")
    bank.commit_sample(1, second, stereo=False, sample_rate=44100, name="B")

    a, b = bank.samples()[0], bank.samples()[1]
    assert a.offset_start == 0
    assert a.offset_end == L.PCM_BLOCK_HEADER_LEN + len(first)
    expected = -(-(a.offset_end + L.PCM_GAP) // L.PCM_ALIGN) * L.PCM_ALIGN
    assert b.offset_start == expected
    assert b.offset_start % L.PCM_ALIGN == 0
    assert b.offset_start - a.offset_end in (2, 3, 4)
    assert bytes(bank.pcm[slice(*b.audio_range)]) == second


def test_commit_defaults_the_tune_to_rate_compensation() -> None:
    """A 32 kHz sample must play at natural pitch, as the hardware writes it."""
    bank = empty_bank()
    bank.commit_sample(0, b"\x00" * 100, stereo=False, sample_rate=32000, name="X")
    slot = bank.samples()[0]
    assert abs(slot.musical_tune()) < 0.01
    assert abs(slot.stored_tune - slot.rate_compensation()) < 0.01
    assert slot.stored_tune < 0, "a sub-44.1k sample is tuned down"


def test_commit_can_carry_a_musical_transposition() -> None:
    bank = empty_bank()
    bank.commit_sample(
        0, b"\x00" * 100, stereo=False, sample_rate=44100, name="X", musical_tune=7.0
    )
    assert abs(bank.samples()[0].musical_tune() - 7.0) < 0.01


def test_commit_writes_a_proper_block_header() -> None:
    """Every PCM block opens with magic + its own start and end (VERIFIED)."""
    bank = empty_bank()
    payload = b"\x11" * 400
    bank.commit_sample(0, payload, stereo=False, sample_rate=44100, name="X")
    slot = bank.samples()[0]
    magic, start, end, number, channel, tail = struct.unpack_from(
        ">IIIBBH", bank.pcm, slot.offset_start
    )
    assert magic == L.PCM_BLOCK_MAGIC
    assert start == slot.offset_start
    assert end == slot.offset_end
    assert number == 0 and channel == L.PCM_CHANNEL_MONO
    assert tail == L.PCM_BLOCK_TAIL
    assert bytes(bank.pcm[slice(*slot.audio_range)]) == payload


def test_commit_terminates_the_chain_with_a_free_block() -> None:
    """The last 16 bytes are one more block header, marked free."""
    bank = empty_bank()
    bank.commit_sample(0, b"\x00" * 400, stereo=False, sample_rate=44100, name="X")
    _, _, cursor = bank.sample_area_header()
    assert len(bank.pcm) == cursor + L.PCM_BLOCK_HEADER_LEN
    magic, start, end, _n, channel, _t = struct.unpack_from(">IIIBBH", bank.pcm, cursor)
    assert magic == L.PCM_BLOCK_MAGIC
    assert start == cursor, "the free block sits AT currentOffset"
    assert end == L.PCM_FREE_BLOCK_END
    assert channel == L.PCM_CHANNEL_FREE


def test_a_committed_bank_validates_and_round_trips() -> None:
    bank = empty_bank()
    bank.commit_sample(0, b"\x11" * 512, stereo=False, sample_rate=44100, name="A")
    bank.commit_sample(5, b"\x22" * 300, stereo=False, sample_rate=22050, name="B")
    assert BankValidator().validate(bank).ok

    data = BankWriter().write(bank)
    again = BankReader().read_auto(data)
    assert BankWriter().write(again) == data
    assert again.samples()[5].name.strip() == "B"
    assert bytes(again.pcm[slice(*again.samples()[5].audio_range)]) == b"\x22" * 300


# -- refusals -----------------------------------------------------------------
def test_commit_refuses_an_occupied_slot() -> None:
    bank = loaded_bank()
    with pytest.raises(InvariantError, match="occupied"):
        bank.commit_sample(0, b"\x00" * 10, stereo=False, sample_rate=44100, name="X")


def test_commit_refuses_the_wrong_pool() -> None:
    """Mono and stereo are separate header tables; a slot cannot be borrowed."""
    bank = empty_bank()
    with pytest.raises(InvariantError, match="mono slot"):
        bank.commit_sample(0, b"\x00" * 10, stereo=True, sample_rate=44100, name="X")
    with pytest.raises(InvariantError, match="stereo slot"):
        bank.commit_sample(
            L.NUM_SAMPLES_MONO, b"\x00" * 10, stereo=False, sample_rate=44100, name="X"
        )


def test_commit_refuses_an_out_of_range_rate() -> None:
    bank = empty_bank()
    for rate in (0, 8000, 192000):
        with pytest.raises(InvariantError, match="rate"):
            bank.commit_sample(
                0, b"\x00" * 10, stereo=False, sample_rate=rate, name="X"
            )


def test_commit_refuses_an_odd_pcm_length() -> None:
    """16-bit frames are always an even byte count."""
    bank = empty_bank()
    with pytest.raises(InvariantError, match="even"):
        bank.commit_sample(0, b"\x00" * 11, stereo=False, sample_rate=44100, name="X")


def test_commit_refuses_to_exceed_capacity_and_changes_nothing() -> None:
    bank = empty_bank()
    before = bytes(bank.pcm)
    too_big = b"\x00" * (L.MAX_SAMPLE_BYTES + 2)
    with pytest.raises(InvariantError, match="exceeds free space"):
        bank.commit_sample(0, too_big, stereo=False, sample_rate=44100, name="X")
    assert bank.samples()[0].empty
    assert bytes(bank.pcm) == before
    assert bank.sample_area_header()[:2] == (0, 0)


def test_commit_refuses_a_bad_slot_index() -> None:
    bank = empty_bank()
    for index in (-1, L.NUM_SAMPLES):
        with pytest.raises(InvariantError, match="out of range"):
            bank.commit_sample(
                index, b"\x00" * 10, stereo=False, sample_rate=44100, name="X"
            )


# -- clear and compact --------------------------------------------------------
def test_clear_empties_the_slot_and_updates_the_count() -> None:
    bank = loaded_bank(num_mono=3)
    assert bank.sample_area_header()[0] == 3
    bank.clear_sample(1)
    assert bank.samples()[1].empty
    assert bank.sample_area_header()[0] == 2
    assert BankValidator().validate(bank).ok


def test_clear_does_not_reclaim_pcm() -> None:
    """Reclaiming would relocate every later sample — a delete must not do that."""
    bank = loaded_bank(num_mono=3)
    third_start = bank.samples()[2].offset_start
    bank.clear_sample(0)
    assert bank.samples()[2].offset_start == third_start


def test_compact_reclaims_the_gap_and_keeps_the_audio() -> None:
    bank = empty_bank()
    a, b = b"\xaa" * 1000, b"\xbb" * 600
    bank.commit_sample(0, a, stereo=False, sample_rate=44100, name="A")
    bank.commit_sample(1, b, stereo=False, sample_rate=44100, name="B")
    bank.clear_sample(0)

    freed = bank.compact_pcm()
    assert freed > 0
    slot = bank.samples()[1]
    assert slot.offset_start == 0
    assert bytes(bank.pcm[slice(*slot.audio_range)]) == b
    assert BankValidator().validate(bank).ok
    data = BankWriter().write(bank)
    assert BankWriter().write(BankReader().read_auto(data)) == data


def test_compact_refuses_a_bank_with_stereo_samples(stereo_bank) -> None:
    """Two ranges per slot that must stay adjacent — not worth guessing at."""
    with pytest.raises(InvariantError, match="stereo"):
        stereo_bank.compact_pcm()


# -- the stereo layout, established from real data ----------------------------
@pytest.mark.corpus
def test_stereo_header_layout_is_verified_against_real_slots(stereo_bank) -> None:
    """CORRECTS TDD §2.3, which inferred this from blank slots only.

    The TDD placed a loopStart at 32, pushing sampleRate to 36 and sampleTune
    to 40. Real populated stereo slots say the rate is at 32 and the tune at
    36, with no loopStart at all.
    """
    stereo = [s for s in stereo_bank.samples()[L.NUM_SAMPLES_MONO :] if not s.empty]
    assert stereo, "the stereo_bank fixture guarantees these exist"

    for slot in stereo:
        raw = slot.to_bytes()
        assert len(raw) == L.CHUNK_SAMPLE_HEADER_STEREO == 44

        # The rate field is a legal import rate...
        assert L.MIN_IMPORT_RATE_HZ <= slot.sample_rate <= L.MAX_IMPORT_RATE_HZ
        # ...and the TDD's claimed rate position is not.
        claimed = struct.unpack_from(">I", raw, 36)[0]
        assert not (L.MIN_IMPORT_RATE_HZ <= claimed <= L.MAX_IMPORT_RATE_HZ)

        # The tune field independently confirms the rate field's position:
        # one is derived from the other.
        assert abs(slot.stored_tune - slot.rate_compensation()) < 0.02

        # Both channels, same length, following the allocation rule.
        ch2 = slot.channel2_range
        assert ch2 is not None
        assert (slot.offset_end - slot.offset_start) == (ch2[1] - ch2[0])
        expected = -(-(slot.offset_end + L.PCM_GAP) // L.PCM_ALIGN) * L.PCM_ALIGN
        assert ch2[0] == expected


@pytest.mark.corpus
def test_no_pcm_range_in_a_real_bank_overlaps_another(bank) -> None:
    """Counts channel 2 as well — missing it is what made commit overwrite it."""
    ranges = []
    for slot in bank.samples():
        if slot.empty:
            continue
        ranges.append((slot.offset_start, slot.offset_end))
        if slot.channel2_range:
            ranges.append(slot.channel2_range)
    ranges.sort()
    for i in range(len(ranges) - 1):
        assert ranges[i][1] <= ranges[i + 1][0], f"overlap at {ranges[i]}"


@pytest.mark.corpus
def test_every_real_block_carries_a_valid_header(bank) -> None:
    """204/204 across two banks when this was established. Never regress it."""
    pcm = bank.pcm
    checked = 0
    for slot in bank.samples():
        if slot.empty:
            continue
        ranges = [(slot.offset_start, slot.offset_end)]
        if slot.channel2_range:
            ranges.append(slot.channel2_range)
        for start, end in ranges:
            if start + L.PCM_BLOCK_HEADER_LEN > len(pcm):
                continue  # e4 has stale headers pointing past EOF
            checked += 1
            magic, got_start, got_end, _n, channel, tail = struct.unpack_from(
                ">IIIBBH", pcm, start
            )
            assert magic == L.PCM_BLOCK_MAGIC
            assert got_start == start and got_end == end
            assert channel in (
                L.PCM_CHANNEL_MONO,
                L.PCM_CHANNEL_LEFT,
                L.PCM_CHANNEL_RIGHT,
            )
            assert tail == L.PCM_BLOCK_TAIL
    if checked == 0:
        pytest.skip("no readable blocks in this bank")


@pytest.mark.corpus
def test_the_free_block_terminates_a_real_chain(bank) -> None:
    _, _, cursor = bank.sample_area_header()
    pcm = bank.pcm
    if cursor + L.PCM_BLOCK_HEADER_LEN > len(pcm):
        pytest.skip("this bank's currentOffset is stale (e4 has 16/18 bad headers)")
    magic, start, _end, _n, channel, _t = struct.unpack_from(">IIIBBH", pcm, cursor)
    assert magic == L.PCM_BLOCK_MAGIC
    assert start == cursor
    assert channel == L.PCM_CHANNEL_FREE


@pytest.mark.corpus
def test_factory_samples_decode_to_zero_musical_tune(bank) -> None:
    """Imported material carries pure rate compensation, no transposition."""
    occupied = [s for s in bank.samples() if not s.empty]
    if not occupied:
        pytest.skip("empty bank")
    tuned = [s for s in occupied if abs(s.musical_tune()) > 0.05]
    assert len(tuned) <= len(occupied) * 0.1, (
        f"{len(tuned)}/{len(occupied)} slots have a musical transposition; "
        "the tune decode is probably wrong"
    )


@pytest.mark.corpus
def test_commit_into_a_real_bank_corrupts_nothing(coherent_bank) -> None:
    """The regression that motivated stereo-aware allocation."""
    bank = coherent_bank
    snapshot = {}
    for slot in bank.samples():
        if slot.empty:
            continue
        snapshot[(slot.index, 1)] = bytes(bank.pcm[slice(*slot.audio_range)])
        if slot.channel2_range:
            snapshot[(slot.index, 2)] = bytes(bank.pcm[slice(*slot.channel2_range)])
    if not snapshot:
        pytest.skip("empty bank")

    free = next(
        i for i, s in enumerate(bank.samples()[: L.NUM_SAMPLES_MONO]) if s.empty
    )
    before_cursor = bank.sample_area_header()[2]
    payload = b"\x11\x22" * 400
    bank.commit_sample(free, payload, stereo=False, sample_rate=44100, name="NEWONE")

    assert bank.sample_area_header()[2] > before_cursor, "the cursor must advance"
    for (index, channel), original in snapshot.items():
        slot = bank.samples()[index]
        current = (
            bytes(bank.pcm[slice(*slot.audio_range)])
            if channel == 1
            else bytes(bank.pcm[slice(*slot.channel2_range)])
        )
        assert current == original, f"slot {index} channel {channel} was overwritten"
    assert bytes(bank.pcm[slice(*bank.samples()[free].audio_range)]) == payload


# -- the one decoded pattern-header field -------------------------------------
def test_tempo_decodes_the_machine_default_exactly() -> None:
    """Every untouched pattern reads exactly 120.0 — the machine's own default."""
    bank = empty_bank()
    for pattern in bank.patterns()[:8]:
        assert pattern.header.tempo == pytest.approx(120.0, abs=0.001)


def test_tempo_round_trips_through_the_writer() -> None:
    bank = empty_bank()
    bank.patterns()[3].header.set_tempo(137.5)
    data = BankWriter().write(bank)
    again = BankReader().read_auto(data)
    assert again.patterns()[3].header.tempo == pytest.approx(137.5, abs=0.01)
    assert BankWriter().write(again) == data


def test_tempo_refuses_values_the_hardware_cannot_hold() -> None:
    from core.pattern import MAX_TEMPO, MIN_TEMPO

    header = empty_bank().patterns()[0].header
    for bad in (0.0, 19.9, 300.1, 10_000.0, -5.0):
        with pytest.raises(InvariantError, match="tempo"):
            header.set_tempo(bad)
    header.set_tempo(MIN_TEMPO)
    assert header.tempo == pytest.approx(MIN_TEMPO, abs=0.01)
    header.set_tempo(MAX_TEMPO)
    assert header.tempo == pytest.approx(MAX_TEMPO, abs=0.01)


def test_the_still_undecoded_header_fields_refuse_to_guess() -> None:
    header = empty_bank().patterns()[0].header
    for field in ("length_bars", "last_step", "playable_steps"):
        with pytest.raises(NotImplementedError, match="hardware diff"):
            getattr(header, field)


@pytest.mark.corpus
def test_real_pattern_tempos_are_musical(bank) -> None:
    """The evidence for the 1/128 scale: real tempos land on whole BPM.

    19 of the 20 distinct values across the corpus are exact integers in the
    20-300 range. A wrong scale would not produce that.
    """
    from core.pattern import MAX_TEMPO, MIN_TEMPO

    named = [p for p in bank.patterns() if p.name.strip()]
    tempos = {p.header.tempo for p in (named or bank.patterns()[:16])}
    assert tempos, "every bank has patterns"
    for tempo in tempos:
        assert MIN_TEMPO <= tempo <= MAX_TEMPO, tempo
    whole = sum(1 for t in tempos if abs(t - round(t)) < 0.001)
    assert whole >= len(tempos) * 0.9, (
        f"only {whole}/{len(tempos)} tempos are whole BPM; the 1/128 scale "
        "may be wrong"
    )


@pytest.mark.corpus
def test_editing_tempo_leaves_every_other_header_byte_alone(coherent_bank) -> None:
    """A tempo edit must touch exactly two bytes."""
    header = coherent_bank.patterns()[0].header
    before = header.to_bytes()
    header.set_tempo(111.0)
    after = header.to_bytes()
    changed = [i for i in range(len(before)) if before[i] != after[i]]
    assert changed and set(changed) <= {0, 1}, f"tempo touched bytes {changed}"
