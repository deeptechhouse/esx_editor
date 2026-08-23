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

import os
import shutil
import tempfile
import time

from audio.ports import AudioConverter, ConversionSpec, KeyDetector, KeyResult
from workspace.budget import BudgetCalculator
from workspace.errors import StagingBlockedError
from workspace.limits import SampleLimitPolicy, Severity
from workspace.naming import pack_slot_name
from workspace.naming import staging_filename as _staging_filename

LOCKFILE = ".lock"
SESSION_PREFIX = "esxstudio-"


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, just not ours
    except OSError:
        return False
    return True


class SessionWorkspace:
    """Owns the crash-safe temp session directory and the orphan sweep."""

    __slots__ = ("_root", "_pid", "_dir")

    def __init__(self, temp_root: str | None = None):
        self._root = temp_root
        self._pid: int | None = None
        self._dir: str | None = None

    def _root_dir(self) -> str:
        return self._root if self._root is not None else tempfile.gettempdir()

    @property
    def path(self) -> str:
        """The current session directory (created lazily)."""
        if self._dir is None:
            self.create()
        assert self._dir is not None
        return self._dir

    def create(self) -> str:
        """Create esxstudio-<pid>-<ts>/ with a PID lockfile; return its path."""
        if self._dir is not None and os.path.isdir(self._dir):
            return self._dir
        self._pid = os.getpid()
        ts = time.strftime("%Y%m%d-%H%M%S")
        # Unique even if two sessions start in the same second.
        unique = f"{ts}-{os.getpid()}-{time.time_ns() % 1000000:06d}"
        self._dir = os.path.join(self._root_dir(), f"{SESSION_PREFIX}{unique}")
        os.makedirs(self._dir, exist_ok=True)
        with open(os.path.join(self._dir, LOCKFILE), "w", encoding="utf-8") as f:
            f.write(str(self._pid))
        return self._dir

    def sweep_orphans(self) -> int:
        """Remove session dirs whose owning PID is no longer alive; return count."""
        root = self._root_dir()
        if not os.path.isdir(root):
            return 0
        removed = 0
        current = os.path.abspath(self._dir) if self._dir else None
        for name in os.listdir(root):
            if not name.startswith(SESSION_PREFIX):
                continue
            d = os.path.abspath(os.path.join(root, name))
            if current is not None and d == current:
                continue
            if not os.path.isdir(d):
                continue
            lock = os.path.join(d, LOCKFILE)
            try:
                with open(lock, encoding="utf-8") as f:
                    pid = int(f.read().strip())
                orphan = not _pid_alive(pid)
            except (OSError, ValueError):
                orphan = True
            if orphan:
                shutil.rmtree(d, ignore_errors=True)
                removed += 1
        return removed

    def clear(self) -> None:
        """Remove this session's converted copies and reset."""
        if self._dir and os.path.isdir(self._dir):
            shutil.rmtree(self._dir, ignore_errors=True)
        self._dir = None
        self._pid = None


class StagingSample:
    """One candidate sample as it moves through the staging workflow."""

    __slots__ = ("_source_path", "_converted_path", "_spec", "_key", "_duration_s")

    def __init__(self, source_path: str):
        self._source_path = source_path
        self._converted_path: str | None = None
        self._spec: ConversionSpec | None = None
        self._key: KeyResult | None = None
        self._duration_s: float | None = None

    @property
    def source_path(self) -> str:
        return self._source_path

    @property
    def converted_path(self) -> str | None:
        return self._converted_path

    @property
    def spec(self) -> ConversionSpec | None:
        return self._spec

    @property
    def duration_s(self) -> float | None:
        return self._duration_s

    @property
    def key(self) -> KeyResult | None:
        """The detected KeyResult or None (not analysed / not tonal)."""
        return self._key

    def staging_filename(self) -> str:
        """The on-disk name carrying the full both-notation name (TDD §5.3)."""
        classical = self._key.classical if self._key else None
        camelot = self._key.camelot if self._key else None
        return _staging_filename(self._source_path, classical, camelot)

    def slot_name(self) -> str:
        """The packed 8-byte machine name via the naming policy (TDD §5.3)."""
        camelot = self._key.camelot if self._key else None
        return pack_slot_name(self._source_path, camelot)


class StagingBank:
    """Coordinates staging: probe, convert, analyse, name, and commit samples.

    Depends only on the audio ports and the limit policy, so backends are
    swappable and the whole flow is testable with fakes.
    """

    __slots__ = ("_converter", "_detector", "_limits", "_session", "_samples", "_calc")

    def __init__(
        self,
        converter: AudioConverter,
        detector: KeyDetector,
        limits: SampleLimitPolicy,
        session: SessionWorkspace,
    ):
        self._converter = converter
        self._detector = detector
        self._limits = limits
        self._session = session
        self._samples: list[StagingSample] = []
        self._calc = BudgetCalculator()

    def _used_bytes(self) -> int:
        total = 0
        for s in self._samples:
            if s.duration_s is None or s.spec is None:
                continue
            total += self._calc.cost_bytes(s.duration_s, s.spec.rate, s.spec.channels)
        return total

    def add(self, source_path: str, spec: ConversionSpec) -> StagingSample:
        """Run drop->probe->convert->analyse->rename for one file.

        Raises StagingBlockedError if a BLOCK-level limit is hit. The original
        file is never modified; the converted copy lives in the session dir.
        """
        duration_s, _src_rate, _src_ch = self._converter.probe_duration(source_path)
        findings, analyse_ok = self._limits.check_sample(
            source_path,
            duration_s,
            spec.channels,
            spec.rate,
            used_bytes=self._used_bytes(),
        )
        if any(f.level == Severity.BLOCK for f in findings):
            raise StagingBlockedError(findings)

        session_dir = self._session.create()
        dest = os.path.join(session_dir, os.path.basename(source_path))
        if os.path.exists(dest):
            stem, ext = os.path.splitext(os.path.basename(source_path))
            dest = os.path.join(session_dir, f"{stem}-{len(self._samples)}{ext}")
        self._converter.convert(source_path, dest, spec)

        sample = StagingSample(source_path)
        sample._converted_path = dest
        sample._spec = spec
        sample._duration_s = duration_s
        if analyse_ok:
            sample._key = self._detector.detect(dest)
        # Rename the converted copy to the both-notation staging filename.
        named = os.path.join(session_dir, sample.staging_filename())
        if named != dest:
            if os.path.exists(named):
                stem, ext = os.path.splitext(sample.staging_filename())
                named = os.path.join(session_dir, f"{stem}-{len(self._samples)}{ext}")
            os.replace(dest, named)
            sample._converted_path = named
        self._samples.append(sample)
        return sample

    def samples(self) -> tuple[StagingSample, ...]:
        return tuple(self._samples)

    def clear(self) -> None:
        """Reset the staging bank and remove converted copies."""
        self._samples.clear()
        self._session.clear()
