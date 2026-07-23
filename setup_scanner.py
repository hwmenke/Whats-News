"""
setup_scanner.py — Breakout / breakdown *setup* detector.

Where scanner.py reports raw per-timeframe technicals, this module classifies
each symbol into an actionable chart setup and scores how clean it is:

  BASE_COILING       consolidation base — Bollinger squeeze + ATR contraction +
                     tight range, constructive near the highs. No trigger yet.
  BASE_BREAKOUT      a coil that just resolved UP — close clears the base high,
                     ideally on a volume expansion.
  BASE_BREAKDOWN     a coil that just resolved DOWN — close breaks the base low.
  PARABOLIC_UP       extended/parabolic advance — steep ROC, price far above the
                     50-day MA, RSI hot. Exhaustion risk or momentum continuation.
  PARABOLIC_DOWN     the mirror image — waterfall decline, deeply oversold.
  PARABOLIC_REVERSAL an extended name rolling over (lost its fast MA / prior low),
                     or a washed-out name reclaiming it.

Everything is computed from daily OHLCV already stored in SQLite (no live calls
at scan time), so a "big scan" is just: bulk-fetch a universe once, then scan.

Each result row carries a `direction` (up / down / watch), a 0-100 `score`
(sortable — higher = cleaner setup), and a `trigger` flag (True once the setup
has actually fired vs. still setting up).
"""

import numpy as np
import pandas as pd
from concurrent.futures import ThreadPoolExecutor

import database as db

# ── Tunable thresholds ────────────────────────────────────────────────────────
BASE_LOOKBACK      = 20      # bars that define the consolidation range
SQUEEZE_PCTL       = 20.0    # BB-bandwidth percentile at/below this = "squeeze"
ATR_CONTRACT_RATIO = 0.85    # ATR now < 0.85 × ATR ~20 bars ago = contracting
TIGHT_RANGE_PCT    = 12.0    # (range high-low over lookback)/price, % — tight base
NEAR_HIGH_PCT      = -15.0   # within 15% of the 52w high = constructive
VOL_SURGE          = 1.5     # today vol / 20d avg vol for a confirmed breakout
PARA_ROC20         = 30.0    # 20-day rate-of-change, % — parabolic threshold
PARA_EXT50         = 20.0    # price vs 50-SMA, % — how far extended
PARA_RSI_HOT       = 75.0    # RSI(14) upper extreme
PARA_RSI_COLD      = 25.0    # RSI(14) lower extreme
MIN_BARS           = 60      # need this much daily history to classify

SETUP_LABELS = {
    "BASE_COILING":       "Base · coiling",
    "BASE_BREAKOUT":      "Base · breakout",
    "BASE_BREAKDOWN":     "Base · breakdown",
    "PARABOLIC_UP":       "Parabolic · extended up",
    "PARABOLIC_DOWN":     "Parabolic · extended down",
    "PARABOLIC_REVERSAL": "Parabolic · reversal",
}


# ── small helpers ─────────────────────────────────────────────────────────────

def _f(v, nd=2):
    """numpy/NaN-safe float rounder → Python float or None."""
    try:
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return None
        f = float(v)
        if np.isnan(f) or np.isinf(f):
            return None
        return round(f, nd)
    except (TypeError, ValueError):
        return None


def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)
    ag    = gain.ewm(alpha=1.0 / n, adjust=False).mean()
    al    = loss.ewm(alpha=1.0 / n, adjust=False).mean()
    rs    = ag / al.replace(0, np.nan)
    rsi   = 100.0 - (100.0 / (1.0 + rs))
    # A window with no down-moves (e.g. a vertical/parabolic run) has avg-loss 0
    # → RSI is 100, not NaN. A perfectly flat window is neutral 50.
    rsi = rsi.where(~((al == 0) & (ag > 0)), 100.0)
    rsi = rsi.where(~((al == 0) & (ag == 0)), 50.0)
    return rsi


def _atr(high, low, close, n=14) -> pd.Series:
    prev_c = close.shift(1)
    tr = pd.concat([high - low,
                    (high - prev_c).abs(),
                    (low - prev_c).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / n, adjust=False).mean()


def _clip01(x):
    return max(0.0, min(1.0, x))


# ── per-symbol classification ─────────────────────────────────────────────────

def detect_one(sym: str):
    """Classify a single symbol's daily chart. Returns a row dict or None."""
    df = db.get_ohlcv_df(sym, "daily", limit=300)
    if df is None or df.empty or len(df) < MIN_BARS:
        return None

    close, high, low, vol = df["close"], df["high"], df["low"], df["volume"]
    n = len(close)

    price = float(close.iloc[-1])
    if not np.isfinite(price) or price <= 0:
        return None
    prev = float(close.iloc[-2])
    chg = (price / prev - 1.0) * 100 if prev else None

    # Moving averages
    sma50  = close.rolling(min(50, n)).mean()
    sma200 = close.rolling(min(200, n)).mean()
    ema10  = close.ewm(span=10, adjust=False).mean()
    ext50  = (price / sma50.iloc[-1] - 1.0) * 100 if sma50.iloc[-1] else None   # % vs 50-SMA
    ext200 = (price / sma200.iloc[-1] - 1.0) * 100 if sma200.iloc[-1] else None

    # RSI
    rsi = float(_rsi(close, 14).iloc[-1])

    # ATR% and contraction
    atr = _atr(high, low, close, 14)
    atr_now = float(atr.iloc[-1])
    atr_pct = atr_now / price * 100
    atr_ref_idx = max(0, n - 1 - BASE_LOOKBACK)
    atr_ref = float(atr.iloc[atr_ref_idx])
    atr_contract = atr_ref > 0 and atr_now < atr_ref * ATR_CONTRACT_RATIO
    atr_ratio = atr_now / atr_ref if atr_ref > 0 else None   # <1 = contracting

    # Bollinger bandwidth + its 6-month percentile (squeeze detector)
    bb_n   = min(20, n - 1)
    bb_mid = close.rolling(bb_n).mean()
    bb_std = close.rolling(bb_n).std(ddof=0)
    bb_bw  = (4 * bb_std) / bb_mid.replace(0, np.nan)          # (upper-lower)/mid
    bw_win = bb_bw.dropna().tail(126)
    cur_bw = float(bb_bw.iloc[-1]) if np.isfinite(bb_bw.iloc[-1]) else None
    if cur_bw is not None and len(bw_win) >= 20:
        bw_pctl = float((bw_win < cur_bw).sum()) / len(bw_win) * 100.0
    else:
        bw_pctl = None
    squeeze = bw_pctl is not None and bw_pctl <= SQUEEZE_PCTL

    # Consolidation base range (exclude today so a breakout can clear it)
    base_hi = float(high.iloc[-(BASE_LOOKBACK + 1):-1].max())
    base_lo = float(low.iloc[-(BASE_LOOKBACK + 1):-1].min())
    range_pct = (base_hi - base_lo) / price * 100 if price else None
    tight = range_pct is not None and range_pct <= TIGHT_RANGE_PCT

    # 52-week high distance
    hi_252 = float(close.rolling(min(252, n)).max().iloc[-1])
    dist_hi = (price / hi_252 - 1.0) * 100 if hi_252 else None
    near_high = dist_hi is not None and dist_hi >= NEAR_HIGH_PCT

    # Momentum
    roc20 = (price / float(close.iloc[-min(21, n)]) - 1.0) * 100
    roc5  = (price / float(close.iloc[-min(6, n)]) - 1.0) * 100

    # Volume
    v20 = float(vol.rolling(20).mean().iloc[-1])
    vol_ratio = float(vol.iloc[-1]) / v20 if v20 and np.isfinite(v20) and v20 > 0 else None

    # Extension state now and a few bars back (for reversal detection)
    def _extended_up_at(i):
        s50 = sma50.iloc[i]
        r = (float(close.iloc[i]) / float(close.iloc[i - 20]) - 1.0) * 100 if i - 20 >= 0 else 0
        e = (float(close.iloc[i]) / s50 - 1.0) * 100 if s50 else 0
        rv = float(_rsi(close, 14).iloc[i])
        return r >= PARA_ROC20 and e >= PARA_EXT50 and rv >= PARA_RSI_HOT
    def _extended_dn_at(i):
        s50 = sma50.iloc[i]
        r = (float(close.iloc[i]) / float(close.iloc[i - 20]) - 1.0) * 100 if i - 20 >= 0 else 0
        e = (float(close.iloc[i]) / s50 - 1.0) * 100 if s50 else 0
        rv = float(_rsi(close, 14).iloc[i])
        return r <= -PARA_ROC20 and e <= -PARA_EXT50 and rv <= PARA_RSI_COLD

    extended_up = _extended_up_at(n - 1)
    extended_dn = _extended_dn_at(n - 1)
    was_ext_up  = any(_extended_up_at(n - 1 - k) for k in range(1, 6) if n - 1 - k >= 20)
    was_ext_dn  = any(_extended_dn_at(n - 1 - k) for k in range(1, 6) if n - 1 - k >= 20)

    lost_fast_ma  = price < float(ema10.iloc[-1])
    reclaim_fast  = price > float(ema10.iloc[-1])

    # ── classify (priority order: fired triggers first, then setups) ──────────
    setup = direction = None
    score = 0.0
    trigger = False

    breakout_up   = tight and price > base_hi and (vol_ratio is None or vol_ratio >= 1.0)
    breakdown_dn  = tight and price < base_lo

    if was_ext_up and (lost_fast_ma or price < float(low.iloc[-2])):
        setup, direction, trigger = "PARABOLIC_REVERSAL", "down", True
        ext_mag = _clip01(abs(ext50 or 0) / 40.0)
        roll = _clip01((float(high.iloc[-2]) - price) / (atr_now or 1))
        score = 55 + 25 * ext_mag + 20 * roll

    elif was_ext_dn and reclaim_fast:
        setup, direction, trigger = "PARABOLIC_REVERSAL", "up", True
        ext_mag = _clip01(abs(ext50 or 0) / 40.0)
        score = 50 + 25 * ext_mag + 15 * _clip01((price - float(high.iloc[-2])) / (atr_now or 1))

    elif breakout_up:
        setup, direction, trigger = "BASE_BREAKOUT", "up", True
        base_quality = 0.4 * (1 - _clip01((range_pct or 12) / TIGHT_RANGE_PCT)) \
                       + 0.3 * (1 if squeeze else 0.3) \
                       + 0.3 * (1 if near_high else 0.4)
        vol_boost = _clip01(((vol_ratio or 1) - 1) / (VOL_SURGE - 1))
        score = 45 + 35 * base_quality + 20 * vol_boost

    elif breakdown_dn:
        setup, direction, trigger = "BASE_BREAKDOWN", "down", True
        base_quality = 0.5 * (1 - _clip01((range_pct or 12) / TIGHT_RANGE_PCT)) \
                       + 0.5 * (1 if squeeze else 0.3)
        vol_boost = _clip01(((vol_ratio or 1) - 1) / (VOL_SURGE - 1))
        score = 45 + 35 * base_quality + 20 * vol_boost

    elif extended_up:
        setup, direction, trigger = "PARABOLIC_UP", "up", False
        score = 40 + 25 * _clip01(roc20 / 60.0) + 20 * _clip01((ext50 or 0) / 40.0) \
                + 15 * _clip01((rsi - PARA_RSI_HOT) / 20.0)

    elif extended_dn:
        setup, direction, trigger = "PARABOLIC_DOWN", "down", False
        score = 40 + 25 * _clip01(-roc20 / 60.0) + 20 * _clip01(-(ext50 or 0) / 40.0) \
                + 15 * _clip01((PARA_RSI_COLD - rsi) / 20.0)

    elif squeeze and tight:
        # A coiled base: BB squeeze + tight range are the essence; ATR contraction
        # and proximity to the highs sharpen the score rather than gate it.
        setup, direction, trigger = "BASE_COILING", "watch", False
        tightness = 1 - _clip01((range_pct or 12) / TIGHT_RANGE_PCT)
        squeeze_q = 1 - _clip01((bw_pctl or SQUEEZE_PCTL) / SQUEEZE_PCTL)
        contract  = _clip01((1 - (atr_ratio or 1)) / 0.4) if atr_contract else 0.0
        proximity = 1 if near_high else 0.4
        score = 25 + 30 * squeeze_q + 20 * contract + 15 * tightness + 10 * proximity

    else:
        return None   # no clean setup

    return {
        "symbol":    sym,
        "price":     _f(price, 2),
        "chg":       _f(chg, 2),
        "setup":     setup,
        "setup_label": SETUP_LABELS[setup],
        "direction": direction,
        "score":     _f(score, 1),
        "trigger":   bool(trigger),
        "rsi":       _f(rsi, 1),
        "roc20":     _f(roc20, 1),
        "roc5":      _f(roc5, 1),
        "ext50":     _f(ext50, 1),
        "ext200":    _f(ext200, 1),
        "atr_pct":   _f(atr_pct, 2),
        "atr_ratio": _f(atr_ratio, 2),
        "bw_pctl":   _f(bw_pctl, 0),
        "dist_hi":   _f(dist_hi, 1),
        "vol_ratio": _f(vol_ratio, 2),
        "range_pct": _f(range_pct, 1),
        "base_hi":   _f(base_hi, 2),
        "base_lo":   _f(base_lo, 2),
    }


def scan_setups(symbols: list, max_workers: int = 8) -> list:
    """Run detect_one over many symbols; drop the ones with no setup."""
    rows = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for r in pool.map(_safe_detect, symbols):
            if r is not None:
                rows.append(r)
    # cleanest setups first
    rows.sort(key=lambda r: -(r.get("score") or 0))
    return rows


def _safe_detect(sym):
    try:
        return detect_one(sym)
    except Exception:
        return None
