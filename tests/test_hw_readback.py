"""
Tests for deploy/hw_readback.py — the return half of the hardware test.

WHY THESE MATTER MORE THAN THEY LOOK
    This tool is used exactly once per hardware session, with the device on the
    desk and the card already back in the reader. If it silently reports
    "not returned" for a test that WAS done — which is what a case-sensitive
    glob did on the first run, because the ESX-1 writes T3.ESX and not
    t3_sample.esx — the session is wasted and nobody finds out until the next
    one. So the filename routing and the comparison rules are tested here
    rather than discovered in the field.

    The fixtures are synthetic: tests/synthetic.build() makes a coherent bank
    without needing a real .esx, which are gitignored and absent on a fresh
    clone.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from codec.reader import BankReader  # noqa: E402
from codec.writer import BankWriter  # noqa: E402
from deploy import hw_readback as rb  # noqa: E402
from tests import synthetic  # noqa: E402


# ---------------------------------------------------------------------------
# Filename routing
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "filename,expected",
    [
        ("t0_identical.esx", "t0"),
        ("T3.ESX", "t3"),  # what the machine actually writes
        ("T3 BACK.ESX", "t3"),
        ("t7_ccprobe.esx", "t7"),
        ("copy of T6.esx", "t6"),
    ],
)
def test_routes_machine_written_names(filename, expected):
    match = rb.TEST_TOKEN.search(filename)
    assert match is not None, f"{filename} should route"
    assert match.group(1).lower() == expected


@pytest.mark.parametrize("filename", ["output3.esx", "mybeats.esx", "set2.esx"])
def test_does_not_route_unrelated_names(filename):
    # Routing a user's own bank onto a test would compare it against something
    # it has nothing to do with, and report a spurious CHANGED.
    assert rb.TEST_TOKEN.search(filename) is None


def test_finds_uppercase_files(tmp_path):
    """The regression that started this file: glob('*.esx') misses T0.ESX."""
    (tmp_path / "T0.ESX").write_bytes(b"")
    (tmp_path / "t1_tempo.esx").write_bytes(b"")
    session = rb.ReadBackSession(str(tmp_path), str(tmp_path))
    session._manifest = {"tests": {"t0_identical": {}, "t1_tempo": {}}}
    matched = session.match()
    assert set(matched) == {"t0_identical", "t1_tempo"}


def test_ignores_appledouble_sidecars(tmp_path):
    (tmp_path / "._T0.ESX").write_bytes(b"junk")
    session = rb.ReadBackSession(str(tmp_path), str(tmp_path))
    session._manifest = {"tests": {"t0_identical": {}}}
    assert session.match() == {}


# ---------------------------------------------------------------------------
# Comparison rules
# ---------------------------------------------------------------------------
def test_json_list_equals_live_tuple():
    # song.chain is a tuple; the manifest round-trips through JSON as a list.
    # A naive == would call an identical chain a mismatch.
    assert rb._equal([1, 0, 3, 5], (1, 0, 3, 5))


def test_int_equals_float():
    assert rb._equal(133, 133.0)


def test_bool_not_confused_with_int():
    assert rb._equal(True, True)
    assert not rb._equal(True, False)


def test_detects_a_real_difference():
    assert not rb._equal([1, 0, 3, 5], [1, 0, 3])
    assert not rb._equal(133.0, 95.0)


# ---------------------------------------------------------------------------
# Probe coverage — every kind the generator emits must have a reader
# ---------------------------------------------------------------------------
def test_every_generated_kind_has_a_probe():
    """If make_hw_test_banks.py learns a new expect() kind, this fails.

    Read out of the generator's source rather than duplicated here, so the
    two files cannot drift into disagreement — which is the whole reason the
    manifest exists in the first place.
    """
    generator = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "deploy",
        "make_hw_test_banks.py",
    )
    with open(generator, encoding="utf-8") as fh:
        source = fh.read()

    import re

    kinds = set(re.findall(r'expect\(\s*"([a-z_]+)"', source))
    assert kinds, "no expect() calls found — did the generator change shape?"
    missing = {k for k in kinds if rb.Probe.for_kind(k) is None}
    assert not missing, f"no probe implements: {sorted(missing)}"


# ---------------------------------------------------------------------------
# End to end, against a synthetic bank
# ---------------------------------------------------------------------------
@pytest.fixture
def session_dirs(tmp_path):
    """A generated dir with one bank + manifest, and an empty returned dir."""
    generated = tmp_path / "generated"
    returned = tmp_path / "returned"
    generated.mkdir()
    returned.mkdir()

    raw = synthetic.build()
    bank = BankReader().read_auto(raw)
    bank.patterns()[0].header.set_tempo(133.0)
    written = BankWriter().write(bank)
    (generated / "t1_tempo.esx").write_bytes(written)

    manifest = {
        "source": "synthetic",
        "source_bytes": len(raw),
        "tests": {
            "t1_tempo": {
                "summary": "one tempo (2-byte field)",
                "file": "t1_tempo.esx",
                "bytes_changed": 1,
                "changes": ["tempo -> 133.0"],
                "expect": [{"kind": "pattern_tempo", "pattern": 0, "value": 133.0}],
            }
        },
    }
    (generated / "manifest.json").write_text(json.dumps(manifest))
    return generated, returned, written


def test_preserved_bank_reports_clean(session_dirs):
    generated, returned, written = session_dirs
    (returned / "T1.ESX").write_bytes(written)

    session = rb.ReadBackSession(str(generated), str(returned))
    session.load_manifest()
    outcome = session.evaluate(session.match())[0]

    assert outcome.returned
    assert outcome.clean


def test_machine_rewriting_the_field_is_caught(session_dirs):
    generated, returned, written = session_dirs
    # Simulate a machine that "repaired" the tempo back to its own default.
    bank = BankReader().read_auto(written)
    bank.patterns()[0].header.set_tempo(95.0)
    (returned / "T1.ESX").write_bytes(BankWriter().write(bank))

    session = rb.ReadBackSession(str(generated), str(returned))
    session.load_manifest()
    outcome = session.evaluate(session.match())[0]

    assert outcome.returned
    assert not outcome.clean
    assert "95.0" in outcome.report()
    assert "133.0" in outcome.report()


def test_missing_save_is_reported_as_not_returned(session_dirs):
    generated, returned, _ = session_dirs
    session = rb.ReadBackSession(str(generated), str(returned))
    session.load_manifest()
    outcome = session.evaluate(session.match())[0]

    assert not outcome.returned
    assert not outcome.clean
    assert "not returned" in outcome.report()


def test_unparseable_save_is_a_finding_not_a_crash(session_dirs):
    generated, returned, written = session_dirs
    (returned / "T1.ESX").write_bytes(b"\x00" * 64)

    session = rb.ReadBackSession(str(generated), str(returned))
    session.load_manifest()
    outcome = session.evaluate(session.match())[0]

    assert outcome.returned
    assert not outcome.clean
    assert "COULD NOT READ" in outcome.report()


def test_missing_manifest_explains_how_to_generate(tmp_path):
    session = rb.ReadBackSession(str(tmp_path), str(tmp_path))
    with pytest.raises(SystemExit) as exc:
        session.load_manifest()
    assert "make_hw_test_banks.py" in str(exc.value)
