# ESX-1 hardware session checklist

Everything still unresolved in the TDD that needs the physical machine.
**All of it is SmartMedia-card work** — none of it requires MIDI. Batch it into
one sitting; individually each item is a few minutes, but each needs the device
out and a card reader to hand.

Nothing here blocks implementation. Wave 0 (contract freeze) and Wave 1 can
proceed without any of it. Items 1 and 2 gate *features*, not the codec.

---

## 1. Pitch value mapping  — GATES the motion editor's Pitch target

**Why:** Pitch is the one motion encoding still unknown. Observed values fall in
two bands, 0–115 and 167–222, with nothing between; the manual's `-63…+63`
doesn't map onto that. Until it's resolved the editor must treat Pitch as raw
0–255 and must not expose it as a drawable target.

**Do:**
1. Pick an empty pattern, assign any sample to Drum 1.
2. Motion-record the **PITCH** knob: sweep it slowly from minimum to maximum
   across one full pattern cycle.
   (Select part → MOTION SEQ key → SMOOTH → REC → PLAY → sweep → let it cycle.)
3. Save All to card under a new name.
4. Read it: `python3 spike_a/esx_probe.py motion BANK.esx`

**Expect:** a monotonic ramp. Its minimum and maximum reveal the true endpoints,
and whether the two bands are a signed encoding or simply unused values.

---

## 2. Stereo sample header — ~~GATES stereo import~~ **CLOSED 2026-08-23 (reading)**

**Closed without hardware.** The premise was wrong: `corpus/Chronic-Interactive.esx`
contains **40 populated stereo slots**. It was added to the corpus after this
checklist was written and item 2 was never re-evaluated against it.

The layout is now VERIFIED from those slots, and it **corrects TDD §2.3** — there
is no `loopStart` in the stereo header; the rate is at 32 and the tune at 36:

```
 0..7  name                16..19 offsetChannel2Start   28..31 end
 8..11 offsetChannel1Start  20..23 offsetChannel2End     32..35 sampleRate
12..15 offsetChannel1End    24..27 start                 36..37 sampleTune
```

40/40 on every predicted property; 0/40 for the TDD's claimed rate position.
See `research/CODEC_FINDINGS_LOG.md` (WF8) and `codec/layout.py`.

**Still open — WRITING a stereo sample.** Reading a layout is weaker evidence
than writing one and having the machine accept it. `SampleSlot.set_stereo_ranges`
exists but `commit_sample` refuses stereo until this is done:

1. Commit a stereo sample with the app, Save All, load it on the ESX-1.
2. Confirm it plays in stereo and the machine does not reject the bank.

---

## 3. Displayable character set — affects the slot-naming convention

**Why:** Lowercase round-trips in the file, but those names came from truncated
WAV filenames, not typed on the machine. Whether the dial can *enter* lowercase,
whether the LCD renders it, and whether `#` exists at all are unknown — and `#`
matters for sharp keys in the `a08C#m…` convention.

**Do:**
1. Rename any sample (SHIFT + WRITE/RENAME) and dial through **every** character
   the machine offers, noting the full set. 8 characters max.
2. Save All, then: `python3 spike_a/esx_probe.py names BANK.esx`

**Expect:** the exact byte set. If `#` is absent, the naming policy needs an
`s`/`b` substitution for sharps and flats.

---

## 4. PSG save variant — codec robustness

**Why:** Save **PSG** writes pattern/song/global only, with no sample area —
a much shorter file that a naive minimum-size check would reject.

**Do:** Global → CARD → Save → choose **PSG** (not All) → save.
Then: `python3 spike_a/esx_probe.py verify PSG_BANK.esx`

---

## 5. Same bank saved twice, unchanged — are the "unknown" regions real state?

**Why:** Five regions are preserved verbatim because their meaning is unknown.
If two identical saves differ inside them, they're scratch/derived rather than
meaningful state, and the writer can relax.

**Do:** Save All as `TWICE_A`, change nothing, Save All again as `TWICE_B`.
Then: `python3 spike_a/esx_probe.py diff TWICE_A.esx TWICE_B.esx`

**Expect:** ideally byte-identical. Any differing run is reported by region name.

---

## 6. Does the machine tolerate stale sample headers?

**Why:** `Two-Lone-Swordsman_andy_mod.esx` has **80 of 233 sample headers
pointing outside the file**, at offsets beyond even the hardware's maximum
sample memory. Whether the ESX-1 loads it determines whether the editor should
*repair* such banks or *refuse* them.

**Do:** Put that bank on a card, load it, and see whether it loads cleanly,
errors, or loads with silent/missing samples.

---

## Optional: MIDI SysEx dump — a faster loop, not a requirement

Attempted 2026-08-09 and **not achieved**. Findings:

- The cable, direction, port and adapter all work — 98,000+ MIDI clock messages
  were received across three sessions.
- **Zero SysEx**, and zero control-change, in ~55 minutes of listening.
- Most likely cause: the **`PCEN` MIDI filter**. `E` = "Exclusive data
  transmission/reception" must be set to `O`, not `X`
  (GLOBAL → SHIFT+key 15 → `Filter` → key 15 → set `E` to `O`).
  The absence of CC traffic suggests `C` may be blocked too.
- Second candidate: the dump menu opens showing `Filter`; the dial must be
  turned to **`Dump`** before pressing key 15. Pressing it immediately opens the
  filter page instead, which looks like progress.
- The sequencer was running throughout (clock ≈ 113.6 BPM). Press
  **STOP/CANCEL** before attempting a dump.

**If revived:** the dump covers `PtBnkA`–`D`, `AllSng`, `Global` — patterns,
songs and global settings, but **not samples**. So it could accelerate items 1
and 5, but items 2, 3, 4 and 6 still need the card either way.

Tooling is built and tested:
`spike_midi/sysex_capture.py` (receive-only) and `spike_midi/sysex_analyse.py`.
The decoder knows a `PtBnkA` dump must unpack to exactly
64 × 4280 = **273,920 bytes**, which confirms the 7-bit encoding rather than
guessing at it.

---

## After any card session

```bash
cd esx_editor/spike_a
python3 esx_probe.py verify   ../corpus/*.esx    # the round-trip gate
python3 esx_probe.py validate ../corpus/*.esx    # internal coherence
```

Add every new bank to `deploy/transfer_to_mini.sh` → `CORPUS_FILES` so the gate
covers it on the mini too.
