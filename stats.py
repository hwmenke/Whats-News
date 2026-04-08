"""
stats.py - Compute statistical analysis and factor quintiles for a symbol.
"""

import numpy as np
import pandas as pd
import database as db
import ta

def _safe(val):
    if val is None: return None
    try:
        if np.isnan(val): return None
    except: pass
    if isinstance(val, (np.integer,)): return int(val)
    if isinstance(val, (np.floating,)): return float(val)
    return val

def compute_stats(symbol: str) -> dict:
    df = db.get_ohlcv_df(symbol, "daily")
    if df.empty:
        return {"error": "No data found"}

    # 1. Base Returns
    df['ret_1d'] = df['close'].pct_change()
    df['fwd_ret_1d'] = df['ret_1d'].shift(-1)
    df['fwd_ret_5d'] = df['close'].pct_change(5).shift(-5)

    # 2. Key Metrics
    returns = df['ret_1d'].dropna()
    vol_ann = returns.std() * np.sqrt(252)
    sharpe = (returns.mean() / returns.std() * np.sqrt(252)) if returns.std() != 0 else 0
    
    cumulative = (1 + returns).cumprod()
    peak = cumulative.cummax()
    drawdown = (cumulative - peak) / peak
    max_dd = drawdown.min()

    # 3. Features for Quintiles
    df['rsi'] = ta.momentum.RSIIndicator(df['close'], window=14).rsi()
    # Volatility Feature (Relative Volatility Index or just standard dev)
    df['vol_20'] = df['ret_1d'].rolling(20).std() * np.sqrt(252)
    
    # 4. Feature Binning (Deciles)
    def get_binned_performance(feature_col, target_col, bins=10):
        temp = df[[feature_col, target_col]].dropna()
        if temp.empty: return []
        
        temp['bin'] = pd.qcut(temp[feature_col], bins, labels=False, duplicates='drop')
        analysis = temp.groupby('bin')[target_col].mean()
        
        return [{"bin": int(b), "value": _safe(v)} for b, v in analysis.items()]

    rsi_deciles_1d = get_binned_performance('rsi', 'fwd_ret_1d')
    rsi_deciles_5d = get_binned_performance('rsi', 'fwd_ret_5d')
    vol_deciles_1d = get_binned_performance('vol_20', 'fwd_ret_1d')

    # 5. Seasonality
    df['month'] = df.index.month
    monthly_ret = df.groupby('month')['ret_1d'].mean() * 21 # Monthly approx
    seasonality = [{"month": int(m), "value": _safe(v)} for m, v in monthly_ret.items()]

    # 6. Returns Distribution
    counts, bins = np.histogram(returns, bins=30)
    dist = [{"bin": _safe((bins[i] + bins[i+1])/2), "count": int(counts[i])} for i in range(len(counts))]

    return {
        "metrics": {
            "volatility": _safe(vol_ann),
            "sharpe": _safe(sharpe),
            "max_drawdown": _safe(max_dd),
            "avg_daily_ret": _safe(returns.mean()),
            "win_rate": _safe((returns > 0).mean())
        },
        "rsi_analysis": {
            "fwd_1d": rsi_deciles_1d,
            "fwd_5d": rsi_deciles_5d
        },
        "vol_analysis": {
            "fwd_1d": vol_deciles_1d
        },
        "seasonality": seasonality,
        "distribution": dist
    }
