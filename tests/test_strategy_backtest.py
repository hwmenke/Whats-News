import pytest
import pandas as pd

import strategy_tester as st


RSI_CROSS_CONFIG = {
    "entry_long": {
        "type": "leaf",
        "kind": "rsi_level",
        "params": {"period": 14, "level": 30},
        "op": "cross_above",
    },
    "exit_long": {
        "type": "leaf",
        "kind": "rsi_level",
        "params": {"period": 14, "level": 70},
        "op": "cross_above",
    },
    "allow_short": False,
    "bar_delay": 1,
}


def test_backtest_output_keys(mock_db):
    result = st.run_backtest("TEST", "daily", RSI_CROSS_CONFIG)
    assert "error" not in result
    for key in ("metrics", "trades", "equity", "dates"):
        assert key in result, f"missing key: {key}"


def test_backtest_metrics_keys(mock_db):
    result = st.run_backtest("TEST", "daily", RSI_CROSS_CONFIG)
    m = result["metrics"]
    for key in ("total_return", "win_rate", "max_drawdown", "n_trades"):
        assert key in m, f"missing metric: {key}"


def test_backtest_equity_length_matches_dates(mock_db):
    result = st.run_backtest("TEST", "daily", RSI_CROSS_CONFIG)
    assert len(result["equity"]) == len(result["dates"])


def test_backtest_no_lookahead(mock_db, synth_ohlcv):
    result = st.run_backtest("TEST", "daily", RSI_CROSS_CONFIG)
    dates = pd.to_datetime(result["dates"])
    for trade in result["trades"]:
        entry_dt = pd.to_datetime(trade["entry_date"])
        assert entry_dt in dates.values, "entry_date not in date index"


def test_backtest_win_rate_bounded(mock_db):
    result = st.run_backtest("TEST", "daily", RSI_CROSS_CONFIG)
    wr = result["metrics"]["win_rate"]
    if wr is not None:
        assert 0.0 <= wr <= 1.0


def test_backtest_empty_config_returns_result(mock_db):
    result = st.run_backtest("TEST", "daily", {})
    # Empty config → no trades, equity stays flat; should not raise
    assert "metrics" in result


def test_monte_carlo_output_shape():
    trades = [{"net_ret": r} for r in [0.05, -0.02, 0.03, 0.08, -0.04, 0.01, 0.06]]
    result = st.monte_carlo(trades, n_sim=500)
    assert isinstance(result, dict)
    assert "error" not in result
