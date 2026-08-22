"""
codec.operation_table — the 313 motion targets and their value domains.

SOURCES (loaded at construction, never hardcoded)
    research/motion_operation_table_313.tsv  — "<id>\\t<name>" per line
    research/motion_target_domains.tsv        — dest/label -> kind, range, smooth

DOMAIN RESOLUTION (WF2: best-effort; finalised in the motion-editor WF)
    The 313 table names targets like "Drum4 Filter Cutoff"; the domain table
    keys by the trailing parameter label ("FILTER CUTOFF"). Each target is
    matched to a domain by longest-suffix match on its uppercased name. Targets
    with no confident match default to a continuous 0-127 domain. `is_known`
    and `get` (all the codec.validator needs) are exact regardless.
"""

from __future__ import annotations

import os
from typing import Iterator, Sequence

EXPECTED_TARGET_COUNT = 313


class MotionTarget:
    """Immutable description of one motion target id."""

    __slots__ = ("_target_id", "_name", "_group", "_kind",
                 "_option_count", "_forced_trig")

    def __init__(self, target_id: int, name: str, group: str, kind: str,
                 option_count: int, forced_trig: bool):
        self._target_id = target_id
        self._name = name
        self._group = group
        self._kind = kind
        self._option_count = option_count
        self._forced_trig = forced_trig

    @property
    def target_id(self) -> int:
        return self._target_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def group(self) -> str:
        return self._group

    @property
    def kind(self) -> str:
        return self._kind

    @property
    def option_count(self) -> int:
        return self._option_count

    @property
    def forced_trig(self) -> bool:
        return self._forced_trig


class OperationTable:
    """The full 313-target table, loaded from the research TSVs."""

    __slots__ = ("_by_id",)

    def __init__(self, by_id: dict[int, MotionTarget]):
        self._by_id = dict(by_id)

    @classmethod
    def load(cls, research_dir: str) -> "OperationTable":
        """Build the table from the TSV sources in `research_dir`."""
        targets_path = os.path.join(research_dir, "motion_operation_table_313.tsv")
        domains_path = os.path.join(research_dir, "motion_target_domains.tsv")

        domains = cls._load_domains(domains_path)   # label(upper) -> (kind,N,trig)
        # Match longest labels first so "FILTER CUTOFF" wins over "CUTOFF".
        labels_by_len = sorted(domains, key=len, reverse=True)

        by_id: dict[int, MotionTarget] = {}
        with open(targets_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                if not line or line.startswith("#") or "\t" not in line:
                    continue
                sid, name = line.split("\t", 1)
                try:
                    tid = int(sid)
                except ValueError:
                    continue
                upper = name.upper()
                kind, n_opt, trig = "continuous", 0, False
                for label in labels_by_len:
                    if upper.endswith(label):
                        kind, n_opt, trig = domains[label]
                        break
                group = name.split(" ", 1)[0] if " " in name else name
                by_id[tid] = MotionTarget(tid, name, group, kind, n_opt, trig)

        if not by_id:
            from codec.errors import CodecError
            raise CodecError(f"no targets parsed from {targets_path}")
        return cls(by_id)

    @staticmethod
    def _load_domains(path: str) -> dict[str, tuple[str, int, bool]]:
        """Return {UPPER_LABEL: (kind, option_count, forced_trig)}."""
        out: dict[str, tuple[str, int, bool]] = {}
        if not os.path.exists(path):
            return out
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                if not line or line.startswith("#"):
                    continue
                cols = line.split("\t")
                if len(cols) < 7:
                    continue
                _dest, label, kind, mn, mx, _labels, smooth = cols[:7]
                try:
                    lo, hi = int(mn), int(mx)
                except ValueError:
                    lo, hi = 0, 0
                if kind in ("boolean", "enum"):
                    n_opt = hi - lo + 1
                else:
                    n_opt = 0
                forced = smooth.strip().upper() == "FORCED_TRIG"
                # Key by the human label (e.g. "FILTER CUTOFF") for suffix match.
                out[label.upper()] = (kind, n_opt, forced)
        return out

    def get(self, target_id: int) -> MotionTarget:
        """Return the target for an id, or raise KeyError if unknown."""
        return self._by_id[target_id]

    def get_or_none(self, target_id: int) -> MotionTarget | None:
        return self._by_id.get(target_id)

    def is_known(self, target_id: int) -> bool:
        return target_id in self._by_id

    def targets_for_part(self, part_kind: str) -> Sequence[MotionTarget]:
        """Targets a given part type may automate (best-effort filter by name).

        Full picker rules (accent=LEVEL only, audio-in hides Pitch/Start/Reverse,
        keyboard swaps Pitch for Glide) are finalised in the motion-editor WF.
        """
        raise NotImplementedError

    def __iter__(self) -> Iterator[MotionTarget]:
        return iter(self._by_id.values())

    def __len__(self) -> int:
        return len(self._by_id)
