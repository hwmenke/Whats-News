"""
market_data.py — On-the-fly market data access for analysis modules.

Analysis code (indicators, stats, scanner, …) should import from here instead
of talking to SQLite directly. Reads are served by the Data Management app
via data_client (HTTP), so the main app stays compute-only.
"""

from data_client import (
    DataServiceError,
    add_symbol,
    add_symbols,
    fetch_symbol,
    get_db_stats,
    get_ohlcv,
    get_ohlcv_df,
    health,
    is_recently_fetched,
    list_symbol_codes,
    list_symbols,
    refresh_all,
    remove_symbol,
    set_symbol_group,
)

__all__ = [
    "DataServiceError",
    "add_symbol",
    "add_symbols",
    "fetch_symbol",
    "get_db_stats",
    "get_ohlcv",
    "get_ohlcv_df",
    "health",
    "is_recently_fetched",
    "list_symbol_codes",
    "list_symbols",
    "refresh_all",
    "remove_symbol",
    "set_symbol_group",
]
