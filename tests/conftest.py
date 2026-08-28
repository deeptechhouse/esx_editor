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

#: The one bank saved on the hardware WITH a song in it. It is what the song
#: chain was decoded from, so it is kept separate: it is not interchangeable
#: with the others the way the general corpus banks are.
SONG_BANK = os.path.join(PROJECT, "corpus", "Chronic-Interactive-song.esx")


@pytest.fixture(scope="session")
def qapp():
    """The one QApplication. Qt permits a single instance per process."""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    from ui.theme import apply as apply_theme

    app = QApplication.instance() or QApplication(["esx-test"])
    apply_theme(app)
    return app


#: Set ESX_NO_CORPUS=1 to simulate a fresh clone / CI runner, where no bank
#: exists. Used to prove the suite and its coverage gates hold without them.
NO_CORPUS = os.environ.get("ESX_NO_CORPUS") == "1"


def available_corpus() -> tuple[str, ...]:
    """Every corpus bank present, honouring the ESX_NO_CORPUS override."""
    if NO_CORPUS:
        return ()
    return tuple(p for p in CORPUS_CANDIDATES if os.path.exists(p))


@pytest.fixture(scope="session")
def song_bank_path() -> str:
    """The hardware-saved bank containing a song, or skip."""
    if NO_CORPUS or not os.path.exists(SONG_BANK):
        pytest.skip("no hardware-saved song bank available (*.esx is gitignored)")
    return SONG_BANK


@pytest.fixture(scope="session")
def corpus_path() -> str:
    """Path to a real bank, or skip."""
    present = available_corpus()
    if present:
        return present[0]
    pytest.skip("no corpus bank available (*.esx is gitignored)")


@pytest.fixture(scope="session")
def bank(corpus_path):
    """A parsed corpus Bank, shared read-mostly across the suite."""
    from codec.reader import BankReader

    return BankReader().read_file(corpus_path)


@pytest.fixture
def coherent_bank():
    """The first corpus bank that validates clean, freshly parsed.

    The default `bank` fixture resolves to e4.esx, which round-trips but has
    16 of 18 sample headers pointing past EOF — deliberately, as a fixture for
    the refusal paths. Tests that mutate a bank need one that is actually
    coherent, and a fresh parse so mutations do not leak between tests.
    """
    from codec.reader import BankReader
    from codec.validator import BankValidator

    for path in available_corpus():
        parsed = BankReader().read_file(path)
        if BankValidator().validate(parsed).ok:
            return parsed
    pytest.skip("no coherent corpus bank available")


@pytest.fixture
def stereo_bank():
    """The first corpus bank with populated stereo slots, freshly parsed.

    Chronic-Interactive.esx has 40. They are what established the stereo header
    layout on 2026-08-23 (see codec/layout.py).
    """
    import codec.layout as L
    from codec.reader import BankReader

    for path in available_corpus():
        parsed = BankReader().read_file(path)
        if any(s for s in parsed.samples()[L.NUM_SAMPLES_MONO :] if not s.empty):
            return parsed
    pytest.skip("no corpus bank with populated stereo slots")


def make_wav(
    path: str, seconds: float = 0.05, rate: int = 44100, channels: int = 1
) -> str:
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
    from audio.passthrough import NullKeyDetector, WavPassthroughConverter
    from workspace.limits import SampleLimitPolicy
    from workspace.staging import SessionWorkspace, StagingBank

    session = SessionWorkspace(temp_root=str(tmp_path))
    return StagingBank(
        WavPassthroughConverter(), NullKeyDetector(), SampleLimitPolicy(), session
    )
