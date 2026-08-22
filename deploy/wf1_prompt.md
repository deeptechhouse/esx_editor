You are executing **Workflow 1 (WF1) — Contract Freeze** for the "ESX Bank Studio"
project. Work ONLY in this repository (the current working directory).

## Read first (they are the authority; obey them over these instructions if they conflict)
- `TDD_esx_bank_studio.html` — the full technical design (sections 02–11 define the format, domain model, codec, audio ports, budget/limits, staging).
- `PLAN_multiagent_implementation.html` — WF1 is defined in section 04 ("WF1 — Contract freeze").
- `spike_a/layout.py` — the PROVEN single source of truth for every byte offset. Do NOT re-derive offsets; port/reuse these exact values.
- `spike_a/esx_probe.py`, `budget.py`, `limits.py` — proven spike logic to fold into the real package contracts.
- `research/motion_operation_table_313.tsv`, `research/motion_target_domains.tsv`, `research/motion_byte_encodings.md` — motion targets and value domains.

## Your one deliverable
Create the **public API skeleton** for the non-UI packages, with EVERY public
signature, type hint, docstring, invariant, and exception declared — but with
method/function BODIES raising `NotImplementedError` (or, for pure data classes,
minimal `__init__` storing validated fields). This is a CONTRACT, not an
implementation. No behaviour beyond what is needed to make signatures importable.

### Packages to create (exact module layout from TDD §04.6, §03, §05, §10)
```
codec/
  __init__.py
  layout.py          # port spike_a/layout.py verbatim (it is proven)
  byte_buffer.py     # big-endian cursor over bytes
  reader.py          # bytes  -> core.Bank   (must handle BOTH All and PSG saves)
  writer.py          # core.Bank -> bytes    (verbatim replay of undecoded regions)
  validator.py       # coherence checks, independent of parsing
  operation_table.py # 313 motion targets + value domains (load from research/ TSVs)
  template.py        # embedded blank-bank template; "New" loads this
core/
  __init__.py
  bank.py            # Bank, RawRegions
  global_params.py   # GlobalParameters
  pattern.py         # Pattern, PatternHeader, FxUnit
  part.py            # Part (Drum/Keyboard/StretchSlice/AudioIn/Accent), SequenceData
  motion.py          # MotionSlot, MotionDomain (encode/decode, snapping)
  song.py            # Song, SongEvent
  sample.py          # SampleSlot (mono/stereo), sample-tune encode/decode
audio/
  __init__.py
  ports.py           # AudioConverter, KeyDetector, FxRenderer protocols + KeyResult
workspace/
  __init__.py
  budget.py          # quality-budget scoreboard contract (from spike_a/budget.py)
  limits.py          # oversize-sample policy contract (from spike_a/limits.py)
  staging.py         # staging bank + temp/session lifecycle (TDD §07)
```

## Hard requirements
1. **Contract only.** Function/method bodies raise `NotImplementedError` with a
   short message. Data classes may store validated fields in `__init__`.
2. **Encapsulation (project standard).** Private fields (`_name`); expose via
   `@property`; collections returned as defensive copies / immutable views; no
   public mutable state. Follow the `MotionSlot` example in TDD §3.3 exactly.
3. **Invariants documented AND declared as raised exceptions** in docstrings
   (e.g. Pattern always holds exactly 24 MotionSlots; MotionSlot always 128
   values; sample names exactly 8 bytes; total PCM ≤ 25,165,824 B; unknown
   regions never modified). See TDD §3.2.
4. **Codec contract:** `writer(reader(b)) == b` for every valid bank. `validate()`
   is a SEPARATE layer from `read()` (TDD §4.4). Write-side safety steps from
   §4.5 documented in the writer's docstrings. Reader must expose a path for the
   PSG (short, no-sample-area) save variant.
5. **Motion domains:** `MotionDomain.encode/decode` per TDD §8.3 — discrete
   targets store knob positions `value = i * ceil(128 / N)`; continuous store
   0–127; `Disabl = 0x80`. Include the forced-TRIG playback-mode rule (§8.4).
6. **Ports & adapters:** `audio/ports.py` uses `typing.Protocol`; `KeyDetector.detect`
   returns `KeyResult | None` (None is a legitimate outcome). No concrete adapters.
7. **No UI in WF1.** Do not create `ui/`. Target Python 3.10+ type-hint syntax.
8. Add a top-of-file module docstring to each file explaining its role, in the
   same clear teaching style as the existing spike files.
9. Do NOT run git commit or push. Do NOT modify files under `spike_a/`,
   `research/`, `deploy/`, or the HTML docs. Only create the new packages.
10. Keep everything importable: `python3 -c "import codec, core, audio, workspace"`
    must succeed with no error from the current directory.

## When done
Print a concise summary: the files created, the key public classes/functions per
module, and any place where the TDD was ambiguous and you made a documented
choice. Then STOP — implementation of the bodies is a later workflow.
