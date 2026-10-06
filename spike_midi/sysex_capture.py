#!/usr/bin/env python3
"""
sysex_capture.py — capture ESX-1 SysEx dumps over MIDI. RECEIVE ONLY.

WHY THIS MATTERS
    The remaining open questions in the TDD (the Pitch value mapping, the
    stereo sample header, the displayable character set) all need the same
    experiment: change ONE thing on the hardware, capture the state, and diff.

    Doing that via SmartMedia means a save-to-card cycle each time. Over MIDI
    the loop is seconds instead of minutes, which is the difference between
    resolving these questions and not bothering.

    The owner's manual does not document the dump format -- it says to contact
    a Korg distributor -- so the format has to be recovered from real captures.
    That is exactly what this tool collects.

SAFETY -- READ THIS
    This script NEVER transmits. It only opens a MIDI INPUT and listens.
    Nothing it does can alter the state of the Electribe. You trigger the dump
    from the front panel; the tool just records what arrives.

    (A dump can also be requested by sending a Data Dump Request, but sending
    anything to the device is a separate decision and deliberately not done
    here.)

HOW TO TRIGGER A DUMP ON THE ESX-1
    1. Press the GLOBAL key (it lights).
    2. Hold SHIFT and press step key 15 (MIDI UTILITY). Display: "MIDIUtil".
    3. Value display reads "Filter" -- turn the dial to "Dump", press key 15.
    4. Display reads "MIDIDump" -- turn the dial to choose what to send:
           PtBnkA / PtBnkB / PtBnkC / PtBnkD   pattern banks (64 patterns each)
           AllSng                              all song data
           Global                              global settings
    5. Press key 15 to transmit.

    Do not touch other keys while the dump runs.

USAGE
    python3 sysex_capture.py --list                 # show MIDI ports
    python3 sysex_capture.py -o dumps/ptbnkA.syx    # listen and save
    python3 sysex_capture.py -o out.syx --idle 8    # wait longer between msgs

ADJUSTABLE PARAMETERS
    IDLE_SECONDS    how long silence must last before the capture is considered
                    finished (a big dump has gaps; too small truncates it)
    MAX_WAIT        overall ceiling so the tool never hangs forever
"""

import argparse
import sys
import time
from pathlib import Path

try:
    import mido
except ImportError:
    sys.exit("mido not installed:  pip3 install mido python-rtmidi")

# --- Adjustable ------------------------------------------------------------
IDLE_SECONDS = 5.0  # silence after the last message that ends the capture
MAX_WAIT = 300.0  # absolute ceiling on one capture session
POLL = 0.01

# Korg's MIDI manufacturer ID, and the ESX-1's device family byte. Both are
# already known from the .esx format: the file's magic contains 0x71, and the
# WAV `smpl` chunk the machine writes uses Manufacturer 0x42 / Product 0x71.
KORG_ID = 0x42
ESX_FAMILY = 0x71


# O(1) time, O(1) space
def describe(msg_bytes: bytes) -> str:
    """Best-effort structural read of one SysEx message."""
    if len(msg_bytes) < 5:
        return "too short to classify"
    # Expected Korg shape:  F0 42 3n 71 <function> ... F7
    b = msg_bytes
    parts = []
    if b[0] != 0xF0:
        return "does not start with F0"
    if b[1] == KORG_ID:
        parts.append("Korg (0x42)")
        chan = b[2] & 0x0F
        parts.append(f"channel {chan + 1} (byte 0x{b[2]:02X})")
        if len(b) > 3:
            fam = b[3]
            parts.append(
                f"family 0x{fam:02X}"
                + (" = ESX-1" if fam == ESX_FAMILY else " (unexpected)")
            )
        if len(b) > 4:
            parts.append(f"function 0x{b[4]:02X}")
    else:
        parts.append(f"manufacturer 0x{b[1]:02X} (not Korg)")
    return "; ".join(parts)


# O(t + n) time, O(n) space — t = poll iterations (<= max_wait / POLL); n = SysEx bytes received
def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--list", action="store_true", help="list MIDI ports and exit")
    ap.add_argument(
        "-p", "--port", default=None, help="input port name (default: first available)"
    )
    ap.add_argument(
        "-o", "--output", default=None, help="file to write raw SysEx to (.syx)"
    )
    ap.add_argument(
        "--idle",
        type=float,
        default=IDLE_SECONDS,
        help=f"seconds of silence that end the capture (default {IDLE_SECONDS})",
    )
    ap.add_argument("--max-wait", type=float, default=MAX_WAIT)
    ap.add_argument(
        "--monitor",
        action="store_true",
        help="print EVERY incoming message (connectivity test: "
        "turn any knob on the ESX-1 and watch for traffic)",
    )
    args = ap.parse_args()

    inputs = mido.get_input_names()
    if args.list or not inputs:
        print("MIDI inputs :", inputs or "(none)")
        print("MIDI outputs:", mido.get_output_names() or "(none)")
        return 0 if inputs else 1

    port_name = args.port or inputs[0]
    print(f"Listening on: {port_name}")
    print(f"  ends after {args.idle:.0f}s of silence, or {args.max_wait:.0f}s total")
    if args.monitor:
        print("\n  MONITOR MODE — turn any knob or press a pad on the ESX-1.")
        print("  Traffic here means the cable direction is correct.\n", flush=True)
    print("\n  >>> Now trigger the dump on the ESX-1:")
    print("      GLOBAL -> SHIFT+key15 (MIDI UTILITY) -> dial to 'Dump' -> key15")
    print("      -> dial to PtBnkA / AllSng / Global -> key15 to send\n")

    messages: list[bytes] = []
    clock_count = 0
    other_count = 0
    started = time.time()
    last_sysex = None  # drives the idle timeout -- ONLY SysEx resets it
    first_activity = None  # any traffic at all, for the connectivity report
    announced = False
    last_beat = 0.0

    # mido delivers SysEx as one message with .type == 'sysex', so reassembly
    # across USB packet boundaries is handled for us.
    with mido.open_input(port_name) as port:
        # O(t + n) time, O(n) space — t = poll iterations (<= max_wait / POLL); n = bytes of MIDI received
        while True:
            now = time.time()
            if now - started > args.max_wait:
                print("  (max wait reached)", flush=True)
                break
            # The idle timer only starts once a dump has actually begun.
            # Clock ticks must NOT keep the capture alive -- the ESX-1 streams
            # clock continuously, which would hold the session open forever.
            if last_sysex is not None and now - last_sysex > args.idle:
                break

            # bigo-lint: disable=BIGO006 — amortised: each received message is drained exactly once over the whole session, so summed over all polls p totals n
            # O(p) time, O(p) space — p = bytes of MIDI messages pending since the last poll
            for msg in port.iter_pending():
                if first_activity is None:
                    first_activity = now
                if msg.type == "sysex":
                    raw = bytes(msg.bytes())
                    messages.append(raw)
                    last_sysex = time.time()
                    print(
                        f"  [{len(messages):3}] SysEx {len(raw):>8,} bytes  — {describe(raw)}",
                        flush=True,
                    )
                elif msg.type == "clock":
                    clock_count += 1
                else:
                    other_count += 1
                    if args.monitor:
                        print(f"        {msg.type:<12} {msg}", flush=True)

            if first_activity is not None and not announced:
                announced = True
                print(
                    "  >>> MIDI traffic detected — cable direction is CORRECT.\n",
                    flush=True,
                )

            # Heartbeat so a long silent wait is visibly alive, without
            # printing thousands of clock ticks.
            if args.monitor and now - last_beat > 10:
                last_beat = now
                waited = int(now - started)
                print(
                    f"        ...{waited}s  clock={clock_count}  "
                    f"other={other_count}  sysex={len(messages)}",
                    flush=True,
                )

            time.sleep(POLL)

    print()
    if not messages:
        print("  No SysEx received.")
        if clock_count or other_count:
            print(
                f"  ({clock_count:,} clock + {other_count} other message(s) DID arrive —"
            )
            print("   the cable direction and port are correct, so re-check the")
            print("   front-panel dump steps.)")
        else:
            print("  Nothing arrived at all. Check: cable direction (ESX MIDI OUT ->")
            print("  adapter MIDI IN), the adapter's own LEDs, and the port choice.")
        return 1

    # O(s) time, O(1) space — s = SysEx messages captured
    total = sum(len(m) for m in messages)
    print(f"  captured {len(messages)} message(s), {total:,} bytes total")
    if clock_count or other_count:
        print(
            f"  (plus {clock_count:,} clock and {other_count} other message(s), ignored)"
        )

    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"".join(messages))
        print(f"  wrote {out}  ({total:,} bytes)")
        print("\n  Next: run sysex_analyse.py on it to inspect the payload encoding.")
    else:
        print("  (no -o given, nothing saved)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
