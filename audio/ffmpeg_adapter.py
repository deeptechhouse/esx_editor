"""
audio.ffmpeg_adapter — the v1 AudioConverter (TDD §5.1, §5.2).

WHY A SUBPROCESS AND NOT A WHEEL
    ffmpeg reads every format the hardware might be fed and is already
    installed. Shelling out keeps the dependency out of the Python environment
    entirely — `codec/` and `core/` stay stdlib-only, and a machine without
    ffmpeg degrades to the WAV passthrough rather than failing to import.

WHAT THE CONVERSION ACTUALLY DOES (TDD §5.2)
    - Resamples with soxr at very-high quality. Naive decimation would alias,
      which is exactly what would make the "quality tier" feature sound broken.
    - Reduces to 16-bit with triangular dither. Truncating instead adds
      correlated quantisation distortion, worst on the quiet material this
      sampler is often fed.
    - Strips every non-audio chunk. An inherited `smpl` chunk makes the
      hardware silently redefine where the sample ENDS (manual p.88), so a
      loop point somebody left in a download would truncate the sample on
      import with no error anywhere.
    - Never touches the source file.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

from audio.ports import ConversionSpec
from core.errors import InvariantError

#: Resampler settings, best first. soxr is ffmpeg's highest-quality engine but
#: it is a BUILD OPTION (--enable-libsoxr) that many distributions omit — the
#: Homebrew build on this machine does not have it. Asking for an unavailable
#: engine does not degrade gracefully: ffmpeg fails the whole conversion with
#: "Requested resampling engine is unavailable", so the engine is probed once
#: at construction rather than assumed.
#:
#: swr with filter_size=256 is the fallback. It is genuinely good — well past
#: audibility for this sampler's material — but it is not soxr, and
#: `resampler_engine` reports which is in use so the UI can say so rather than
#: claim a quality it did not deliver.
RESAMPLER_SOXR = "aresample=resampler=soxr:precision=28:dither_method=triangular"
RESAMPLER_SWR = "aresample=resampler=swr:filter_size=256:dither_method=triangular"

#: How long a single conversion may run before it is treated as hung.
TIMEOUT_SECONDS = 300


class FfmpegUnavailable(InvariantError):
    """Raised when the ffmpeg/ffprobe binaries cannot be found (see `_search_path`)."""


#: Where Homebrew puts binaries (Intel, then Apple Silicon). Searched AFTER the
#: inherited PATH, never before it, so a user's own PATH choice still wins.
#: THE TRAP: an app launched from Finder/Dock does not get the shell's PATH —
#: launchd hands it /usr/bin:/bin:/usr/sbin:/sbin — so `shutil.which("ffmpeg")`
#: misses /usr/local/bin/ffmpeg and the app quietly drops to WAV-only import
#: even though ffmpeg is installed (seen 2026-10-06 building the .app).
HOMEBREW_BIN_DIRS = ("/usr/local/bin", "/opt/homebrew/bin")


# O(d) time, O(d) space — d = directories on the search path (a handful)
def _search_path() -> str:
    """The directories ffmpeg is looked for in, best first.

    1. `bin/` inside a frozen build (PyInstaller sets `sys._MEIPASS`), so the
       packaged .app uses the ffmpeg it was shipped with and needs nothing
       installed on the machine.
    2. The inherited PATH — a dev checkout behaves exactly as before.
    3. Homebrew's locations, for a GUI launch that did not inherit PATH.
    """
    dirs: list[str] = []
    bundle = getattr(sys, "_MEIPASS", None)  # set only inside a frozen app
    if bundle:
        dirs.append(os.path.join(bundle, "bin"))
    dirs.extend(os.environ.get("PATH", "").split(os.pathsep))
    dirs.extend(HOMEBREW_BIN_DIRS)
    # O(d) time, O(d) space — d = directories collected above (empties dropped)
    return os.pathsep.join(d for d in dirs if d)


# O(d) time, O(d) space — d = directories on the search path
def _which(name: str) -> str | None:
    return shutil.which(name, path=_search_path())


def available() -> bool:
    """True when both binaries this adapter needs are present."""
    return _which("ffmpeg") is not None and _which("ffprobe") is not None


def _resolve(explicit: str | None, name: str) -> str:
    """Resolve a binary path, or refuse at construction.

    An explicit path is checked for existence rather than just truthiness: a
    caller who passes a wrong path deserves a clear error here, not a confusing
    subprocess failure three calls later.
    """
    path = explicit or _which(name)
    if not path:
        raise FfmpegUnavailable(
            f"{name} is required for non-WAV import; install it "
            "(brew install ffmpeg) or stay on the WAV passthrough"
        )
    if explicit and not (os.path.isfile(path) and os.access(path, os.X_OK)):
        raise FfmpegUnavailable(f"{path!r} is not an executable {name}")
    return path


class FfmpegConverter:
    """AudioConverter backed by the ffmpeg/ffprobe binaries."""

    __slots__ = ("_ffmpeg", "_ffprobe", "_timeout", "_engine")

    def __init__(
        self,
        ffmpeg: str | None = None,
        ffprobe: str | None = None,
        timeout: int = TIMEOUT_SECONDS,
    ):
        self._ffmpeg = _resolve(ffmpeg, "ffmpeg")
        self._ffprobe = _resolve(ffprobe, "ffprobe")
        self._timeout = timeout
        self._engine = self._detect_engine()

    @property
    def resampler_engine(self) -> str:
        """'soxr' or 'swr' — which resampler this build actually has.

        Surfaced so the UI can be honest about conversion quality instead of
        advertising soxr on a build that does not include it.
        """
        return self._engine

    def _detect_engine(self) -> str:
        """Ask the binary which resamplers it was built with.

        --enable-libsoxr in the build configuration is authoritative and costs
        one cheap invocation, versus a trial conversion that needs a temp file.
        """
        try:
            proc = subprocess.run(
                [self._ffmpeg, "-hide_banner", "-buildconf"],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return "swr"
        return "soxr" if "--enable-libsoxr" in (proc.stdout or "") else "swr"

    # -- probing ------------------------------------------------------------
    def probe_duration(self, src_path: str) -> tuple[float, int, int]:
        """Return (duration_seconds, source_rate, channels) from the header.

        Header only — no decode. That is what makes the budget scoreboard
        instant for a folder of long files (TDD §6.1).
        """
        if not os.path.exists(src_path):
            raise InvariantError(f"{src_path!r} does not exist")
        out = self._run(
            [
                self._ffprobe,
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=sample_rate,channels,duration:format=duration",
                "-of",
                "json",
                src_path,
            ]
        )
        try:
            data = json.loads(out)
        except json.JSONDecodeError as exc:
            raise InvariantError(
                f"ffprobe returned unparseable JSON for {src_path!r}"
            ) from exc

        streams = data.get("streams") or []
        if not streams:
            raise InvariantError(f"{src_path!r} contains no audio stream")
        stream = streams[0]
        rate = int(stream.get("sample_rate") or 0)
        channels = int(stream.get("channels") or 0)
        duration = stream.get("duration") or (data.get("format") or {}).get("duration")
        if rate <= 0 or channels <= 0:
            raise InvariantError(
                f"{src_path!r} reports rate={rate} channels={channels}; unusable"
            )
        if duration is None:
            raise InvariantError(
                f"{src_path!r} has no duration in its header; a streaming format "
                "would have to be decoded to measure, which the budget must not do"
            )
        return (float(duration), rate, channels)

    def formats(self) -> tuple[str, ...]:
        """Container extensions worth offering in a file dialog."""
        return (
            "wav",
            "aif",
            "aiff",
            "flac",
            "mp3",
            "m4a",
            "aac",
            "ogg",
            "opus",
            "wma",
            "caf",
        )

    # -- conversion ---------------------------------------------------------
    def convert(self, src_path: str, dst_path: str, spec: ConversionSpec) -> None:
        """Convert src -> dst at `spec`. The original is never modified."""
        if not os.path.exists(src_path):
            raise InvariantError(f"{src_path!r} does not exist")
        if os.path.abspath(src_path) == os.path.abspath(dst_path):
            raise InvariantError(
                "refusing to convert a file onto itself; originals are never modified"
            )
        if spec.channels not in (1, 2):
            raise InvariantError(f"channels must be 1 or 2, got {spec.channels}")

        args = [
            self._ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-i",
            src_path,
            "-map",
            "0:a:0",
            "-ac",
            str(spec.channels),
            "-ar",
            str(spec.rate),
            "-af",
            RESAMPLER_SOXR if self._engine == "soxr" else RESAMPLER_SWR,
            "-c:a",
            "pcm_s16le",
            "-sample_fmt",
            "s16",
        ]
        if spec.strip_smpl:
            # -map_metadata -1 drops tags; write_bext/other chunk writers stay
            # off by default, so the output carries fmt + data and nothing else.
            args += ["-map_metadata", "-1", "-fflags", "+bitexact"]
        args += ["-f", "wav", dst_path]

        self._run(args)
        if not os.path.exists(dst_path) or os.path.getsize(dst_path) == 0:
            raise InvariantError(f"ffmpeg produced no output for {src_path!r}")

    # -- internals ----------------------------------------------------------
    def _run(self, args: list[str]) -> str:
        try:
            proc = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise InvariantError(
                f"{os.path.basename(args[0])} timed out after {self._timeout}s"
            ) from exc
        except OSError as exc:
            raise InvariantError(f"could not run {args[0]!r}: {exc}") from exc
        if proc.returncode != 0:
            detail = (proc.stderr or "").strip().splitlines()
            message = detail[-1] if detail else f"exit {proc.returncode}"
            raise InvariantError(f"{os.path.basename(args[0])} failed: {message}")
        return proc.stdout
