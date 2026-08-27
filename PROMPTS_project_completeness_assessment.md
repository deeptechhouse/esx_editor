# Prompt Log — Project Completeness Assessment

Running log of user prompts for this chat session.

---

## Prompt 1 — 2026-08-22

> claude code was working on the project in this directory [/Users/aaandy/_andy_ai_projects_2026/esx_editor]. assess project completeness. currently there is a smart media card with an esx file attached via usb

**Action taken:** Read-only assessment. Enumerated project tree, read planning/TDD docs and all spike code, mounted SmartMedia card at `/Volumes/Untitled` (e4.esx, e5.esx), and ran the Spike A round-trip + validate gates against both real card files. No code changed.

---

## Prompt 2 — 2026-08-22

> set up the git repo local and remote (private); complete this to-do item [batch the 6 hardware-checklist items in one sitting ... Loading e4.esx on the ESX-1 immediately answers the stale-header question]; then kick off workflow 1

## Prompt 3 — 2026-08-22

> if remote github is not possible until later that is ok

**Action taken:**
1. **Git** — `git init -b main` locally (no commits, per standing rule); created private GitHub repo `deeptechhouse/esx_editor` via `gh` (used `gh auth token` to bypass a stale keyring entry) and wired it as `origin`. Added `.gitignore`.
2. **Hardware batch** — built `spike_a/hw_session.py` (OOP batch runner for all 6 checklist items), extracted the baseline from the two card banks, and wrote `research/HW_SESSION_2026-08-22.md`. The physical button-press steps are irreducibly the user's; the runner evaluates each save as it appears.
3. **Workflow 1 (contract freeze)** — attempted via Claude CLI (per user rule) but it hit the **weekly usage limit** (resets 7pm America/Chicago), so executed the contract freeze directly: created `codec/`, `core/`, `audio/`, `workspace/` package skeletons with frozen public signatures, docstrings, invariants, and exceptions (bodies raise `NotImplementedError`). All 20 submodules compile and import; no lint errors. Prompt saved to `deploy/wf1_prompt.md` for a later real-account run if desired.

---

## Prompt 4 — 2026-08-22

> commit. do i actually need to do those steps on the machine? how will this program read what has happened to observe the results?

**Action taken:** Committed the WF1 skeleton locally (needed `git_write` permission for `.git/index.lock` under the sandbox). Explained that the physical button presses are irreducible but the program observes their results by re-reading the resulting `.esx` save (`hw_session.py`), and clarified the read-back model.

---

## Prompt 5 — 2026-08-22

> start WF2

**Action taken:** Implemented the real `codec` + `core` package bodies against the frozen WF1 contracts (Claude CLI still weekly-limited, so implemented directly):
- **core**: `motion` (MotionSlot + MotionDomain with discrete knob-position snapping), `part`, `sample`, `global_params`, `pattern` (full from/to bytes), `bank` (+ `RawRegions`, sample-area header read, capacity guard).
- **codec**: `reader` (All + PSG + auto-detect), `writer` (byte-identical + mandatory write-side safety: temp → re-read verify → atomic replace → `.bak`), `byte_buffer` (big-endian cursors), `operation_table` (313 targets from TSVs), `validator` (coherence findings), `template` (bundled blank bank loader).
- **Gate proven**: `writer(reader(b)) == b` byte-for-byte on all 4 corpus banks; `pytest tests/test_roundtrip.py` → 7 passed; no lint errors. `validate()` flags `e4.esx` (17 offset-past-EOF errors) while it still round-trips — confirming the parse/validate split and the stale-header hardware signal.
- Logged findings/decisions in `research/CODEC_FINDINGS_LOG.md`.

---

## Prompt 6 — 2026-08-22

> commit wf2 & move to WF3  /  proceed with the commit of wf2 and continue on to wf3

**Action taken:**
1. **Committed WF2** as `542c406` ("feat(WF2): implement codec + core bodies; round-trip gate green").
2. **WF3 — the gate barrier** (the plan's only barrier). Hard exit = byte-identical round-trip + ≥98% line coverage on `codec/`.
   - **Integration**: wired `allow_invalid` into `writer.write_file` — it now refuses to write a bank with error-severity validator findings unless overridden (proven on `e4.esx`).
   - **Adversarial suite** (`tests/test_codec_gate.py`): malformed-input rejection (→ `FormatError`), surgical-edit proofs (only intended bytes change + re-reads), write-safety proofs (temp cleanup, `.bak`, `RoundTripError` on verify-mismatch never touches the destination), and every validator finding code via byte-level fixtures.
   - **Result**: `pytest tests/` → **52 passed**; **100% line coverage on `codec/`** (473 stmts, 0 missed) — exceeds the 98% bar. No lint errors.
   - Logged the barrier result in `research/CODEC_FINDINGS_LOG.md`.

---

## Prompt 7 — 2026-08-22

> begin wf4  /  Start multitasking  /  (forked worker died at usage limit; continue in parent)

**Action taken:**
1. Forked worker [WF4 UI foundation] died immediately (Other Models usage limit) after reading workspace stubs; no code written.
2. Continued WF4 on branch `feat/wf4-ui-foundation`:
   - Installed **PySide6 6.9.3** into `~/.venvs/esx` (pinned; last installable on macOS 12).
   - Implemented `workspace/` bodies: budget, limits, naming (TDD §5.3), staging session (PID lockfile + orphan sweep) + StagingBank against audio ports.
   - Created `ui/`: theme tokens + QSS, BudgetMeter/KnobDial/StepGrid/WaveformView, MainWindow shell (6 placeholder tabs), BankSession composition root.
   - `pytest tests/` → **78 passed** (offscreen Qt). No lint errors.
   - Logged in `research/CODEC_FINDINGS_LOG.md`.

---

## Prompt 8 — 2026-08-22

> what are next steps when ready  /  start WF5

**Action taken:** Implemented WF5 (motion editor) on `feat/wf5-motion-editor`:
- `MotionDomain.snap_stored` + `MotionSlot.write_stored` / `empty` (length masking).
- `OperationTable.targets_for_part` picker rules (accent=LEVEL only, hide Pitch, audio-in hides Start/Reverse, FX on non-accent).
- Pure `ui/motion/tools.py` (pencil/line/ramp/lfo/s&h/invert/scale/smooth/random/clear/eraser).
- `MotionCanvas` (three-state, forced-TRIG stairs, length mask), `TargetPicker`, `MotionEditor` (n/24 refuse, overwrite guard, Start Point seconds/step) wired into the Motion tab.
- Byte-verify suite: discrete N=2/3/4 encodings, Disabl=0x80, mask, on-disk 130 B form.
- `pytest tests/` → **96 passed**.

---

## Prompt 9 — 2026-08-23

> implement WF6

**Action taken (incomplete — interrupted):** Created `feat/wf6-views-wizard`. Wrote uncommitted `audio/passthrough.py`, `ui/views/bank_view.py`, `ui/views/staging_view.py`, `ui/views/pattern_view.py`. Did not write song/global views, wizard, MainWindow wiring, or tests. Did not commit.

---

## Prompt 10 — 2026-08-23

> create a handoff document for claude

**Action taken:** Wrote `HANDOFF_claude_wf6.html` (agent-facing status, constraints, remaining WF6 steps) and `deploy/wf6_continue.txt` (exact pytest/venv command).

---

## Prompt 11 — 2026-08-23

> /goal — do not stop working until this [HANDOFF_claude_wf6.html] document's goals are complete. i will check back in 8 hours for any confirmations that are needed, however i would like the program to be already tested, ready for human testing

**Action taken:** Completed WF6 on `feat/wf6-views-wizard` (uncommitted, per the handoff's "do not commit unless asked"):
- Wrote `ui/views/song_view.py`, `ui/views/global_view.py`, `ui/views/__init__.py`; exported the passthrough adapters from `audio/__init__.py`.
- Built `ui/wizard/` — 11 skippable `QWizard` pages (TDD §9) over a shared `WizardContext`.
- Rewired `ui/main_window.py`: five real views replace the placeholders, `bankChanged` binds them all, pattern selection re-binds the motion editor, File → "Guided setup…".
- Added `BankSession.validate()` and `StagingView(bank=...)` (shared staging model).
- Fixed two real bugs: `wave.Error` escaping the UI (app crash on a bad `.wav` drop) and garbage-collected `QMenu` wrappers.
- Tests: `tests/test_views.py`, `tests/test_wizard.py`, `tests/test_shell_wiring.py` → `pytest tests/` **203 passed**; `codec/` 100%, every WF6 module 100%.
- Wrote `WF6_HUMAN_TESTING.html` (manual test script) and `next_steps/`.

**Awaiting confirmation:** whether to commit WF6, and whether to start WF7.

---

## Prompt 12 — 2026-08-23

> commit WF6, start WF7 and continue to the other phases until all work from the TDD is complete, tested, and ready for human testing
> *(reaffirmed: "continue working until all items from all phases of the TDD are complete, tested, and ready for human testing")*

**Action taken:** Committed WF6, then ran WF7–WF12 as separate branches and commits.

- **WF7** `eb94c63` — version pins, pyproject/ruff/black/mypy config, property + golden + integration tests, `tests/synthetic.py` (a coherent bank built in memory so CI can run the round-trip gate without the gitignored corpus), CI pipeline, pre-commit hooks, README/NAVIGATION/CHANGELOG. Property tests found a latent bug: 12 motion option counts would have encoded as the Disabl sentinel.
- **WF8** `bca26c8` — `Bank.commit_sample`, the thing the app existed for and could not do. Required decoding the sample-area header out of a verbatim blob. Three format discoveries: the stereo header layout (**corrects TDD §2.3**), PCM big-endianness confirmed from the audio itself, and the PCM trailer mirroring currentOffset. Found a bug where committing would overwrite a stereo sample's second channel.
- **WF9** `99f07f4` — ffmpeg and librosa adapters, both optional. Found that this ffmpeg has no libsoxr, that the mode-margin alone cannot reject noise, and that Camelot minor keys were a minor third out.
- **WF10** `f8b0c7e` — pattern tempo decoded (1/128 BPM); length/beat/last-step proven **undeterminable** from the corpus.
- **WF11** `ef00410` — part sample numbers (672/672 verified against an independent oracle) and step triggers (LSB-first, settled statistically). Song decoding proven impossible: all 64 songs in all 4 banks are byte-identical blanks.
- **WF12** `2499b38` — dominant-note detection for material with no key (see prompt 13).
- **Docs** `635c921`, `e350e87`.

**Result:** 96 → **375 tests**, `codec/` 100%, project 91%, mypy and lint clean, CI green without corpus banks.

---

## Prompt 13 — 2026-08-23

> regarding this "A 15 ms one-shot has no key anyway — better to return None than analyse noise." a noise still has a note correct? due to each frequency corresponding to a note frequency? for each sound that does not have a "key" i would like it to show what "note" it corresponds to

**Action taken:** Correct for essentially all real material, so it was built as its own `PitchDetector` port (`audio/pitch.py`, commit `2499b38`). Key and note are now separate claims: a kick reports no key but a real note (A1, E1…), a chord reports both, and only genuinely broadband material reports neither. Two measured corrections were needed — skipping the attack (percussion is pitch-swept, so measuring the whole sound reads a semitone sharp) and combining frames with a median rather than a mean (mean error 32.7 → 2.4 cents). 12/12 correct on sines, kicks, toms and a snare. Surfaced in the Staging tab and wizard screens 5 and 7.

---

## Prompt 14 — 2026-08-23

> is the editor reading for testing (eg for me to make an esx file with it and load it to smartmedia card to try it with the electribe)

**Action taken:** Yes, with the safety story stated plainly. Wrote `HUMAN_TESTING.html` and `deploy/make_hw_test_banks.py` — graduated hardware test banks (t0 byte-identical, then one change at a time) so a machine rejection points at a single field rather than the whole editor.

---

## Prompt 15 — 2026-08-23

> open editor

**Action taken:** Launched the app.

---

## Prompt 16 — 2026-08-23

> yes fix the font warning; notes form opening the app: it should be able to add new pattern and add patterns to songs . there is no place to name the pattern / bank etc

**Action taken:** Three things. Font resolved through `QFontDatabase` instead of assuming. Sample renaming had no UI at all — added, editable in place. "Add new pattern" was reframed rather than built: the machine has a fixed 256, so the real operations are Clear and Copy-to, which is what shipped. "Add patterns to songs" was recorded as blocked on hardware evidence (WF13, checklist item 2b).

---

## Prompt 17 — 2026-08-23

> i closed it

**Action taken:** Confirmed the app exit was deliberate, not a crash.

---

## Prompt 18 — 2026-08-23

> also, the smart media card can hold more data (128 mb)

**Action taken:** Correct, and it exposed a misleading label — the meter was measuring the sampler's 27 MB RAM budget, not the card. Relabelled as RAM and added card-capacity awareness (`workspace/card.py`, WF14): a card holds many banks, one bank cannot exceed 27,590,672 B.

---

## Prompt 19 — 2026-08-23

> this file [sawloop_.rtfd] contains data regarding this esx file [Chronic-Interactive.esx] and the sawloop interface for esx editing and debug/file info that may be useful

**Action taken:** Found a serious bug. SawLoop's Data Length did not match the offset span, which exposed that `commit_sample` was writing **no PCM block header** — raw audio where the machine expects magic. Undetectable downstream: such banks round-trip, validate and re-read fine (WF15).

---

## Prompt 20 — 2026-08-23

> /Users/aaandy/_andy_ai_projects_2026/sawloop_song.rtf

**Action taken:** Independently confirmed the song-events negative result ("There are no song events configured for this file!"). Found that only nine of the 528 bytes in a song block are non-zero; implemented `Song.name` and `Song.tempo` read-only (WF16).

---

## Prompt 21 — 2026-08-26

> /Users/aaandy/Downloads/Chronic-Interactive-3.esx here is an esx file with a song saved (i believe)

**Action taken:** The blocker is gone. Diffing against the untouched original changed twenty bytes in 8.5 MB, all in the song area, giving the chain length and the ordered list of pattern indices. Songs are now decoded *and writable*: the verbatim mid region was split so the writer emits songs from objects, and the Song tab became a real chain editor (add / remove / reorder / rename / retempo). Also established that the region the TDD calls "song events" is not song events — a four-position song changed nothing in it (WF17).

---

## Prompt 22 — 2026-08-26

> the sawloop editor can edit which midi cc messages control which items. this is an important feature, as I would like to use various midi controllers with the electribe that do not necessarily map to the default electribe midi mapping

**Action taken:** Both halves of the MIDI map turned out to be in the 192-byte global block, which had been retained entirely verbatim until now. The **drum note numbers** (+10..+22) are VERIFIED — all thirteen match the manual's printed factory table (p.90) exactly — and are editable with note names shown. The **CC assign table** (+23..+55, 33 rows) is located with certainty but its rows are NOT named: every bank carries the identical factory table, so which knob each row drives cannot be derived from the data. Rows are editable by position and deliberately unlabelled, with a `t7_ccprobe` hardware bank that names the whole table in one pass (WF18).

---

## Prompt 23 — 2026-08-26

> assloop is ok, rather than trigger annotatted, i need to change the rule to annotate as the code is made and revided

**Action taken:** Two decisions closed. (1) The `bass_loop` → `ASS_LOOP` tail-truncation rule stands as TDD §5.3 specifies it — settled, not to be re-raised. (2) Rewrote CLAUDE.md §15: annotation now happens **in the source, as code is written and revised, in the same commit** — no `_annotated` duplicate tree, because a duplicate drifts the moment the original is edited and a stale explanation teaches the wrong thing with full confidence. Added §8 step 3b so stale annotation is caught as a defect during code verification. Existing `_annotated` files across the workspace are treated as frozen historical snapshots. Applied the new rule to this codebase: audited all 59 modules (every one already had a module docstring) and annotated the public methods where a real *why* existed, deliberately leaving Qt overrides like `paintEvent` alone per the rule's own "match the surrounding density" clause.

---

## Prompt 24 — 2026-08-26

> what is left to do before human teting?

**Action taken:** Audited rather than recalled, and closed the four real gaps found. (1) `deploy/hw_test_session.txt` was actively misleading — it still named "make a SONG" as the top blocker, which WF17 solved, and listed neither `t6_song` nor `t7_ccprobe`; rewritten, with naming the CC rows now the highest-value item. (2) Screenshots predated WF13/WF14, so the testing document showed a build that no longer existed; added `tools/capture_screens.py` and regenerated all 17. (3) The status-bar memory meter was clipped mid-word — its minimum width was a guessed 180 px; it now measures the widest label it can paint. (4) Verified the documented launch venv (`~/.venvs/esx`) actually runs the new code, and confirmed the remaining Qt font warning is offscreen-only and never appears in the app.

---

## Prompt 25 — 2026-08-26

> this is the midi cc for the esx file that has been analyzed most recently: [SawLoop "Midi CC Assignments" — 33 knob names with values]

**Action taken:** Verified before implementing: all 33 numbers match the stored table position for position, in all four banks. That sequence match *proves the row order*; the names rest on SawLoop's authority, and the source says so. The Global tab now lists every knob by name with an editable CC number, plus `cc_for()` / `set_cc_for()` by name (forgiving about case and spacing) and a warning when one CC drives two knobs — legal, occasionally deliberate, and the likeliest way a remap goes quietly wrong. Hardware checklist item 2c closed without touching the machine; `t7_ccprobe` repurposed to test the *write* direction instead (WF19).

---

## Prompt 26 — 2026-08-27

> what do i need to do before i can use it?

**Action taken:** Verified the environment instead of describing it, which found two things that would have stopped a real session. (1) `deploy/verify_env.py` reported "environment is NOT ready" on a perfectly working install — it still imported the Wave 0 flat spike modules and looked for banks one directory above the project. A verification script that cries wolf stops the one person doing the right thing by checking; fixed, and a missing corpus is now a skip rather than a failure since `*.esx` is gitignored. (2) Saving `e4.esx` — a real bank off the user's own card, incoherent since before the editor existed — refused with "pass allow_invalid=True", a programmer's instruction shown to someone holding a mouse, with no GUI path to act on it. The writer still refuses by default; the shell now explains what is incoherent, states that the editor did not create it and will preserve rather than repair it, and offers Save anyway. Confirmed end to end: edit → save → `.bak` byte-identical to the original → re-read shows the edit, 14 bytes changed, all inside the two regions touched.

---

## Prompt 27 — 2026-08-27

> the midi cc section does not seem as though t=you can add information to it (eg for each electribe knob assign a midi cc note; either via drop down form or by pressing a button and moving a knob or button on a midi device that is connected)

**Action taken:** The numbers *were* editable, but the observation was right about what mattered: 8 of 33 rows visible, hairline steppers, nothing signalling the action. Technically interactive is not the same as offering the action. Rebuilt as a form — tables now take five parts of the height to the hex dump's one, and every row carries a dropdown of all 128 CCs named where the MIDI spec names one. Added MIDI Learn as a new `midi/` package following the same ports/adapters shape as `audio/`: a `MidiInput` Protocol, a mido/python-rtmidi adapter, a null fallback, cached capability probe. Polled from a Qt timer rather than callback-driven, because backend callbacks arrive on another thread and touching Qt from there crashes weeks later; receive-only by construction, since nothing may alter a connected instrument. One row armed at a time, first message wins, 15 s timeout. 17 tests against a fake input — no hardware needed — which caught a real bug where a disabled button explained a state its own view was not in (WF20).
