"""
insights.py — derived analytics over the existing social-trends data.

Nothing here needs external data: it computes against ``themes.json``, the
existing OHLCV in SQLite, and the daily ``social_snapshots`` rows.

  • portfolio_exposure(symbols)   → which themes you own, weighted by purity
  • streak_summary(days=14)       → consecutive-day streaks on the top board
  • anomaly_baselines()           → per-theme momentum baseline + z-score
  • search_arbitrage(trends)      → Google leading social (or vice versa)
  • lifecycle_classify(spark)     → archetype + expected half-life heuristic
  • position_size(idea, capital)  → suggested $ size given catch-up + vol
  • seasonality_hint(theme)       → calendar-aware seasonality note
"""

from __future__ import annotations

import math
import statistics
from datetime import datetime, timedelta, timezone

import database as db
import social_trends as st


# ── Phase μ · Portfolio theme exposure ──────────────────────────────────────
def portfolio_exposure(symbols):
    """For a list of tickers, return per-theme exposure + coverage gaps."""
    syms = {s.upper() for s in symbols if s}
    if not syms:
        return {"holdings": [], "themes": [], "coverage_gaps": []}

    holdings = []
    theme_weights: dict[str, float] = {}
    theme_tickers: dict[str, list] = {}
    for sym in syms:
        themes = st.get_themes_for_ticker(sym)
        if not themes:
            holdings.append({"ticker": sym, "themes": []})
            continue
        holdings.append({"ticker": sym,
                         "themes": [{"theme": t["theme"], "purity": t["purity"]} for t in themes]})
        for t in themes:
            theme_weights[t["theme"]] = theme_weights.get(t["theme"], 0.0) + t["purity"]
            theme_tickers.setdefault(t["theme"], []).append(sym)

    total = sum(theme_weights.values()) or 1.0
    themes = sorted(
        [{
            "theme":  name,
            "weight": round(w / total * 100, 1),     # % of your themed exposure
            "score":  round(w, 2),                   # raw sum of purities
            "tickers": sorted(theme_tickers[name]),
        } for name, w in theme_weights.items()],
        key=lambda x: -x["weight"],
    )

    # Coverage gaps: themes the user owns *nothing* in.
    owned = {t["theme"] for t in themes}
    gaps = [{"theme": th["theme"],
             "top_play": sorted(th["stocks"], key=lambda s: -s["purity"])[0]["ticker"]}
            for th in st.load_themes() if th["theme"] not in owned]

    return {"holdings": holdings, "themes": themes, "coverage_gaps": gaps[:20]}


# ── Phase π · Streak tracking ───────────────────────────────────────────────
def streak_summary(days: int = 14, top_n: int = 30):
    """Consecutive days a term has held a top-N momentum spot."""
    conn = db.get_connection()
    today = datetime.now(timezone.utc).date()
    streaks: dict[str, int] = {}
    for offset in range(days):
        date_str = (today - timedelta(days=offset)).isoformat()
        rows = conn.execute(
            "SELECT term FROM social_snapshots WHERE date = ? "
            "ORDER BY momentum DESC LIMIT ?", (date_str, top_n)
        ).fetchall()
        top_terms = {r["term"] for r in rows}
        # any term that already has a streak from a more recent date AND is on this date
        for term in list(streaks):
            if term in top_terms and streaks[term] == offset:    # contiguous backwards
                streaks[term] = offset + 1
        for term in top_terms:
            streaks.setdefault(term, offset + 1 if offset == 0 else 0)
    conn.close()
    out = sorted(((term, days) for term, days in streaks.items() if days >= 2),
                 key=lambda x: -x[1])
    return [{"term": t, "days": d} for t, d in out[:20]]


# ── Phase π · Anomaly-of-anomaly (per-theme momentum z-score) ───────────────
def anomaly_baselines(payload: dict):
    """Flag momentum that's exceptional *for its theme*, not in absolute terms."""
    trends = payload.get("trends") or []
    by_theme: dict[str, list] = {}
    for t in trends:
        cat = t.get("category") or "—"
        if cat == "—":
            continue
        by_theme.setdefault(cat, []).append(t["momentum"])

    out = []
    for t in trends:
        cat = t.get("category")
        if not cat or cat == "—":
            continue
        peers = by_theme.get(cat, [])
        if len(peers) < 2:
            continue
        mean = sum(peers) / len(peers)
        sd   = statistics.pstdev(peers) or 1.0
        z    = (t["momentum"] - mean) / sd
        if z >= 1.5:
            out.append({"term": t["term"], "theme": cat,
                        "z": round(z, 2), "momentum": t["momentum"],
                        "baseline": round(mean, 1)})
    return sorted(out, key=lambda x: -x["z"])[:15]


# ── Phase κ.4 · Search arbitrage (Google leading social, or v.v.) ───────────
def search_arbitrage(payload: dict):
    """Estimate per-term lead/lag between Google and the social platforms.

    A positive ``lag_days`` means social is leading Google; negative means
    Google ran first. Computed as the index-difference between each series'
    peak point on its own spark.
    """
    out = []
    for t in payload.get("trends") or []:
        per_src = t.get("source_mom") or {}
        if "google" not in per_src or not (per_src.keys() - {"google"}):
            continue
        spark = t.get("spark") or []
        n = len(spark)
        if n < 6:
            continue
        # Without per-source raw series here we approximate: compare which
        # source the trend is *currently* driven by versus the overall peak.
        peak_idx = spark.index(max(spark))
        # 'Lag' heuristic: if Google's per-source momentum > social max,
        # google is leading (negative lag). Else social is leading.
        social_max = max((v for k, v in per_src.items() if k != "google"), default=0)
        google_val = per_src.get("google", 0)
        bias = google_val - social_max                    # >0 → google leads
        if abs(bias) < 5:
            continue
        out.append({
            "term":      t["term"],
            "bias":      round(bias, 1),
            "leader":    "google" if bias > 0 else (t.get("driven_by") or "social"),
            "peak_at":   f"d-{n - 1 - peak_idx}",
        })
    return sorted(out, key=lambda x: -abs(x["bias"]))[:15]


# ── Phase ν · Lifecycle classifier + half-life heuristic ────────────────────
_ARCHETYPES = {
    "slow-build":  "slowly building attention; tends to sustain for weeks",
    "spike-fade":  "sharp spike likely to fade within ~7 days",
    "plateau":     "elevated and sticky — attention is holding",
    "secular":     "broad multi-week ascent — durable",
    "rolled-over": "post-peak decline — most upside has passed",
    "flat":        "no real motion to model",
}


def lifecycle_classify(spark: list[float]):
    """Bucket a 30d spark into an archetype + give a half-life estimate."""
    n = len(spark)
    if n < 8:
        return {"archetype": "flat", "description": _ARCHETYPES["flat"], "half_life_days": None}

    peak  = max(spark); peak_idx = spark.index(peak)
    head  = sum(spark[:n // 3])     / max(1, n // 3)
    mid   = sum(spark[n // 3: 2 * n // 3]) / max(1, n // 3)
    tail  = sum(spark[-n // 4:])    / max(1, n // 4)
    rise  = (peak - head) / max(head, 5.0)
    decay = (peak - tail) / max(peak, 5.0)
    pos   = peak_idx / (n - 1)

    if peak < 30:
        archetype, hl = "flat", None
    elif decay > 0.45 and peak_idx < n - 4:
        archetype, hl = "rolled-over", 3
    elif rise > 1.5 and pos > 0.6:
        archetype, hl = "spike-fade", 7
    elif rise > 0.5 and 0.4 < pos < 0.85 and decay < 0.2:
        archetype, hl = "plateau", 14
    elif rise > 0.8 and pos > 0.75:
        archetype, hl = "slow-build", 21
    elif tail > head * 1.4:
        archetype, hl = "secular", 30
    else:
        archetype, hl = "plateau", 10

    return {"archetype": archetype, "description": _ARCHETYPES[archetype],
            "half_life_days": hl, "peak_at": f"d-{n - 1 - peak_idx}"}


# ── Phase ν · Position-size helper ──────────────────────────────────────────
def position_size(idea: dict, capital: float = 10_000.0, max_risk_pct: float = 1.5):
    """Suggest a $ size for an idea given catch-up, purity, and realised vol.

    Uses *only* locally-available data — no broker, no live quote stream. The
    output is a 'reasonable starting size' under a fixed-fractional risk model.
    """
    cu     = idea.get("catch_up")
    purity = idea.get("purity") or 0.5
    r20    = idea.get("ret_20d")
    if cu is None or r20 is None:
        return {"shares": None, "dollars": None, "note": "need price + catch-up data first"}

    # Realised 20d vol proxy: |20d return| / sqrt(20)
    realised_vol = abs(r20) / math.sqrt(20) if r20 else 1.0
    # Conviction weight: catch-up × purity (0–100)
    conviction   = (cu / 100.0) * purity                   # 0..1
    # Risk dollars allowed
    risk_dollars = capital * (max_risk_pct / 100.0) * (0.4 + 0.6 * conviction)
    # Stop distance ≈ 1.5 × realised vol → shares = risk / stop$
    price        = idea.get("price") or 1.0
    stop_pct     = max(2.0, realised_vol * 1.5)
    stop_dollars = price * (stop_pct / 100.0)
    shares       = int(risk_dollars / max(stop_dollars, 0.01))
    dollars      = shares * price
    return {
        "shares":       shares,
        "dollars":      round(dollars, 2),
        "stop_pct":     round(stop_pct, 1),
        "conviction":   round(conviction, 2),
        "note": (f"~{shares} sh ≈ ${dollars:,.0f} with a {stop_pct:.1f}% stop "
                 f"(conviction {conviction:.2f})."),
    }


# ── Phase π · Calendar seasonality hint ─────────────────────────────────────
_SEASONAL = {
    "GLP-1 / Weight Loss":   ("Jan",  "Resolutions season usually inflates weight-loss attention."),
    "Live Events / Concerts":("Summer","Tour announcements run from spring through summer."),
    "Crypto":                ("Q4",   "Crypto attention spikes when BTC tests new highs (often Q4)."),
    "Cannabis":              ("Apr",  "April 20 (4/20) drives a predictable annual attention spike."),
    "Energy Drinks":         ("Summer","Energy-drink searches climb through summer."),
    "Viral Drinkware":       ("Q4",   "Holiday gifting season drives Stanley-cup-style spikes."),
    "Beauty / Skincare":     ("Q4",   "Holiday gifting + Sephora sale season."),
    "Discount E-Commerce":   ("Nov",  "Black Friday / Cyber Monday is the seasonal peak."),
}


def seasonality_hint(theme: str):
    when, note = _SEASONAL.get(theme, (None, None))
    if not when:
        return None
    return {"theme": theme, "season": when, "note": note}


# ── Phase ρ · Notebook / CSV exporter for an idea ───────────────────────────
def theme_rotation(days_back: int = 7, top_n: int = 12):
    """Phase ξ.3 — which themes gained or lost attention vs N days ago.

    Aggregates daily snapshots by theme (via the term→category mapping that
    ``social_trends._theme_for_term`` resolves), then ranks themes by the
    delta in their average top-N momentum.
    """
    conn = db.get_connection()
    today = datetime.now(timezone.utc).date()
    then  = today - timedelta(days=days_back)

    def _theme_avg(date_str: str) -> dict[str, float]:
        rows = conn.execute(
            "SELECT term, momentum FROM social_snapshots WHERE date = ? "
            "ORDER BY momentum DESC LIMIT 60", (date_str,)
        ).fetchall()
        by_theme: dict[str, list[float]] = {}
        for r in rows:
            cat, _ = st._theme_for_term(r["term"])
            if not cat or cat == "—":
                continue
            by_theme.setdefault(cat, []).append(float(r["momentum"]))
        return {t: sum(v) / len(v) for t, v in by_theme.items() if v}

    cur = _theme_avg(today.isoformat())
    prev = _theme_avg(then.isoformat())
    conn.close()

    if not cur:
        return {"days": days_back, "rotation": [], "note": "no snapshots yet"}

    out = []
    for theme, mom_now in cur.items():
        mom_then = prev.get(theme)
        if mom_then is None:
            out.append({"theme": theme, "now": round(mom_now, 1),
                        "then": None, "delta": None, "direction": "new"})
        else:
            delta = mom_now - mom_then
            direction = "rising" if delta > 5 else "falling" if delta < -5 else "flat"
            out.append({"theme": theme, "now": round(mom_now, 1),
                        "then": round(mom_then, 1),
                        "delta": round(delta, 1), "direction": direction})
    out.sort(key=lambda r: -(r["delta"] if r["delta"] is not None else -999))
    return {"days": days_back, "rotation": out[:top_n]}


def scenario(idea: dict, target_momentum: int = 95, theme_beta: float = 0.30):
    """Phase ο.2 — back-of-envelope price projection if momentum hits a target.

    ``theme_beta`` = expected % stock move per +10 momentum points. The default
    0.30 (3% per +10 mom) is a reasonable starting guess; users can override.
    """
    mom_now = idea.get("trend_momentum") or 0
    price   = idea.get("price")
    if price is None:
        return {"error": "no price data — fetch the ticker first"}
    delta_mom = max(0, target_momentum - mom_now)
    purity = idea.get("purity") or 0.5
    move_pct = delta_mom * (theme_beta * (0.5 + 0.5 * purity))   # scaled by purity
    target_price = price * (1 + move_pct / 100.0)
    return {
        "ticker":         idea["ticker"],
        "price_now":      round(price, 2),
        "momentum_now":   mom_now,
        "momentum_target": target_momentum,
        "implied_move":   round(move_pct, 1),       # %
        "price_target":   round(target_price, 2),
        "assumption":     f"~{theme_beta * 100:.0f}% per +10 momentum, scaled by purity {purity:.2f}",
    }


def evaluate_signal(expr: str, payload: dict) -> dict:
    """Phase ρ — tiny DSL for custom alerts over the ideas list.

    Supported vars per row: ticker, theme, purity, score, catch_up, ret_5d,
                            ret_20d, trend_momentum, status, in_watchlist
    Supported ops: comparisons (>, <, >=, <=, ==, !=), 'and' / 'or' / 'not',
                    parentheses, numeric and string literals.

    Example: ``catch_up > 50 and purity >= 0.7 and status == 'catch_up'``

    Implementation is a sandboxed ``eval`` over a name-restricted dict — no
    builtins, no attribute access — so it stays cheap and safe.
    """
    import ast
    expr = (expr or "").strip()
    if not expr:
        return {"error": "expression required", "matches": []}

    # AST-validate first so we reject anything beyond expressions/comparisons.
    ALLOWED = (ast.Expression, ast.BoolOp, ast.UnaryOp, ast.BinOp, ast.Compare,
               ast.Name, ast.Constant, ast.Load, ast.And, ast.Or, ast.Not,
               ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
               ast.Add, ast.Sub, ast.Mult, ast.Div, ast.USub)
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        return {"error": f"syntax: {exc}", "matches": []}
    for node in ast.walk(tree):
        if not isinstance(node, ALLOWED):
            return {"error": f"disallowed: {type(node).__name__}", "matches": []}
    code = compile(tree, "<signal>", "eval")

    matches = []
    for i in payload.get("ideas") or []:
        ctx = {
            "ticker": i["ticker"], "theme": i["theme"],
            "purity": i["purity"], "score": i["score"],
            "catch_up": i.get("catch_up") or 0,
            "ret_5d":   i.get("ret_5d")   or 0,
            "ret_20d":  i.get("ret_20d")  or 0,
            "trend_momentum": i.get("trend_momentum") or 0,
            "status": i.get("status") or "",
            "in_watchlist": bool(i.get("in_watchlist")),
        }
        try:
            ok = bool(eval(code, {"__builtins__": {}}, ctx))
        except Exception:
            ok = False
        if ok:
            matches.append({"ticker": i["ticker"], "theme": i["theme"],
                            "score": i["score"], "catch_up": i.get("catch_up")})
    return {"expression": expr, "matches": matches[:50], "count": len(matches)}


def co_movement(payload: dict, top_n: int = 12, min_pairs: int = 2):
    """Phase ζ.1 — pairwise correlation of momentum series across top trends.

    Returns the top-correlated and top-anti-correlated trend pairs so the user
    can spot themes that move together (AI + quantum) or in opposition.
    """
    trends = [t for t in (payload.get("trends") or [])[:top_n]
              if t.get("spark") and len(t["spark"]) >= 8]
    if len(trends) < min_pairs:
        return {"pairs": [], "anti_pairs": []}

    def _corr(a: list[float], b: list[float]) -> float:
        n = min(len(a), len(b))
        if n < 4:
            return 0.0
        a, b = a[-n:], b[-n:]
        ma, mb = sum(a)/n, sum(b)/n
        num = sum((a[i]-ma)*(b[i]-mb) for i in range(n))
        da  = math.sqrt(sum((a[i]-ma)**2 for i in range(n)))
        dbb = math.sqrt(sum((b[i]-mb)**2 for i in range(n)))
        if da == 0 or dbb == 0:
            return 0.0
        return num / (da * dbb)

    pairs = []
    for i in range(len(trends)):
        for j in range(i+1, len(trends)):
            r = _corr(trends[i]["spark"], trends[j]["spark"])
            if abs(r) < 0.4:
                continue
            pairs.append({"a": trends[i]["term"], "b": trends[j]["term"],
                          "r": round(r, 2),
                          "theme_a": trends[i].get("category"),
                          "theme_b": trends[j].get("category")})
    pos  = sorted([p for p in pairs if p["r"] > 0], key=lambda p: -p["r"])[:8]
    neg  = sorted([p for p in pairs if p["r"] < 0], key=lambda p:  p["r"])[:5]
    return {"pairs": pos, "anti_pairs": neg}


def rolled_over(payload: dict):
    """Phase ζ.4 — terms whose phase just flipped from peaking → fading.

    A contrarian / short-side signal — peaked-and-rolling vs the secular
    'building' trends the rest of the radar surfaces.
    """
    today = datetime.now(timezone.utc).date()
    yest_iso = (today - timedelta(days=1)).isoformat()
    out = []
    for t in payload.get("trends") or []:
        if t.get("phase") != "fading":
            continue
        try:
            prior = db.get_snapshot(yest_iso, t["term"])
        except Exception:
            prior = None
        was_peaking = prior and prior.get("phase") in ("peaking", "building")
        out.append({
            "term":     t["term"],
            "momentum": t["momentum"],
            "category": t.get("category"),
            "just_flipped": bool(was_peaking),
            "delta_vs_yest": (t["momentum"] - prior["momentum"]) if prior and prior.get("momentum") is not None else None,
        })
    out.sort(key=lambda r: (not r["just_flipped"], r["momentum"]))
    return out[:10]


def relative_strength(ticker: str, sector_etf: str = "SPY"):
    """Phase δ.1 — stock's 20d return minus the sector ETF's 20d return.

    Positive RS = stock outperforming; negative = underperforming. Cheap and
    sector-agnostic; the caller picks the relevant ETF if they care to.
    """
    s = _stock_move_pair(ticker)
    if s["ret_20d"] is None:
        return {"rs_20d": None, "vs": sector_etf, "note": f"no OHLCV for {ticker}"}
    e = _stock_move_pair(sector_etf)
    if e["ret_20d"] is None:
        return {"rs_20d": None, "vs": sector_etf, "note": f"no OHLCV for {sector_etf}"}
    return {"rs_20d": round(s["ret_20d"] - e["ret_20d"], 1),
            "stock_20d": s["ret_20d"], "benchmark_20d": e["ret_20d"],
            "vs": sector_etf}


def _stock_move_pair(ticker: str):
    """Shared helper — returns 20d return + most recent close, None when absent."""
    try:
        df = db.get_ohlcv_df(ticker, "daily", limit=30)
    except Exception:
        return {"ret_20d": None, "price": None}
    if df is None or df.empty or len(df) < 21:
        return {"ret_20d": None, "price": None}
    closes = [float(c) for c in df["close"].tolist() if c and c > 0]
    if len(closes) < 21:
        return {"ret_20d": None, "price": None}
    return {"ret_20d": round((closes[-1] / closes[-21] - 1.0) * 100.0, 1),
            "price":   round(closes[-1], 2)}


def liquidity_guard(ticker: str, threshold_dollar: float = 10_000_000):
    """Phase δ.4 — flag thin names where social-driven volatility is real but
    execution can't take size. Returns avg-daily-dollar-volume (20d) + flag.
    """
    try:
        df = db.get_ohlcv_df(ticker, "daily", limit=25)
    except Exception:
        return {"adv_dollar": None, "thin": None, "note": "no data"}
    if df is None or df.empty or len(df) < 5:
        return {"adv_dollar": None, "thin": None, "note": "no data"}
    closes = [float(c) for c in df["close"].tolist()]
    vols   = [float(v) for v in df["volume"].tolist()]
    n = min(len(closes), len(vols))
    if n < 5:
        return {"adv_dollar": None, "thin": None, "note": "no data"}
    adv = sum(closes[-i-1] * vols[-i-1] for i in range(n)) / n
    return {"adv_dollar": round(adv, 0),
            "thin": adv < threshold_dollar,
            "threshold": threshold_dollar}


def edge_grade(idea: dict, rs: dict | None = None, liq: dict | None = None) -> dict:
    """Phase δ.5 — composite 'edge' read combining catch-up, phase, rel-strength,
    and liquidity. Returns a grade A/B/C/D + the reasoning bullet points."""
    score = 0
    reasons = []
    if idea.get("status") == "catch_up":
        score += 2; reasons.append("✓ trend hot, stock cold")
    if idea.get("status") == "moved":
        score -= 1; reasons.append("✗ stock already moved with trend")
    if rs and rs.get("rs_20d") is not None:
        if rs["rs_20d"] < -3:
            score += 1; reasons.append(f"✓ underperforming SPY by {-rs['rs_20d']:.1f}pp (room)")
        elif rs["rs_20d"] > 5:
            score -= 1; reasons.append(f"✗ already +{rs['rs_20d']:.1f}pp vs SPY")
    if liq and liq.get("thin"):
        score -= 1; reasons.append("⚠ thin ADV — execution risk")
    purity = idea.get("purity") or 0
    if purity >= 0.85:
        score += 1; reasons.append(f"✓ pure-play purity ({purity:.2f})")
    elif purity < 0.5:
        score -= 1; reasons.append(f"✗ low purity ({purity:.2f})")
    grade = "A" if score >= 3 else "B" if score >= 1 else "C" if score >= 0 else "D"
    return {"grade": grade, "score": score, "reasons": reasons}


def daily_digest():
    """Phase ε.1 — JSON + HTML morning digest for cron/email/webhook delivery."""
    p = st.get_social_trends(30)
    new = [t for t in (p.get("trends") or []) if t.get("new_today")][:5]
    acc = [t for t in (p.get("trends") or []) if t.get("accelerating")][:5]
    fad = [t for t in (p.get("trends") or []) if t.get("fading_fast")][:5]
    cu  = [i for i in (p.get("ideas")  or []) if i.get("status") == "catch_up"][:8]

    json_payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "new_today":      [{"term": t["term"], "momentum": t["momentum"]} for t in new],
        "accelerating":   [{"term": t["term"], "momentum": t["momentum"]} for t in acc],
        "fading_fast":    [{"term": t["term"], "momentum": t["momentum"]} for t in fad],
        "catch_up_ideas": [{"ticker": i["ticker"], "name": i["name"],
                            "theme":  i["theme"],  "catch_up": i["catch_up"]} for i in cu],
    }

    def _list(label, rows, fmt):
        if not rows: return ""
        return f"<h3>{label}</h3><ul>" + "".join(f"<li>{fmt(r)}</li>" for r in rows) + "</ul>"
    html = (
        "<div style='font:14px sans-serif;color:#e6edf3;background:#0d1117;padding:16px;'>"
        "<h2>🔥 FinDash · daily digest</h2>"
        + _list("🆕 New today",     new, lambda t: f"<b>{t['term']}</b> · momentum {t['momentum']}")
        + _list("🔥 Accelerating",  acc, lambda t: f"<b>{t['term']}</b> · momentum {t['momentum']}")
        + _list("💤 Fading fast",   fad, lambda t: f"<b>{t['term']}</b> · momentum {t['momentum']}")
        + _list("🚀 Catch-up ideas", cu, lambda i: f"<b>{i['ticker']}</b> ({i['name']}) — {i['theme']} · catch-up {i['catch_up']}")
        + "</div>"
    )
    return {"json": json_payload, "html": html}


def theme_compare(theme_a: str, theme_b: str):
    """Phase η — side-by-side cohort stats for two themes (drill-down compare)."""
    a = get_theme_cohort_stats_or_none(theme_a)
    b = get_theme_cohort_stats_or_none(theme_b)
    if not a or not b:
        return {"error": "one or both themes not found"}
    return {"a": a, "b": b}


def get_theme_cohort_stats_or_none(name):
    return st.get_theme_cohort_stats(name)


def export_idea_notebook(idea: dict) -> str:
    """Return a Jupyter-pastable Python snippet for the idea."""
    return (
        "# Auto-generated by FinDash — paste into a notebook to dig in.\n"
        f"TICKER = '{idea['ticker']}'\n"
        f"THEME  = {idea['theme']!r}\n"
        f"PURITY = {idea['purity']}\n"
        f"CATCH_UP = {idea.get('catch_up')}\n"
        f"DRIVERS = {[d['term'] for d in (idea.get('drivers') or [])[:5]]}\n"
        "\n"
        "import yfinance as yf, pandas as pd\n"
        "df = yf.Ticker(TICKER).history(period='6mo')\n"
        "df[['Close']].plot(title=f'{TICKER} · 6mo · {THEME} catch-up'+'%' )\n"
    )


# ── Phase ο · Broker deeplinks ──────────────────────────────────────────────
def trade_deeplinks(ticker: str) -> dict[str, str]:
    """Pre-filled URLs to common retail brokers — they all accept a symbol param.

    Nothing is auto-submitted; the user lands on the broker's trade ticket
    with the ticker already populated.
    """
    tk = ticker.upper()
    return {
        "robinhood": f"https://robinhood.com/stocks/{tk}",
        "schwab":    f"https://client.schwab.com/Areas/Trade/Allinone/index.aspx?symbol={tk}",
        "fidelity":  f"https://digital.fidelity.com/prgw/digital/trade-equity?symbol={tk}",
        "ibkr":      f"https://www.interactivebrokers.com/portal/?action=symbolSearch&symbol={tk}",
        "yahoo":     f"https://finance.yahoo.com/quote/{tk}",
    }


# ── Phase π · Risk overlay (earnings within N days, FOMC, etc.) ─────────────
def risk_overlay(ticker: str, lookahead_days: int = 14):
    """Pull near-term earnings / catalyst flags. yfinance.calendar is best-effort."""
    try:
        import yfinance as yf
        cal = yf.Ticker(ticker).calendar
    except Exception:
        return {"earnings_in_days": None, "flags": []}

    flags = []
    earnings_in = None
    try:
        if isinstance(cal, dict):
            d = cal.get("Earnings Date")
            if isinstance(d, list) and d:
                d = d[0]
            if hasattr(d, "date"): d = d.date()
            if d:
                today = datetime.now(timezone.utc).date()
                earnings_in = (d - today).days
                if 0 <= earnings_in <= lookahead_days:
                    flags.append(f"📅 Earnings in {earnings_in}d")
    except Exception:
        pass
    return {"earnings_in_days": earnings_in, "flags": flags}


# ── Phase λ · Institutional confirmation (scaffold) ─────────────────────────
def institutional_signal(ticker: str):
    """Best-effort 'smart money confirms' read.

    SEC EDGAR returns 403 from a lot of sandboxes; this defensive scaffold
    surfaces nothing rather than crashing when network is restricted.
    """
    try:
        import urllib.request, json as _json
        req = urllib.request.Request(
            f"https://data.sec.gov/submissions/CIK{ticker}.json",
            headers={"User-Agent": "FinDash research/0.1 (contact@example.com)"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = _json.loads(r.read())
        recent = data.get("filings", {}).get("recent", {})
        forms  = recent.get("form", []) or []
        f4s    = sum(1 for f in forms[:50] if f == "4")
        thirteen_fs = sum(1 for f in forms[:50] if f.startswith("13F"))
        confirms = f4s >= 2 or thirteen_fs >= 1
        return {"confirms": confirms,
                "form_4_count": f4s,
                "form_13f_count": thirteen_fs,
                "note": "Form 4 insider activity present" if f4s else None,
                "live": True}
    except Exception:
        return {"confirms": False, "form_4_count": 0, "form_13f_count": 0,
                "note": "SEC EDGAR unreachable", "live": False}
