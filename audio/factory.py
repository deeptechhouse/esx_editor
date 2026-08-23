"""
audio.factory — pick the best adapter available on this machine.

WHY A FACTORY AND NOT AN IMPORT
    The concrete backends are optional: ffmpeg is an external binary and
    librosa is a heavy optional dependency that will not build on every
    machine (llvmlite needs an LLVM toolchain, and older pins have no wheel
    for this Python). The app must run without either, so nothing imports a
    backend at module scope — this is the single place that decides, and it
    reports what it chose so the UI can tell the user the truth about which
    capabilities are live.
"""

from __future__ import annotations

import functools

from audio.passthrough import NullKeyDetector, WavPassthroughConverter
from audio.ports import AudioConverter, KeyDetector, PitchDetector


class Capabilities:
    """What this machine can actually do, and the adapters that do it."""

    __slots__ = ("_converter", "_detector", "_pitch", "_notes")

    def __init__(
        self,
        converter: AudioConverter,
        detector: KeyDetector,
        pitch: PitchDetector | None,
        notes: tuple[str, ...],
    ):
        self._converter = converter
        self._detector = detector
        self._pitch = pitch
        self._notes = notes

    @property
    def converter(self) -> AudioConverter:
        return self._converter

    @property
    def detector(self) -> KeyDetector:
        return self._detector

    @property
    def pitch(self) -> PitchDetector | None:
        """The dominant-pitch detector, or None when unavailable."""
        return self._pitch

    @property
    def can_detect_note(self) -> bool:
        return self._pitch is not None

    @property
    def notes(self) -> tuple[str, ...]:
        """One human-readable line per capability, live or missing."""
        return self._notes

    @property
    def can_convert_any_format(self) -> bool:
        return type(self._converter).__name__ != "WavPassthroughConverter"

    @property
    def can_detect_key(self) -> bool:
        return type(self._detector).__name__ != "NullKeyDetector"


def build_converter() -> tuple[AudioConverter, str]:
    """The best AudioConverter available, plus a line describing it."""
    from audio import ffmpeg_adapter

    if ffmpeg_adapter.available():
        try:
            converter = ffmpeg_adapter.FfmpegConverter()
        except Exception as exc:  # pragma: no cover - defensive
            return (
                WavPassthroughConverter(),
                f"WAV only — ffmpeg found but unusable ({exc})",
            )
        engine = converter.resampler_engine
        quality = (
            "soxr (highest quality)"
            if engine == "soxr"
            else "swr (good; this ffmpeg was built without libsoxr)"
        )
        return converter, f"Any format via ffmpeg; resampling with {quality}"
    return (
        WavPassthroughConverter(),
        "WAV only — install ffmpeg (brew install ffmpeg) for other formats",
    )


def build_detector() -> tuple[KeyDetector, str]:
    """The best KeyDetector available, plus a line describing it."""
    from audio import librosa_adapter

    if librosa_adapter.available():
        try:
            return (
                librosa_adapter.LibrosaKeyDetector(),
                "Key detection via librosa (CQT chroma + Krumhansl-Schmuckler)",
            )
        except Exception as exc:  # pragma: no cover - defensive
            return NullKeyDetector(), f"No key detection — librosa unusable ({exc})"
    return (
        NullKeyDetector(),
        "No key detection — install librosa for it; names stay key-free",
    )


@functools.lru_cache(maxsize=1)
def build_pitch_detector() -> tuple[PitchDetector | None, str]:
    """The dominant-pitch detector, plus a line describing it."""
    from audio import pitch as pitch_module

    if pitch_module.available():
        try:
            return (
                pitch_module.SpectralPitchDetector(),
                "Dominant note via spectral peak — works on drums, not just "
                "tonal material",
            )
        except Exception as exc:  # pragma: no cover - defensive
            return None, f"No note detection — unusable ({exc})"
    return None, "No note detection — needs numpy and librosa"


@functools.lru_cache(maxsize=1)
def detect_capabilities() -> Capabilities:
    """Probe the machine ONCE and return the adapters to use.

    Cached deliberately. Probing costs an ffmpeg subprocess and a librosa
    import (seconds, because of numba/llvmlite), and the answer cannot change
    while the process runs. Without the cache every widget construction paid
    it, which took the test suite from 35 s to over two minutes.

    Call `detect_capabilities.cache_clear()` in a test that needs to simulate a
    machine with different backends.
    """
    converter, converter_note = build_converter()
    detector, detector_note = build_detector()
    pitch, pitch_note = build_pitch_detector()
    return Capabilities(
        converter, detector, pitch, (converter_note, detector_note, pitch_note)
    )
