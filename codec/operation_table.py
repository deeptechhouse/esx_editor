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
from collections.abc import Iterator, Sequence

EXPECTED_TARGET_COUNT = 313


#: Trie-node key that holds the label ending at that node. Real edges are single
#: characters, so the empty string can never collide with one.
_LABEL_KEY = ""


# O(c) time, O(c) space — c = characters in `label`
def _insert_reversed(root: dict, label: str) -> None:
    """Add `label` to the trie BACK TO FRONT, so a walk from the root reads suffixes."""
    node = root
    # O(c) time, O(c) space — c = characters in the label, at most one new node each
    for ch in reversed(label):
        node = node.setdefault(ch, {})
    node[_LABEL_KEY] = label


# O(T) time, O(T) space — T = total characters across all labels
def _build_suffix_trie(labels) -> dict:
    """A trie of the labels reversed: the index behind longest-suffix matching."""
    root: dict = {}
    # O(T) time, O(T) space — T = total label characters, each inserted once
    for label in labels:
        _insert_reversed(root, label)
    return root


# O(c) time, O(1) space — c = characters in `text`, walking one trie path
def _longest_suffix_label(trie: dict, text: str) -> str | None:
    """The longest label that `text` ends with, or None.

    Same answer as testing labels longest-first with str.endswith: two distinct
    labels of equal length cannot both be suffixes of one string, so "longest"
    is never a tie. The deepest label seen on the walk is the longest suffix.
    """
    node = trie
    best = node.get(_LABEL_KEY)  # an empty label would match every name
    # O(c) time, O(1) space — c = characters of text, read back to front
    for ch in reversed(text):
        node = node.get(ch)
        if node is None:
            break
        best = node.get(_LABEL_KEY, best)
    return best


class MotionTarget:
    """Immutable description of one motion target id."""

    __slots__ = (
        "_target_id",
        "_name",
        "_group",
        "_kind",
        "_option_count",
        "_forced_trig",
    )

    # O(1) time, O(1) space
    def __init__(
        self,
        target_id: int,
        name: str,
        group: str,
        kind: str,
        option_count: int,
        forced_trig: bool,
    ):
        self._target_id = target_id
        self._name = name
        self._group = group
        self._kind = kind
        self._option_count = option_count
        self._forced_trig = forced_trig

    # O(1) time, O(1) space
    @property
    def target_id(self) -> int:
        return self._target_id

    # O(1) time, O(1) space
    @property
    def name(self) -> str:
        return self._name

    # O(1) time, O(1) space
    @property
    def group(self) -> str:
        return self._group

    # O(1) time, O(1) space
    @property
    def kind(self) -> str:
        return self._kind

    # O(1) time, O(1) space
    @property
    def option_count(self) -> int:
        return self._option_count

    # O(1) time, O(1) space
    @property
    def forced_trig(self) -> bool:
        return self._forced_trig


class OperationTable:
    """The full 313-target table, loaded from the research TSVs."""

    __slots__ = ("_by_id",)

    # O(n) time, O(n) space — n = targets (the dict is copied)
    def __init__(self, by_id: dict[int, MotionTarget]):
        self._by_id = dict(by_id)

    # O(C + D) time, O(n + D) space — C = characters in the targets TSV, D = characters in the domains TSV, n = targets parsed
    @classmethod
    def load(cls, research_dir: str) -> OperationTable:
        """Build the table from the TSV sources in `research_dir`."""
        targets_path = os.path.join(research_dir, "motion_operation_table_313.tsv")
        domains_path = os.path.join(research_dir, "motion_target_domains.tsv")

        domains = cls._load_domains(domains_path)  # label(upper) -> (kind,N,trig)
        # Longest label wins, so "FILTER CUTOFF" beats "CUTOFF". A reversed-label
        # trie finds it in one walk of the name, where trying every label against
        # every name (the old sorted-list scan) cost O(targets x labels).
        trie = _build_suffix_trie(domains)

        by_id: dict[int, MotionTarget] = {}
        with open(targets_path, encoding="utf-8") as f:
            # O(C) time, O(n) space — C = characters in the targets TSV (each name walks the label trie once), n = targets stored
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
                label = _longest_suffix_label(trie, upper)
                if label is not None:
                    kind, n_opt, trig = domains[label]
                group = name.split(" ", 1)[0] if " " in name else name
                by_id[tid] = MotionTarget(tid, name, group, kind, n_opt, trig)

        if not by_id:
            from codec.errors import CodecError

            raise CodecError(f"no targets parsed from {targets_path}")
        return cls(by_id)

    # O(D) time, O(D) space — D = characters in the domains TSV
    @staticmethod
    def _load_domains(path: str) -> dict[str, tuple[str, int, bool]]:
        """Return {UPPER_LABEL: (kind, option_count, forced_trig)}."""
        out: dict[str, tuple[str, int, bool]] = {}
        if not os.path.exists(path):
            return out
        with open(path, encoding="utf-8") as f:
            # O(D) time, O(D) space — D = characters in the domains TSV
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

    # O(1) time, O(1) space
    def get(self, target_id: int) -> MotionTarget:
        """Return the target for an id, or raise KeyError if unknown."""
        return self._by_id[target_id]

    # O(1) time, O(1) space
    def get_or_none(self, target_id: int) -> MotionTarget | None:
        return self._by_id.get(target_id)

    # O(1) time, O(1) space
    def is_known(self, target_id: int) -> bool:
        return target_id in self._by_id

    # O(c) time, O(c) space — c = characters in the target name
    def section_of(self, target: MotionTarget) -> str:
        """Hardware grouping: Part Common / Filter / Modulation / Effects."""
        upper = target.name.upper()
        if upper.startswith("FX") or "EFFECT" in upper:
            return "Effects"
        if "FILTER" in upper:
            return "Filter"
        if "MODULATION" in upper or " MOD " in f" {upper} ":
            return "Modulation"
        return "Part Common"

    # O(C) time, O(n) space — C = total characters across target names, n = targets
    def targets_for_part(
        self, part_kind: str, *, hide_unverified_pitch: bool = True
    ) -> Sequence[MotionTarget]:
        """Targets a given part type may automate (TDD §8.5).

        Rules:
          - accent offers only LEVEL
          - audio-in hides Pitch / Start Point / Reverse
          - keyboard already uses Glide (not Pitch) in the 313 table
          - Pitch is hidden by default until the hardware mapping is proven
            (research/CODEC_FINDINGS_LOG.md / TDD §12)
          - FX Edit1/Edit2 are offered on every non-accent part
        """
        prefixes = {
            "drum": ("Drum",),
            "keyboard": ("Keyboard",),
            "stretchslice": ("Stretch", "Slice"),
            "audioin": ("AudioIn",),
            "accent": ("Accent",),
        }.get(part_kind)
        if prefixes is None:
            raise ValueError(f"unknown part kind {part_kind!r}")

        audio_hide = (" PITCH", " START POINT", " REVERSE")
        out: list[MotionTarget] = []
        # O(C) time, O(n) space — C = total characters across target names, n = targets kept
        for t in self._by_id.values():
            if t.target_id == 0:
                continue
            name_u = t.name.upper()
            is_fx = t.name.startswith("FX")
            # O(p) time, O(1) space — p = 2 part prefixes at most
            is_part = any(t.name.startswith(p) for p in prefixes)
            if not (is_part or (is_fx and part_kind != "accent")):
                continue
            if part_kind == "accent" and not name_u.endswith("LEVEL"):
                continue
            # O(h*c) time, O(1) space — h = 3 hidden suffixes, c = characters in the target name
            if part_kind == "audioin" and any(
                name_u.endswith(s.strip()) or s in name_u for s in audio_hide
            ):
                continue
            if hide_unverified_pitch and name_u.endswith("PITCH"):
                continue
            out.append(t)
        return tuple(out)

    # O(1) time, O(1) space
    def __iter__(self) -> Iterator[MotionTarget]:
        return iter(self._by_id.values())

    # O(1) time, O(1) space
    def __len__(self) -> int:
        return len(self._by_id)
