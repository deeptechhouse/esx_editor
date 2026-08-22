#!/usr/bin/env python3
"""
budget.py — the sample-memory "scoreboard" for ESX Bank Studio.

WHAT THIS DOES
    Answers "will this fit on the card, and what if I drop these three samples
    to 22 kHz?" WITHOUT converting anything. Reading a file's duration costs
    microseconds (header only, no audio decoded); the memory cost of any rate is
    then pure arithmetic.

WHY IT IS EXACT, NOT AN ESTIMATE
    The .esx stores uncompressed 16-bit PCM, so:

        frames = round(duration_seconds * target_rate)
        bytes  = frames * 2
        cost   = align_up(bytes + 2, 4)      <-- see ALLOCATION RULE below

    There is no codec, no variable bitrate, and no compression. The only
    uncertainty is +/- 1 frame from resampler rounding, i.e. +/- 2 bytes on a
    25 MB budget. Re-encoding to find out would be pointless.

ALLOCATION RULE (derived from real banks, Spike A)
    Measured across 200 factory samples and 79 user samples:
      - every sample's byte length is EVEN            (16-bit frames)
      - every sample's start offset is 4-BYTE ALIGNED (200/200 and 79/79)
      - the gap to the next sample is always exactly 2 or 4 bytes
    Both facts are explained by a single rule:
        next_start = align_up(previous_end + 2, 4)
    so each sample really occupies align_up(bytes + 2, 4). The overhead is 2-4
    bytes per sample -- negligible in total, but included here so the scoreboard
    never quietly under-reports.

USAGE
    python3 budget.py FILE.wav [FILE.wav ...]        # scoreboard at CD default
    python3 budget.py --tier 22050 FILE.wav ...      # all samples at one tier
    python3 budget.py --fit DIR                      # what-if ladder for a folder

ADJUSTABLE PARAMETERS
    TIERS      the quality ladder offered in the UI
    DEFAULT_RATE  what a freshly added sample gets
"""

import sys
import os
import wave
import audioop  # noqa: F401  (import kept for future dither/convert work)
import subprocess
import json
import math
import layout as L

# --- Adjustable: the quality ladder -----------------------------------------
TIERS = [
    ("CD",        44100),
    ("Broadcast", 32000),
    ("Radio",     22050),
    ("Lo-fi",     16000),
    ("Telephone", 11025),
]
DEFAULT_RATE = 44100

CAPACITY = L.MAX_SAMPLE_BYTES          # 25,165,824 bytes
SLOTS_MONO = L.NUM_SAMPLES_MONO        # 256
SLOTS_STEREO = L.NUM_SAMPLES_STEREO    # 128


# ===========================================================================
# Cost model
# ===========================================================================
def align_up(n, boundary):
    return ((n + boundary - 1) // boundary) * boundary


def cost_bytes(duration_s, rate, channels=1):
    """Exact bytes a sample of this duration occupies at this rate.

    Stereo samples store two channels, so they cost twice as much AND consume a
    stereo slot rather than a mono one.
    """
    frames = int(round(duration_s * rate))
    raw = frames * 2 * channels
    return align_up(raw + 2, 4)


def seconds_available(rate, channels=1):
    """How many seconds of audio fit in an empty bank at this rate."""
    return CAPACITY / (rate * 2 * channels)


# ===========================================================================
# Duration probing -- metadata only, never decodes audio
# ===========================================================================
def probe_duration(path):
    """Return (duration_seconds, source_rate, channels) or None.

    Tries the stdlib WAV reader first (instant, no subprocess). Falls back to
    ffprobe for AIFF/MP3/anything else. Neither decodes the audio payload.
    """
    try:
        with wave.open(path, "rb") as w:
            fr = w.getframerate()
            return (w.getnframes() / fr, fr, w.getnchannels())
    except Exception:
        pass
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_streams", "-select_streams", "a:0", path],
            capture_output=True, text=True, timeout=15)
        st = json.loads(out.stdout)["streams"][0]
        return (float(st["duration"]), int(st["sample_rate"]), int(st["channels"]))
    except Exception:
        return None


# ===========================================================================
# Scoreboard
# ===========================================================================
def _bar(frac, width=34):
    frac = max(0.0, min(1.5, frac))
    filled = int(min(frac, 1.0) * width)
    over = frac > 1.0
    return ("[" + "#" * filled + "." * (width - filled) + "]" +
            ("  OVER BUDGET" if over else ""))


def scoreboard(items, rate_for=None):
    """items: list of (name, duration_s, source_rate, channels)."""
    rate_for = rate_for or (lambda name: DEFAULT_RATE)
    total = 0
    mono = stereo = 0
    rows = []
    for name, dur, srate, ch in items:
        r = rate_for(name)
        c = cost_bytes(dur, r, ch)
        total += c
        if ch >= 2:
            stereo += 1
        else:
            mono += 1
        rows.append((name, dur, srate, ch, r, c))

    print(f"{'sample':<40}{'dur':>7}{'src':>8}{'ch':>3}{'tier':>8}{'bytes':>12}")
    for name, dur, srate, ch, r, c in rows[:14]:
        print(f"  {os.path.basename(name)[:36]:<38}{dur:>7.2f}{srate:>8}{ch:>3}"
              f"{r:>8}{c:>12,}")
    if len(rows) > 14:
        print(f"  ... and {len(rows)-14} more")

    print(f"\n  MEMORY   {total:>12,} / {CAPACITY:,} bytes   "
          f"({100*total/CAPACITY:5.1f}%)")
    print(f"           {_bar(total/CAPACITY)}")
    free = CAPACITY - total
    print(f"  FREE     {free:>12,} bytes = {free/(44100*2):6.1f} s more at CD, "
          f"{free/(22050*2):6.1f} s at Radio")
    print(f"  SLOTS    mono {mono}/{SLOTS_MONO}   stereo {stereo}/{SLOTS_STEREO}")
    if total > CAPACITY:
        print(f"\n  ! OVER by {total-CAPACITY:,} bytes "
              f"({(total-CAPACITY)/(44100*2):.1f} s of CD-quality audio)")
    return total


def what_if(items):
    """Show the decision space: rate ladder CROSSED WITH mono/stereo.

    Channel count matters as much as rate and is usually the better first move:
    stereo costs exactly 2x the bytes AND consumes one of only 128 stereo slots
    instead of one of 256 mono slots. Folding to mono is the same 2x saving as
    halving the rate, but for most drum and bass material it is far less audible.
    """
    print(f"\n{'tier':<12}{'rate':>8}{'as-is':>16}{'forced mono':>16}"
          f"{'fits mono?':>12}")
    for label, rate in TIERS:
        asis = sum(cost_bytes(d, rate, ch) for _, d, _, ch in items)
        mono = sum(cost_bytes(d, rate, 1) for _, d, _, _ in items)
        print(f"{label:<12}{rate:>8}{asis:>16,}{mono:>16,}"
              f"{('yes' if mono <= CAPACITY else 'NO'):>12}")

    # Duration is the third and often largest lever -- show where the bytes are.
    ranked = sorted(items, key=lambda it: -cost_bytes(it[1], 44100, it[3]))
    top = ranked[:5]
    tot_all = sum(cost_bytes(d, 44100, ch) for _, d, _, ch in items)
    print(f"\n  biggest consumers at CD (trimming length beats any tier change):")
    for name, dur, _, ch in top:
        c = cost_bytes(dur, 44100, ch)
        print(f"    {c:>12,} B  {dur:>7.1f}s {'st' if ch>=2 else 'mo'}  "
              f"{os.path.basename(name)[:40]}")
    print(f"    top 5 = {sum(cost_bytes(d,44100,ch) for _,d,_,ch in top)/tot_all*100:.0f}%"
          f" of the total")

    n_st = sum(1 for _, _, _, ch in items if ch >= 2)
    if n_st:
        asis = sum(cost_bytes(d, 44100, ch) for _, d, _, ch in items)
        mono = sum(cost_bytes(d, 44100, 1) for _, d, _, _ in items)
        print(f"\n  {n_st} stereo source(s). Folding all to mono at CD quality "
              f"frees {asis-mono:,} B")
        print(f"  -- the same saving as dropping every sample to Radio (22.05k), "
              f"usually far less audible.")

    print(f"\n{'per-sample savings, CD -> tier (largest first)':<52}")
    base = {n: cost_bytes(d, 44100, ch) for n, d, _, ch in items}
    for label, rate in TIERS[1:]:
        deltas = sorted(((base[n] - cost_bytes(d, rate, ch), n)
                         for n, d, _, ch in items), reverse=True)
        top = deltas[0]
        tot = sum(x for x, _ in deltas)
        print(f"  -> {label:<10} frees {tot:>12,} B total; "
              f"biggest single win {top[0]:,} B ({os.path.basename(top[1])[:28]})")


def main(argv):
    args = argv[1:]
    tier = None
    if args and args[0] == "--tier":
        tier = int(args[1]); args = args[2:]
    if args and args[0] == "--fit":
        d = args[1]
        args = [os.path.join(d, f) for f in sorted(os.listdir(d))
                if f.lower().endswith((".wav", ".aif", ".aiff", ".mp3"))]
    if not args:
        print(__doc__); return 2

    items = []
    skipped = 0
    for p in args:
        info = probe_duration(p)
        if not info:
            skipped += 1
            continue
        items.append((p, info[0], info[1], info[2]))
    if skipped:
        print(f"(skipped {skipped} unreadable file(s))\n")
    if not items:
        print("no readable audio files"); return 1

    scoreboard(items, (lambda n: tier) if tier else None)
    what_if(items)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
