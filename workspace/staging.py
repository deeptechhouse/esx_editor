"""
workspace.staging — the staging bank and its crash-safe temp lifecycle (TDD §07).

WORKFLOW (TDD §7.1)
    drop -> probe -> convert -> analyse -> rename -> display -> assign -> commit
    Originals are never modified; converted copies live in a session temp dir.

TEMP LIFECYCLE MUST SURVIVE A CRASH (TDD §7.2)
    "Delete on close" does nothing if the process is killed. Design:
      - session dir  esxstudio-<pid>-<timestamp>/  under the OS temp dir
      - a lockfile inside it holding the owning PID
      - orphan sweep at startup removes any session dir whose PID is dead
      - explicit "Clear" removes the current session's converted copies

RE-ENCODE FROM SOURCE ALWAYS (TDD §7.3)
    Changing a sample's tier re-encodes from the ORIGINAL file, never from an
    already-downgraded copy, so tiers are freely revisable with no generation loss.
"""

from __future__ import annotations

from typing import Sequence

from audio.ports import AudioConverter, KeyDetector, ConversionSpec
from workspace.limits import SampleLimitPolicy


class SessionWorkspace:
    """Owns the crash-safe temp session directory and the orphan sweep."""

    __slots__ = ("_root", "_pid", "_dir")

    def __init__(self, temp_root: str | None = None):
        self._root = temp_root
        self._pid = None
        self._dir = None

    @property
    def path(self) -> str:
        """The current session directory (created lazily)."""
        raise NotImplementedError

    def create(self) -> str:
        """Create esxstudio-<pid>-<ts>/ with a PID lockfile; return its path."""
        raise NotImplementedError

    def sweep_orphans(self) -> int:
        """Remove session dirs whose owning PID is no longer alive; return count."""
        raise NotImplementedError

    def clear(self) -> None:
        """Remove this session's converted copies and reset."""
        raise NotImplementedError


class StagingSample:
    """One candidate sample as it moves through the staging workflow."""

    __slots__ = ("_source_path", "_converted_path", "_spec",
                 "_key", "_duration_s")

    def __init__(self, source_path: str):
        self._source_path = source_path
        self._converted_path = None
        self._spec = None
        self._key = None
        self._duration_s = None

    @property
    def source_path(self) -> str:
        return self._source_path

    @property
    def key(self):
        """The detected KeyResult or None (not analysed / not tonal)."""
        return self._key

    def staging_filename(self) -> str:
        """The on-disk name carrying the full both-notation name (TDD §5.3)."""
        raise NotImplementedError

    def slot_name(self) -> str:
        """The packed 8-byte machine name via the naming policy (TDD §5.3)."""
        raise NotImplementedError


class StagingBank:
    """Coordinates staging: probe, convert, analyse, name, and commit samples.

    Depends only on the audio ports and the limit policy, so backends are
    swappable and the whole flow is testable with fakes.
    """

    __slots__ = ("_converter", "_detector", "_limits", "_session", "_samples")

    def __init__(self, converter: AudioConverter, detector: KeyDetector,
                 limits: SampleLimitPolicy, session: SessionWorkspace):
        self._converter = converter
        self._detector = detector
        self._limits = limits
        self._session = session
        self._samples: list[StagingSample] = []

    def add(self, source_path: str, spec: ConversionSpec) -> StagingSample:
        """Run drop->probe->convert->analyse->rename for one file.

        Raises workspace errors if a BLOCK-level limit is hit and not overridden.
        """
        raise NotImplementedError

    def samples(self) -> tuple[StagingSample, ...]:
        return tuple(self._samples)

    def clear(self) -> None:
        """Reset the staging bank and remove converted copies."""
        raise NotImplementedError
