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
from collections.abc import Sequence

import codec.layout as L
from audio.ports import (
    AudioConverter,
    ConversionSpec,
    KeyDetector,
    KeyResult,
    NoteResult,
    PitchDetector,
)
from core.errors import InvariantError
from workspace.budget import BudgetCalculator
from workspace.errors import StagingBlockedError
from workspace.limits import Finding, SampleLimitPolicy, Severity
from workspace.naming import pack_slot_name
from workspace.naming import staging_filename as _staging_filename

LOCKFILE = ".lock"
SESSION_PREFIX = "esxstudio-"


# O(1) time, O(1) space
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

    # O(1) time, O(1) space
    def __init__(self, temp_root: str | None = None):
        self._root = temp_root
        self._pid: int | None = None
        self._dir: str | None = None

    # O(1) time, O(1) space
    def _root_dir(self) -> str:
        return self._root if self._root is not None else tempfile.gettempdir()

    @property
    # O(1) time, O(1) space
    def path(self) -> str:
        """The current session directory (created lazily)."""
        if self._dir is None:
            self.create()
        assert self._dir is not None
        return self._dir

    # O(1) time, O(1) space
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

    # O(e + r) time, O(1) space — e = entries in the temp root; r = files removed from orphaned session dirs
    def sweep_orphans(self) -> int:
        """Remove session dirs whose owning PID is no longer alive; return count."""
        root = self._root_dir()
        if not os.path.isdir(root):
            return 0
        removed = 0
        current = os.path.abspath(self._dir) if self._dir else None
        # O(e + r) time, O(1) space — e = entries in the temp root; r = files removed by rmtree across orphans
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

    # O(r) time, O(1) space — r = files in this session's dir (rmtree)
    def clear(self) -> None:
        """Remove this session's converted copies and reset."""
        if self._dir and os.path.isdir(self._dir):
            shutil.rmtree(self._dir, ignore_errors=True)
        self._dir = None
        self._pid = None


class StagingSample:
    """One candidate sample as it moves through the staging workflow."""

    __slots__ = (
        "_source_path",
        "_converted_path",
        "_spec",
        "_key",
        "_note",
        "_duration_s",
    )

    # O(1) time, O(1) space
    def __init__(self, source_path: str):
        self._source_path = source_path
        self._converted_path: str | None = None
        self._spec: ConversionSpec | None = None
        self._key: KeyResult | None = None
        self._note: NoteResult | None = None
        self._duration_s: float | None = None

    @property
    # O(1) time, O(1) space
    def source_path(self) -> str:
        return self._source_path

    @property
    # O(1) time, O(1) space
    def converted_path(self) -> str | None:
        return self._converted_path

    @property
    # O(1) time, O(1) space
    def spec(self) -> ConversionSpec | None:
        return self._spec

    @property
    # O(1) time, O(1) space
    def duration_s(self) -> float | None:
        return self._duration_s

    @property
    # O(1) time, O(1) space
    def key(self) -> KeyResult | None:
        """The detected KeyResult or None (not analysed / not tonal)."""
        return self._key

    @property
    # O(1) time, O(1) space
    def note(self) -> NoteResult | None:
        """The dominant pitch, or None for genuinely broadband material.

        Independent of `key`. A kick drum has a note and no key; a chord has
        both. This is the number you tune a drum to a bassline with.
        """
        return self._note

    @property
    # O(1) time, O(1) space
    def pitch_label(self) -> str:
        """'A1 -3c', or '—' when there is no measurable pitch."""
        if self._note is None:
            return "—"
        return f"{self._note.label} {self._note.cents:+.0f}c"

    # O(L) time, O(L) space — L = characters in the source path
    def staging_filename(self) -> str:
        """The on-disk name carrying the full both-notation name (TDD §5.3)."""
        classical = self._key.classical if self._key else None
        camelot = self._key.camelot if self._key else None
        return _staging_filename(self._source_path, classical, camelot)

    # O(L) time, O(L) space — L = characters in the source path
    def slot_name(self) -> str:
        """The packed 8-byte machine name via the naming policy (TDD §5.3)."""
        camelot = self._key.camelot if self._key else None
        return pack_slot_name(self._source_path, camelot)


class StagingBank:
    """Coordinates staging: probe, convert, analyse, name, and commit samples.

    Depends only on the audio ports and the limit policy, so backends are
    swappable and the whole flow is testable with fakes.
    """

    __slots__ = (
        "_converter",
        "_detector",
        "_pitch",
        "_limits",
        "_session",
        "_samples",
        "_calc",
        "_used",
    )

    # O(1) time, O(1) space
    def __init__(
        self,
        converter: AudioConverter,
        detector: KeyDetector,
        limits: SampleLimitPolicy,
        session: SessionWorkspace,
        pitch: PitchDetector | None = None,
    ):
        self._converter = converter
        self._detector = detector
        self._pitch = pitch
        self._limits = limits
        self._session = session
        self._samples: list[StagingSample] = []
        self._calc = BudgetCalculator()
        # Running byte cost of everything in _samples. Kept in step by add()
        # and clear() — the ONLY two places _samples changes — so add() does
        # not re-sum every staged sample per file (that made a u-file drop
        # O(u·n) in the staging view). If you add a remove/replace path, it
        # MUST adjust _used too, or the fit check drifts from reality.
        self._used = 0

    # O(1) time, O(1) space
    def _used_bytes(self) -> int:
        """Bytes the staged samples will cost (the running total, see __init__)."""
        return self._used

    # O(a) time, O(a) space — a = bytes of this file's audio (probe, convert and detect each pass over it once, the used-bytes total is a running sum)
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
        # O(f) time, O(1) space — f = findings for this candidate
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
            # A key and a note are independent claims. Percussion has no key
            # but almost always has a pitch, and that pitch is what you tune a
            # drum to a track with — so ask for it whether or not a key was
            # found.
            if self._pitch is not None:
                sample._note = self._pitch.detect_note(dest)
        # Rename the converted copy to the both-notation staging filename.
        named = os.path.join(session_dir, sample.staging_filename())
        if named != dest:
            if os.path.exists(named):
                stem, ext = os.path.splitext(sample.staging_filename())
                named = os.path.join(session_dir, f"{stem}-{len(self._samples)}{ext}")
            os.replace(dest, named)
            sample._converted_path = named
        # Same arguments check_sample() already costed above, so this cannot
        # raise here; it is the one place the running total grows.
        self._used += self._calc.cost_bytes(duration_s, spec.rate, spec.channels)
        self._samples.append(sample)
        return sample

    # O(n) time, O(n) space — n = staged samples
    def samples(self) -> tuple[StagingSample, ...]:
        return tuple(self._samples)

    # O(k + P) time, O(P) space — k = assignments (each commit also scans the fixed 384 slots); P = PCM bytes across the assigned samples (bytearray tail writes are amortised)
    def commit_to(
        self,
        bank,
        assignments: Sequence[tuple[StagingSample, int]],
        *,
        reader=None,
    ) -> tuple[int, ...]:
        """Write staged samples into a Bank's slots. Returns the slots filled.

        ALL-OR-NOTHING
            Every sample is decoded and every slot checked BEFORE the first
            byte is committed, so a failure half-way through cannot leave the
            bank with three of five samples in it and a cursor nobody can
            reason about. The bank is mutated only once everything is known
            to be placeable.

        The audio is read through a PcmReader, so the little-endian WAV becomes
        the big-endian form the file stores (see audio.pcm).
        """
        from audio.pcm import WavPcmReader

        pcm_reader = reader or WavPcmReader()
        prepared: list[tuple[int, bytes, int, str]] = []
        # O(s) time, O(s) space — s = 384 sample slots (fixed)
        free = {i for i, slot in enumerate(bank.samples()) if slot.empty}
        budget = bank.pcm_free_bytes()

        # O(k + P) time, O(P) space — k = assignments; P = PCM bytes read across them
        for sample, slot_index in assignments:
            if slot_index not in free:
                raise StagingBlockedError(
                    (
                        Finding(
                            Severity.BLOCK,
                            "slot_unavailable",
                            f"slot {slot_index} is already occupied or already "
                            "claimed by another sample in this batch",
                        ),
                    )
                )
            if sample.converted_path is None or sample.spec is None:
                raise StagingBlockedError(
                    (
                        Finding(
                            Severity.BLOCK,
                            "not_staged",
                            f"{os.path.basename(sample.source_path)} has not been "
                            "converted yet",
                        ),
                    )
                )
            block, source_rate, _channels = pcm_reader.read(
                sample.converted_path, channels=1
            )
            if not isinstance(block, bytes):  # pragma: no cover - channels=1
                raise InvariantError("a mono read must return a single block")
            pcm = block
            # The passthrough converter copies rather than resamples, so the
            # stored rate must be the rate the bytes are actually AT, not the
            # tier that was requested. Writing the requested rate would make
            # the hardware's pitch compensation wrong by exactly the ratio.
            budget -= len(pcm)
            if budget < 0:
                raise StagingBlockedError(
                    (
                        Finding(
                            Severity.BLOCK,
                            "exceeds_capacity",
                            f"the batch needs more than the {bank.pcm_free_bytes():,} B "
                            "free in this bank",
                        ),
                    )
                )
            prepared.append((slot_index, pcm, source_rate, sample.slot_name()))
            free.discard(slot_index)

        # O(k + P) time, O(1) space — k = prepared samples, each commit_sample scanning the fixed 384 slots; P = PCM bytes written across them
        for slot_index, pcm, rate, name in prepared:
            bank.commit_sample(
                slot_index, pcm, stereo=False, sample_rate=rate, name=name
            )
        # O(k) time, O(k) space — k = prepared samples
        return tuple(index for index, _, _, _ in prepared)

    # O(s) time, O(s) space — s = 384 sample slots (fixed, only the 256 mono are scanned)
    def next_free_slots(self, bank, count: int) -> tuple[int, ...]:
        """The first `count` free MONO slots in `bank`, in order."""
        # O(s) time, O(s) space — s = 256 mono sample slots (fixed slice)
        free = [
            i
            for i, slot in enumerate(bank.samples()[: L.NUM_SAMPLES_MONO])
            if slot.empty
        ]
        return tuple(free[:count])

    # O(n + r) time, O(1) space — n = staged samples; r = files in the session dir
    def clear(self) -> None:
        """Reset the staging bank and remove converted copies."""
        self._samples.clear()
        self._used = 0
        self._session.clear()
