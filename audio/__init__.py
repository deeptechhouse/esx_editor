"""
audio — ports (interfaces) for every external audio capability.

Ports-and-adapters (TDD §5.1): the codec and UI depend only on the Protocols in
audio.ports, never on ffmpeg/librosa directly, so any capability can be swapped
without touching callers. v1 adapters (ffmpeg converter, librosa key detector)
are added in a later workflow; WF1 freezes only the interfaces.

WF6 ships the first adapters: audio.passthrough.WavPassthroughConverter (WAV
header probe + byte copy) and NullKeyDetector (never guesses a key). Both
satisfy the ports structurally, so swapping in ffmpeg/librosa later touches no
caller.
"""

from .passthrough import NullKeyDetector, WavPassthroughConverter
from .ports import (
    AudioConverter,
    ConversionSpec,
    FxRenderer,
    KeyDetector,
    KeyResult,
)

__all__ = [
    "AudioConverter",
    "KeyDetector",
    "FxRenderer",
    "KeyResult",
    "ConversionSpec",
    "WavPassthroughConverter",
    "NullKeyDetector",
]
