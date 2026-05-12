"""
scanner.py — Multi-timeframe watchlist scanner.

Metrics computed per symbol × (daily / weekly / monthly):
  RSI        : rsi_7, rsi_14, rsi_21
  KAMA ratios: p_kf_pct  — percentile rank of close/KAMA_fast
               p_km_pct  — percentile rank of close/KAMA_medium
               kf_km     — (KAMA_fast / KAMA_medium − 1) × 100  (cross %)
  Momentum   : roc_1m, roc_3m, roc_6m  (rate of change)
               bb_b      — Bollinger %B
  Volatility : atr_pct   — ATR(14) as % of price
  Structure  : vol_ratio — 5-bar / 20-bar avg volume
               dist_hi   — % below lookback-period high  (0 = at high)
               dist_sma  — % above/below 200-bar SMA

Timeframe lookbacks used for percentile rank windows:
  daily  → 252 bars   (~1 year)
  weekly →  52 bars   (~1 year)
  monthly→  36 bars   (~3 years)

Also includes S&P 500 bulk-fetch and signal-based scanner (local features).
"""

import numpy as np
import pandas as pd
import ta
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import database as db
import data_fetcher as fetcher
from shared_indicators import _kama, _rsi
from config import KAMA_PERIODS

# ── Module-level bulk-fetch status (Lock-guarded) ────────────────────────────
_fetch_lock = threading.Lock()
_fetch_status = {
    "running":  False,
    "progress": 0,
    "total":    0,
    "done":     0,
    "summary":  None,
}


def get_fetch_status() -> dict:
    with _fetch_lock:
        return dict(_fetch_status)


def _update_fetch_status(**kwargs):
    with _fetch_lock:
        _fetch_status.update(kwargs)


# ── type helpers ─────────────────────────────────────────────────────────────

def _safe(v):
    """Coerce numpy scalar → Python native; None on NaN."""
    if v is None:
        return None
    try:
        if np.isnan(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating):
        return round(float(v), 4)
    return v


def _last(s: pd.Series):
    """Return last non-NaN value of a Series, or None."""
    valid = s.dropna()
    return _safe(valid.iloc[-1]) if len(valid) else None


# ── indicator implementations ─────────────────────────────────────────────────
# _kama and _rsi are imported from shared_indicators


def _pct_rank(series: pd.Series, lookback: int) -> pd.Series:
    """
    Rolling percentile rank: where does the current bar's value sit
    within the previous `lookback` bars?  Returns 0–100.
    Uses numpy searchsorted for speed.
    """
    arr = series.values.astype(float)
    n   = len(arr)
    out = np.full(n, np.nan)
    for i in range(lookback, n):
        cur = arr[i]
        if np.isnan(cur):
            continue
        window = arr[i - lookback: i]
        valid  = window[~np.isnan(window)]
        if len(valid) == 0:
            continue
        out[i] = float(
            np.searchsorted(np.sort(valid), cur, side='right')
        ) / len(valid) * 100.0
    return pd.Series(out, index=series.index)


# ── per-timeframe computation ─────────────────────────────────────────────────

def _compute_tf(df: pd.DataFrame, lookback: int, roc_periods: tuple | None = None):
    """Compute all scanner metrics for one symbol × timeframe.
    roc_periods = (1m_bars, 3m_bars, 6m_bars) — pass explicitly for non-daily data.
    """
    min_bars = max(22, lookback // 8)
    if df is None or len(df) < min_bars:
        return None

    close = df['close']
    high  = df['high']
    low   = df['low']
    vol   = df['volume']

    # ── RSI ──────────────────────────────────────────────────────────
    rsi7  = _rsi(close, 7)
    rsi14 = _rsi(close, 14)
    rsi21 = _rsi(close, 21)

    # ── KAMA baselines ────────────────────────────────────────────────
    kf = _kama(close, window=10, fast=2, slow=30)   # fast
    km = _kama(close, window=20, fast=2, slow=60)   # medium

    kf_safe = kf.replace(0, np.nan)
    km_safe = km.replace(0, np.nan)

    p_kf  = close / kf_safe                         # price / KAMA_fast
    p_km  = close / km_safe                         # price / KAMA_medium
    kf_km = (kf_safe / km_safe - 1.0) * 100        # cross (%)

    p_kf_pct = _pct_rank(p_kf,  lookback)
    p_km_pct = _pct_rank(p_km,  lookback)

    # ── Bollinger %B ──────────────────────────────────────────────────
    bb_n   = min(20, len(close) - 1)
    bb_mid = close.rolling(bb_n).mean()
    bb_std = close.rolling(bb_n).std(ddof=0)
    bb_b   = (close - (bb_mid - 2 * bb_std)) / (4 * bb_std.replace(0, np.nan))

    # ── ATR% ──────────────────────────────────────────────────────────
    prev_c = close.shift(1)
    tr     = pd.concat([
                 high - low,
                 (high - prev_c).abs(),
                 (low  - prev_c).abs(),
             ], axis=1).max(axis=1)
    atr_n  = min(14, len(tr) - 1)
    atr    = tr.ewm(alpha=1.0 / atr_n, adjust=False).mean()
    atr_pct = atr / close.replace(0, np.nan) * 100

    # ── Rate of change ────────────────────────────────────────────────
    nb = len(close)
    if roc_periods is not None:
        p1, p2, p3 = (min(max(1, p), nb - 1) for p in roc_periods)
    else:
        p1 = min(max(1, lookback // 12), nb - 1)
        p2 = min(max(1, lookback //  4), nb - 1)
        p3 = min(max(1, lookback //  2), nb - 1)
    roc_1m = close.pct_change(p1) * 100
    roc_3m = close.pct_change(p2) * 100
    roc_6m = close.pct_change(p3) * 100

    # ── Volume ratio (5-bar / 20-bar avg) ─────────────────────────────
    v5        = vol.rolling(5).mean()
    v20       = vol.rolling(20).mean()
    vol_ratio = v5 / v20.replace(0, np.nan)

    # ── Distance from period high ─────────────────────────────────────
    hi       = close.rolling(min(lookback, nb)).max()
    dist_hi  = (close / hi.replace(0, np.nan) - 1.0) * 100   # 0 = at high

    # ── Distance from 200-bar SMA ─────────────────────────────────────
    sma_n    = min(200, nb - 1)
    sma200   = close.rolling(max(2, sma_n)).mean()
    dist_sma = (close / sma200.replace(0, np.nan) - 1.0) * 100

    # ── Trend score (RSI + MACD + CCI composite, range -3...+3) ──────────
    ema12     = close.ewm(span=12, adjust=False).mean()
    ema26     = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    macd_hist = macd_line - macd_line.ewm(span=9, adjust=False).mean()

    hlc3  = (df['high'] + df['low'] + close) / 3.0
    sma20 = hlc3.rolling(20).mean()
    mad20 = hlc3.rolling(20).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
    cci   = (hlc3 - sma20) / (0.015 * mad20.replace(0, np.nan))

    _rsi_sc   = np.where(rsi14 > 80, 0, np.where(rsi14 > 50,  1, -1))
    _cci_sc   = np.where(cci   > 0,  1, -1)
    _macd_sc  = np.where(macd_hist > 0, 1, -1)
    _trend_s  = pd.Series(
        _rsi_sc + _cci_sc + _macd_sc,
        index=close.index, dtype=float
    )
    _trend_s[rsi14.isna() | cci.isna() | macd_hist.isna()] = np.nan

    return {
        'rsi_7':      _last(rsi7),
        'rsi_14':     _last(rsi14),
        'rsi_21':     _last(rsi21),
        'p_kf_pct':   _last(p_kf_pct),
        'p_km_pct':   _last(p_km_pct),
        'kf_km':      _last(kf_km),
        'bb_b':       _last(bb_b),
        'atr_pct':    _last(atr_pct),
        'roc_1m':     _last(roc_1m),
        'roc_3m':     _last(roc_3m),
        'roc_6m':     _last(roc_6m),
        'vol_ratio':  _last(vol_ratio),
        'dist_hi':    _last(dist_hi),
        'dist_sma':   _last(dist_sma),
        'trend_score': _last(_trend_s),
    }


# ── S&P 500 bulk-fetch helpers ────────────────────────────────────────────────

def get_sp500_tickers() -> pd.DataFrame:
    """
    Scrape S&P 500 constituents from Wikipedia.
    Returns a DataFrame with at least 'Symbol' and 'Security' columns.
    Replaces '.' with '-' in symbols for yfinance compatibility.
    """
    url    = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    tables = pd.read_html(url)
    df     = tables[0]

    # Standardise column names
    df.columns = [c.strip() for c in df.columns]

    # The ticker column may be named 'Symbol' or 'Ticker symbol'
    for col in df.columns:
        if "symbol" in col.lower() or "ticker" in col.lower():
            df = df.rename(columns={col: "Symbol"})
            break

    df["Symbol"] = df["Symbol"].str.replace(".", "-", regex=False)
    return df


def bulk_fetch_sp500(max_workers: int = 5, force_refresh: bool = False) -> dict:
    """
    Add all S&P 500 tickers to the DB and fetch their OHLCV data.
    Skips symbols fetched within the last 23 hours unless force_refresh=True.
    Updates the module-level _fetch_status dict throughout (Lock-guarded).
    """
    try:
        sp500_df = get_sp500_tickers()
        symbols  = sp500_df["Symbol"].tolist()
    except Exception as e:
        _update_fetch_status(running=False)
        return {"error": f"Failed to fetch S&P 500 list: {str(e)}"}

    _update_fetch_status(total=len(symbols), done=0, progress=0)

    # Ensure all symbols are in the DB first
    for sym in symbols:
        db.add_symbol(sym)

    results = {"total": len(symbols), "success": 0, "skipped": 0, "failed": 0, "errors": []}

    def _fetch_one(sym):
        if not force_refresh and db.is_recently_fetched(sym):
            return ("skipped", sym, None)
        try:
            res = fetcher.fetch_and_store(sym)
            if "error" in res:
                return ("failed", sym, res["error"])
            return ("success", sym, None)
        except Exception as e:
            return ("failed", sym, str(e))

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_fetch_one, sym): sym for sym in symbols}
        for future in as_completed(futures):
            status_str, sym, err = future.result()
            results[status_str] += 1
            if err:
                results["errors"].append({"symbol": sym, "error": err})

            with _fetch_lock:
                _fetch_status["done"] += 1
                total = _fetch_status["total"] or 1
                _fetch_status["progress"] = round(_fetch_status["done"] / total * 100, 1)

    _update_fetch_status(running=False, summary=results)
    return results


# ── Signal-based scanner (local) ──────────────────────────────────────────────

def _scan_one(sym: str):
    """
    Compute scanner signals for a single symbol using DB data only.
    Returns None if there is not enough data.
    """
    df = db.get_ohlcv_df(sym, "daily", limit=300)
    if df.empty or len(df) < 60:
        return None

    close = df["close"]
    high  = df["high"]
    low   = df["low"]
    vol   = df["volume"]

    try:
        # Price
        price = float(close.iloc[-1])

        # Week return (5 trading days)
        week_ret = float(close.pct_change(5).iloc[-1]) if len(close) >= 6 else None

        # RSI
        rsi_s = ta.momentum.RSIIndicator(close, window=14).rsi()
        rsi   = float(rsi_s.iloc[-1]) if not np.isnan(rsi_s.iloc[-1]) else None

        # Trend score (RSI + CCI + MACD like in indicators.py)
        cci_s    = ta.trend.CCIIndicator(high, low, close, window=20).cci()
        macd_ind = ta.trend.MACD(close, window_slow=26, window_fast=12, window_sign=9)
        macd_h   = macd_ind.macd_diff()

        rsi_score  = float(np.where(rsi_s > 80, 0, np.where(rsi_s > 50, 1, -1)).tolist()[-1])
        cci_score  = float(np.where(cci_s > 0, 1, -1).tolist()[-1])
        macd_score = float(np.where(macd_h > 0, 1, -1).tolist()[-1])

        all_nan = rsi_s.isna().iloc[-1] or cci_s.isna().iloc[-1] or macd_h.isna().iloc[-1]
        trend_score = None if all_nan else int(rsi_score + cci_score + macd_score)

        # KAMA distances
        kama_vals = {}
        for period in KAMA_PERIODS:
            k_s = _kama(close, window=period)
            k_last = k_s.iloc[-1]
            if not np.isnan(k_last) and k_last != 0:
                kama_vals[period] = (price / k_last - 1.0) * 100.0  # as %
            else:
                kama_vals[period] = None

        # Volume ratio
        vol_ma20 = vol.rolling(20).mean().iloc[-1]
        vol_ratio = float(vol.iloc[-1] / vol_ma20) if vol_ma20 and not np.isnan(vol_ma20) and vol_ma20 != 0 else None

        # Bollinger Band %B
        bb = ta.volatility.BollingerBands(close, window=20, window_dev=2)
        bb_upper = bb.bollinger_hband().iloc[-1]
        bb_lower = bb.bollinger_lband().iloc[-1]
        bb_range = bb_upper - bb_lower
        bb_pct   = float((price - bb_lower) / bb_range) if bb_range and bb_range != 0 else None

        # MACD histogram latest
        macd_hist_val = float(macd_h.iloc[-1]) if not np.isnan(macd_h.iloc[-1]) else None

        # ── Signals ──────────────────────────────────────────────────────────
        signals = []

        if rsi is not None:
            if rsi < 30:
                signals.append("RSI_OVERSOLD")
            if rsi > 70:
                signals.append("RSI_OVERBOUGHT")

        # KAMA crossover signals (k10 vs k20)
        k10_s = _kama(close, window=10)
        k20_s = _kama(close, window=20)
        if len(k10_s) >= 2 and len(k20_s) >= 2:
            k10_prev, k10_curr = float(k10_s.iloc[-2]), float(k10_s.iloc[-1])
            k20_prev, k20_curr = float(k20_s.iloc[-2]), float(k20_s.iloc[-1])
            if not any(np.isnan(v) for v in [k10_prev, k10_curr, k20_prev, k20_curr]):
                if k10_prev <= k20_prev and k10_curr > k20_curr:
                    signals.append("KAMA_BULL_CROSS")
                if k10_prev >= k20_prev and k10_curr < k20_curr:
                    signals.append("KAMA_BEAR_CROSS")

        if trend_score is not None:
            if trend_score >= 2:
                signals.append("STRONG_BULL")
            if trend_score <= -2:
                signals.append("STRONG_BEAR")

        # MACD crossover signals
        if len(macd_h) >= 2:
            mh_prev = float(macd_h.iloc[-2])
            mh_curr = float(macd_h.iloc[-1])
            if not (np.isnan(mh_prev) or np.isnan(mh_curr)):
                if mh_prev <= 0 and mh_curr > 0:
                    signals.append("MACD_BULL_CROSS")
                if mh_prev >= 0 and mh_curr < 0:
                    signals.append("MACD_BEAR_CROSS")

        if vol_ratio is not None and vol_ratio > 2:
            signals.append("HIGH_VOLUME")

        if bb_pct is not None:
            if bb_pct < 0.05:
                signals.append("BB_LOWER_BAND")
            if bb_pct > 0.95:
                signals.append("BB_UPPER_BAND")

        def _r(v, decimals=2):
            try:
                return round(float(v), decimals) if v is not None and not np.isnan(v) else None
            except Exception:
                return None

        return {
            "symbol":       sym,
            "price":        _r(price, 2),
            "week_ret":     _r(week_ret, 4),
            "rsi":          _r(rsi, 2),
            "trend_score":  trend_score,
            "kama10_dist":  _r(kama_vals[10], 2),
            "kama20_dist":  _r(kama_vals[20], 2),
            "kama50_dist":  _r(kama_vals[50], 2),
            "vol_ratio":    _r(vol_ratio, 2),
            "bb_pct":       _r(bb_pct, 4),
            "macd_hist":    _r(macd_hist_val, 6),
            "signals":      signals,
            "signal_count": len(signals),
        }
    except Exception:
        return None


def run_scanner(symbols: list = None, signal_filter: str = None) -> list:
    """
    Run _scan_one for all symbols in DB (or a provided list).
    Optionally filters by a specific signal name.
    Sorted by (signal_count desc, trend_score desc).
    """
    if symbols is None:
        symbols = [s["symbol"] for s in db.list_symbols()]

    results = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_scan_one, sym): sym for sym in symbols}
        for future in as_completed(futures):
            result = future.result()
            if result is not None:
                results.append(result)

    if signal_filter:
        results = [r for r in results if signal_filter in r["signals"]]

    results.sort(
        key=lambda r: (
            -(r.get("signal_count") or 0),
            -(r.get("trend_score") or 0),
        )
    )
    return results


# ── Multi-timeframe scanner (remote) ─────────────────────────────────────────

# ── monthly resampler ─────────────────────────────────────────────────

def _to_monthly(df: pd.DataFrame) -> pd.DataFrame:
    """Resample a daily DatetimeIndex DataFrame to month-end bars.
    Tries pandas 2.2+ 'ME' alias first, falls back to legacy 'M'.
    """
    if df is None or df.empty:
        return pd.DataFrame()
    agg = dict(open='first', high='max', low='min', close='last', volume='sum')
    for alias in ('ME', 'M'):
        try:
            return df.resample(alias).agg(**agg).dropna(subset=['close'])
        except Exception:
            continue
    return pd.DataFrame()


# ── public API ────────────────────────────────────────────────────────

def compute_scanner(symbols: list) -> list:
    """
    Compute D/W/M scanner metrics for every symbol in the list.
    Returns a JSON-serialisable list of row dicts.
    """
    # Build symbol metadata index (sector, group_tag, name) from DB in one pass
    sym_meta = {s['symbol']: s for s in db.list_symbols()}

    results = []
    for sym in symbols:
        try:
            d_df = db.get_ohlcv_df(sym, 'daily',  limit=600)
            w_df = db.get_ohlcv_df(sym, 'weekly', limit=200)
            meta = sym_meta.get(sym, {})

            if d_df.empty:
                results.append({
                    'symbol': sym, 'error': 'No data — fetch first',
                    'price': None, 'chg': None, 'ret_1m': None,
                    'sector': meta.get('sector') or '', 'group_tag': meta.get('group_tag') or '',
                    'd': None, 'w': None, 'm': None,
                })
                continue

            # Price / change computed before any further processing
            price  = _safe(d_df['close'].iloc[-1])
            prev   = _safe(d_df['close'].iloc[-2]) if len(d_df) > 1 else None
            chg    = round((price - prev) / prev * 100, 2) if price and prev else None
            # 1-month (21 trading days) return
            prev1m = _safe(d_df['close'].iloc[-22]) if len(d_df) >= 22 else None
            ret_1m = round((price - prev1m) / prev1m * 100, 2) if price and prev1m else None

            # Monthly resample — isolated so a failure doesn't kill price/D/W
            try:
                m_df = _to_monthly(d_df)
            except Exception:
                m_df = pd.DataFrame()

            # Each timeframe is isolated — one failure won't blank the others
            def _safe_tf(df, lb):
                try:
                    return _compute_tf(df, lb)
                except Exception:
                    return None

            results.append({
                'symbol':    sym,
                'name':      meta.get('name') or '',
                'sector':    meta.get('sector') or '',
                'group_tag': meta.get('group_tag') or '',
                'price':     price,
                'chg':       chg,
                'ret_1m':    ret_1m,
                'd':         _safe_tf(d_df, 252),
                'w':         _safe_tf(w_df,  52, (4, 13, 26)),
                'm':         _safe_tf(m_df,  36, (1,  3,  6)),
            })
        except Exception as e:
            results.append({
                'symbol': sym, 'error': str(e),
                'price': None, 'chg': None,
                'd': None, 'w': None, 'm': None,
            })

    return results


# ── Custom indicator builder ──────────────────────────────────────────────────

def compute_custom_indicator(symbols: list, indic: dict) -> list:
    """
    Compute a single user-defined indicator for every symbol.

    indic keys:
      type      — 'rsi' | 'roc' | 'sma' | 'ema' | 'atr_pct' | 'macd_hist' | 'bb_b' | 'vol_ratio' | 'cci'
      period    — primary period (int)
      period2   — secondary period for SMA cross / MACD slow (int, optional)
      timeframe — 'd' | 'w' | 'm'  (default 'd')

    Returns list of {symbol, value} dicts.
    """
    tf      = indic.get('timeframe', 'd')
    itype   = indic.get('type', 'rsi').lower()
    period  = int(indic.get('period', 14))
    period2 = int(indic.get('period2', 26)) if indic.get('period2') else None

    freq_map = {'d': 'daily', 'w': 'weekly', 'm': 'daily'}
    freq     = freq_map.get(tf, 'daily')
    limit    = {'d': 300, 'w': 150, 'm': 600}.get(tf, 300)

    results = []
    for sym in symbols:
        try:
            df = db.get_ohlcv_df(sym, freq, limit=limit)
            if tf == 'm':
                df = _to_monthly(df)
            if df is None or df.empty or len(df) < max(period + 5, 30):
                results.append({'symbol': sym, 'value': None})
                continue

            close  = df['close']
            high   = df['high']
            low    = df['low']
            volume = df['volume'] if 'volume' in df.columns else pd.Series(dtype=float)

            if itype == 'rsi':
                series = _rsi(close, period)
            elif itype == 'roc':
                series = close.pct_change(period) * 100
            elif itype == 'sma':
                series = close.rolling(period).mean()
                if period2:
                    s2 = close.rolling(period2).mean()
                    series = (close / s2.replace(0, np.nan) - 1.0) * 100
            elif itype == 'ema':
                series = close.ewm(span=period, adjust=False).mean()
                if period2:
                    s2 = close.ewm(span=period2, adjust=False).mean()
                    series = (close / s2.replace(0, np.nan) - 1.0) * 100
            elif itype == 'atr_pct':
                prev_c = close.shift(1)
                tr = pd.concat([
                    high - low,
                    (high - prev_c).abs(),
                    (low  - prev_c).abs(),
                ], axis=1).max(axis=1)
                atr = tr.ewm(alpha=1.0 / period, adjust=False).mean()
                series = atr / close.replace(0, np.nan) * 100
            elif itype == 'macd_hist':
                slow = period2 or period * 2
                ema_fast  = close.ewm(span=period, adjust=False).mean()
                ema_slow  = close.ewm(span=slow,   adjust=False).mean()
                macd_line = ema_fast - ema_slow
                series    = macd_line - macd_line.ewm(span=9, adjust=False).mean()
            elif itype == 'bb_b':
                mid  = close.rolling(period).mean()
                std  = close.rolling(period).std(ddof=0)
                series = (close - (mid - 2 * std)) / (4 * std.replace(0, np.nan)) * 100
            elif itype == 'vol_ratio':
                slow   = period2 or period * 4
                v_fast = volume.rolling(period).mean()
                v_slow = volume.rolling(slow).mean()
                series = v_fast / v_slow.replace(0, np.nan)
            elif itype == 'cci':
                hlc3 = (high + low + close) / 3.0
                sma  = hlc3.rolling(period).mean()
                mad  = hlc3.rolling(period).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
                series = (hlc3 - sma) / (0.015 * mad.replace(0, np.nan))
            else:
                results.append({'symbol': sym, 'value': None})
                continue

            val = _last(series)
            results.append({'symbol': sym, 'value': round(val, 4) if val is not None else None})
        except Exception:
            results.append({'symbol': sym, 'value': None})

    return results
