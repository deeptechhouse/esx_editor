"""
workspace.card — what is on a SmartMedia card, and whether the next bank fits.

WHY THIS IS SEPARATE FROM THE BUDGET
    Two limits are easy to confuse and the app previously showed only one:

      sample RAM   25,165,824 B (285 s mono)  a property of the MACHINE.
                                              A bank past it will not load.
      card         4-128 MB (manual p.6435)   a property of the CARD.
                                              Holds several banks.

    The budget meter measures the first. This measures the second. A 128 MB
    card holds roughly four full-size banks (a maximum bank is ~26.3 MiB: a
    2.31 MiB fixed structure plus up to 24 MiB of PCM), or many more part-full
    ones.

CHEAP BY DESIGN
    Scanning reads each bank's sample-area header — twelve bytes at a known
    offset — rather than parsing the file. Listing a card of 100 MB banks
    should not cost 100 MB of reads.
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass

import codec.layout as L

#: Capacities the ESX-1 accepts (manual p.6435, "4 MB~128 MB").
MIN_CARD_BYTES = 4 * 1024 * 1024
MAX_CARD_BYTES = 128 * 1024 * 1024

#: Every .esx carries this much structure before any audio.
FIXED_BYTES = L.ADDR_SAMPLE_DATA

#: The largest bank the machine can produce: fixed structure + full RAM + trailer.
MAX_BANK_BYTES = FIXED_BYTES + L.MAX_SAMPLE_BYTES + L.PCM_TRAILER_LEN


@dataclass(frozen=True)
class BankFile:
    """One .esx on a card, described without parsing it."""

    path: str
    size: int
    num_mono: int
    num_stereo: int
    pcm_used: int
    readable: bool = True

    @property
    def name(self) -> str:
        return os.path.basename(self.path)

    @property
    def samples(self) -> int:
        return self.num_mono + self.num_stereo

    @property
    def ram_fraction(self) -> float:
        """How much of the machine's sample RAM this bank would occupy."""
        return self.pcm_used / L.MAX_SAMPLE_BYTES if L.MAX_SAMPLE_BYTES else 0.0


def describe_bank(path: str) -> BankFile:
    """Read one bank's headline numbers from its header only.

    A file too short or without the sample-area magic comes back with
    `readable=False` rather than raising: a card can contain anything, and a
    listing must not fail because one file is junk.
    """
    size = os.path.getsize(path)
    if size < L.SIZE_FILE_MIN:
        return BankFile(path, size, 0, 0, 0, readable=False)
    try:
        with open(path, "rb") as handle:
            handle.seek(L.ADDR_MAGIC_2)
            magic = handle.read(16)
            if not magic.startswith(L.MAGIC_HEAD) or L.MAGIC_2_TAIL not in magic:
                return BankFile(path, size, 0, 0, 0, readable=False)
            handle.seek(L.ADDR_NUM_MONO_SAMPLES)
            mono, stereo, cursor = struct.unpack(">III", handle.read(12))
    except OSError:
        return BankFile(path, size, 0, 0, 0, readable=False)
    return BankFile(path, size, mono, stereo, cursor)


@dataclass(frozen=True)
class CardContents:
    """Every bank in a directory, plus how full the card is."""

    path: str
    banks: tuple[BankFile, ...]
    capacity: int

    @property
    def used(self) -> int:
        """Bytes the banks occupy. Not total disk usage — banks only."""
        return sum(b.size for b in self.banks)

    @property
    def free(self) -> int:
        return max(0, self.capacity - self.used)

    @property
    def fraction(self) -> float:
        return self.used / self.capacity if self.capacity else 0.0

    def fits(self, size: int) -> bool:
        return size <= self.free

    def room_for_full_banks(self) -> int:
        """How many more maximum-size banks would fit."""
        return self.free // MAX_BANK_BYTES

    def summary(self) -> str:
        mib = 1024 * 1024
        return (
            f"{len(self.banks)} bank(s), {self.used / mib:.1f} MiB used of "
            f"{self.capacity / mib:.0f} MiB, {self.free / mib:.1f} MiB free "
            f"(room for {self.room_for_full_banks()} more full-size bank(s))"
        )


def scan(directory: str, capacity: int = MAX_CARD_BYTES) -> CardContents:
    """List every .esx in `directory`, newest layout first by name.

    `capacity` defaults to the largest card the ESX-1 accepts. Pass the real
    card size when it is known — free space is only meaningful against it.
    """
    banks: list[BankFile] = []
    try:
        entries = sorted(os.listdir(directory))
    except OSError:
        entries = []
    for entry in entries:
        if not entry.lower().endswith(".esx"):
            continue
        full = os.path.join(directory, entry)
        if os.path.isfile(full):
            banks.append(describe_bank(full))
    return CardContents(directory, tuple(banks), capacity)


def detect_capacity(directory: str) -> int:
    """Real capacity of the filesystem holding `directory`, clamped to a card.

    A card reports its own size, which beats assuming 128 MB. Anything larger
    than a SmartMedia card means the directory is not on one — a scratch folder
    on the internal disk, say — so the reported figure is capped rather than
    implying a 2 TB "card".
    """
    try:
        stats = os.statvfs(directory)
    except OSError:
        return MAX_CARD_BYTES
    total = stats.f_blocks * stats.f_frsize
    if total <= 0:
        return MAX_CARD_BYTES
    return min(total, MAX_CARD_BYTES)
