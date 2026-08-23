"""WF6 wizard: the eleven guided-setup screens — offscreen Qt.

Two properties matter most and are asserted first: the flow is exactly eleven
screens (TDD §09), and every one of them is skippable — `isComplete()` must be
True everywhere, or an experienced user gets trapped behind a disabled Next.
The rest checks that each screen reports the model honestly.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

import codec.layout as L  # noqa: E402
from audio.ports import ConversionSpec  # noqa: E402
from tests.conftest import make_staging, make_wav  # noqa: E402
from ui.session import BankSession  # noqa: E402
from ui.wizard import PAGE_COUNT, SetupWizard, WizardContext  # noqa: E402
from ui.wizard.pages import (  # noqa: E402
    PAGE_CLASSES,
    AddSamplesPage,
    CardCheckPage,
    KeyAnalysisPage,
    MotionPage,
    NamingPage,
    PartSetupPage,
    PatternBasicsPage,
    QualityBudgetPage,
    SlotAssignmentPage,
    StartPage,
    ValidateWritePage,
)
from workspace.budget import CAPACITY  # noqa: E402
from workspace.naming import SLOT_NAME_LEN  # noqa: E402
from workspace.staging import StagingBank  # noqa: E402


@pytest.fixture
def opened(corpus_path) -> BankSession:
    s = BankSession()
    s.open_path(corpus_path)
    return s


def build(session: BankSession, staging: StagingBank | None = None) -> SetupWizard:
    return SetupWizard(session, staging_bank=staging)


# -- flow shape --------------------------------------------------------------
def test_wizard_has_exactly_eleven_pages(qapp) -> None:
    wiz = build(BankSession())
    assert PAGE_COUNT == len(PAGE_CLASSES) == 11
    assert len(wiz.pages()) == 11
    assert len(wiz.pageIds()) == 11


def test_every_page_is_skippable(qapp) -> None:
    """isComplete() must be True on every screen (TDD §09)."""
    wiz = build(BankSession())
    for i, page in enumerate(wiz.pages()):
        page.initializePage()
        assert page.isComplete() is True, f"page {i + 1} blocks Next"


def test_pages_are_in_spec_order(qapp) -> None:
    expected = (
        StartPage,
        CardCheckPage,
        AddSamplesPage,
        QualityBudgetPage,
        KeyAnalysisPage,
        NamingPage,
        SlotAssignmentPage,
        PartSetupPage,
        PatternBasicsPage,
        MotionPage,
        ValidateWritePage,
    )
    assert PAGE_CLASSES == expected
    wiz = build(BankSession())
    for i, cls in enumerate(expected):
        assert isinstance(wiz.page_at(i), cls)
        assert wiz.page_at(i).title().startswith(f"{i + 1} ·")


def test_every_page_states_its_reasoning(qapp) -> None:
    """Each screen must explain the decision, not just ask for it (TDD §09)."""
    from PySide6.QtWidgets import QLabel

    wiz = build(BankSession())
    for page in wiz.pages():
        assert page.subTitle(), f"{page.title()} has no subtitle"
        texts = " ".join(lab.text() for lab in page.findChildren(QLabel))
        assert len(texts) > 80, f"{page.title()} explains too little"


def test_wizard_walks_a_real_bank_without_throwing(qapp, opened) -> None:
    wiz = build(opened)
    for page in wiz.pages():
        page.initializePage()
        page.refresh()
    assert wiz.context.session is opened


# -- context -----------------------------------------------------------------
def test_context_reports_no_staging_before_page_three(qapp) -> None:
    ctx = WizardContext(BankSession())
    assert ctx.staging_bank is None
    assert ctx.staged_samples() == ()
    assert ctx.first_pattern() is None


def test_context_notify_is_optional_and_fires(qapp) -> None:
    hits = []
    ctx = WizardContext(BankSession(), on_changed=lambda: hits.append(1))
    ctx.notify_changed()
    assert hits == [1]
    WizardContext(BankSession()).notify_changed()  # no callback: must not throw


# -- 1 Start -----------------------------------------------------------------
def test_start_page_opens_a_file(qapp, corpus_path) -> None:
    session = BankSession()
    wiz = build(session)
    page = wiz.page_at(0)
    page.open_file(corpus_path)
    assert session.is_open and session.path == corpus_path
    assert corpus_path in page.status.text()


def test_start_page_reports_open_failure_in_page(qapp, tmp_path) -> None:
    """No modal dialog: a bad file must not trap the user behind a QMessageBox."""
    bad = tmp_path / "not-a-bank.esx"
    bad.write_bytes(b"nope")
    wiz = build(BankSession())
    page = wiz.page_at(0)
    page.open_file(str(bad))
    assert "open failed" in page.status.text()
    assert page.isComplete() is True


def test_start_page_creates_a_blank_bank(qapp) -> None:
    session = BankSession()
    wiz = build(session)
    page = wiz.page_at(0)
    page.create_new()
    if not session.is_open:
        pytest.skip(f"blank template unavailable: {page.status.text()}")
    assert session.dirty and session.path is None
    assert "untitled" in page.status.text()


# -- 2 Card check ------------------------------------------------------------
def test_card_check_names_the_backup_path(qapp, opened) -> None:
    wiz = build(opened)
    page = wiz.page_at(1)
    page.refresh()
    assert page.confirm.isChecked() is False  # never pre-consented
    assert f"{opened.path}.bak" in page.status.text()
    assert page.isComplete() is True  # skippable even unchecked


# -- 3 Add samples -----------------------------------------------------------
def test_add_samples_page_reuses_the_shared_staging_bank(qapp, tmp_path) -> None:
    model = make_staging(tmp_path)
    wiz = build(BankSession(), staging=model)
    page = wiz.page_at(2)
    assert page.staging.bank is model
    assert wiz.staging_bank() is model
    page.staging.add_path(make_wav(str(tmp_path / "hat.wav")))
    assert len(model.samples()) == 1
    assert wiz.context.staged_samples() == model.samples()


def test_add_samples_page_creates_a_bank_when_given_none(qapp) -> None:
    wiz = build(BankSession())
    assert wiz.staging_bank() is not None
    assert wiz.staging_bank() is wiz.page_at(2).staging.bank


# -- 4 Quality budget --------------------------------------------------------
def test_budget_page_costs_the_staged_set(qapp, tmp_path) -> None:
    model = make_staging(tmp_path)
    model.add(make_wav(str(tmp_path / "a.wav"), seconds=1.0), ConversionSpec(44100, 1))
    wiz = build(BankSession(), staging=model)
    page = wiz.page_at(3)
    page.refresh()
    assert page.staged_cost() > 0
    assert page.proposals() == (), "1 s at 44.1 kHz is nowhere near capacity"
    assert "Within budget" in page.proposal.text()
    assert f"of {CAPACITY:,} B" in page.summary.text()


def test_budget_page_proposes_trims_in_order_when_over(qapp, tmp_path) -> None:
    """Trim first, fold second, drop the rate last — rate is irreversible."""
    model = make_staging(tmp_path)
    wiz = build(BankSession(), staging=model)
    page = wiz.page_at(3)
    page.staged_cost = lambda: CAPACITY + 1_000_000
    props = page.proposals()
    assert props and "Over capacity" in props[0]
    assert "Trim" in props[1]
    assert "Drop the tier" in props[-1]


def test_budget_page_with_nothing_staged(qapp) -> None:
    wiz = build(BankSession())
    page = wiz.page_at(3)
    page.refresh()
    assert page.staged_cost() == 0
    assert page.proposals() == ()


# -- 5 Key analysis ----------------------------------------------------------
def test_key_page_says_no_key_rather_than_guessing(qapp, tmp_path) -> None:
    model = make_staging(tmp_path)
    model.add(make_wav(str(tmp_path / "b.wav")), ConversionSpec(44100, 1))
    wiz = build(BankSession(), staging=model)
    page = wiz.page_at(4)
    page.refresh()
    assert page.table.rowCount() == 1
    assert page.table.item(0, 1).text() == "— none —"
    assert page.table.item(0, 2).text() == "— none —"
    assert "0 with a key" in page.status.text()


# -- 6 Naming ----------------------------------------------------------------
def test_naming_preview_is_always_eight_characters(qapp) -> None:
    wiz = build(BankSession())
    page = wiz.page_at(5)
    page.example.setText("my_bassline_take3")
    for style_row in range(page.style.count()):
        page.style.setCurrentIndex(style_row)
        for key_row in range(page.camelot.count()):
            page.camelot.setCurrentIndex(key_row)
            packed = page.preview_lines()[0].split("|")[1]
            assert len(packed) == SLOT_NAME_LEN == 8


def test_naming_preview_includes_camelot_prefix(qapp) -> None:
    wiz = build(BankSession())
    page = wiz.page_at(5)
    page.example.setText("bassline")
    page.camelot.setCurrentIndex(page.camelot.findData("8A"))
    page.style.setCurrentIndex(
        [page.style.itemData(i) for i in range(page.style.count())].index("short")
    )
    packed = page.preview_lines()[0].split("|")[1]
    assert packed.startswith("a08")
    assert page.current_style() == "short"


def test_naming_previews_every_staged_sample(qapp, tmp_path) -> None:
    model = make_staging(tmp_path)
    model.add(make_wav(str(tmp_path / "c.wav")), ConversionSpec(44100, 1))
    model.add(make_wav(str(tmp_path / "d.wav")), ConversionSpec(44100, 1))
    wiz = build(BankSession(), staging=model)
    page = wiz.page_at(5)
    page.refresh()
    lines = page.preview_lines()
    assert len(lines) == 3  # the example plus both staged files
    assert page.preview.toPlainText() == "\n".join(lines)


# -- 7 Slot assignment -------------------------------------------------------
def test_slot_page_reports_free_pools_separately(qapp, opened) -> None:
    wiz = build(opened)
    page = wiz.page_at(6)
    page.refresh()
    mono, stereo = page.free_slots()
    samples = opened.bank.samples()
    assert mono == sum(1 for s in samples[: L.NUM_SAMPLES_MONO] if s.empty)
    assert stereo == sum(1 for s in samples[L.NUM_SAMPLES_MONO :] if s.empty)
    assert f"/{L.NUM_SAMPLES_MONO}" in page.pools.text()
    assert f"/{L.NUM_SAMPLES_STEREO}" in page.pools.text()


def test_slot_page_full_pools_with_no_bank(qapp) -> None:
    wiz = build(BankSession())
    page = wiz.page_at(6)
    assert page.free_slots() == (L.NUM_SAMPLES_MONO, L.NUM_SAMPLES_STEREO)


def test_slot_page_lists_packed_names(qapp, tmp_path) -> None:
    model = make_staging(tmp_path)
    model.add(make_wav(str(tmp_path / "e.wav")), ConversionSpec(44100, 1))
    wiz = build(BankSession(), staging=model)
    page = wiz.page_at(6)
    page.refresh()
    assert page.table.rowCount() == 1
    assert page.table.item(0, 1).text() == model.samples()[0].slot_name()
    assert page.table.item(0, 2).text() == "mono"


# -- 8 Part setup ------------------------------------------------------------
def test_part_page_shows_raw_parts_not_sample_numbers(qapp, opened) -> None:
    wiz = build(opened)
    page = wiz.page_at(7)
    page.refresh()
    parts = opened.bank.patterns()[0].parts()
    assert page.table.rowCount() == len(parts) == 16
    assert page.table.item(0, 1).text() == parts[0].kind
    assert page.table.item(0, 3).text() == str(len(parts[0].to_bytes()))
    with pytest.raises(NotImplementedError):
        _ = parts[0].sample_number  # the page must never call this


def test_part_page_with_no_bank(qapp) -> None:
    wiz = build(BankSession())
    page = wiz.page_at(7)
    page.refresh()
    assert page.table.rowCount() == 0
    assert "No bank open" in page.status.text()


# -- 9 Pattern basics --------------------------------------------------------
def test_pattern_basics_shows_header_hex_only(qapp, opened) -> None:
    wiz = build(opened)
    page = wiz.page_at(8)
    page.refresh()
    pat = opened.bank.patterns()[0]
    assert page.header.toPlainText() == pat.header.to_bytes().hex(" ")
    assert f"/{L.NUM_PARAMETERS_MOTION} motion" in page.motion.text()
    # Tempo IS decoded now; length/beat/last-step are still unproven and the
    # page must never call them.
    assert page.tempo.value() == pytest.approx(pat.header.tempo, abs=0.05)
    for field in ("length_bars", "last_step", "playable_steps"):
        with pytest.raises(NotImplementedError):
            getattr(pat.header, field)


def test_pattern_basics_rename_marks_dirty(qapp, opened) -> None:
    hits = []
    wiz = SetupWizard(opened, on_changed=lambda: hits.append(1))
    page = wiz.page_at(8)
    page.refresh()
    page.name.setText("WIZNAME")
    page.apply_name()
    assert opened.bank.patterns()[0].name.strip() == "WIZNAME"
    assert opened.dirty is True
    assert hits == [1]
    page.apply_name()  # idempotent: no second notification
    assert hits == [1]


# -- 10 Motion ---------------------------------------------------------------
def test_motion_page_reports_the_slot_budget(qapp, opened) -> None:
    wiz = build(opened)
    page = wiz.page_at(9)
    page.refresh()
    pat = opened.bank.patterns()[0]
    assert page.slots.count() == L.NUM_PARAMETERS_MOTION == 24
    assert f"{pat.motion_slots_used()}/24" in page.status.text()
    assert "Motion tab" in page.status.text()


# -- 11 Validate & write -----------------------------------------------------
def test_validate_page_lists_findings_without_repairing(qapp, opened) -> None:
    wiz = build(opened)
    page = wiz.page_at(10)
    n = page.run_validate()
    report = opened.validate()
    assert n == len(report) == page.findings.count()
    assert page.allow_invalid.isChecked() is False
    if report.ok:
        assert "safe to write" in page.status.text()
    else:
        assert "override" in page.status.text()


def test_validate_page_without_a_bank(qapp) -> None:
    wiz = build(BankSession())
    page = wiz.page_at(10)
    assert page.run_validate() == 0
    assert "no bank is open" in page.status.text()
    assert page.run_write("/nowhere/x.esx") is False
    assert "No bank open" in page.status.text()


def test_validate_page_refuses_an_incoherent_bank(qapp, opened, tmp_path) -> None:
    """Findings are reported, never auto-repaired; the write is refused."""
    wiz = build(opened)
    page = wiz.page_at(10)
    if opened.validate().ok:
        pytest.skip("this corpus bank is coherent; nothing to refuse")
    dest = str(tmp_path / "out.esx")
    assert page.run_write(dest) is False
    assert "refus" in page.status.text().lower()
    assert not os.path.exists(dest)


def test_validate_page_writes_with_override_and_keeps_a_backup(
    qapp, opened, tmp_path
) -> None:
    wiz = build(opened)
    page = wiz.page_at(10)
    page.allow_invalid.setChecked(True)
    dest = str(tmp_path / "written.esx")
    assert page.run_write(dest) is True
    assert os.path.exists(dest)
    assert "verified by re-read" in page.status.text()
    assert opened.dirty is False and opened.path == dest
    # a second write preserves the previous version
    assert page.run_write(dest) is True
    assert os.path.exists(dest + ".bak")


def test_wizard_write_round_trips_the_source_bytes(qapp, opened, tmp_path) -> None:
    """The round-trip gate must survive a trip through the wizard."""
    source = open(opened.path, "rb").read()
    wiz = build(opened)
    page = wiz.page_at(10)
    page.allow_invalid.setChecked(True)
    dest = str(tmp_path / "rt.esx")
    assert page.run_write(dest) is True
    assert open(dest, "rb").read() == source


# -- remaining dialog and error paths ----------------------------------------
def test_start_page_browse_opens_the_chosen_file(qapp, corpus_path, monkeypatch):
    import ui.wizard.pages as pages

    monkeypatch.setattr(
        pages.QFileDialog, "getOpenFileName", lambda *a, **k: (corpus_path, "")
    )
    session = BankSession()
    wiz = build(session)
    wiz.page_at(0).browse()
    assert session.path == corpus_path
    assert wiz.page_at(0).open_radio.isChecked() is True


def test_start_page_browse_cancelled_does_nothing(qapp, monkeypatch) -> None:
    import ui.wizard.pages as pages

    monkeypatch.setattr(pages.QFileDialog, "getOpenFileName", lambda *a, **k: ("", ""))
    session = BankSession()
    wiz = build(session)
    wiz.page_at(0).browse()
    assert session.is_open is False


def test_start_page_reports_a_missing_template(qapp, monkeypatch) -> None:
    from codec.errors import CodecError

    session = BankSession()
    monkeypatch.setattr(
        session, "new_bank", lambda: (_ for _ in ()).throw(CodecError("no template"))
    )
    wiz = build(session)
    page = wiz.page_at(0)
    page.create_new()
    assert "blank template unavailable" in page.status.text()
    assert page.isComplete() is True


def test_budget_proposal_names_the_stereo_fold(qapp, tmp_path) -> None:
    """With stereo staged, folding to mono is offered before the rate drop."""
    model = make_staging(tmp_path)
    model.add(make_wav(str(tmp_path / "st.wav")), ConversionSpec(44100, 2))
    wiz = build(BankSession(), staging=model)
    page = wiz.page_at(3)
    page.staged_cost = lambda: CAPACITY * 2
    props = page.proposals()
    assert any("Fold 1 stereo" in p for p in props)
    assert props[-1].startswith("3.")


def test_naming_preview_reports_a_bad_camelot_code(qapp) -> None:
    wiz = build(BankSession())
    page = wiz.page_at(5)
    page.camelot.addItem("bogus", "99Z")
    page.camelot.setCurrentIndex(page.camelot.count() - 1)
    assert "<unknown Camelot code" in page.preview_lines()[0]


def test_pattern_basics_rename_without_a_bank_is_a_no_op(qapp) -> None:
    wiz = build(BankSession())
    page = wiz.page_at(8)
    page.refresh()
    page.name.setText("NOBANK")
    page.apply_name()  # must not raise
    assert "No bank open" in page.motion.text()


def test_validate_page_asks_where_to_save_when_there_is_no_path(
    qapp, tmp_path, monkeypatch
) -> None:
    import ui.wizard.pages as pages

    session = BankSession()
    try:
        session.new_bank()
    except Exception as exc:
        pytest.skip(f"blank template unavailable: {exc}")
    dest = str(tmp_path / "asked.esx")
    monkeypatch.setattr(
        pages.QFileDialog, "getSaveFileName", lambda *a, **k: (dest, "")
    )
    wiz = build(session)
    page = wiz.page_at(10)
    page.allow_invalid.setChecked(True)
    assert page.run_write() is True
    assert os.path.exists(dest)


def test_validate_page_write_can_be_cancelled(qapp, monkeypatch) -> None:
    import ui.wizard.pages as pages

    session = BankSession()
    try:
        session.new_bank()
    except Exception as exc:
        pytest.skip(f"blank template unavailable: {exc}")
    monkeypatch.setattr(pages.QFileDialog, "getSaveFileName", lambda *a, **k: ("", ""))
    wiz = build(session)
    page = wiz.page_at(10)
    assert page.run_write() is False
    assert "cancelled" in page.status.text()


def test_validate_page_ready_message_names_the_target(qapp, opened) -> None:
    wiz = build(opened)
    page = wiz.page_at(10)
    page.refresh()
    assert opened.path in page.status.text()


# -- 7 Slot assignment: the commit path ---------------------------------------
def test_slot_page_commits_staged_samples_into_the_bank(qapp, tmp_path) -> None:
    """The screen that finally does the thing the app exists for."""
    from codec.reader import BankReader
    from tests.synthetic import build as build_bank

    session = BankSession()
    session._bank = BankReader().read_auto(build_bank(num_mono=0, pcm_bytes=16))
    model = make_staging(tmp_path)
    model.add(make_wav(str(tmp_path / "kick.wav")), ConversionSpec(44100, 1))
    model.add(make_wav(str(tmp_path / "snare.wav")), ConversionSpec(44100, 1))

    wiz = SetupWizard(session, staging_bank=model)
    page = wiz.page_at(6)
    page.refresh()
    assert page.targets() == (0, 1)
    assert page.commit_button.isEnabled()

    assert page.commit() == 2
    bank = session.bank
    assert bank.sample_area_header()[:2] == (2, 0)
    assert not bank.samples()[0].empty and not bank.samples()[1].empty
    assert session.dirty is True
    assert "Committed 2 sample(s)" in page.status.text()
    assert "Nothing is on disk" in page.status.text()


def test_slot_page_commit_survives_a_write_and_reread(qapp, tmp_path) -> None:
    from codec.reader import BankReader
    from tests.synthetic import build as build_bank

    session = BankSession()
    session._bank = BankReader().read_auto(build_bank(num_mono=0, pcm_bytes=16))
    model = make_staging(tmp_path)
    model.add(make_wav(str(tmp_path / "tom.wav")), ConversionSpec(44100, 1))

    wiz = SetupWizard(session, staging_bank=model)
    assert wiz.page_at(6).commit() == 1

    final = wiz.page_at(10)
    assert final.run_validate() == 0, "a committed bank must stay coherent"
    dest = str(tmp_path / "committed.esx")
    assert final.run_write(dest) is True

    reread = BankReader().read_file(dest)
    assert reread.sample_area_header()[:2] == (1, 0)
    slot = reread.samples()[0]
    assert not slot.empty
    assert slot.sample_rate == 44100
    assert slot.offset_end > slot.offset_start


def test_slot_page_refuses_when_nothing_is_staged(qapp) -> None:
    from codec.reader import BankReader
    from tests.synthetic import build as build_bank

    session = BankSession()
    session._bank = BankReader().read_auto(build_bank(num_mono=0, pcm_bytes=16))
    wiz = build(session)
    page = wiz.page_at(6)
    page.refresh()
    assert page.commit() == 0
    assert "Nothing staged" in page.status.text()
    assert not page.commit_button.isEnabled()


def test_slot_page_refuses_with_no_bank_open(qapp, tmp_path) -> None:
    model = make_staging(tmp_path)
    model.add(make_wav(str(tmp_path / "x.wav")), ConversionSpec(44100, 1))
    wiz = SetupWizard(BankSession(), staging_bank=model)
    page = wiz.page_at(6)
    page.refresh()
    assert page.commit() == 0
    assert "No bank open" in page.status.text()


def test_slot_page_refuses_when_there_are_too_few_free_slots(qapp, tmp_path) -> None:
    """A full bank must say so, not commit a partial batch."""
    from codec.reader import BankReader
    from tests.synthetic import build as build_bank

    session = BankSession()
    bank = BankReader().read_auto(build_bank(num_mono=0, pcm_bytes=16))
    session._bank = bank
    model = make_staging(tmp_path)
    for i in range(3):
        model.add(make_wav(str(tmp_path / f"m{i}.wav")), ConversionSpec(44100, 1))

    wiz = SetupWizard(session, staging_bank=model)
    page = wiz.page_at(6)
    # Only one free slot: fill every other mono slot first.
    for i in range(1, L.NUM_SAMPLES_MONO):
        bank.commit_sample(
            i, b"\x00" * 4, stereo=False, sample_rate=44100, name=f"F{i}"
        )
    page.refresh()
    assert page.commit() == 0
    assert "Only 1 free mono slot" in page.status.text()
    assert bank.sample_area_header()[0] == L.NUM_SAMPLES_MONO - 1


def test_pattern_basics_edits_the_tempo(qapp, opened) -> None:
    hits = []
    wiz = SetupWizard(opened, on_changed=lambda: hits.append(1))
    page = wiz.page_at(8)
    page.refresh()
    page.tempo.setValue(137.5)
    page.apply_tempo(137.5)
    assert opened.bank.patterns()[0].header.tempo == pytest.approx(137.5, abs=0.01)
    assert opened.dirty is True
    assert hits


def test_pattern_basics_refresh_does_not_count_as_an_edit(qapp, opened) -> None:
    """Loading a pattern into the spinbox must not mark the bank modified."""
    wiz = build(opened)
    page = wiz.page_at(8)
    page.refresh()
    assert opened.dirty is False
