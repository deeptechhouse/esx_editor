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
