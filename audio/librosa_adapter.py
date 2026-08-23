"""
audio.librosa_adapter — the v1 KeyDetector (TDD §5.1, §5.3).

METHOD
    Chroma from a constant-Q transform, averaged over time, then correlated
    against the Krumhansl-Schmuckler key profiles in all 24 rotations. The
    highest correlation wins. CQT rather than STFT chroma because it puts bins
    on musical semitones rather than linear frequency, which matters most in
    the bass — and bass is what a sampler is usually fed.

WHY IT IS ALLOWED TO SAY NOTHING
    Returning None is a first-class result, not a failure. A kick drum has no
    key. Guessing one puts a wrong letter into an 8-character slot name that
    then goes to the hardware and stays there. Two gates enforce it:

      - a confidence floor, computed as the MARGIN between the best key and
        the best key of the opposite mode, not as the raw correlation. Raw
        correlation is high for anything with harmonic content, including
        noise; the margin is what actually distinguishes "this is A minor"
        from "this is vaguely tonal".
      - a percussiveness check: if harmonic-percussive separation leaves
        almost no harmonic energy, there is nothing to have a key.

IMPORT COST
    librosa pulls in numpy, scipy, numba and llvmlite — seconds of import time.
    It is imported lazily inside detect() so the app starts fast and so a
    machine without it degrades to NullKeyDetector rather than failing to boot.
"""

from __future__ import annotations

import importlib.util
import math

from audio.ports import KeyResult

#: Krumhansl-Schmuckler profiles (Krumhansl & Kessler 1982), C-rooted.
MAJOR_PROFILE = (
    6.35,
    2.23,
    3.48,
    2.33,
    4.38,
    4.09,
    2.52,
    5.19,
    2.39,
    3.66,
    2.29,
    2.88,
)
MINOR_PROFILE = (
    6.33,
    2.68,
    3.52,
    5.38,
    2.60,
    3.53,
    2.54,
    4.75,
    3.98,
    2.69,
    3.34,
    3.17,
)

#: Pitch classes, sharp spelling, index 0 = C.
PITCH_CLASSES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")

#: Camelot wheel position for each (pitch class index, is_minor).
#: 8B = C major and 8A = A minor are the anchors; the wheel advances by a
#: perfect fifth (7 semitones) per position.
_CAMELOT_MAJOR_ROOT = 0  # C
_CAMELOT_MAJOR_POSITION = 8

#: Below this margin between the best key and the best opposite-mode key, the
#: estimate is not trustworthy enough to put in a permanent name.
DEFAULT_MIN_MARGIN = 0.06

#: Above this chroma flatness, the material has no tonal centre at all.
#:
#: MEASURED, not guessed. Flatness is the geometric mean of the chroma vector
#: over its arithmetic mean: 1.0 is perfectly uniform, lower is peakier.
#:     C major progression  0.372      white noise        0.999
#:     A minor progression  0.368      white noise (2)    0.999
#:     Am pad + hard kick   0.238      pink-ish noise     0.970
#:                                     kick drum          0.888
#: 0.70 sits in the empty band between 0.38 and 0.89.
#:
#: This gate is what actually rejects noise. The margin alone does NOT: white
#: noise scored a margin of 0.258, HIGHER than the real C major progression's
#: 0.238, because a flat chroma still correlates best with *something*. Without
#: this check the detector confidently labelled white noise "Fm".
DEFAULT_MAX_CHROMA_FLATNESS = 0.70

#: Below this fraction of harmonic energy, treat the material as percussive.
DEFAULT_MIN_HARMONIC_RATIO = 0.10

#: Analysing more than this is wasted: key does not change, and a 5-minute file
#: would otherwise cost 5 minutes of CQT (TDD §6.5).
DEFAULT_MAX_SECONDS = 30.0


def available() -> bool:
    """True when librosa can be imported without actually importing it."""
    return importlib.util.find_spec("librosa") is not None


def camelot_for(pitch_class: int, minor: bool) -> str:
    """Camelot code for a pitch class and mode.

    Derived rather than tabulated: the wheel is a circle of fifths, so a major
    key's position is 8 + 7*semitones (mod 12), anchored at C major = 8B.

    A minor key shares its position with its RELATIVE major — that is the whole
    point of the wheel, and the reason 8A (A minor) sits beside 8B (C major)
    rather than beside C minor. The relative major is three semitones up, so a
    minor key is placed by that root, not its own. Getting this wrong yields a
    plausible-looking code that is a minor third out on every minor key.

    Verified against the 24-entry table in workspace.naming.
    """
    root = (pitch_class + 3) % 12 if minor else pitch_class
    steps = (root - _CAMELOT_MAJOR_ROOT) * 7
    position = (_CAMELOT_MAJOR_POSITION - 1 + steps) % 12 + 1
    return f"{position}{'A' if minor else 'B'}"


def classical_for(pitch_class: int, minor: bool) -> str:
    """'Am' / 'C' / 'F#m' for a pitch class and mode."""
    return PITCH_CLASSES[pitch_class] + ("m" if minor else "")


def _correlate(chroma: list[float], profile: tuple[float, ...], rotation: int) -> float:
    """Pearson correlation of the chroma against a rotated key profile."""
    rotated = [profile[(i - rotation) % 12] for i in range(12)]
    n = 12
    mean_c = sum(chroma) / n
    mean_p = sum(rotated) / n
    cov = sum((chroma[i] - mean_c) * (rotated[i] - mean_p) for i in range(n))
    var_c = sum((chroma[i] - mean_c) ** 2 for i in range(n))
    var_p = sum((rotated[i] - mean_p) ** 2 for i in range(n))
    if var_c <= 0 or var_p <= 0:
        return 0.0
    return cov / (var_c * var_p) ** 0.5


def chroma_flatness(chroma: list[float]) -> float:
    """Geometric mean over arithmetic mean of the chroma vector.

    1.0 means every pitch class carries equal energy — noise, or nothing.
    A real key concentrates energy in seven of the twelve, so it scores far
    lower. Pure function, so the thresholds above can be re-measured.
    """
    total = sum(chroma)
    if total <= 0:
        return 1.0
    normalised = [max(v / total, 1e-12) for v in chroma]
    log_mean = sum(math.log(v) for v in normalised) / len(normalised)
    arithmetic = sum(normalised) / len(normalised)
    return math.exp(log_mean) / arithmetic if arithmetic > 0 else 1.0


def estimate_from_chroma(chroma: list[float]) -> tuple[int, bool, float]:
    """Return (pitch_class, is_minor, margin) for a 12-bin chroma vector.

    `margin` is the gap between the winning key and the best key of the
    OPPOSITE mode. Major/minor confusion is the failure mode that matters: C
    major and A minor share every note, so a detector that cannot separate them
    is not confident even when its raw correlation is high.
    """
    if len(chroma) != 12:
        raise ValueError(f"chroma must have 12 bins, got {len(chroma)}")
    scores = []
    for rotation in range(12):
        scores.append((_correlate(chroma, MAJOR_PROFILE, rotation), rotation, False))
        scores.append((_correlate(chroma, MINOR_PROFILE, rotation), rotation, True))
    scores.sort(reverse=True)
    best_score, best_root, best_minor = scores[0]
    opposite = next(
        (s for s in scores if s[2] is not best_minor), (0.0, 0, not best_minor)
    )
    return best_root, best_minor, best_score - opposite[0]


class LibrosaKeyDetector:
    """KeyDetector backed by librosa's CQT chroma."""

    __slots__ = ("_min_margin", "_min_harmonic", "_max_seconds", "_max_flatness")

    def __init__(
        self,
        min_margin: float = DEFAULT_MIN_MARGIN,
        min_harmonic_ratio: float = DEFAULT_MIN_HARMONIC_RATIO,
        max_seconds: float = DEFAULT_MAX_SECONDS,
        max_chroma_flatness: float = DEFAULT_MAX_CHROMA_FLATNESS,
    ):
        if not available():
            raise ImportError(
                "librosa is not installed; key detection stays on NullKeyDetector"
            )
        self._min_margin = min_margin
        self._min_harmonic = min_harmonic_ratio
        self._max_seconds = max_seconds
        self._max_flatness = max_chroma_flatness

    def detect(self, path: str, max_seconds: float | None = None) -> KeyResult | None:
        """Estimate the key, or None when the material is not tonal enough."""
        import librosa  # noqa: PLC0415 - deliberately lazy; see module docstring
        import numpy as np

        limit = self._max_seconds if max_seconds is None else max_seconds
        try:
            y, sr = librosa.load(path, sr=None, mono=True, duration=limit)
        except Exception:
            # A file librosa cannot decode has no key. Failing the whole
            # staging flow over it would be worse than reporting "no key".
            return None
        if y.size == 0 or not np.any(y):
            return None

        harmonic, percussive = librosa.effects.hpss(y)
        harmonic_energy = float(np.sum(harmonic**2))
        total_energy = harmonic_energy + float(np.sum(percussive**2))
        if total_energy <= 0:
            return None
        harmonic_ratio = harmonic_energy / total_energy
        if harmonic_ratio < self._min_harmonic:
            return None  # percussive: no key to find

        chroma = librosa.feature.chroma_cqt(y=harmonic, sr=sr)
        averaged = [float(v) for v in np.mean(chroma, axis=1)]
        if not any(averaged):
            return None

        flatness = chroma_flatness(averaged)
        if flatness > self._max_flatness:
            return None  # no tonal centre: noise, or something close to it

        root, minor, margin = estimate_from_chroma(averaged)
        if margin < self._min_margin:
            return None  # tonal, but not confidently in one key

        # Confidence blends three things: how cleanly one mode won, how
        # harmonic the material is, and how peaked the chroma is. A strong
        # margin on a mostly-percussive loop is a shakier claim than the same
        # margin on a sustained pad.
        confidence = min(1.0, margin * 4.0) * harmonic_ratio * (1.0 - flatness)
        return KeyResult(
            camelot_for(root, minor), classical_for(root, minor), confidence
        )
