"""
The round-trip gate (TDD §4.2): writer(reader(b)) == b, byte for byte.

This is the primary correctness gate for the codec. It runs against every real
.esx bank found in the corpus/ directory (and the blank template). Copyrighted
banks are NOT committed; the test skips gracefully when a file is absent.
"""

from __future__ import annotations

import os
import glob

import pytest

from codec.reader import BankReader
from codec.writer import BankWriter
from core.motion import MotionSlot, MotionDomain
from core.errors import InvariantError

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _corpus_files() -> list[str]:
    paths = glob.glob(os.path.join(PROJECT_ROOT, "corpus", "**", "*.esx"),
                      recursive=True)
    paths += glob.glob(os.path.join(PROJECT_ROOT, "spike_a", "*.esx"))
    return sorted(set(paths))


@pytest.mark.parametrize("path", _corpus_files() or [pytest.param(
    "", marks=pytest.mark.skip(reason="no corpus .esx files present"))])
def test_roundtrip_byte_identical(path: str) -> None:
    with open(path, "rb") as f:
        original = f.read()
    bank = BankReader().read_auto(original)
    rewritten = BankWriter().write(bank)
    assert rewritten == original, (
        f"round-trip changed bytes for {os.path.basename(path)} "
        f"(len {len(original)} -> {len(rewritten)})")


def test_motion_slot_requires_128_values() -> None:
    with pytest.raises(InvariantError):
        MotionSlot(0, b"\x00" * 127)


def test_motion_slot_roundtrips() -> None:
    raw = bytes([0x12, 0x34]) + bytes(range(128))
    slot = MotionSlot.from_bytes(raw)
    assert slot.target == 0x1234
    assert slot.to_bytes() == raw


def test_motion_domain_snaps_discrete() -> None:
    # Filter Type: 4 options -> knob positions {0, 32, 64, 96}
    dom = MotionDomain(MotionDomain.ENUM, 4, forced_trig=True)
    assert dom.legal_values() == (0, 32, 64, 96)
    assert dom.encode(2) == 64
    assert dom.decode(64) == 2
