"""WF5 UI smoke: canvas, picker, editor — offscreen Qt."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from codec.operation_table import OperationTable  # noqa: E402
from core.motion import MotionDomain, MotionSlot  # noqa: E402
from ui.motion.canvas import MotionCanvas  # noqa: E402
from ui.motion.picker import TargetPicker  # noqa: E402
from ui.motion.editor import MotionEditor  # noqa: E402
from ui.theme import apply as apply_theme  # noqa: E402

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESEARCH = os.path.join(PROJECT, "research")


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(["esx-motion-test"])
    apply_theme(app)
    return app


@pytest.fixture(scope="module")
def ops():
    return OperationTable.load(RESEARCH)


def test_canvas_pencil_snaps_discrete(qapp) -> None:
    slot = MotionSlot.empty()
    dom = MotionDomain.discrete(4)
    c = MotionCanvas(slot=slot, domain=dom, length=16)
    c.resize(640, 160)
    c.apply_pencil(3, 50)          # nearer 64 than 32
    assert slot.get_step(3) == 64
    c.apply_eraser(3)
    assert slot.is_disabled(3)
    c.apply_pencil(20, 10)         # beyond length=16: no write
    assert slot.is_disabled(20)
    c.show()
    qapp.processEvents()
    assert c.grab().width() >= 320
    c.close()


def test_canvas_forced_trig_flag(qapp) -> None:
    c = MotionCanvas(domain=MotionDomain.discrete(2, forced_trig=True), length=8)
    assert c._stepped() is True
    c.set_trig_hold(False)
    assert c._stepped() is True          # forced-TRIG wins
    c.set_slot(MotionSlot.empty(), MotionDomain.continuous())
    c.set_trig_hold(True)
    assert c._stepped() is True


def test_picker_hides_pitch_and_filters_accent(qapp, ops) -> None:
    p = TargetPicker(ops)
    names = p.visible_names()
    assert names
    assert not any(n.upper().endswith("PITCH") for n in names)
    p.set_part_kind("accent")
    qapp.processEvents()
    accent = p.visible_names()
    assert accent
    assert all(n.upper().endswith("LEVEL") for n in accent)
    p.set_part_kind("audioin")
    qapp.processEvents()
    audio = p.visible_names()
    assert not any("START POINT" in n.upper() for n in audio)
    p.close()


def test_editor_constructs_and_budget(qapp, ops) -> None:
    ed = MotionEditor(table=ops)
    assert ed.canvas.length == 64
    assert "0/24" in ed._budget.text()
    # assign a real target onto slot 0
    drums = ops.targets_for_part("drum")
    cutoff = next(t for t in drums if "CUTOFF" in t.name.upper())
    ed._slots[0].set_target(cutoff.target_id)
    ed._refresh_budget()
    assert "1/24" in ed._budget.text()
    ed.set_sample_duration(12.8)
    ed._target = next(t for t in drums if "START POINT" in t.name.upper())
    ed._refresh_start_help()
    assert "s per step" in ed._start_help.text()
    ed.show()
    qapp.processEvents()
    ed.grab()
    ed.close()
