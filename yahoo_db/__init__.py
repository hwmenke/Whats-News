"""
yahoo_db - a standalone Yahoo Finance downloader that archives price history
for as many tickers as possible (listed and delisted) into a SQLite database.

Nothing in this package imports from the dashboard app in the repository root;
it owns its own database file and can be copied out and used on its own.
"""

from .config import Config, load_config
from .db import Store
from .downloader import Downloader

__version__ = "1.0.0"
__all__ = ["Config", "load_config", "Store", "Downloader"]
