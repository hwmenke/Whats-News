import sys
from unittest.mock import MagicMock

# Stub yfinance so tests work without the package installed
if "yfinance" not in sys.modules:
    sys.modules["yfinance"] = MagicMock()

import pytest
import numpy as np
import pandas as pd


@pytest.fixture
def synth_ohlcv():
    rng = np.random.default_rng(42)
    n = 200
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    trend = np.linspace(100, 140, n)
    close = trend + 4 * np.sin(np.linspace(0, 8 * np.pi, n)) + rng.normal(0, 0.8, n)
    high  = close + rng.uniform(0.3, 1.2, n)
    low   = close - rng.uniform(0.3, 1.2, n)
    open_ = np.r_[close[0], close[:-1]] + rng.normal(0, 0.3, n)
    return pd.DataFrame(
        {
            "open":   open_,
            "high":   high,
            "low":    low,
            "close":  pd.Series(close, index=idx),
            "volume": rng.integers(500_000, 5_000_000, n).astype(float),
        },
        index=idx,
    )


@pytest.fixture
def mock_db(monkeypatch, synth_ohlcv):
    import database as db
    monkeypatch.setattr(db, "get_ohlcv_df",
        lambda symbol, freq="daily", limit=1000: synth_ohlcv.tail(limit))
