#!/usr/bin/env python3
"""
limits.py — oversize-sample policy for ESX Bank Studio.

WHAT THIS DECIDES
    When a sample is added to the staging bank, three separate questions get
    asked. They are deliberately kept apart because they have different causes
    and different consequences:

      1. Will it FIT?            -> capacity check, can be a hard error
      2. Is it WORTH ANALYSING?  -> musical-validity check, skips key detection
      3. Should we WARN?         -> a dismissible heads-up, "ignore for all"

WHY ANALYSIS IS SKIPPED ON LONG FILES
    Measured on real material (see spike notes): key analysis costs about
    11 ms per second of audio, so even a 485-second recording finishes in ~5.5 s.
    Speed is therefore NOT the reason to skip.

    The real reason is that a global key estimate on a long, multi-section
    recording is musically meaningless. Worse, the naming convention appends
    that key to the filename -- so a bogus estimate does not just waste time,
    it permanently mislabels the file in the user's library. Refusing to guess
    is the correct behaviour.

ADJUSTABLE PARAMETERS
    Everything in the CONFIG block below. All are safe to tune.
"""

import os
import wave
import layout as L

# ===========================================================================
# CONFIG -- adjustable
# ===========================================================================

# Longest sample we will attempt key detection on. Above this we mark the
# sample "not analysed" and append no key to the filename.
# 30 s covers 8 bars at 60 BPM, i.e. any realistic single-key musical phrase.
ANALYSIS_MAX_SECONDS = 30.0

# A sample costing more than this fraction of total bank memory gets a warning.
# 0.10 of 25,165,824 B is ~2.5 MB, about 28 s of CD-quality mono.
WARN_BANK_FRACTION = 0.10

# The largest share of sample memory ONE sample may occupy. Long samples are a
# legitimate technique -- assign a long recording to a part and motion-sequence
# its Start Point to scrub slowly through it -- so this is deliberately generous.
# The remaining 20% stays free for other samples and headroom.
MAX_SINGLE_SAMPLE_FRACTION = 0.80

# Independent of bank fraction, warn on any source file larger than this.
# Purely a "did you mean to add this?" guard against dropping in whole mixes.
WARN_SOURCE_BYTES = 20 * 1024 * 1024        # 20 MB

# Offer "analyse only the first N seconds" for long files. Never applied
# automatically -- silently analysing a fragment and presenting it as the
# file's key would be the same mislabelling problem in a subtler form.
PARTIAL_ANALYSIS_SECONDS = 30.0

CAPACITY = L.MAX_SAMPLE_BYTES                # 25,165,824
MAX_SECONDS_AT_CD = CAPACITY / (44100 * 2)   # ~285.3 s


# ===========================================================================
# Severity levels
# ===========================================================================
OK = "ok"              # nothing to say
NOTICE = "notice"      # informational, no dialog
WARN = "warn"          # dismissible, supports "ignore for all"
BLOCK = "block"        # cannot proceed -- physically will not fit


class Finding:
    """One thing worth telling the user about a sample."""

    __slots__ = ("level", "code", "message", "dismissible")

    def __init__(self, level, code, message, dismissible=True):
        self.level = level
        self.code = code
        self.message = message
        # BLOCK findings are never dismissible: the audio genuinely cannot fit.
        self.dismissible = dismissible and level != BLOCK

    def __repr__(self):
        return f"<{self.level}:{self.code}>"


def check_sample(path, duration_s, channels, target_rate, used_bytes=0):
    """Evaluate one candidate sample. Returns (findings, analyse_ok).

    `used_bytes` is how much of the bank is already spoken for, so the fit
    check reflects the real remaining space rather than an empty bank.
    """
    findings = []

    frames = int(round(duration_s * target_rate))
    cost = ((frames * 2 * channels) + 2 + 3) // 4 * 4      # align_up(bytes+2, 4)
    free = CAPACITY - used_bytes

    # --- 1. capacity -------------------------------------------------------
    single_cap = int(CAPACITY * MAX_SINGLE_SAMPLE_FRACTION)
    if cost > single_cap:
        # Say concretely what WOULD work rather than "make it smaller".
        fixes = []
        if channels > 1 and (frames * 2) <= single_cap:
            fixes.append("fold to mono")
        for label, r in (("Broadcast", 32000), ("Radio", 22050),
                         ("Lo-fi", 16000), ("Telephone", 11025)):
            if int(round(duration_s * r)) * 2 <= single_cap:
                fixes.append(f"drop to {label} ({r} Hz) mono")
                break
        fixes.append(f"trim to {single_cap/(44100*2):.0f}s at CD mono")
        findings.append(Finding(
            BLOCK, "exceeds_single_cap",
            f"{duration_s:.1f}s at {target_rate} Hz needs {cost:,} B. One sample "
            f"may use at most {MAX_SINGLE_SAMPLE_FRACTION:.0%} of sample memory "
            f"({single_cap:,} B), leaving {1-MAX_SINGLE_SAMPLE_FRACTION:.0%} free. "
            f"Options: " + "; ".join(fixes) + ".",
            dismissible=False))
    elif cost > CAPACITY * WARN_BANK_FRACTION and cost > single_cap * 0.5:
        # Large but allowed -- explain the trade-off rather than just flagging size.
        steps = duration_s / 128.0
        findings.append(Finding(
            WARN, "dominant_sample",
            f"uses {cost:,} B — {100*cost/CAPACITY:.0f}% of the bank, leaving "
            f"{CAPACITY-cost:,} B ({(CAPACITY-cost)/(44100*2):.0f}s at CD mono) for "
            f"everything else. Motion-sequencing Start Point across its 128 "
            f"positions moves ~{steps:.2f}s per step."))
    elif cost > free:
        findings.append(Finding(
            BLOCK, "exceeds_free",
            f"needs {cost:,} B but only {free:,} B remain in this bank.",
            dismissible=False))
    elif cost > CAPACITY * WARN_BANK_FRACTION:
        pct = 100 * cost / CAPACITY
        findings.append(Finding(
            WARN, "large_sample",
            f"uses {cost:,} B — {pct:.0f}% of the whole bank."))

    # --- 2. source file size ----------------------------------------------
    try:
        src = os.path.getsize(path)
        if src > WARN_SOURCE_BYTES:
            findings.append(Finding(
                WARN, "large_source",
                f"source file is {src/1048576:.1f} MB."))
    except OSError:
        pass

    # --- 3. analysis viability --------------------------------------------
    analyse_ok = duration_s <= ANALYSIS_MAX_SECONDS
    if not analyse_ok:
        findings.append(Finding(
            NOTICE, "analysis_skipped",
            f"{duration_s:.1f}s exceeds the {ANALYSIS_MAX_SECONDS:.0f}s analysis "
            f"limit — key detection skipped, no key appended. A single key for a "
            f"recording this long would not be meaningful. You can analyse the "
            f"first {PARTIAL_ANALYSIS_SECONDS:.0f}s explicitly if you want one."))

    if not findings:
        findings.append(Finding(OK, "ok", "fine"))
    return findings, analyse_ok


# Codes that all mean "this sample is big". Grouped so the UI can offer a single
# "ignore all size warnings" action rather than muting each variant separately.
SIZE_WARNING_CODES = frozenset({"large_sample", "large_source", "dominant_sample"})


class WarningPolicy:
    """Tracks which warning codes the user has chosen to stop seeing.

    "Ignore for all" suppresses a CODE, not an individual sample -- so
    dismissing "large_sample" once silences it for every oversized sample added
    afterwards, which is what was asked for. BLOCK findings are never
    suppressible; ignoring them would produce a bank that cannot be written.
    """

    def __init__(self):
        self._muted = set()

    def mute(self, code):
        self._muted.add(code)

    def mute_size_warnings(self):
        """One click: stop warning about large samples entirely."""
        self._muted.update(SIZE_WARNING_CODES)

    def unmute(self, code):
        self._muted.discard(code)

    @property
    def muted(self):
        return sorted(self._muted)

    def visible(self, findings):
        return [f for f in findings
                if f.level != OK
                and not (f.dismissible and f.code in self._muted)]


# ===========================================================================
# Demo
# ===========================================================================
def _probe(path):
    try:
        with wave.open(path, "rb") as w:
            return w.getnframes() / w.getframerate(), w.getnchannels()
    except Exception:
        return None


if __name__ == "__main__":
    import sys
    d = sys.argv[1] if len(sys.argv) > 1 else "/Users/aaandy/Documents/TEST_SAMPLES"
    files = sorted(f for f in os.listdir(d) if f.lower().endswith(".wav"))
    policy = WarningPolicy()

    counts = {BLOCK: 0, WARN: 0, NOTICE: 0, OK: 0}
    skipped = 0
    shown = 0
    print(f"Adding {len(files)} file(s) at CD mono, warning policy active\n")
    for f in files:
        info = _probe(os.path.join(d, f))
        if not info:
            continue
        dur, ch = info
        findings, analyse = check_sample(os.path.join(d, f), dur, 1, 44100)
        if not analyse:
            skipped += 1
        for fd in findings:
            counts[fd.level] = counts.get(fd.level, 0) + 1
        vis = policy.visible(findings)
        if vis and shown < 6:
            print(f"  {f[:48]:<50} ({dur:.1f}s)")
            for fd in vis:
                print(f"     [{fd.level.upper():6}] {fd.message[:100]}")
            shown += 1
            # After showing a couple, simulate the user clicking "ignore for all"
            if shown == 3:
                policy.mute_size_warnings()
                print("\n  >>> user clicks 'ignore for all large-sample warnings'\n")

    print(f"\nSummary over {len(files)} files:")
    print(f"  BLOCK  (cannot fit, not dismissible): {counts[BLOCK]}")
    print(f"  WARN   (dismissible)                : {counts[WARN]}")
    print(f"  NOTICE (analysis skipped)           : {counts[NOTICE]}")
    print(f"  key analysis skipped on {skipped} file(s) "
          f"(> {ANALYSIS_MAX_SECONDS:.0f}s)")
    print(f"  currently muted codes: {policy.muted}")
