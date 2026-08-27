"""
ui.midi_names — advisory names for the 128 control-change numbers.

WHAT THESE ARE, AND WHAT THEY ARE NOT
    These are the MIDI specification's own general-purpose names. They are a
    HINT for picking a number, nothing more: the ESX-1 does not implement most
    of them, and your controller is free to send CC 74 from a fader labelled
    anything at all. The number is what travels down the cable; the name is
    here so "which one was the mod wheel again" does not need a web search.

    Numbers with no standard meaning are deliberately left bare rather than
    invented, so a blank name reads as "free to use", which is what it is.
"""

from __future__ import annotations

#: number -> the MIDI spec's general name. Sparse on purpose.
STANDARD_CC_NAMES = {
    0: "Bank Select MSB",
    1: "Mod Wheel",
    2: "Breath",
    4: "Foot Pedal",
    5: "Portamento Time",
    6: "Data Entry MSB",
    7: "Volume",
    8: "Balance",
    10: "Pan",
    11: "Expression",
    12: "Effect Control 1",
    13: "Effect Control 2",
    16: "General Purpose 1",
    17: "General Purpose 2",
    18: "General Purpose 3",
    19: "General Purpose 4",
    32: "Bank Select LSB",
    64: "Sustain Pedal",
    65: "Portamento On/Off",
    66: "Sostenuto",
    67: "Soft Pedal",
    68: "Legato",
    69: "Hold 2",
    70: "Sound Variation",
    71: "Resonance",
    72: "Release Time",
    73: "Attack Time",
    74: "Brightness / Cutoff",
    75: "Decay Time",
    76: "Vibrato Rate",
    77: "Vibrato Depth",
    78: "Vibrato Delay",
    79: "Sound Control 10",
    80: "General Purpose 5",
    81: "General Purpose 6",
    82: "General Purpose 7",
    83: "General Purpose 8",
    84: "Portamento Control",
    91: "Reverb Send",
    92: "Tremolo Depth",
    93: "Chorus Send",
    94: "Detune Depth",
    95: "Phaser Depth",
    120: "All Sound Off",
    121: "Reset All Controllers",
    122: "Local On/Off",
    123: "All Notes Off",
    124: "Omni Off",
    125: "Omni On",
    126: "Mono Mode",
    127: "Poly Mode",
}

#: Above this, control changes are reserved channel-mode messages. Assigning a
#: knob to one is legal in the file but a bad idea on the wire, so the picker
#: marks them rather than hiding them — the machine allows it, so the editor
#: does too, with a warning.
CHANNEL_MODE_FIRST = 120


def note_choice_label(number: int, name: str) -> str:
    """ "C2  (36)" — the NAME first, because that is what the ESX-1 displays.

    The number follows in brackets because it is what a DAW or a controller's
    documentation will quote, and having to convert between the two in your
    head is exactly the friction this list exists to remove.
    """
    return f"{name}  ({number})"


def cc_label(number: int) -> str:
    """ "74 — Brightness / Cutoff", or just "53" where the spec says nothing."""
    name = STANDARD_CC_NAMES.get(number, "")
    if not name:
        return f"{number}"
    if number >= CHANNEL_MODE_FIRST:
        return f"{number} — {name}  (reserved)"
    return f"{number} — {name}"
