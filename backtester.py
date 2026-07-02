"""
backtester.py - KAMA Crossover Optimizer
Tests all fast/slow KAMA period combinations with and without trend filter.
"""

import numpy as np
import pandas as pd
import ta
import database as db

FAST_PERIODS = [5, 8, 10, 15, 20]
SLOW_PERIODS = [20, 30, 50, 100, 200]

# Transaction cost per side, in basis points. Without a cost term the Sharpe
# ranking systematically favours the highest-turnover configs, whose paper
# edge is thinnest in practice.
COST_BPS = 5.0


def _kama(close: pd.Series, window: int = 10, fast: int = 2, slow: int = 30) -> pd.Series:
    """Kaufman's Adaptive Moving Average."""
    prices = close.to_numpy(dtype=float, copy=True)
    kama_vals = np.full(len(prices), np.nan)

    if len(prices) < window:
        return pd.Series(kama_vals, index=close.index)

    fast_sc = 2.0 / (fast + 1)
    slow_sc = 2.0 / (slow + 1)
    kama_vals[window - 1] = prices[window - 1]

    for i in range(window, len(prices)):
        direction = abs(prices[i] - prices[i - window])
        volatility = np.sum(np.abs(np.diff(prices[i - window: i + 1])))
        er = direction / volatility if volatility != 0 else 0
        sc = (er * (fast_sc - slow_sc) + slow_sc) ** 2
        kama_vals[i] = kama_vals[i - 1] + sc * (prices[i] - kama_vals[i - 1])

    return pd.Series(kama_vals, index=close.index)


def _compute_trend_score(df: pd.DataFrame) -> pd.Series:
    """Compute composite trend score (RSI + CCI + MACD) as in indicators.py."""
    close = df["close"]
    high  = df["high"]
    low   = df["low"]

    rsi14 = ta.momentum.RSIIndicator(close, window=14).rsi()
    cci   = ta.trend.CCIIndicator(high, low, close, window=20).cci()
    macd_hist = ta.trend.MACD(close, window_slow=26, window_fast=12, window_sign=9).macd_diff()

    rsi_score  = np.where(rsi14 > 80, 0, np.where(rsi14 > 50, 1, -1))
    cci_score  = np.where(cci > 0, 1, -1)
    macd_score = np.where(macd_hist > 0, 1, -1)

    total = rsi_score + cci_score + macd_score
    mask  = rsi14.isna() | cci.isna() | macd_hist.isna()
    total = np.where(mask, np.nan, total)

    return pd.Series(total, index=close.index)


def _safe(val):
    try:
        if val is None or not np.isfinite(val):
            return None
        return round(float(val), 6)
    except Exception:
        return None


def _strategy_returns(close: pd.Series, kama_fast: pd.Series, kama_slow: pd.Series,
                      trend_score: pd.Series = None, use_trend: bool = False):
    """
    Daily strategy returns for one KAMA crossover config.
    Signal = fast above slow → long; else flat. Executes next bar (shift 1).
    Returns (position, strat_ret) full-length series so callers can slice
    train/test windows from the same computation.
    """
    fast_above = (kama_fast > kama_slow).astype(int)

    if use_trend and trend_score is not None:
        # Only allow long when trend_score > 0
        trend_ok = (trend_score > 0).astype(int)
        signal_raw = fast_above * trend_ok
    else:
        signal_raw = fast_above

    # Execute next bar
    position = signal_raw.shift(1).fillna(0)

    daily_ret = close.pct_change()
    costs     = (COST_BPS / 1e4) * position.diff().abs().fillna(0.0)
    strat_ret = position * daily_ret - costs
    return position, strat_ret


def _metrics(strat_ret: pd.Series, position: pd.Series) -> dict:
    """Performance metrics over a (possibly sliced) return series."""
    strat_ret = strat_ret.dropna()
    if strat_ret.empty or strat_ret.std() == 0:
        return {
            "ann_ret": None, "ann_vol": None, "sharpe": None,
            "max_dd": None, "n_trades": 0, "win_rate": None,
        }

    # Annualised return & vol
    ann_ret = strat_ret.mean() * 252
    ann_vol = strat_ret.std() * np.sqrt(252)
    sharpe  = ann_ret / ann_vol if ann_vol != 0 else 0.0

    # Max drawdown
    equity   = (1 + strat_ret).cumprod()
    peak     = equity.cummax()
    drawdown = (equity - peak) / peak
    max_dd   = drawdown.min()

    # Trade counting (position changes)
    pos_changes = position.diff().fillna(0)
    entries = (pos_changes > 0).sum()
    n_trades = int(entries)

    # Win rate: fraction of positive daily returns while in position
    in_pos = position[position > 0]
    if len(in_pos) > 0:
        returns_in_pos = strat_ret[in_pos.index.intersection(strat_ret.index)]
        win_rate = float((returns_in_pos > 0).mean()) if len(returns_in_pos) > 0 else None
    else:
        win_rate = None

    return {
        "ann_ret":  _safe(ann_ret),
        "ann_vol":  _safe(ann_vol),
        "sharpe":   _safe(sharpe),
        "max_dd":   _safe(max_dd),
        "n_trades": n_trades,
        "win_rate": _safe(win_rate),
    }


def _weekly_equity(close: pd.Series, kama_fast: pd.Series, kama_slow: pd.Series,
                   trend_score: pd.Series = None, use_trend: bool = False) -> list:
    """Return weekly equity curve for strategy and buy-and-hold."""
    position, strat_ret = _strategy_returns(close, kama_fast, kama_slow,
                                            trend_score=trend_score, use_trend=use_trend)
    daily_ret = close.pct_change().fillna(0)

    strat_equity = (1 + strat_ret.fillna(0)).cumprod()
    bh_equity    = (1 + daily_ret).cumprod()

    # Resample to weekly
    strat_w = strat_equity.resample("W-FRI").last().dropna()
    bh_w    = bh_equity.resample("W-FRI").last().dropna()

    curve = []
    for date in strat_w.index:
        if date in bh_w.index:
            curve.append({
                "date":      date.strftime("%Y-%m-%d"),
                "strategy":  round(float(strat_w[date]), 6),
                "benchmark": round(float(bh_w[date]), 6),
            })
    return curve


def _bh_metrics(daily_ret: pd.Series) -> dict:
    """Buy-and-hold metrics over a (possibly sliced) daily-return series."""
    daily_ret = daily_ret.dropna()
    if daily_ret.empty or daily_ret.std() == 0:
        return {"ann_ret": None, "ann_vol": None, "sharpe": None, "max_dd": None}
    ann_ret = daily_ret.mean() * 252
    ann_vol = daily_ret.std() * np.sqrt(252)
    equity  = (1 + daily_ret).cumprod()
    max_dd  = ((equity - equity.cummax()) / equity.cummax()).min()
    return {
        "ann_ret": _safe(ann_ret),
        "ann_vol": _safe(ann_vol),
        "sharpe":  _safe(ann_ret / ann_vol if ann_vol != 0 else 0.0),
        "max_dd":  _safe(max_dd),
    }


TRAIN_FRAC = 0.75


def run_optimization(symbol: str) -> dict:
    """
    Walk-forward KAMA crossover optimization.

    All FAST × SLOW combinations (± trend filter) are ranked by Sharpe on the
    TRAIN window (first 75% of history) only; the selected config's metrics on
    the untouched holdout window are reported separately. Ranking on the full
    sample and plotting the winner on the same data is pure selection bias —
    the max of 48 noisy Sharpes always looks good.
    """
    df = db.get_ohlcv_df(symbol, "daily", limit=5000)
    if df.empty or len(df) < 220:
        return {"error": f"Not enough data for {symbol}"}

    close = df["close"]
    split_idx  = int(len(close) * TRAIN_FRAC)
    split_date = close.index[split_idx].strftime("%Y-%m-%d")

    # Pre-compute trend score once
    trend_score = _compute_trend_score(df)

    # Pre-compute all KAMA series (recursive → past-only, safe on full series)
    kama_cache = {}
    for p in set(FAST_PERIODS + SLOW_PERIODS):
        kama_cache[p] = _kama(close, window=p)

    # Buy-and-hold benchmark, train + holdout
    daily_ret     = close.pct_change()
    benchmark     = _bh_metrics(daily_ret.iloc[:split_idx])
    benchmark_oos = _bh_metrics(daily_ret.iloc[split_idx:])

    all_results = []
    returns_by_label = {}
    for fast_p in FAST_PERIODS:
        for slow_p in SLOW_PERIODS:
            if fast_p >= slow_p:
                continue
            for use_trend in (False, True):
                label = f"K{fast_p}/K{slow_p}" + (" +Trend" if use_trend else "")
                position, strat_ret = _strategy_returns(
                    close,
                    kama_cache[fast_p],
                    kama_cache[slow_p],
                    trend_score=trend_score,
                    use_trend=use_trend,
                )
                returns_by_label[label] = (position, strat_ret)
                metrics = _metrics(strat_ret.iloc[:split_idx], position.iloc[:split_idx])
                all_results.append({
                    "label":      label,
                    "fast":       fast_p,
                    "slow":       slow_p,
                    "use_trend":  use_trend,
                    **metrics,
                })

    total_tested = len(all_results)

    # Sort by TRAIN Sharpe descending (None → treated as -inf)
    def sharpe_key(r):
        s = r.get("sharpe")
        return s if s is not None else -1e9

    all_results.sort(key=sharpe_key, reverse=True)
    top10 = all_results[:10]

    # Best config: holdout metrics + full-period equity curve
    best = all_results[0] if all_results else None
    best_oos = None
    equity_curve = []
    if best:
        position, strat_ret = returns_by_label[best["label"]]
        best_oos = _metrics(strat_ret.iloc[split_idx:], position.iloc[split_idx:])
        equity_curve = _weekly_equity(
            close,
            kama_cache[best["fast"]],
            kama_cache[best["slow"]],
            trend_score=trend_score,
            use_trend=best["use_trend"],
        )

    # Heatmap data: Sharpe indexed by (fast, slow) — no-trend version
    heatmap = {}
    for r in all_results:
        if not r["use_trend"]:
            key = f"{r['fast']}x{r['slow']}"
            heatmap[key] = r.get("sharpe")

    return {
        "symbol":        symbol,
        "benchmark":     benchmark,       # buy & hold, train window
        "benchmark_oos": benchmark_oos,   # buy & hold, holdout window
        "top10":         top10,           # ranked by TRAIN Sharpe
        "best":          best,            # train metrics of selected config
        "best_oos":      best_oos,        # holdout metrics of selected config
        "split_date":    split_date,
        "train_frac":    TRAIN_FRAC,
        "equity_curve":  equity_curve,
        "heatmap":       heatmap,
        "total_tested":  total_tested,
        "cost_bps":      COST_BPS,
        "fast_periods":  FAST_PERIODS,
        "slow_periods":  SLOW_PERIODS,
    }
