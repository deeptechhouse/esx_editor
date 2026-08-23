"""
ui.wizard.pages — the eleven guided-setup screens (TDD §09).

EVERY SCREEN IS SKIPPABLE
    The wizard exists because the ESX-1's two-line display makes these decisions
    opaque, not because the app needs the answers. So `isComplete()` is True on
    every page: Next is never blocked, and an experienced user can walk straight
    to Validate & write. Each page states the decision AND the reasoning, which
    is why the explanatory labels are as long as they are.

HONESTY RULES CARRIED THROUGH FROM THE CODEC
    Where the format is not decoded, the screen says so instead of showing a
    plausible number: pattern tempo/length/last-step are shown as header hex
    (offsets unproven), key detection reports "none" because NullKeyDetector
    never guesses, and slot commit is described as pending rather than faked.
"""

from __future__ import annotations

import os

from PySide6.QtWidgets import (
    QWizardPage, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QRadioButton,
    QButtonGroup, QCheckBox, QComboBox, QLineEdit, QListWidget, QTableWidget,
    QTableWidgetItem, QFileDialog, QPlainTextEdit,
)

from codec.errors import CodecError
from ui.theme import PALETTE, TYPE
from ui.views.staging_view import StagingView
from ui.widgets.budget_meter import BudgetMeter
from workspace.budget import BudgetCalculator, CAPACITY
from workspace.naming import CAMELOT, pack_slot_name
import codec.layout as L


NAME_STYLES = (("short  (Am / C)", "short"),
               ("long   (Amin / Cmaj)", "long"),
               ("camelot only (8A)", "camelot"))


def _muted(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setWordWrap(True)
    lab.setStyleSheet(f"color: {PALETTE.muted};")
    return lab


def _lcd(text: str = "") -> QLabel:
    lab = QLabel(text)
    lab.setWordWrap(True)
    lab.setStyleSheet(f"color: {PALETTE.lcd};")
    return lab


def _mono(widget: QPlainTextEdit) -> QPlainTextEdit:
    widget.setReadOnly(True)
    widget.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
    widget.setStyleSheet(
        f"font-family: {TYPE.lcd}; font-size: {TYPE.size_lcd}px; "
        f"color: {PALETTE.lcd}; background: {PALETTE.lcd_bg};")
    return widget


class SkippablePage(QWizardPage):
    """Base page: titled, self-building, and never blocking Next."""

    TITLE = ""
    SUBTITLE = ""

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self._ctx = ctx
        self.setTitle(self.TITLE)
        self.setSubTitle(self.SUBTITLE)
        self.layout = QVBoxLayout(self)
        self.build()

    # -- hooks subclasses fill ---------------------------------------------
    def build(self) -> None:
        """Create the widgets. Called once, from __init__."""

    def refresh(self) -> None:
        """Re-read the model. Called every time the page is shown."""

    # -- QWizardPage contract ----------------------------------------------
    def isComplete(self) -> bool:  # noqa: N802
        """Always True — every screen is skippable (TDD §09)."""
        return True

    def initializePage(self) -> None:  # noqa: N802
        self.refresh()

    def reason(self, text: str) -> None:
        """Add the 'why this screen exists' paragraph."""
        self.layout.addWidget(_muted(text))


# 1 ---------------------------------------------------------------------------
class StartPage(SkippablePage):
    TITLE = "1 · Start"
    SUBTITLE = "New bank from the blank template, or open an existing .esx."

    def build(self) -> None:
        self.reason(
            "'New' loads a blank bank a real ESX-1 wrote, then edits it — five "
            "regions of the format are still undecoded, so synthesising a bank "
            "from zeros risks a file the hardware rejects.")
        self.new_radio = QRadioButton("New bank from template")
        self.open_radio = QRadioButton("Open an existing .esx")
        self.new_radio.setChecked(True)
        self._group = QButtonGroup(self)
        self._group.addButton(self.new_radio)
        self._group.addButton(self.open_radio)
        self.apply_button = QPushButton("Create blank bank")
        self.apply_button.clicked.connect(self.create_new)
        self.browse_button = QPushButton("Choose file…")
        self.browse_button.clicked.connect(self.browse)
        self.status = _lcd("")
        row = QHBoxLayout()
        row.addWidget(self.apply_button)
        row.addWidget(self.browse_button)
        row.addStretch(1)
        self.layout.addWidget(self.new_radio)
        self.layout.addWidget(self.open_radio)
        self.layout.addLayout(row)
        self.layout.addWidget(self.status)
        self.layout.addStretch(1)

    def create_new(self) -> None:
        try:
            self._ctx.session.new_bank()
        except CodecError as exc:
            self.status.setText(f"blank template unavailable: {exc}")
            return
        self._ctx.notify_changed()
        self.refresh()

    def browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open ESX bank", "", "ESX banks (*.esx);;All files (*)")
        if path:
            self.open_file(path)

    def open_file(self, path: str) -> None:
        """Open `path` into the session. Reports failure in-page, not a dialog."""
        try:
            self._ctx.session.open_path(path)
        except (CodecError, OSError) as exc:
            self.status.setText(f"open failed: {exc}")
            return
        self.open_radio.setChecked(True)
        self._ctx.notify_changed()
        self.refresh()

    def refresh(self) -> None:
        session = self._ctx.session
        if not session.is_open:
            self.status.setText("No bank open yet — you can still skip ahead.")
            return
        where = session.path or "untitled (from template)"
        self.status.setText(f"Open: {where}")


# 2 ---------------------------------------------------------------------------
class CardCheckPage(SkippablePage):
    TITLE = "2 · Card check"
    SUBTITLE = "Back up the card before anything is written."

    def build(self) -> None:
        self.reason(
            "Writing is already defensive — the app serialises to a temp file, "
            "re-reads it to verify the bytes, replaces atomically, and keeps the "
            "previous version as <name>.esx.bak. A card-level copy still protects "
            "you from the things software cannot: a bad card, a yanked reader.")
        self.confirm = QCheckBox("I have copied the card contents somewhere safe")
        self.status = _lcd("")
        self.layout.addWidget(self.confirm)
        self.layout.addWidget(self.status)
        self.layout.addStretch(1)

    def refresh(self) -> None:
        path = self._ctx.session.path
        if path:
            self.status.setText(
                f"This bank came from {path}\nA backup will be kept at {path}.bak")
        else:
            self.status.setText(
                "No source file yet — Validate & write will ask where to save.")


# 3 ---------------------------------------------------------------------------
class AddSamplesPage(SkippablePage):
    TITLE = "3 · Add samples"
    SUBTITLE = "Drop files; the scoreboard fills as they land."

    def build(self) -> None:
        self.reason(
            "Originals are never modified. Each file is copied into a session "
            "workspace and costed against the 25 MB budget from its header — no "
            "re-encoding is needed to know what a configuration will cost.")
        self.staging = StagingView(bank=self._ctx.staging_bank)
        self._ctx.adopt_staging_bank(self.staging.bank)
        self.layout.addWidget(self.staging, 1)

    def refresh(self) -> None:
        self.staging.reload()


# 4 ---------------------------------------------------------------------------
class QualityBudgetPage(SkippablePage):
    TITLE = "4 · Quality budget"
    SUBTITLE = "What the staged set costs against 25,165,824 bytes."

    def build(self) -> None:
        self.reason(
            "Order of sacrifice: trim silence first, then fold stereo to mono, "
            "and only then drop the sample rate — rate is the one that cannot be "
            "undone later. Nothing here is applied automatically; this screen "
            "proposes, you decide.")
        self._calc = BudgetCalculator()
        self.meter = BudgetMeter()
        self.summary = _lcd("")
        self.proposal = _muted("")
        self.layout.addWidget(self.meter)
        self.layout.addWidget(self.summary)
        self.layout.addWidget(self.proposal)
        self.layout.addStretch(1)

    def staged_cost(self) -> int:
        """Total bytes the staged set would occupy at its chosen tiers."""
        total = 0
        for s in self._ctx.staged_samples():
            if s.duration_s is not None and s.spec is not None:
                total += self._calc.cost_bytes(
                    s.duration_s, s.spec.rate, s.spec.channels)
        return total

    def proposals(self) -> tuple[str, ...]:
        """Ordered, display-only suggestions for getting back under capacity."""
        cost = self.staged_cost()
        if cost <= CAPACITY:
            return ()
        over = cost - CAPACITY
        stereo = [s for s in self._ctx.staged_samples()
                  if s.spec is not None and s.spec.channels > 1]
        out = [f"Over capacity by {over:,} B ({over / CAPACITY:.0%} of the card)."]
        out.append("1. Trim leading/trailing silence — free, lossless, reversible.")
        if stereo:
            out.append(f"2. Fold {len(stereo)} stereo sample(s) to mono — halves "
                       "their cost and frees the 128-slot stereo pool.")
        out.append(f"{3 if stereo else 2}. Drop the tier (44.1 → 32 → 24 kHz) — "
                   "cheapest in bytes, but resampling cannot be undone.")
        return tuple(out)

    def refresh(self) -> None:
        cost = self.staged_cost()
        self.meter.set_used(min(cost, CAPACITY))
        n = len(self._ctx.staged_samples())
        pct = (cost / CAPACITY * 100) if CAPACITY else 0.0
        self.summary.setText(
            f"{n} staged sample(s) — {cost:,} B of {CAPACITY:,} B ({pct:.1f}%). "
            f"{max(CAPACITY - cost, 0):,} B free.")
        props = self.proposals()
        self.proposal.setText(
            "\n".join(props) if props
            else "Within budget — the CD-quality default (44.1 kHz) stands.")


# 5 ---------------------------------------------------------------------------
class KeyAnalysisPage(SkippablePage):
    TITLE = "5 · Key analysis"
    SUBTITLE = "Confirm detected keys; suppress them for percussive material."

    def build(self) -> None:
        self.reason(
            "The adapter shipped today is NullKeyDetector: it returns no key, "
            "ever. Returning nothing is a legitimate result — a kick drum has no "
            "key, and a guessed one would be baked into the 8-character slot name "
            "permanently. Real detection lands with the librosa adapter.")
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["sample", "camelot", "classical"])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.status = _lcd("")
        self.layout.addWidget(self.status)
        self.layout.addWidget(self.table, 1)

    def refresh(self) -> None:
        staged = self._ctx.staged_samples()
        detected = sum(1 for s in staged if s.key is not None)
        self.status.setText(
            f"{len(staged)} staged, {detected} with a key. "
            "The passthrough detector reports none by design.")
        self.table.setRowCount(len(staged))
        for row, s in enumerate(staged):
            key = s.key
            vals = (os.path.basename(s.source_path),
                    key.camelot if key else "— none —",
                    key.classical if key else "— none —")
            for col, text in enumerate(vals):
                self.table.setItem(row, col, QTableWidgetItem(text))
        self.table.resizeColumnsToContents()


# 6 ---------------------------------------------------------------------------
class NamingPage(SkippablePage):
    TITLE = "6 · Naming"
    SUBTITLE = "Slot-name policy with a live 8-character preview."

    def build(self) -> None:
        self.reason(
            "The machine slot name is exactly 8 characters, so the policy is a "
            "real trade-off: the Camelot prefix costs 3 of them. The on-disk "
            "staging filename is unlimited and carries both notations, so nothing "
            "is lost — only the hardware display is constrained.")
        self.style = QComboBox()
        for label, value in NAME_STYLES:
            self.style.addItem(label, value)
        self.style.currentIndexChanged.connect(self.refresh)
        self.camelot = QComboBox()
        self.camelot.addItem("no key detected", None)
        for code in sorted(CAMELOT, key=lambda c: (c[-1], int(c[:-1]))):
            self.camelot.addItem(code, code)
        self.camelot.currentIndexChanged.connect(self.refresh)
        self.example = QLineEdit("my_bassline_take3")
        self.example.textChanged.connect(self.refresh)
        self.preview = _mono(QPlainTextEdit())
        self.preview.setMaximumHeight(150)

        row = QHBoxLayout()
        row.addWidget(QLabel("Style"))
        row.addWidget(self.style)
        row.addWidget(QLabel("Key"))
        row.addWidget(self.camelot)
        row.addStretch(1)
        self.layout.addLayout(row)
        self.layout.addWidget(QLabel("Example filename"))
        self.layout.addWidget(self.example)
        self.layout.addWidget(QLabel("8-character preview"))
        self.layout.addWidget(self.preview)
        self.layout.addStretch(1)

    def current_style(self) -> str:
        return self.style.currentData() or "short"

    def preview_lines(self) -> list[str]:
        """One '<source> -> |PACKED  |' line per staged sample, plus the example."""
        style = self.current_style()
        chosen = self.camelot.currentData()
        rows = [(self.example.text() or "example", chosen)]
        for s in self._ctx.staged_samples():
            key = s.key
            rows.append((os.path.basename(s.source_path),
                         key.camelot if key else chosen))
        lines = []
        for name, code in rows:
            try:
                packed = pack_slot_name(name, code, style)
            except ValueError as exc:
                packed = f"<{exc}>"
            lines.append(f"{name[:28]:<28} -> |{packed}|")
        return lines

    def refresh(self) -> None:
        self.preview.setPlainText("\n".join(self.preview_lines()))


# 7 ---------------------------------------------------------------------------
class SlotAssignmentPage(SkippablePage):
    TITLE = "7 · Slot assignment"
    SUBTITLE = "Mono and stereo pools are separate tables in the file."

    def build(self) -> None:
        self.reason(
            "Mono samples occupy 256 slots, stereo 128 — separate header tables "
            "at separate offsets, so a stereo file cannot borrow a free mono slot. "
            "Committing PCM into a slot lands with the staging workflow "
            "(Bank.commit_sample still raises NotImplementedError); this screen "
            "shows what would be written, and nothing is written yet.")
        self.pools = _lcd("")
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["staged file", "packed name", "pool"])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.layout.addWidget(self.pools)
        self.layout.addWidget(self.table, 1)

    def free_slots(self) -> tuple[int, int]:
        """(free mono, free stereo) in the open bank; full pools when none open."""
        bank = self._ctx.session.bank
        if bank is None:
            return L.NUM_SAMPLES_MONO, L.NUM_SAMPLES_STEREO
        samples = bank.samples()
        mono = sum(1 for s in samples[:L.NUM_SAMPLES_MONO] if s.empty)
        stereo = sum(1 for s in samples[L.NUM_SAMPLES_MONO:] if s.empty)
        return mono, stereo

    def refresh(self) -> None:
        mono, stereo = self.free_slots()
        self.pools.setText(
            f"free mono {mono}/{L.NUM_SAMPLES_MONO}   "
            f"free stereo {stereo}/{L.NUM_SAMPLES_STEREO}   "
            "— commit-to-slot lands with the staging workflow.")
        staged = self._ctx.staged_samples()
        self.table.setRowCount(len(staged))
        for row, s in enumerate(staged):
            channels = s.spec.channels if s.spec is not None else 1
            vals = (os.path.basename(s.source_path), s.slot_name(),
                    "stereo" if channels > 1 else "mono")
            for col, text in enumerate(vals):
                self.table.setItem(row, col, QTableWidgetItem(text))
        self.table.resizeColumnsToContents()


# 8 ---------------------------------------------------------------------------
class PartSetupPage(SkippablePage):
    TITLE = "8 · Part setup"
    SUBTITLE = "The 16 parts of pattern 000."

    def build(self) -> None:
        self.reason(
            "Which sample a part plays lives at an unproven offset inside the "
            "part chunk — Part.sample_number raises NotImplementedError rather "
            "than return a guess, so this screen shows each part's kind and "
            "index only. Assignment arrives when a hardware diff pins the field.")
        self.status = _lcd("")
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["#", "kind", "index", "chunk B", "first 8 B"])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.layout.addWidget(self.status)
        self.layout.addWidget(self.table, 1)

    def refresh(self) -> None:
        pat = self._ctx.first_pattern()
        self.table.setRowCount(0)
        if pat is None:
            self.status.setText("No bank open — nothing to show.")
            return
        parts = pat.parts()
        self.status.setText(
            f"Pattern 000 '{pat.name}' — {len(parts)} parts, raw and undecoded.")
        self.table.setRowCount(len(parts))
        for row, part in enumerate(parts):
            raw = part.to_bytes()
            vals = (str(row), part.kind, str(part.index),
                    str(len(raw)), raw[:8].hex(" "))
            for col, text in enumerate(vals):
                self.table.setItem(row, col, QTableWidgetItem(text))
        self.table.resizeColumnsToContents()


# 9 ---------------------------------------------------------------------------
class PatternBasicsPage(SkippablePage):
    TITLE = "9 · Pattern basics"
    SUBTITLE = "Name now; tempo, length and last step when their offsets are proven."

    def build(self) -> None:
        self.reason(
            "The 16-byte pattern header carries tempo, length, beat, last step, "
            "swing and roll — but which byte holds which is not settled, and "
            "PatternHeader.tempo raises NotImplementedError. Writing a wrong byte "
            "into a pattern is exactly the corruption this project exists to "
            "avoid, so the header is shown as hex until a hardware diff pins it.")
        self.name = QLineEdit()
        self.name.setMaxLength(L.PATTERN_NAME_LEN)
        self.name.editingFinished.connect(self.apply_name)
        self.header = _mono(QPlainTextEdit())
        self.header.setMaximumHeight(70)
        self.motion = _lcd("")
        row = QHBoxLayout()
        row.addWidget(QLabel("Name"))
        row.addWidget(self.name)
        row.addStretch(1)
        self.layout.addLayout(row)
        self.layout.addWidget(QLabel("Header (16 B, undecoded)"))
        self.layout.addWidget(self.header)
        self.layout.addWidget(self.motion)
        self.layout.addStretch(1)

    def apply_name(self) -> None:
        pat = self._ctx.first_pattern()
        if pat is None:
            return
        if pat.name == self.name.text():
            return
        pat.set_name(self.name.text())
        self._ctx.session.mark_dirty()
        self._ctx.notify_changed()

    def refresh(self) -> None:
        pat = self._ctx.first_pattern()
        if pat is None:
            self.name.setText("")
            self.header.setPlainText("")
            self.motion.setText("No bank open — nothing to show.")
            return
        self.name.setText(pat.name)
        self.header.setPlainText(pat.header.to_bytes().hex(" "))
        self.motion.setText(
            f"{pat.motion_slots_used()}/{L.NUM_PARAMETERS_MOTION} motion slots used")


# 10 --------------------------------------------------------------------------
class MotionPage(SkippablePage):
    TITLE = "10 · Motion (optional)"
    SUBTITLE = "Draw curves in the Motion tab; the budget is shown here."

    def build(self) -> None:
        self.reason(
            "A pattern has 24 motion slots. Drawing happens on the full canvas in "
            "the Motion tab, which knows each target's real value domain — a "
            "4-option target snaps to {0,32,64,96}, not to arbitrary bytes. This "
            "screen only reports how much of the budget is spent.")
        self.status = _lcd("")
        self.slots = QListWidget()
        self.layout.addWidget(self.status)
        self.layout.addWidget(self.slots, 1)

    def refresh(self) -> None:
        pat = self._ctx.first_pattern()
        self.slots.clear()
        if pat is None:
            self.status.setText("No bank open — nothing to show.")
            return
        used = pat.motion_slots_used()
        self.status.setText(
            f"{used}/{L.NUM_PARAMETERS_MOTION} motion slots used in pattern 000. "
            "Close the wizard and use the Motion tab to draw.")
        for i, slot in enumerate(pat.motion_slots()):
            state = (f"target 0x{slot.target:04X}" if slot.in_use else "free")
            self.slots.addItem(f"slot {i:02d}  {state}")


# 11 --------------------------------------------------------------------------
class ValidateWritePage(SkippablePage):
    TITLE = "11 · Validate & write"
    SUBTITLE = "Coherence findings, then a verified write with a backup."

    def build(self) -> None:
        self.reason(
            "Round-tripping proves the file can be re-read; it does NOT prove the "
            "bank is coherent. One real corpus bank round-trips perfectly and "
            "still has 17 sample headers pointing past EOF. Findings are reported, "
            "never auto-repaired — an incoherent bank is refused unless you "
            "explicitly override, because that stale state may be exactly what "
            "you are trying to preserve.")
        self.findings = QListWidget()
        self.allow_invalid = QCheckBox(
            "Write anyway if validation reports errors (allow_invalid)")
        self.validate_button = QPushButton("Validate")
        self.validate_button.clicked.connect(self.run_validate)
        self.write_button = QPushButton("Write bank")
        self.write_button.clicked.connect(self.run_write)
        self.status = _lcd("")
        row = QHBoxLayout()
        row.addWidget(self.validate_button)
        row.addWidget(self.write_button)
        row.addStretch(1)
        self.layout.addLayout(row)
        self.layout.addWidget(self.findings, 1)
        self.layout.addWidget(self.allow_invalid)
        self.layout.addWidget(self.status)

    def run_validate(self) -> int:
        """Fill the findings list. Returns the number of findings."""
        self.findings.clear()
        try:
            report = self._ctx.session.validate()
        except CodecError as exc:
            self.status.setText(str(exc))
            return 0
        for f in report.findings:
            self.findings.addItem(f"{f.severity:<7} {f.code:<20} {f.message}")
        n_err = len(report.errors())
        self.status.setText(
            f"{len(report)} finding(s), {n_err} error(s). "
            + ("Coherent — safe to write." if report.ok
               else "Writing needs the override below."))
        return len(report)

    def run_write(self, path: str | None = None) -> bool:
        """Write via the session. Returns True on success; never raises."""
        session = self._ctx.session
        if not session.is_open:
            self.status.setText("No bank open.")
            return False
        dest = path or session.path
        if not dest:
            dest, _ = QFileDialog.getSaveFileName(
                self, "Save ESX bank", "", "ESX banks (*.esx)")
            if not dest:
                self.status.setText("Write cancelled.")
                return False
        try:
            written = session.save(
                dest, allow_invalid=self.allow_invalid.isChecked())
        except (CodecError, OSError) as exc:
            self.status.setText(f"Write refused: {exc}")
            return False
        self._ctx.notify_changed()
        self.status.setText(
            f"Wrote {written} (verified by re-read; previous kept as .bak).")
        return True

    def refresh(self) -> None:
        session = self._ctx.session
        if not session.is_open:
            self.status.setText("No bank open — nothing to validate.")
            return
        self.status.setText(
            f"Ready: {session.path or 'untitled (will ask where to save)'}. "
            "Press Validate to check coherence first.")


#: The eleven screens, in wizard order (TDD §09).
PAGE_CLASSES = (
    StartPage, CardCheckPage, AddSamplesPage, QualityBudgetPage,
    KeyAnalysisPage, NamingPage, SlotAssignmentPage, PartSetupPage,
    PatternBasicsPage, MotionPage, ValidateWritePage,
)
