#!/usr/bin/env python3
"""
Generate a graduated set of hardware test banks.

WHY GRADUATED
    No file this app has written has ever been loaded by a real ESX-1. The way
    to find out whether it works is NOT to write a fully-edited bank and see if
    it plays — if that fails you learn nothing about which of six changes broke
    it. Each bank here makes exactly ONE kind of change, ordered by how many
    bytes it touches, so a failure points at a specific decision.

WHY EACH TEST IS ALSO AN EXPERIMENT
    Every step answers a question the corpus cannot. Test 1 confirms the tempo
    scale on the machine's own display. Test 2 confirms the step bit order and
    which grid position step 0 actually is. Test 3 confirms the sample-number
    field. They are not just safety checks.

USAGE
    python3 deploy/make_hw_test_banks.py --source corpus/card_backup_2026-08-22/e4.esx
    python3 deploy/make_hw_test_banks.py --source BANK.esx --out /Volumes/CARD

Every bank is written through the normal safety path (temp -> re-read verify ->
atomic replace) and re-validated afterwards. Nothing is written to the source.

AFTER THE SESSION
    Each test also records what a bank coming BACK off the machine must show,
    into manifest.json beside the banks. Save each loaded bank back to the card,
    then:  python3 deploy/hw_readback.py hw_test RETURNED_DIR
    That answers the question the eyeball test cannot: did the machine PRESERVE
    what this editor wrote, or quietly rewrite it?
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from codec.operation_table import OperationTable  # noqa: E402
from codec.reader import BankReader  # noqa: E402
from codec.validator import BankValidator  # noqa: E402
from codec.writer import BankWriter  # noqa: E402
from core.global_params import NUM_CC_ASSIGN  # noqa: E402
from core.motion import MotionDomain  # noqa: E402
from core.pattern import pattern_label  # noqa: E402

#: Values chosen to be unmistakable on the machine's two-line display.
TEST_TEMPO = 133.0
TEST_PATTERN = 0
TEST_PART = 0
TEST_STEP = 1
TEST_NAME = "HWTEST"


def sample_label(index: int, num_mono: int = 256) -> str:
    """Machine display for a sample slot: monaural 000-255 (manual p.2019).

    Zero-based and three digits. Stereo slots restart at 000 with a stereo
    marker, so a stereo index has to be reported relative to its own pool.
    """
    if index < num_mono:
        return f"{index:03d}"
    return f"{index - num_mono:03d} (stereo)"


def _first_named_pattern(bank) -> int:
    for index, pattern in enumerate(bank.patterns()):
        if pattern.name.strip():
            return index
    return 0


def t0_identical(bank, _report, _expect):
    """No change at all."""
    return (
        "Load it and compare with the original by ear and by eye. A "
        "byte-identical file IS the original, so if this does not load, the "
        "problem is the card, the filename, or the transfer - not the editor."
    )


def t1_tempo(bank, report, expect):
    index = _first_named_pattern(bank)
    before = bank.patterns()[index].header.tempo
    bank.patterns()[index].header.set_tempo(TEST_TEMPO)
    report(f"pattern {pattern_label(index)} tempo {before:.1f} -> {TEST_TEMPO:.1f} BPM")
    expect("pattern_tempo", pattern=index, value=TEST_TEMPO)
    return (
        f"Select pattern {pattern_label(index)} and read its TEMPO.\n"
        f"       Expect exactly {TEST_TEMPO:.1f}. A different number means the "
        "1/128 BPM scale is wrong - write down what it actually says, because "
        "the ratio identifies the real scale immediately."
    )


def t2_step(bank, report, expect):
    index = _first_named_pattern(bank)
    pattern = bank.patterns()[index]
    part = next(p for p in pattern.parts() if p.has_sequence())
    sequence = part.sequence()
    was = sequence.is_active(TEST_STEP)
    sequence.set_active(TEST_STEP, not was)
    part.write_sequence(sequence)
    report(
        f"pattern {pattern_label(index)} part 1 ({part.kind}) step "
        f"{TEST_STEP} {'on->off' if was else 'off->on'}"
    )
    expect("step_active", pattern=index, part=TEST_PART, step=TEST_STEP, value=not was)
    return (
        f"Select pattern {pattern_label(index)}, part 1 ({part.kind}), and "
        f"look at step key {TEST_STEP + 1} of 16.\n"
        f"       Expect it {'UNLIT' if was else 'LIT'}. If a DIFFERENT step key "
        "changed, note WHICH one: that number alone tells us whether the bit "
        "order or the step origin is wrong."
    )


def t3_sample_number(bank, report, expect):
    index = _first_named_pattern(bank)
    part = bank.patterns()[index].parts()[TEST_PART]
    occupied = [i for i, s in enumerate(bank.samples()[:256]) if not s.empty]
    before = part.sample_number
    # Pick something far from the current value: a neighbouring slot could be
    # confused for an off-by-one, which would read as a pass.
    target = max(occupied, key=lambda i: abs(i - before)) if occupied else before
    part.set_sample_number(target)
    name = bank.samples()[target].name.strip()
    report(
        f"pattern {pattern_label(index)} part 1 sample "
        f"{sample_label(before)} -> {sample_label(target)} ({name!r})"
    )
    expect("part_sample_number", pattern=index, part=TEST_PART, value=target)
    return (
        f"Select pattern {pattern_label(index)}, part 1, and read its SAMPLE.\n"
        f"       Expect {sample_label(target)} ({name!r}), and it should SOUND "
        "different when you play the pattern.\n"
        f"       If it still shows {sample_label(before)}, the field is not what "
        "we think it is."
    )


def t4_commit(bank, report, expect):
    free = next(i for i, s in enumerate(bank.samples()[:256]) if s.empty)
    rate = 44100
    # One second of a 220 Hz square-ish tone: audible, obviously synthetic, and
    # unmistakable if it plays back at the wrong rate or byte order.
    import math
    import struct

    frames = rate
    pcm = b"".join(
        struct.pack(
            ">h", 12000 if math.sin(2 * math.pi * 220 * i / rate) > 0 else -12000
        )
        for i in range(frames)
    )
    bank.commit_sample(free, pcm, stereo=False, sample_rate=rate, name=TEST_NAME)
    report(
        f"committed {len(pcm):,} B into free mono slot {sample_label(free)} "
        f"as {TEST_NAME!r}"
    )
    expect("sample_name", slot=free, value=TEST_NAME)
    expect("sample_rate", slot=free, value=rate)
    expect("sample_bytes", slot=free, value=len(pcm))
    return (
        f"Find sample {sample_label(free)} in Sample mode.\n"
        f"       Expect the name {TEST_NAME!r} and a steady one-second buzz at "
        "A3 (220 Hz).\n"
        "       Right pitch, clean tone .... everything works.\n"
        "       Harsh static ............... PCM byte order is wrong.\n"
        "       Roughly an octave out ...... the sample-rate field is wrong.\n"
        "       Silent or slot missing ..... counts or offsets are wrong.\n"
        "       Machine refuses the bank ... the trailer or currentOffset is wrong."
    )


def t5_motion(bank, report, expect):
    index = _first_named_pattern(bank)
    pattern = bank.patterns()[index]
    slots = pattern.motion_slots()
    target = next((i for i, s in enumerate(slots) if s.in_use), None)  # noqa: E501
    if target is None:
        report("SKIPPED - this pattern has no motion slot in use")
        return None
    slot = slots[target]
    domain = MotionDomain.continuous()
    for step in range(16):
        slot.write_stored(step, 127 if step % 2 == 0 else 0, domain, length=64)
    pattern.replace_motion(target, slot)
    report(
        f"pattern {pattern_label(index)} motion slot {target} -> "
        "alternating 127/0 over 16 steps"
    )
    expect(
        "motion_stored",
        pattern=index,
        slot=target,
        value=[127 if step % 2 == 0 else 0 for step in range(16)],
    )
    return (
        f"Play pattern {pattern_label(index)} and listen to motion slot "
        f"{target}.\n"
        "       Expect a hard alternation every step, not a smooth ramp."
    )


#: The chain written by t6_song, chosen to be unmistakable on the display:
#: it starts on the SECOND pattern, goes backwards, then skips.
SONG_CHAIN = (1, 0, 3, 5)
SONG_SLOT = 3  # song 04 — leaves the two real songs on the card alone


def t6_song(bank, report, expect):
    """Write a song chain from the editor and see whether the machine plays it.

    This is the other direction of the WF17 decoding: the chain was READ from a
    bank the machine wrote, and reading it correctly does not prove writing it
    correctly. Song 04 is used so the songs already on the card are untouched.
    """
    song = bank.songs()[SONG_SLOT]
    song.clear()
    song.set_name(TEST_NAME[:8])
    song.set_chain(SONG_CHAIN)
    report(
        f"song {SONG_SLOT + 1:02d} -> {TEST_NAME}, chain "
        + " ".join(pattern_label(i) for i in SONG_CHAIN)
    )
    expect("song_name", slot=SONG_SLOT, value=TEST_NAME[:8])
    expect("song_chain", slot=SONG_SLOT, value=list(SONG_CHAIN))
    return (
        f"Song mode -> select song {SONG_SLOT + 1:02d} ({TEST_NAME}) and play it.\n"
        "       Expect exactly "
        + " -> ".join(pattern_label(i) for i in SONG_CHAIN)
        + ", in that order.\n"
        "       If the machine rejects the bank or plays a different order, the "
        "chain\n       encoding is wrong - say so, and change nothing else."
    )


#: The probe writes CC (CC_PROBE_BASE + row) into every CC-assign row, so each
#: row carries a number that is unique and immediately readable on the machine.
#: 33 rows, and CC numbers stop at 127, so the base must leave room for all of
#: them: 95..127.
CC_PROBE_BASE = 95


def t7_ccprobe(bank, report, expect):
    """Check that the editor WRITES the CC table where the machine reads it.

    The row order is settled - an independent editor's 33 knob names match the
    factory bytes position for position. What that does NOT prove is that this
    editor writes them back to the right place. Every row gets a distinct,
    ordered number, so one pass through Global > MIDIUtil > CCAsin shows
    immediately whether the knobs line up or the table is shifted.
    """
    params = bank.globals
    rows = NUM_CC_ASSIGN
    for row in range(rows):
        params.set_cc_assignment(row, CC_PROBE_BASE + row)
    report(
        f"CC assign rows 1-{rows} -> CC "
        f"{CC_PROBE_BASE}-{CC_PROBE_BASE + rows - 1}, one per row"
    )
    expect(
        "cc_assignments",
        value=[CC_PROBE_BASE + row for row in range(rows)],
    )
    return (
        "Global > SHIFT+key15 (MIDIUtil) > CCAsin.\n"
        f"       MOD SPEED must read CC {CC_PROBE_BASE}, MOD DEPTH "
        f"{CC_PROBE_BASE + 1}, FILTER CUTOFF\n"
        f"       {CC_PROBE_BASE + 5}, and FX CHAIN {CC_PROBE_BASE + rows - 1}. "
        "Spot-check those four.\n"
        "       All four right ......... the editor writes the table "
        "correctly.\n"
        "       All off by the same N .. the table offset is wrong.\n"
        "       Only some wrong ....... the row ORDER is wrong.\n"
        "       Load a t0 bank afterwards to put the factory map back."
    )


TESTS = [
    ("t0_identical", "byte-identical round-trip", t0_identical),
    ("t1_tempo", "one tempo (2-byte field)", t1_tempo),
    ("t2_step", "one step trigger (1 bit)", t2_step),
    ("t3_sample", "one part's sample number", t3_sample_number),
    ("t5_motion", "one motion slot", t5_motion),
    ("t4_commit", "a whole new sample", t4_commit),
    ("t6_song", "a song chain (4 positions)", t6_song),
    ("t7_ccprobe", "name the CC assign rows", t7_ccprobe),
]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="a bank from your card")
    parser.add_argument("--out", default="hw_test", help="output directory")
    parser.add_argument(
        "--allow-invalid",
        action="store_true",
        help="write even if the SOURCE bank is already incoherent (e4.esx is)",
    )
    args = parser.parse_args(argv)

    reader, writer = BankReader(), BankWriter()
    try:
        ops = OperationTable.load("research")
    except Exception:
        ops = None
    validator = BankValidator(ops)

    original = open(args.source, "rb").read()
    baseline = validator.validate(reader.read_auto(original))
    os.makedirs(args.out, exist_ok=True)

    print(f"source   {args.source}  ({len(original):,} B)")
    print(f"baseline {len(baseline.errors())} validation error(s) before any edit")
    if baseline.errors() and not args.allow_invalid:
        print("\n  This bank is already incoherent. That is fine as a fixture but")
        print("  it muddies a hardware test: pass --allow-invalid to proceed, or")
        print("  pick a clean bank so a failure cannot be blamed on the source.")
        return 1
    print()

    manifest: dict = {
        "source": os.path.abspath(args.source),
        "source_bytes": len(original),
        "tests": {},
    }

    for name, summary, mutate in TESTS:
        bank = reader.read_auto(original)
        notes: list[str] = []
        probes: list[dict] = []

        def expect(kind: str, _probes=probes, **params) -> None:
            """Record one fact a bank coming BACK off the machine must show.

            Written here, next to the edit, so the two cannot drift apart.
            deploy/hw_readback.py knows HOW to read each kind; this file is the
            only place that says WHAT to look for.
            """
            _probes.append({"kind": kind, **params})

        instruction = mutate(bank, notes.append, expect)
        if instruction is None:
            print(f"{name:12s} {summary:34s} SKIPPED")
            continue
        dest = os.path.join(args.out, f"{name}.esx")
        writer.write_file(bank, dest, allow_invalid=bool(baseline.errors()))
        written = open(dest, "rb").read()
        report = validator.validate(reader.read_auto(written))
        new_errors = len(report.errors()) - len(baseline.errors())
        delta = sum(
            1
            for i in range(min(len(written), len(original)))
            if written[i] != original[i]
        ) + abs(len(written) - len(original))
        flag = "" if new_errors <= 0 else f"  <-- {new_errors} NEW validation error(s)"
        plural = "byte differs" if delta == 1 else "bytes differ"
        print(f"{name:12s} {summary:34s} {delta:>9,} {plural}{flag}")
        for note in notes:
            print(f"       change: {note}")
        print(f"       ON THE MACHINE: {instruction}")
        print()
        manifest["tests"][name] = {
            "summary": summary,
            "file": os.path.basename(dest),
            "bytes_changed": delta,
            "changes": list(notes),
            "expect": probes,
        }

    # The manifest is what makes the return trip checkable. Without it,
    # deploy/hw_readback.py would need its own copy of every expected value —
    # and a second copy of a fact is a second chance to be wrong about it.
    manifest_path = os.path.join(args.out, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)
    print(f"wrote {manifest_path}")
    print()
    print("Load them in this order. Stop at the first one that misbehaves and")
    print("note exactly how - that identifies the wrong decision by itself.")
    print()
    print("While the device is out, also do research/HARDWARE_CHECKLIST.md:")
    print("  pitch knob sweep, a stereo save, a RENAME charset walk, a Save PSG,")
    print("  two unchanged Save Alls, and FX1 set to each of the 16 types.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
