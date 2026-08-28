"""
The real audio adapters: ffmpeg conversion and librosa key detection.

Both backends are OPTIONAL — ffmpeg is an external binary and librosa will not
build everywhere — so every test here skips rather than fails when its backend
is missing. That is the same contract the app honours at runtime: a machine
without them degrades to WAV-only and no key detection, and says so.
"""

from __future__ import annotations

import math
import os
import subprocess
import wave

import pytest

from audio import factory
from audio.ffmpeg_adapter import FfmpegConverter, FfmpegUnavailable
from audio.ffmpeg_adapter import available as ffmpeg_available
from audio.librosa_adapter import (
    LibrosaKeyDetector,
    camelot_for,
    chroma_flatness,
    classical_for,
    estimate_from_chroma,
)
from audio.librosa_adapter import available as librosa_available
from audio.passthrough import NullKeyDetector, WavPassthroughConverter
from audio.ports import AudioConverter, ConversionSpec, KeyDetector
from core.errors import InvariantError
from workspace.naming import CAMELOT

needs_ffmpeg = pytest.mark.skipif(
    not ffmpeg_available(), reason="ffmpeg/ffprobe not installed"
)
needs_librosa = pytest.mark.skipif(
    not librosa_available(), reason="librosa not installed"
)


@pytest.fixture
def source_wav(tmp_path) -> str:
    """One second of a stereo sawtooth at 48 kHz — needs real resampling."""
    import array

    path = str(tmp_path / "source.wav")
    frames = array.array(
        "h", [int(12000 * ((i % 400) / 400 * 2 - 1)) for i in range(48000 * 2)]
    )
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(frames.tobytes())
    return path


# -- the ports contract -------------------------------------------------------
def test_every_adapter_satisfies_its_port() -> None:
    """Structural typing is the whole point: no inheritance, still swappable."""
    assert isinstance(WavPassthroughConverter(), AudioConverter)
    assert isinstance(NullKeyDetector(), KeyDetector)
    if ffmpeg_available():
        assert isinstance(FfmpegConverter(), AudioConverter)
    if librosa_available():
        assert isinstance(LibrosaKeyDetector(), KeyDetector)


def test_factory_reports_what_this_machine_can_do() -> None:
    factory.detect_capabilities.cache_clear()
    caps = factory.detect_capabilities()
    assert len(caps.notes) == 3, "converter, key detector, pitch detector"
    assert all(note.strip() for note in caps.notes)
    assert caps.can_convert_any_format is ffmpeg_available()
    assert caps.can_detect_key is librosa_available()
    assert caps.can_detect_note is (caps.pitch is not None)
    # Cached: probing costs an ffmpeg subprocess and a librosa import.
    assert factory.detect_capabilities() is caps


def test_factory_falls_back_when_a_backend_is_missing(monkeypatch) -> None:
    from audio import ffmpeg_adapter, librosa_adapter

    monkeypatch.setattr(ffmpeg_adapter, "available", lambda: False)
    monkeypatch.setattr(librosa_adapter, "available", lambda: False)
    factory.detect_capabilities.cache_clear()
    try:
        caps = factory.detect_capabilities()
        assert isinstance(caps.converter, WavPassthroughConverter)
        assert isinstance(caps.detector, NullKeyDetector)
        assert not caps.can_convert_any_format and not caps.can_detect_key
        assert any("ffmpeg" in note for note in caps.notes)
    finally:
        factory.detect_capabilities.cache_clear()


# -- ffmpeg -------------------------------------------------------------------
@needs_ffmpeg
def test_ffmpeg_probes_from_the_header_only(source_wav) -> None:
    duration, rate, channels = FfmpegConverter().probe_duration(source_wav)
    assert abs(duration - 1.0) < 0.01
    assert rate == 48000 and channels == 2


@needs_ffmpeg
def test_ffmpeg_resamples_and_folds(source_wav, tmp_path) -> None:
    dst = str(tmp_path / "out.wav")
    FfmpegConverter().convert(source_wav, dst, ConversionSpec(44100, 1))
    with wave.open(dst, "rb") as w:
        assert w.getnchannels() == 1
        assert w.getframerate() == 44100
        assert w.getsampwidth() == 2, "the file stores 16-bit"
        assert abs(w.getnframes() - 44100) < 100


@needs_ffmpeg
def test_ffmpeg_never_modifies_the_original(source_wav, tmp_path) -> None:
    before = open(source_wav, "rb").read()
    FfmpegConverter().convert(
        source_wav, str(tmp_path / "o.wav"), ConversionSpec(22050, 1)
    )
    assert open(source_wav, "rb").read() == before


@needs_ffmpeg
def test_ffmpeg_refuses_to_convert_a_file_onto_itself(source_wav) -> None:
    with pytest.raises(InvariantError, match="onto itself"):
        FfmpegConverter().convert(source_wav, source_wav, ConversionSpec(44100, 1))


@needs_ffmpeg
@pytest.mark.parametrize("container", ["mp3", "flac", "aiff", "ogg"])
def test_ffmpeg_reads_every_container_it_advertises(
    source_wav, tmp_path, container
) -> None:
    encoded = str(tmp_path / f"enc.{container}")
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            source_wav,
            encoded,
        ],
        check=True,
    )
    converter = FfmpegConverter()
    assert container in converter.formats()
    duration, _rate, _channels = converter.probe_duration(encoded)
    assert abs(duration - 1.0) < 0.1

    out = str(tmp_path / f"from_{container}.wav")
    converter.convert(encoded, out, ConversionSpec(32000, 1))
    with wave.open(out, "rb") as w:
        assert w.getframerate() == 32000 and w.getnchannels() == 1


@needs_ffmpeg
def test_ffmpeg_reports_which_resampler_it_actually_has() -> None:
    """soxr is a build option; claiming it when absent would be a lie."""
    assert FfmpegConverter().resampler_engine in ("soxr", "swr")


@needs_ffmpeg
def test_ffmpeg_refuses_a_missing_file() -> None:
    with pytest.raises(InvariantError, match="does not exist"):
        FfmpegConverter().probe_duration("/nowhere/at/all.wav")


@needs_ffmpeg
def test_ffmpeg_refuses_a_file_with_no_audio_stream(tmp_path) -> None:
    junk = tmp_path / "junk.wav"
    junk.write_bytes(b"not audio at all, not even close")
    with pytest.raises(InvariantError):
        FfmpegConverter().probe_duration(str(junk))


@needs_ffmpeg
def test_ffmpeg_refuses_an_impossible_channel_count(source_wav, tmp_path) -> None:
    with pytest.raises(InvariantError, match="1 or 2"):
        FfmpegConverter().convert(
            source_wav, str(tmp_path / "x.wav"), ConversionSpec(44100, 5)
        )


def test_ffmpeg_adapter_refuses_an_explicit_path_that_is_not_executable() -> None:
    """Fail at construction, not three calls later inside a subprocess."""
    with pytest.raises(FfmpegUnavailable, match="not an executable"):
        FfmpegConverter(ffprobe="/definitely/not/here")


def test_ffmpeg_adapter_refuses_when_the_binary_is_absent(monkeypatch) -> None:
    from audio import ffmpeg_adapter

    monkeypatch.setattr(ffmpeg_adapter, "_which", lambda _name: None)
    with pytest.raises(FfmpegUnavailable, match="required for non-WAV import"):
        FfmpegConverter()


# -- the Camelot derivation (no librosa needed) -------------------------------
def test_camelot_derivation_matches_the_naming_table() -> None:
    """All 24 positions, derived from the circle of fifths rather than typed."""
    for pitch_class in range(12):
        for minor in (False, True):
            code = camelot_for(pitch_class, minor)
            spelling = classical_for(pitch_class, minor)
            assert code in CAMELOT, code
            assert spelling in CAMELOT[code], (code, spelling, CAMELOT[code])


def test_a_minor_sits_beside_c_major_on_the_wheel() -> None:
    """The relative-major rule: getting it wrong is a minor third out."""
    assert camelot_for(9, True) == "8A"  # A minor
    assert camelot_for(0, False) == "8B"  # C major
    assert camelot_for(0, True) == "5A"  # C minor, NOT 8A


def test_estimate_prefers_the_profile_it_was_given() -> None:
    from audio.librosa_adapter import MAJOR_PROFILE, MINOR_PROFILE

    root, minor, margin = estimate_from_chroma(list(MAJOR_PROFILE))
    assert (root, minor) == (0, False) and margin > 0
    root, minor, margin = estimate_from_chroma(list(MINOR_PROFILE))
    assert (root, minor) == (0, True) and margin > 0


def test_estimate_refuses_a_wrong_sized_vector() -> None:
    with pytest.raises(ValueError, match="12 bins"):
        estimate_from_chroma([1.0] * 11)


def test_chroma_flatness_separates_uniform_from_peaked() -> None:
    """The gate that actually rejects noise."""
    assert chroma_flatness([1.0] * 12) == pytest.approx(1.0)
    peaked = [0.01] * 12
    peaked[0] = 1.0
    assert chroma_flatness(peaked) < 0.5
    assert chroma_flatness([0.0] * 12) == 1.0


# -- librosa ------------------------------------------------------------------
def _write_progression(path: str, pitch_class: int, minor: bool, rate: int = 22050):
    """A I-IV-V-I triad progression in a known key, written as a WAV."""
    import array

    third = 3 if minor else 4
    duration = 6.0
    total = int(rate * duration)
    segment = total // 4
    out = [0.0] * total
    for index, step in enumerate([0, 5, 7, 0]):
        base = 60 + pitch_class + step
        for note in (base, base + third, base + 7):
            freq = 440.0 * 2 ** ((note - 69) / 12)
            for i in range(segment):
                t = i / rate
                value = sum(
                    math.sin(2 * math.pi * freq * h * t) / h for h in (1, 2, 3, 4)
                )
                out[index * segment + i] += value * 0.15
    peak = max(abs(v) for v in out) or 1.0
    samples = array.array("h", [int(v / peak * 26000) for v in out])
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples.tobytes())
    return path


@needs_librosa
@pytest.mark.slow
@pytest.mark.parametrize(
    ("pitch_class", "minor", "expected"),
    [(0, False, "C"), (9, True, "Am"), (5, False, "F"), (7, True, "Gm")],
)
def test_librosa_identifies_a_known_key(tmp_path, pitch_class, minor, expected) -> None:
    path = _write_progression(str(tmp_path / "prog.wav"), pitch_class, minor)
    result = LibrosaKeyDetector().detect(path)
    assert result is not None, f"failed to detect {expected}"
    assert result.classical == expected
    assert result.camelot == camelot_for(pitch_class, minor)
    assert 0.0 < result.confidence <= 1.0


@needs_librosa
def test_librosa_returns_none_for_silence(tmp_path) -> None:
    path = str(tmp_path / "silent.wav")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(22050)
        w.writeframes(b"\x00\x00" * 22050)
    assert LibrosaKeyDetector().detect(path) is None


@needs_librosa
@pytest.mark.slow
def test_librosa_returns_none_for_noise(tmp_path) -> None:
    """A guessed key would be baked into a permanent 8-character slot name."""
    import array
    import random

    rng = random.Random(7)
    samples = array.array("h", [rng.randint(-9000, 9000) for _ in range(22050 * 3)])
    path = str(tmp_path / "noise.wav")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(22050)
        w.writeframes(samples.tobytes())
    assert LibrosaKeyDetector().detect(path) is None


@needs_librosa
def test_librosa_returns_none_for_an_undecodable_file(tmp_path) -> None:
    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"nope")
    assert LibrosaKeyDetector().detect(str(bad)) is None


def test_librosa_detector_refuses_to_construct_when_absent(monkeypatch) -> None:
    from audio import librosa_adapter

    monkeypatch.setattr(librosa_adapter, "available", lambda: False)
    with pytest.raises(ImportError, match="librosa"):
        librosa_adapter.LibrosaKeyDetector()


# -- staging with the real adapters -------------------------------------------
@needs_ffmpeg
def test_staging_accepts_a_non_wav_when_ffmpeg_is_present(tmp_path, source_wav) -> None:
    from workspace.limits import SampleLimitPolicy
    from workspace.staging import SessionWorkspace, StagingBank

    encoded = str(tmp_path / "loop.mp3")
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            source_wav,
            encoded,
        ],
        check=True,
    )
    session = SessionWorkspace(temp_root=str(tmp_path))
    staging = StagingBank(
        FfmpegConverter(), NullKeyDetector(), SampleLimitPolicy(), session
    )
    sample = staging.add(encoded, ConversionSpec(44100, 1))
    assert sample.duration_s is not None and sample.duration_s > 0.5
    assert sample.converted_path and os.path.exists(sample.converted_path)
    with wave.open(sample.converted_path, "rb") as w:
        assert w.getframerate() == 44100 and w.getnchannels() == 1
    assert os.path.exists(encoded), "the original is never modified"


@needs_librosa
def test_librosa_refuses_a_clip_shorter_than_its_analysis_window(tmp_path) -> None:
    """A 15 ms one-shot has no key; analysing it would only produce a guess."""
    import array

    path = str(tmp_path / "blip.wav")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(22050)
        w.writeframes(array.array("h", [9000, -9000] * 150).tobytes())
    assert LibrosaKeyDetector().detect(path) is None


# -- dominant-note detection --------------------------------------------------
def test_note_conversion_is_exact_at_the_anchors() -> None:
    """A4 = 440 Hz is the definition; everything else follows from it."""
    from audio.pitch import A4_HZ, frequency_to_note, note_to_frequency

    name, octave, cents = frequency_to_note(A4_HZ)
    assert (name, octave) == ("A", 4)
    assert abs(cents) < 1e-9
    assert note_to_frequency("A", 4) == pytest.approx(440.0)
    assert note_to_frequency("C", 4) == pytest.approx(261.626, abs=0.01)
    assert note_to_frequency("A", 1) == pytest.approx(55.0, abs=0.001)


@pytest.mark.parametrize(
    ("name", "octave"),
    [("C", 1), ("F#", 2), ("A", 4), ("D#", 0), ("B", 6)],
)
def test_note_conversion_round_trips(name, octave) -> None:
    from audio.pitch import frequency_to_note, note_to_frequency

    got_name, got_octave, cents = frequency_to_note(note_to_frequency(name, octave))
    assert (got_name, got_octave) == (name, octave)
    assert abs(cents) < 0.01


def test_cents_report_the_deviation_rather_than_rounding_it() -> None:
    """A sound 30 cents sharp of A is A +30, not silently A or A#."""
    from audio.pitch import frequency_to_note, note_to_frequency

    sharp = note_to_frequency("A", 4) * 2 ** (30 / 1200)
    name, octave, cents = frequency_to_note(sharp)
    assert (name, octave) == ("A", 4)
    assert cents == pytest.approx(30.0, abs=0.5)


def test_note_conversion_refuses_a_non_positive_frequency() -> None:
    from audio.pitch import frequency_to_note

    for bad in (0.0, -1.0):
        with pytest.raises(ValueError, match="positive"):
            frequency_to_note(bad)


def test_parabolic_refinement_is_a_no_op_at_the_edges() -> None:
    from audio.pitch import refine_peak

    assert refine_peak([1.0, 2.0, 3.0], 0) == 0.0
    assert refine_peak([1.0, 2.0, 3.0], 2) == 2.0
    # A symmetric peak stays put; an asymmetric one shifts toward the taller side.
    assert refine_peak([1.0, 2.0, 1.0], 1) == pytest.approx(1.0)
    assert refine_peak([1.0, 2.0, 1.5], 1) > 1.0


def _write_tone(path, frequency, seconds=1.0, rate=44100):
    import array
    import math

    frames = int(rate * seconds)
    samples = array.array(
        "h",
        [
            int(20000 * math.sin(2 * math.pi * frequency * i / rate))
            for i in range(frames)
        ],
    )
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples.tobytes())
    return str(path)


@needs_librosa
@pytest.mark.parametrize(
    ("frequency", "expected"),
    [(440.0, "A4"), (55.0, "A1"), (82.41, "E2"), (146.83, "D3")],
)
def test_pitch_detector_names_a_pure_tone(tmp_path, frequency, expected) -> None:
    from audio.pitch import SpectralPitchDetector

    path = _write_tone(tmp_path / "tone.wav", frequency)
    result = SpectralPitchDetector().detect_note(path)
    assert result is not None
    assert result.label == expected
    assert abs(result.cents) < 25
    assert result.frequency == pytest.approx(frequency, rel=0.02)


@needs_librosa
def test_pitch_detector_returns_nothing_for_broadband_noise(tmp_path) -> None:
    """White noise genuinely has no dominant pitch — naming one would invent it."""
    import array
    import random

    from audio.pitch import SpectralPitchDetector

    rng = random.Random(3)
    samples = array.array("h", [rng.randint(-12000, 12000) for _ in range(44100)])
    path = str(tmp_path / "noise.wav")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(samples.tobytes())
    assert SpectralPitchDetector().detect_note(path) is None


@needs_librosa
def test_pitch_detector_returns_nothing_for_silence(tmp_path) -> None:
    from audio.pitch import SpectralPitchDetector

    path = _write_tone(tmp_path / "quiet.wav", 440.0)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(b"\x00\x00" * 44100)
    assert SpectralPitchDetector().detect_note(path) is None


def test_pitch_detector_refuses_to_construct_without_numpy(monkeypatch) -> None:
    from audio import pitch as pitch_module

    monkeypatch.setattr(pitch_module, "available", lambda: False)
    with pytest.raises(ImportError, match="numpy"):
        pitch_module.SpectralPitchDetector()


@needs_librosa
def test_staged_samples_carry_a_note_even_with_no_key(tmp_path) -> None:
    """The point of the feature: a drum has no key but does have a pitch."""
    from audio.pitch import SpectralPitchDetector
    from workspace.limits import SampleLimitPolicy
    from workspace.staging import SessionWorkspace, StagingBank

    path = _write_tone(tmp_path / "tone55.wav", 55.0)
    staging = StagingBank(
        WavPassthroughConverter(),
        NullKeyDetector(),
        SampleLimitPolicy(),
        SessionWorkspace(temp_root=str(tmp_path)),
        pitch=SpectralPitchDetector(),
    )
    sample = staging.add(path, ConversionSpec(44100, 1))
    assert sample.key is None, "NullKeyDetector never guesses a key"
    assert sample.note is not None, "but the pitch is still measurable"
    assert sample.note.label == "A1"
    assert sample.pitch_label.startswith("A1")


def test_a_sample_with_no_pitch_detector_reports_no_note(tmp_path) -> None:
    from workspace.limits import SampleLimitPolicy
    from workspace.staging import SessionWorkspace, StagingBank

    path = _write_tone(tmp_path / "t.wav", 440.0, seconds=0.2)
    staging = StagingBank(
        WavPassthroughConverter(),
        NullKeyDetector(),
        SampleLimitPolicy(),
        SessionWorkspace(temp_root=str(tmp_path)),
    )
    sample = staging.add(path, ConversionSpec(44100, 1))
    assert sample.note is None
    assert sample.pitch_label == "—"
