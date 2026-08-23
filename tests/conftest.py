"""
Shared offscreen-Qt fixtures.

Three WF6 test modules need the same three things — a QApplication, a real
corpus bank, and a throwaway WAV — and each built its own copy. They live here
instead: one QApplication for the whole session (Qt allows exactly one), one
corpus-bank lookup, and one WAV writer.

`*.esx` is gitignored, so every corpus-dependent test SKIPS rather than fails on
a fresh clone. That is deliberate: a checkout with no banks should still be able
to prove the codec and the UI wiring work.
"""

from __future__ import annotations

import os
import wave

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESEARCH = os.path.join(PROJECT, "research")

#: Corpus banks in preference order. e4.esx is the most useful fixture: it
#: round-trips byte-identically AND reports 17 offset_past_eof findings, so it
#: exercises both the write path and the refusal path.
CORPUS_CANDIDATES = (
    os.path.join(PROJECT, "corpus", "card_backup_2026-08-22", "e4.esx"),
    os.path.join(PROJECT, "corpus", "Chronic-Interactive.esx"),
    os.path.join(PROJECT, "corpus", "card_backup_2026-08-22", "e5.esx"),
    os.path.join(PROJECT, "spike_a", "default.esx"),
)


@pytest.fixture(scope="session")
def qapp():
    """The one QApplication. Qt permits a single instance per process."""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from ui.theme import apply as apply_theme

    app = QApplication.instance() or QApplication(["esx-test"])
    apply_theme(app)
    return app


@pytest.fixture(scope="session")
def corpus_path() -> str:
    """Path to a real bank, or skip."""
    for path in CORPUS_CANDIDATES:
        if os.path.exists(path):
            return path
    pytest.skip("no corpus bank available (*.esx is gitignored)")


@pytest.fixture(scope="session")
def bank(corpus_path):
    """A parsed corpus Bank, shared read-mostly across the suite."""
    from codec.reader import BankReader
    return BankReader().read_file(corpus_path)


def make_wav(path: str, seconds: float = 0.05, rate: int = 44100,
             channels: int = 1) -> str:
    """Write a tiny silent WAV so staging has a real header to probe."""
    frames = int(rate * seconds)
    with wave.open(path, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * frames * channels)
    return path


def make_staging(tmp_path):
    """A StagingBank rooted in tmp_path, using the WAV passthrough adapters."""
    from audio.passthrough import WavPassthroughConverter, NullKeyDetector
    from workspace.limits import SampleLimitPolicy
    from workspace.staging import SessionWorkspace, StagingBank

    session = SessionWorkspace(temp_root=str(tmp_path))
    return StagingBank(WavPassthroughConverter(), NullKeyDetector(),
                       SampleLimitPolicy(), session)
