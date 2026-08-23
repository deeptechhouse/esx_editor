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
    assert len(caps.notes) == 2
    assert all(note.strip() for note in caps.notes)
    assert caps.can_convert_any_format is ffmpeg_available()
    assert caps.can_detect_key is librosa_available()
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
