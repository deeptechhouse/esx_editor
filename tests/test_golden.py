"""
Golden tests — pin the exact bytes, so a codec regression fails loudly.

WHY HASHES AND NOT FILES
    `*.esx` is gitignored (large binaries, Korg factory-derived audio), so a
    golden bank cannot live in the repo. Two things stand in for it:

    1. A synthetic bank built deterministically in `tests.synthetic`. Its hash
       is pinned here, so ANY change to the reader, the writer, or the layout
       constants that alters the emitted bytes shows up as a failed hash rather
       than as a subtle diff nobody reads.
    2. The real corpus banks, when present: their own bytes are the golden
       reference, and the assertion is that writer(reader(b)) == b exactly.

    A hash mismatch is not automatically a bug — it means the emitted bytes
    changed, and someone has to decide whether that was intended. That is the
    point: the decision becomes explicit.
"""

from __future__ import annotations

import hashlib

import pytest

import codec.layout as L
from codec.reader import BankReader
from codec.validator import BankValidator
from codec.writer import BankWriter
from tests.synthetic import SEED, build, sha256

# Pinned bytes for the default synthetic bank. Regenerate ONLY when a change to
# the emitted image is intended, and say why in research/CODEC_FINDINGS_LOG.md.
#
# CHANGED 2026-08-23 (WF10/WF11): the synthetic patterns now carry the real
# machine default header (tempo 120.0) and a zeroed part/FX area, instead of
# deterministic filler that decoded as a nonsense 104.02 BPM and as parts
# triggering on half their steps. The fixture now looks like something an ESX-1
# actually wrote. This hash moving is the golden test doing its job — the
# changes were intended.
#
# CHANGED again 2026-08-23 (WF13): only the first four patterns are named now.
# Naming all 256 made every pattern chunk unique, so the fixture had no "blank
# pattern" — which a real bank very much does (204 of 256 in the busiest corpus
# bank). Pattern Clear derives its bytes from that, so the fixture had to match
# reality for it to be testable.
#
# CHANGED again 2026-08-23 (WF15): every PCM block now carries its real 16-byte
# header and the chain ends with a free block, because that is what a machine
# writes. A fixture of bare audio would have hidden the very bug that prompted
# this — commit_sample was writing no block header at all.
GOLDEN_DEFAULT = "07426e0770f9958a71985b70e960313adf0fcb5ccd0192e3ee73f6ad22069932"
GOLDEN_SIZE = 2428928


def test_synthetic_bank_bytes_are_pinned() -> None:
    """The fixture itself must be reproducible, or every other golden is moot."""
    data = build()
    assert len(data) == GOLDEN_SIZE
    assert sha256(data) == GOLDEN_DEFAULT, (
        "the synthetic bank changed; if that was intended, update GOLDEN_DEFAULT "
        "and record why in research/CODEC_FINDINGS_LOG.md"
    )


def test_synthetic_bank_is_deterministic() -> None:
    assert build() == build()
    assert SEED == b"esx-bank-studio-synthetic-v1"


def test_writer_reproduces_the_synthetic_bank_exactly() -> None:
    """THE GATE, runnable with no corpus: writer(reader(b)) == b."""
    data = build()
    assert BankWriter().write(BankReader().read_auto(data)) == data


def test_layout_constants_are_pinned() -> None:
    """The offsets are the whole format. Pin them so a typo cannot slip in."""
    assert L.ADDR_MAGIC_1 == 0x00000000
    assert L.ADDR_GLOBAL_PARAMETERS == 0x00000020
    assert L.ADDR_PATTERN_DATA == 0x00000200
    assert L.ADDR_SONG_DATA == 0x00130000
    assert L.ADDR_SONG_EVENT_DATA == 0x00138400
    assert L.ADDR_MAGIC_2 == 0x001B0000
    assert L.ADDR_SAMPLE_HEADER_MONO == 0x001B0100
    assert L.ADDR_SAMPLE_HEADER_STEREO == 0x001B2900
    assert L.ADDR_SLICE_DATA == 0x001B4200
    assert L.ADDR_SAMPLE_DATA == 0x00250000
    assert L.CHUNK_PATTERN == 4280
    assert L.CHUNK_SONG == 528
    assert L.CHUNK_PARAMETERS_MOTION == 130
    assert L.NUM_PATTERNS == 256
    assert L.NUM_SAMPLES == 384
    assert L.NUM_PARAMETERS_MOTION == 24
    assert L.MAX_SAMPLE_BYTES == 25_165_824
    assert L.SIZE_FILE_MIN == 0x00250010
    # The motion chunk must end exactly at the pattern boundary, or every
    # pattern after the first is misaligned.
    assert (
        L.PAT_OFF_PARAMETERS_MOTION
        + L.NUM_PARAMETERS_MOTION * L.CHUNK_PARAMETERS_MOTION
        == L.CHUNK_PATTERN
    )


def test_pattern_region_tiles_exactly() -> None:
    """Patterns must fill the region between their start and unknown_2."""
    end = L.ADDR_PATTERN_DATA + L.NUM_PATTERNS * L.CHUNK_PATTERN
    assert end == L.ADDR_UNKNOWN_2 == 0x0010BA00


def test_sample_header_tables_tile_exactly() -> None:
    mono_end = (
        L.ADDR_SAMPLE_HEADER_MONO + L.NUM_SAMPLES_MONO * L.CHUNK_SAMPLE_HEADER_MONO
    )
    stereo_end = (
        L.ADDR_SAMPLE_HEADER_STEREO
        + L.NUM_SAMPLES_STEREO * L.CHUNK_SAMPLE_HEADER_STEREO
    )
    assert mono_end == 0x001B2900 == L.ADDR_SAMPLE_HEADER_STEREO
    assert stereo_end == 0x001B3F00 == L.ADDR_UNKNOWN_4


# -- the real banks, when they are present ------------------------------------
@pytest.mark.corpus
def test_corpus_bank_round_trips_byte_identically(corpus_path) -> None:
    """The gate on real data. Never regress this."""
    with open(corpus_path, "rb") as f:
        original = f.read()
    bank = BankReader().read_auto(original)
    assert BankWriter().write(bank) == original


@pytest.mark.corpus
def test_every_available_corpus_bank_round_trips() -> None:
    """Not just the first one — every bank on disk."""
    from tests.conftest import available_corpus

    present = available_corpus()
    if not present:
        pytest.skip("no corpus banks available")
    for path in present:
        with open(path, "rb") as f:
            original = f.read()
        bank = BankReader().read_auto(original)
        assert BankWriter().write(bank) == original, f"{path} did not round-trip"


@pytest.mark.corpus
def test_corpus_bank_digest_is_stable_across_a_read_write_cycle(
    corpus_path, tmp_path
) -> None:
    """Through the real file path, not just in memory."""
    with open(corpus_path, "rb") as f:
        before = hashlib.sha256(f.read()).hexdigest()
    bank = BankReader().read_file(corpus_path)
    dest = str(tmp_path / "cycled.esx")
    BankWriter().write_file(bank, dest, allow_invalid=True)
    with open(dest, "rb") as f:
        after = hashlib.sha256(f.read()).hexdigest()
    assert before == after


@pytest.mark.corpus
def test_validator_findings_are_stable(bank) -> None:
    """Validation is a pure function of the bank; two runs must agree."""
    a = BankValidator().validate(bank)
    b = BankValidator().validate(bank)
    assert [(f.severity, f.code) for f in a.findings] == [
        (f.severity, f.code) for f in b.findings
    ]


# -- the hardware-saved song --------------------------------------------------
def test_the_hardware_saved_song_decodes_as_documented(song_bank_path) -> None:
    """The one real song, read back exactly as core/song.py claims it reads.

    This is the evidence the whole song decoder rests on. If it ever stops
    matching, the decoder is wrong, not the bank.
    """
    from codec.reader import BankReader

    bank = BankReader().read_file(song_bank_path)
    songs = bank.songs()

    first = songs[0]
    assert first.name == "bib1"
    assert first.tempo == 120.0
    assert first.length == 4
    assert first.chain == (1, 0, 3, 5)
    assert first.chain_labels() == ("A.02", "A.01", "A.04", "A.06")
    assert first.is_blank is False

    # Song 1 was named on the machine and otherwise left alone: a named song
    # with a default chain, which is the case that separates "has a name" from
    # "has content".
    assert songs[1].name == "bib2"
    assert songs[1].chain == (0,)
    assert songs[1].is_blank is False

    assert all(s.is_blank for s in songs[2:]), "only two songs were touched"


def test_the_song_bank_round_trips_byte_identically(song_bank_path) -> None:
    """Songs are emitted from objects now — the gate has to still hold."""
    from codec.reader import BankReader
    from codec.writer import BankWriter

    with open(song_bank_path, "rb") as f:
        raw = f.read()
    assert BankWriter().write(BankReader().read_auto(raw)) == raw


def test_editing_a_song_touches_only_that_song_block(song_bank_path) -> None:
    """A song edit must not disturb one byte outside its own 528."""
    import codec.layout as L
    from codec.reader import BankReader
    from codec.writer import BankWriter

    with open(song_bank_path, "rb") as f:
        raw = f.read()
    bank = BankReader().read_auto(raw)
    bank.songs()[0].append_pattern(200)
    out = BankWriter().write(bank)

    assert len(out) == len(raw)
    start = L.ADDR_SONG_DATA
    end = start + L.CHUNK_SONG
    differing = [i for i in range(len(raw)) if raw[i] != out[i]]
    assert differing, "the edit did land"
    assert all(start <= i < end for i in differing), (
        "an edit to song 1 changed bytes outside its own block"
    )
