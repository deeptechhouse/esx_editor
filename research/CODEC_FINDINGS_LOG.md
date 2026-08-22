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
