"""features_api.py - Flask Blueprint with additional analytics/journal/portfolio routes."""
import json
import logging
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from flask import Blueprint, jsonify, request

import database as db
import news as news_mod
import newsletter_engine

logger = logging.getLogger(__name__)
features_bp = Blueprint("features", __name__)


# --- helpers ---
def _err(message, status=400):
    return jsonify({"error": message}), status


# indicator helpers (replace the `ta` library)
def _rsi(close, window=14):
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/window, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/window, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def _macd_diff(close, fast=12, slow=26, signal=9):
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    return macd - macd.ewm(span=signal, adjust=False).mean()


def _bb_pband(close, window=20, ndev=2.0):
    ma = close.rolling(window).mean()
    sd = close.rolling(window).std()
    upper = ma + ndev * sd
    lower = ma - ndev * sd
    return (close - lower) / (upper - lower).replace(0, np.nan)


def _atr(high, low, close, window=14):
    pc = close.shift(1)
    tr = pd.concat([high - low, (high - pc).abs(), (low - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/window, adjust=False).mean()


def _kama(close: pd.Series, period: int = 10, fast: int = 2, slow: int = 30) -> pd.Series:
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


# --- routes ---

# -- Symbols --------------------------------------------------------------------

@features_bp.route("/api/symbols/<string:symbol>/group", methods=["PUT"])
def set_symbol_group(symbol):
    data      = request.get_json(silent=True) or {}
    group_tag = data.get("group_tag", "").strip()
    db.set_symbol_group(symbol.upper(), group_tag)
    return jsonify({"message": "ok"})


# -- Quick stats (lightweight watchlist badges) ---------------------------------

@features_bp.route("/api/symbols/quick-stats", methods=["GET"])
def quick_stats():
    """
    Return per-symbol stats for watchlist badges + sort/filter.
    DB-only — no network calls. Runs on every page load.
    Fields: price, chg (1D%), ret_5d (1W%), ret_1m, rsi14, vol_ratio, above_sma20
    """
    import numpy as np
    from shared_indicators import _rsi

    symbols = [s["symbol"] for s in db.list_symbols()]
    results = []
    for sym in symbols:
        try:
            df = db.get_ohlcv_df(sym, "daily", limit=60)
            if df.empty or len(df) < 2:
                results.append({"symbol": sym})
                continue
            close  = df["close"]
            volume = df["volume"] if "volume" in df.columns else None
            price  = float(close.iloc[-1])
            prev   = float(close.iloc[-2])
            chg    = round((price - prev) / prev * 100, 2) if prev else None

            ret_5d = None
            if len(close) >= 6:
                p5 = float(close.iloc[-6])
                ret_5d = round((price - p5) / p5 * 100, 2) if p5 else None

            ret_1m = None
            if len(close) >= 22:
                p1m = float(close.iloc[-22])
                ret_1m = round((price - p1m) / p1m * 100, 2) if p1m else None

            rsi14 = None
            if len(close) >= 15:
                r = _rsi(close, 14)
                v = r.iloc[-1]
                if not np.isnan(v):
                    rsi14 = round(float(v), 1)

            vol_ratio = None
            above_sma20 = None
            if volume is not None and len(volume) >= 20:
                avg20 = float(volume.iloc[-20:].mean())
                if avg20 > 0:
                    vol_ratio = round(float(volume.iloc[-1]) / avg20, 2)
            if len(close) >= 20:
                sma20 = float(close.iloc[-20:].mean())
                above_sma20 = price > sma20

            results.append({
                "symbol":      sym,
                "price":       round(price, 2),
                "chg":         chg,
                "ret_5d":      ret_5d,
                "ret_1m":      ret_1m,
                "rsi14":       rsi14,
                "vol_ratio":   vol_ratio,
                "above_sma20": above_sma20,
            })
        except Exception:
            results.append({"symbol": sym})
    return jsonify(results)


# -- Notes ---------------------------------------------------------------------

@features_bp.route("/api/symbols/<string:symbol>/notes", methods=["PUT"])
def set_notes(symbol):
    body  = request.get_json(silent=True) or {}
    notes = body.get("notes", "")
    db.set_symbol_notes(symbol.upper(), notes)
    return jsonify({"message": "ok"})


# -- Fundamentals ---------------------------------------------------------------

@features_bp.route("/api/fundamentals/<string:symbol>", methods=["GET"])
def get_fundamentals(symbol):
    row = db.get_fundamentals(symbol.upper())
    if row is None:
        return _err("No fundamental data. Fetch the symbol first.", 404)
    return jsonify(row)


# -- Alerts --------------------------------------------------------------------

@features_bp.route("/api/alerts", methods=["GET"])
def list_alerts():
    symbol = request.args.get("symbol")
    return jsonify(db.list_alerts(symbol.upper() if symbol else None))


@features_bp.route("/api/alerts", methods=["POST"])
def create_alert():
    body = request.get_json(silent=True) or {}
    symbol    = body.get("symbol", "").strip().upper()
    field     = body.get("field", "").strip()
    condition = body.get("condition", "").strip()
    threshold = body.get("threshold")

    if not symbol:
        return _err("symbol is required")
    if field not in ("price", "rsi_14", "kama10_pct", "kama20_pct", "kama50_pct"):
        return _err("field must be one of: price, rsi_14, kama10_pct, kama20_pct, kama50_pct")
    if condition not in ("above", "below"):
        return _err("condition must be 'above' or 'below'")
    try:
        threshold = float(threshold)
    except (TypeError, ValueError):
        return _err("threshold must be a number")

    alert_id = db.add_alert(symbol, field, condition, threshold)
    return jsonify({"id": alert_id, "message": "Alert created"}), 201


@features_bp.route("/api/alerts/<int:alert_id>", methods=["DELETE"])
def delete_alert(alert_id):
    db.delete_alert(alert_id)
    return jsonify({"message": "deleted"})


@features_bp.route("/api/alerts/<int:alert_id>/reset", methods=["POST"])
def reset_alert(alert_id):
    db.reset_alert(alert_id)
    return jsonify({"message": "reset"})


# -- Relative Strength ---------------------------------------------------------

@features_bp.route("/api/relative-strength/<string:symbol>", methods=["GET"])
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
        return _err("limit must be an integer >= 2")
    if freq not in ("daily", "weekly"):
        return _err("freq must be 'daily' or 'weekly'")

    sym_df   = db.get_ohlcv_df(symbol.upper(), freq, limit=limit)
    bench_df = db.get_ohlcv_df(bench, freq, limit=limit)

    if sym_df.empty:
        return _err(f"No data for {symbol.upper()}. Fetch it first.", 404)
    if bench_df.empty:
        return _err(f"No data for benchmark {bench}. Fetch it first.", 404)

    import numpy as np
    # Align on common dates
    common = sym_df.index.intersection(bench_df.index)
    if len(common) < 2:
        return _err("Not enough overlapping dates between symbol and benchmark", 404)

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


# -- Correlations --------------------------------------------------------------

@features_bp.route("/api/correlations", methods=["GET"])
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
        return _err("limit must be an integer >= 5")
    if freq not in ("daily", "weekly"):
        return _err("freq must be 'daily' or 'weekly'")

    symbols = [s["symbol"] for s in db.list_symbols()]
    if len(symbols) < 2:
        return _err("Need at least 2 symbols in the watchlist", 400)

    import numpy as np

    frames = {}
    for sym in symbols:
        df = db.get_ohlcv_df(sym, freq, limit=limit)
        if not df.empty and len(df) >= 5:
            frames[sym] = df["close"].pct_change().dropna()

    if len(frames) < 2:
        return _err("Not enough symbols with data", 400)

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


# -- Positions (Portfolio) -----------------------------------------------------

@features_bp.route("/api/positions", methods=["GET"])
def list_positions():
    include_closed = request.args.get("include_closed", "true").lower() != "false"
    positions = db.list_positions(include_closed=include_closed)

    # Enrich with current price and unrealised P&L
    for pos in positions:
        if pos.get("closed_at"):
            if pos.get("exit_price") and pos.get("entry_price"):
                pos["realised_pnl"] = round(
                    (pos["exit_price"] - pos["entry_price"]) * pos["qty"], 2)
            continue
        ohlcv = db.get_ohlcv(pos["symbol"], "daily", limit=1)
        if ohlcv:
            cur_price = ohlcv[-1]["close"]
            pos["current_price"]  = round(cur_price, 2)
            pos["current_value"]  = round(cur_price * pos["qty"], 2)
            pos["unrealised_pnl"] = round(
                (cur_price - pos["entry_price"]) * pos["qty"], 2)
            pos["pnl_pct"] = round(
                (cur_price / pos["entry_price"] - 1) * 100, 2)

    return jsonify(positions)


@features_bp.route("/api/positions", methods=["POST"])
def create_position():
    body = request.get_json(silent=True) or {}
    symbol = body.get("symbol", "").strip().upper()
    if not symbol:
        return _err("symbol is required")
    try:
        qty         = float(body["qty"])
        entry_price = float(body["entry_price"])
        if qty == 0:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return _err("qty (non-zero) and entry_price are required numbers")

    opened_at = body.get("opened_at")
    notes     = body.get("notes", "")
    pos_id    = db.add_position(symbol, qty, entry_price, opened_at, notes)
    return jsonify({"id": pos_id, "message": "Position created"}), 201


@features_bp.route("/api/positions/<int:pos_id>", methods=["PUT"])
def update_position(pos_id):
    body = request.get_json(silent=True) or {}
    allowed = {"qty", "entry_price", "opened_at", "closed_at", "exit_price", "notes"}
    updates = {k: body[k] for k in allowed if k in body}
    if not updates:
        return _err("No valid fields to update")
    db.update_position(pos_id, **updates)
    return jsonify({"message": "updated"})


@features_bp.route("/api/positions/<int:pos_id>", methods=["DELETE"])
def delete_position(pos_id):
    db.delete_position(pos_id)
    return jsonify({"message": "deleted"})


# -- Volume Profile ------------------------------------------------------------

@features_bp.route("/api/volume-profile/<string:symbol>", methods=["GET"])
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
        return _err("limit (>=5) and bins (>=2) must be positive integers")
    if freq not in ("daily", "weekly"):
        return _err("freq must be 'daily' or 'weekly'")

    df = db.get_ohlcv_df(symbol.upper(), freq, limit=limit)
    if df.empty:
        return _err("No data. Fetch the symbol first.", 404)

    import numpy as np
    prices = ((df["high"] + df["low"]) / 2).values
    vols   = df["volume"].values
    lo, hi = prices.min(), prices.max()
    if lo >= hi:
        return _err("Insufficient price range", 400)

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


# ── News ───────────────────────────────────────────────────────────────────────

@features_bp.route("/api/news/<string:symbol>", methods=["GET"])
def get_news(symbol):
    limit = min(int(request.args.get("limit", 20)), 50)
    articles = news_mod.fetch_news(symbol, limit=limit)
    return jsonify(articles)


# ── Sector Heatmap ─────────────────────────────────────────────────────────────

@features_bp.route("/api/sector-heatmap", methods=["GET"])
def sector_heatmap():
    import datetime
    import numpy as np
    symbols = db.list_symbols()
    if not symbols:
        return jsonify([])

    today_str = datetime.date.today().isoformat()
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


# ── Signals Dashboard ──────────────────────────────────────────────────────────

@features_bp.route("/api/signals", methods=["GET"])
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


# ── Watchlist Export / Import ──────────────────────────────────────────────────

@features_bp.route("/api/export", methods=["GET"])
def export_watchlist():
    return jsonify({
        "version":   2,
        "symbols":   db.list_symbols(),
        "alerts":    db.list_alerts(),
        "positions": db.list_positions(),
    })


@features_bp.route("/api/import", methods=["POST"])
def import_watchlist():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict) or "symbols" not in data:
        return _err("Invalid import format — expected {symbols: [...], ...}")

    added = 0
    for sym_row in (data.get("symbols") or []):
        sym = (sym_row.get("symbol") or "").strip().upper()
        if not sym:
            continue
        ok = db.add_symbol(sym, sym_row.get("name", ""), sym_row.get("sector", ""))
        if ok:
            added += 1
            if sym_row.get("group_tag"):
                db.set_symbol_group(sym, sym_row["group_tag"])
            if sym_row.get("notes"):
                db.set_symbol_notes(sym, sym_row["notes"])

    for a in (data.get("alerts") or []):
        try:
            db.add_alert(a["symbol"], a["field"], a["condition"], float(a["threshold"]))
        except Exception:
            pass

    return jsonify({"imported": added})


# ── Risk Calculator ────────────────────────────────────────────────────────────

@features_bp.route("/api/risk/<string:symbol>", methods=["GET"])
def get_risk(symbol):
    import numpy as np
    account = float(request.args.get("account", 10000))
    risk_pct = float(request.args.get("risk_pct", 1.0)) / 100
    atr_mult = float(request.args.get("atr_mult", 2.0))

    df = db.get_ohlcv_df(symbol.upper(), "daily", limit=60)
    if df.empty or len(df) < 15:
        return _err("Not enough data", 404)

    close = df["close"].iloc[-1]
    atr14 = _atr(df["high"], df["low"], df["close"], 14).iloc[-1]

    stop_distance = atr14 * atr_mult
    stop_loss     = close - stop_distance
    stop_pct      = stop_distance / close

    risk_amount   = account * risk_pct
    shares        = int(risk_amount / stop_distance) if stop_distance > 0 else 0
    position_size = shares * close

    # Simple R:R targets
    tp1 = close + stop_distance * 1.5
    tp2 = close + stop_distance * 3.0

    # Annualised vol (20-day)
    ret     = df["close"].pct_change().dropna()
    ann_vol = float(ret.tail(20).std() * np.sqrt(252)) if len(ret) >= 20 else None

    # Kelly fraction (very rough: 55% win, 1.5 R:R)
    kelly = max(0.0, 0.55 - 0.45 / 1.5)

    return jsonify({
        "symbol":        symbol.upper(),
        "price":         round(float(close), 2),
        "atr14":         round(float(atr14), 4),
        "stop_distance": round(float(stop_distance), 4),
        "stop_loss":     round(float(stop_loss), 2),
        "stop_pct":      round(float(stop_pct), 4),
        "tp1":           round(float(tp1), 2),
        "tp2":           round(float(tp2), 2),
        "shares":        shares,
        "position_size": round(float(position_size), 2),
        "risk_amount":   round(float(risk_amount), 2),
        "ann_vol":       round(float(ann_vol), 4) if ann_vol else None,
        "kelly":         round(kelly, 4),
    })


# ── Anomaly Detection ──────────────────────────────────────────────────────────

@features_bp.route("/api/anomalies", methods=["GET"])
def get_anomalies():
    import numpy as np
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
            gap_pct = (df["open"].iloc[-1] - close.iloc[-2]) / close.iloc[-2]
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


# ── Journal ────────────────────────────────────────────────────────────────────

@features_bp.route("/api/journal", methods=["GET"])
def list_journal():
    symbol = request.args.get("symbol")
    tag    = request.args.get("tag")
    return jsonify(db.list_journal(symbol.upper() if symbol else None, tag))


@features_bp.route("/api/journal", methods=["POST"])
def create_journal_entry():
    from datetime import datetime as _dt
    body = request.get_json(silent=True) or {}
    symbol = body.get("symbol", "").strip().upper()
    if not symbol:
        return _err("symbol is required")
    try:
        entry_price = float(body["entry_price"])
        qty         = float(body.get("qty", 1))
    except (KeyError, TypeError, ValueError):
        return _err("entry_price (number) is required")

    exit_p = body.get("exit_price")
    stop_p = body.get("stop_loss")
    jid = db.add_journal_entry(
        symbol=symbol,
        direction=body.get("direction", "long"),
        entry_date=body.get("entry_date", _dt.now().date().isoformat()),
        entry_price=entry_price,
        qty=qty,
        exit_date=body.get("exit_date"),
        exit_price=float(exit_p) if exit_p is not None else None,
        stop_loss=float(stop_p) if stop_p is not None else None,
        setup=body.get("setup", ""),
        tags=body.get("tags", ""),
        thesis=body.get("thesis", ""),
    )
    return jsonify({"id": jid, "message": "Journal entry created"}), 201


@features_bp.route("/api/journal/<int:entry_id>", methods=["PUT"])
def update_journal_entry(entry_id):
    body    = request.get_json(silent=True) or {}
    allowed = {"direction", "entry_date", "exit_date", "entry_price",
               "exit_price", "stop_loss", "qty", "setup", "tags", "thesis"}
    updates = {k: body[k] for k in allowed if k in body}
    if not updates:
        return _err("No valid fields to update")
    db.update_journal_entry(entry_id, **updates)
    return jsonify({"message": "updated"})


@features_bp.route("/api/journal/<int:entry_id>", methods=["DELETE"])
def delete_journal_entry(entry_id):
    db.delete_journal_entry(entry_id)
    return jsonify({"message": "deleted"})


# ── Portfolio Analytics ────────────────────────────────────────────────────────

@features_bp.route("/api/analytics", methods=["GET"])
def get_analytics():
    import numpy as np

    positions = db.list_positions(include_closed=True)
    closed    = [p for p in positions if p.get("closed_at") and p.get("exit_price")]

    if not closed:
        return jsonify({
            "trade_count": 0, "win_rate": None, "profit_factor": None,
            "avg_win": None, "avg_loss": None, "sharpe": None,
            "max_drawdown": None, "equity_curve": [], "trades": [],
        })

    closed.sort(key=lambda p: p.get("closed_at", ""))
    trades = []
    for p in closed:
        pnl = (p["exit_price"] - p["entry_price"]) * p["qty"]
        trades.append({
            "symbol": p["symbol"],
            "date":   p["closed_at"][:10],
            "pnl":    round(pnl, 2),
            "pct":    round((p["exit_price"] / p["entry_price"] - 1) * 100, 2),
        })

    pnls   = [t["pnl"] for t in trades]
    wins   = [v for v in pnls if v > 0]
    losses = [v for v in pnls if v <= 0]

    win_rate      = len(wins) / len(pnls) if pnls else None
    avg_win       = float(np.mean(wins))  if wins   else None
    avg_loss      = float(np.mean(losses)) if losses else None
    profit_factor = abs(sum(wins) / sum(losses)) if sum(losses) != 0 else None

    cum = 0
    equity = []
    for t in trades:
        cum += t["pnl"]
        equity.append({"date": t["date"], "equity": round(cum, 2)})

    arr    = np.array(pnls)
    sharpe = float(arr.mean() / arr.std() * np.sqrt(252)) if len(arr) >= 3 and arr.std() > 0 else None

    eq_vals = np.array([e["equity"] for e in equity])
    if len(eq_vals) >= 2:
        peak   = np.maximum.accumulate(eq_vals)
        dd     = (eq_vals - peak) / np.where(np.abs(peak) > 0, np.abs(peak), 1.0)
        max_dd = float(dd.min())
    else:
        max_dd = None

    return jsonify({
        "trade_count":   len(trades),
        "win_rate":      round(win_rate, 4)      if win_rate      is not None else None,
        "profit_factor": round(profit_factor, 4) if profit_factor is not None else None,
        "avg_win":       round(avg_win, 2)       if avg_win       is not None else None,
        "avg_loss":      round(avg_loss, 2)      if avg_loss      is not None else None,
        "sharpe":        round(sharpe, 4)        if sharpe        is not None else None,
        "max_drawdown":  round(max_dd, 4)        if max_dd        is not None else None,
        "equity_curve":  equity,
        "trades":        trades,
    })


# ── R-Multiple Analytics ───────────────────────────────────────────────────────

@features_bp.route("/api/r-analytics", methods=["GET"])
def get_r_analytics():
    """R-distribution from journal entries that have stop_loss recorded."""
    entries = db.list_journal()

    BUCKETS = [
        {"label": "< −2R",       "min": -999, "max": -2  },
        {"label": "−2R to −1R",  "min": -2,   "max": -1  },
        {"label": "−1R to −0.5R","min": -1,   "max": -0.5},
        {"label": "−0.5R to 0",  "min": -0.5, "max":  0  },
        {"label": "0 to +1R",    "min":  0,   "max":  1  },
        {"label": "+1R to +3R",  "min":  1,   "max":  3  },
        {"label": "+3R to +10R", "min":  3,   "max": 10  },
        {"label": "> +10R",      "min": 10,   "max": 999 },
    ]

    r_trades = []
    for e in entries:
        if e.get("exit_price") is None or e.get("stop_loss") is None:
            continue
        entry = float(e["entry_price"])
        stop  = float(e["stop_loss"])
        exit_ = float(e["exit_price"])
        risk  = abs(entry - stop)
        if risk < 0.0001:
            continue
        r = (exit_ - entry) / risk if e.get("direction", "long") != "short" else (entry - exit_) / risk
        r_trades.append({
            "symbol":      e["symbol"],
            "date":        (e.get("exit_date") or e.get("entry_date") or "")[:10],
            "r":           round(r, 3),
            "setup_grade": e.get("setup_grade") or "",
        })

    if not r_trades:
        return jsonify({"count": 0, "histogram": BUCKETS})

    rs     = [t["r"] for t in r_trades]
    wins   = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    n      = len(rs)

    win_rate     = len(wins) / n
    avg_win_r    = float(np.mean(wins))   if wins   else 0.0
    avg_loss_r   = float(np.mean(losses)) if losses else 0.0
    payoff_ratio = abs(avg_win_r / avg_loss_r) if avg_loss_r else None
    expectancy   = round(win_rate * avg_win_r + (1 - win_rate) * avg_loss_r, 3)

    # Slippage: how much worse than -1R are average losses?
    avg_loss_slippage = round(avg_loss_r - (-1.0), 3) if losses else None

    for b in BUCKETS:
        b["count"] = sum(1 for r in rs if b["min"] <= r < b["max"])
        b["pct"]   = round(b["count"] / n * 100, 1)

    # Per-grade breakdown
    grade_stats = {}
    for grade in ("A", "B", "C", ""):
        g_rs = [t["r"] for t in r_trades if t["setup_grade"] == grade]
        if not g_rs:
            continue
        g_wins   = [r for r in g_rs if r > 0]
        g_losses = [r for r in g_rs if r <= 0]
        g_wr     = len(g_wins) / len(g_rs)
        g_aw     = float(np.mean(g_wins))   if g_wins   else 0.0
        g_al     = float(np.mean(g_losses)) if g_losses else 0.0
        grade_stats[grade or "Ungraded"] = {
            "count":      len(g_rs),
            "win_rate":   round(g_wr, 3),
            "avg_r":      round(float(np.mean(g_rs)), 3),
            "expectancy": round(g_wr * g_aw + (1 - g_wr) * g_al, 3),
        }

    return jsonify({
        "count":              n,
        "win_rate":           round(win_rate, 4),
        "avg_win_r":          round(avg_win_r, 3),
        "avg_loss_r":         round(avg_loss_r, 3),
        "payoff_ratio":       round(payoff_ratio, 3) if payoff_ratio else None,
        "expectancy":         expectancy,
        "avg_loss_slippage":  avg_loss_slippage,
        "histogram":          BUCKETS,
        "grade_stats":        grade_stats,
    })


# ── Pair Trading / Spread ──────────────────────────────────────────────────────

@features_bp.route("/api/spread", methods=["GET"])
def get_spread():
    import numpy as np

    sym1 = request.args.get("sym1", "").strip().upper()
    sym2 = request.args.get("sym2", "").strip().upper()
    freq = request.args.get("freq", "daily")
    try:
        limit  = int(request.args.get("limit",  252))
        window = int(request.args.get("window",  20))
    except (TypeError, ValueError):
        return _err("limit and window must be integers")

    if not sym1 or not sym2:  return _err("sym1 and sym2 are required")
    if sym1 == sym2:           return _err("sym1 and sym2 must be different")
    if freq not in ("daily", "weekly"): return _err("freq must be daily or weekly")

    df1 = db.get_ohlcv_df(sym1, freq, limit=limit)
    df2 = db.get_ohlcv_df(sym2, freq, limit=limit)

    if df1.empty: return _err(f"No data for {sym1}. Fetch it first.", 404)
    if df2.empty: return _err(f"No data for {sym2}. Fetch it first.", 404)

    common = df1.index.intersection(df2.index)
    if len(common) < window + 5:
        return _err("Not enough overlapping data", 404)

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


# ── Macro Overlay ──────────────────────────────────────────────────────────────

@features_bp.route("/api/macro", methods=["GET"])
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


# ── Macro Economic Calendar ────────────────────────────────────────────────────

@features_bp.route("/api/calendar", methods=["GET"])
def get_calendar():
    import datetime as dt

    today = dt.date.today()
    year  = today.year

    fomc_dates = [
        "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18",
        "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-17",
        "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
        "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-16",
    ]

    events = [{"date": d, "type": "FOMC", "label": "FOMC Meeting", "color": "#3b82f6"}
              for d in fomc_dates]

    months = [f"{year:04d}-{m:02d}" for m in range(1, 13)] + \
             [f"{year+1:04d}-{m:02d}" for m in range(1, 7)]
    for ym in months:
        events.append({"date": ym + "-13", "type": "CPI",
                        "label": "CPI Release", "color": "#f97316"})
        events.append({"date": ym + "-05", "type": "NFP",
                        "label": "Jobs Report (NFP)", "color": "#22c55e"})

    for sym in db.list_symbols():
        ed = sym.get("next_earnings")
        if ed:
            events.append({"date": ed, "type": "EARNINGS",
                            "label": f"{sym['symbol']} Earnings",
                            "symbol": sym["symbol"], "color": "#a855f7"})

    past_limit   = (today - dt.timedelta(days=30)).isoformat()
    future_limit = (today + dt.timedelta(days=180)).isoformat()
    events = sorted(
        [e for e in events if past_limit <= e["date"] <= future_limit],
        key=lambda e: e["date"]
    )
    return jsonify(events)


# ── Strategies ─────────────────────────────────────────────────────────────────

@features_bp.route("/api/strategies", methods=["GET"])
def list_strategies_route():
    return jsonify(db.list_strategies())


@features_bp.route("/api/strategies", methods=["POST"])
def create_strategy():
    body = request.get_json(silent=True) or {}
    name = body.get("name", "").strip()
    if not name:
        return _err("name is required")
    conditions = body.get("conditions", [])
    if not isinstance(conditions, list):
        return _err("conditions must be a list")
    sid = db.add_strategy(name, conditions)
    return jsonify({"id": sid, "message": "Strategy created"}), 201


@features_bp.route("/api/strategies/<int:strategy_id>", methods=["PUT"])
def update_strategy_route(strategy_id):
    body = request.get_json(silent=True) or {}
    name       = body.get("name")
    conditions = body.get("conditions")
    if name is None and conditions is None:
        return _err("name or conditions required")
    db.update_strategy(strategy_id, name=name, conditions=conditions)
    return jsonify({"message": "updated"})


@features_bp.route("/api/strategies/<int:strategy_id>", methods=["DELETE"])
def delete_strategy_route(strategy_id):
    db.delete_strategy(strategy_id)
    return jsonify({"message": "deleted"})


# -- Relative Rotation Graph ---------------------------------------------------

@features_bp.route("/api/rrg", methods=["GET"])
def get_rrg():
    import numpy as np

    benchmark = request.args.get("benchmark", "SPY").upper()
    period    = max(2, min(int(request.args.get("period", 10)), 52))
    trail_n   = max(2, min(int(request.args.get("trail", 5)), 12))

    bdf = db.get_ohlcv_df(benchmark, "weekly", limit=120)
    if bdf.empty:
        return _err(f"No data for benchmark {benchmark}. Fetch it first.", 404)

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


# ── Newsletter Data ──────────────────────────────────────────────────────────

@features_bp.route("/api/newsletter/data", methods=["GET"])
def get_newsletter_data():
    try:
        n_charts = min(int(request.args.get("n", 20)), 50)
    except (TypeError, ValueError):
        n_charts = 20
    try:
        return jsonify(newsletter_engine.compute_newsletter_data(n_charts=n_charts))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Earnings Dates ────────────────────────────────────────────────────────────

@features_bp.route("/api/earnings/<string:symbol>", methods=["GET"])
def get_earnings_dates(symbol):
    """Return known earnings dates for a symbol from the watchlist metadata."""
    sym = symbol.upper()
    rows = db.list_symbols()
    entry = next((r for r in rows if r["symbol"] == sym), None)
    dates = []
    if entry and entry.get("next_earnings"):
        dates.append({"date": entry["next_earnings"], "type": "scheduled"})
    return jsonify({"symbol": sym, "dates": dates})


# ═══════════════════════════════════════════════════════════════════════════════
# TRADING PROCESS TOOLS
# ═══════════════════════════════════════════════════════════════════════════════

def _swing_data_for(symbol: str) -> dict:
    """Compute swing-data metrics for a symbol. Returns dict or raises."""
    sym = symbol.upper()
    df  = db.get_ohlcv_df(sym, freq="daily", limit=260)
    if df.empty or len(df) < 20:
        raise ValueError(f"Insufficient data for {sym}")

    close  = df["close"]
    high   = df["high"]
    low    = df["low"]
    volume = df["volume"]

    last_close = float(close.iloc[-1])
    last_high  = float(high.iloc[-1])
    last_low   = float(low.iloc[-1])

    # ADR% — average daily range as % of close, 20-day
    adr_pct = float(((high - low) / close).tail(20).mean() * 100)

    # ATR-14
    atr14 = float(_atr(high, low, close, 14).iloc[-1])

    # RVOL — today's volume vs 50-day average (excluding today)
    avg_vol_50 = float(volume.iloc[-51:-1].mean()) if len(volume) >= 51 else float(volume.iloc[:-1].mean())
    today_vol  = float(volume.iloc[-1])
    rvol = round(today_vol / avg_vol_50, 2) if avg_vol_50 > 0 else 0.0

    # ATR multiple from 50-MA
    ma50 = float(close.tail(51).mean())
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
    rsi_7  = round(float(_rsi(close, 7).iloc[-1]),  1) if len(close) >= 8  else None
    rsi_14 = round(float(_rsi(close, 14).iloc[-1]), 1) if len(close) >= 15 else None
    rsi_21 = round(float(_rsi(close, 21).iloc[-1]), 1) if len(close) >= 22 else None

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

    kama10_stat = _kama_stat(_kama(close, 10))
    kama20_stat = _kama_stat(_kama(close, 20))
    kama50_stat = _kama_stat(_kama(close, 50))
    kama_alignment = sum(1 for s in [kama10_stat, kama20_stat, kama50_stat] if s and s["above"])

    return {
        "symbol":        sym,
        "last_close":    round(last_close, 2),
        "adr_pct":       round(adr_pct, 2),
        "atr_14":        round(atr14, 4),
        "rvol":          rvol,
        "atr_mult_50ma": round(atr_mult_50ma, 2),
        "ma50":          round(ma50, 2),
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
    }


def _grade_from_swing(sd: dict) -> dict:
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


# ── Swing Data ────────────────────────────────────────────────────────────────

@features_bp.route("/api/swing-data/<string:symbol>", methods=["GET"])
def get_swing_data(symbol):
    try:
        return jsonify(_swing_data_for(symbol))
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logging.exception("swing-data error")
        return jsonify({"error": str(e)}), 500


# ── Setup Grade ───────────────────────────────────────────────────────────────

@features_bp.route("/api/setup-grade/<string:symbol>", methods=["GET"])
def get_setup_grade(symbol):
    try:
        sd     = _swing_data_for(symbol)
        result = _grade_from_swing(sd)
        result.update(sd)
        # Persist grade to DB
        try:
            db.set_setup_grade(symbol, result["grade"])
        except Exception:
            pass
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logging.exception("setup-grade error")
        return jsonify({"error": str(e)}), 500


# ── Market Breadth ────────────────────────────────────────────────────────────

@features_bp.route("/api/breadth", methods=["GET"])
def get_market_breadth():
    symbols = db.list_symbols()
    if not symbols:
        return jsonify({"error": "No symbols in watchlist"}), 404

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

    # Equal-weight vs cap-weight divergence (RSP = EW S&P 500, SPY = CW S&P 500)
    ew_cw = None
    try:
        import yfinance as yf
        raw = yf.download(["SPY", "RSP"], period="2mo", auto_adjust=True, progress=False)["Close"]
        spy = raw["SPY"].dropna()
        rsp = raw["RSP"].dropna()
        if len(spy) >= 22 and len(rsp) >= 22:
            ratio_now  = float(rsp.iloc[-1])  / float(spy.iloc[-1])
            ratio_prev = float(rsp.iloc[-22]) / float(spy.iloc[-22])
            chg = round((ratio_now / ratio_prev - 1) * 100, 2)
            ew_cw = {
                "ratio":   round(ratio_now, 4),
                "chg_20d": chg,
                "signal":  "broadening" if chg > 0.5 else "narrowing" if chg < -0.5 else "neutral",
            }
    except Exception:
        pass

    return jsonify({
        "total":          total,
        "pct_above_20ma": pct(above_20),
        "pct_above_50ma": pct(above_50),
        "pct_above_200ma":pct(above_200),
        "advances":       advances,
        "declines":       declines,
        "ad_ratio":       round(advances / declines, 2) if declines else advances,
        "new_highs":      new_highs,
        "new_lows":       new_lows,
        "ew_cw":          ew_cw,
    })


# ── Position Sizer ────────────────────────────────────────────────────────────

@features_bp.route("/api/position-size", methods=["POST"])
def calc_position_size():
    body        = request.get_json(silent=True) or {}
    account     = float(body.get("account",   100000))
    risk_pct    = float(body.get("risk_pct",  0.5)) / 100.0
    entry       = float(body.get("entry",     0))
    stop        = float(body.get("stop",      0))
    if entry <= 0 or stop <= 0 or stop >= entry:
        return jsonify({"error": "entry must be > stop > 0"}), 400

    dollar_risk  = account * risk_pct
    risk_per_sh  = entry - stop
    shares       = int(dollar_risk / risk_per_sh)
    gross_exp    = shares * entry
    stop_pct     = (entry - stop) / entry * 100

    return jsonify({
        "account":      account,
        "risk_pct":     risk_pct * 100,
        "entry":        entry,
        "stop":         stop,
        "dollar_risk":  round(dollar_risk, 2),
        "risk_per_sh":  round(risk_per_sh, 4),
        "shares":       shares,
        "gross_exp":    round(gross_exp, 2),
        "stop_pct":     round(stop_pct, 2),
        "pct_portfolio":round(gross_exp / account * 100, 2),
        "tp1_1r":       round(entry + risk_per_sh * 1,  2),
        "tp2_3r":       round(entry + risk_per_sh * 3,  2),
        "tp3_5r":       round(entry + risk_per_sh * 5,  2),
        "tp4_10r":      round(entry + risk_per_sh * 10, 2),
        "tranche1_stop":round(entry - risk_per_sh * 0.33, 2),
        "tranche2_stop":round(entry - risk_per_sh * 0.67, 2),
        "tranche3_stop":stop,
    })


# ── Focus Pipeline Tier ───────────────────────────────────────────────────────

@features_bp.route("/api/symbols/<string:symbol>/tier", methods=["PUT"])
def set_symbol_tier_route(symbol):
    body = request.get_json(silent=True) or {}
    tier = body.get("tier", "watchlist")
    if not db.set_symbol_tier(symbol, tier):
        return jsonify({"error": f"Invalid tier: {tier}. Use watchlist/stalk/focus/active"}), 400
    return jsonify({"symbol": symbol.upper(), "tier": tier})


@features_bp.route("/api/focus-pipeline", methods=["GET"])
def get_focus_pipeline():
    """Return all symbols grouped by watchlist tier, with swing data and grade."""
    tiers   = db.list_symbols_by_tier()
    result  = {}
    for tier, syms in tiers.items():
        enriched = []
        for s in syms:
            entry = {
                "symbol":      s["symbol"],
                "name":        s.get("name") or "",
                "sector":      s.get("sector") or "",
                "setup_grade": s.get("setup_grade") or "",
                "tier":        tier,
            }
            try:
                sd = _swing_data_for(s["symbol"])
                entry.update({
                    "adr_pct":       sd["adr_pct"],
                    "rvol":          sd["rvol"],
                    "atr_mult_50ma": sd["atr_mult_50ma"],
                })
            except Exception:
                pass
            enriched.append(entry)
        result[tier] = enriched
    return jsonify(result)


# ── Data Coverage ─────────────────────────────────────────────────────────────

@features_bp.route("/api/data-coverage", methods=["GET"])
def get_data_coverage():
    """Per-symbol coverage stats: date range, bar counts, staleness."""
    from datetime import date as _date
    conn = db.get_connection()
    rows = conn.execute("""
        SELECT s.symbol, s.name, s.sector, s.last_fetch,
               COUNT(CASE WHEN o.freq='daily'  THEN 1 END) AS daily_count,
               COUNT(CASE WHEN o.freq='weekly' THEN 1 END) AS weekly_count,
               MIN(CASE WHEN o.freq='daily'    THEN o.date END) AS first_daily,
               MAX(CASE WHEN o.freq='daily'    THEN o.date END) AS last_daily
        FROM symbols s
        LEFT JOIN ohlcv o ON o.symbol = s.symbol
        GROUP BY s.symbol
        ORDER BY s.symbol
    """).fetchall()
    conn.close()

    today = _date.today()
    result = []
    for r in rows:
        r = dict(r)
        no_data = not r["first_daily"]
        has_gap = False
        if r["last_daily"]:
            last = _date.fromisoformat(r["last_daily"])
            has_gap = (today - last).days > 7
        result.append({
            "symbol":       r["symbol"],
            "name":         r["name"] or "",
            "sector":       r["sector"] or "",
            "last_fetch":   r["last_fetch"] or "",
            "daily_count":  r["daily_count"] or 0,
            "weekly_count": r["weekly_count"] or 0,
            "first_daily":  r["first_daily"] or "",
            "last_daily":   r["last_daily"] or "",
            "no_data":      no_data,
            "has_gap":      has_gap,
        })
    return jsonify(result)


@features_bp.route("/api/fetch-range/<string:symbol>", methods=["POST"])
def fetch_range(symbol):
    """Fetch history for a symbol between start_date and end_date."""
    body       = request.get_json(silent=True) or {}
    start_date = body.get("start_date", "2000-01-01")
    end_date   = body.get("end_date", "")
    try:
        import data_fetcher as df_mod
        df_mod.fetch_full_history(symbol.upper(), start=start_date)
        return jsonify({"ok": True, "symbol": symbol.upper(), "start": start_date})
    except Exception as e:
        logging.exception("fetch-range error")
        return jsonify({"error": str(e)}), 500
