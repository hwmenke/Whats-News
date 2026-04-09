"""
stats.py - Compute statistical analysis and factor quintiles for a symbol.
"""

import numpy as np
import pandas as pd
import database as db
import ta

KAMA_PERIODS = [10, 20, 50]


def _safe(val):
    if val is None: return None
    try:
        if np.isnan(val): return None
    except: pass
    if isinstance(val, (np.integer,)): return int(val)
    if isinstance(val, (np.floating,)): return float(val)
    return val

def _finite_or_none(val):
    try:
        if val is None or not np.isfinite(val):
            return None
    except Exception:
        return _safe(val)
    return _safe(val)


def _kama(close: pd.Series, window: int = 10, fast: int = 2, slow: int = 30) -> pd.Series:
    """Lightweight KAMA implementation shared with the stats calculations."""
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


def compute_stats(symbol: str) -> dict:
    # Use 5000 bars (~20 years) for deep statistical context
    df = db.get_ohlcv_df(symbol, "daily", limit=5000)
    if df.empty:
        return {"error": "No data found"}

    # 1. Base Returns
    df['ret_1d'] = df['close'].pct_change()
    df['fwd_ret_1d'] = df['ret_1d'].shift(-1)
    df['fwd_ret_5d'] = df['close'].pct_change(5).shift(-5)

    # 2. Key Metrics
    returns = df['ret_1d'].dropna()
    if returns.empty:
        vol_ann = None
        sharpe = None
        max_dd = None
        distribution = []
    else:
        ret_std = returns.std()
        ret_mean = returns.mean()
        vol_ann = ret_std * np.sqrt(252) if pd.notna(ret_std) else None
        sharpe = (ret_mean / ret_std * np.sqrt(252)) if pd.notna(ret_std) and ret_std != 0 else None

        cumulative = (1 + returns).cumprod()
        peak = cumulative.cummax()
        drawdown = (cumulative - peak) / peak
        max_dd = drawdown.min()

        counts, bins = np.histogram(returns, bins=30)
        distribution = [{"bin": _finite_or_none((bins[i] + bins[i+1]) / 2), "count": int(counts[i])} for i in range(len(counts))]

    # 3. Features for Quintiles
    df['rsi'] = ta.momentum.RSIIndicator(df['close'], window=14).rsi()
    # Volatility Feature (Relative Volatility Index or just standard dev)
    df['vol_20'] = df['ret_1d'].rolling(20).std() * np.sqrt(252)
    
    # 4. Feature Binning (Deciles)
    def get_binned_performance(feature_col, target_col, bins=10):
        temp = df[[feature_col, target_col]].dropna().copy()
        if temp.empty: return []

        try:
            temp['bin'] = pd.qcut(temp[feature_col], bins, labels=False, duplicates='drop')
        except ValueError:
            return []
        temp = temp.dropna(subset=['bin'])
        if temp.empty:
            return []
        analysis = temp.groupby('bin')[target_col].mean()

        return [{"bin": int(b), "value": _finite_or_none(v)} for b, v in analysis.items()]

    def summarize_forward_returns(mask):
        fwd_1d = df.loc[mask, 'fwd_ret_1d'].dropna()
        fwd_5d = df.loc[mask, 'fwd_ret_5d'].dropna()
        return {
            "fwd_1d": _finite_or_none(fwd_1d.mean() if not fwd_1d.empty else None),
            "count_1d": int(len(fwd_1d)),
            "fwd_5d": _finite_or_none(fwd_5d.mean() if not fwd_5d.empty else None),
            "count_5d": int(len(fwd_5d)),
        }

    rsi_deciles_1d = get_binned_performance('rsi', 'fwd_ret_1d')
    rsi_deciles_5d = get_binned_performance('rsi', 'fwd_ret_5d')
    vol_deciles_1d = get_binned_performance('vol_20', 'fwd_ret_1d')

    kama_distance_analysis = {"fwd_1d": {}, "fwd_5d": {}}
    kama_cross_analysis = []

    for period in KAMA_PERIODS:
        kama_col = f'kama_{period}'
        gap_col = f'price_vs_kama_{period}'
        df[kama_col] = _kama(df['close'], window=period)
        df[gap_col] = (df['close'] / df[kama_col].replace(0, np.nan)) - 1.0

        kama_distance_analysis["fwd_1d"][str(period)] = get_binned_performance(gap_col, 'fwd_ret_1d')
        kama_distance_analysis["fwd_5d"][str(period)] = get_binned_performance(gap_col, 'fwd_ret_5d')

        prev_gap = df[gap_col].shift(1)
        valid_cross = df[gap_col].notna() & prev_gap.notna()
        bullish_cross = valid_cross & (prev_gap <= 0) & (df[gap_col] > 0)
        bearish_cross = valid_cross & (prev_gap >= 0) & (df[gap_col] < 0)

        for direction, mask in (("Bull", bullish_cross), ("Bear", bearish_cross)):
            summary = summarize_forward_returns(mask)
            kama_cross_analysis.append({
                "period": period,
                "direction": direction.lower(),
                "label": f"K{period} {direction}",
                **summary,
            })

    # 5. Seasonality
    df['month'] = df.index.month
    monthly_ret = df.groupby('month')['ret_1d'].mean() * 21 # Monthly approx
    seasonality = [{"month": int(m), "value": _finite_or_none(v)} for m, v in monthly_ret.items()]

    return {
        "metrics": {
            "volatility": _finite_or_none(vol_ann),
            "sharpe": _finite_or_none(sharpe),
            "max_drawdown": _finite_or_none(max_dd),
            "avg_daily_ret": _finite_or_none(returns.mean() if not returns.empty else None),
            "win_rate": _finite_or_none((returns > 0).mean() if not returns.empty else None)
        },
        "rsi_analysis": {
            "fwd_1d": rsi_deciles_1d,
            "fwd_5d": rsi_deciles_5d
        },
        "vol_analysis": {
            "fwd_1d": vol_deciles_1d
        },
        "kama_distance_analysis": kama_distance_analysis,
        "kama_cross_analysis": kama_cross_analysis,
        "seasonality": seasonality,
        "distribution": distribution
    }
