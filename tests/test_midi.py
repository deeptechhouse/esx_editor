"""MIDI Learn: the port, the null fallback, and the Global tab wiring.

No hardware and no MIDI backend are involved. A fake MidiInput stands in, which
is the point of the port — the learn logic is testable precisely because the
device is behind an interface.
"""

from __future__ import annotations

import pytest

from midi.null import NullMidiInput
from midi.ports import ControlChange, MidiInput, NoteOn


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

    v.toggle_learn("cc", 5)
    assert v._learning == ("cc", 5)
    assert fake.opened == ["Fake Controller"]
    v._poll_midi()

    assert bank.globals.cc_assignment(5) == 21
    assert v.cc.cellWidget(5, 2).value() == 21
    assert v._learning is None, "capturing disarms the row"
    assert fake.closed >= 1, "the port is released after capture"
    assert CC_ASSIGN_NAMES[5] in v._midi_status.text()
    assert "CC 21" in v._midi_status.text()
    assert "channel 3" in v._midi_status.text(), "channels display 1-16"
    assert len(edits) == 1

    bank.globals.set_cc_assignment(5, before)


def test_only_one_row_can_be_armed(qapp, bank) -> None:
    fake = FakeMidiInput([])
    v = _global_view(qapp, bank, fake)
    v.toggle_learn("cc", 0)
    v.toggle_learn("cc", 3)
    assert v._learning == ("cc", 3)
    assert v.cc.cellWidget(0, 3).isChecked() is False
    assert v.cc.cellWidget(3, 3).isChecked() is True
    v.stop_learn(captured=False)


def test_pressing_learn_twice_disarms(qapp, bank) -> None:
    fake = FakeMidiInput([])
    v = _global_view(qapp, bank, fake)
    v.toggle_learn("cc", 2)
    v.toggle_learn("cc", 2)
    assert v._learning is None
    assert v.cc.cellWidget(2, 3).text() == "Learn"


def test_learn_with_no_device_says_so_and_does_not_arm(qapp, bank) -> None:
    v = _global_view(qapp, bank, FakeMidiInput([], ports=()))
    v.toggle_learn("cc", 1)
    assert v._learning is None
    assert "No MIDI input connected" in v._midi_status.text()


def test_learn_survives_a_device_that_vanishes_on_open(qapp, bank) -> None:
    v = _global_view(qapp, bank, FakeMidiInput([], fail_open=True))
    v.toggle_learn("cc", 1)
    assert v._learning is None
    assert "Could not open" in v._midi_status.text()


def test_learn_disabled_without_a_backend(qapp, bank) -> None:
    v = _global_view(qapp, bank, NullMidiInput("mido is not installed"))
    button = v.cc.cellWidget(0, 3)
    assert button.isEnabled() is False
    assert "mido" in button.toolTip()
    v.toggle_learn("cc", 0)
    assert v._learning is None


def test_learn_flags_a_reserved_channel_mode_number(qapp, bank) -> None:
    before = bank.globals.cc_assignment(4)
    v = _global_view(qapp, bank, FakeMidiInput([ControlChange(0, 123, 0)]))
    v.toggle_learn("cc", 4)
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
    assert picker.is_filled is False, "options are built on first open, not up front"
    picker.ensure_filled()
    assert picker.count() == MAX_CC + 1
    assert picker.itemData(74) == 74
    assert picker.itemText(74) == "74 — Brightness / Cutoff"
    assert picker.itemText(53) == "53", "no invented name where the spec is silent"


def test_choosing_from_the_picker_edits_the_bank(qapp, bank) -> None:
    before = bank.globals.cc_assignment(0)
    v = _global_view(qapp, bank, FakeMidiInput([]))
    edits = []
    v.globalsEdited.connect(lambda: edits.append(1))
    v.cc.cellWidget(0, 2).set_value(100)
    v.cc.cellWidget(0, 2).valueChanged.emit(100)
    assert bank.globals.cc_assignment(0) == 100
    assert edits
    bank.globals.set_cc_assignment(0, before)


def test_timeout_disarms_a_forgotten_row(qapp, bank) -> None:
    """A row left armed must not capture a stray message much later."""
    v = _global_view(qapp, bank, FakeMidiInput([]))
    v.toggle_learn("cc", 0)
    assert v._learn_deadline.isActive()
    v.stop_learn(captured=False)  # what the deadline timer calls
    assert v._learning is None
    assert not v._learn_deadline.isActive()


@pytest.mark.parametrize("row", [0, 16, 32])
def test_every_row_can_be_armed(qapp, bank, row) -> None:
    v = _global_view(qapp, bank, FakeMidiInput([]))
    v.toggle_learn("cc", row)
    assert v._learning == ("cc", row)
    v.stop_learn(captured=False)


# -- drum notes ---------------------------------------------------------------


def test_note_learn_captures_a_pad_hit(qapp, bank) -> None:
    from core.global_params import DRUM_NOTE_PARTS

    before = bank.globals.drum_note(2)
    fake = FakeMidiInput([NoteOn(9, 45, 110)])
    v = _global_view(qapp, bank, fake)

    v.toggle_learn("note", 2)
    assert v._learning == ("note", 2)
    v._poll_midi()

    assert bank.globals.drum_note(2) == 45
    assert v.notes.cellWidget(2, 1).value() == 45
    assert DRUM_NOTE_PARTS[2] in v._midi_status.text()
    assert "A2" in v._midi_status.text(), "the machine displays note names"
    assert "channel 10" in v._midi_status.text()
    bank.globals.set_drum_note(2, before)


def test_a_knob_cannot_set_a_drum_note(qapp, bank) -> None:
    """An armed note row ignores control changes, and stays armed."""
    before = bank.globals.drum_note(0)
    fake = FakeMidiInput([ControlChange(0, 74, 100)])
    v = _global_view(qapp, bank, fake)
    v.toggle_learn("note", 0)
    v._poll_midi()
    assert bank.globals.drum_note(0) == before
    assert v._learning == ("note", 0), "still waiting for a pad"
    v.stop_learn(captured=False)


def test_a_pad_cannot_set_a_cc(qapp, bank) -> None:
    before = bank.globals.cc_assignment(0)
    v = _global_view(qapp, bank, FakeMidiInput([NoteOn(0, 60, 100)]))
    v.toggle_learn("cc", 0)
    v._poll_midi()
    assert bank.globals.cc_assignment(0) == before
    assert v._learning == ("cc", 0)
    v.stop_learn(captured=False)


def test_note_learn_ignores_a_pad_release(qapp, bank) -> None:
    """Velocity 0 is a note-off; the RELEASE must not set the mapping."""
    from midi.mido_adapter import MidoMidiInput

    class _Msg:
        def __init__(self, type_, **kw):
            self.type = type_
            self.__dict__.update(kw)

    class _Port:
        def iter_pending(self):
            return iter(
                [
                    _Msg("note_on", channel=0, note=40, velocity=0),
                    _Msg("note_on", channel=0, note=44, velocity=99),
                ]
            )

        def close(self):
            pass

    adapter = MidoMidiInput()
    adapter._port = _Port()
    events = adapter.poll()
    assert len(events) == 1
    assert isinstance(events[0], NoteOn) and events[0].number == 44


def test_only_one_row_is_armed_across_both_tables(qapp, bank) -> None:
    v = _global_view(qapp, bank, FakeMidiInput([]))
    v.toggle_learn("cc", 0)
    v.toggle_learn("note", 1)
    assert v._learning == ("note", 1)
    assert v.cc.cellWidget(0, 3).isChecked() is False
    assert v.notes.cellWidget(1, 2).isChecked() is True
    v.stop_learn(captured=False)


def test_the_note_picker_lists_the_machines_whole_range(qapp, bank) -> None:
    from core.global_params import MAX_NOTE

    v = _global_view(qapp, bank, FakeMidiInput([]))
    picker = v.notes.cellWidget(0, 1)
    picker.ensure_filled()
    assert picker.count() == MAX_NOTE + 1
    assert picker.itemText(0).startswith("C-1"), "manual says the range starts at C-1"
    assert picker.itemText(127).startswith("G9"), "and ends at G9"
    assert picker.itemText(36) == "C2  (36)"


def test_factory_notes_restores_the_manuals_table(qapp, bank) -> None:
    from core.global_params import FACTORY_DRUM_NOTES

    v = _global_view(qapp, bank, FakeMidiInput([]))
    edits = []
    v.globalsEdited.connect(lambda: edits.append(1))
    v.notes.cellWidget(0, 1).set_value(100)
    v.notes.cellWidget(0, 1).valueChanged.emit(100)
    assert bank.globals.drum_note(0) == 100

    v.reset_drum_notes()
    assert bank.globals.drum_notes() == FACTORY_DRUM_NOTES
    assert edits


def test_two_parts_on_one_note_warns_but_is_allowed(qapp, bank) -> None:
    before = bank.globals.drum_note(1)
    v = _global_view(qapp, bank, FakeMidiInput([]))
    assert v._notes_warning.text() == "", "the factory table has no duplicates"
    v.notes.cellWidget(1, 1).valueChanged.emit(bank.globals.drum_note(0))
    warning = v._notes_warning.text()
    assert "Drum1" in warning and "Drum2" in warning
    assert "sound together" in warning
    bank.globals.set_drum_note(1, before)
