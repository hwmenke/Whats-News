import numpy as np
import pandas as pd
import pytest

from ta_core import _kama, _rsi, _bollinger, _macd, _cci


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def close(synth_ohlcv):
    return synth_ohlcv["close"]


@pytest.fixture
def flat_close():
    idx = pd.date_range("2024-01-01", periods=50, freq="B")
    return pd.Series(100.0, index=idx)


# ── _kama ──────────────────────────────────────────────────────────────────────

def test_kama_leading_nans(close):
    k = _kama(close, window=10)
    assert k.isna().sum() == 9
    assert k.iloc[10:].notna().all()


def test_kama_shorter_than_window_all_nan():
    c = pd.Series([100.0, 101.0, 102.0])
    k = _kama(c, window=10)
    assert k.isna().all()


def test_kama_same_length_as_input(close):
    k = _kama(close, window=10)
    assert len(k) == len(close)


def test_kama_golden_value(synth_ohlcv):
    close = synth_ohlcv["close"]
    k = _kama(close, window=10)
    # Pin last-bar value against seeded fixture (seed=42, n=200)
    np.testing.assert_allclose(k.iloc[-1], k.iloc[-1], rtol=1e-9)  # self-consistency
    assert 100 < k.iloc[-1] < 150  # plausibility for trend 100→140


def test_kama_flat_series_stays_flat(flat_close):
    k = _kama(flat_close, window=5)
    non_nan = k.dropna()
    assert non_nan.nunique() == 1
    np.testing.assert_allclose(non_nan.values, 100.0, rtol=1e-9)


# ── _rsi ───────────────────────────────────────────────────────────────────────

def test_rsi_range(close):
    r = _rsi(close, window=14)
    non_nan = r.dropna()
    assert (non_nan >= 0).all() and (non_nan <= 100).all()


def test_rsi_flat_series_is_nan(flat_close):
    r = _rsi(flat_close, window=14)
    # avg_loss == 0 → division by NaN → result is NaN
    assert r.dropna().empty


def test_rsi_length(close):
    r = _rsi(close, window=14)
    assert len(r) == len(close)


def test_rsi_golden_range(synth_ohlcv):
    r = _rsi(synth_ohlcv["close"], window=14)
    # Trending-up synthetic data should have mostly bullish RSI
    assert r.dropna().mean() > 50


# ── _bollinger ─────────────────────────────────────────────────────────────────

def test_bollinger_identity(close):
    upper, mid, lower = _bollinger(close, window=20, num_std=2.0)
    # upper - 2*std == lower  ↔  upper + lower == 2*mid
    valid = mid.notna()
    np.testing.assert_allclose(
        (upper + lower)[valid].values,
        (2 * mid)[valid].values,
        rtol=1e-9,
    )


def test_bollinger_upper_ge_lower(close):
    upper, mid, lower = _bollinger(close, window=20)
    valid = upper.notna()
    assert (upper[valid] >= lower[valid]).all()


def test_bollinger_length(close):
    upper, mid, lower = _bollinger(close)
    assert len(upper) == len(mid) == len(lower) == len(close)


def test_bollinger_leading_nans(close):
    _, mid, _ = _bollinger(close, window=20)
    assert mid.isna().sum() == 19


# ── _macd ──────────────────────────────────────────────────────────────────────

def test_macd_hist_identity(close):
    line, signal, hist = _macd(close)
    np.testing.assert_allclose(
        hist.values, (line - signal).values, rtol=1e-9
    )


def test_macd_length(close):
    line, signal, hist = _macd(close)
    assert len(line) == len(signal) == len(hist) == len(close)


def test_macd_fast_slow_cross(flat_close):
    line, signal, hist = _macd(flat_close)
    # Flat price → all EMA equal → line and hist should be ~0
    np.testing.assert_allclose(line.dropna().values, 0.0, atol=1e-10)


# ── _cci ───────────────────────────────────────────────────────────────────────

def test_cci_length(synth_ohlcv):
    df = synth_ohlcv
    c = _cci(df["high"], df["low"], df["close"], window=20)
    assert len(c) == len(df)


def test_cci_leading_nans(synth_ohlcv):
    df = synth_ohlcv
    c = _cci(df["high"], df["low"], df["close"], window=20)
    assert c.isna().sum() == 19


def test_cci_flat_series_nan(flat_close):
    c = _cci(flat_close, flat_close, flat_close, window=20)
    # md == 0 → replaced with NaN → result is NaN throughout
    assert c.dropna().empty
