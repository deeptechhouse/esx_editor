"""Workspace layer: budget arithmetic, limits policy, naming, staging lifecycle."""

from __future__ import annotations

import os

import pytest

from audio.ports import ConversionSpec, KeyResult
from workspace.budget import CAPACITY, BudgetCalculator, BudgetItem
from workspace.errors import StagingBlockedError
from workspace.limits import (
    SIZE_WARNING_CODES,
    SampleLimitPolicy,
    Severity,
    WarningPolicy,
)
from workspace.naming import classical, pack_slot_name, staging_filename
from workspace.staging import SessionWorkspace, StagingBank


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------
def test_align_up_and_cost_bytes() -> None:
    calc = BudgetCalculator()
    assert calc.align_up(0, 4) == 0
    assert calc.align_up(1, 4) == 4
    assert calc.align_up(4, 4) == 4
    # 1.0 s at 44100 mono: 16 B block header + 88,200 B audio = 88,216;
    # +2 -> 88,218; align_up(.,4) -> 88,220.
    assert calc.cost_bytes(1.0, 44100, 1) == 88220
    # Stereo doubles the AUDIO. The block header is per block, counted once.
    stereo = calc.cost_bytes(1.0, 44100, 2)
    assert stereo == calc.align_up(16 + 44100 * 2 * 2 + 2, 4)


def test_total_cost_honours_rate_for() -> None:
    calc = BudgetCalculator()
    items = [
        BudgetItem("kick.wav", 1.0, 44100, 1),
        BudgetItem("snare.wav", 1.0, 44100, 1),
    ]
    default = calc.total_cost(items)
    radio = calc.total_cost(items, rate_for=lambda _n: 22050)
    assert radio < default
    mixed = calc.total_cost(items, rate_for=lambda n: 22050 if "snare" in n else 44100)
    assert radio < mixed < default


def test_seconds_available_empty_bank() -> None:
    calc = BudgetCalculator()
    assert calc.seconds_available(44100, 1) == pytest.approx(CAPACITY / (44100 * 2))
    assert calc.remaining_bytes(0) == CAPACITY


def test_budget_rejects_bad_inputs() -> None:
    calc = BudgetCalculator()
    with pytest.raises(ValueError):
        calc.align_up(4, 0)
    with pytest.raises(ValueError):
        calc.cost_bytes(-1, 44100)
    with pytest.raises(ValueError):
        calc.seconds_available(0)


# ---------------------------------------------------------------------------
# Naming
# ---------------------------------------------------------------------------
def test_pack_slot_name_short_form_examples() -> None:
    # TDD §5.3 table: 8B C major short form keeps 4 chars of KICKDRUM -> b08CDRUM
    assert pack_slot_name("kickdrum", "8B") == "b08CDRUM"
    assert pack_slot_name("kickdrum", "8A") == "a08AmRUM"
    assert len(pack_slot_name("kickdrum", "12A")) == 8


def test_pack_slot_name_without_key_uses_tail() -> None:
    assert pack_slot_name("kick01", None) == "KICK01  "
    assert staging_filename("kickdrum.wav", "Am", "8A") == "kickdrum_Am_8A.wav"
    assert staging_filename("kickdrum.wav", None, None) == "kickdrum.wav"
    assert classical("8A") == "Am"
    assert classical("8B") == "C"


def test_classical_unknown_raises() -> None:
    with pytest.raises(ValueError):
        classical("99Z")


# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------
def test_ok_sample_and_mute_policy(tmp_path) -> None:
    p = tmp_path / "tiny.wav"
    p.write_bytes(b"RIFF")
    policy = SampleLimitPolicy()
    findings, analyse = policy.check_sample(str(p), 1.0, 1, 44100)
    assert analyse is True
    assert findings[0].level == Severity.OK
    wp = WarningPolicy()
    assert wp.visible(findings) == ()  # OK findings are hidden
    wp.mute("large_sample")
    wp.mute_size_warnings()
    assert set(wp.muted) == SIZE_WARNING_CODES
    wp.unmute("large_sample")
    assert "large_sample" not in wp.muted


def test_analysis_skipped_on_long_file(tmp_path) -> None:
    p = tmp_path / "long.wav"
    p.write_bytes(b"RIFF")
    findings, analyse = SampleLimitPolicy().check_sample(str(p), 90.0, 1, 44100)
    assert analyse is False
    assert any(f.code == "analysis_skipped" for f in findings)


def test_block_exceeds_single_cap(tmp_path) -> None:
    p = tmp_path / "huge.wav"
    p.write_bytes(b"RIFF")
    # ~285 s at CD is the whole bank; 0.80 cap is ~228 s.
    findings, _ = SampleLimitPolicy().check_sample(str(p), 250.0, 1, 44100)
    assert any(
        f.level == Severity.BLOCK and f.code == "exceeds_single_cap" for f in findings
    )
    assert all(not f.dismissible for f in findings if f.level == Severity.BLOCK)


def test_block_exceeds_free_space(tmp_path) -> None:
    p = tmp_path / "mid.wav"
    p.write_bytes(b"RIFF")
    findings, _ = SampleLimitPolicy().check_sample(
        str(p), 10.0, 1, 44100, used_bytes=CAPACITY - 100
    )
    assert any(f.code == "exceeds_free" for f in findings)


def test_large_sample_and_source_warnings(tmp_path) -> None:
    p = tmp_path / "bigsrc.wav"
    p.write_bytes(b"\x00" * (21 * 1024 * 1024))
    findings, _ = SampleLimitPolicy().check_sample(str(p), 40.0, 1, 44100)
    codes = {f.code for f in findings}
    assert "large_sample" in codes or "dominant_sample" in codes
    assert "large_source" in codes
    wp = WarningPolicy()
    wp.mute_size_warnings()
    vis = wp.visible(findings)
    assert not any(f.code in SIZE_WARNING_CODES for f in vis)


def test_block_never_muted(tmp_path) -> None:
    p = tmp_path / "x.wav"
    p.write_bytes(b"x")
    findings, _ = SampleLimitPolicy().check_sample(str(p), 250.0, 1, 44100)
    wp = WarningPolicy()
    wp.mute("exceeds_single_cap")
    vis = wp.visible(findings)
    assert any(f.level == Severity.BLOCK for f in vis)


# ---------------------------------------------------------------------------
# Staging lifecycle
# ---------------------------------------------------------------------------
class _FakeConverter:
    def __init__(self, duration=1.0):
        self.duration = duration
        self.converted = []

    def probe_duration(self, src_path: str):
        return (self.duration, 44100, 1)

    def convert(self, src_path, dst_path, spec):
        os.makedirs(os.path.dirname(dst_path), exist_ok=True)
        with open(dst_path, "wb") as f:
            f.write(b"RIFFFAKE")
        self.converted.append((src_path, dst_path, spec))


class _FakeDetector:
    def detect(self, path, max_seconds=None):
        return KeyResult("8A", "Am", 0.9)


def test_session_create_lockfile_and_clear(tmp_path) -> None:
    ws = SessionWorkspace(temp_root=str(tmp_path))
    path = ws.create()
    assert os.path.isdir(path)
    assert os.path.exists(os.path.join(path, ".lock"))
    assert ws.path == path
    ws.clear()
    assert not os.path.isdir(path)


def test_orphan_sweep_removes_dead_pid(tmp_path) -> None:
    orphan = tmp_path / "esxstudio-999999-dead"
    orphan.mkdir()
    (orphan / ".lock").write_text("999999")
    live = tmp_path / "esxstudio-live"
    live.mkdir()
    (live / ".lock").write_text(str(os.getpid()))
    ws = SessionWorkspace(temp_root=str(tmp_path))
    n = ws.sweep_orphans()
    assert n >= 1
    assert not orphan.exists()
    assert live.exists()


def test_staging_add_converts_analyses_renames(tmp_path) -> None:
    src = tmp_path / "kickdrum.wav"
    src.write_bytes(b"RIFF")
    session = SessionWorkspace(temp_root=str(tmp_path / "tmp"))
    bank = StagingBank(_FakeConverter(), _FakeDetector(), SampleLimitPolicy(), session)
    sample = bank.add(str(src), ConversionSpec(44100, 1))
    assert sample.key is not None
    assert sample.key.camelot == "8A"
    assert sample.staging_filename() == "kickdrum_Am_8A.wav"
    assert sample.slot_name() == "a08AmRUM"
    assert sample.converted_path and os.path.exists(sample.converted_path)
    assert sample.converted_path.endswith("kickdrum_Am_8A.wav")
    # original untouched
    assert src.read_bytes() == b"RIFF"
    bank.clear()
    assert bank.samples() == ()
    assert not os.path.exists(sample.converted_path)


def test_staging_add_blocks_oversize(tmp_path) -> None:
    src = tmp_path / "huge.wav"
    src.write_bytes(b"RIFF")
    bank = StagingBank(
        _FakeConverter(duration=250.0),
        _FakeDetector(),
        SampleLimitPolicy(),
        SessionWorkspace(temp_root=str(tmp_path / "tmp")),
    )
    with pytest.raises(StagingBlockedError):
        bank.add(str(src), ConversionSpec(44100, 1))
    assert bank.samples() == ()


def test_staging_skips_key_on_long_file(tmp_path) -> None:
    src = tmp_path / "loop.wav"
    src.write_bytes(b"RIFF")
    bank = StagingBank(
        _FakeConverter(duration=90.0),
        _FakeDetector(),
        SampleLimitPolicy(),
        SessionWorkspace(temp_root=str(tmp_path / "tmp")),
    )
    sample = bank.add(str(src), ConversionSpec(11025, 1))  # telephone: will fit
    assert sample.key is None
    assert sample.staging_filename() == "loop.wav"
