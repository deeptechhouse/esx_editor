"""
audio.passthrough — WAV-only probe + copy, and a silent key detector.

The ffmpeg / librosa adapters land later. Staging and the wizard still need
something that satisfies the ports so WAV drops work today: we read duration
from the header (no decode) and copy the original into the session dir.
Resampling to the chosen tier is recorded on ConversionSpec for the scoreboard
but not applied until a real converter is wired (TDD §7.3 still holds: we
never mutate the original, and we never re-encode from a downgraded copy
because we have not encoded yet).
"""

from __future__ import annotations

import shutil
import wave

from audio.ports import ConversionSpec, KeyResult


class WavPassthroughConverter:
    """AudioConverter for .wav files: header probe + byte-copy."""

    def probe_duration(self, src_path: str) -> tuple[float, int, int]:
        """Read duration/rate/channels from the header only.

        Backend failures are translated to ValueError. That translation is the
        adapter's job: callers hold the AudioConverter port, not the `wave`
        module, so they cannot be expected to catch `wave.Error` — and an
        untranslated one escapes the UI's handler and takes the app down when
        somebody drops a file with a .wav extension that is not a WAV.
        """
        try:
            with wave.open(src_path, "rb") as w:
                rate = w.getframerate()
                if rate <= 0:
                    raise ValueError(f"wav {src_path!r} has non-positive rate")
                return (w.getnframes() / rate, rate, w.getnchannels())
        except (wave.Error, EOFError) as exc:
            # EOFError, not just wave.Error: a TRUNCATED wav (a partial
            # download, a file still being written) hits the end of the stream
            # mid-chunk and the wave module raises EOFError, which is not a
            # subclass of wave.Error. Catching only wave.Error left that path
            # crashing the app exactly as the original bug did.
            raise ValueError(
                f"{src_path!r} is not a readable WAV: {exc or type(exc).__name__}"
            ) from exc

    def formats(self) -> tuple[str, ...]:
        """Container extensions this adapter can read: WAV only."""
        return ("wav",)

    def convert(self, src_path: str, dst_path: str, spec: ConversionSpec) -> None:
        shutil.copy2(src_path, dst_path)


class NullKeyDetector:
    """KeyDetector that never guesses — percussion-safe (TDD §5.1 / §6.5)."""

    def detect(self, path: str, max_seconds: float | None = None) -> KeyResult | None:
        return None
