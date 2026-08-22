"""
workspace.naming — slot-name convention (TDD §5.3).

TWO NAMESPACES
    Staging filename (unlimited):  kickdrum_Am_8A.wav
    8-byte machine slot name:      a08AmRUM  (Camelot letter+NN + short classical
                               + tail of the basename, uppercased)

The packed form takes the name from the TAIL so numbered variants (kick01 /
kick02) still distinguish themselves after truncation. Short classical is the
default: long form leaves nothing of the name for 10 of 24 Camelot positions.
"""

from __future__ import annotations

import os

# Camelot wheel <-> classical key (a bijection). Values are (flat, sharp) spellings.
CAMELOT: dict[str, tuple[str, str]] = {
    "1A": ("Abm", "G#m"), "1B": ("B", "B"),
    "2A": ("Ebm", "D#m"), "2B": ("F#", "F#"),
    "3A": ("Bbm", "A#m"), "3B": ("Db", "C#"),
    "4A": ("Fm", "Fm"),   "4B": ("Ab", "G#"),
    "5A": ("Cm", "Cm"),   "5B": ("Eb", "D#"),
    "6A": ("Gm", "Gm"),   "6B": ("Bb", "A#"),
    "7A": ("Dm", "Dm"),   "7B": ("F", "F"),
    "8A": ("Am", "Am"),   "8B": ("C", "C"),
    "9A": ("Em", "Em"),   "9B": ("G", "G"),
    "10A": ("Bm", "Bm"),  "10B": ("D", "D"),
    "11A": ("F#m", "F#m"), "11B": ("A", "A"),
    "12A": ("C#m", "C#m"), "12B": ("E", "E"),
}

SLOT_NAME_LEN = 8


def classical(camelot: str, style: str = "short") -> str:
    """Return the classical spelling for a Camelot code.

    style='short' -> 'Am' / 'C' / 'F#m'   (the default, TDD §5.3)
    style='long'  -> 'Amin' / 'Cmaj'
    """
    if camelot not in CAMELOT:
        raise ValueError(f"unknown Camelot code {camelot!r}")
    flat, _sharp = CAMELOT[camelot]
    minor = camelot.endswith("A")
    root = flat[:-1] if minor else flat
    if style == "long":
        return root + ("min" if minor else "maj")
    if style == "short":
        return root + ("m" if minor else "")
    raise ValueError(f"unknown classical style {style!r}")


def _stem(path_or_name: str) -> str:
    return os.path.splitext(os.path.basename(path_or_name))[0]


def pack_slot_name(basename: str, camelot: str | None,
                   style: str = "short") -> str:
    """Pack an 8-byte machine slot name. Pads/truncates to exactly 8 chars.

    With no key, uses the uppercased tail of the basename. With a Camelot code,
    uses [a|b][NN][classical][tail] as specified in TDD §5.3.
    """
    name = _stem(basename)
    if not camelot:
        return name.upper()[-SLOT_NAME_LEN:].ljust(SLOT_NAME_LEN)[:SLOT_NAME_LEN]
    if camelot not in CAMELOT:
        raise ValueError(f"unknown Camelot code {camelot!r}")
    letter = camelot[-1].lower()
    num = camelot[:-1].zfill(2)
    prefix = letter + num
    key = "" if style == "camelot" else classical(camelot, style)
    head = prefix + key
    room = SLOT_NAME_LEN - len(head)
    tail = name[-room:].upper() if room > 0 else ""
    return (head + tail)[:SLOT_NAME_LEN].ljust(SLOT_NAME_LEN)


def staging_filename(basename: str, classical_key: str | None,
                     camelot: str | None) -> str:
    """Unlimited-length on-disk name carrying both notations (TDD §5.3)."""
    stem = _stem(basename)
    if classical_key and camelot:
        return f"{stem}_{classical_key}_{camelot}.wav"
    return f"{stem}.wav"
