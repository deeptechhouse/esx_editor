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

from .factory import Capabilities, detect_capabilities
from .passthrough import NullKeyDetector, WavPassthroughConverter
from .pcm import WavPcmReader, fold_to_mono, split_stereo, swap_endianness
from .pitch import SpectralPitchDetector, frequency_to_note, note_to_frequency
from .ports import (
    AudioConverter,
    ConversionSpec,
    FxRenderer,
    KeyDetector,
    KeyResult,
    NoteResult,
    PitchDetector,
)

__all__ = [
    "AudioConverter",
    "NoteResult",
    "PitchDetector",
    "KeyDetector",
    "FxRenderer",
    "KeyResult",
    "ConversionSpec",
    "WavPassthroughConverter",
    "NullKeyDetector",
    "WavPcmReader",
    "SpectralPitchDetector",
    "frequency_to_note",
    "note_to_frequency",
    "Capabilities",
    "detect_capabilities",
    "swap_endianness",
    "fold_to_mono",
    "split_stereo",
]
