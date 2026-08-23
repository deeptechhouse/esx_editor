# ESX Bank Studio — Navigation Map

> Offline desktop editor for Korg Electribe SX (`.esx`) banks: read, edit, and
> write a bank without ever corrupting it.

## Architecture Overview

Ports-and-adapters around a pure domain model. `core/` is plain Python with no
I/O; `codec/` turns bytes into `core` objects and back; `audio/` defines
interfaces (`Protocol`s) that concrete backends implement; `ui/` renders and
emits intent. The two rules that shape everything: **undecoded regions are
carried verbatim** so a round-trip is byte-identical, and **no layer above
`codec/` ever touches bytes** — widgets do not import `codec/`, only the
composition root (`ui/session.BankSession`) does.

## Directory Map

| Directory | Layer/Role | Description |
|---|---|---|
| `core/` | Domain | `Bank`, `Pattern`, `Part`, `SampleSlot`, `MotionSlot`, `GlobalParameters`, `Song`. No I/O, no Qt. Fields are private; invariants enforced in methods. |
| `codec/` | Serialization | `reader` / `writer` (byte-identical round-trip), `validator` (coherence, reports never repairs), `template` (the blank bank), `layout` (**the single source of truth for every offset**), `operation_table` (313 motion targets), `byte_buffer`. stdlib only. |
| `audio/` | Ports + adapters | `ports.py` freezes `AudioConverter` / `KeyDetector` / `PitchDetector` / `FxRenderer` as Protocols. Adapters: `ffmpeg_adapter` (any format), `librosa_adapter` (key), `pitch` (dominant note), `passthrough` (WAV fallback), `pcm` (endianness + channel handling). `factory.py` probes the machine and picks. |
| `workspace/` | Application services | `budget` (the verified cost model), `limits` (fit/analyse/warn policy), `naming` (8-byte slot names + Camelot), `staging` (session dir, lockfile, orphan sweep). |
| `ui/` | Presentation | `session.py` is the composition root. `main_window.py` is the shell. |
| `ui/views/` | Presentation | One widget per region: bank, staging, pattern, song, global. Each binds via `bind_bank(bank)`. |
| `ui/motion/` | Presentation | Drawable motion canvas, pure tools, target picker. |
| `ui/wizard/` | Presentation | 11 skippable guided-setup pages over a shared `WizardContext`. |
| `ui/widgets/` | Presentation | Reusable: `BudgetMeter`, `KnobDial`, `StepGrid`, `WaveformView`. |
| `tests/` | Testing | Unit, property (hypothesis), golden (pinned hashes), integration, UI (offscreen Qt). |
| `research/` | Reference | Verified byte encodings, the 313-target table, the findings log, the hardware checklist. **Read `CODEC_FINDINGS_LOG.md` before touching the codec.** |
| `spike_a/` | Research tooling | The original format spike: probe, fixture generator, hardware session runner. Not part of the app. |
| `deploy/` | Ops | Environment verification, run commands, local requirements. |

## Key Entry Points

- **Application start:** `ui/app.py` → `main()`; run with `python -m ui.app`
- **Shell / menus:** `ui/main_window.py` → `MainWindow`
- **Open/save/validate:** `ui/session.py` → `BankSession` (the only UI object that imports `codec/`)
- **Read a bank:** `codec/reader.py` → `BankReader.read_auto(bytes)`
- **Write a bank safely:** `codec/writer.py` → `BankWriter.write_file(...)`
- **Every offset and size:** `codec/layout.py` — never duplicate a constant from here
- **Test fixtures without a real bank:** `tests/synthetic.py` → `build()`
- **Commit a sample into a bank:** `core/bank.py` → `Bank.commit_sample()`
- **Which backends are live:** `audio/factory.py` → `detect_capabilities()`

## Module Relationships

- `ui/` → `core/` and `workspace/`. **`ui/views/`, `ui/motion/`, `ui/widgets/`, and `ui/wizard/` never import `codec/`** except `codec.layout` constants; `ui/session.py` is the one place `reader`/`writer`/`template`/`validator` are constructed.
- `codec/` → `core/`. The reader builds `core` objects; the writer serializes them. `core/` never imports `codec/` except `codec.layout`.
- `workspace/` → `audio.ports` (Protocols only), never a concrete backend.
- `audio/passthrough.py` implements the ports; swapping in ffmpeg/librosa touches no caller.
- `core.RawRegions` has **no setter** — the "never modify unknown bytes" invariant is structural, not a convention.

## Invariants That Must Never Regress

1. `BankWriter().write(BankReader().read_auto(b)) == b` on every corpus bank and on `tests/synthetic.build()`.
2. Writes go temp file → re-read verify → atomic replace → `.bak`; an incoherent bank is refused unless `allow_invalid=True`.
3. Motion discrete values are `i * ceil(128/N)`; `0x80` is Disabl, a third state, never a value.
4. Total committed PCM ≤ 25,165,824 B.
5. Undecoded fields raise `NotImplementedError` rather than return a guess; the UI shows bytes instead.
6. PCM is 16-bit signed **big-endian**. A wrong byte order still round-trips and still validates — it just plays static, so `tests/test_pcm.py` measures it rather than trusting the spec.
7. Committing never relocates an existing sample. `_highest_end()` must count a stereo slot's SECOND channel, or a commit overwrites it.

## What Is Decoded, And What Is Not

| Region | State | Why |
|---|---|---|
| Sample headers (mono + stereo), rate, tune | **Decoded** | Stereo layout verified against 40 real slots; corrects TDD §2.3 |
| Pattern tempo | **Decoded** | 19/20 distinct values are exact integer BPMs; default exactly 120.0 |
| Part sample number | **Decoded** | 728/728 point at an occupied slot; 672/672 match the slot's own name |
| Step triggers (drum, stretch/slice) | **Decoded** | Halves identical on 468/468; LSB-first concentrates hits on the beat 1.85× |
| Motion slots | **Decoded** | Byte-verified in WF5 |
| Pattern length / beat / last step | Raises | Those header bytes are CONSTANT across all 52 named corpus patterns |
| Songs | Raises | All 64 songs in all 4 banks are byte-identical blanks |
| Global fields (MIDI channel) | Raises | Block is effectively constant across the corpus |
| Keyboard / audio-in / accent step data | Raises | Keyboard bits show no grid concentration; not a trigger bitmap |
| FX index → effect name | Not mapped | The manual names 16 types but gives no indices, and its two orderings disagree |

Each "raises" row needs one hardware diff, not more analysis. See `research/HARDWARE_CHECKLIST.md`.

## External Dependencies

| Dependency | Purpose | Swappable? |
|---|---|---|
| PySide6 6.9.3 (pinned) | Qt UI | No (UI framework); pinned because 6.10+ cannot install on macOS 12 |
| ffmpeg (external binary) | Decode/resample any input format | Yes — behind `AudioConverter` |
| librosa + soundfile | Key detection | Yes — behind `KeyDetector` |
| hypothesis / pytest | Testing | Yes |

`codec/` and `core/` have **no third-party dependencies at all** — the layers that can destroy a bank have zero external surface.

## Where To Look First

| If you are… | Read |
|---|---|
| Changing the codec | `research/CODEC_FINDINGS_LOG.md`, then `codec/layout.py` |
| Changing motion | `research/motion_byte_encodings.md` |
| Adding a view | `ui/views/song_view.py` (the honest-reporting pattern) |
| Wondering why a field raises | `research/HARDWARE_CHECKLIST.md` — it is probably hardware-gated |
| Testing without a bank | `tests/synthetic.py` |
