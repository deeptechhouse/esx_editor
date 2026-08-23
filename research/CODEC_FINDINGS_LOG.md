# Codec Findings & Bug Log (AI-agent-oriented)

Machine- and human-readable log of format findings, bugs, and the reasoning
behind fixes. Feed this back into an agent before codec (WF2) work.

---

## 2026-08-22 — Findings from `Chronic-Interactive.esx`

Source bank: `corpus/Chronic-Interactive.esx` (8,537,724 B). Round-trip: PASS.
Contents: 140 samples in use (100 mono, **40 stereo**), 136 motion slots across
51 patterns, incl. **66 Pitch-target motion slots**. First bank in the corpus
with populated stereo samples AND pitch motion.

### Finding 1 — Pitch encoding evidence (checklist item 1)
- Pitch-target motion values span **0..255** in real user data (targets 4,68,
  100,132,164,196,228,260 = Drum/Stretch/Slice Pitch).
- Distinct values observed include the full low range 0..127 plus isolated
  **192 (0xC0)** and **255 (0xFF)**.
- Interpretation (UNCONFIRMED): consistent with a **signed int8** encoding
  (192 = -64, 255 = -1), with 128 (0x80) reserved as the per-step Disabl
  sentinel — which would explain the "gap" seen in earlier reference data
  (bands 0-115 and 167-222).
- STATUS: strong evidence, not proof. A controlled hardware PITCH-knob sweep
  with plateaus at min / center(0) / max is still needed to fix the exact
  ±range and zero point. Until then, codec MUST treat Pitch as raw 0-255 and
  MUST NOT clamp or expose it as a drawable motion target (TDD §12 risk).

### Finding 2 — Stereo header decode is unverified even though banks round-trip (item 2)
- The bank has 40 stereo samples and round-trips byte-identically, so the
  editor can safely READ/WRITE banks containing stereo without corrupting them.
- BUT decoding stereo fields is NOT yet trustworthy. Per TDD §2.3 the stereo
  sampleRate should live at header offset 36; reading it there yields a
  constant garbage value (0x85370000) across all 40 stereo slots, and offset 28
  (the mono rate offset) yields small non-rate values.
- CONCLUSION: verbatim round-trip is safe; **stereo field decode / stereo IMPORT
  remains unverified**. Since the user rarely uses stereo, hardware stereo
  confirmation is DEFERRED, not blocking. Do not ship stereo *import* until a
  known stereo sample's fields decode sanely (ideally confirmed on hardware).

### BUG 1 — `spike_a/esx_probe.py` reads sampleRate at the mono offset for stereo slots
- ERROR: `validate` reports "N sample(s) with out-of-range sample rate" for
  stereo banks (e.g. slot 258 = 5389 Hz).
- BUG: `SampleHeader.sample_rate` always does `unpack_from(">I", raw, 28)`.
  Offset 28 is the mono rate offset; for the 44-byte stereo header the rate is
  a different field (TDD §2.3 says 36, but see Finding 2 — even 36 is unclear
  for this bank).
- STATUS: NOT fixed in spike code. The correct stereo rate offset is itself
  unconfirmed (Finding 2), so patching to 36 would trade one wrong answer for
  another. RESOLUTION deferred to WF2 `codec/reader.py`, where the stereo header
  layout must be pinned against a known-good stereo sample.
- REASONING: never "fix" a decoder to a value that also fails; confirm the field
  first. For now, `validate`'s stereo-rate warning is a known false-ish positive.

---

## 2026-08-22 — WF2 (codec + core bodies implemented)

Implemented the real `codec` + `core` packages against the frozen WF1 contracts
and proved the primary gate.

### RESULT — Round-trip gate PASS through real codec/core (not just the spike)
- `BankWriter().write(BankReader().read_auto(b)) == b`, byte-for-byte, on all
  four available banks: `Chronic-Interactive.esx` (8.5 MB), `e4.esx` (4.5 MB),
  `e5.esx` (14.7 MB), `spike_a/default.esx` (2.4 MB).
- Mechanism: reader decomposes the image into contiguous spans
  (pre | patterns | mid | mono-hdrs | stereo-hdrs | tail | pcm); everything not
  modelled is held on `Bank.raw_regions` and replayed verbatim by the writer.
  Identity is structural, not incidental. Test: `tests/test_roundtrip.py`.

### DESIGN DECISION 1 — `core` imports `codec.layout` (only)
- `core.pattern` / `core.bank` read structural offsets from `codec.layout`.
- REASONING: layout.py is pure declarative data and the format's single source
  of truth (TDD §04.6). Duplicating offsets in `core` would violate DRY and risk
  drift. No codec *logic* is imported, so there is no behavioural coupling and no
  import cycle (`codec.reader` -> `core` -> `codec.layout`; layout is a leaf).
- The `core/__init__` note was updated to document this.

### DESIGN DECISION 2 — songs & PSG kept verbatim for now
- Song area lives inside the `mid` raw region (not yet decoded); `Bank.songs()`
  returns empty but no song byte is lost. Full PSG layout is retained under a
  `psg_image` raw region. Both decode in later workflows; round-trip is safe now.

### CONFIRMATION — validate() catches incoherence that round-trips fine (item 6 / stale headers)
- `e4.esx` round-trips byte-identically YET `BankValidator.validate` reports
  **17 `offset_past_eof` errors**: sample slots 2..N have header end-offsets
  (e.g. 0x5343E0) far beyond the file's PCM length (0x1FC398).
- This is the exact scenario the TDD predicts ("a bank round-trips perfectly yet
  has headers pointing outside the file") and is consistent with the **stale
  sample-header** hardware question (HARDWARE_CHECKLIST item 6 / item 4): a card
  save can leave header records referencing PCM that is no longer present.
- CONCLUSION: the parse/validate separation is working as designed. `e4.esx` is a
  useful negative fixture for a future validator test.
- ACTION: `Chronic-Interactive.esx` and `e5.esx` validate clean (0 errors,
  0 warnings) — the mono-only rate check (stereo rate skipped per BUG 1) produced
  no false positives on these banks.

### DEFERRED (documented as NotImplementedError, not silently dropped)
- Semantic field decoders (pattern tempo/length, part sample#/steps, global MIDI
  channel, sample tune) — land with the view workflows.
- `Bank.commit_sample`/`clear_sample` — capacity guard active; full PCM
  allocation lands with the staging workflow.
- `OperationTable.targets_for_part` — picker rules land with the motion editor.
  Domain resolution (id -> kind/options) is currently best-effort suffix-match;
  `is_known`/`get` (all the validator needs) are exact (313 targets loaded).

---

## 2026-08-22 — WF3 (the gate barrier)

The only barrier in the plan. Hard exit: byte-identical round-trip on the corpus
PLUS >=98% line coverage on `codec/`. Both met.

### RESULT — gate PASSED
- Round-trip byte-identical on all 4 banks (re-proven through the real packages).
- **Coverage: 100% of `codec/`** (473 stmts, 0 missed) — exceeds the 98% bar.
  `pytest tests/` = **52 passed**. Suite: `tests/test_codec_gate.py` (+ the WF2
  `tests/test_roundtrip.py`).

### INTEGRATION — `allow_invalid` wired into `writer.write_file`
- `write_file` now runs `BankValidator().validate(bank)` first and RAISES
  `CodecError` if the bank has error-severity findings, unless
  `allow_invalid=True` (TDD §4.5 "refuse to write an invalid file").
- Proven: opening `e4.esx` (17 offset-past-EOF errors) and calling `write_file`
  is refused by default and succeeds with `allow_invalid=True`.
- The round-trip re-read verification still always runs regardless of the flag.

### ADVERSARIAL — attempts to break the writer/reader (all now covered)
- Malformed input -> `FormatError` (never a corrupt write): short file, bad head
  magic, missing "ESX" tag, missing sample-area "KORG..BPS" magic, PSG bad magic.
- Surgical-edit proof: mutating one motion slot changes ONLY bytes inside that
  slot's region (target-name area excluded) and the result re-reads identically;
  same for a sample-name edit (only the 8 name bytes change).
- Write-safety proof: temp file is cleaned up on success AND on failure; `.bak`
  is created on overwrite (and skipped with `keep_backup=False`); a forced
  verify-mismatch (mocked re-read) raises `RoundTripError` and NEVER creates or
  replaces the destination file.
- Validator coverage: every finding code exercised via byte-level fixtures
  (reversed_offsets, offset_past_eof, rate_out_of_range, mono/stereo count
  mismatch, current_offset_low, current_offset_past_eof, pcm_over_capacity,
  unknown_motion_target) plus the clean-bank and PSG paths.

### NOTE — `_replace` OSError path
- `writer._replace` carries `# pragma: no cover` for its `os.replace` OSError
  branch (platform/FS-dependent, not reproducible in a unit test). This is the
  only intentionally-excluded line; coverage is otherwise total.

---

## 2026-08-22 — WF4 (UI foundation + workspace bodies)

The forked WF4 worker died at a usage-limit before writing any code; implementation
continued in the parent session on branch `feat/wf4-ui-foundation`.

### RESULT
- `workspace/`: budget (exact align_up cost model), limits (fit/analyse/warn +
  mute policy), naming (TDD §5.3 packed 8-byte + staging filename), staging
  (crash-safe session dir + PID lockfile + orphan sweep + fake-able StagingBank).
- `ui/`: token-driven theme (ESX chassis/amber LCD, WCAG AA contrast), reusable
  widgets (BudgetMeter, KnobDial, StepGrid, WaveformView), MainWindow shell with
  6 placeholder tabs, BankSession composition root (the only UI object that
  imports codec/).
- PySide6 **6.9.3** installed into `~/.venvs/esx` (pinned; 6.10+ will not install
  on macOS 12). Offscreen QApplication + QPainter grab() smoke-tested.
- `pytest tests/` = **78 passed**. No lint errors.

### DESIGN DECISIONS
- UI widgets never import codec/; BankSession is the composition root (TDD §10.2).
- View tabs are placeholders on purpose — WF6 fills Bank/Staging/Pattern/Song/Global,
  WF5 fills Motion. Shell menus (New/Open/Save) already work against BankSession.
- StagingBank.add re-encodes via the AudioConverter port from the ORIGINAL path
  (TDD §7.3); tests use fakes so no ffmpeg/librosa in this workflow.
- Naming defaults to short classical; unknown Camelot raises ValueError rather
  than packing a garbage slot name.

---

## 2026-08-22 — WF5 (motion editor)

### RESULT
- Canvas + tools + picker implemented. Tools are pure functions; the canvas
  calls the same primitives the byte-verify suite does, so drawn == scripted.
- Byte-verify PASS: N=2 {0,64}, N=3 {0,43,86}, N=4 {0,32,64,96}, Disabl=0x80,
  length-mask leaves bytes beyond N untouched, 130-byte to_bytes form matches
  Spike A framing. `pytest tests/` = 96 passed.

### RULES ENFORCED
- Discrete writes go through `snap_stored` — a Filter Type ramp never emits 1/2/3.
- Pitch is hidden from the picker (TDD §12 / encoding still OPEN).
- Forced-TRIG domains always draw as staircases, even if TRIG HOLD is unchecked.
- A 25th slot assignment is refused with a dialog, never dropped silently.
- Overwrite of a populated target asks first (hardware erases on re-assign).

### DEFERRED
- Binding to pattern N>0 (currently pattern 0 on bank open).
- OSC EDIT 1/2 are not in the 313-target TSV, so they cannot be offered.
- Pitch drawable mapping still needs the hardware knob sweep.

---

## 2026-08-23 — WF6 (views + 11-screen wizard)

Continued from `HANDOFF_claude_wf6.html` on `feat/wf6-views-wizard`. WF1–WF5 were
not touched except where noted below.

### RESULT
- `ui/views/song_view.py`, `ui/views/global_view.py`, `ui/views/__init__.py`.
- `ui/wizard/` — `context.py` (WizardContext), `pages.py` (11 pages), `wizard.py`
  (SetupWizard). Every page `isComplete() == True`.
- `ui/main_window.py` rewired: placeholders replaced with the five real views,
  `bankChanged` → `bind_bank` on all of them, pattern select → `motion_editor
  .bind_pattern`, File → "Guided setup…", Edit → "Clear staging".
- `audio/__init__.py` now exports `WavPassthroughConverter` / `NullKeyDetector`.
- Tests: `tests/test_views.py`, `tests/test_wizard.py`, `tests/test_shell_wiring.py`.
  `pytest tests/` = **203 passed** (was 96). `codec/` back to **100%**; every WF6
  module (5 views, 4 wizard modules, main_window, passthrough) at **100%**.

### BUG FOUND AND FIXED — `wave.Error` escaped the UI
- `WavPassthroughConverter.probe_duration` let `wave.Error` propagate.
  `StagingView.add_path` catches `(OSError, ValueError)`, and `wave.Error`
  is neither, so **dropping a non-WAV file with a `.wav` extension crashed the
  app**. Reproduced in a test before fixing.
- Fixed in the ADAPTER, not the view: `probe_duration` now translates
  `wave.Error` → `ValueError`. Callers hold the `AudioConverter` port, not the
  `wave` module, so they cannot reasonably be asked to catch a backend type.
  This is the ports-and-adapters boundary doing its job (TDD §5.1).

### BUG FOUND AND FIXED — menus unreachable from code
- `MainWindow._build_menus` kept no Python reference to the `QMenu`s returned by
  `addMenu()`. The wrappers were garbage-collected, so the menus still rendered
  but `RuntimeError: Internal C++ object already deleted` on any later access.
  Now retained in `self.menus`.

### COVERAGE GAP CLOSED (WF5 leftover)
- `codec/operation_table.py:193` (the audio-in Pitch/Start/Reverse filter) was
  the one uncovered line in `codec/`, because the shipped 313-target table has no
  such AudioIn targets — the guard is dead code against real data. Covered with a
  synthetic table, so a future table addition cannot silently expose Pitch.

### DESIGN DECISIONS
- **`BankSession.validate()` added** rather than importing `codec.validator` in the
  wizard's finish page. The handoff allowed the finish page to be a composition
  root; routing through the session is strictly tighter and keeps *every* widget
  free of codec imports (TDD §10.2).
- **`StagingView(bank=...)`** — the wizard's Add-samples screen renders the SAME
  `StagingBank` the Staging tab does, so a drop in one appears in the other. Two
  views over one model; no widget reparenting.
- **Song view shows bytes, not songs.** `Bank.songs()` is empty on purpose; the
  data lives in raw region `mid`. The view reports the region size and dumps the
  first 16 B of each 528 B block at the VERIFIED offset `ADDR_SONG_DATA`. Reading
  bytes at a verified region offset is not decoding; no field is interpreted.
- **Global view shows a hex dump.** `midi_channel` still raises
  `NotImplementedError` and the view never calls it (asserted by a test).
- **Part setup screen shows kind/index/chunk size/first 8 B.** `sample_number`
  and `sequence()` both raise `NotImplementedError`; the page calls neither.
- **Pattern basics screen shows header hex only.** No tempo/length/last-step.
- Wizard dialogs report failures IN-PAGE (a status label), not via `QMessageBox`,
  so a bad file cannot trap the user behind a modal — and offscreen tests do not
  stall.

### UI POLISH (theme, additive)
- `ui/theme.py` gained `QListWidget` / `QTableWidget` / `QHeaderView` /
  `QPlainTextEdit` rules: the default bright-blue selection clashed badly with the
  amber chassis. Selection is now `amber_dim` on `chassis`.
- WF6 tables hide the row-number gutter (the `#` column already carries it),
  alternate row colours, and stretch the last section.

### OPEN / DEFERRED
- `pack_slot_name` takes the LAST 8 characters of a basename, so `bass_loop`
  packs as `ASS_LOOP`. That is the frozen TDD §5.3 rule and was not changed —
  but it is a real usability wart and needs a user decision.
- `ui/widgets/placeholder.py` is now dead code (no view uses it). Left in place;
  removal is a WF7 call.
- Motion tab still binds pattern 0 on open, then follows the Pattern tab
  selection. Song/global decoding, `Bank.commit_sample`, and `Part.sample_number`
  remain `NotImplementedError` by design.

---

## 2026-08-23 — WF8 (commit_sample + three format discoveries)

Implementing `Bank.commit_sample` — the one thing the app existed for and could
not do — required decoding fields that were sitting inside a verbatim blob. That
led to three findings against real data, one of which **corrects the TDD**.

### DISCOVERY 1 — the stereo sample header layout (CORRECTS TDD §2.3)

`Chronic-Interactive.esx` contains **40 populated stereo slots**. The hardware
checklist recorded "both banks mono-only" — true of e4/e5, but the checklist was
written before Chronic was in the corpus, so item 2 was never re-evaluated
against it. No hardware was needed to close this.

The TDD inferred the 44-byte stereo layout from BLANK slots and inserted a
`loopStart` at 32, pushing `sampleRate` to 36 and `sampleTune` to 40. Real data
contradicts that. The actual layout:

```
 0..7   name                 16..19 offsetChannel2Start   28..31 end
 8..11  offsetChannel1Start  20..23 offsetChannel2End     32..35 sampleRate
12..15  offsetChannel1End    24..27 start                 36..37 sampleTune
                                                          38..43 playLevel + unknown
```

There is **no loopStart in the stereo header**; the extra 4 bytes over the mono
header are the second channel-offset pair.

Evidence, all 40/40:
- `u32@32` is a legal import rate (32000). `u32@36` is 2,234,974,208 — not a
  rate under any reading (0/40 for the TDD's claimed position).
- `u16@36` decodes via the VERIFIED tune packing to −5.55 semitones, and
  `12·log2(32000/44100) = −5.55`. The tune field independently confirms the rate
  field's position, because one is derived from the other. Delta 0.002.
- `ch2start == align_up(ch1end + 2, 4)` and `len(ch1) == len(ch2)`.
- Across the whole bank, 180 PCM ranges (100 mono + 2×40 stereo) tile with
  **zero overlaps** and 179/179 follow the allocation rule.

### DISCOVERY 2 — the PCM region is big-endian, confirmed from the audio itself

TDD §2.1 says big-endian. Rather than take that on trust: reading a real sample
both ways gives a lag-1 autocorrelation of **+0.98 big-endian vs +0.19
little-endian**, and big-endian wins on **20 of 20** samples. Audio is strongly
correlated sample to sample; the wrong byte order is nearly noise.

This matters because nothing downstream would catch it. A little-endian bank
loads, validates, and round-trips perfectly — it just plays static. `tests/
test_pcm.py::test_real_bank_pcm_is_big_endian` now guards it with the same
measurement.

### DISCOVERY 3 — the 16-byte PCM trailer mirrors currentOffset

On all four corpus banks the PCM region is **exactly currentOffset + 16 bytes**,
and bytes 4..7 of that trailer are a big-endian copy of currentOffset:

```
80 00 7f ff | <currentOffset u32> | 01 7f ff fe | 00 ff ff ff
```

Chronic 0x005D466C = 6,112,876; e5 0x00BAFA34 = 12,253,748; e4 0x001FC388 =
2,081,672 — each that bank's currentOffset. The last 12 bytes were identical on
all three machine-written banks. Committing without updating this would leave
the file internally contradictory, so `Bank._sync_trailer` patches those four
bytes and carries the rest verbatim.

### REFINEMENT — currentOffset is align_up(highest_end + 2, 4)

The documented rule was `highest_end + 2`. That holds on e5 only because its
highest end happens to be 4-aligned. Chronic needs the align_up: 6,112,872 →
6,112,876. (e4 satisfies neither, because 16 of its 18 headers are stale — it is
the incoherent fixture.)

### BUG FOUND AND FIXED — commit would overwrite a stereo sample's channel 2

`_highest_end()` used `slot.offset_end`, which for a stereo slot is **channel
1's** end. The true high-water mark is often a channel-2 end. Committing into
Chronic placed the new sample at 6,070,916 — inside existing channel-2 data.
Caught by committing into a real bank and diffing every existing sample's bytes;
now covered by `test_commit_into_a_real_bank_corrupts_nothing`.

### ARCHITECTURE — the sample-area header left the verbatim blob

The counts and currentOffset at 0x1B0020..0x1B002B are VERIFIED, but the reader
swept them into `mid` along with the songs and the undecoded gaps, making them
unwritable. `mid` is now split into `mid` / `magic2` / decoded `SampleArea` /
`hdr_gap`. "Unknown regions are never modified" still holds structurally —
`RawRegions` still has no setter. These twelve bytes were simply never unknown.
Round-trip re-verified byte-identical on all four corpus banks after the split.

### DELIBERATELY NOT DONE
- **Stereo commit.** The layout is now known and readable, and `set_stereo_ranges`
  exists, but no stereo bank this app WROTE has been loaded by hardware. Reading
  a layout is weaker evidence than writing one and having the machine accept it.
- **Compaction of a stereo bank.** Refused loudly: a stereo slot owns two ranges
  that must stay adjacent and equal-length.
- **`pack_slot_name` tail truncation.** TDD §5.3 states the tail rule is
  deliberate ("trailing characters distinguish numbered variants"), so it stands
  — but `bass_loop` → `ASS_LOOP` and `snare_hat` → `NARE_HAT` in real use. Still
  a user decision.

### RESULT
`Bank.commit_sample` / `clear_sample` / `compact_pcm`, `SampleSlot.set_range` /
`set_stereo_ranges` / `set_sample_rate` / `stored_tune` / `musical_tune` /
`set_musical_tune` / `channel2_range`, `audio/pcm.py` (endianness, folding,
splitting, 8-bit widening), `StagingBank.commit_to` (all-or-nothing batch), the
wizard's screen 7 commit button, and the bank view now showing a real stereo
rate plus musical tune. **297 tests passing**; codec/ 100%, project 92%.

---

## 2026-08-23 — WF9 (real audio adapters: ffmpeg + librosa)

The ports were frozen in WF1 and only the WAV passthrough existed. Both v1
adapters now ship, and both are OPTIONAL: the app runs, and says what it can do,
on a machine with neither.

### RESULT
- `audio/ffmpeg_adapter.py` — header-only probe via ffprobe, conversion via
  ffmpeg with anti-aliased resampling, triangular dither, and metadata stripped
  (an inherited `smpl` chunk silently redefines where a sample ENDS, manual
  p.88). Verified against wav / mp3 / flac / aiff / m4a / ogg.
- `audio/librosa_adapter.py` — CQT chroma + Krumhansl-Schmuckler, **24/24 exact**
  on synthesised triad progressions in every key.
- `audio/factory.py` — probes the machine once and reports what is live.
- `audio/pcm.py` — endianness, channel folding/splitting, 8-bit widening.
- Staging and the wizard now use whatever backend exists; the Staging tab prints
  which, rather than implying a capability it does not have.
- **330 tests** passing; codec/ 100%, project 92%, audio/ 94%.

### FINDING — this ffmpeg has no libsoxr
The TDD assumed soxr. `ffmpeg -buildconf` on this machine has no
`--enable-libsoxr`, and asking for an unavailable engine does NOT degrade: the
conversion fails outright with "Requested resampling engine is unavailable".
The adapter now probes the build once and falls back to `swr:filter_size=256`,
and `resampler_engine` reports which is in use so the UI does not advertise a
quality it did not deliver.

### FINDING — the margin metric alone cannot reject noise
The first key detector confidently labelled **white noise "Fm"**. HPSS treats
steady broadband content as harmonic, so the percussiveness gate passed, and a
flat chroma still correlates best with *something*: white noise scored a
mode-margin of 0.258, **higher than a real C major progression's 0.238**.

Added a chroma-flatness gate (geometric mean over arithmetic mean of the chroma
vector). Measured, not guessed:

```
  C major progression  0.372      white noise      0.999
  A minor progression  0.368      white noise (2)  0.999
  Am pad + hard kick   0.238      pink-ish noise   0.970
                                  kick drum        0.888
```

Threshold 0.70 sits in the empty band between 0.38 and 0.89. After the gate: all
24 keys still exact, and noise / clicks / kick / silence all correctly return
None, while an A-minor pad buried under a heavy kick is still found.

### BUG FOUND AND FIXED — Camelot minor keys were a minor third out
`camelot_for` placed a minor key at its own root's wheel position. The wheel
pairs RELATIVE keys — 8A (A minor) sits beside 8B (C major), not beside C minor
— so a minor key takes its relative major's position, three semitones up. All
12 minor codes were wrong; all 12 major codes were right, which is exactly the
kind of half-correct bug that survives a spot check. Now derived from the circle
of fifths and asserted against all 24 entries of `workspace.naming.CAMELOT`.

### BUG FOUND AND FIXED — EOFError still escaped the WAV reader
The WF6 fix translated `wave.Error` but not `EOFError`, which is what a
TRUNCATED wav raises (a partial download, a file still being written) and is
not a subclass of `wave.Error`. Same crash, different door. Both adapters now
catch it, with a test that feeds a half-written RIFF header.

### PERFORMANCE — capability detection had to be cached
Probing costs an ffmpeg subprocess plus a librosa import (seconds, via
numba/llvmlite). Every widget construction paid it, taking the suite from 35 s
to over two minutes. `detect_capabilities()` is now `lru_cache`d; the answer
cannot change while the process runs.

### PACKAGING — librosa 0.11 will not install here
It pins an older numba whose llvmlite has no cp313 x86_64 wheel, so pip tries a
source build and needs an LLVM toolchain. librosa **1.0.0** resolves to numba
0.62 / llvmlite 0.45, which ship wheels. Pinned in `requirements-audio.txt` with
a note to install `--only-binary=:all:`. This contradicts PLAN Rev 2's claim
that "numba / llvmlite cp313 x86_64 wheels exist" — true only for recent
versions, not for the ones librosa 0.11 pins.

---

## 2026-08-23 — WF10 (pattern tempo decoded; the rest proven undeterminable)

### DISCOVERY — tempo is a big-endian u16 at header offset 0, scaled by 128

`PatternHeader.tempo` no longer raises. Established across **1,024 pattern
headers in four banks**:

- 19 of 20 distinct values decode to **exact integer BPMs**: 69, 72, 80, 82, 84,
  85, 86, 89, 90, 91, 92, 95, 98, 100, 120, 124, 128, 134, 144. All inside the
  documented 20.0-300.0 range.
- The default header — on the blank template, on e5.esx, and on 204 of Chronic's
  256 patterns — is `3c 00 ...` = 15360/128 = **exactly 120.0**, the machine's
  own default.
- The competing reading (byte 0 doubled) is **ruled out** by the odd tempos: 69,
  85, 89, 91 and 95 cannot come from doubling a byte. They arise when the low
  byte is 0x80, i.e. exactly +1.00 BPM at a 1/128 scale.

Stored resolution (1/128 ≈ 0.008 BPM) is finer than the 0.1 BPM the machine
displays, so a stored value need not land on a tenth. One corpus value
(144.015625) is exactly that case.

### NEGATIVE RESULT — length, beat, last step and swing are NOT determinable

Worth recording as a result rather than a gap. Across all **52 named patterns in
the entire corpus**, header bytes 2, 4, 5, 6 and 7 are **constant**:

```
  byte 2: {0}        byte 5: {15}
  byte 4: {1}        byte 6: {0}       byte 7: {60}
```

A field that never varies cannot be distinguished from any other constant. Byte
3 does vary — {1, 3, 19, 67, 131}, i.e. low bits 1 or 3 plus at most one of bits
4/6/7 — but five values across two apparent sub-fields is not enough to assign
meanings.

`length_bars`, `last_step` and `playable_steps` therefore still raise
`NotImplementedError`, and the message now names exactly which bytes to watch,
so the hardware session knows what to diff: change ONE setting on ONE pattern,
Save All, compare. That single experiment closes all of them.

### FIXTURE — the synthetic bank now carries the machine's real default header

`tests/synthetic.py` filled pattern headers with deterministic filler, which
decoded to a nonsense tempo of 104.02. It now writes the real default
(`3c 00 00 00 00 0f 00 3c 00 00 7f ff 7f ff 7f ff`), so the fixture looks like
something an ESX-1 actually wrote. The golden hash moved as a result — that is
the golden test doing its job, and the change was intended.

### HARDWARE CHECKLIST — item 2 closed for reading
Updated `research/HARDWARE_CHECKLIST.md`: the stereo-header item was written
before Chronic-Interactive.esx joined the corpus and was never re-evaluated
against it. Reading is closed; WRITING a stereo sample still needs the machine.

---

## 2026-08-23 — WF11 (part sample numbers and step triggers decoded)

### DISCOVERY — `Part.sample_number` is a big-endian u16 at part offset 0

PROVEN, with an independent oracle:

- Across every sample-playing part in `Chronic-Interactive.esx` — 468 drum, 104
  keyboard, 156 stretch/slice — the field points at an **OCCUPIED** slot
  **728/728**. The bank has 100 occupied slots out of 384, so a wrong field
  would land on an empty one most of the time.
- That bank names its samples after their own slot index (`'00'`..`'99'`), which
  is a free oracle: the decoded number must equal `int(slot.name)`. It does, on
  **672 of 672** parts whose slot name is numeric.

Audio-in and accent parts raise instead of answering: they do not reference the
sample table (their offset 0 holds a constant 127 and values above 10,000
respectively), and returning that as a slot index would be a lie.

### DISCOVERY — the step trigger bitmap, and its bit order

16 bytes = 128 one-bit steps, END-ALIGNED in the part chunk:

```
  drum          offset 18  (18 + 16 == 34, the chunk size)
  stretchslice  offset 16  (16 + 16 == 32)
```

- The two 8-byte halves are byte-identical on **468/468** drum and **156/156**
  stretch parts — what a 64-step pattern written into a 128-step field looks
  like.
- **Bit order is LSB-first**, settled statistically rather than by eye. Read
  LSB-first, step 0 is the single most-triggered step (244 hits vs 29 for step
  1) and the quarter-note grid carries **1.85x** its uniform share. Read
  MSB-first, the busiest step becomes step 7 — a 16th-note offbeat — and grid
  concentration inverts to **0.5x**. Real drum programming puts hits on the
  beat.
- Decoded patterns are musically coherent, which is the final sanity check:
  one part triggers every other step (8th-note hats), another on steps 4, 12,
  20, 28 (the backbeat), another on 26, 58, 90, 122 (a sparse accent).

Keyboard, audio-in and accent parts are NOT decoded. Keyboard bits show **no**
grid concentration (0.80x, i.e. below uniform), consistent with note data rather
than a trigger bitmap; the other two gave no usable signal. All three raise.

### NEGATIVE RESULT — song decoding is impossible from this corpus

Recorded so nobody re-runs it. **All 64 songs in every corpus bank are
byte-identical and blank**: eight spaces (the same name convention patterns and
samples use) followed by `3c 00` — which is tempo 120.0 at the same 1/128 scale
the pattern header uses — and then zeros. Zero bytes vary across all 256 song
blocks in four banks. No user in this corpus has ever saved a song, so there is
nothing to correlate against. `Bank.songs()` stays empty and the song area stays
verbatim in the `mid` region.

(The structural hint is worth keeping for the hardware session: a song block
appears to open exactly like a pattern chunk — 8-byte space-padded name, then a
1/128-scaled tempo. One saved song would confirm or kill that in seconds.)

### FIXTURE — the synthetic bank now has a zeroed part/FX area
Filler bytes there decoded as parts triggering on roughly half their steps and
pointing at random slots, so every fixture-based assertion started from noise.
Golden hash repinned; the change was intended.

### UI
The Pattern tab now shows each part's sample number, that sample's name, and its
trigger count — and the `StepGrid` widget built in WF4 and never wired to
anything is finally live: selecting a part loads its 128 steps, and clicking a
step edits the bank. Wizard screen 8 shows the same decoded data.

### RESULT
**356 tests** passing (1 skipped: no stereo write). codec/ 100%, project 91%.

---

## 2026-08-23 — WF12 (dominant-note detection for material with no key)

User request: *"a noise still has a note correct? ... for each sound that does
not have a 'key' i would like it to show what 'note' it corresponds to."*

Correct for essentially all real material, and it is now implemented as its own
port. The distinction the UI now makes:

- A **key** is a claim about harmony — which seven notes a piece is built from.
  Most one-shots have none, and a guess gets baked into an 8-character slot name
  permanently, so the key detector is allowed to say nothing.
- A **note** is just the dominant pitch. Nearly every real sound has one: a kick
  sits around 40-60 Hz, which is a note you can tune to a bassline. This is
  often the more useful number for a sampler.
- Only genuinely broadband material — white noise, a noise-burst hi-hat — has
  neither, and that is reported as "—" rather than invented.

### WHY NOT A PITCH TRACKER
YIN/pYIN estimate the fundamental of a SUSTAINED periodic tone. Point one at a
kick and it usually reports nothing: two cycles of a falling sine under a click
is not periodic enough to track. So `audio/pitch.py` measures the dominant
SPECTRAL PEAK instead, refined by parabolic interpolation and named with its
cent deviation.

### TWO MEASURED CORRECTIONS

**1. Averaging the whole sound reads SHARP.** Percussion is pitch-swept by
design — a kick starts an octave or more above where it lands. Measuring
everything biased the result by roughly a semitone, enough to name the wrong
note. Fixed by skipping the attack: find the loudest frame, skip half of what
follows, measure the body. What a producer means by "what note is this kick" is
the body, not the click.

**2. Combine frames with a MEDIAN, not a mean.** This is what actually fixes the
sweep: the swept frequencies appear in a minority of frames while the settled
pitch appears in most. Grid-searched over sines, kicks and toms from 36 Hz to
440 Hz:

```
  mean,   skip 0.25  -> mean error 32.7 cents, worst 66.5   (2 wrong notes)
  mean,   skip 0.50  -> mean error  5.6 cents, worst 15.0
  median, skip 0.25  -> mean error 17.2 cents, worst 35.2
  median, skip 0.50  -> mean error  2.4 cents, worst  7.7   (all correct)
```

Also raised the FFT cap to 16,384: at 44.1 kHz an 8,192-point transform has
5.4 Hz bins, which is nearly **two semitones** at the 40 Hz where kicks live.

Final accuracy: **12/12** correct on sines, kicks (36-65 Hz), toms and a snare,
all within a few cents, with white noise correctly reporting nothing.

### A TESTING LESSON WORTH RECORDING
The first run showed 2 failures that were **my test signal, not the detector**:
I synthesised the pitch sweep as `sin(2π·f(t)·t)`, whose instantaneous frequency
is `f(t) + t·f'(t)`, not `f(t)`. Integrating the phase properly changed the
answer. Worth remembering before "fixing" code to match a broken fixture.

### PROMINENCE GATE
The spectral peak must stand 8x above the median magnitude to count. Measured:
sine ~1000x, tonal chord ~120x, kick ~40x, white noise ~3x. 8.0 sits well clear
of noise while admitting every real percussive sound.

### NOTE
For a chord the dominant note is the loudest PARTIAL, not necessarily the root —
an A minor triad reports E5. That is what "dominant note" means and the label
says so; the key detector is what answers "what chord is this".

---

## 2026-08-23 — WF13 (feedback from first real launch)

### BUG FOUND AND FIXED — bit 15 of the part sample field is a FLAG

Found while investigating what a "blank pattern" looks like, i.e. by accident.

`Part.sample_number` returned the raw u16. In `Chronic-Interactive.esx` every
sample-playing part of a never-used pattern reads exactly **0x8000** — flag set,
index bits zero — which decoded as slot **32,768**. There are only 384 slots.

- 2,856 of 2,856 parts in the 204 unnamed patterns carry it.
- 0 of 728 parts in the 52 named patterns do.
- The other three banks never set it, because all their patterns are untouched
  in the same way `default.esx`'s are.

`sample_number` now masks with `0x3FFF`, and `sample_assigned` exposes the flag.
Whether the bit means precisely "no sample" or something adjacent is not
settled; that it is a flag and not part of the index is.

**Why the suite missed it:** `test_every_sample_number_points_at_an_occupied_slot`
walks only NAMED patterns, which never carry the flag. A corpus test that
covers every pattern now exists. Worth remembering — a filter added to make a
test meaningful also narrowed what it could catch.

### FEATURE — Pattern Clear and Copy ("add a new pattern")

There is no "add a pattern" on this machine: it always has exactly 256, and the
manual's operation is **Pattern Clear** (p.3191). Making a new pattern means
clearing an unused slot or copying an existing one into it, so those are what
the Pattern tab now offers, with empty slots marked `— empty —` in the list so
the free ones are visible.

`Bank.blank_pattern_bytes()` takes the bank's OWN most common pattern chunk
rather than synthesising a blank. That is 204/256 on the busiest corpus bank and
256/256 on an empty one. It also sidesteps a real difference: Chronic's blank
patterns set the no-sample flag on every part while the other three leave those
bytes zero — both machine-written. Copying whichever the bank already uses keeps
a cleared pattern consistent with its neighbours.

Verified: copy a pattern into a free slot, clear it again, and the whole bank is
**byte-identical** to the source.

### FEATURE — sample renaming

`SampleSlot.set_name` had existed since WF1 with no UI at all. The Bank tab's
name column is now editable in place; every other column is explicitly
non-editable. The cell is rewritten with what was actually stored, so the table
can never show a name the file does not have (the field is exactly 8 bytes and
the model pads or truncates).

### FIX — the font warning

`ui/theme.py` carried a CSS font stack (`-apple-system`, `BlinkMacSystemFont`,
`ui-monospace`). Qt's stylesheet parser does not resolve CSS generics, so it
walked every alias looking for names no font database contains and said so:
"Populating font family aliases took 405 ms." The user paid that on every launch
and still got a fallback face.

Candidates are now resolved once against the real `QFontDatabase` and the winner
written into the stylesheet — portable, since the mini and the Linux CI runner
each pick their own first hit, and anything with no hit omits the declaration
entirely rather than emitting `font-family: ;`. Resolves to Helvetica Neue /
Menlo here. Warning gone.

### FIXTURE — the synthetic bank is now mostly blank
Naming all 256 patterns made every chunk unique, so the fixture had no blank
pattern — which a real bank very much does. Only the first four are named now.
Golden hash repinned.

### STILL IMPOSSIBLE — adding patterns to songs

Requested, and it is the one thing here that cannot be built. The manual is
clear that the machine does it ("You can edit a song by inserting or deleting
patterns", p.5904), but **all 64 songs in all four corpus banks are
byte-identical blanks** — zero bytes vary across 256 song blocks. There is no
signal to decode from, and inventing a song format would write bytes no machine
has produced into a region the writer currently preserves verbatim.

**One saved song closes it.** Added to the hardware session as the highest-value
item: build a short song on the ESX-1 with a handful of known patterns in a
known order, Save All, and the diff against a blank song gives the event format
almost immediately — the pattern indices are already known, so they can be
searched for directly.
