"""MIDI Learn: the port, the null fallback, and the Global tab wiring.

No hardware and no MIDI backend are involved. A fake MidiInput stands in, which
is the point of the port — the learn logic is testable precisely because the
device is behind an interface.
"""

from __future__ import annotations

import pytest

from midi.null import NullMidiInput
from midi.ports import ControlChange, MidiInput


class FakeMidiInput:
    """A MidiInput that replays a scripted list of control changes."""

    def __init__(self, messages=(), ports=("Fake Controller",), fail_open=False):
        self._queued = list(messages)
        self._ports = tuple(ports)
        self._open = False
        self._fail_open = fail_open
        self.opened: list[str] = []
        self.closed = 0

    @property
    def available(self) -> bool:
        return True

    def ports(self):
        return self._ports

    def open(self, port):
        if self._fail_open:
            raise OSError("device vanished")
        self._open = True
        self.opened.append(port)

    def close(self):
        self._open = False
        self.closed += 1

    @property
    def is_open(self):
        return self._open

    def poll(self):
        if not self._open:
            return ()
        out, self._queued = tuple(self._queued), []
        return out


# -- the contract -------------------------------------------------------------


def test_fakes_and_null_both_satisfy_the_port() -> None:
    assert isinstance(FakeMidiInput(), MidiInput)
    assert isinstance(NullMidiInput(), MidiInput)


def test_control_change_reports_the_channel_the_way_hardware_does() -> None:
    assert ControlChange(0, 74, 100).display_channel == 1
    assert ControlChange(15, 74, 100).display_channel == 16


def test_null_input_never_raises_and_carries_its_reason() -> None:
    null = NullMidiInput("mido is not installed")
    assert null.available is False
    assert "mido" in null.reason
    null.open("anything")
    null.close()
    assert null.ports() == () and null.poll() == () and null.is_open is False


def test_factory_returns_something_usable_either_way() -> None:
    from midi.factory import describe, midi_input

    got = midi_input()
    assert isinstance(got, MidiInput)
    assert got.poll() == () or got.available
    assert "MIDI Learn" in describe()


# -- the Global tab -----------------------------------------------------------


def _global_view(qapp, bank, midi):
    from ui.views import GlobalView

    view = GlobalView()
    view.midi = midi
    view.bind_bank(bank)
    return view


def test_learn_captures_the_first_control_change(qapp, bank) -> None:
    from core.global_params import CC_ASSIGN_NAMES

    before = bank.globals.cc_assignment(5)
    fake = FakeMidiInput([ControlChange(2, 21, 64), ControlChange(2, 21, 65)])
    v = _global_view(qapp, bank, fake)
    edits = []
    v.globalsEdited.connect(lambda: edits.append(1))

    v.toggle_learn(5)
    assert v._learning_row == 5
    assert fake.opened == ["Fake Controller"]
    v._poll_midi()

    assert bank.globals.cc_assignment(5) == 21
    assert v.cc.cellWidget(5, 2).currentIndex() == 21
    assert v._learning_row is None, "capturing disarms the row"
    assert fake.closed >= 1, "the port is released after capture"
    assert CC_ASSIGN_NAMES[5] in v._midi_status.text()
    assert "CC 21" in v._midi_status.text()
    assert "channel 3" in v._midi_status.text(), "channels display 1-16"
    assert len(edits) == 1

    bank.globals.set_cc_assignment(5, before)


def test_only_one_row_can_be_armed(qapp, bank) -> None:
    fake = FakeMidiInput([])
    v = _global_view(qapp, bank, fake)
    v.toggle_learn(0)
    v.toggle_learn(3)
    assert v._learning_row == 3
    assert v.cc.cellWidget(0, 3).isChecked() is False
    assert v.cc.cellWidget(3, 3).isChecked() is True
    v.stop_learn(captured=False)


def test_pressing_learn_twice_disarms(qapp, bank) -> None:
    fake = FakeMidiInput([])
    v = _global_view(qapp, bank, fake)
    v.toggle_learn(2)
    v.toggle_learn(2)
    assert v._learning_row is None
    assert v.cc.cellWidget(2, 3).text() == "Learn"


def test_learn_with_no_device_says_so_and_does_not_arm(qapp, bank) -> None:
    v = _global_view(qapp, bank, FakeMidiInput([], ports=()))
    v.toggle_learn(1)
    assert v._learning_row is None
    assert "No MIDI input connected" in v._midi_status.text()


def test_learn_survives_a_device_that_vanishes_on_open(qapp, bank) -> None:
    v = _global_view(qapp, bank, FakeMidiInput([], fail_open=True))
    v.toggle_learn(1)
    assert v._learning_row is None
    assert "Could not open" in v._midi_status.text()


def test_learn_disabled_without_a_backend(qapp, bank) -> None:
    v = _global_view(qapp, bank, NullMidiInput("mido is not installed"))
    button = v.cc.cellWidget(0, 3)
    assert button.isEnabled() is False
    assert "mido" in button.toolTip()
    v.toggle_learn(0)
    assert v._learning_row is None


def test_learn_flags_a_reserved_channel_mode_number(qapp, bank) -> None:
    before = bank.globals.cc_assignment(4)
    v = _global_view(qapp, bank, FakeMidiInput([ControlChange(0, 123, 0)]))
    v.toggle_learn(4)
    v._poll_midi()
    assert bank.globals.cc_assignment(4) == 123
    assert "reserved" in v._midi_status.text()
    bank.globals.set_cc_assignment(4, before)


def test_the_picker_lists_every_legal_cc_with_names_where_they_exist(
    qapp, bank
) -> None:
    from core.global_params import MAX_CC

    v = _global_view(qapp, bank, FakeMidiInput([]))
    picker = v.cc.cellWidget(0, 2)
    assert picker.count() == MAX_CC + 1
    assert picker.itemData(74) == 74
    assert picker.itemText(74) == "74 — Brightness / Cutoff"
    assert picker.itemText(53) == "53", "no invented name where the spec is silent"


def test_choosing_from_the_picker_edits_the_bank(qapp, bank) -> None:
    before = bank.globals.cc_assignment(0)
    v = _global_view(qapp, bank, FakeMidiInput([]))
    edits = []
    v.globalsEdited.connect(lambda: edits.append(1))
    v.cc.cellWidget(0, 2).setCurrentIndex(100)
    assert bank.globals.cc_assignment(0) == 100
    assert edits
    bank.globals.set_cc_assignment(0, before)


def test_timeout_disarms_a_forgotten_row(qapp, bank) -> None:
    """A row left armed must not capture a stray message much later."""
    v = _global_view(qapp, bank, FakeMidiInput([]))
    v.toggle_learn(0)
    assert v._learn_deadline.isActive()
    v.stop_learn(captured=False)  # what the deadline timer calls
    assert v._learning_row is None
    assert not v._learn_deadline.isActive()


@pytest.mark.parametrize("row", [0, 16, 32])
def test_every_row_can_be_armed(qapp, bank, row) -> None:
    v = _global_view(qapp, bank, FakeMidiInput([]))
    v.toggle_learn(row)
    assert v._learning_row == row
    v.stop_learn(captured=False)
