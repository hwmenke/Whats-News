"""
guru_scanner.py — Multi-strategy "guru" scan inspired by Qullamaggie, Minervini,
Stockbee, and William O'Neil.

Six strategies:
  qullamaggie  VCP breakout: Stage 2, tight base, near 20-bar pivot, ATR ext < 5×
  minervini    Trend Template: 6-condition MA stack checklist (full TTM)
  stockbee_4   4% Daily Mover: 1-day gain ≥ 4%, dollar volume ≥ $1M
  stockbee_20  20% Weekly Mover: 5-day move ≥ 20% (either direction)
  stockbee_9m  9-Million Dollar Mover: 20-day avg dollar vol > $9M, recent move ≥ 2%
  canslim      O'Neil L+S+M+N (technical proxy): Stage 2 leader near 52W high

All strategies cap results at ATR-extension-from-SMA50 < 5× (Jeff rule: never
initiate into an extended name).

Common row shape:
  symbol, sector, stage, stage_str, price, atr14, atr_pct, atr_ext,
  sma50, sma200, range_pos_52w, hi52, lo52, avg_dollar_vol, rr, + strategy extras
"""

import logging
import numpy as np
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

import database as db
import swing_core

logger = logging.getLogger(__name__)

_atr_fn = swing_core.atr
MAX_ATR_EXT = 5.0  # extension cap (Jeff: never enter > 5× ATR from SMA50)


# ── Stage classification ───────────────────────────────────────────────────────

def compute_stage(close: pd.Series, high: pd.Series, low: pd.Series
                  ) -> tuple[int | None, str | None]:
    """Weinstein stage (1–4) with sub-stage (A/B/C).

    Sub-stage key (within Stage 2):
      A = tight to SMA50 (<1.5 ATR) — fresh setup or base
      B = normal extension (1.5–3.5 ATR) — mid-trend
      C = late/extended (>3.5 ATR) — be cautious

    Returns (stage_int, sub_char) or (None, None) if insufficient data.
    """
    if len(close) < 210:
        return None, None

    sma50  = close.rolling(50,  min_periods=50).mean()
    sma200 = close.rolling(200, min_periods=200).mean()

    s50  = sma50.iloc[-1]
    s200 = sma200.iloc[-1]
    if pd.isna(s50) or pd.isna(s200):
        return None, None

    last = float(close.iloc[-1])
    s50  = float(s50)
    s200 = float(s200)

    # SMA200 direction: compare to 1 month ago (21 bars)
    idx_21 = -22 if len(sma200.dropna()) > 21 else None
    s200_prev = float(sma200.iloc[idx_21]) if idx_21 else s200
    s200_up   = s200 > s200_prev * 1.001

    atr14 = float(_atr_fn(high, low, close, 14).iloc[-1])
    ext   = (last - s50) / atr14 if atr14 > 0 else 0.0

    above_200 = last > s200
    s50_above = s50  > s200

    if above_200 and s50_above and s200_up:
        # Stage 2: proper uptrend
        sub = "A" if ext < 1.5 else "B" if ext < 3.5 else "C"
        return 2, sub

    if not above_200 and not s50_above and not s200_up:
        # Stage 4: clear downtrend
        depth = (s200 - last) / atr14 if atr14 > 0 else 0.0
        sub   = "A" if depth < 2 else "B" if depth < 5 else "C"
        return 4, sub

    if above_200 and s50_above and not s200_up:
        # Stage 3B: both MAs above 200 but 200 no longer rising — topping
        return 3, "B"

    if above_200 and not s50_above:
        # Stage 3A: SMA50 has crossed below SMA200 — late topping
        return 3, "A"

    # Stage 1: basing (below SMA200 or mixed)
    sub = "B" if (s50_above or last > s200 * 0.97) else "A"
    return 1, sub


# ── Shared row builder ─────────────────────────────────────────────────────────

def _base_row(sym: str, df: pd.DataFrame, info: dict | None = None) -> dict:
    """Common row fields shared by all strategies."""
    close  = df["close"]
    high   = df["high"]
    low    = df["low"]
    volume = df.get("volume", pd.Series(dtype=float))

    last  = float(close.iloc[-1])
    atr14 = float(_atr_fn(high, low, close, 14).iloc[-1])
    atr_pct = round(atr14 / last * 100, 2) if last > 0 else None

    # SMA50 / SMA200
    sma50_s  = close.rolling(50,  min_periods=50).mean()
    sma200_s = close.rolling(200, min_periods=200).mean()
    sma50    = float(sma50_s.iloc[-1])  if not pd.isna(sma50_s.iloc[-1])  else None
    sma200   = float(sma200_s.iloc[-1]) if not pd.isna(sma200_s.iloc[-1]) else None

    # ATR extension from SMA50
    atr_ext = round((last - sma50) / atr14, 2) if (sma50 and atr14 > 0) else None

    # 52-week range
    hi52 = float(high.tail(252).max()) if len(high) >= 100 else float(high.max())
    lo52 = float(low.tail(252).min())  if len(low)  >= 100 else float(low.min())
    rng  = hi52 - lo52
    rng_pos = round((last - lo52) / rng, 3) if rng > 0 else None

    # 20-day avg dollar volume (in millions)
    vol_arr = volume.values if len(volume) else np.zeros(len(close))
    close_arr = close.values
    dv_m = round(float(np.mean(close_arr[-20:] * vol_arr[-20:])) / 1e6, 2) if len(close) >= 5 else 0.0

    # Stage
    stage_int, stage_sub = compute_stage(close, high, low)
    stage_str = f"{stage_int}{stage_sub}" if stage_int else None

    # R:R — (distance to 52W high) / (1.5× ATR stop)
    upside   = hi52 - last
    stop_dist = 1.5 * atr14
    rr = round(upside / stop_dist, 2) if (stop_dist > 0 and upside > 0) else round(3.0, 2)

    return {
        "symbol":         sym,
        "sector":         (info.get("sector") or "") if info else "",
        "tier":           (info.get("watchlist_tier") or "") if info else "",
        "stage":          stage_int,
        "stage_str":      stage_str,
        "price":          round(last, 2),
        "atr14":          round(atr14, 4),
        "atr_pct":        atr_pct,
        "atr_ext":        atr_ext,
        "sma50":          round(sma50,  2) if sma50  else None,
        "sma200":         round(sma200, 2) if sma200 else None,
        "range_pos_52w":  rng_pos,
        "hi52":           round(hi52, 2),
        "lo52":           round(lo52, 2),
        "avg_dollar_vol": dv_m,
        "rr":             rr,
    }


# ── Minervini Trend Template ───────────────────────────────────────────────────

def _ttm_flags(df: pd.DataFrame) -> tuple[bool, dict]:
    """6-condition Minervini Trend Template. Returns (passes, flags)."""
    close = df["close"]
    if len(close) < 210:
        return False, {}

    last   = float(close.iloc[-1])
    sma50  = float(close.rolling(50).mean().iloc[-1])
    sma150 = float(close.rolling(150).mean().iloc[-1])
    sma200 = float(close.rolling(200).mean().iloc[-1])

    # SMA200 slope: compare to 1 month ago
    sma200_s  = close.rolling(200).mean()
    sma200_1m = float(sma200_s.iloc[-22]) if len(sma200_s.dropna()) > 21 else sma200

    # 52W high/low
    hi52 = float(df["high"].tail(252).max())
    lo52 = float(df["low"].tail(252).min())

    f = {
        "above_200":    last > sma200,
        "200_slope_up": sma200 > sma200_1m,
        "ma_stack":     sma50 > sma150 > sma200,
        "above_50":     last > sma50,
        "near_52hi":    last >= hi52 * 0.75,   # within 25% of 52W high
        "above_52lo":   last >= lo52 * 1.30,   # ≥30% above 52W low
    }
    return all(f.values()), f


def compute_minervini(symbols: list, rs_ranks: dict | None = None) -> list:
    """Minervini Trend Template — all 6 conditions must pass. RS ≥ 70 optional."""
    info_map = {r["symbol"]: r for r in db.list_symbols()}
    results  = []

    def _scan(sym):
        info = info_map.get(sym, {})
        try:
            df = db.get_ohlcv_df(sym, "daily", limit=265)
            if df.empty or len(df) < 210:
                return None
            ok, flags = _ttm_flags(df)
            if not ok:
                return None
            row = _base_row(sym, df, info)
            if row["atr_ext"] is not None and row["atr_ext"] > MAX_ATR_EXT:
                return None
            rs = (rs_ranks or {}).get(sym)
            if rs is not None and rs < 70:
                return None
            ttm_score = sum(1 for v in flags.values() if v)
            row.update({"ttm_flags": flags, "ttm_score": ttm_score, "rs_rank": rs})
            return row
        except Exception as e:
            logger.debug("minervini %s: %s", sym, e)
            return None

    with ThreadPoolExecutor(max_workers=4) as ex:
        for r in as_completed({ex.submit(_scan, s): s for s in symbols}):
            if r.result():
                results.append(r.result())

    results.sort(key=lambda r: (r.get("atr_ext") or 99, -(r.get("range_pos_52w") or 0)))
    return results


# ── Qullamaggie VCP Breakout ───────────────────────────────────────────────────

def compute_qullamaggie(symbols: list) -> list:
    """VCP breakout setup: Stage 2, volatility contraction, near pivot, ext < 5×."""
    info_map = {r["symbol"]: r for r in db.list_symbols()}
    results  = []

    def _scan(sym):
        info = info_map.get(sym, {})
        try:
            df = db.get_ohlcv_df(sym, "daily", limit=265)
            if df.empty or len(df) < 100:
                return None

            close = df["close"]
            high  = df["high"]
            row   = _base_row(sym, df, info)

            if row["stage"] != 2:
                return None
            if row["atr_ext"] is not None and row["atr_ext"] > MAX_ATR_EXT:
                return None
            if (row["range_pos_52w"] or 0) < 0.60:
                return None

            # Trigger = 20-bar high; proximity filter
            trigger   = float(high.tail(20).max())
            last      = row["price"]
            dist_pct  = round((trigger / last - 1) * 100, 2) if last > 0 else None
            if dist_pct is None or dist_pct > 10:
                return None

            # Volatility contraction (VCP)
            rng_bars = high - df["low"]
            recent   = float(rng_bars.tail(10).mean())
            prior    = float(rng_bars.iloc[-40:-10].mean()) if len(rng_bars) >= 40 else recent
            vcp_ratio = round(recent / prior, 2) if prior > 0 else 1.0

            # VCP score from swing_core
            try:
                sd = swing_core.swing_data_for(sym, df=df)
                vcp_score = round(sd.get("vcp_score") or 0, 2)
                rvol      = sd.get("rvol")
            except Exception:
                vcp_score, rvol = 0.0, None

            status = "AT" if dist_pct <= 1.5 else "NEAR" if dist_pct <= 5 else "WATCH"
            row.update({
                "trigger":          round(trigger, 2),
                "trigger_dist_pct": dist_pct,
                "trigger_status":   status,
                "vcp_ratio":        vcp_ratio,
                "vcp_score":        vcp_score,
                "rvol":             rvol,
            })
            return row
        except Exception as e:
            logger.debug("qullamaggie %s: %s", sym, e)
            return None

    with ThreadPoolExecutor(max_workers=4) as ex:
        for r in as_completed({ex.submit(_scan, s): s for s in symbols}):
            if r.result():
                results.append(r.result())

    _trank = {"AT": 0, "NEAR": 1, "WATCH": 2}
    results.sort(key=lambda r: (_trank.get(r.get("trigger_status"), 3), r.get("atr_ext") or 99))
    return results


# ── Stockbee 4% Daily Movers ──────────────────────────────────────────────────

def compute_stockbee_4pct(symbols: list) -> list:
    """4% Daily: 1-day gain ≥ 4%, avg dollar volume ≥ $1M, any stage."""
    info_map = {r["symbol"]: r for r in db.list_symbols()}
    results  = []

    def _scan(sym):
        info = info_map.get(sym, {})
        try:
            df = db.get_ohlcv_df(sym, "daily", limit=265)
            if df.empty or len(df) < 30:
                return None

            close = df["close"]
            vol   = df["volume"]

            ret_1d = float(close.iloc[-1] / close.iloc[-2] - 1) if len(close) >= 2 else 0
            if ret_1d < 0.04:
                return None

            row = _base_row(sym, df, info)
            if row["atr_ext"] is not None and row["atr_ext"] > MAX_ATR_EXT:
                return None
            if row["avg_dollar_vol"] < 1.0:
                return None

            vol_ma20 = float(vol.iloc[-51:-1].mean()) if len(vol) >= 51 else float(vol.mean())
            rvol     = round(float(vol.iloc[-1]) / vol_ma20, 2) if vol_ma20 > 0 else None

            row.update({"ret_1d": round(ret_1d * 100, 2), "rvol": rvol})
            return row
        except Exception as e:
            logger.debug("stockbee_4 %s: %s", sym, e)
            return None

    with ThreadPoolExecutor(max_workers=4) as ex:
        for r in as_completed({ex.submit(_scan, s): s for s in symbols}):
            if r.result():
                results.append(r.result())

    results.sort(key=lambda r: -(r.get("ret_1d") or 0))
    return results


# ── Stockbee 20% Weekly Movers ────────────────────────────────────────────────

def compute_stockbee_20pct(symbols: list) -> list:
    """20% Weekly: 5-day move ≥ 20% (either direction), dollar vol ≥ $1M."""
    info_map = {r["symbol"]: r for r in db.list_symbols()}
    results  = []

    def _scan(sym):
        info = info_map.get(sym, {})
        try:
            df = db.get_ohlcv_df(sym, "daily", limit=265)
            if df.empty or len(df) < 10:
                return None

            close  = df["close"]
            ret_5d = float(close.iloc[-1] / close.iloc[-6] - 1) if len(close) >= 6 else 0
            if abs(ret_5d) < 0.20:
                return None

            row = _base_row(sym, df, info)
            if row["atr_ext"] is not None and row["atr_ext"] > MAX_ATR_EXT:
                return None
            if row["avg_dollar_vol"] < 1.0:
                return None

            row.update({"ret_5d": round(ret_5d * 100, 2)})
            return row
        except Exception as e:
            logger.debug("stockbee_20 %s: %s", sym, e)
            return None

    with ThreadPoolExecutor(max_workers=4) as ex:
        for r in as_completed({ex.submit(_scan, s): s for s in symbols}):
            if r.result():
                results.append(r.result())

    results.sort(key=lambda r: -abs(r.get("ret_5d") or 0))
    return results


# ── Stockbee 9-Million Dollar Movers ─────────────────────────────────────────

def compute_stockbee_9mil(symbols: list) -> list:
    """9M Movers: 20-day avg dollar vol > $9M + recent day move ≥ 2%."""
    info_map = {r["symbol"]: r for r in db.list_symbols()}
    results  = []

    def _scan(sym):
        info = info_map.get(sym, {})
        try:
            df = db.get_ohlcv_df(sym, "daily", limit=265)
            if df.empty or len(df) < 30:
                return None

            close = df["close"]
            vol   = df["volume"]

            dv_m = float(np.mean(close.values[-20:] * vol.values[-20:])) / 1e6
            if dv_m < 9.0:
                return None

            ret_1d = float(close.iloc[-1] / close.iloc[-2] - 1) if len(close) >= 2 else 0
            if abs(ret_1d) < 0.02:
                return None

            row = _base_row(sym, df, info)
            if row["atr_ext"] is not None and row["atr_ext"] > MAX_ATR_EXT:
                return None

            vol_ma = float(vol.iloc[-51:-1].mean()) if len(vol) >= 51 else float(vol.mean())
            rvol   = round(float(vol.iloc[-1]) / vol_ma, 2) if vol_ma > 0 else None

            row.update({
                "ret_1d":         round(ret_1d * 100, 2),
                "rvol":           rvol,
                "avg_dollar_vol": round(dv_m, 2),
            })
            return row
        except Exception as e:
            logger.debug("stockbee_9m %s: %s", sym, e)
            return None

    with ThreadPoolExecutor(max_workers=4) as ex:
        for r in as_completed({ex.submit(_scan, s): s for s in symbols}):
            if r.result():
                results.append(r.result())

    results.sort(key=lambda r: -(r.get("avg_dollar_vol") or 0))
    return results


# ── O'Neil CANSLIM (technical proxy) ─────────────────────────────────────────

def compute_canslim(symbols: list) -> list:
    """O'Neil CANSLIM — L (leader RS ≥ 70), S (volume surge), M (Stage 2), N (near high)."""
    info_map = {r["symbol"]: r for r in db.list_symbols()}

    # Compute intra-watchlist 20-day RS ranks first (L criterion)
    ret20_map: dict = {}
    for sym in symbols:
        try:
            df = db.get_ohlcv_df(sym, "daily", limit=25)
            if not df.empty and len(df) >= 21:
                ret20_map[sym] = float(df["close"].iloc[-1] / df["close"].iloc[-21] - 1)
        except Exception:
            pass

    all_rets = sorted(ret20_map.values())
    n_rets   = len(all_rets)

    def _rs_pct(sym):
        r = ret20_map.get(sym)
        if r is None or n_rets == 0:
            return None
        return round(sum(1 for v in all_rets if v <= r) / n_rets * 100)

    results = []

    def _scan(sym):
        info   = info_map.get(sym, {})
        rs_pct = _rs_pct(sym)
        try:
            df = db.get_ohlcv_df(sym, "daily", limit=265)
            if df.empty or len(df) < 100:
                return None

            close = df["close"]
            high  = df["high"]
            vol   = df["volume"]

            row = _base_row(sym, df, info)

            # M: must be Stage 2
            if row["stage"] != 2:
                return None
            # ATR extension cap
            if row["atr_ext"] is not None and row["atr_ext"] > MAX_ATR_EXT:
                return None
            # L: leader (≥70th percentile 20d RS)
            if rs_pct is not None and rs_pct < 70:
                return None
            # N: near 52W high (≥70th percentile)
            if (row["range_pos_52w"] or 0) < 0.70:
                return None

            # S: supply/demand — relative volume
            vol_ma = float(vol.iloc[-51:-1].mean()) if len(vol) >= 51 else float(vol.mean())
            rvol   = round(float(vol.iloc[-1]) / vol_ma, 2) if vol_ma > 0 else None

            # N: pivot distance
            trigger   = float(high.tail(20).max())
            dist_pct  = round((trigger / row["price"] - 1) * 100, 2)

            row.update({
                "rs_rank":          rs_pct,
                "rvol":             rvol,
                "trigger":          round(trigger, 2),
                "trigger_dist_pct": dist_pct,
                "trigger_status":   "AT" if dist_pct <= 1.5 else "NEAR" if dist_pct <= 5 else "WATCH" if dist_pct <= 12 else "EARLY",
            })
            return row
        except Exception as e:
            logger.debug("canslim %s: %s", sym, e)
            return None

    with ThreadPoolExecutor(max_workers=4) as ex:
        for r in as_completed({ex.submit(_scan, s): s for s in symbols}):
            if r.result():
                results.append(r.result())

    results.sort(key=lambda r: (-(r.get("rs_rank") or 0), r.get("atr_ext") or 99))
    return results


# ── Stage distribution (for the board / dashboard) ────────────────────────────

def compute_stage_distribution(symbols: list) -> dict:
    """Stage breakdown across the entire symbol list. Returns counts per stage."""
    counts: dict[str, int] = {}
    total = 0

    for sym in symbols:
        try:
            df = db.get_ohlcv_df(sym, "daily", limit=265)
            if df.empty or len(df) < 60:
                continue
            s, sub = compute_stage(df["close"], df["high"], df["low"])
            if s:
                key = f"{s}{sub}"
                counts[key] = counts.get(key, 0) + 1
                total += 1
        except Exception:
            pass

    # Build stage-level totals and percentages
    stage_totals = {1: 0, 2: 0, 3: 0, 4: 0}
    for k, v in counts.items():
        try:
            s = int(k[0])
            stage_totals[s] = stage_totals.get(s, 0) + v
        except Exception:
            pass

    return {
        "counts":       counts,
        "stage_totals": stage_totals,
        "total":        total,
        "pct": {
            s: round(v / total * 100, 1) if total else 0
            for s, v in stage_totals.items()
        },
    }


# ── Public dispatcher ─────────────────────────────────────────────────────────

STRATEGIES: dict = {
    "qullamaggie": compute_qullamaggie,
    "minervini":   compute_minervini,
    "stockbee_4":  compute_stockbee_4pct,
    "stockbee_20": compute_stockbee_20pct,
    "stockbee_9m": compute_stockbee_9mil,
    "canslim":     compute_canslim,
}


def compute_guru_scan(strategy: str, symbols: list) -> list:
    fn = STRATEGIES.get(strategy)
    if fn is None:
        raise ValueError(f"Unknown strategy: {strategy!r}. Valid: {sorted(STRATEGIES)}")
    return fn(symbols)
