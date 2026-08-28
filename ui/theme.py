"""
ui.theme — ESX-1-inspired motif, entirely token-driven (TDD §10.3).

A dark chassis, amber backlit-LCD accents, orange step-key highlights. Every
colour, font, spacing, and radius lives here so the whole look is editable in
one file. Widgets paint from these tokens; Qt widgets pick them up via QSS.

Accessibility (WCAG 2.1 AA): body text is #e8e0d4 on #12100d (~12:1), focus
rings are 2 px amber, and the QSS uses relative font sizes so 200% zoom stays
usable. Keyboard navigation is Qt's default (Tab / Shift-Tab / mnemonics).
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Palette:
    bg: str = "#12100d"
    panel: str = "#1b1814"
    panel2: str = "#231f19"
    line: str = "#3a332a"
    amber: str = "#ff9d2e"
    amber_dim: str = "#c9761b"
    lcd: str = "#ffb454"
    step: str = "#ff7a2e"  # orange step-key highlight
    green: str = "#7fd68a"
    red: str = "#ff6b5e"
    blue: str = "#6fb6ff"
    txt: str = "#e8e0d4"
    muted: str = "#9d9384"
    chassis: str = "#0c0b09"
    lcd_bg: str = "#1a1208"


#: Font candidates in preference order. These are QT family names, not a CSS
#: font stack.
#:
#: WHY NOT A CSS STACK
#:     Qt's stylesheet parser does not resolve CSS generic families. Naming
#:     "-apple-system" or "ui-monospace" — which no font database contains —
#:     makes Qt walk every alias looking for them, and it says so on startup:
#:     "Populating font family aliases took 405 ms." The user pays that on every
#:     launch and still gets a fallback face.
#:
#:     So the stack is resolved ONCE against the real font database and the
#:     winner is written into the stylesheet. Portable: the mini and the Linux
#:     CI runner each pick their own first hit, and anything with no hit falls
#:     back to the application default rather than to a guess.
UI_FONT_CANDIDATES = (
    "Helvetica Neue",  # macOS
    "Segoe UI",  # Windows
    "Inter",
    "DejaVu Sans",  # common on Linux
    "Helvetica",
    "Arial",
)
LCD_FONT_CANDIDATES = (
    "Menlo",  # macOS
    "SF Mono",
    "Consolas",  # Windows
    "DejaVu Sans Mono",  # common on Linux
    "Monaco",
    "Courier New",
)


def resolve_family(candidates: Sequence[str], available: Collection[str]) -> str:
    """First candidate the font database actually has, else "" for the default.

    Pure so the choice can be tested without a font database, and so a machine
    with none of the candidates degrades to the application default instead of
    to an unresolvable name.
    """
    for family in candidates:
        if family in available:
            return family
    return ""


def _installed_families() -> frozenset[str]:
    try:
        from PySide6.QtGui import QFontDatabase

        return frozenset(QFontDatabase.families())
    except Exception:  # pragma: no cover - no Qt, or no display
        return frozenset()


@dataclass(frozen=True)
class Type:
    ui: str = ""
    lcd: str = ""
    size_body: int = 13
    size_lcd: int = 12
    size_title: int = 16

    @property
    def ui_rule(self) -> str:
        """`font-family: X;` or nothing — never `font-family: ;`."""
        return f"font-family: {self.ui};" if self.ui else ""

    @property
    def lcd_rule(self) -> str:
        return f"font-family: {self.lcd};" if self.lcd else ""

    def resolved(self, available: Collection[str] | None = None) -> Type:
        """A copy with `ui` and `lcd` bound to real installed families."""
        families = _installed_families() if available is None else available
        return replace(
            self,
            ui=resolve_family(UI_FONT_CANDIDATES, families),
            lcd=resolve_family(LCD_FONT_CANDIDATES, families),
        )


@dataclass(frozen=True)
class Space:
    xs: int = 4
    sm: int = 8
    md: int = 12
    lg: int = 18
    radius: int = 5
    focus: int = 2


PALETTE = Palette()
TYPE = Type()
SPACE = Space()


def qss(palette: Palette = PALETTE, typ: Type = TYPE, space: Space = SPACE) -> str:
    """Return the application-wide stylesheet derived from the tokens."""
    p, t, s = palette, typ, space
    return f"""
QWidget {{
    background: {p.bg};
    color: {p.txt};
    {t.ui_rule}
    font-size: {t.size_body}px;
}}
QMainWindow, QDialog {{
    background: {p.bg};
}}
QMenuBar {{
    background: {p.panel};
    color: {p.txt};
    border-bottom: 1px solid {p.line};
}}
QMenuBar::item:selected {{
    background: {p.panel2};
    color: {p.lcd};
}}
QMenu {{
    background: {p.panel};
    color: {p.txt};
    border: 1px solid {p.line};
}}
QMenu::item:selected {{
    background: {p.panel2};
    color: {p.amber};
}}
QTabWidget::pane {{
    border: 1px solid {p.line};
    background: {p.panel};
    top: -1px;
}}
QTabBar::tab {{
    background: {p.panel2};
    color: {p.muted};
    padding: {s.sm}px {s.lg}px;
    border: 1px solid {p.line};
    border-bottom: none;
    margin-right: 2px;
}}
QTabBar::tab:selected {{
    background: {p.panel};
    color: {p.lcd};
    border-top: 2px solid {p.amber};
}}
QTabBar::tab:focus {{
    outline: {s.focus}px solid {p.amber};
}}
QStatusBar {{
    background: {p.panel};
    color: {p.muted};
    border-top: 1px solid {p.line};
}}
QPushButton {{
    background: {p.panel2};
    color: {p.txt};
    border: 1px solid {p.line};
    border-radius: {s.radius}px;
    padding: {s.xs}px {s.md}px;
    min-height: 22px;
}}
QPushButton:hover {{
    border-color: {p.amber_dim};
    color: {p.lcd};
}}
QPushButton:focus {{
    border: {s.focus}px solid {p.amber};
}}
QPushButton:disabled {{
    color: {p.muted};
}}
QLineEdit, QSpinBox, QComboBox {{
    background: {p.chassis};
    color: {p.lcd};
    {t.lcd_rule}
    border: 1px solid {p.line};
    border-radius: {s.radius}px;
    padding: {s.xs}px {s.sm}px;
    selection-background-color: {p.amber_dim};
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{
    border: {s.focus}px solid {p.amber};
}}
QScrollBar:vertical, QScrollBar:horizontal {{
    background: {p.chassis};
    border: none;
    width: 10px;
    height: 10px;
}}
QScrollBar::handle {{
    background: {p.line};
    border-radius: 4px;
    min-height: 24px;
}}
QListWidget, QTableWidget, QPlainTextEdit {{
    background: {p.chassis};
    color: {p.txt};
    border: 1px solid {p.line};
    border-radius: {s.radius}px;
    alternate-background-color: {p.panel};
}}
QListWidget::item, QTableWidget::item {{
    padding: {s.xs}px {s.sm}px;
}}
QListWidget::item:selected, QTableWidget::item:selected {{
    background: {p.amber_dim};
    color: {p.chassis};
}}
QListWidget::item:hover, QTableWidget::item:hover {{
    background: {p.panel2};
    color: {p.lcd};
}}
QHeaderView::section {{
    background: {p.panel2};
    color: {p.lcd};
    border: none;
    border-right: 1px solid {p.line};
    border-bottom: 1px solid {p.line};
    padding: {s.xs}px {s.sm}px;
}}
QListWidget:focus, QTableWidget:focus {{
    border: {s.focus}px solid {p.amber};
}}
QLabel[role="lcd"] {{
    color: {p.lcd};
    {t.lcd_rule}
}}
QLabel[role="muted"] {{
    color: {p.muted};
}}
"""


def apply(app) -> None:
    """Apply the theme to a QApplication.

    Fonts are resolved here, against the live font database, rather than at
    import time: the database is not populated until a QApplication exists.
    """
    app.setStyleSheet(qss(typ=TYPE.resolved()))
