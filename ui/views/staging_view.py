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

    def _hint_text(self) -> str:
        caps = self.capabilities
        formats = "audio files" if caps.can_convert_any_format else "WAV files"
        line = f"Drop {formats} here — originals are never modified."
        return line + "\n" + "  ·  ".join(caps.notes)

    def accepts(self, path: str) -> bool:
        """Whether this machine can read `path` at all."""
        converter = self.capabilities.converter
        extensions = getattr(converter, "formats", lambda: ("wav",))()
        return path.lower().rsplit(".", 1)[-1] in extensions

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        for url in event.mimeData().urls():
            self.add_path(url.toLocalFile())

    def _pick(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Add samples", "", "WAV audio (*.wav)"
        )
        for p in paths:
            self.add_path(p)

    def add_path(self, path: str) -> None:
        if not path:
            return
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
            packed = s.slot_name()
            key = s.key.classical if s.key else "no key"
            self._list.addItem(
                f"{os.path.basename(s.source_path)}  →  {s.staging_filename()}  "
                f"[{packed}]  {key} · {s.pitch_label}  {cost:,} B"
            )
        self.meter.set_used(used)
