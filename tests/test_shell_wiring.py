"""WF6 shell wiring: menu actions, dialogs, and the wizard hand-off.

These paths are the ones a human hits first — File→New, File→Open, the guided
setup, closing with unsaved changes — and every one of them ends in a modal
dialog that would hang an offscreen run. Each dialog is therefore stubbed, and
the test asserts on the ARGUMENTS the shell passed it: that is what proves the
wiring, not the pixels.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

import ui.main_window as mw  # noqa: E402
from codec.errors import CodecError  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402
from ui.wizard import PAGE_COUNT, SetupWizard  # noqa: E402


@pytest.fixture
def win(qapp):
    """A shell whose dirty flag is cleared on teardown so close() never blocks."""
    window = MainWindow()
    yield window
    window.session._dirty = False
    window.close()


class Dialogs:
    """Records what the shell asked each dialog, and answers as configured."""

    def __init__(self, monkeypatch, *, open_path="", save_path="", discard=True):
        self.warnings: list[tuple[str, str]] = []
        self.abouts: list[str] = []
        self.questions = 0
        self._open_path = open_path
        self._save_path = save_path
        monkeypatch.setattr(
            mw.QMessageBox,
            "warning",
            lambda _p, title, text, *a, **k: self.warnings.append((title, text)),
        )
        monkeypatch.setattr(
            mw.QMessageBox, "about", lambda _p, title, text: self.abouts.append(title)
        )
        answer = (
            mw.QMessageBox.StandardButton.Discard
            if discard
            else mw.QMessageBox.StandardButton.Cancel
        )
        monkeypatch.setattr(
            mw.QMessageBox, "question", lambda *a, **k: self._question(answer)
        )
        monkeypatch.setattr(
            mw.QFileDialog, "getOpenFileName", lambda *a, **k: (self._open_path, "")
        )
        monkeypatch.setattr(
            mw.QFileDialog, "getSaveFileName", lambda *a, **k: (self._save_path, "")
        )

    def _question(self, answer):
        self.questions += 1
        return answer


# -- File -> New -------------------------------------------------------------
def test_new_bank_binds_every_view(win, monkeypatch) -> None:
    dialogs = Dialogs(monkeypatch)
    win._on_new()
    if not win.session.is_open:
        assert dialogs.warnings and dialogs.warnings[0][0] == "New bank"
        pytest.skip("blank template unavailable in this checkout")
    assert win.pattern_view.list.count() == 256
    assert len(win.global_view.block_bytes()) == 192
    assert win.session.dirty is True


def test_new_bank_warns_when_the_template_is_missing(win, monkeypatch) -> None:
    dialogs = Dialogs(monkeypatch)
    monkeypatch.setattr(
        win.session,
        "new_bank",
        lambda: (_ for _ in ()).throw(CodecError("no template")),
    )
    win._on_new()
    assert dialogs.warnings == [("New bank", "no template")]
    assert win.session.is_open is False


# -- File -> Open ------------------------------------------------------------
def test_open_uses_the_chosen_path(win, monkeypatch, corpus_path) -> None:
    Dialogs(monkeypatch, open_path=corpus_path)
    win._on_open()
    assert win.session.path == corpus_path
    assert win.bank_view.table.rowCount() > 0


def test_open_cancelled_changes_nothing(win, monkeypatch) -> None:
    Dialogs(monkeypatch, open_path="")
    win._on_open()
    assert win.session.is_open is False


def test_open_failure_warns_and_returns_false(win, monkeypatch, tmp_path) -> None:
    dialogs = Dialogs(monkeypatch)
    bad = tmp_path / "bad.esx"
    bad.write_bytes(b"nope")
    assert win.open_path(str(bad)) is False
    assert dialogs.warnings and dialogs.warnings[0][0] == "Open failed"
    assert win.session.is_open is False


def test_open_is_guarded_by_the_discard_prompt(win, monkeypatch, corpus_path) -> None:
    dialogs = Dialogs(monkeypatch, open_path=corpus_path, discard=False)
    win.session._dirty = True
    win._on_open()
    assert dialogs.questions == 1
    assert win.session.is_open is False, "Cancel must abort the open"


# -- File -> Save ------------------------------------------------------------
def test_save_writes_to_the_current_path(win, monkeypatch, corpus_path, tmp_path):
    Dialogs(monkeypatch)
    win.open_path(corpus_path)
    dest = str(tmp_path / "saved.esx")
    win.session._path = dest
    monkeypatch.setattr(
        win.session, "save", lambda path, **k: seen.append(path) or path
    )
    seen: list[str] = []
    win._on_save()
    assert seen == [dest]


def test_save_falls_back_to_save_as_without_a_path(win, monkeypatch, tmp_path):
    dest = str(tmp_path / "as.esx")
    Dialogs(monkeypatch, save_path=dest)
    seen: list[str] = []
    monkeypatch.setattr(
        win.session, "save", lambda path, **k: seen.append(path) or path
    )
    win._on_save()
    assert seen == [dest]


def test_save_as_cancelled_writes_nothing(win, monkeypatch) -> None:
    Dialogs(monkeypatch, save_path="")
    seen: list[str] = []
    monkeypatch.setattr(
        win.session, "save", lambda path, **k: seen.append(path) or path
    )
    win._on_save_as()
    assert seen == []


def test_save_refusal_is_surfaced_not_swallowed(win, monkeypatch) -> None:
    """An incoherent bank is refused by the writer; the user must be told."""
    dialogs = Dialogs(monkeypatch)
    monkeypatch.setattr(
        win.session,
        "save",
        lambda path, **k: (_ for _ in ()).throw(CodecError("refusing: 17 errors")),
    )
    win._write("/tmp/whatever.esx")
    assert dialogs.warnings == [("Save refused", "refusing: 17 errors")]


# -- Help, discard, close ----------------------------------------------------
def test_about_is_reachable(win, monkeypatch) -> None:
    dialogs = Dialogs(monkeypatch)
    win._on_about()
    assert dialogs.abouts == ["About ESX Bank Studio"]


def test_clean_session_never_prompts(win, monkeypatch) -> None:
    dialogs = Dialogs(monkeypatch)
    assert win._confirm_discard() is True
    assert dialogs.questions == 0


def test_close_with_unsaved_changes_can_be_cancelled(win, monkeypatch) -> None:
    from PySide6.QtGui import QCloseEvent

    dialogs = Dialogs(monkeypatch, discard=False)
    win.session._dirty = True
    event = QCloseEvent()
    win.closeEvent(event)
    assert dialogs.questions == 1
    assert event.isAccepted() is False
    win.session._dirty = False


def test_close_with_unsaved_changes_can_be_discarded(win, monkeypatch) -> None:
    from PySide6.QtGui import QCloseEvent

    Dialogs(monkeypatch, discard=True)
    win.session._dirty = True
    event = QCloseEvent()
    win.closeEvent(event)
    assert event.isAccepted() is True


# -- Guided setup ------------------------------------------------------------
def test_guided_setup_opens_on_the_live_session(win, corpus_path) -> None:
    win.open_path(corpus_path)
    wizard = win.open_wizard()
    try:
        assert isinstance(wizard, SetupWizard)
        assert len(wizard.pages()) == PAGE_COUNT == 11
        assert wizard.context.session is win.session
        assert (
            wizard.staging_bank() is win.staging_view.bank
        ), "the wizard must render the Staging tab's model, not a second one"
    finally:
        wizard.close()


def test_guided_setup_changes_flow_back_to_the_shell(win, corpus_path) -> None:
    win.open_path(corpus_path)
    wizard = win.open_wizard()
    try:
        page = wizard.page_at(8)  # 9 · Pattern basics
        page.refresh()
        page.name.setText("FROMWIZ")
        page.apply_name()
        assert win.session.dirty is True
        assert "modified" in win._dirty_label.text()
        assert win.pattern_view.list.item(0).text().endswith("FROMWIZ")
    finally:
        wizard.close()


def test_menus_expose_every_wired_action(win) -> None:
    labels = {
        name: [a.text() for a in menu.actions()] for name, menu in win.menus.items()
    }
    assert "Guided setup…" in labels["File"]
    assert "Clear staging" in labels["Edit"]
    assert "About" in labels["Help"]
    assert labels["View"] == [name for name, _hint in mw.TABS]


# -- entry point -------------------------------------------------------------
def test_app_main_builds_and_shows_a_window(monkeypatch) -> None:
    import ui.app as app_mod

    monkeypatch.setattr(app_mod.QApplication, "exec", lambda self: 0)
    assert app_mod.main(["esx-app-test"]) == 0


def test_pattern_selection_without_a_bank_is_a_no_op(win) -> None:
    win._on_pattern_selected(0)  # no bank open — must not raise
    assert win.session.bank is None


def test_new_is_guarded_by_the_discard_prompt(win, monkeypatch) -> None:
    dialogs = Dialogs(monkeypatch, discard=False)
    win.session._dirty = True
    win._on_new()
    assert dialogs.questions == 1
    assert win.session.is_open is False
    win.session._dirty = False


def test_bind_motion_tolerates_a_bank_with_no_patterns(win, monkeypatch) -> None:
    class _Empty:
        def patterns(self):
            return ()

    monkeypatch.setattr(type(win.session), "bank", property(lambda self: _Empty()))
    win._bind_motion()  # must not raise or bind anything


# -- card overview ------------------------------------------------------------
def test_card_overview_lists_the_banks_in_a_folder(win, monkeypatch, tmp_path):
    """Card space is a different question from the sampler's RAM budget."""
    from tests.synthetic import build

    shown = []
    monkeypatch.setattr(
        mw.QMessageBox, "information", lambda _p, title, text: shown.append(text)
    )
    (tmp_path / "one.esx").write_bytes(build(num_mono=2, pcm_bytes=2048))
    (tmp_path / "two.esx").write_bytes(build(num_mono=0, pcm_bytes=64))

    text = win.show_card_overview(str(tmp_path))
    assert "one.esx" in text and "two.esx" in text
    assert "free" in text and "sampler RAM" in text
    assert shown == [text]


def test_card_overview_cancelled_shows_nothing(win, monkeypatch):
    monkeypatch.setattr(mw.QFileDialog, "getExistingDirectory", lambda *a, **k: "")
    assert win.show_card_overview() == ""


def test_card_overview_handles_an_empty_folder(win, monkeypatch, tmp_path):
    monkeypatch.setattr(mw.QMessageBox, "information", lambda *a, **k: None)
    assert "No .esx banks here." in win.show_card_overview(str(tmp_path))


def test_no_card_warning_when_there_is_room(win, monkeypatch, tmp_path, corpus_path):
    Dialogs(monkeypatch)
    win.open_path(corpus_path)
    assert win.card_warning_for(str(tmp_path / "new.esx")) == ""


def test_card_warning_when_the_card_is_too_small(
    win, monkeypatch, tmp_path, corpus_path
):
    """A 4 MB card is legal, and most banks do not fit on one."""
    Dialogs(monkeypatch)
    win.open_path(corpus_path)
    monkeypatch.setattr(mw.card, "detect_capacity", lambda _d: mw.card.MIN_CARD_BYTES)
    warning = win.card_warning_for(str(tmp_path / "big.esx"))
    assert "MiB is free" in warning
    assert "4–128 MB" in warning


def test_a_save_that_would_overflow_the_card_asks_first(
    win, monkeypatch, tmp_path, corpus_path
):
    dialogs = Dialogs(monkeypatch, discard=False)  # Cancel the overflow prompt
    win.open_path(corpus_path)
    monkeypatch.setattr(mw.card, "detect_capacity", lambda _d: mw.card.MIN_CARD_BYTES)
    seen = []
    monkeypatch.setattr(win.session, "save", lambda p, **k: seen.append(p) or p)
    win._write(str(tmp_path / "nope.esx"))
    assert dialogs.questions == 1
    assert seen == [], "cancelling the prompt must not write"
