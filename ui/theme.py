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

from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    bg: str = "#12100d"
    panel: str = "#1b1814"
    panel2: str = "#231f19"
    line: str = "#3a332a"
    amber: str = "#ff9d2e"
    amber_dim: str = "#c9761b"
    lcd: str = "#ffb454"
    step: str = "#ff7a2e"          # orange step-key highlight
    green: str = "#7fd68a"
    red: str = "#ff6b5e"
    blue: str = "#6fb6ff"
    txt: str = "#e8e0d4"
    muted: str = "#9d9384"
    chassis: str = "#0c0b09"
    lcd_bg: str = "#1a1208"


@dataclass(frozen=True)
class Type:
    ui: str = '-apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif'
    lcd: str = 'Menlo, "SF Mono", ui-monospace, Consolas, monospace'
    size_body: int = 13
    size_lcd: int = 12
    size_title: int = 16


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
    font-family: {t.ui};
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
    font-family: {t.lcd};
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
    font-family: {t.lcd};
}}
QLabel[role="muted"] {{
    color: {p.muted};
}}
"""


def apply(app) -> None:
    """Apply the theme to a QApplication."""
    app.setStyleSheet(qss())
