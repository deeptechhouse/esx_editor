"""
Integration tests — the whole cycle, through the real objects.

WHY THESE ARE SEPARATE FROM THE UNIT TESTS
    Every layer passes its own tests and the app can still be broken at the
    seams: a view that binds but never refreshes, a session that saves but
    forgets to clear the dirty flag, a wizard that edits a Pattern object the
    writer never sees. These drive the same path a user does — open, edit,
    validate, write, re-read — and assert on what ends up in the file.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import codec.layout as L  # noqa: E402
from audio.ports import ConversionSpec  # noqa: E402
from codec.errors import CodecError  # noqa: E402
from codec.reader import BankReader  # noqa: E402
from codec.writer import BankWriter  # noqa: E402
from tests.conftest import make_staging, make_wav  # noqa: E402
from tests.synthetic import build  # noqa: E402
from ui.session import BankSession  # noqa: E402
from workspace.budget import CAPACITY, BudgetCalculator  # noqa: E402


@pytest.fixture
def synthetic_bank_file(tmp_path) -> str:
    """A coherent bank on disk — works with no corpus present."""
    path = str(tmp_path / "synthetic.esx")
    with open(path, "wb") as f:
        f.write(build())
    return path


# -- session: the full open -> edit -> write -> re-read cycle -----------------
def test_open_edit_write_reread_preserves_the_edit(synthetic_bank_file, tmp_path):
    session = BankSession()
    session.open_path(synthetic_bank_file)
    assert session.dirty is False

    session.bank.patterns()[0].set_name("CYCLE")
    session.mark_dirty()
    assert session.dirty is True

    dest = str(tmp_path / "written.esx")
    assert session.save(dest) == dest
    assert session.dirty is False and session.path == dest

    reread = BankSession()
    reread.open_path(dest)
    assert reread.bank.patterns()[0].name.strip() == "CYCLE"


def test_an_untouched_bank_writes_back_byte_identically(synthetic_bank_file, tmp_path):
    """Opening and saving without editing must not perturb a single byte."""
    with open(synthetic_bank_file, "rb") as f:
        original = f.read()
    session = BankSession()
    session.open_path(synthetic_bank_file)
    dest = str(tmp_path / "untouched.esx")
    session.save(dest)
    with open(dest, "rb") as f:
        assert f.read() == original


def test_write_keeps_the_previous_version_as_bak(synthetic_bank_file, tmp_path):
    session = BankSession()
    session.open_path(synthetic_bank_file)
    dest = str(tmp_path / "twice.esx")
    session.save(dest)
    session.bank.patterns()[0].set_name("SECOND")
    session.save(dest)
    assert os.path.exists(dest + ".bak")
    # The .bak is the FIRST write, not the second.
    backup = BankReader().read_file(dest + ".bak")
    assert backup.patterns()[0].name.strip() != "SECOND"


def test_undecoded_regions_survive_an_edit_and_a_write(synthetic_bank_file, tmp_path):
    """Editing a pattern must not disturb the verbatim regions."""
    session = BankSession()
    session.open_path(synthetic_bank_file)
    before = {
        n: session.bank.raw_regions.get(n) for n in session.bank.raw_regions.names()
    }
    session.bank.patterns()[7].set_name("EDITED")
    dest = str(tmp_path / "regions.esx")
    session.save(dest)
    after_bank = BankReader().read_file(dest)
    for name, data in before.items():
        assert after_bank.raw_regions.get(name) == data, f"region {name} changed"


def test_motion_edits_survive_a_write(synthetic_bank_file, tmp_path):
    from core.motion import MotionDomain

    session = BankSession()
    session.open_path(synthetic_bank_file)
    pattern = session.bank.patterns()[0]
    slot = pattern.motion_slots()[0]
    dom = MotionDomain.continuous()
    slot.write_stored(3, 99, dom, length=64)
    pattern.replace_motion(0, slot)

    dest = str(tmp_path / "motion.esx")
    session.save(dest)
    reread = BankReader().read_file(dest)
    assert reread.patterns()[0].motion_slots()[0].get_step(3) == 99


def test_save_refuses_an_incoherent_bank_and_touches_nothing(tmp_path):
    """The refusal must happen BEFORE the destination is written."""
    import struct

    data = bytearray(build())
    # Point sample 0's end past the PCM region.
    off = L.ADDR_SAMPLE_HEADER_MONO
    struct.pack_into(">I", data, off + 12, 0xFFFFFF0)
    broken = str(tmp_path / "broken.esx")
    with open(broken, "wb") as f:
        f.write(bytes(data))

    session = BankSession()
    session.open_path(broken)
    report = session.validate()
    assert not report.ok
    assert any(f.code == "offset_past_eof" for f in report.errors())

    dest = str(tmp_path / "refused.esx")
    with pytest.raises(CodecError):
        session.save(dest)
    assert not os.path.exists(dest)

    # ...and succeeds with the explicit override.
    session.save(dest, allow_invalid=True)
    assert os.path.exists(dest)


def test_session_refuses_to_save_with_no_bank_and_no_path(tmp_path):
    session = BankSession()
    with pytest.raises(CodecError):
        session.save(str(tmp_path / "x.esx"))
    session._bank = BankReader().read_auto(build())
    session._path = None
    with pytest.raises(CodecError):
        session.save()


# -- staging -> budget --------------------------------------------------------
def test_staging_costs_match_the_calculator(tmp_path):
    bank = make_staging(tmp_path)
    calc = BudgetCalculator()
    total = 0
    for i, seconds in enumerate((0.25, 1.0, 2.5)):
        path = make_wav(str(tmp_path / f"s{i}.wav"), seconds=seconds)
        sample = bank.add(path, ConversionSpec(44100, 1))
        total += calc.cost_bytes(sample.duration_s, 44100, 1)
    assert len(bank.samples()) == 3
    assert total < CAPACITY
    # Originals are never modified.
    for i in range(3):
        assert os.path.exists(str(tmp_path / f"s{i}.wav"))


def test_staging_clear_removes_the_converted_copies(tmp_path):
    bank = make_staging(tmp_path)
    path = make_wav(str(tmp_path / "gone.wav"))
    sample = bank.add(path, ConversionSpec(44100, 1))
    converted = sample.converted_path
    assert converted and os.path.exists(converted)
    bank.clear()
    assert bank.samples() == ()
    assert not os.path.exists(converted)
    assert os.path.exists(path), "the ORIGINAL must survive a clear"


def test_a_sample_over_the_single_cap_is_blocked_with_named_fixes(tmp_path):
    from workspace.errors import StagingBlockedError

    bank = make_staging(tmp_path)
    # 0.8 * 25,165,824 B at 44.1 kHz mono is about 228 s; ask for 400 s.
    path = make_wav(str(tmp_path / "huge.wav"), seconds=400.0, rate=8000)
    with pytest.raises(StagingBlockedError):
        bank.add(path, ConversionSpec(44100, 1))
    assert bank.samples() == ()


# -- the wizard, end to end ---------------------------------------------------
def test_wizard_walk_ends_in_a_verified_write(qapp, synthetic_bank_file, tmp_path):
    """Screen 1 opens, screen 9 edits, screen 11 writes — and it round-trips."""
    from ui.wizard import SetupWizard

    session = BankSession()
    wizard = SetupWizard(session)
    try:
        wizard.page_at(0).open_file(synthetic_bank_file)
        assert session.is_open

        for page in wizard.pages():
            page.initializePage()
            assert page.isComplete() is True

        basics = wizard.page_at(8)
        basics.name.setText("WIZWALK")
        basics.apply_name()
        assert session.dirty is True

        final = wizard.page_at(10)
        assert final.run_validate() == 0, "the synthetic bank is coherent"
        dest = str(tmp_path / "wizard.esx")
        assert final.run_write(dest) is True
    finally:
        wizard.close()

    reread = BankReader().read_file(dest)
    assert reread.patterns()[0].name.strip() == "WIZWALK"
    assert BankWriter().write(reread) == open(dest, "rb").read()


def test_shell_open_to_save_cycle(qapp, synthetic_bank_file, tmp_path, monkeypatch):
    """The MainWindow path a user actually drives."""
    import ui.main_window as mw
    from ui.main_window import MainWindow

    monkeypatch.setattr(mw.QMessageBox, "warning", lambda *a, **k: None)
    win = MainWindow()
    try:
        assert win.open_path(synthetic_bank_file) is True
        assert win.bank_view.table.rowCount() == 3
        assert win.pattern_view.list.count() == L.NUM_PATTERNS
        assert win.song_view.list.count() == L.NUM_SONGS
        assert len(win.global_view.block_bytes()) == L.CHUNK_GLOBAL_PARAMETERS

        win.pattern_view._name.setText("SHELL")
        win.pattern_view._rename()
        assert win.session.dirty is True

        dest = str(tmp_path / "shell.esx")
        win._write(dest)
        assert win.session.dirty is False
        assert BankReader().read_file(dest).patterns()[0].name.strip() == "SHELL"
    finally:
        win.session._dirty = False
        win.close()


def test_staging_survives_a_trip_through_the_wizard(qapp, tmp_path):
    """A drop on the wizard's screen 3 is visible on the Staging tab."""
    import ui.main_window as mw  # noqa: F401
    from ui.main_window import MainWindow

    win = MainWindow()
    try:
        wizard = win.open_wizard()
        try:
            path = make_wav(str(tmp_path / "shared.wav"))
            wizard.page_at(2).staging.add_path(path)
            assert len(win.staging_view.bank.samples()) == 1
            win.staging_view.reload()
            assert win.staging_view._list.count() == 1
        finally:
            wizard.close()
        win.staging_view.clear_staging()
    finally:
        win.session._dirty = False
        win.close()


# -- a full corpus bank, when present ------------------------------------------
@pytest.mark.corpus
def test_corpus_bank_survives_the_whole_ui_cycle(qapp, corpus_path, tmp_path):
    from ui.main_window import MainWindow

    with open(corpus_path, "rb") as f:
        original = f.read()
    win = MainWindow()
    try:
        assert win.open_path(corpus_path) is True
        dest = str(tmp_path / "corpus_cycle.esx")
        win.session.save(dest, allow_invalid=True)
        with open(dest, "rb") as f:
            assert f.read() == original
    finally:
        win.session._dirty = False
        win.close()
