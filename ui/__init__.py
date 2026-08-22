"""
ui — ESX Bank Studio Qt shell.

Widgets render state and emit intent (TDD §10.2). They never import codec/.
The composition root (ui.session.BankSession, ui.main_window) is the only UI
layer that talks to codec, and even then only through BankSession.
"""

from .theme import PALETTE, TYPE, SPACE, apply as apply_theme

__all__ = ["PALETTE", "TYPE", "SPACE", "apply_theme"]
