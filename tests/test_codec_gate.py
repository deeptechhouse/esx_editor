"""
WF3 — the gate barrier.

This is the integration + adversarial suite that guards the codec. It:
  * re-proves the byte-identical round-trip through the real packages,
  * exercises every codec module for coverage (hard exit: >=98% on codec/),
  * attacks the reader/writer with malformed and mutated input,
  * proves edits are surgical (only intended bytes change) and re-readable,
  * proves the write-side safety protocol (verify -> atomic replace -> .bak)
    and the incoherent-bank refusal.

Copyrighted banks are not committed; tests that need a real bank skip when the
corpus is absent.
"""

from __future__ import annotations

import os
import glob
import struct
import tempfile
from unittest import mock

import pytest

import codec.layout as L
from codec.errors import CodecError, FormatError, RoundTripError
from codec.byte_buffer import ByteReader, ByteWriter
from codec.reader import BankReader
from codec.writer import BankWriter
from codec.validator import BankValidator, ValidationReport, Finding
from codec.operation_table import OperationTable, MotionTarget
from codec.template import BankTemplate
from core.motion import MotionSlot

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESEARCH_DIR = os.path.join(PROJECT_ROOT, "research")
CLEAN_BANK = os.path.join(PROJECT_ROOT, "corpus", "Chronic-Interactive.esx")


def _corpus_files() -> list[str]:
    paths = glob.glob(os.path.join(PROJECT_ROOT, "corpus", "**", "*.esx"),
                      recursive=True)
    paths += glob.glob(os.path.join(PROJECT_ROOT, "spike_a", "*.esx"))
    return sorted(set(paths))


def _require(path: str) -> bytes:
    if not os.path.exists(path):
        pytest.skip(f"corpus file absent: {path}")
    with open(path, "rb") as f:
        return f.read()


def _clean_image() -> bytes:
    return _require(CLEAN_BANK)


def _edit(data: bytes, edits: dict[int, bytes]) -> bytes:
    """Return a copy of `data` with raw byte-slices patched at absolute offsets."""
    buf = bytearray(data)
    for off, raw in edits.items():
        buf[off:off + len(raw)] = raw
    return bytes(buf)


def _u32(v: int) -> bytes:
    return struct.pack(">I", v)


# ---------------------------------------------------------------------------
# 1. The gate: byte-identical round-trip
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("path", _corpus_files() or [pytest.param(
    "", marks=pytest.mark.skip(reason="no corpus .esx files present"))])
def test_gate_roundtrip_byte_identical(path: str) -> None:
    original = _require(path)
    bank = BankReader().read_auto(original)
    assert BankWriter().write(bank) == original


# ---------------------------------------------------------------------------
# 2. Surgical edits: only intended bytes change, and the result re-reads
# ---------------------------------------------------------------------------
def test_edit_motion_value_is_surgical() -> None:
    data = _clean_image()
    bank = BankReader().read_auto(data)
    pat = bank.patterns()[0]
    slot = pat.motion_slots()[0]
    new = MotionSlot(slot.target, bytes([(b + 1) & 0x7F for b in slot.values]))
    pat.replace_motion(0, new)

    out = BankWriter().write(bank)
    assert len(out) == len(data)
    diffs = [i for i in range(len(data)) if out[i] != data[i]]
    # Every differing byte must fall inside pattern 0's motion slot 0 region.
    base = L.ADDR_PATTERN_DATA + L.PAT_OFF_PARAMETERS_MOTION
    lo, hi = base + 2, base + L.CHUNK_PARAMETERS_MOTION  # skip the 2-byte target
    assert diffs, "edit produced no change"
    assert all(lo <= d < hi for d in diffs)
    # ...and the mutated image is still valid and re-reads to the same bytes.
    assert BankWriter().write(BankReader().read_auto(out)) == out


def test_edit_sample_name_is_surgical() -> None:
    data = _clean_image()
    bank = BankReader().read_auto(data)
    bank.samples()[0].set_name("HELLO")
    out = BankWriter().write(bank)
    diffs = [i for i in range(len(data)) if out[i] != data[i]]
    assert all(L.ADDR_SAMPLE_HEADER_MONO <= d < L.ADDR_SAMPLE_HEADER_MONO + 8
               for d in diffs)


# ---------------------------------------------------------------------------
# 3. Adversarial: malformed input must raise FormatError, never corrupt
# ---------------------------------------------------------------------------
def test_read_rejects_short_file() -> None:
    with pytest.raises(FormatError):
        BankReader().read(b"KORG" + b"\x00" * 100)


def test_read_rejects_bad_head_magic() -> None:
    data = _clean_image()
    with pytest.raises(FormatError):
        BankReader().read(_edit(data, {0: b"XXXX"}))


def test_read_rejects_missing_esx_tag() -> None:
    data = _clean_image()
    corrupt = b"KORG" + b"\x00" * 28 + data[32:]
    with pytest.raises(FormatError):
        BankReader().read(corrupt)


def test_read_rejects_missing_sample_area_magic() -> None:
    data = _clean_image()
    with pytest.raises(FormatError):
        BankReader().read(_edit(data, {L.ADDR_MAGIC_2: b"\x00" * 16}))


def test_read_psg_rejects_bad_magic() -> None:
    with pytest.raises(FormatError):
        BankReader().read_psg(b"XXXX" + b"\x00" * 100)


# ---------------------------------------------------------------------------
# 4. PSG + auto-detect paths
# ---------------------------------------------------------------------------
def test_is_psg_detection_and_roundtrip() -> None:
    data = _clean_image()
    r = BankReader()
    assert r.is_psg(data) is False
    # A truncated image (>= globals, < All-save minimum) is treated as PSG and
    # retained verbatim.
    trunc = data[:0x2000]
    assert r.is_psg(trunc) is True
    bank = r.read_auto(trunc)
    assert bank.save_type == "psg"
    assert BankWriter().write(bank) == trunc


def test_read_psg_tiny_uses_zero_globals() -> None:
    tiny = b"KORG" + b"\x00" * 20  # shorter than ADDR_UNKNOWN_1
    bank = BankReader().read_auto(tiny)
    assert bank.save_type == "psg"
    assert BankWriter().write(bank) == tiny


def test_read_file_roundtrip(tmp_path) -> None:
    data = _clean_image()
    p = tmp_path / "in.esx"
    p.write_bytes(data)
    bank = BankReader().read_file(str(p))
    assert BankWriter().write(bank) == data


# ---------------------------------------------------------------------------
# 5. Write-side safety protocol
# ---------------------------------------------------------------------------
def test_write_file_verifies_replaces_and_backs_up(tmp_path) -> None:
    data = _clean_image()
    bank = BankReader().read_auto(data)
    p = str(tmp_path / "out.esx")
    w = BankWriter()

    w.write_file(bank, p)
    assert os.path.exists(p) and not os.path.exists(p + ".bak")
    assert not glob.glob(str(tmp_path / "*.tmp"))   # temp cleaned up

    w.write_file(bank, p)                            # second write -> .bak
    assert os.path.exists(p + ".bak")
    with open(p, "rb") as f:
        assert f.read() == data


def test_write_file_no_backup_option(tmp_path) -> None:
    data = _clean_image()
    bank = BankReader().read_auto(data)
    p = str(tmp_path / "out.esx")
    w = BankWriter()
    w.write_file(bank, p)
    w.write_file(bank, p, keep_backup=False)
    assert not os.path.exists(p + ".bak")


def test_write_file_raises_roundtrip_error_on_verify_mismatch(tmp_path) -> None:
    data = _clean_image()
    bank = BankReader().read_auto(data)
    other = BankTemplate().new_bank()               # serializes to different bytes
    p = str(tmp_path / "out.esx")
    with mock.patch("codec.reader.BankReader.read_auto", return_value=other):
        with pytest.raises(RoundTripError):
            BankWriter().write_file(bank, p)
    assert not os.path.exists(p)                     # original never created
    assert not glob.glob(str(tmp_path / "*.tmp"))    # temp cleaned up


def test_write_file_refuses_incoherent_bank(tmp_path) -> None:
    e4 = os.path.join(PROJECT_ROOT, "corpus", "card_backup_2026-08-22", "e4.esx")
    data = _require(e4)
    bank = BankReader().read_auto(data)
    p = str(tmp_path / "out.esx")
    with pytest.raises(CodecError):
        BankWriter().write_file(bank, p)             # default refuses
    BankWriter().write_file(bank, p, allow_invalid=True)   # override writes
    assert os.path.exists(p)


# ---------------------------------------------------------------------------
# 6. Validator — every finding code
# ---------------------------------------------------------------------------
def _first_occupied_mono_offset() -> int:
    return L.ADDR_SAMPLE_HEADER_MONO + 0 * L.CHUNK_SAMPLE_HEADER_MONO


def _codes(report: ValidationReport) -> set[str]:
    return {f.code for f in report.findings}


def test_validate_clean_bank_ok() -> None:
    bank = BankReader().read_auto(_clean_image())
    report = BankValidator().validate(bank)
    assert report.ok
    assert report.errors() == ()


def test_validate_reversed_offsets() -> None:
    base = _first_occupied_mono_offset()
    data = _edit(_clean_image(), {base + 8: _u32(0x5000), base + 12: _u32(0x4000)})
    report = BankValidator().validate(BankReader().read_auto(data))
    assert "reversed_offsets" in _codes(report)
    assert not report.ok


def test_validate_offset_past_eof_real_bank() -> None:
    e4 = os.path.join(PROJECT_ROOT, "corpus", "card_backup_2026-08-22", "e4.esx")
    report = BankValidator().validate(BankReader().read_auto(_require(e4)))
    assert "offset_past_eof" in _codes(report)


def test_validate_rate_out_of_range() -> None:
    base = _first_occupied_mono_offset()
    data = _edit(_clean_image(), {base + 28: _u32(5)})
    report = BankValidator().validate(BankReader().read_auto(data))
    assert "rate_out_of_range" in _codes(report)


def test_validate_count_mismatch() -> None:
    data = _edit(_clean_image(), {
        L.ADDR_NUM_MONO_SAMPLES: _u32(255),
        L.ADDR_NUM_STEREO_SAMPLES: _u32(127),
    })
    report = BankValidator().validate(BankReader().read_auto(data))
    codes = _codes(report)
    assert "mono_count_mismatch" in codes and "stereo_count_mismatch" in codes


def test_validate_current_offset_low() -> None:
    data = _edit(_clean_image(), {L.ADDR_CURRENT_OFFSET: _u32(0)})
    report = BankValidator().validate(BankReader().read_auto(data))
    assert "current_offset_low" in _codes(report)


def test_validate_current_offset_past_eof() -> None:
    data = _edit(_clean_image(), {L.ADDR_CURRENT_OFFSET: _u32(0xFFFFFFF0)})
    report = BankValidator().validate(BankReader().read_auto(data))
    assert "current_offset_past_eof" in _codes(report)


def test_validate_pcm_over_capacity() -> None:
    bank = BankReader().read_auto(_clean_image())
    bank._pcm = b"\x00" * (L.MAX_SAMPLE_BYTES + 1)   # force the capacity branch
    report = BankValidator().validate(bank)
    assert "pcm_over_capacity" in _codes(report)


def test_validate_unknown_motion_target() -> None:
    ops = OperationTable.load(RESEARCH_DIR)
    bank = BankReader().read_auto(_clean_image())
    # 0x7FFE is in-use (not the empty sentinel) and not a real target id.
    bank.patterns()[0].replace_motion(0, MotionSlot(0x7FFE, bytes(128)))
    report = BankValidator(ops).validate(bank)
    assert "unknown_motion_target" in _codes(report)


def test_validate_psg_bank_skips_sample_checks() -> None:
    bank = BankReader().read_auto(_clean_image()[:0x2000])
    report = BankValidator().validate(bank)      # PSG: no sample area
    assert report.ok


def test_validation_report_helpers() -> None:
    findings = [Finding("error", "e", "boom"), Finding("warning", "w", "hmm"),
                Finding("info", "i", "fyi")]
    report = ValidationReport(findings)
    assert len(report) == 3
    assert report.errors()[0].code == "e"
    assert report.warnings()[0].code == "w"
    assert not report.ok
    assert report.findings[0].severity == "error"
    assert report.findings[0].message == "boom"
    assert "error:e" in repr(findings[0])


# ---------------------------------------------------------------------------
# 7. Operation table
# ---------------------------------------------------------------------------
def test_operation_table_loads_313() -> None:
    ops = OperationTable.load(RESEARCH_DIR)
    assert len(ops) == 313
    assert ops.is_known(0)
    assert not ops.is_known(0xABCDE)
    assert ops.get_or_none(0xABCDE) is None
    t = ops.get(0)
    assert isinstance(t, MotionTarget)
    _ = (t.target_id, t.name, t.group, t.kind, t.option_count, t.forced_trig)
    assert list(ops)                                # __iter__


def test_operation_table_resolves_discrete_domain() -> None:
    ops = OperationTable.load(RESEARCH_DIR)
    # At least one target should resolve to a forced-TRIG discrete domain
    # (e.g. Roll / Reverse / FX Select) via suffix match.
    assert any(t.forced_trig and t.option_count > 0 for t in ops)
    # ...and at least one continuous default.
    assert any(t.kind == "continuous" for t in ops)


def test_operation_table_targets_for_part_rules() -> None:
    ops = OperationTable.load(RESEARCH_DIR)
    drums = ops.targets_for_part("drum")
    assert drums and all(
        t.name.startswith("Drum") or t.name.startswith("FX") for t in drums)
    assert not any(t.name.upper().endswith("PITCH") for t in drums)
    accent = ops.targets_for_part("accent")
    assert accent and all(t.name.upper().endswith("LEVEL") for t in accent)
    audio = ops.targets_for_part("audioin")
    assert not any("PITCH" in t.name.upper() or "START POINT" in t.name.upper()
                   or t.name.upper().endswith("REVERSE") for t in audio)
    keys = ops.targets_for_part("keyboard")
    assert any("GLIDE" in t.name.upper() for t in keys)
    assert not any(t.name.upper().endswith("PITCH") for t in keys)
    with pytest.raises(ValueError):
        ops.targets_for_part("nope")


def test_operation_table_missing_domains_file() -> None:
    assert OperationTable._load_domains("/no/such/file.tsv") == {}


def test_operation_table_parses_edge_cases(tmp_path) -> None:
    targets = tmp_path / "motion_operation_table_313.tsv"
    targets.write_text(
        "# comment line\n"
        "\n"
        "notanint\tBad Id\n"
        "5\tDrum1 Roll\n"
        "6\tDrum1 FX Select\n"
        "7\tFx1Ed1 Continuous Thing\n")
    domains = tmp_path / "motion_target_domains.tsv"
    domains.write_text(
        "# header comment\n"
        "shortcol\tonly\n"
        "Roll\tROLL\tboolean\t0\t1\tOff,On\tFORCED_TRIG\n"
        "FxSel\tFX SELECT\tenum\t0\t2\tFx1,Fx2,Fx3\tFORCED_TRIG\n"
        "Bad\tBAD RANGE\tcontinuous\tx\ty\t-\tY\n")
    ops = OperationTable.load(str(tmp_path))
    assert ops.is_known(5) and ops.is_known(6) and ops.is_known(7)
    assert not ops.is_known(0)                      # "notanint" line skipped
    assert ops.get(5).option_count == 2             # ROLL boolean
    assert ops.get(6).option_count == 3             # FX SELECT enum


def test_operation_table_empty_raises(tmp_path) -> None:
    (tmp_path / "motion_operation_table_313.tsv").write_text("# nothing here\n")
    (tmp_path / "motion_target_domains.tsv").write_text("# nothing\n")
    with pytest.raises(CodecError):
        OperationTable.load(str(tmp_path))


# ---------------------------------------------------------------------------
# 8. Template
# ---------------------------------------------------------------------------
def test_template_blank_bytes_and_new_bank() -> None:
    t = BankTemplate()
    raw = t.blank_bytes()
    assert raw.startswith(L.MAGIC_HEAD)
    bank = t.new_bank()
    assert bank.save_type in ("all", "psg")


def test_template_missing_file_raises() -> None:
    t = BankTemplate()
    with mock.patch.object(BankTemplate, "_candidate_paths", return_value=()):
        with pytest.raises(CodecError):
            t.blank_bytes()


# ---------------------------------------------------------------------------
# 9. ByteReader / ByteWriter
# ---------------------------------------------------------------------------
def test_byte_reader_all_ops() -> None:
    r = ByteReader(bytes([0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07]))
    assert r.size == 7 and r.remaining == 7 and r.pos == 0
    assert r.read_u8() == 0x01
    assert r.read_u16() == 0x0203
    assert r.read_u32() == 0x04050607
    assert r.remaining == 0
    r.seek(2)
    assert r.pos == 2
    assert r.read_ascii(2) == bytes([0x03, 0x04])
    assert r.read_at(0, 2) == bytes([0x01, 0x02])   # cursor unaffected
    assert r.pos == 4


def test_byte_reader_bounds() -> None:
    r = ByteReader(b"\x00\x01")
    with pytest.raises(ValueError):
        r.seek(99)
    with pytest.raises(ValueError):
        r.read(99)
    with pytest.raises(ValueError):
        r.read_at(1, 99)


def test_byte_writer_all_ops() -> None:
    w = ByteWriter()
    w.write(b"\xAA")
    w.write_u8(0x01)
    w.write_u16(0x0203)
    w.write_u32(0x04050607)
    w.write_ascii(b"HI", 4)                          # right-padded with 0x20
    assert bytes(w.getvalue()) == (
        b"\xAA\x01\x02\x03\x04\x05\x06\x07HI  ")
    assert len(w) == 12


def test_byte_writer_range_checks() -> None:
    w = ByteWriter()
    for fn, bad in ((w.write_u8, 0x100), (w.write_u16, 0x10000),
                    (w.write_u32, 0x100000000)):
        with pytest.raises(ValueError):
            fn(bad)


def test_byte_buffer_reader_writer_roundtrip() -> None:
    w = ByteWriter()
    w.write_u16(0xBEEF)
    w.write_u32(0xDEADBEEF)
    r = ByteReader(w.getvalue())
    assert r.read_u16() == 0xBEEF
    assert r.read_u32() == 0xDEADBEEF


# ---------------------------------------------------------------------------
# 10. Layout helpers + errors
# ---------------------------------------------------------------------------
def test_layout_discrete_helpers() -> None:
    assert L.discrete_step(2) == 64
    assert L.discrete_step(3) == 43
    assert L.discrete_step(4) == 32
    assert L.encode_discrete(2, 4) == 64
    assert L.decode_discrete(64, 4) == 2


def test_layout_region_map_is_ordered_and_covers_file() -> None:
    regions = L.region_map()
    assert regions[0][0] == "magic_1"
    assert regions[-1][0] == "sample_data"
    assert regions[-1][2] is None                   # runs to EOF
    assert len(L.UNKNOWN_REGIONS) == 5


def test_error_hierarchy() -> None:
    assert issubclass(FormatError, CodecError)
    assert issubclass(RoundTripError, CodecError)


def test_audioin_hides_pitch_start_and_reverse_if_a_table_ever_lists_them() -> None:
    """The audio-in guard is dead code against the 313 table — prove it works.

    The shipped table has no 'AudioIn Pitch' / 'Start Point' / 'Reverse' target,
    so targets_for_part's audio-in filter never fires on real data. That is the
    only line in codec/ the suite does not otherwise reach, and leaving it
    unexercised means a future table addition could silently expose Pitch —
    which is exactly what TDD §12 says must not happen while its encoding is
    OPEN. A synthetic table exercises the guard directly.
    """
    from codec.operation_table import MotionTarget, OperationTable as OT

    def target(tid, name):
        return MotionTarget(tid, name, name.split(" ", 1)[0], "continuous", 0, False)

    table = OT({
        1: target(1, "AudioIn Level"),
        2: target(2, "AudioIn Pitch"),
        3: target(3, "AudioIn Start Point"),
        4: target(4, "AudioIn Reverse"),
    })
    names = [t.name for t in table.targets_for_part("audioin")]
    assert names == ["AudioIn Level"]
    # Even with the global pitch guard off, audio-in still hides all three.
    names = [t.name for t in
             table.targets_for_part("audioin", hide_unverified_pitch=False)]
    assert names == ["AudioIn Level"]
