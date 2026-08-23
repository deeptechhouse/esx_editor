"""UI foundation: theme tokens, reusable widgets, shell — offscreen Qt."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtCore import (
    QEvent,  # noqa: E402
    Qt,  # noqa: E402
)
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ui.main_window import TABS, MainWindow  # noqa: E402
from ui.session import BankSession  # noqa: E402
from ui.theme import PALETTE, qss  # noqa: E402
from ui.theme import apply as apply_theme
from ui.widgets.budget_meter import BudgetMeter  # noqa: E402
from ui.widgets.knob_dial import KnobDial  # noqa: E402
from ui.widgets.step_grid import NUM_STEPS, StepGrid  # noqa: E402
from ui.widgets.waveform_view import WaveformView  # noqa: E402
from workspace.budget import CAPACITY  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(["esx-test"])
    apply_theme(app)
    return app


def test_theme_qss_contains_tokens() -> None:
    sheet = qss()
    assert PALETTE.bg in sheet
    assert PALETTE.amber in sheet
    assert PALETTE.lcd in sheet
    assert "QTabBar::tab:selected" in sheet


def test_budget_meter_paints(qapp) -> None:
    m = BudgetMeter()
    m.set_used(0)
    assert m.fraction == 0.0
    m.set_used(CAPACITY // 2)
    assert 0.49 < m.fraction < 0.51
    m.resize(300, 28)
    m.show()
    qapp.processEvents()
    # grab a paint to prove paintEvent does not throw
    pix = m.grab()
    assert pix.width() >= 180


def test_knob_dial_clamps_and_emits(qapp) -> None:
    k = KnobDial()
    seen = []
    k.valueChanged.connect(seen.append)
    k.setValue(200)
    assert k.value == 127
    k.setValue(-4)
    assert k.value == 0
    k.setValue(64)
    assert seen[-1] == 64
    k.show()
    qapp.processEvents()
    pix = k.grab()
    assert pix.width() >= 48


def test_knob_dial_keyboard(qapp) -> None:
    k = KnobDial(value=10)
    k.setFocus()
    event = QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier
    )
    k.keyPressEvent(event)
    assert k.value == 11


def test_step_grid_toggle_and_length(qapp) -> None:
    g = StepGrid(length=16)
    seen = []
    g.stepToggled.connect(lambda i, on: seen.append((i, on)))
    g.set_step(3, True)
    assert g.is_on(3)
    assert seen == [(3, True)]
    g.set_step(3, True)  # idempotent: no extra signal
    assert seen == [(3, True)]
    g.set_length(8)
    assert g.steps()[3] is True
    g.resize(320, 160)
    g.show()
    qapp.processEvents()
    assert g.grab().width() >= 16
    assert NUM_STEPS == 128


def test_waveform_view_empty_and_peaks(qapp) -> None:
    w = WaveformView()
    w.resize(200, 60)
    w.show()
    qapp.processEvents()
    w.grab()
    w.set_peaks([0.0, 0.5, 1.0, 0.25])
    assert w.peaks[2] == 1.0
    w.grab()


def test_main_window_has_six_tabs(qapp) -> None:
    win = MainWindow()
    assert win.tabs.count() == len(TABS) == 6
    names = [win.tabs.tabText(i) for i in range(win.tabs.count())]
    assert names == [t[0] for t in TABS]
    win.show()
    qapp.processEvents()
    win.grab()
    win.close()


def test_bank_session_new_and_pcm_used() -> None:
    s = BankSession()
    assert not s.is_open
    try:
        bank = s.new_bank()
    except Exception as exc:
        pytest.skip(f"blank template unavailable: {exc}")
    assert s.is_open and s.dirty and s.path is None
    assert bank is s.bank
    assert s.pcm_used() >= 0
