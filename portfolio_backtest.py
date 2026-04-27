"""
portfolio_backtest.py — Multi-asset portfolio backtesting with dynamic position sizing.

Sizing modes:
  vol_target   : weight_i = target_vol / (trailing_vol_i * sqrt(ann)); normalized to max_gross
  risk_parity  : weight_i = 1 / trailing_vol_i; normalized so sum(weights) = 1
  equal        : weight_i = 1 / N for active positions

Public API:
  run_portfolio_backtest(symbols, freq, config, sizing) -> dict
"""

import math
import numpy as np
import pandas as pd
import database as db
from strategy_tester import (
    _build_positions_from_config,
    _ann_factor,
    _compute_metrics,
    DEFAULT_COSTS,
    _safe,
)

VOL_LOOKBACK  = 20    # bars for trailing realized vol
TARGET_VOL    = 0.10  # annualised vol target for vol_target mode
MAX_GROSS     = 1.5   # max sum(|weights|) for vol_target


def _compute_symbol_returns(symbol: str, freq: str, limit: int) -> pd.Series:
    df = db.get_ohlcv_df(symbol, freq, limit=limit)
    if df.empty:
        return pd.Series(dtype=float)
    return df["close"].pct_change()


def _vol_target_weights(positions_df: pd.DataFrame, returns_df: pd.DataFrame,
                        ann: float, target_vol: float = TARGET_VOL,
                        lookback: int = VOL_LOOKBACK,
                        max_gross: float = MAX_GROSS) -> pd.DataFrame:
    """Compute vol-targeted weights. Zero where position=0."""
    weights = pd.DataFrame(0.0, index=positions_df.index, columns=positions_df.columns)
    for sym in positions_df.columns:
        if sym not in returns_df.columns:
            continue
        roll_vol = (returns_df[sym]
                    .rolling(lookback, min_periods=max(2, lookback // 2))
                    .std(ddof=1) * math.sqrt(ann))
        roll_vol = roll_vol.reindex(positions_df.index)
        roll_vol = roll_vol.replace(0, np.nan).ffill().fillna(0.01)
        raw_w = target_vol / roll_vol
        weights[sym] = raw_w * positions_df[sym].abs()   # zero where flat
        # Preserve direction
        weights[sym] *= positions_df[sym].apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))

    # Normalize to max_gross
    gross = weights.abs().sum(axis=1)
    scale = (max_gross / gross).clip(upper=1.0)
    weights = weights.multiply(scale, axis=0)
    return weights


def _risk_parity_weights(positions_df: pd.DataFrame, returns_df: pd.DataFrame,
                         lookback: int = VOL_LOOKBACK) -> pd.DataFrame:
    """Inverse-vol weights; sum of active |weights| normalized to 1."""
    weights = pd.DataFrame(0.0, index=positions_df.index, columns=positions_df.columns)
    for sym in positions_df.columns:
        if sym not in returns_df.columns:
            continue
        roll_vol = (returns_df[sym]
                    .rolling(lookback, min_periods=max(2, lookback // 2))
                    .std(ddof=1))
        roll_vol = roll_vol.reindex(positions_df.index)
        roll_vol = roll_vol.replace(0, np.nan).ffill().fillna(0.01)
        weights[sym] = (1.0 / roll_vol) * positions_df[sym].apply(
            lambda x: 1 if x > 0 else (-1 if x < 0 else 0))

    # Normalize: sum(|active weights|) = 1 per bar
    gross = weights.abs().sum(axis=1).replace(0, np.nan)
    weights = weights.divide(gross, axis=0).fillna(0.0)
    return weights


def _equal_weights(positions_df: pd.DataFrame) -> pd.DataFrame:
    """Equal-weight all active (non-zero) positions."""
    n_active = (positions_df != 0).sum(axis=1).replace(0, np.nan)
    weights = positions_df.divide(n_active, axis=0).fillna(0.0)
    return weights


def run_portfolio_backtest(symbols: list, freq: str, config: dict,
                           sizing: str = "vol_target") -> dict:
    """
    Run a portfolio backtest across multiple symbols.

    config is a single strategy config applied to every symbol.
    sizing: "vol_target" | "risk_parity" | "equal"

    Returns portfolio equity curve, per-leg equity, and aggregate metrics.
    """
    limit = int(config.get("limit", 2000))
    ann   = _ann_factor(freq)
    commission = float(config.get("commission_pct", DEFAULT_COSTS["commission_pct"]))
    slippage   = float(config.get("slippage_pct",   DEFAULT_COSTS["slippage_pct"]))
    cost_per_side = commission + slippage

    # Load data and build per-symbol positions
    dfs       = {}
    positions = {}
    ret_series = {}

    for sym in symbols:
        df = db.get_ohlcv_df(sym, freq, limit=limit)
        if df.empty or len(df) < 30:
            continue
        dfs[sym]        = df
        ret_series[sym] = df["close"].pct_change()
        try:
            pos = _build_positions_from_config(df, config)
        except Exception:
            pos = pd.Series(0, index=df.index)
        positions[sym] = pos

    if not positions:
        return {"error": "No usable data for any symbol"}

    # Align to common date intersection
    common_idx = None
    for sym, pos in positions.items():
        common_idx = pos.index if common_idx is None else common_idx.intersection(pos.index)

    if len(common_idx) < 30:
        return {"error": "Insufficient common dates across symbols"}

    # Warn if intersection is much shorter than individual series
    max_len = max(len(p) for p in positions.values())
    if len(common_idx) < max_len * 0.8:
        pass  # included in response as intersection_pct

    positions_df = pd.DataFrame(
        {sym: positions[sym].reindex(common_idx).fillna(0) for sym in positions},
        index=common_idx,
    )
    returns_df = pd.DataFrame(
        {sym: ret_series[sym].reindex(common_idx).fillna(0) for sym in positions},
        index=common_idx,
    )

    # Compute weights per sizing mode
    if sizing == "vol_target":
        weights = _vol_target_weights(positions_df, returns_df, ann)
    elif sizing == "risk_parity":
        weights = _risk_parity_weights(positions_df, returns_df)
    else:
        weights = _equal_weights(positions_df)

    # Lag weights by 1 bar (signal generated at bar close, executed next bar)
    weights_lag = weights.shift(1).fillna(0.0)

    # Bar-by-bar P&L for each leg
    leg_gross_ret = returns_df * weights_lag

    # Cost drag: fire on weight changes (any change ≥ 1% of prior weight)
    weight_change = weights_lag.diff().abs()
    cost_drag_per_leg = weight_change * cost_per_side
    leg_net_ret = leg_gross_ret - cost_drag_per_leg

    # Portfolio net return = sum across legs
    port_net_ret = leg_net_ret.sum(axis=1)

    # Portfolio equity curve
    port_equity = (1.0 + port_net_ret).cumprod()
    port_peak   = port_equity.cummax()
    port_dd     = port_equity / port_peak - 1.0

    # Per-leg equity curves
    leg_equity = {}
    for sym in positions_df.columns:
        leg_equity[sym] = (1.0 + leg_net_ret[sym]).cumprod()

    # Benchmark: equal buy-and-hold of all symbols
    bh_ret   = returns_df.mean(axis=1)
    bh_eq    = (1.0 + bh_ret).cumprod()

    # Portfolio metrics
    nr = port_net_ret.values
    eq_ser = port_equity.values
    peak   = port_peak.values
    dd_arr = port_dd.values

    total_return = float(eq_ser[-1] - 1.0)
    n_years      = len(nr) / ann
    cagr         = float(eq_ser[-1] ** (1.0 / max(n_years, 0.01)) - 1.0)
    ret_mean     = float(np.mean(nr))
    ret_std      = float(np.std(nr, ddof=1)) if len(nr) > 1 else 1e-9
    sharpe       = (ret_mean / ret_std * math.sqrt(ann)) if ret_std > 1e-12 else 0.0
    max_dd       = float(np.min(dd_arr))
    vol_ann      = ret_std * math.sqrt(ann)

    # Turnover: mean daily sum of absolute weight changes (annualised)
    daily_turnover = weight_change.sum(axis=1).mean()
    turnover_ann   = float(daily_turnover * ann / 2)  # /2: round-trip

    # Avg pairwise correlation of leg net returns
    leg_nr_df = leg_net_ret.replace(0, np.nan).dropna(how='all')
    if leg_nr_df.shape[1] >= 2:
        corr_mat = leg_nr_df.corr().values
        mask = ~np.eye(len(corr_mat), dtype=bool)
        avg_corr = float(np.nanmean(corr_mat[mask]))
    else:
        avg_corr = 0.0

    # Per-leg contribution
    per_leg_contribution = {}
    for sym in positions_df.columns:
        leg_total = float(leg_net_ret[sym].sum())
        port_total = float(port_net_ret.sum()) or 1e-9
        avg_w = float(weights_lag[sym].abs().mean())
        n_trades = int((positions_df[sym].diff().abs() > 0).sum() // 2)
        per_leg_contribution[sym] = {
            "contribution_pct": round(leg_total / abs(port_total), 4),
            "avg_weight":       round(avg_w, 4),
            "n_trades":         n_trades,
        }

    dates = [d.strftime("%Y-%m-%d") for d in common_idx]

    def sl(arr):
        return [None if not np.isfinite(v) else round(float(v), 6) for v in arr]

    return {
        "dates":           dates,
        "equity":          sl(port_equity.values),
        "benchmark":       sl(bh_eq.values),
        "drawdown":        sl(port_dd.values),
        "per_leg_equity":  {sym: sl(leg_equity[sym].values) for sym in leg_equity},
        "weights":         {sym: sl(weights_lag[sym].values) for sym in weights_lag.columns},
        "metrics": {
            "total_return":       round(total_return, 4),
            "cagr":               round(cagr, 4),
            "sharpe":             round(sharpe, 4),
            "vol_ann":            round(vol_ann, 4),
            "max_drawdown":       round(max_dd, 4),
            "turnover_ann":       round(turnover_ann, 4),
            "avg_pairwise_corr":  round(avg_corr, 4),
            "n_symbols":          len(positions_df.columns),
            "intersection_pct":   round(len(common_idx) / max(max_len, 1), 4),
            "per_leg_contribution": per_leg_contribution,
        },
        "symbols":         list(positions_df.columns),
        "sizing":          sizing,
    }
