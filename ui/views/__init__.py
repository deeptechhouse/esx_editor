"""
ui.views — one widget per region of the bank (TDD §10.1).

Each view binds to the live core.Bank with `bind_bank(bank)` and renders it.
Views hold no codec objects and perform no I/O: the shell (ui.main_window) owns
the BankSession, and the session is the only place reader/writer/template live.
Where a region is not yet decoded (songs, global fields, pattern header fields)
the view says so and shows the bytes, rather than inventing field offsets.
"""

from .bank_view import BankView
from .global_view import GlobalView
from .pattern_view import PatternView
from .song_view import SongView
from .staging_view import StagingView

__all__ = ["BankView", "StagingView", "PatternView", "SongView", "GlobalView"]
