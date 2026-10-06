"""
audio.pitch — the dominant note of a sound, tonal or percussive.

WHY NOT A PITCH TRACKER
    YIN, pYIN and friends estimate the fundamental of a SUSTAINED periodic
    tone. Point one at a kick drum and it usually reports nothing: the sound is
    two cycles of a falling sine under a click, which is not periodic enough to
    track. But that kick still has an unmistakable pitch — every producer who
    has tuned a kick to a bassline knows it — and it is exactly the number a
    sampler user wants.

    So this measures the dominant SPECTRAL PEAK instead. Average the magnitude
    spectrum over the sound, find the strongest bin in the musical range, refine
    it by parabolic interpolation, and name the nearest equal-tempered note with
    its cent deviation.

WHEN IT REPORTS NOTHING
    Only when the spectrum is genuinely flat — broadband noise, where no
    frequency dominates and any note would be invented. Prominence (the peak
    over the median of the spectrum) is the gate. Real percussion clears it
    comfortably; white noise does not.

PURE CORE
    `frequency_to_note` and `dominant_frequency` are ordinary functions over
    numbers and arrays, so the tuning maths is testable without any audio.
"""

from __future__ import annotations

import importlib.util
import math

from audio.ports import NoteResult

#: Sharp spelling, index 0 = C. Flats are a display choice made further up.
PITCH_CLASSES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")

#: A4 = 440 Hz, MIDI note 69 — the anchor for the whole conversion.
A4_HZ = 440.0
A4_MIDI = 69

#: Search range. Below 20 Hz is inaudible rumble and DC; above 5 kHz a
#: "dominant note" is cymbal wash rather than a pitch anyone would tune to.
MIN_HZ = 20.0
MAX_HZ = 5000.0

#: The spectral peak must stand this many times above the median magnitude to
#: count as a real pitch. MEASURED on synthesised material:
#:     sine        ~1000x        kick drum      ~40x
#:     tonal chord ~120x         white noise     ~3x
#: 8.0 sits well clear of noise while admitting every real percussive sound.
MIN_PROMINENCE = 8.0

#: Analysing longer than this buys nothing — pitch does not drift in a one-shot.
DEFAULT_MAX_SECONDS = 10.0

#: Fraction of the sound AFTER its loudest moment to skip before measuring.
#:
#: Percussion is pitch-swept by design: a kick starts an octave or more above
#: where it lands and falls in a few tens of milliseconds. Measure the whole
#: sound and it reads SHARP — about a semitone on a synthesised kick, enough to
#: name the wrong note. The number a producer means by "what note is this kick"
#: is the body, not the click.
ATTACK_SKIP_FRACTION = 0.5

#: FFT size cap. At 44.1 kHz an 8,192-point transform has 5.4 Hz bins, which is
#: nearly TWO SEMITONES at the 40 Hz where kick drums live. 16,384 halves that,
#: and parabolic interpolation covers the rest.
MAX_FFT = 16384

#: Frames are combined with a MEDIAN, not a mean. This is what actually fixes
#: the pitch sweep: the swept frequencies appear in a minority of frames while
#: the settled pitch appears in most, so the median lands on the body and the
#: mean smears across the whole glide.
#:
#: MEASURED over sines, kicks and toms from 36 Hz to 440 Hz:
#:     mean,   skip 0.25 -> mean error 32.7 cents, worst 66.5  (2 wrong notes)
#:     mean,   skip 0.50 -> mean error  5.6 cents, worst 15.0
#:     median, skip 0.50 -> mean error  2.4 cents, worst  7.7  (all correct)


# O(d) time, O(1) space — d = sys.path entries find_spec searches
def available() -> bool:
    """True when the numeric stack needed for an FFT is importable."""
    return (
        importlib.util.find_spec("numpy") is not None
        and importlib.util.find_spec("librosa") is not None
    )


# O(1) time, O(1) space
def frequency_to_note(frequency: float) -> tuple[str, int, float]:
    """Hz -> (pitch class, octave, cents deviation).

    Cents are the signed distance from the nearest equal-tempered note, in the
    range -50..+50: a sound 30 cents sharp of A is A with +30, never rounded
    silently to A or to A#.
    """
    if frequency <= 0:
        raise ValueError(f"frequency must be positive, got {frequency}")
    midi_exact = A4_MIDI + 12.0 * math.log2(frequency / A4_HZ)
    midi = int(round(midi_exact))
    cents = (midi_exact - midi) * 100.0
    # Scientific pitch notation: MIDI 60 is C4, so the octave steps at C.
    octave = midi // 12 - 1
    return PITCH_CLASSES[midi % 12], octave, cents


# O(k) time, O(1) space — k = 12 pitch classes searched by tuple.index
def note_to_frequency(name: str, octave: int) -> float:
    """The inverse, for tests and for tuning displays."""
    try:
        index = PITCH_CLASSES.index(name)
    except ValueError as exc:
        raise ValueError(f"unknown pitch class {name!r}") from exc
    midi = (octave + 1) * 12 + index
    return A4_HZ * 2 ** ((midi - A4_MIDI) / 12)


# O(1) time, O(1) space
def refine_peak(magnitudes, index: int) -> float:
    """Parabolic interpolation around a peak bin, returning a fractional bin.

    An FFT bin is often tens of cents wide in the bass, which is enough to name
    the wrong note. Fitting a parabola through the peak and its two neighbours
    recovers most of that resolution for the cost of three multiplications.
    """
    if index <= 0 or index >= len(magnitudes) - 1:
        return float(index)
    left, centre, right = (
        float(magnitudes[index - 1]),
        float(magnitudes[index]),
        float(magnitudes[index + 1]),
    )
    denominator = left - 2.0 * centre + right
    if denominator == 0:
        return float(index)
    return index + 0.5 * (left - right) / denominator


class SpectralPitchDetector:
    """PitchDetector using the averaged magnitude spectrum."""

    __slots__ = ("_min_prominence", "_max_seconds")

    # O(d) time, O(1) space — d = sys.path entries find_spec searches
    def __init__(
        self,
        min_prominence: float = MIN_PROMINENCE,
        max_seconds: float = DEFAULT_MAX_SECONDS,
    ):
        if not available():
            raise ImportError(
                "numpy and librosa are required for pitch detection; "
                "without them samples carry no note"
            )
        self._min_prominence = min_prominence
        self._max_seconds = max_seconds

    # O(e) time, O(e) space — e = spectrum elements (bins x frames), np.median partitions in linear time
    @staticmethod
    def _body_spectrum(spectrum, np):
        """Average the spectrum over the sound's BODY, skipping the attack.

        Find the loudest frame, skip half of what remains after it, and take
        the MEDIAN of the rest. Median rather than mean because the swept
        frequencies of a drum transient appear in only a minority of frames
        while the settled pitch appears in most. Together these move a
        synthesised kick from a semitone sharp to within a few cents, and they
        degrade gracefully — a sustained tone has no sweep, so skipping half of
        it changes nothing.
        """
        frames = spectrum.shape[1]
        if frames < 4:
            return np.median(spectrum, axis=1)
        energy = spectrum.sum(axis=0)
        peak_frame = int(np.argmax(energy))
        start = peak_frame + max(1, int((frames - peak_frame) * ATTACK_SKIP_FRACTION))
        start = min(start, frames - 2)
        return np.median(spectrum[:, start:], axis=1)

    # O(s) time, O(s) space — s = decoded samples, capped at max_seconds x rate (n_fft is capped at MAX_FFT, so the STFT is linear in s)
    def detect_note(
        self, path: str, max_seconds: float | None = None
    ) -> NoteResult | None:
        """The dominant note, or None when the spectrum has no real peak."""
        import librosa
        import numpy as np

        limit = self._max_seconds if max_seconds is None else max_seconds
        try:
            y, sr = librosa.load(path, sr=None, mono=True, duration=limit)
        except Exception:
            return None
        if y.size < 256 or not np.any(y):
            return None

        n_fft = min(MAX_FFT, 1 << max(8, int(y.size).bit_length() - 1))
        spectrum = np.abs(librosa.stft(y, n_fft=n_fft))
        if spectrum.size == 0:
            return None
        averaged = self._body_spectrum(spectrum, np)
        freqs = librosa.fft_frequencies(sr=sr, n_fft=n_fft)

        band = (freqs >= MIN_HZ) & (freqs <= MAX_HZ)
        if not band.any():
            return None
        candidates = np.where(band)[0]
        peak_index = int(candidates[int(np.argmax(averaged[candidates]))])
        peak = float(averaged[peak_index])
        median = float(np.median(averaged[candidates]))
        if median <= 0 or peak <= 0:
            return None
        prominence = peak / median
        if prominence < self._min_prominence:
            return None  # flat spectrum: naming a note would be inventing one

        refined = refine_peak(averaged, peak_index)
        bin_hz = sr / n_fft
        frequency = float(refined * bin_hz)
        if not (MIN_HZ <= frequency <= MAX_HZ):
            return None

        name, octave, cents = frequency_to_note(frequency)
        # Map prominence onto 0..1 with diminishing returns: 8x is a weak but
        # real peak, 100x is unambiguous.
        confidence = min(1.0, math.log10(prominence / self._min_prominence + 1) / 1.2)
        return NoteResult(name, octave, frequency, cents, confidence)
