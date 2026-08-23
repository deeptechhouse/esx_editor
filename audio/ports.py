"""
audio.ports — the interfaces every external audio capability implements.

WHY PROTOCOLS
    typing.Protocol gives structural interfaces: an adapter satisfies a port by
    shape, with no inheritance coupling. This is the vendor-swap boundary the
    project standard requires (ffmpeg <-> soundfile+soxr; librosa <->
    libkeyfinder) without the codec or UI ever importing a concrete backend.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


class KeyResult:
    """The outcome of key detection: classical + Camelot are a bijection.

    Both notations are always derived from one estimate, so they cannot
    disagree (TDD §5.3). `confidence` is 0..1; callers may suppress the key
    suffix for low-confidence percussive material.
    """

    __slots__ = ("_camelot", "_classical", "_confidence")

    def __init__(self, camelot: str, classical: str, confidence: float):
        self._camelot = camelot
        self._classical = classical
        self._confidence = confidence

    @property
    def camelot(self) -> str:
        """e.g. '8A' (letter = mode: A minor, B major)."""
        return self._camelot

    @property
    def classical(self) -> str:
        """e.g. 'Am', 'C', 'F#m'."""
        return self._classical

    @property
    def confidence(self) -> float:
        return self._confidence


class NoteResult:
    """The dominant pitch of a sound, whether or not it has a musical key.

    WHY THIS IS SEPARATE FROM KeyResult
        A key is a claim about harmony — which seven notes a piece of music is
        built from. Most one-shots have no key: a kick drum is not "in A minor".
        But nearly every real sound has a dominant PITCH, and for a sampler that
        is often the more useful number: it tells you what a kick, tom or snare
        body will clash with, and how far to tune it.

        The two are independent. Tonal material has both. A drum hit usually has
        only a note. True broadband noise has neither, and says so.

    `cents` is the deviation from the exact equal-tempered note, -50..+50, so a
    sound 30 cents sharp of A is reported as A with cents=+30 rather than
    silently rounded.
    """

    __slots__ = ("_name", "_octave", "_frequency", "_cents", "_confidence")

    def __init__(
        self, name: str, octave: int, frequency: float, cents: float, confidence: float
    ):
        self._name = name
        self._octave = octave
        self._frequency = frequency
        self._cents = cents
        self._confidence = confidence

    @property
    def name(self) -> str:
        """Pitch class, sharp spelling: 'C', 'F#', 'A'."""
        return self._name

    @property
    def octave(self) -> int:
        """Scientific pitch notation octave — middle C is C4."""
        return self._octave

    @property
    def label(self) -> str:
        """The note as a musician would write it: 'A1', 'F#3'."""
        return f"{self._name}{self._octave}"

    @property
    def frequency(self) -> float:
        """The measured dominant frequency in Hz."""
        return self._frequency

    @property
    def cents(self) -> float:
        """Deviation from equal temperament, -50..+50."""
        return self._cents

    @property
    def confidence(self) -> float:
        """0..1, from how far the spectral peak stands above the noise floor."""
        return self._confidence

    def __repr__(self) -> str:
        return f"<NoteResult {self.label} {self._cents:+.0f}c {self._frequency:.1f}Hz>"


class ConversionSpec:
    """The target format for a conversion (TDD §5.2).

    Bit depth is always 16 (the file stores 16-bit; 8-bit input is
    zero-expanded), so it is not a parameter here.
    """

    __slots__ = ("_rate", "_channels", "_strip_smpl")

    def __init__(self, rate: int, channels: int, strip_smpl: bool = True):
        self._rate = rate
        self._channels = channels
        self._strip_smpl = strip_smpl

    @property
    def rate(self) -> int:
        return self._rate

    @property
    def channels(self) -> int:
        return self._channels

    @property
    def strip_smpl(self) -> bool:
        """Strip inherited smpl chunks so the hardware does not silently
        redefine the sample's End from a stray loop (TDD §5.2)."""
        return self._strip_smpl


@runtime_checkable
class AudioConverter(Protocol):
    """Decode any input format and write 16-bit PCM at the requested spec."""

    def convert(self, src_path: str, dst_path: str, spec: ConversionSpec) -> None:
        """Convert src -> dst. The original file is NEVER modified (TDD §5.2).

        Resampling uses proper anti-aliasing; reduction to 16-bit dithers.
        """
        ...

    def probe_duration(self, src_path: str) -> tuple[float, int, int]:
        """Return (duration_seconds, source_rate, channels) from the header
        only, without decoding audio (TDD §6.1)."""
        ...


@runtime_checkable
class KeyDetector(Protocol):
    """Estimate the musical key of an audio file."""

    def detect(self, path: str, max_seconds: float | None = None) -> KeyResult | None:
        """Return the estimated key, or None if the material is not tonal enough.

        Returning None is a legitimate, expected outcome: percussive one-shots
        have no key, and guessing one would mislabel the file permanently
        (TDD §5.1 / §6.5).
        """
        ...


@runtime_checkable
class PitchDetector(Protocol):
    """Estimate the dominant pitch of a sound, tonal or percussive."""

    def detect_note(
        self, path: str, max_seconds: float | None = None
    ) -> NoteResult | None:
        """Return the dominant note, or None when there is no spectral peak.

        Returning None is reserved for material with genuinely flat spectral
        content — broadband noise. Ordinary percussion has a clear fundamental
        and must report it.
        """
        ...


@runtime_checkable
class FxRenderer(Protocol):
    """Approximate offline render of the ESX-1 effects (phase 2 only, TDD §8.6).

    v1 ships NO adapter; motion preview is silent. Any future adapter is offline
    (render-to-buffer), never a real-time callback, and its output is labelled
    'approximate' in the UI.
    """

    def render(
        self, pcm: bytes, sample_rate: int, fx_type: int, edit1: int, edit2: int
    ) -> bytes: ...
