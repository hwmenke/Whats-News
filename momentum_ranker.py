"""
momentum_ranker.py — Cross-Sectional Momentum Ranking

For every symbol in the watchlist, computes momentum across four lookbacks
using the standard Jegadeesh-Titman construction:
  1M  = 21-bar total return
  3M  = 63-bar total return
  6M  = 126-bar total return
  12M = 252-bar return, but SKIP the most recent 21 bars
         (avoids the short-term reversal effect at the 1-month horizon)

Composite score = equal-weight z-score of (3M, 6M, 12M-1M).
  — 1M is shown in the table but excluded from the composite because it
    reverses at short horizons; 3M–12M is the robust signal band.

Tier assignment:
  Top 25%    → STRONG   (green)
  25–50%     → LEADING  (light green)
  50–75%     → LAGGING  (light red)
  Bottom 25% → WEAK     (red)

Also returns a simple equal-rebalance momentum-portfolio backtest:
  At each monthly rebalance, go long the top-tercile symbols.
  Compare vs equal-weight of the full universe.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import database as db


def _safe(v):
    if v is None: return None
    try:
        if np.isnan(v): return None
    except: pass
    return round(float(v), 4)


def compute_momentum_ranks() -> dict:
    """
    Ranks all watchlist symbols by momentum.
    Returns: ranked list + portfolio simulation.
    """
    syms_meta = db.list_symbols()
    if not syms_meta:
        return {"error": "No symbols in watchlist"}

    symbols = [s["symbol"] for s in syms_meta]

    # ── Gather last price + returns for each symbol ────────────
    rows    = []
    closes  = {}    # sym → close Series (for portfolio simulation)

    for sym in symbols:
        df = db.get_ohlcv_df(sym, "daily", limit=280)
        if df.empty or len(df) < 22:
            continue
        close = df["close"]
        closes[sym] = close

        n   = len(close)
        ret = lambda h: float((close.iloc[-1] / close.iloc[-h] - 1)) if n >= h else None

        r1m  = ret(21)
        r3m  = ret(63)   if n >= 63  else None
        r6m  = ret(126)  if n >= 126 else None
        # 12M-1M: close[-252] → close[-21]
        r12m1m = None
        if n >= 252 and n >= 21:
            r12m1m = float(close.iloc[-21] / close.iloc[-252] - 1)

        last_price = _safe(close.iloc[-1])
        prev_price = _safe(close.iloc[-2]) if n >= 2 else None
        chg1d      = ((close.iloc[-1] / close.iloc[-2]) - 1) if (n >= 2 and prev_price) else None

        rows.append({
            "symbol":  sym,
            "name":    next((s["name"] for s in syms_meta if s["symbol"] == sym), ""),
            "price":   last_price,
            "chg1d":   _safe(chg1d),
            "ret_1m":  _safe(r1m),
            "ret_3m":  _safe(r3m),
            "ret_6m":  _safe(r6m),
            "ret_12m_skip1m": _safe(r12m1m),
        })

    if not rows:
        return {"error": "Insufficient data — fetch symbols first"}

    df_ranks = pd.DataFrame(rows)

    # ── Composite z-score ─────────────────────────────────────
    # Use the three robust horizons: 3M, 6M, 12M-1M
    score_cols = ["ret_3m", "ret_6m", "ret_12m_skip1m"]
    for col in score_cols:
        s = df_ranks[col].astype(float)
        mu, std = s.mean(), s.std()
        df_ranks[f"z_{col}"] = (s - mu) / std.clip(lower=1e-10) if std > 1e-10 else 0.0

    z_cols = [f"z_{c}" for c in score_cols]
    available = [c for c in z_cols if df_ranks[c].notna().any()]
    df_ranks["composite"] = df_ranks[available].mean(axis=1) if available else 0.0

    # ── Rank + tier ────────────────────────────────────────────
    df_ranks.sort_values("composite", ascending=False, inplace=True, ignore_index=True)
    df_ranks["rank"] = df_ranks.index + 1
    n_syms = len(df_ranks)

    def _tier(rank):
        pct = rank / n_syms
        if pct <= 0.25: return "STRONG"
        if pct <= 0.50: return "LEADING"
        if pct <= 0.75: return "LAGGING"
        return "WEAK"

    df_ranks["tier"] = df_ranks["rank"].apply(_tier)
    df_ranks["composite"] = df_ranks["composite"].round(4)

    # ── Portfolio backtest (simple top-tercile rebalance) ─────
    portfolio = _momentum_portfolio(closes)

    result_rows = []
    for _, row in df_ranks.iterrows():
        result_rows.append({
            "rank":        int(row["rank"]),
            "symbol":      row["symbol"],
            "name":        row.get("name", ""),
            "price":       row["price"],
            "chg1d":       row["chg1d"],
            "ret_1m":      row["ret_1m"],
            "ret_3m":      row["ret_3m"],
            "ret_6m":      row["ret_6m"],
            "ret_12m_skip1m": row["ret_12m_skip1m"],
            "composite":   float(row["composite"]) if pd.notna(row["composite"]) else None,
            "tier":        row["tier"],
        })

    return {
        "rankings":  result_rows,
        "n_symbols": n_syms,
        "portfolio": portfolio,
    }


def _momentum_portfolio(closes: dict[str, pd.Series]) -> dict:
    """
    Backtest a monthly-rebalance top-tercile momentum portfolio.
    Uses the composite momentum score at each rebalance date.
    Returns equity curve vs equal-weight benchmark.
    """
    if len(closes) < 3:
        return {}

    # Align all series on a common daily date range
    prices = pd.DataFrame(closes).dropna(how="all")
    if len(prices) < 126:
        return {}

    prices = prices.fillna(method="ffill").dropna(how="all")
    rets   = prices.pct_change().fillna(0)

    # Monthly rebalance dates (~every 21 trading days)
    rebalance_idx = list(range(63, len(prices), 21))   # warm-up 63 bars

    port_rets   = pd.Series(0.0, index=rets.index)
    bench_rets  = rets.mean(axis=1)                    # equal-weight benchmark
    weights     = {}   # sym → weight

    for i, rb in enumerate(rebalance_idx):
        # Score at rebalance
        end_score   = rb
        scores      = {}
        for sym in closes:
            s = prices[sym].dropna()
            if len(s) < rb + 1:
                continue
            idx_in_prices = list(prices.index).index(prices.index[rb])
            # 63-bar return
            start63 = max(0, idx_in_prices - 63)
            r3m = (prices[sym].iloc[idx_in_prices] / prices[sym].iloc[start63]) - 1 if prices[sym].iloc[start63] > 0 else np.nan
            scores[sym] = r3m

        if not scores:
            continue

        sc_arr   = pd.Series(scores).dropna()
        thresh   = sc_arr.quantile(0.67)
        top_syms = sc_arr[sc_arr >= thresh].index.tolist()

        # Equal-weight among top symbols
        new_weights = {sym: 1.0 / len(top_syms) for sym in top_syms} if top_syms else {}
        weights = new_weights

        # Apply weights until next rebalance
        next_rb = rebalance_idx[i + 1] if i + 1 < len(rebalance_idx) else len(prices)
        for day_i in range(rb, next_rb):
            if day_i >= len(rets):
                break
            date = rets.index[day_i]
            day_ret = sum(weights.get(sym, 0) * rets.loc[date, sym]
                          for sym in weights if sym in rets.columns)
            port_rets.iloc[day_i] = day_ret

    # Build equity curves
    eq_port  = (1 + port_rets.iloc[63:]).cumprod()
    eq_bench = (1 + bench_rets.iloc[63:]).cumprod()

    dates = [d.strftime("%Y-%m-%d") for d in eq_port.index]
    return {
        "dates":     dates,
        "portfolio": [round(float(v), 4) for v in eq_port.values],
        "benchmark": [round(float(v), 4) for v in eq_bench.values],
        "total_return_port":  round(float(eq_port.iloc[-1] - 1), 4) if len(eq_port) else None,
        "total_return_bench": round(float(eq_bench.iloc[-1] - 1), 4) if len(eq_bench) else None,
    }
