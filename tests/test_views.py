"""WF6 views: bank, staging, pattern, song, global — offscreen Qt.

The views are the last layer before the user, so these tests check the two
things that can silently rot: that each view binds a REAL corpus bank without
throwing, and that the honest-reporting rules hold (no invented pattern-header
fields, no invented song decoder, no invented MIDI offsets).
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

import codec.layout as L  # noqa: E402
import ui.views.song_view as song_view_mod  # noqa: E402
from audio.passthrough import NullKeyDetector, WavPassthroughConverter  # noqa: E402
from tests.conftest import make_staging, make_wav  # noqa: E402
from ui.main_window import TABS, MainWindow  # noqa: E402
from ui.views import (  # noqa: E402
    BankView,
    GlobalView,
    PatternView,
    SongView,
    StagingView,
)
from ui.views.global_view import hex_dump  # noqa: E402


# -- package -----------------------------------------------------------------
def test_views_package_exports_five() -> None:
    import ui.views as views

    assert set(views.__all__) == {
        "BankView",
        "StagingView",
        "PatternView",
        "SongView",
        "GlobalView",
    }
    for name in views.__all__:
        assert getattr(views, name) is not None


def test_audio_package_exports_passthrough_adapters() -> None:
    import audio

    assert audio.WavPassthroughConverter is WavPassthroughConverter
    assert audio.NullKeyDetector is NullKeyDetector
    # The adapters satisfy the ports structurally (ports-and-adapters, TDD §5.1).
    assert isinstance(WavPassthroughConverter(), audio.AudioConverter)
    assert isinstance(NullKeyDetector(), audio.KeyDetector)


# -- bank view ---------------------------------------------------------------
def test_bank_view_lists_occupied_slots(qapp, bank) -> None:
    v = BankView()
    v.bind_bank(bank)
    occupied = [s for s in bank.samples() if not s.empty]
    assert v.table.rowCount() == len(occupied)
    assert occupied, "corpus bank should have at least one sample"
    names = {v.table.item(r, 1).text() for r in range(v.table.rowCount())}
    assert names == {s.name for s in occupied}
    assert v.meter.used == bank.pcm_used_bytes()


def test_bank_view_counts_pools_separately(qapp, bank) -> None:
    v = BankView()
    v.bind_bank(bank)
    text = v._counts.text()
    assert f"/{L.NUM_SAMPLES_MONO}" in text and f"/{L.NUM_SAMPLES_STEREO}" in text


def test_bank_view_shows_the_verified_stereo_rate(qapp, stereo_bank) -> None:
    """Stereo rate was printed as "—" while its offset was unconfirmed.

    The 40 populated stereo slots in Chronic-Interactive.esx settled it on
    2026-08-23, so both pools now show a real rate. A vacuous version of this
    test passed for weeks because the default fixture bank has no stereo rows —
    hence the explicit stereo_bank fixture.
    """
    v = BankView()
    v.bind_bank(stereo_bank)
    stereo_rows = [
        r for r in range(v.table.rowCount()) if v.table.item(r, 2).text() == "stereo"
    ]
    assert stereo_rows, "the stereo_bank fixture guarantees these exist"
    for row in stereo_rows:
        rate = int(v.table.item(row, 3).text())
        assert L.MIN_IMPORT_RATE_HZ <= rate <= L.MAX_IMPORT_RATE_HZ
        # Imported material carries pure rate compensation.
        assert abs(float(v.table.item(row, 4).text())) < 0.05


def test_bank_view_unbinds_cleanly(qapp, bank) -> None:
    v = BankView()
    v.bind_bank(bank)
    v.bind_bank(None)
    assert v.table.rowCount() == 0
    assert v.meter.used == 0
    assert v._counts.text() == "no bank"


# -- staging view ------------------------------------------------------------
def test_staging_view_add_wav_and_clear(qapp, tmp_path) -> None:
    src = make_wav(str(tmp_path / "kick.wav"))
    v = StagingView(bank=make_staging(tmp_path))
    seen = []
    v.samplesChanged.connect(lambda: seen.append(1))
    v.add_path(src)
    assert v._list.count() == 1
    assert v.meter.used > 0
    assert seen == [1]
    assert os.path.exists(src), "the original file must never be touched"
    v.clear_staging()
    assert v._list.count() == 0
    assert v.meter.used == 0


def test_staging_view_shares_one_model(qapp, tmp_path) -> None:
    """The wizard's Add-samples screen renders the SAME StagingBank."""
    model = make_staging(tmp_path)
    a = StagingView(bank=model)
    b = StagingView(bank=model)
    assert a.bank is b.bank is model
    a.add_path(make_wav(str(tmp_path / "snare.wav")))
    b.reload()
    assert b._list.count() == 1


def test_staging_view_ignores_empty_path(qapp, tmp_path) -> None:
    v = StagingView(bank=make_staging(tmp_path))
    v.add_path("")
    assert v._list.count() == 0


def test_staging_view_refuses_a_format_no_backend_can_read(
    qapp, tmp_path, monkeypatch
) -> None:
    """The refusal follows the machine's real capabilities, not a hard-coded list."""
    import ui.views.staging_view as mod

    shown = []
    monkeypatch.setattr(
        mod.QMessageBox, "information", lambda *a, **k: shown.append(a[-1])
    )
    v = StagingView(bank=make_staging(tmp_path))
    other = tmp_path / "notes.txt"
    other.write_text("definitely not audio")
    v.add_path(str(other))
    assert v._list.count() == 0
    assert shown and "can read" in shown[0]


def test_staging_view_accepts_what_the_converter_advertises(qapp, tmp_path) -> None:
    v = StagingView(bank=make_staging(tmp_path))
    assert v.accepts("kick.wav")
    assert v.accepts("KICK.WAV"), "extension matching must be case-insensitive"
    assert not v.accepts("readme.txt")
    # Whether mp3 is accepted depends on ffmpeg being installed — assert the
    # rule, not the outcome.
    assert v.accepts("loop.mp3") is v.capabilities.can_convert_any_format


def test_staging_view_surfaces_a_truncated_wav(qapp, tmp_path, monkeypatch) -> None:
    """A part-written .wav raises EOFError, not wave.Error — it must not crash."""
    import ui.views.staging_view as mod

    warned = []
    monkeypatch.setattr(
        mod.QMessageBox,
        "warning",
        lambda _p, title, text, *a, **k: warned.append(title),
    )
    v = StagingView(bank=make_staging(tmp_path))
    truncated = tmp_path / "half.wav"
    truncated.write_bytes(b"RIFF\x24\x00\x00\x00WAVEfmt ")
    v.add_path(str(truncated))
    assert v._list.count() == 0
    assert warned == ["Could not add"]


# -- pattern view ------------------------------------------------------------
def test_pattern_view_lists_all_patterns(qapp, bank) -> None:
    v = PatternView()
    v.bind_bank(bank)
    assert v.list.count() == L.NUM_PATTERNS == 256
    assert v.current_index == 0
    assert v.current_pattern() is bank.patterns()[0]


def test_pattern_view_shows_header_as_hex_not_fields(qapp, bank) -> None:
    """Tempo/length/last-step offsets are unproven — never render them."""
    v = PatternView()
    v.bind_bank(bank)
    text = v._header.text()
    assert "unproven" in text
    assert v._tempo.value() == pytest.approx(bank.patterns()[0].header.tempo, abs=0.05)
    assert bank.patterns()[0].header.to_bytes().hex(" ") in text
    assert f"/{L.NUM_PARAMETERS_MOTION} motion" in v._motion.text()


def test_pattern_view_rename_emits_intent(qapp, bank) -> None:
    v = PatternView()
    v.bind_bank(bank)
    edits = []
    v.patternEdited.connect(lambda: edits.append(1))
    v._name.setText("WF6TEST")
    v._rename()
    assert bank.patterns()[0].name.strip() == "WF6TEST"
    assert edits == [1]


def test_pattern_view_selection_emits_index(qapp, bank) -> None:
    v = PatternView()
    v.bind_bank(bank)
    picked = []
    v.patternSelected.connect(picked.append)
    v.list.setCurrentRow(3)
    assert picked[-1] == 3
    assert v.current_index == 3
    assert v.current_pattern() is bank.patterns()[3]


def test_pattern_view_unbinds_cleanly(qapp) -> None:
    v = PatternView()
    v.bind_bank(None)
    assert v.list.count() == 0
    assert v._header.text() == "no pattern"


# -- song view ---------------------------------------------------------------
def test_song_view_lists_every_song(qapp, bank) -> None:
    v = SongView()
    v.bind_bank(bank)
    assert len(bank.songs()) == L.NUM_SONGS == 64
    assert v.list.count() == L.NUM_SONGS
    assert v.list.item(0).text().startswith("01"), "songs display 1-based"
    assert "— unnamed —" in v.list.item(0).text()


def test_song_view_shows_the_default_chain(qapp, bank) -> None:
    """Every corpus song is untouched: one position, playing A.01, at 120 BPM."""
    v = SongView()
    v.bind_bank(bank)
    assert v.chain.rowCount() == 1
    assert v.chain.item(0, 0).text() == "1"
    assert v.chain.item(0, 1).text() == "A.01"
    assert v._tempo.value() == pytest.approx(120.0, abs=0.01)
    assert "untouched default" in v._headline.text()


def test_song_view_unbinds_cleanly(qapp) -> None:
    v = SongView()
    v.bind_bank(None)
    assert v.chain.rowCount() == 0
    assert v.list.count() == 0
    assert v._headline.text() == "no bank"
    assert not v.add_button.isEnabled()


# -- global view -------------------------------------------------------------
def test_hex_dump_formats_offsets_and_ascii() -> None:
    out = hex_dump(b"KORG" + bytes(12), base=0x20)
    assert out.startswith("00000020  4b 4f 52 47 00")
    assert out.endswith("|KORG............|")
    assert len(hex_dump(bytes(48)).splitlines()) == 3


def test_global_view_dumps_the_retained_block(qapp, bank) -> None:
    v = GlobalView()
    v.bind_bank(bank)
    raw = v.block_bytes()
    assert len(raw) == 192 == L.CHUNK_GLOBAL_PARAMETERS
    assert raw == bank.globals.to_bytes()
    assert "192 B" in v._headline.text() and "unproven" in v._headline.text()
    assert v.dump.toPlainText() == hex_dump(raw, L.ADDR_GLOBAL_PARAMETERS)


def test_global_view_does_not_decode_midi_channel(qapp, bank) -> None:
    """The view must never call the deferred decoder."""
    with pytest.raises(NotImplementedError):
        _ = bank.globals.midi_channel
    v = GlobalView()
    v.bind_bank(bank)  # would raise if the view touched the property
    assert "NotImplementedError" in v._detail.text()


def test_global_view_unbinds_cleanly(qapp) -> None:
    v = GlobalView()
    v.bind_bank(None)
    assert v.block_bytes() == b""
    assert v.dump.toPlainText() == ""


# -- shell wiring ------------------------------------------------------------
def test_main_window_tabs_are_the_real_views(qapp) -> None:
    win = MainWindow()
    assert win.tabs.count() == len(TABS) == 6
    assert isinstance(win.views["Bank"], BankView)
    assert isinstance(win.views["Staging"], StagingView)
    assert isinstance(win.views["Pattern"], PatternView)
    assert isinstance(win.views["Song"], SongView)
    assert isinstance(win.views["Global"], GlobalView)
    for name, _hint in TABS:
        assert win.tabs.indexOf(win.views[name]) >= 0
    win.close()


def test_main_window_binds_every_view_on_open(qapp, corpus_path) -> None:
    win = MainWindow()
    assert win.open_path(corpus_path) is True
    bank = win.session.bank
    assert win.pattern_view.list.count() == L.NUM_PATTERNS
    assert win.bank_view.table.rowCount() == len(
        [s for s in bank.samples() if not s.empty]
    )
    assert win.song_view.list.count() == L.NUM_SONGS
    assert len(win.global_view.block_bytes()) == 192
    win.session._dirty = False
    win.close()


def test_main_window_pattern_selection_rebinds_motion(qapp, corpus_path) -> None:
    win = MainWindow()
    win.open_path(corpus_path)
    win.pattern_view.list.setCurrentRow(5)
    expected = list(win.session.bank.patterns()[5].motion_slots())
    assert win.motion_editor._slots == expected
    win.session._dirty = False
    win.close()


def test_main_window_marks_dirty_on_view_intent(qapp, corpus_path) -> None:
    win = MainWindow()
    win.open_path(corpus_path)
    assert win.session.dirty is False
    win.pattern_view._name.setText("DIRTY")
    win.pattern_view._rename()
    assert win.session.dirty is True
    assert "modified" in win._dirty_label.text()
    win.session._dirty = False
    win.close()


def test_main_window_clear_staging_marks_dirty(qapp) -> None:
    win = MainWindow()
    win._on_clear_staging()
    assert win.session.dirty is True
    assert win.staging_view._list.count() == 0
    win.session._dirty = False
    win.close()


# -- staging: drop, picker, and the two refusal paths -------------------------
class _Mime:
    """Minimal QMimeData stand-in — the view only asks these two questions."""

    def __init__(self, urls):
        self._urls = urls

    def hasUrls(self):  # noqa: N802
        return bool(self._urls)

    def urls(self):
        return self._urls


class _DropEvent:
    def __init__(self, urls):
        self._mime = _Mime(urls)
        self.accepted = False

    def mimeData(self):  # noqa: N802
        return self._mime

    def acceptProposedAction(self):  # noqa: N802
        self.accepted = True


class _Url:
    def __init__(self, path):
        self._path = path

    def toLocalFile(self):  # noqa: N802
        return self._path


def test_staging_view_accepts_a_file_drag(qapp, tmp_path) -> None:
    v = StagingView(bank=make_staging(tmp_path))
    event = _DropEvent([_Url("/x.wav")])
    v.dragEnterEvent(event)
    assert event.accepted is True
    empty = _DropEvent([])
    v.dragEnterEvent(empty)
    assert empty.accepted is False


def test_staging_view_drop_adds_every_url(qapp, tmp_path) -> None:
    v = StagingView(bank=make_staging(tmp_path))
    urls = [
        _Url(make_wav(str(tmp_path / "d1.wav"))),
        _Url(make_wav(str(tmp_path / "d2.wav"))),
    ]
    v.dropEvent(_DropEvent(urls))
    assert v._list.count() == 2


def test_staging_view_file_picker_adds_selection(qapp, tmp_path, monkeypatch) -> None:
    import ui.views.staging_view as mod

    chosen = [make_wav(str(tmp_path / "p1.wav"))]
    monkeypatch.setattr(
        mod.QFileDialog, "getOpenFileNames", lambda *a, **k: (chosen, "")
    )
    v = StagingView(bank=make_staging(tmp_path))
    v._pick()
    assert v._list.count() == 1


def test_staging_view_surfaces_a_blocked_sample(qapp, tmp_path, monkeypatch) -> None:
    """A BLOCK-level limit must reach the user, not vanish into a log."""
    import ui.views.staging_view as mod
    from workspace.errors import StagingBlockedError
    from workspace.limits import Finding, Severity

    warned = []
    monkeypatch.setattr(
        mod.QMessageBox,
        "warning",
        lambda _p, title, text, *a, **k: warned.append(title),
    )
    v = StagingView(bank=make_staging(tmp_path))
    blocked = StagingBlockedError(
        (Finding(Severity.BLOCK, "exceeds_single_cap", "too big"),)
    )
    monkeypatch.setattr(
        type(v.bank), "add", lambda *a, **k: (_ for _ in ()).throw(blocked)
    )
    v.add_path(make_wav(str(tmp_path / "big.wav")))
    assert warned == ["Sample blocked"]
    assert v._list.count() == 0


def test_staging_view_surfaces_an_unreadable_file(qapp, tmp_path, monkeypatch) -> None:
    import ui.views.staging_view as mod

    warned = []
    monkeypatch.setattr(
        mod.QMessageBox,
        "warning",
        lambda _p, title, text, *a, **k: warned.append(title),
    )
    v = StagingView(bank=make_staging(tmp_path))
    broken = tmp_path / "broken.wav"
    broken.write_bytes(b"not really a wav")
    v.add_path(str(broken))
    assert warned == ["Could not add"]
    assert v._list.count() == 0


def test_staging_view_uses_the_selected_tier(qapp, tmp_path) -> None:
    v = StagingView(bank=make_staging(tmp_path))
    v._tier.setCurrentIndex(v._tier.count() - 1)
    lowest = v._tier.currentData()
    v.add_path(make_wav(str(tmp_path / "tier.wav"), seconds=0.2))
    assert v.bank.samples()[0].spec.rate == lowest


# -- song / pattern edge cases ------------------------------------------------
def test_song_view_edits_the_chain_and_reports_it(qapp, bank) -> None:
    v = SongView()
    v.bind_bank(bank)
    edits = []
    v.songEdited.connect(lambda: edits.append(1))

    v.pattern_picker.setCurrentIndex(65)  # B.02
    v.add_pattern()
    assert v.chain.rowCount() == 2
    assert v.chain.item(1, 1).text() == "B.02"
    assert bank.songs()[0].chain == (0, 65)

    v.chain.setCurrentCell(1, 0)
    v.move_position(-1)
    assert bank.songs()[0].chain == (65, 0)
    assert v.chain.item(0, 1).text() == "B.02"

    v.chain.setCurrentCell(0, 0)
    v.remove_position()
    assert bank.songs()[0].chain == (0,)
    assert edits, "every chain edit marks the bank modified"

    bank.songs()[0].clear()  # leave the shared fixture as it was found


def test_song_view_refuses_to_empty_a_chain(qapp, bank, monkeypatch) -> None:
    """A song always plays at least one pattern — warn, do not corrupt."""
    warned = []
    monkeypatch.setattr(
        song_view_mod.QMessageBox, "warning", lambda *a, **k: warned.append(a[2])
    )
    v = SongView()
    v.bind_bank(bank)
    v.chain.setCurrentCell(0, 0)
    v.remove_position()
    assert warned and "at least one pattern" in warned[0]
    assert bank.songs()[0].chain == (0,)


def test_song_view_renames_and_retempos(qapp, bank) -> None:
    v = SongView()
    v.bind_bank(bank)
    v._name.setText("BIBTEST")
    v._rename()
    v._tempo.setValue(140.0)
    assert bank.songs()[0].name == "BIBTEST"
    assert bank.songs()[0].tempo == pytest.approx(140.0, abs=0.01)
    assert "BIBTEST" in v.list.item(0).text()
    bank.songs()[0].clear()


def test_pattern_view_rename_without_a_bank_is_a_no_op(qapp) -> None:
    v = PatternView()
    edits = []
    v.patternEdited.connect(lambda: edits.append(1))
    v._rename()
    assert edits == []


def test_pattern_view_current_pattern_out_of_range(qapp, bank) -> None:
    v = PatternView()
    v.bind_bank(bank)
    v._index = 99999
    assert v.current_pattern() is None


def test_bank_view_survives_a_bank_without_a_sample_header(qapp, bank, monkeypatch):
    """pcm_used_bytes() raises on a PSG bank — fall back to the PCM length."""
    v = BankView()
    monkeypatch.setattr(
        type(bank),
        "pcm_used_bytes",
        lambda self: (_ for _ in ()).throw(RuntimeError("psg")),
    )
    v.bind_bank(bank)
    assert v.meter.used == len(bank.pcm)


# -- the WAV adapter ----------------------------------------------------------
def test_passthrough_probes_a_real_wav(tmp_path) -> None:
    src = make_wav(str(tmp_path / "probe.wav"), seconds=0.5, rate=22050)
    duration, rate, channels = WavPassthroughConverter().probe_duration(src)
    assert rate == 22050 and channels == 1
    assert abs(duration - 0.5) < 0.001


def test_passthrough_translates_backend_errors(tmp_path) -> None:
    """A bad WAV must surface as ValueError, not the `wave` module's own type."""
    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"definitely not a wav")
    with pytest.raises(ValueError):
        WavPassthroughConverter().probe_duration(str(bad))


def test_passthrough_copy_never_touches_the_original(tmp_path) -> None:
    from audio.ports import ConversionSpec

    src = make_wav(str(tmp_path / "orig.wav"))
    before = open(src, "rb").read()
    dst = str(tmp_path / "copy.wav")
    WavPassthroughConverter().convert(src, dst, ConversionSpec(44100, 1))
    assert open(dst, "rb").read() == before
    assert open(src, "rb").read() == before


def test_null_key_detector_never_guesses(tmp_path) -> None:
    src = make_wav(str(tmp_path / "kick2.wav"))
    assert NullKeyDetector().detect(src) is None
    assert NullKeyDetector().detect(src, max_seconds=5.0) is None


def test_passthrough_rejects_a_zero_rate_header(tmp_path) -> None:
    """A hand-built WAV claiming 0 Hz would divide by zero — refuse it instead."""
    import struct

    data = (
        b"RIFF"
        + struct.pack("<I", 36)
        + b"WAVE"
        + b"fmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, 0, 0, 2, 16)
        + b"data"
        + struct.pack("<I", 0)
    )
    bad = tmp_path / "zero.wav"
    bad.write_bytes(data)
    with pytest.raises(ValueError):
        WavPassthroughConverter().probe_duration(str(bad))


# -- tempo, the one decoded header field --------------------------------------
def test_pattern_view_edits_tempo_and_emits_intent(qapp, bank) -> None:
    v = PatternView()
    v.bind_bank(bank)
    edits = []
    v.patternEdited.connect(lambda: edits.append(1))
    v._tempo.setValue(101.5)
    assert bank.patterns()[0].header.tempo == pytest.approx(101.5, abs=0.01)
    assert edits


def test_pattern_view_binding_does_not_emit_a_spurious_edit(qapp, bank) -> None:
    """Loading a pattern into the spinbox must not look like a user edit."""
    v = PatternView()
    edits = []
    v.patternEdited.connect(lambda: edits.append(1))
    v.bind_bank(bank)
    v.list.setCurrentRow(4)
    assert edits == []


def test_pattern_view_disables_tempo_with_no_bank(qapp) -> None:
    v = PatternView()
    v.bind_bank(None)
    assert not v._tempo.isEnabled()


# -- songs: two fields decodable, the rest deliberately not -------------------
def test_song_view_explains_what_is_still_undecoded(qapp, bank) -> None:
    v = SongView()
    v.bind_bank(bank)
    detail = v._detail.text()
    assert "tempo lock" in detail
    assert "guessing" in detail


def test_songs_decode_only_what_the_evidence_supports(bank) -> None:
    """Name, tempo and chain are readable; the rest still refuses."""
    song = bank.songs()[0]
    assert song.name == ""
    assert song.tempo == pytest.approx(120.0, abs=0.01)
    assert song.is_blank is True
    assert song.length == 1 and song.chain == (0,)
    assert len(song.to_bytes()) == L.CHUNK_SONG
    for field in ("tempo_lock", "mute_hold", "next_song"):
        with pytest.raises(NotImplementedError, match="not decoded"):
            getattr(song, field)


def test_parsing_songs_does_not_affect_the_round_trip(corpus_path) -> None:
    """Songs are read for display; the writer still replays the region.

    Parses its OWN bank rather than using the shared session fixture, which
    earlier tests deliberately mutate.
    """
    from codec.reader import BankReader
    from codec.writer import BankWriter

    with open(corpus_path, "rb") as handle:
        original = handle.read()
    fresh = BankReader().read_auto(original)
    assert len(fresh.songs()) == L.NUM_SONGS
    assert BankWriter().write(fresh) == original
