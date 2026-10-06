"""Staging view — drop zone, per-sample readout, live scoreboard (TDD §7 / §10.1)."""

from __future__ import annotations

import os

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from audio.factory import detect_capabilities
from audio.ports import ConversionSpec
from ui.theme import PALETTE
from ui.widgets.budget_meter import BudgetMeter
from workspace.budget import DEFAULT_RATE, TIERS, BudgetCalculator
from workspace.errors import StagingBlockedError
from workspace.limits import SampleLimitPolicy
from workspace.staging import SessionWorkspace, StagingBank


class StagingView(QWidget):
    samplesChanged = Signal()

    # O(e + T) time, O(e + T) space — e = entries swept under the staging temp root (including files of orphaned session dirs); T = 5 rate tiers
    def __init__(
        self,
        parent=None,
        *,
        temp_root: str | None = None,
        bank: StagingBank | None = None,
    ):
        """Render a StagingBank.

        `bank` lets a second view (the wizard's Add-samples screen) render the
        SAME staging model the Staging tab shows, so a drop in one appears in
        the other. Passing nothing creates a fresh session workspace.
        """
        super().__init__(parent)
        self.setAcceptDrops(True)
        # Which backends are live is a property of the machine, not a constant:
        # ffmpeg is an external binary and librosa an optional dependency, so
        # the view asks rather than assumes, and tells the user what it got.
        self.capabilities = detect_capabilities()
        if bank is None:
            session = SessionWorkspace(temp_root=temp_root)
            session.sweep_orphans()
            bank = StagingBank(
                self.capabilities.converter,
                self.capabilities.detector,
                SampleLimitPolicy(),
                session,
                pitch=self.capabilities.pitch,
            )
        self.bank = bank
        self._calc = BudgetCalculator()

        self.meter = BudgetMeter()
        self._tier = QComboBox()
        # O(T) time, O(T) space — T = 5 rate tiers
        for label, rate in TIERS:
            self._tier.addItem(f"{label} ({rate} Hz)", rate)
        self._list = QListWidget()
        self._hint = QLabel(self._hint_text())
        self._hint.setStyleSheet(f"color: {PALETTE.muted};")
        add = QPushButton("Add files…")
        add.clicked.connect(self._pick)
        clear = QPushButton("Clear")
        clear.clicked.connect(self.clear_staging)

        top = QHBoxLayout()
        top.addWidget(QLabel("Tier"))
        top.addWidget(self._tier)
        top.addWidget(add)
        top.addWidget(clear)
        top.addWidget(self.meter, 1)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self._hint)
        layout.addWidget(self._list)

    # O(k) time, O(k) space — k = capability notes joined
    def _hint_text(self) -> str:
        caps = self.capabilities
        formats = "audio files" if caps.can_convert_any_format else "WAV files"
        line = f"Drop {formats} here — originals are never modified."
        return line + "\n" + "  ·  ".join(caps.notes)

    # O(x) time, O(x) space — x = file extensions the converter reads
    def accepts(self, path: str) -> bool:
        """Whether this machine can read `path` at all."""
        converter = self.capabilities.converter
        extensions = getattr(converter, "formats", lambda: ("wav",))()
        return path.lower().rsplit(".", 1)[-1] in extensions

    # O(1) time, O(1) space
    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    # O(u·x + A + n + L) time, O(A + n + L) space — u = files dropped; x = ≤ 11 extensions the converter reads (fixed formats() tuple, audio/ffmpeg_adapter.py); A = audio bytes across the dropped files; n = staged samples after the drop; L = characters across all staged source paths
    def dropEvent(self, event) -> None:  # noqa: N802
        # O(u) time, O(1) space — u = URLs in the drop (consumed lazily)
        self.add_paths(url.toLocalFile() for url in event.mimeData().urls())

    # O(u·x + A + n + L) time, O(u + A + n + L) space — u = files picked; x = ≤ 11 extensions the converter reads (fixed formats() tuple, audio/ffmpeg_adapter.py); A = audio bytes across the picked files; n = staged samples after the pick; L = characters across all staged source paths
    def _pick(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Add samples", "", "WAV audio (*.wav)"
        )
        self.add_paths(paths)

    # O(x + a + n + L) time, O(a + n + L) space — x = ≤ 11 extensions the converter reads (fixed formats() tuple, audio/ffmpeg_adapter.py); a = audio bytes in this file; n = staged samples after the add; L = characters across all staged source paths
    def add_path(self, path: str) -> None:
        self.add_paths((path,))

    # O(u·x + A + n + L) time, O(A + n + L) space — u = paths given; x = ≤ 11 extensions the converter reads (fixed formats() tuple, audio/ffmpeg_adapter.py); A = audio bytes across the paths; n = staged samples after the add; L = characters across all staged source paths
    def add_paths(self, paths) -> None:
        """Stage every path, then redraw and announce ONCE.

        Redrawing after each file made a drop of u files cost u × (whole list)
        — quadratic in the drop size. The list and the meter are rebuilt from
        the model anyway, so one redraw at the end shows exactly the same
        result; files that fail still get their own message box as they come.

        StagingBank.add keeps a running byte total (workspace/staging.py,
        _used), so staging one file no longer rescans the files already
        staged. Together with the single redraw, a drop is linear overall.
        """
        added = False
        # O(u·x + A) time, O(A) space — u = paths given; x = ≤ 11 extensions the converter reads (fixed formats() tuple, audio/ffmpeg_adapter.py); A = audio bytes across the paths
        for path in paths:
            added = self._stage(path) or added
        if added:
            self.reload()
            self.samplesChanged.emit()

    # O(x + a) time, O(a) space — x = ≤ 11 extensions the converter reads (fixed formats() tuple, audio/ffmpeg_adapter.py); a = audio bytes in this file (StagingBank.add keeps a running byte total, so it no longer rescans staged samples)
    def _stage(self, path: str) -> bool:
        """Convert/analyse one file into the staging bank. True if it landed."""
        if not path:
            return False
        if not self.accepts(path):
            supported = ", ".join(
                getattr(self.capabilities.converter, "formats", lambda: ("wav",))()
            )
            QMessageBox.information(
                self,
                "Unsupported format",
                f"This machine can read: {supported}.\n\n"
                + (
                    ""
                    if self.capabilities.can_convert_any_format
                    else "Install ffmpeg (brew install ffmpeg) to read everything else."
                ),
            )
            return False
        rate = int(self._tier.currentData() or DEFAULT_RATE)
        try:
            self.bank.add(path, ConversionSpec(rate, 1))
        except StagingBlockedError as exc:
            QMessageBox.warning(self, "Sample blocked", str(exc))
            return False
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Could not add", str(exc))
            return False
        return True

    # O(f) time, O(1) space — f = converted files removed from the session dir
    def clear_staging(self) -> None:
        self.bank.clear()
        self.reload()
        self.samplesChanged.emit()

    # O(n + L) time, O(n + L) space — n = staged samples; L = total characters across their source paths
    def reload(self) -> None:
        self._list.clear()
        used = 0
        # O(n + L) time, O(n + L) space — n = staged samples; L = total characters across their source paths
        for s in self.bank.samples():
            cost = 0
            if s.duration_s is not None and s.spec is not None:
                cost = self._calc.cost_bytes(s.duration_s, s.spec.rate, s.spec.channels)
                used += cost
            packed = s.slot_name()
            key = s.key.classical if s.key else "no key"
            self._list.addItem(
                f"{os.path.basename(s.source_path)}  →  {s.staging_filename()}  "
                f"[{packed}]  {key} · {s.pitch_label}  {cost:,} B"
            )
        self.meter.set_used(used)
