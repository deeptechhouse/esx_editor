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
