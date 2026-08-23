"""
WF5 byte-verify: drawn / tooled curves produce the encodings proven in Spike A.

    discrete N=2 -> {0, 64}          i * ceil(128/N)
    discrete N=3 -> {0, 43, 86}
    discrete N=4 -> {0, 32, 64, 96}
    Disabl       -> 0x80
    beyond length -> untouched (still 0x80 on an empty slot)
    continuous   -> raw 0–127, never 0x80 unless eraser

These tests call the same ui.motion.tools primitives the canvas uses, so a
scripted curve and a drawn curve cannot diverge.
"""

from __future__ import annotations

import random

from core.motion import MotionDomain, MotionSlot
from ui.motion import tools


def _empty() -> MotionSlot:
    return MotionSlot.empty()


def test_discrete_n2_knob_positions() -> None:
    # Roll / Reverse / FX Send / Amp EG
    dom = MotionDomain.discrete(2)
    assert dom.legal_values() == (0, 64)
    slot = _empty()
    tools.write_step(slot, 0, 0, dom)
    tools.write_step(slot, 1, 30, dom)  # nearer 0 than 64
    tools.write_step(slot, 2, 40, dom)  # nearer 64
    tools.write_step(slot, 3, 127, dom)
    assert slot.get_step(0) == 0
    assert slot.get_step(1) == 0
    assert slot.get_step(2) == 64
    assert slot.get_step(3) == 64
    assert set(slot.values[:4]) <= {0, 64}


def test_discrete_n3_fx_select() -> None:
    dom = MotionDomain.discrete(3)
    assert dom.legal_values() == (0, 43, 86)
    slot = _empty()
    for i, raw in enumerate((0, 20, 43, 60, 86, 127)):
        tools.write_step(slot, i, raw, dom)
    assert slot.values[:6] == bytes([0, 0, 43, 43, 86, 86])


def test_discrete_n4_filter_type() -> None:
    dom = MotionDomain.discrete(4)
    assert dom.legal_values() == (0, 32, 64, 96)
    slot = _empty()
    tools.ramp(slot, dom, 0, 127, length=8)
    # A ramp snapped to 4 zones must only ever hit knob positions.
    assert set(slot.values[:8]) <= {0, 32, 64, 96}
    assert 1 not in slot.values[:8]
    assert 2 not in slot.values[:8]
    assert 3 not in slot.values[:8]


def test_eraser_writes_disabl_sentinel() -> None:
    dom = MotionDomain.continuous()
    slot = _empty()
    tools.write_step(slot, 5, 77, dom)
    assert slot.get_step(5) == 77
    tools.eraser(slot, 5, dom)
    assert slot.get_step(5) == MotionSlot.DISABLED == 0x80


def test_length_mask_does_not_write_beyond() -> None:
    dom = MotionDomain.continuous()
    slot = _empty()
    tools.ramp(slot, dom, 0, 127, length=16)
    assert all(slot.get_step(i) != MotionSlot.DISABLED for i in range(16))
    assert all(slot.get_step(i) == MotionSlot.DISABLED for i in range(16, 128))
    tools.write_step(slot, 20, 99, dom, length=16)
    assert slot.get_step(20) == MotionSlot.DISABLED


def test_clear_keeps_target_and_disables_playable() -> None:
    dom = MotionDomain.continuous()
    slot = MotionSlot(102, bytes(range(128)))
    tools.clear(slot, dom, length=64)
    assert slot.target == 102
    assert slot.values[:64] == bytes([0x80] * 64)
    assert slot.values[64:] == bytes(range(64, 128))  # masked tail untouched


def test_invert_skips_disabl() -> None:
    dom = MotionDomain.continuous()
    slot = _empty()
    tools.write_step(slot, 0, 10, dom, length=8)
    tools.write_step(slot, 1, 100, dom, length=8)
    tools.invert(slot, dom, length=8)
    assert slot.get_step(0) == 117
    assert slot.get_step(1) == 27
    assert slot.is_disabled(2)


def test_lfo_shapes_stay_in_0_127() -> None:
    dom = MotionDomain.continuous()
    for shape in tools.SHAPES:
        slot = _empty()
        tools.lfo(slot, dom, shape, length=32)
        vals = [slot.get_step(i) for i in range(32)]
        assert all(0 <= v <= 127 for v in vals)
        assert MotionSlot.DISABLED not in vals


def test_discrete_lfo_never_writes_illegal_bytes() -> None:
    dom = MotionDomain.discrete(4)
    slot = _empty()
    tools.lfo(slot, dom, "sine", length=32)
    assert set(slot.values[:32]) <= {0, 32, 64, 96}


def test_sample_and_hold_is_deterministic_with_seed() -> None:
    dom = MotionDomain.discrete(2)
    a, b = _empty(), _empty()
    tools.sample_and_hold(a, dom, hold=4, length=16, rng=random.Random(1))
    tools.sample_and_hold(b, dom, hold=4, length=16, rng=random.Random(1))
    assert a.values[:16] == b.values[:16]
    for i in range(0, 16, 4):
        assert len(set(a.values[i : i + 4])) == 1


def test_line_interpolates_continuous() -> None:
    dom = MotionDomain.continuous()
    slot = _empty()
    tools.line(slot, dom, 0, 0, 4, 40, length=16)
    assert list(slot.values[:5]) == [0, 10, 20, 30, 40]


def test_scale_and_smooth_preserve_disabl() -> None:
    dom = MotionDomain.continuous()
    slot = _empty()
    tools.write_step(slot, 0, 32, dom, length=8)
    tools.write_step(slot, 1, 96, dom, length=8)
    tools.scale(slot, dom, 0.5, centre=64, length=8)
    assert slot.get_step(0) == 48
    assert slot.is_disabled(2)
    tools.smooth(slot, dom, length=8)
    assert slot.is_disabled(2)


def test_randomise_discrete_only_legal() -> None:
    dom = MotionDomain.discrete(3)
    slot = _empty()
    tools.randomise(slot, dom, length=32, rng=random.Random(0))
    assert set(slot.values[:32]) <= {0, 43, 86}


def test_write_stored_roundtrip_bytes() -> None:
    """A tooled slot serializes to the 130-byte on-disk form."""
    dom = MotionDomain.discrete(2, forced_trig=True)
    slot = MotionSlot(14, bytes([0x80] * 128))  # Drum1 Roll
    tools.write_step(slot, 0, 64, dom, length=16)
    tools.write_step(slot, 1, 0, dom, length=16)
    raw = slot.to_bytes()
    assert len(raw) == 130
    assert raw[:2] == b"\x00\x0e"
    assert raw[2] == 64
    assert raw[3] == 0
    assert raw[4] == 0x80
    assert MotionSlot.from_bytes(raw).values == slot.values
