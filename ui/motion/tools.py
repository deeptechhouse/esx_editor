"""
ui.motion.tools — pure functions that write MotionSlot bytes.

No Qt here. The canvas and the byte-verify suite both call these, so a drawn
curve and a scripted curve produce the same encodings:

    discrete:  value = i * ceil(128 / N)     (0/64, 0/43/86, 0/32/64/96)
    Disabl:    0x80
    beyond N:  untouched (length masking)

Tools never interpolate through a Disabl step and never write Pitch (the picker
hides it; these functions are domain-agnostic and will snap whatever domain
they are given).
"""

from __future__ import annotations

import math
import random

from core.motion import MotionDomain, MotionSlot

SHAPES = ("sine", "tri", "saw", "square")


def write_step(slot: MotionSlot, step: int, stored: int | None,
               domain: MotionDomain, *, length: int = MotionSlot.NUM_STEPS) -> None:
    """Pencil / eraser primitive: one step, snapped, length-masked."""
    slot.write_stored(step, stored, domain, length=length)


def eraser(slot: MotionSlot, step: int, domain: MotionDomain,
           *, length: int = MotionSlot.NUM_STEPS) -> None:
    slot.write_stored(step, None, domain, length=length)


def clear(slot: MotionSlot, domain: MotionDomain,
          *, length: int = MotionSlot.NUM_STEPS) -> None:
    """Fill the playable range with Disabl; keep the target id."""
    for i in range(min(length, MotionSlot.NUM_STEPS)):
        slot.write_stored(i, None, domain, length=length)


def line(slot: MotionSlot, domain: MotionDomain,
         x0: int, y0: int, x1: int, y1: int,
         *, length: int = MotionSlot.NUM_STEPS) -> None:
    """Linear interpolation inclusive of both endpoints (length-masked)."""
    if x0 == x1:
        write_step(slot, x0, y0, domain, length=length)
        return
    if x1 < x0:
        x0, x1, y0, y1 = x1, x0, y1, y0
    span = x1 - x0
    for x in range(x0, x1 + 1):
        t = (x - x0) / span
        y = y0 + t * (y1 - y0)
        write_step(slot, x, int(round(y)), domain, length=length)


def ramp(slot: MotionSlot, domain: MotionDomain,
         start: int, end: int,
         *, length: int = MotionSlot.NUM_STEPS) -> None:
    """Ramp across the playable range (last playable step = `end`)."""
    last = min(length, MotionSlot.NUM_STEPS) - 1
    if last < 0:
        return
    line(slot, domain, 0, start, last, end, length=length)


def lfo(slot: MotionSlot, domain: MotionDomain, shape: str,
        *, depth: int = 127, centre: int = 64,
        length: int = MotionSlot.NUM_STEPS) -> None:
    """One cycle of sine / tri / saw / square over the playable range."""
    if shape not in SHAPES:
        raise ValueError(f"unknown LFO shape {shape!r}")
    n = min(length, MotionSlot.NUM_STEPS)
    if n <= 0:
        return
    amp = depth / 2.0
    for i in range(n):
        t = i / n                          # [0, 1)
        if shape == "sine":
            w = math.sin(2 * math.pi * t)
        elif shape == "tri":
            # -1..1 triangle starting at 0 going up
            ph = (t + 0.25) % 1.0
            w = 4 * ph - 1 if ph < 0.5 else 3 - 4 * ph
        elif shape == "saw":
            w = 2 * t - 1
        else:  # square
            w = 1.0 if t < 0.5 else -1.0
        y = centre + amp * w
        write_step(slot, i, int(round(y)), domain, length=length)


def sample_and_hold(slot: MotionSlot, domain: MotionDomain,
                    *, hold: int = 8, length: int = MotionSlot.NUM_STEPS,
                    rng: random.Random | None = None) -> None:
    rng = rng or random.Random()
    legal = domain.legal_values()
    hold = max(1, hold)
    n = min(length, MotionSlot.NUM_STEPS)
    current = legal[rng.randrange(len(legal))]
    for i in range(n):
        if i % hold == 0:
            current = legal[rng.randrange(len(legal))]
        write_step(slot, i, current, domain, length=length)


def invert(slot: MotionSlot, domain: MotionDomain,
           *, length: int = MotionSlot.NUM_STEPS) -> None:
    """Mirror enabled steps around 63.5; Disabl and masked steps stay put."""
    n = min(length, MotionSlot.NUM_STEPS)
    for i in range(n):
        if slot.is_disabled(i):
            continue
        write_step(slot, i, 127 - slot.get_step(i), domain, length=length)


def scale(slot: MotionSlot, domain: MotionDomain, factor: float,
          *, centre: int = 64, length: int = MotionSlot.NUM_STEPS) -> None:
    n = min(length, MotionSlot.NUM_STEPS)
    for i in range(n):
        if slot.is_disabled(i):
            continue
        y = centre + (slot.get_step(i) - centre) * factor
        write_step(slot, i, int(round(y)), domain, length=length)


def smooth(slot: MotionSlot, domain: MotionDomain,
           *, length: int = MotionSlot.NUM_STEPS) -> None:
    """3-point average of neighbouring *enabled* steps; Disabl is a wall."""
    n = min(length, MotionSlot.NUM_STEPS)
    original = [slot.get_step(i) for i in range(n)]
    disabled = [slot.is_disabled(i) for i in range(n)]
    for i in range(n):
        if disabled[i]:
            continue
        acc = [original[i]]
        if i > 0 and not disabled[i - 1]:
            acc.append(original[i - 1])
        if i + 1 < n and not disabled[i + 1]:
            acc.append(original[i + 1])
        write_step(slot, i, int(round(sum(acc) / len(acc))), domain, length=length)


def randomise(slot: MotionSlot, domain: MotionDomain,
              *, length: int = MotionSlot.NUM_STEPS,
              rng: random.Random | None = None) -> None:
    rng = rng or random.Random()
    legal = domain.legal_values()
    n = min(length, MotionSlot.NUM_STEPS)
    for i in range(n):
        write_step(slot, i, legal[rng.randrange(len(legal))], domain, length=length)
