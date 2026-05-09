"""
backtester.py - KAMA Crossover Optimizer
Tests all fast/slow KAMA period combinations with and without trend filter.
"""

import numpy as np
import pandas as pd
import ta
import database as db
from shared_indicators import _kama

FAST_PERIODS = [5, 8, 10, 15, 20]
SLOW_PERIODS = [20, 30, 50, 100, 200]


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


def _run_strategy(close: pd.Series, kama_fast: pd.Series, kama_slow: pd.Series,
                  trend_score: pd.Series = None, use_trend: bool = False) -> dict:
    """
    Run a single KAMA crossover backtest.
    Signal = fast crosses above slow → long; fast crosses below slow → flat.
    Executes on the next bar (shift 1).
    """
    # Raw signal: 1 = long, 0 = flat
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
    strat_ret = position * daily_ret

    # Drop leading NaNs
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
    fast_above = (kama_fast > kama_slow).astype(int)

    if use_trend and trend_score is not None:
        trend_ok   = (trend_score > 0).astype(int)
        signal_raw = fast_above * trend_ok
    else:
        signal_raw = fast_above

    position  = signal_raw.shift(1).fillna(0)
    daily_ret = close.pct_change().fillna(0)

    strat_equity = (1 + position * daily_ret).cumprod()
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


def run_optimization(symbol: str, train_pct: float = 0.7) -> dict:
    """
    Test all FAST × SLOW KAMA period combinations, with and without trend filter.
    Returns top-10 results sorted by Sharpe, plus equity curve and heatmap data.
    """
    df = db.get_ohlcv_df(symbol, "daily", limit=5000)
    if df.empty or len(df) < 220:
        return {"error": f"Not enough data for {symbol}"}

    # ── Walk-forward split ────────────────────────────────────────
    train_pct = max(0.5, min(train_pct, 0.95))
    split_idx = int(len(df) * train_pct)
    df_train  = df.iloc[:split_idx]
    df_oos    = df.iloc[split_idx:]

    close       = df["close"]
    close_train = df_train["close"]
    close_oos   = df_oos["close"]

    # Pre-compute trend score on full series (needs warmup bars)
    trend_score     = _compute_trend_score(df)
    trend_score_oos = trend_score.iloc[split_idx:]

    # Pre-compute all KAMA series on full series
    kama_cache = {}
    for p in set(FAST_PERIODS + SLOW_PERIODS):
        kama_cache[p] = _kama(close, window=p)

    def _bh_stats(c: pd.Series) -> dict:
        ret = c.pct_change().dropna()
        if ret.empty:
            return {"ann_ret": None, "ann_vol": None, "sharpe": None, "max_dd": None}
        ann_ret = ret.mean() * 252
        ann_vol = ret.std() * np.sqrt(252)
        sharpe  = ann_ret / ann_vol if ann_vol != 0 else 0.0
        eq      = (1 + ret).cumprod()
        pk      = eq.cummax()
        max_dd  = ((eq - pk) / pk).min()
        return {"ann_ret": _safe(ann_ret), "ann_vol": _safe(ann_vol),
                "sharpe": _safe(sharpe), "max_dd": _safe(max_dd)}

    benchmark     = _bh_stats(close)
    benchmark_oos = _bh_stats(close_oos)

    # ── In-sample optimisation ────────────────────────────────────
    all_results = []
    for fast_p in FAST_PERIODS:
        for slow_p in SLOW_PERIODS:
            if fast_p >= slow_p:
                continue
            kf_full = kama_cache[fast_p]
            ks_full = kama_cache[slow_p]

            # In-sample slice (use full KAMA for warmup continuity)
            kf_train = kf_full.iloc[:split_idx]
            ks_train = ks_full.iloc[:split_idx]
            ts_train = trend_score.iloc[:split_idx]

            for use_trend in (False, True):
                label  = f"K{fast_p}/K{slow_p}" + (" +Trend" if use_trend else "")
                is_met = _run_strategy(close_train, kf_train, ks_train,
                                       trend_score=ts_train, use_trend=use_trend)

                # Out-of-sample evaluation with same params
                kf_oos = kf_full.iloc[split_idx:]
                ks_oos = ks_full.iloc[split_idx:]
                oos_met = _run_strategy(close_oos, kf_oos, ks_oos,
                                        trend_score=trend_score_oos,
                                        use_trend=use_trend)

                all_results.append({
                    "label":     label,
                    "fast":      fast_p,
                    "slow":      slow_p,
                    "use_trend": use_trend,
                    **{f"is_{k}": v for k, v in is_met.items()},
                    **{f"oos_{k}": v for k, v in oos_met.items()},
                    # Keep legacy keys from in-sample for backward compat
                    **is_met,
                })

    total_tested = len(all_results)

    def sharpe_key(r):
        s = r.get("is_sharpe") or r.get("sharpe")
        return s if s is not None else -1e9

    all_results.sort(key=sharpe_key, reverse=True)
    top10 = all_results[:10]

    # Equity curve for the best result (full period)
    best = all_results[0] if all_results else None
    equity_curve = []
    if best:
        equity_curve = _weekly_equity(
            close,
            kama_cache[best["fast"]],
            kama_cache[best["slow"]],
            trend_score=trend_score,
            use_trend=best["use_trend"],
        )

    # Heatmap: in-sample Sharpe, no-trend version
    heatmap = {}
    for r in all_results:
        if not r["use_trend"]:
            key = f"{r['fast']}x{r['slow']}"
            heatmap[key] = r.get("is_sharpe") or r.get("sharpe")

    return {
        "symbol":        symbol,
        "benchmark":     benchmark,
        "benchmark_oos": benchmark_oos,
        "top10":         top10,
        "best":          best,
        "equity_curve":  equity_curve,
        "heatmap":       heatmap,
        "total_tested":  total_tested,
        "fast_periods":  FAST_PERIODS,
        "slow_periods":  SLOW_PERIODS,
        "train_pct":     train_pct,
        "train_bars":    split_idx,
        "oos_bars":      len(df_oos),
    }
