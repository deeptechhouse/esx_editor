"""
audio — ports (interfaces) for every external audio capability.

Ports-and-adapters (TDD §5.1): the codec and UI depend only on the Protocols in
audio.ports, never on ffmpeg/librosa directly, so any capability can be swapped
without touching callers. v1 adapters (ffmpeg converter, librosa key detector)
are added in a later workflow; WF1 freezes only the interfaces.
"""

from .ports import (
    AudioConverter,
    KeyDetector,
    FxRenderer,
    KeyResult,
    ConversionSpec,
)

__all__ = [
    "AudioConverter",
    "KeyDetector",
    "FxRenderer",
    "KeyResult",
    "ConversionSpec",
]
