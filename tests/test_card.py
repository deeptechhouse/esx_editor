"""
Card capacity — a different limit from the sampler's RAM.

The two are easy to confuse and the app used to show only one:

    sample RAM  25,165,824 B (285 s mono)   a property of the MACHINE
    card        4-128 MB                    a property of the CARD

A 128 MB card holds about four full-size banks. Reporting card space as if it
were the RAM budget (or vice versa) would give exactly the wrong answer to
"can I fit another bank".
"""

from __future__ import annotations

import os

import pytest

import codec.layout as L
from tests.synthetic import build
from workspace import card


@pytest.fixture
def card_dir(tmp_path):
    """A folder standing in for a card: two banks and one non-bank file."""
    (tmp_path / "a.esx").write_bytes(build(num_mono=2, pcm_bytes=2048))
    (tmp_path / "b.esx").write_bytes(build(num_mono=0, pcm_bytes=64))
    (tmp_path / "notes.txt").write_text("not a bank")
    (tmp_path / "junk.esx").write_bytes(b"far too short to be a bank")
    return str(tmp_path)


def test_the_two_limits_are_not_the_same_number() -> None:
    """If these ever coincide, the distinction has been lost somewhere."""
    assert L.MAX_SAMPLE_BYTES == 25_165_824
    assert card.MAX_CARD_BYTES == 128 * 1024 * 1024
    assert card.MAX_CARD_BYTES > L.MAX_SAMPLE_BYTES * 5


def test_a_full_bank_is_ram_plus_the_fixed_structure() -> None:
    assert card.FIXED_BYTES == L.ADDR_SAMPLE_DATA
    assert card.MAX_BANK_BYTES == (
        L.ADDR_SAMPLE_DATA + L.MAX_SAMPLE_BYTES + L.PCM_TRAILER_LEN
    )
    # About four fit on a 128 MB card. If this changes, the advice changes.
    assert card.MAX_CARD_BYTES // card.MAX_BANK_BYTES == 4


def test_describe_reads_the_header_without_parsing(tmp_path) -> None:
    path = str(tmp_path / "one.esx")
    with open(path, "wb") as handle:
        handle.write(build(num_mono=3, pcm_bytes=4096))
    described = card.describe_bank(path)
    assert described.readable
    assert described.num_mono == 3 and described.num_stereo == 0
    assert described.samples == 3
    assert described.pcm_used > 0
    assert 0 < described.ram_fraction < 1
    assert described.name == "one.esx"


def test_a_junk_file_is_reported_not_raised(tmp_path) -> None:
    """A card can contain anything; a listing must not fail on one bad file."""
    short = tmp_path / "short.esx"
    short.write_bytes(b"nope")
    assert card.describe_bank(str(short)).readable is False

    wrong = tmp_path / "wrong.esx"
    wrong.write_bytes(b"\x00" * (L.SIZE_FILE_MIN + 16))
    assert card.describe_bank(str(wrong)).readable is False


def test_scan_finds_banks_and_ignores_everything_else(card_dir) -> None:
    contents = card.scan(card_dir)
    names = [b.name for b in contents.banks]
    assert names == ["a.esx", "b.esx", "junk.esx"]
    assert "notes.txt" not in names
    assert [b.readable for b in contents.banks] == [True, True, False]


def test_scan_of_a_missing_directory_is_empty_not_an_error() -> None:
    assert card.scan("/definitely/not/here").banks == ()


def test_capacity_accounting(card_dir) -> None:
    contents = card.scan(card_dir, capacity=card.MAX_CARD_BYTES)
    assert contents.used == sum(b.size for b in contents.banks)
    assert contents.free == card.MAX_CARD_BYTES - contents.used
    assert 0 < contents.fraction < 1
    assert contents.fits(1024)
    assert not contents.fits(card.MAX_CARD_BYTES)


def test_a_small_card_reports_no_room_for_a_full_bank(card_dir) -> None:
    """A 4 MB card is legal and holds no full-size bank at all."""
    contents = card.scan(card_dir, capacity=card.MIN_CARD_BYTES)
    assert contents.room_for_full_banks() == 0
    assert not contents.fits(card.MAX_BANK_BYTES)


def test_summary_names_both_numbers(card_dir) -> None:
    text = card.scan(card_dir).summary()
    assert "bank(s)" in text and "used" in text and "free" in text
    assert "full-size bank" in text


def test_detect_capacity_never_claims_a_card_bigger_than_a_card(tmp_path) -> None:
    """tmp_path is on the internal disk, which is not a 2 TB SmartMedia card."""
    detected = card.detect_capacity(str(tmp_path))
    assert detected <= card.MAX_CARD_BYTES
    assert card.detect_capacity("/definitely/not/here") == card.MAX_CARD_BYTES


@pytest.mark.corpus
def test_the_real_card_backup_reports_sensibly() -> None:
    directory = os.path.join("corpus", "card_backup_2026-08-22")
    if not os.path.isdir(directory):
        pytest.skip("no card backup present")
    contents = card.scan(directory)
    if not contents.banks:
        pytest.skip("no banks in the backup")
    assert all(b.readable for b in contents.banks)
    assert contents.used > 0
    assert contents.fraction < 1.0, "the backup must fit on the card it came from"
    for bank in contents.banks:
        assert bank.ram_fraction <= 1.0, f"{bank.name} claims more than the RAM cap"
