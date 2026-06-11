"""Market-wide analysis routes: relative strength, correlations, volume
profile, sector heatmap, signals, anomalies, spread, macro, RRG, breadth."""
import logging
from flask import Blueprint, jsonify, request

import database as db
import errors
import swing_core

logger = logging.getLogger(__name__)
market_bp = Blueprint("market", __name__)

_rsi       = swing_core.rsi
_macd_diff = swing_core.macd_diff
_bb_pband  = swing_core.bb_pband


@market_bp.route("/api/relative-strength/<string:symbol>", methods=["GET"])
def get_relative_strength(symbol):
    """
    Returns the symbol's close divided by a benchmark close, both normalised
    to 1.0 at the start of the window.  Query params:
      bench : benchmark symbol (default SPY)
      freq  : daily | weekly (default daily)
      limit : number of bars (default 252)
    """
    bench = request.args.get("bench", "SPY").strip().upper()
    freq  = request.args.get("freq", "daily")
    try:
        limit = int(request.args.get("limit", 252))
        if limit < 2:
            raise ValueError
    except (TypeError, ValueError):
        raise errors.validation("limit must be an integer >= 2")
    if freq not in ("daily", "weekly"):
        raise errors.validation("freq must be 'daily' or 'weekly'")

    sym_df   = db.get_ohlcv_df(symbol.upper(), freq, limit=limit)
    bench_df = db.get_ohlcv_df(bench, freq, limit=limit)

    if sym_df.empty:
        raise errors.no_data(symbol.upper())
    if bench_df.empty:
        raise errors.no_data(bench)

    # Align on common dates
    common = sym_df.index.intersection(bench_df.index)
    if len(common) < 2:
        raise errors.ApiError("NO_DATA",
                              "Not enough overlapping dates between symbol and benchmark",
                              http=404)

    sym_close   = sym_df.loc[common, "close"]
    bench_close = bench_df.loc[common, "close"]

    # Normalise both to 1.0 at the first common date
    sym_norm   = sym_close   / sym_close.iloc[0]
    bench_norm = bench_close / bench_close.iloc[0]
    rs         = sym_norm / bench_norm

    from shared_indicators import _safe
    result = [
        {"date": d.strftime("%Y-%m-%d"), "rs": _safe(round(float(v), 6)),
         "sym": _safe(round(float(s), 6)), "bench": _safe(round(float(b), 6))}
        for d, v, s, b in zip(common, rs.values, sym_norm.values, bench_norm.values)
    ]
    return jsonify({"symbol": symbol.upper(), "bench": bench, "series": result})


@market_bp.route("/api/correlations", methods=["GET"])
def get_correlations():
    """
    Pairwise Pearson correlation of daily returns across all watchlist symbols.
    Query params:
      freq  : daily | weekly (default daily)
      limit : bars to use   (default 252)
    """
    freq = request.args.get("freq", "daily")
    try:
        limit = int(request.args.get("limit", 252))
        if limit < 5:
            raise ValueError
    except (TypeError, ValueError):
        raise errors.validation("limit must be an integer >= 5")
    if freq not in ("daily", "weekly"):
        raise errors.validation("freq must be 'daily' or 'weekly'")

    symbols = [s["symbol"] for s in db.list_symbols()]
    if len(symbols) < 2:
        raise errors.validation("Need at least 2 symbols in the watchlist")

    import numpy as np

    frames = {}
    for sym in symbols:
        df = db.get_ohlcv_df(sym, freq, limit=limit)
        if not df.empty and len(df) >= 5:
            frames[sym] = df["close"].pct_change().dropna()

    if len(frames) < 2:
        raise errors.ApiError("NO_DATA", "Not enough symbols with data", http=400)

    import pandas as pd
    prices = pd.DataFrame(frames)
    corr   = prices.corr(method="pearson")

    syms = list(corr.columns)
    matrix = []
    for s1 in syms:
        row = []
        for s2 in syms:
            v = corr.loc[s1, s2]
            row.append(None if (v is None or (isinstance(v, float) and np.isnan(v)))
                       else round(float(v), 4))
        matrix.append(row)

    return jsonify({"symbols": syms, "matrix": matrix})


@market_bp.route("/api/volume-profile/<string:symbol>", methods=["GET"])
def get_volume_profile(symbol):
    """
    Returns a price histogram weighted by volume.
    Query params:
      freq  : daily | weekly (default daily)
      limit : bars to use   (default 252)
      bins  : number of price buckets (default 40)
    """
    freq = request.args.get("freq", "daily")
    try:
        limit = int(request.args.get("limit", 252))
        bins  = int(request.args.get("bins",  40))
        if limit < 5 or bins < 2:
            raise ValueError
    except (TypeError, ValueError):
        raise errors.validation("limit (>=5) and bins (>=2) must be positive integers")
    if freq not in ("daily", "weekly"):
        raise errors.validation("freq must be 'daily' or 'weekly'")

    df = db.get_ohlcv_df(symbol.upper(), freq, limit=limit)
    if df.empty:
        raise errors.no_data(symbol.upper())

    import numpy as np
    prices = ((df["high"] + df["low"]) / 2).values
    vols   = df["volume"].values
    lo, hi = prices.min(), prices.max()
    if lo >= hi:
        raise errors.validation("Insufficient price range")

    edges   = np.linspace(lo, hi, bins + 1)
    buckets = []
    for i in range(bins):
        mask   = (prices >= edges[i]) & (prices < edges[i + 1])
        vol_sum = float(vols[mask].sum())
        buckets.append({
            "price_low":  round(float(edges[i]),     4),
            "price_high": round(float(edges[i + 1]), 4),
            "price_mid":  round(float((edges[i] + edges[i + 1]) / 2), 4),
            "volume":     vol_sum,
        })

    total = sum(b["volume"] for b in buckets) or 1
    for b in buckets:
        b["volume_pct"] = round(b["volume"] / total * 100, 2)

    return jsonify({"symbol": symbol.upper(), "buckets": buckets,
                    "price_range": {"low": round(float(lo), 4),
                                    "high": round(float(hi), 4)}})


@market_bp.route("/api/sector-heatmap", methods=["GET"])
def sector_heatmap():
    import datetime
    import numpy as np
    symbols = db.list_symbols()
    if not symbols:
        return jsonify([])

    ytd_start = datetime.date.today().replace(month=1, day=1).isoformat()

    sectors: dict[str, list] = {}
    for sym in symbols:
        sector = (sym.get("sector") or "Unknown").strip() or "Unknown"
        sectors.setdefault(sector, []).append(sym["symbol"])

    result = []
    for sector, syms in sorted(sectors.items()):
        rows = []
        for s in syms:
            df = db.get_ohlcv_df(s, "daily", limit=260)
            if df.empty or len(df) < 2:
                continue
            close = df["close"]

            def _ret(n):
                return float(close.iloc[-1] / close.iloc[-n] - 1) if len(close) >= n else None

            ytd_df  = df[df.index.astype(str) >= ytd_start]
            ret_ytd = float(close.iloc[-1] / ytd_df["close"].iloc[0] - 1) if len(ytd_df) > 0 else None

            rows.append({
                "symbol": s,
                "close":  round(float(close.iloc[-1]), 2),
                "ret_1d":  round(_ret(2), 4)   if _ret(2)   is not None else None,
                "ret_5d":  round(_ret(6), 4)   if _ret(6)   is not None else None,
                "ret_20d": round(_ret(21), 4)  if _ret(21)  is not None else None,
                "ret_ytd": round(ret_ytd, 4)   if ret_ytd   is not None else None,
            })

        if rows:
            # Sector-level averages
            def _avg(key):
                vals = [r[key] for r in rows if r[key] is not None]
                return round(float(np.mean(vals)), 4) if vals else None

            result.append({
                "sector":   sector,
                "count":    len(rows),
                "avg_1d":   _avg("ret_1d"),
                "avg_5d":   _avg("ret_5d"),
                "avg_20d":  _avg("ret_20d"),
                "avg_ytd":  _avg("ret_ytd"),
                "symbols":  rows,
            })

    return jsonify(result)


@market_bp.route("/api/signals", methods=["GET"])
def get_signals():
    symbols = db.list_symbols()
    if not symbols:
        return jsonify([])

    results = []
    for sym_row in symbols:
        sym = sym_row["symbol"]
        try:
            df = db.get_ohlcv_df(sym, "daily", limit=100)
            if df.empty or len(df) < 30:
                continue
            close = df["close"]
            rsi14   = _rsi(close, 14).iloc[-1]
            macd    = _macd_diff(close).iloc[-1]
            bb_pct  = _bb_pband(close).iloc[-1]
            vol     = df["volume"]
            vol_ma  = vol.rolling(20).mean().iloc[-1]
            vol_z   = (vol.iloc[-1] - vol_ma) / (vol.std() + 1e-9)

            signals = []
            if rsi14 < 30:   signals.append({"type": "rsi_os", "label": "RSI Oversold",  "bull": True})
            if rsi14 > 70:   signals.append({"type": "rsi_ob", "label": "RSI Overbought","bull": False})
            if macd > 0:     signals.append({"type": "macd_bull", "label": "MACD Bull",  "bull": True})
            if macd < 0:     signals.append({"type": "macd_bear", "label": "MACD Bear",  "bull": False})
            if bb_pct < 0.1: signals.append({"type": "bb_squeeze_low", "label": "BB Lower",  "bull": True})
            if bb_pct > 0.9: signals.append({"type": "bb_squeeze_hi",  "label": "BB Upper",  "bull": False})
            if vol_z > 2.5:  signals.append({"type": "vol_spike",  "label": "Vol Spike",  "bull": None})

            score = sum(1 if s["bull"] else -1 if s["bull"] is False else 0 for s in signals)
            results.append({
                "symbol":  sym,
                "name":    sym_row.get("name", ""),
                "close":   round(float(close.iloc[-1]), 2),
                "rsi14":   round(float(rsi14), 1),
                "macd":    round(float(macd), 4),
                "bb_pct":  round(float(bb_pct), 3),
                "vol_z":   round(float(vol_z), 2),
                "signals": signals,
                "score":   score,
            })
        except Exception as exc:
            logger.debug("Signals skipped %s: %s", sym, exc)

    results.sort(key=lambda r: -abs(r["score"]))
    return jsonify(results)


@market_bp.route("/api/anomalies", methods=["GET"])
def get_anomalies():
    symbols  = db.list_symbols()
    anomalies = []

    for sym_row in symbols:
        sym = sym_row["symbol"]
        df  = db.get_ohlcv_df(sym, "daily", limit=60)
        if df.empty or len(df) < 21:
            continue

        flags = []
        close  = df["close"]
        volume = df["volume"]

        # Volume spike: today vs 20-day avg
        vol_avg = volume.iloc[:-1].tail(20).mean()
        vol_std = volume.iloc[:-1].tail(20).std()
        if vol_std > 0:
            vol_z = (volume.iloc[-1] - vol_avg) / vol_std
            if abs(vol_z) > 2.5:
                flags.append({"type": "vol_spike", "label": f"Vol spike ({vol_z:+.1f}σ)", "z": round(float(vol_z), 2)})

        # Price gap: open vs prev close
        if "open" in df.columns and len(df) >= 2:
            prev_close = close.iloc[-2]
            gap_pct = (df["open"].iloc[-1] - prev_close) / prev_close if prev_close != 0 else 0.0
            if abs(gap_pct) > 0.02:
                flags.append({"type": "price_gap", "label": f"Gap {gap_pct*100:+.1f}%", "z": round(float(gap_pct), 4)})

        # Volatility spike: today range vs avg
        df["range"] = (df["high"] - df["low"]) / close
        rng_today = df["range"].iloc[-1]
        rng_avg   = df["range"].iloc[-21:-1].mean()
        rng_std   = df["range"].iloc[-21:-1].std()
        if rng_std > 0 and rng_today > rng_avg + 2.5 * rng_std:
            flags.append({"type": "vol_range", "label": "High-range candle", "z": round(float((rng_today - rng_avg) / rng_std), 2)})

        # 52-week high/low touch
        high52 = close.tail(252).max()
        low52  = close.tail(252).min()
        if abs(close.iloc[-1] - high52) / high52 < 0.005:
            flags.append({"type": "high52", "label": "52w High", "z": 0})
        elif abs(close.iloc[-1] - low52) / low52 < 0.005:
            flags.append({"type": "low52",  "label": "52w Low",  "z": 0})

        if flags:
            anomalies.append({
                "symbol": sym,
                "name":   sym_row.get("name", ""),
                "close":  round(float(close.iloc[-1]), 2),
                "flags":  flags,
            })

    return jsonify(anomalies)


@market_bp.route("/api/spread", methods=["GET"])
def get_spread():
    import numpy as np

    sym1 = request.args.get("sym1", "").strip().upper()
    sym2 = request.args.get("sym2", "").strip().upper()
    freq = request.args.get("freq", "daily")
    try:
        limit  = int(request.args.get("limit",  252))
        window = int(request.args.get("window",  20))
    except (TypeError, ValueError):
        raise errors.validation("limit and window must be integers")

    if not sym1 or not sym2:
        raise errors.validation("sym1 and sym2 are required")
    if sym1 == sym2:
        raise errors.validation("sym1 and sym2 must be different")
    if freq not in ("daily", "weekly"):
        raise errors.validation("freq must be daily or weekly")

    df1 = db.get_ohlcv_df(sym1, freq, limit=limit)
    df2 = db.get_ohlcv_df(sym2, freq, limit=limit)

    if df1.empty:
        raise errors.no_data(sym1)
    if df2.empty:
        raise errors.no_data(sym2)

    common = df1.index.intersection(df2.index)
    if len(common) < window + 5:
        raise errors.ApiError("NO_DATA", "Not enough overlapping data", http=404)

    c1    = df1.loc[common, "close"]
    c2    = df2.loc[common, "close"]
    ratio = c1 / c2

    rm    = ratio.rolling(window).mean()
    rs    = ratio.rolling(window).std().replace(0, float("nan"))
    zs    = (ratio - rm) / rs

    result = [
        {"date":   d.strftime("%Y-%m-%d"),
         "ratio":  round(float(r), 6) if np.isfinite(r) else None,
         "zscore": round(float(z), 4) if np.isfinite(z) else None}
        for d, r, z in zip(common, ratio.values, zs.values)
    ]

    last_z = float(zs.dropna().iloc[-1]) if len(zs.dropna()) else None
    signal = None
    if last_z is not None:
        if last_z > 2:    signal = "mean_revert_short"
        elif last_z < -2: signal = "mean_revert_long"
        else:             signal = "neutral"

    return jsonify({
        "sym1": sym1, "sym2": sym2, "window": window,
        "last_zscore": round(last_z, 4) if last_z and np.isfinite(last_z) else None,
        "signal":  signal,
        "series":  result,
    })


@market_bp.route("/api/macro", methods=["GET"])
def get_macro():
    import numpy as np
    import pandas as pd

    freq  = request.args.get("freq", "daily")
    try:
        limit = int(request.args.get("limit", 252))
    except (TypeError, ValueError):
        limit = 252

    macro_map = {"VIX": "^VIX", "DXY": "DX-Y.NYB", "US10Y": "^TNX", "OIL": "CL=F"}
    result = {}

    for label, sym in macro_map.items():
        df = db.get_ohlcv_df(sym, freq, limit=limit)
        if df.empty:
            try:
                import yfinance as yf
                hist = yf.Ticker(sym).history(period="2y",
                                              interval="1d" if freq == "daily" else "1wk")
                if hist.empty:
                    continue
                hist.index = pd.to_datetime(hist.index).tz_localize(None)
                hist.columns = [c.lower() for c in hist.columns]
                df = hist[["open", "high", "low", "close", "volume"]]
                try:
                    db.upsert_ohlcv(sym, freq, df)
                except Exception:
                    pass
            except Exception as exc:
                logger.debug("Macro fetch failed for %s: %s", sym, exc)
                continue
        if df.empty:
            continue
        close = df["close"].tail(limit)
        result[label] = [
            {"date": d.strftime("%Y-%m-%d"), "value": round(float(v), 4)}
            for d, v in zip(close.index, close.values)
            if np.isfinite(v)
        ]

    return jsonify(result)


@market_bp.route("/api/rrg", methods=["GET"])
def get_rrg():
    import numpy as np

    benchmark = request.args.get("benchmark", "SPY").upper()
    period    = max(2, min(int(request.args.get("period", 10)), 52))
    trail_n   = max(2, min(int(request.args.get("trail", 5)), 12))

    bdf = db.get_ohlcv_df(benchmark, "weekly", limit=120)
    if bdf.empty:
        raise errors.no_data(benchmark)

    symbols = [s["symbol"] for s in db.list_symbols() if s["symbol"] != benchmark]
    if not symbols:
        return jsonify({"benchmark": benchmark, "symbols": []})

    def _quadrant(rs_r, rs_m):
        if rs_r >= 100 and rs_m >= 100: return "leading"
        if rs_r >= 100 and rs_m <  100: return "weakening"
        if rs_r <  100 and rs_m <  100: return "lagging"
        return "improving"

    results = []
    for sym in symbols:
        try:
            df = db.get_ohlcv_df(sym, "weekly", limit=120)
            if df.empty:
                continue
            common = df.index.intersection(bdf.index)
            if len(common) < period + 10:
                continue

            sc = df.loc[common, "close"]
            bc = bdf.loc[common, "close"]

            # JdK RS-Ratio: relative strength smoothed and normalised to 100
            rs_raw    = sc / bc.replace(0, float("nan"))
            rs_ema    = rs_raw.ewm(span=period, adjust=False).mean()
            rs_roll   = rs_ema.rolling(min(52, len(rs_ema))).mean().replace(0, float("nan"))
            rs_ratio  = (rs_ema / rs_roll * 100).fillna(100)

            # JdK RS-Momentum: rate of change of RS-Ratio
            rs_mom    = rs_ratio.pct_change(period) * 100 + 100

            # Build trail (last trail_n non-NaN points)
            valid = [(r, m) for r, m in zip(rs_ratio.values, rs_mom.values)
                     if np.isfinite(r) and np.isfinite(m)]
            trail = [{"rs_ratio": round(r, 3), "rs_mom": round(m, 3)}
                     for r, m in valid[-trail_n:]]
            if not trail:
                continue

            last = trail[-1]
            results.append({
                "symbol":   sym,
                "rs_ratio": last["rs_ratio"],
                "rs_mom":   last["rs_mom"],
                "trail":    trail,
                "quadrant": _quadrant(last["rs_ratio"], last["rs_mom"]),
            })
        except Exception:
            continue

    return jsonify({"benchmark": benchmark, "symbols": results})


def _breadth_snapshot() -> dict:
    """Watchlist breadth core (no external network calls)."""
    symbols = db.list_symbols()
    if not symbols:
        raise errors.ApiError("NO_DATA", "No symbols in watchlist", http=404)

    above_20 = above_50 = above_200 = advances = declines = new_highs = new_lows = total = 0

    for row in symbols:
        sym = row["symbol"]
        try:
            df = db.get_ohlcv_df(sym, freq="daily", limit=260)
            if df.empty or len(df) < 20:
                continue
            close      = df["close"]
            last       = float(close.iloc[-1])
            prev       = float(close.iloc[-2]) if len(close) >= 2 else last
            total     += 1
            if last > float(close.tail(21).mean()):  above_20  += 1
            if last > float(close.tail(51).mean()):  above_50  += 1
            if len(close) >= 200 and last > float(close.tail(201).mean()): above_200 += 1
            if last >= prev: advances += 1
            else:            declines += 1
            high_52w = float(df["high"].tail(252).max())
            low_52w  = float(df["low"].tail(252).min())
            if high_52w > 0 and abs(last - high_52w) / high_52w < 0.01: new_highs += 1
            if low_52w  > 0 and abs(last - low_52w)  / low_52w  < 0.01: new_lows  += 1
        except Exception:
            pass

    pct = lambda n: round(n / total * 100, 1) if total else 0
    return {
        "total":          total,
        "pct_above_20ma": pct(above_20),
        "pct_above_50ma": pct(above_50),
        "pct_above_200ma":pct(above_200),
        "advances":       advances,
        "declines":       declines,
        "ad_ratio":       round(advances / declines, 2) if declines else advances,
        "new_highs":      new_highs,
        "new_lows":       new_lows,
    }


@market_bp.route("/api/breadth", methods=["GET"])
def get_market_breadth():
    snap = _breadth_snapshot()

    # Equal-weight vs cap-weight divergence:
    #   RSP/SPY  — equal- vs cap-weight S&P 500
    #   QQQE/QQQ — equal- vs cap-weight Nasdaq-100
    def _ew_ratio(ew_sym, cw_sym, closes):
        ew = closes[ew_sym].dropna()
        cw = closes[cw_sym].dropna()
        if len(ew) < 22 or len(cw) < 22:
            return None
        ratio_now  = float(ew.iloc[-1])  / float(cw.iloc[-1])
        ratio_prev = float(ew.iloc[-22]) / float(cw.iloc[-22])
        chg = round((ratio_now / ratio_prev - 1) * 100, 2)
        return {
            "ratio":   round(ratio_now, 4),
            "chg_20d": chg,
            "signal":  "broadening" if chg > 0.5 else "narrowing" if chg < -0.5 else "neutral",
        }

    ew_cw = qqqe_qqq = None
    try:
        import yfinance as yf
        raw = yf.download(["SPY", "RSP", "QQQ", "QQQE"], period="2mo",
                          auto_adjust=True, progress=False)["Close"]
        ew_cw    = _ew_ratio("RSP",  "SPY", raw)
        qqqe_qqq = _ew_ratio("QQQE", "QQQ", raw)
    except Exception:
        pass

    return jsonify({**snap, "ew_cw": ew_cw, "qqqe_qqq": qqqe_qqq})


# ── Risk Pedal ────────────────────────────────────────────────────────────────

def _compute_risk_pedal() -> dict:
    """Translate regime + breadth + index extension into green/yellow/red."""
    reasons = []

    regime_state = ""
    try:
        import market_regime as mr
        res = mr.compute_market_regime("SPY")
        if "error" not in res:
            regime_state = (res.get("current") or {}).get("state", "")
    except Exception:
        pass

    try:
        snap = _breadth_snapshot()
    except errors.ApiError:
        snap = {}
    pct20 = snap.get("pct_above_20ma")

    spy_ext = None
    spy_up_streak = None
    try:
        sd = swing_core.swing_data_for("SPY")
        spy_ext = sd.get("atr_mult_50ma")
    except Exception:
        pass
    try:
        spy_df = db.get_ohlcv_df("SPY", "daily", limit=15)
        if not spy_df.empty and len(spy_df) >= 2:
            closes = spy_df["close"].values
            streak = 0
            for i in range(len(closes) - 1, 0, -1):
                if closes[i] > closes[i - 1]:
                    streak += 1
                else:
                    break
            spy_up_streak = streak
    except Exception:
        pass

    if not regime_state and pct20 is None:
        return {
            "pedal": "yellow", "regime_state": "", "breadth_pct20": None,
            "breadth_pct50": None, "new_highs": None, "new_lows": None,
            "spy_ext": spy_ext,
            "reasons": ["Insufficient data — fetch SPY and watchlist OHLCV first"],
        }

    pedal = "green"
    if regime_state in ("BEAR", "CRASH"):
        pedal = "red"
        reasons.append(f"Regime is {regime_state}")
    elif pct20 is not None and pct20 < 30:
        pedal = "red"
        reasons.append(f"Only {pct20}% of watchlist above 20-MA")

    if pedal != "red":
        if regime_state == "CHOP":
            pedal = "yellow"
            reasons.append("Regime is CHOP")
        if pct20 is not None and pct20 < 50:
            pedal = "yellow"
            reasons.append(f"{pct20}% of watchlist above 20-MA (weak breadth)")
        if spy_ext is not None and spy_ext > 4:
            pedal = "yellow"
            reasons.append(f"SPY extended {spy_ext:.1f}× ATR from 50-MA")
        if spy_up_streak is not None and spy_up_streak >= 5:
            pedal = "yellow"
            reasons.append(f"SPY up {spy_up_streak} days in a row — late to the move, be cautious")

    if pedal == "green":
        reasons.append("Regime and breadth supportive — take A setups at normal risk")
    elif pedal == "yellow":
        reasons.append("Reduce size, fewer new names, prefer existing winners")
    else:
        reasons.append("Minimal new risk — raise cash, manage existing positions")

    return {
        "pedal":         pedal,
        "regime_state":  regime_state,
        "breadth_pct20": pct20,
        "breadth_pct50": snap.get("pct_above_50ma"),
        "new_highs":     snap.get("new_highs"),
        "new_lows":      snap.get("new_lows"),
        "spy_ext":       spy_ext,
        "spy_up_streak": spy_up_streak,
        "reasons":       reasons,
    }


@market_bp.route("/api/risk-pedal", methods=["GET"])
def get_risk_pedal():
    return jsonify(_compute_risk_pedal())


# ── Market Diary ──────────────────────────────────────────────────────────────

@market_bp.route("/api/diary", methods=["GET"])
def list_diary_route():
    try:
        limit = int(request.args.get("limit", 60))
        if limit < 1:
            raise ValueError
    except (TypeError, ValueError):
        raise errors.validation("limit must be a positive integer")
    return jsonify(db.list_diary(limit=limit))


@market_bp.route("/api/diary", methods=["POST"])
def save_diary_route():
    """Save today's (or the given date's) diary entry.  Context fields
    (regime, pedal, breadth) are snapshotted server-side unless provided."""
    from datetime import date as _date
    body = request.get_json(silent=True) or {}
    day  = (body.get("date") or _date.today().isoformat())[:10]

    ctx = {}
    if not body.get("regime_state") or body.get("risk_pedal") is None:
        try:
            ctx = _compute_risk_pedal()
        except Exception:
            ctx = {}

    db.upsert_diary_entry(
        date=day,
        regime_state=body.get("regime_state")  or ctx.get("regime_state", ""),
        risk_pedal=body.get("risk_pedal")      or ctx.get("pedal", ""),
        breadth_pct20=body.get("breadth_pct20", ctx.get("breadth_pct20")),
        breadth_pct50=body.get("breadth_pct50", ctx.get("breadth_pct50")),
        new_highs=body.get("new_highs", ctx.get("new_highs")),
        new_lows=body.get("new_lows",  ctx.get("new_lows")),
        notes=body.get("notes", ""),
    )
    return jsonify({"date": day, "message": "Diary saved"}), 201


@market_bp.route("/api/diary/<string:date>", methods=["DELETE"])
def delete_diary_route(date):
    db.delete_diary_entry(date[:10])
    return jsonify({"message": "deleted"})
