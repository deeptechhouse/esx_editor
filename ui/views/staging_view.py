"""Staging view — drop zone, per-sample readout, live scoreboard (TDD §7 / §10.1)."""

from __future__ import annotations

import os

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QPushButton,
    QComboBox, QFileDialog, QMessageBox,
)

from audio.passthrough import WavPassthroughConverter, NullKeyDetector
from audio.ports import ConversionSpec
from ui.theme import PALETTE
from ui.widgets.budget_meter import BudgetMeter
from workspace.budget import BudgetCalculator, TIERS, DEFAULT_RATE
from workspace.errors import StagingBlockedError
from workspace.limits import SampleLimitPolicy
from workspace.staging import SessionWorkspace, StagingBank


class StagingView(QWidget):
    samplesChanged = Signal()

    def __init__(self, parent=None, *, temp_root: str | None = None,
                 bank: StagingBank | None = None):
        """Render a StagingBank.

        `bank` lets a second view (the wizard's Add-samples screen) render the
        SAME staging model the Staging tab shows, so a drop in one appears in
        the other. Passing nothing creates a fresh session workspace.
        """
        super().__init__(parent)
        self.setAcceptDrops(True)
        if bank is None:
            session = SessionWorkspace(temp_root=temp_root)
            session.sweep_orphans()
            bank = StagingBank(
                WavPassthroughConverter(), NullKeyDetector(),
                SampleLimitPolicy(), session)
        self.bank = bank
        self._calc = BudgetCalculator()

        self.meter = BudgetMeter()
        self._tier = QComboBox()
        for label, rate in TIERS:
            self._tier.addItem(f"{label} ({rate} Hz)", rate)
        self._list = QListWidget()
        self._hint = QLabel("Drop WAV files here — originals are never modified.")
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

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        for url in event.mimeData().urls():
            self.add_path(url.toLocalFile())

    def _pick(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Add samples", "", "WAV audio (*.wav)")
        for p in paths:
            self.add_path(p)

    def add_path(self, path: str) -> None:
        if not path:
            return
        if not path.lower().endswith(".wav"):
            QMessageBox.information(
                self, "WAV only for now",
                "The passthrough converter reads WAV headers. "
                "Other formats wait on the ffmpeg adapter.")
            return
        rate = int(self._tier.currentData() or DEFAULT_RATE)
        try:
            self.bank.add(path, ConversionSpec(rate, 1))
        except StagingBlockedError as exc:
            QMessageBox.warning(self, "Sample blocked", str(exc))
            return
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Could not add", str(exc))
            return
        self.reload()
        self.samplesChanged.emit()

    def clear_staging(self) -> None:
        self.bank.clear()
        self.reload()
        self.samplesChanged.emit()

    def reload(self) -> None:
        self._list.clear()
        used = 0
        for s in self.bank.samples():
            cost = 0
            if s.duration_s is not None and s.spec is not None:
                cost = self._calc.cost_bytes(s.duration_s, s.spec.rate, s.spec.channels)
                used += cost
            key = s.slot_name()
            self._list.addItem(
                f"{os.path.basename(s.source_path)}  →  {s.staging_filename()}  "
                f"[{key}]  {cost:,} B")
        self.meter.set_used(used)
