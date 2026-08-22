# Motion sequence byte encodings — VERIFIED against real banks

Derived by analysing 297 populated motion slots in `ESX-Factory-Data.esx`
(20,721,848 B, 194 samples, 106 patterns with motion) plus `a3jan26.esx`.
Spike A, 2026-08-09.

Status key: **PROVEN** = observed directly and unambiguously in real data.
**OPEN** = not yet determined.

---

## 1. Slot framing — PROVEN

```
struct MotionSlot {          // 130 bytes, 24 per pattern, at pattern offset 1160
    uint16_be target;        // 0xFFFF = slot unused
    uint8     value[128];    // one per step
}
```

An **unused slot** is `target == 0xFFFF` with all 128 values set to `0x80`.
Observed across all 6144 slots of a bank containing no motion data.

## 2. The `Disabl` sentinel = `128` (0x80) — PROVEN

The manual documents a per-step `Disabl` meaning "do not update the parameter at
this step". It is encoded as **128**, which sits outside the 0–127 knob range.

Proof — pattern 3, slot 0, target 102 (Drum4 Filter Cutoff):

```
steps  0..5    128 128 128 128 128 128          <- disabled (no motion yet)
steps  6..63    35  31  33 ... 117 126 127 127  <- a real filter sweep
steps 64..127  128 128 128 ... 128 128 128      <- disabled (pattern is 64 steps)
```

The trailing block starts exactly at step 64, which is the pattern's length.
This simultaneously confirms that **unused steps beyond the pattern length are
stored as `Disabl`**, so the editor must not render them as data.

## 3. Discrete parameters are stored as knob positions, NOT ordinals — PROVEN

A discrete parameter divides the 0–127 knob range into N zones. The stored byte
is the zone's base value, not the option index.

| Parameter kind | N | Observed byte values | Rule |
|---|---|---|---|
| Roll, Effect Send, Amp EG, **Reverse** | 2 | `{0, 64}` | `i × 64` |
| Effect Select (Fx1/Fx2/Fx3) | 3 | `{0, 43, 86}` | `i × 43` |
| Filter Type (LPF/HPF/BPF/BPF+) | 4 | `{0, 32, 64, 96}` | `i × 32` |

General rule that fits all three: **`value = i × ceil(128 / N)`**,
and to decode: **`i = value // ceil(128 / N)`**.

Observed option counts match the manual's enum lists exactly (3 for Effect
Select, 4 for Filter Type), which independently validates those lists.

### This settles the manual erratum
`REVERSE` shows exactly two distinct values `{0, 64}` — it is **boolean**,
confirming the parameter reference (p.53 "On, Off") and confirming that the
p.71 motion table's "Disabl, 0...127" for Reverse is a **typo**.
`FX SEND` likewise shows `{0, 64}` — boolean, as printed.

## 4. Continuous parameters — PROVEN

Stored directly as 0–127. Observed ranges (excluding the 128 sentinel):

| Target | Observed min..max |
|---|---|
| Filter Cutoff | 0..127 |
| Filter EG Int | 3..127 |
| Level | 0..127 |
| Pan | 0..127 |
| EG Time | 0..127 |
| Start Point | 0..125 |
| FX Edit1 / Edit2 | 0..127 |

(Minimums above 0 and maximums below 127 reflect what the factory patterns
happened to use, not the legal range.)

## 5. Pitch does NOT follow the 0–127 rule — **OPEN**

`Pitch` targets (Drum, Stretch, Slice) store values well outside 0–127:

```
values < 128 : 103 distinct, range 0..115
values > 128 : 40  distinct, range 167..222
values 116..166 : NONE (other than 128 = Disabl)
```

The most common single value is **64** (663 occurrences), which behaves like a
held/centre value. The manual gives `PITCH = -63...+63` with a ±2 octave range,
but that does not map obviously onto the observed byte distribution.

Reading the byte as signed two's complement gives `+0..+115` and `-89..-34`,
which is asymmetric and leaves an unexplained gap. **The observed bands may
simply be the values these particular factory patterns used, not the full legal
range** — usage is not the same as domain.

**To close:** on the hardware, record a Pitch motion sequence sweeping the knob
from minimum to maximum, save, and read the byte array. That yields the exact
mapping in one experiment.

## 6. Consequences for the editor

- The canvas must treat `128` as a **third state** (no update), drawn as a gap.
  It is not a value and must never be interpolated through.
- Steps beyond the pattern's length are `Disabl` and must be masked, not drawn.
- Discrete targets snap to `i × ceil(128/N)`, never to `0,1,2,3`.
- `Pitch` needs its own value mapping once resolved; until then the editor should
  treat it as raw 0–255 and refuse to "helpfully" clamp it to 0–127.
