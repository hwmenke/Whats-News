"""
swing_core.py — Shared swing-trading metric engine.

Single source of truth for the indicator helpers and the swing-data /
setup-grade computation, used by both features_api.py (per-symbol routes)
and jeff_scanner.py (watchlist-wide setup scan).

Keeping these here avoids a circular import between the two modules and
guarantees the scanner and the per-symbol widgets agree on every number.
"""

import numpy as np
import pandas as pd

import database as db


# ── indicator helpers (pure numpy/pandas — no `ta` dependency) ─────────────────

def rsi(close, window=14):
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / window, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / window, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def macd_diff(close, fast=12, slow=26, signal=9):
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    return macd - macd.ewm(span=signal, adjust=False).mean()


def bb_pband(close, window=20, ndev=2.0):
    ma = close.rolling(window).mean()
    sd = close.rolling(window).std()
    upper = ma + ndev * sd
    lower = ma - ndev * sd
    return (close - lower) / (upper - lower).replace(0, np.nan)


def atr(high, low, close, window=14):
    pc = close.shift(1)
    tr = pd.concat([high - low, (high - pc).abs(), (low - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / window, adjust=False).mean()


def vars_score(close: pd.Series, bench_close: pd.Series, window: int = 63) -> float:
    """Volatility-Adjusted Relative Strength (Jeff Sun's VARS, scalar form).

    Excess return vs the benchmark over `window` bars, divided by the
    symbol's own return volatility over the same window — strong RS in a
    quiet stock scores higher than the same RS with violent swings.
    Returns 0.0 when there is insufficient overlapping data.
    """
    common = close.index.intersection(bench_close.index)
    if len(common) < window + 1:
        return 0.0
    c = close.loc[common].tail(window + 1)
    b = bench_close.loc[common].tail(window + 1)
    sym_ret   = float(c.iloc[-1] / c.iloc[0] - 1)
    bench_ret = float(b.iloc[-1] / b.iloc[0] - 1)
    daily_std = float(c.pct_change().dropna().std())
    if daily_std <= 0:
        return 0.0
    return round((sym_ret - bench_ret) / (daily_std * np.sqrt(window)), 3)


def kama(close: pd.Series, period: int = 10, fast: int = 2, slow: int = 30) -> pd.Series:
    """Kaufman Adaptive Moving Average."""
    vals = close.values.astype(float)
    n = len(vals)
    out = np.full(n, np.nan)
    if n <= period:
        return pd.Series(out, index=close.index)
    fast_sc = 2.0 / (fast + 1)
    slow_sc = 2.0 / (slow + 1)
    out[period - 1] = vals[period - 1]
    for i in range(period, n):
        change = abs(vals[i] - vals[i - period])
        vol = float(np.sum(np.abs(np.diff(vals[i - period:i + 1]))))
        er = change / vol if vol > 0 else 0.0
        sc = (er * (fast_sc - slow_sc) + slow_sc) ** 2
        out[i] = out[i - 1] + sc * (vals[i] - out[i - 1])
    return pd.Series(out, index=close.index)


# ── swing data ─────────────────────────────────────────────────────────────────

def swing_data_for(symbol: str, df: pd.DataFrame = None) -> dict:
    """Compute swing-data metrics for a symbol. Returns dict or raises ValueError.

    Pass an already-loaded `df` to avoid a second DB read (used by the scanner).
    """
    sym = symbol.upper()
    if df is None:
        df = db.get_ohlcv_df(sym, freq="daily", limit=260)
    if df.empty or len(df) < 20:
        raise ValueError(f"Insufficient data for {sym}")

    close  = df["close"]
    high   = df["high"]
    low    = df["low"]
    volume = df["volume"]

    last_close = float(close.iloc[-1])
    last_low   = float(low.iloc[-1])

    # ADR% — average daily range as % of close, 20-day
    adr_pct = float(((high - low) / close).tail(20).mean() * 100)

    # ATR-14
    atr14 = float(atr(high, low, close, 14).iloc[-1])

    # RVOL — today's volume vs 50-day average (excluding today)
    avg_vol_50 = float(volume.iloc[-51:-1].mean()) if len(volume) >= 51 else float(volume.iloc[:-1].mean())
    today_vol  = float(volume.iloc[-1])
    rvol = round(today_vol / avg_vol_50, 2) if avg_vol_50 > 0 else 0.0

    # ATR multiple from 50-MA
    ma50 = float(close.tail(50).mean())
    atr_mult_50ma = float((last_close - ma50) / atr14) if atr14 > 0 else 0.0

    # LoD distance as fraction of ATR (article rule: >0.6 = don't enter)
    lod_dist      = last_close - last_low
    lod_dist_atr  = round(lod_dist / atr14, 3) if atr14 > 0 else 0.0

    # VCP score — how much current 5-bar range has contracted vs 20-bar range
    ranges_20 = (high - low).tail(20)
    ranges_5  = (high - low).tail(5)
    r20_std   = float(ranges_20.std())
    vcp_score = float((ranges_20.mean() - ranges_5.mean()) / r20_std) if r20_std > 0 else 0.0

    # 52-week range position
    high_52w  = float(high.tail(252).max())
    low_52w   = float(low.tail(252).min())
    rng       = high_52w - low_52w
    range_pos = round((last_close - low_52w) / rng, 3) if rng > 0 else 0.5

    # 20-day return
    ret_20d = round((last_close / float(close.iloc[-21]) - 1) * 100, 2) if len(close) >= 21 else None

    # RSI at 7, 14, 21 periods
    rsi_7  = round(float(rsi(close, 7).iloc[-1]),  1) if len(close) >= 8  else None
    rsi_14 = round(float(rsi(close, 14).iloc[-1]), 1) if len(close) >= 15 else None
    rsi_21 = round(float(rsi(close, 21).iloc[-1]), 1) if len(close) >= 22 else None

    # KAMA alignment (10 / 20 / 50 period)
    def _kama_stat(k_series):
        v = float(k_series.iloc[-1])
        if np.isnan(v):
            return None
        valid = k_series.dropna()
        v5 = float(valid.iloc[-5]) if len(valid) >= 5 else v
        return {
            "value":    round(v, 2),
            "above":    last_close > v,
            "dist_atr": round((last_close - v) / atr14, 2) if atr14 > 0 else 0.0,
            "slope":    "up" if v > v5 else "down" if v < v5 else "flat",
        }

    kama10_stat = _kama_stat(kama(close, 10))
    kama20_stat = _kama_stat(kama(close, 20))
    kama50_stat = _kama_stat(kama(close, 50))
    kama_alignment = sum(1 for s in [kama10_stat, kama20_stat, kama50_stat] if s and s["above"])

    # Pocket pivot — up day whose volume beats every down-day volume of the
    # prior 10 sessions (O'Neil/Morales institutional-accumulation signal)
    pocket_pivot = False
    if len(close) >= 12:
        up_today   = last_close > float(close.iloc[-2])
        prior      = df.iloc[-11:-1]
        prev_close = df["close"].shift(1).iloc[-11:-1]
        down_mask  = prior["close"].values < prev_close.values
        down_vols  = prior["volume"].values[down_mask]
        max_down   = float(down_vols.max()) if len(down_vols) else 0.0
        pocket_pivot = bool(up_today and today_vol > max_down and max_down > 0)

    # Volume dry-up — supply contraction inside a base
    vol_dryup = bool(avg_vol_50 > 0 and today_vol < 0.5 * avg_vol_50)

    # 200-day MA declining — structural overhead (hard no-trade rule)
    ma200_declining = None
    if len(close) >= 220:
        ma200_now  = float(close.tail(200).mean())
        ma200_back = float(close.iloc[-220:-20].mean())
        ma200_declining = ma200_now < ma200_back

    # Average dollar volume (20-day) — liquidity / position-size cap
    avg_dollar_vol = float((close * volume).tail(20).mean())

    return {
        "symbol":        sym,
        "last_close":    round(last_close, 2),
        "adr_pct":       round(adr_pct, 2),
        "atr_14":        round(atr14, 4),
        "rvol":          rvol,
        "atr_mult_50ma": round(atr_mult_50ma, 2),
        "ma50":          round(ma50, 2),
        "above_50ma":    last_close > ma50,
        "lod_dist_atr":  lod_dist_atr,
        "vcp_score":     round(vcp_score, 2),
        "range_pos_52w": range_pos,
        "ret_20d":       ret_20d,
        "too_extended":  atr_mult_50ma > 4.0,
        "lod_too_far":   lod_dist_atr > 0.6,
        "low_rvol":      rvol < 0.7,
        "rsi_7":         rsi_7,
        "rsi_14":        rsi_14,
        "rsi_21":        rsi_21,
        "kama10":        kama10_stat,
        "kama20":        kama20_stat,
        "kama50":        kama50_stat,
        "kama_alignment":kama_alignment,
        "pocket_pivot":  pocket_pivot,
        "vol_dryup":     vol_dryup,
        "ma200_declining": ma200_declining,
        "avg_dollar_vol": round(avg_dollar_vol, 0),
    }


def grade_from_swing(sd: dict) -> dict:
    """Compute A/B/C setup grade from swing data dict. Returns {grade, score, factors}."""
    score   = 0
    factors = []

    # ATR extension from 50-MA (article: >4x = hard block)
    ext = sd["atr_mult_50ma"]
    if ext < 0:
        factors.append({"label": "Below 50-MA", "bull": False, "pts": 0})
    elif ext < 2:
        score += 2
        factors.append({"label": f"Not extended ({ext:.1f}×)", "bull": True, "pts": 2})
    elif ext < 4:
        score += 1
        factors.append({"label": f"Mildly extended ({ext:.1f}×)", "bull": True, "pts": 1})
    else:
        score -= 2
        factors.append({"label": f"Too extended ({ext:.1f}× > 4×)", "bull": False, "pts": -2})

    # RVOL
    rv = sd["rvol"]
    if rv >= 1.5:
        score += 2
        factors.append({"label": f"Strong RVOL {rv:.1f}×", "bull": True, "pts": 2})
    elif rv >= 1.0:
        score += 1
        factors.append({"label": f"RVOL {rv:.1f}×", "bull": True, "pts": 1})
    else:
        score -= 1
        factors.append({"label": f"Low RVOL {rv:.1f}×", "bull": False, "pts": -1})

    # LoD distance (article: >0.6 ATR = don't enter)
    ld = sd["lod_dist_atr"]
    if ld < 0.3:
        score += 2
        factors.append({"label": "Tight LoD", "bull": True, "pts": 2})
    elif ld < 0.6:
        score += 1
        factors.append({"label": f"Acceptable LoD ({ld:.2f}×)", "bull": True, "pts": 1})
    else:
        score -= 1
        factors.append({"label": f"LoD too far ({ld:.2f}×)", "bull": False, "pts": -1})

    # VCP — volatility contraction
    vcp = sd["vcp_score"]
    if vcp > 1.5:
        score += 2
        factors.append({"label": "VCP detected", "bull": True, "pts": 2})
    elif vcp > 0.5:
        score += 1
        factors.append({"label": "Mild contraction", "bull": True, "pts": 1})
    else:
        factors.append({"label": "No contraction", "bull": False, "pts": 0})

    # 52-week range position (leadership indicator)
    rp = sd["range_pos_52w"]
    if rp >= 0.80:
        score += 2
        factors.append({"label": f"Near 52W high ({rp*100:.0f}%ile)", "bull": True, "pts": 2})
    elif rp >= 0.60:
        score += 1
        factors.append({"label": f"Upper range ({rp*100:.0f}%ile)", "bull": True, "pts": 1})
    else:
        factors.append({"label": f"Lower range ({rp*100:.0f}%ile)", "bull": False, "pts": 0})

    grade = "A" if score >= 7 else "B" if score >= 3 else "C"
    return {"grade": grade, "score": score, "factors": factors}
