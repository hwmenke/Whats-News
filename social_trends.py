"""
social_trends.py — Social-media trend radar + pure-play stock mapper

Goal
----
Surface words/topics that have *moved a lot* across Google Trends, TikTok,
Twitter/X and Instagram over a lookback window (default 30 days), then map
those trends to the listed stocks that are the cleanest "pure plays" on each
theme.

Design
------
Each source is a pluggable *provider*. A provider returns a list of
``{"term": str, "series": [float, ...]}`` items plus a ``live`` flag:

  * Google Trends  — genuine best-effort fetch via ``pytrends`` (no API key).
  * TikTok         — env var ``TIKTOK_API_KEY``       (3rd-party/Creative Center)
  * Twitter / X    — env var ``TWITTER_BEARER_TOKEN``
  * Instagram      — env var ``INSTAGRAM_API_KEY``

When a live call is unavailable (no key, no network, rate-limited, or running
in a sandbox), the provider falls back to a curated *seed* dataset so the UI
stays fully functional and demonstrable. Every payload reports per-source
``live: true|false`` so the front-end can label seeded data honestly.

The trend → ticker mapping is a hand-curated knowledge base (``THEME_MAP``).
Each stock carries a ``purity`` score (0–1) describing how concentrated its
business is on the theme. The final idea score combines that purity with the
trend's measured momentum.
"""

import os
import re
import math
import hashlib
from datetime import datetime, timedelta, timezone

import database as db


# ── Sources ────────────────────────────────────────────────────────────────
SOURCES = [
    {"id": "google",    "name": "Google Trends"},
    {"id": "tiktok",    "name": "TikTok"},
    {"id": "twitter",   "name": "Twitter / X"},
    {"id": "reddit",    "name": "Reddit / WSB"},
    {"id": "instagram", "name": "Instagram"},
]

# Env vars that unlock a live provider (Google needs none).
SOURCE_ENV = {
    "tiktok":    "TIKTOK_API_KEY",
    "twitter":   "TWITTER_BEARER_TOKEN",
    "reddit":    "REDDIT_CLIENT_ID",      # uses CLIENT_ID + CLIENT_SECRET pair
    "instagram": "INSTAGRAM_API_KEY",
}


# ── Curated theme → ticker knowledge base ───────────────────────────────────
# purity: how concentrated the company's business is on the theme (0–1).
#   >= 0.85 Pure · >= 0.65 High · >= 0.45 Moderate · else Tangential
THEMES_PATH = os.path.join(os.path.dirname(__file__), "themes.json")
_themes_cache = {"mtime": 0.0, "data": []}


def _validate_themes(raw):
    """Schema-check a parsed themes.json blob; raise ValueError on bad data."""
    if not isinstance(raw, list) or not raw:
        raise ValueError("themes.json must be a non-empty list")
    seen_themes = set()
    for i, th in enumerate(raw):
        if not isinstance(th, dict):
            raise ValueError(f"theme #{i}: not an object")
        for key in ("theme", "keywords", "stocks"):
            if key not in th:
                raise ValueError(f"theme #{i}: missing '{key}'")
        if th["theme"] in seen_themes:
            raise ValueError(f"duplicate theme: {th['theme']}")
        seen_themes.add(th["theme"])
        if not isinstance(th["keywords"], list) or not th["keywords"]:
            raise ValueError(f"theme '{th['theme']}': keywords must be non-empty list")
        if not isinstance(th["stocks"], list) or not th["stocks"]:
            raise ValueError(f"theme '{th['theme']}': stocks must be non-empty list")
        for st in th["stocks"]:
            for sk in ("ticker", "name", "purity"):
                if sk not in st:
                    raise ValueError(f"theme '{th['theme']}': stock missing '{sk}'")
            try:
                p = float(st["purity"])
            except (TypeError, ValueError):
                raise ValueError(f"theme '{th['theme']}' ticker '{st['ticker']}': purity not numeric")
            if not (0.0 <= p <= 1.0):
                raise ValueError(f"theme '{th['theme']}' ticker '{st['ticker']}': purity out of [0,1]")
            st.setdefault("note", "")
    return raw


def load_themes(force: bool = False):
    """Hot-reload themes.json when its mtime changes; cache otherwise."""
    import json
    try:
        mtime = os.path.getmtime(THEMES_PATH)
    except OSError:
        if _themes_cache["data"]:
            return _themes_cache["data"]
        raise
    if force or mtime != _themes_cache["mtime"]:
        with open(THEMES_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
        try:
            data = _validate_themes(raw)
        except ValueError as exc:
            # Bad file — keep last good copy, log loudly.
            print(f"!! themes.json invalid ({exc}); keeping previous in-memory copy")
            if _themes_cache["data"]:
                return _themes_cache["data"]
            raise
        _themes_cache["mtime"] = mtime
        _themes_cache["data"]  = data
        print(f"++ social_trends: loaded {len(data)} themes from themes.json")
    return _themes_cache["data"]


def THEME_MAP_get():
    """Late-bound accessor — always returns the freshest themes."""
    return load_themes()


# Keep ``THEME_MAP`` available for any code that imports it directly. It's a
# module-level attribute pointing at the loaded list, refreshed on every
# request via ``_themes_matching`` / ``_match_stocks`` calling load_themes().
THEME_MAP = load_themes()


# ── Seed dataset (used when a live provider is unavailable) ──────────────────
# shape ∈ {breakout, spike, steady, decline, volatile}
# sources = which platforms the term is seeded onto.
SEED_TRENDS = [
    {"term": "Ozempic",              "sources": ["google", "twitter", "tiktok", "instagram"], "shape": "spike"},
    {"term": "Wegovy",               "sources": ["google", "twitter"],                        "shape": "breakout"},
    {"term": "Zepbound",             "sources": ["google", "twitter"],                        "shape": "breakout"},
    {"term": "ChatGPT",              "sources": ["google", "twitter", "tiktok"],              "shape": "steady"},
    {"term": "Sora AI",              "sources": ["google", "twitter", "tiktok"],              "shape": "breakout"},
    {"term": "DeepSeek",             "sources": ["google", "twitter", "reddit"],                        "shape": "spike"},
    {"term": "AI girlfriend",        "sources": ["tiktok", "twitter"],                        "shape": "volatile"},
    {"term": "Cybertruck",           "sources": ["google", "tiktok", "twitter", "instagram", "reddit"], "shape": "volatile"},
    {"term": "Roaring Kitty",        "sources": ["twitter", "google", "reddit"],                        "shape": "spike"},
    {"term": "GameStop GME",         "sources": ["twitter", "google", "reddit"],                        "shape": "spike"},
    {"term": "Bitcoin ETF",          "sources": ["google", "twitter", "reddit"],                        "shape": "breakout"},
    {"term": "Dogecoin",             "sources": ["twitter", "tiktok", "reddit"],                        "shape": "volatile"},
    {"term": "Eras Tour",            "sources": ["instagram", "tiktok", "twitter", "google"], "shape": "decline"},
    {"term": "Taylor Swift",         "sources": ["instagram", "twitter", "tiktok"],           "shape": "steady"},
    {"term": "Celsius energy drink", "sources": ["tiktok", "instagram"],                      "shape": "breakout"},
    {"term": "Stanley cup tumbler",  "sources": ["tiktok", "instagram", "google"],            "shape": "spike"},
    {"term": "e.l.f. cosmetics",     "sources": ["tiktok", "instagram"],                      "shape": "steady"},
    {"term": "Temu haul",            "sources": ["tiktok", "twitter"],                        "shape": "breakout"},
    {"term": "Shein haul",           "sources": ["tiktok", "instagram"],                      "shape": "steady"},
    {"term": "quantum computing",    "sources": ["twitter", "google", "reddit"],                        "shape": "breakout"},
    {"term": "small modular reactor","sources": ["twitter", "google", "reddit"],                        "shape": "breakout"},
    {"term": "Rocket Lab",           "sources": ["twitter", "reddit"],                                  "shape": "breakout"},
    {"term": "Reddit IPO",           "sources": ["twitter", "google", "reddit"],                        "shape": "spike"},
    {"term": "DraftKings",           "sources": ["twitter", "tiktok", "reddit"],                        "shape": "volatile"},
    {"term": "Roblox",               "sources": ["tiktok", "google", "reddit"],                         "shape": "steady"},
    {"term": "Hoka shoes",           "sources": ["tiktok", "instagram"],                      "shape": "breakout"},
    {"term": "Lululemon dupes",      "sources": ["tiktok", "instagram"],                      "shape": "steady"},
    {"term": "uranium",              "sources": ["twitter", "reddit"],                                  "shape": "breakout"},
    {"term": "humanoid robot",       "sources": ["twitter", "tiktok", "reddit"],                        "shape": "breakout"},
    {"term": "weight loss",          "sources": ["google", "tiktok", "instagram"],            "shape": "steady"},
    {"term": "Nvidia",               "sources": ["twitter", "google", "reddit"],                        "shape": "steady"},
    {"term": "Palantir",             "sources": ["twitter", "reddit"],                                  "shape": "breakout"},
    {"term": "Vision Pro",           "sources": ["tiktok", "twitter", "google"],              "shape": "decline"},
    {"term": "cannabis rescheduling","sources": ["twitter", "google"],                        "shape": "spike"},
    {"term": "solar panels",         "sources": ["google"],                                   "shape": "decline"},
    {"term": "Hims weight loss",     "sources": ["tiktok", "twitter"],                        "shape": "breakout"},
    {"term": "SoundHound",           "sources": ["twitter", "reddit"],                                  "shape": "volatile"},
    {"term": "Prime energy drink",   "sources": ["tiktok", "instagram"],                      "shape": "decline"},
]


# ── Keyword matching ─────────────────────────────────────────────────────────
def _kw_in_term(term_l: str, kw_l: str) -> bool:
    """Word-boundary-aware substring match (case-insensitive, lowercased inputs).

    Short keywords (<= 4 chars, e.g. 'ai', 'ev', 'gme') require a full word
    boundary on both sides to avoid false positives. Longer keywords need only
    a leading boundary, so 'solar panel' still matches 'solar panels'.
    """
    lead  = r"(?<![a-z0-9])"
    trail = r"(?![a-z0-9])" if len(kw_l) <= 4 else r""
    return re.search(lead + re.escape(kw_l) + trail, term_l) is not None


def _themes_matching(term: str):
    term_l = term.lower()
    return [th for th in load_themes()
            if any(_kw_in_term(term_l, kw) for kw in th["keywords"])]


def _theme_for_term(term: str):
    """Best single theme label + its top tickers, for display on a trend row."""
    matches = _themes_matching(term)
    if not matches:
        return ("—", [])
    best = max(matches, key=lambda t: max(s["purity"] for s in t["stocks"]))
    tickers = [s["ticker"] for s in sorted(best["stocks"], key=lambda s: -s["purity"])[:3]]
    return (best["theme"], tickers)


# ── Series synthesis + analysis ──────────────────────────────────────────────
def _seed_int(s: str) -> int:
    return int(hashlib.md5(s.encode("utf-8")).hexdigest()[:8], 16)


def _synth_series(seed_key: str, shape: str, n: int = 30):
    """Deterministic 0–100 interest series with a recognisable shape."""
    import random
    rnd = random.Random(_seed_int(seed_key))
    base = rnd.uniform(8, 32)
    series = []
    for i in range(n):
        f = i / (n - 1) if n > 1 else 1.0
        if shape == "breakout":
            trend = base + (95 - base) * (f ** 2.2)
        elif shape == "spike":
            peak = 0.72
            if f < peak:
                trend = base + (98 - base) * (f / peak) ** 1.8
            else:
                trend = 98 - (98 - 58) * ((f - peak) / (1 - peak)) ** 1.3
        elif shape == "decline":
            start = 70 + rnd.uniform(0, 22)
            trend = start * (1 - f) ** 1.1 + 8
        elif shape == "volatile":
            trend = base + (68 - base) * f
        else:  # steady
            trend = base + (78 - base) * f
        noise = rnd.uniform(-5, 5)
        if shape == "volatile":
            noise += 14 * math.sin(i * 1.35 + base)
        series.append(round(max(1.0, min(100.0, trend + noise)), 1))
    return series


def _combine_series(series_list):
    """Element-wise average of aligned tails (handles differing lengths)."""
    valid = [s for s in series_list if s]
    if not valid:
        return []
    length = min(len(s) for s in valid)
    if length <= 0:
        return []
    trimmed = [s[-length:] for s in valid]
    return [round(sum(col) / len(col), 1) for col in zip(*trimmed)]


def _analyze_series(series):
    """Derive momentum (0–100), 30d change %, direction, and phase from a series.

    Scoring v2:
      • Log-compressed change so 300%+ moves don't all flat-line at the ceiling.
      • Recency-weighted: last 7d count more than first half of the window.
      • Phase classification — building (rising into peak), peaking (at peak,
        flat slope), fading (off peak, declining), flat (no real move).
    """
    n = len(series)
    if n < 4:
        return {"momentum": 0, "change_pct": 0.0, "direction": "flat",
                "level": 0, "peak": 0, "phase": "flat"}

    head      = series[: max(2, n // 4)]
    tail      = series[-min(7, max(2, n // 4)):]
    prior_wk  = series[-min(14, max(4, n // 2)): -min(7, max(2, n // 4))] if n >= 8 else head
    base      = sum(head)     / len(head)
    recent    = sum(tail)     / len(tail)
    prior     = sum(prior_wk) / len(prior_wk) if prior_wk else base

    denom = max(base, 5.0)
    change_pct = (recent - base) / denom * 100.0

    # log-compressed magnitude → much better spread above ~100% change
    abs_move = abs(change_pct)
    log_norm = math.log1p(abs_move) / math.log1p(300.0)  # ≈ 0 at 0%, 1.0 at 300%+
    momentum = recent * 0.30 + min(log_norm, 1.0) * 100.0 * 0.70
    momentum = int(round(max(0.0, min(100.0, momentum))))

    direction = "rising" if change_pct > 12 else "falling" if change_pct < -12 else "flat"

    # Phase: where is the peak, and is recent ≷ prior week?
    peak_val = max(series)
    peak_idx = series.index(peak_val)
    near_peak    = peak_idx >= n - max(3, n // 6)
    slope_recent = recent - prior          # >0 still rising into peak
    if peak_val < 25 and abs(change_pct) < 15:
        phase = "flat"
    elif near_peak and slope_recent > 1.0:
        phase = "building"
    elif near_peak:
        phase = "peaking"
    elif recent < peak_val * 0.7:
        phase = "fading"
    else:
        phase = "peaking"

    return {
        "momentum":   momentum,
        "change_pct": round(change_pct, 1),
        "direction":  direction,
        "level":      int(round(recent)),
        "peak":       int(round(peak_val)),
        "phase":      phase,
    }


# ── Providers ────────────────────────────────────────────────────────────────
def _seed_for(source_id: str, n: int):
    out = []
    for s in SEED_TRENDS:
        if source_id in s["sources"]:
            out.append({
                "term":   s["term"],
                "series": _synth_series(f"{source_id}:{s['term']}", s["shape"], n),
            })
    return out


def _fetch_google(n: int, geo: str):
    """Genuine best-effort Google Trends fetch via pytrends; seed on failure."""
    try:
        from pytrends.request import TrendReq  # optional dependency
        py = TrendReq(hl="en-US", tz=360)
        trending = py.trending_searches(pn="united_states")
        terms = [str(x) for x in trending[0].tolist()][:10]
        out = []
        for i in range(0, len(terms), 5):  # Google limits payloads to 5 terms
            grp = terms[i:i + 5]
            py.build_payload(grp, timeframe="today 1-m", geo=geo)
            iot = py.interest_over_time()
            if iot is None or iot.empty:
                continue
            for kw in grp:
                if kw in iot.columns:
                    series = [float(v) for v in iot[kw].tolist()]
                    if series:
                        out.append({"term": kw, "series": series})
        if out:
            return out, True
    except Exception as exc:  # missing pkg, no network, rate-limited, sandbox…
        print(f"!! social_trends: Google live fetch unavailable ({exc}); using seed data")
    return _seed_for("google", n), False


def _fetch_twitter_live(token: str, n: int, geo: str):
    """Twitter / X v2: pull current trends and synthesize a series per term.

    The trends endpoint (``/2/trends/by/woeid``) returns a list of trending
    terms with current 24h tweet counts but no time series — the v2 endpoint
    that *would* give a series (``/2/tweets/counts/all``) is gated behind paid
    academic access. We approximate with a synthetic ramp based on volume so
    the rest of the pipeline (momentum, anomaly, matching) works unchanged.
    """
    import json, urllib.request, urllib.error
    woeid = {"US": 23424977, "GB": 23424975, "GLOBAL": 1}.get(geo.upper(), 23424977)
    url = f"https://api.twitter.com/2/trends/by/woeid/{woeid}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())
    out = []
    for it in (data.get("data") or [])[:15]:
        term  = (it.get("trend_name") or it.get("name") or "").strip()
        if not term:
            continue
        # Use tweet_count as a "magnitude" hint to choose a shape.
        vol = it.get("tweet_count") or 0
        shape = "breakout" if vol > 50000 else "spike" if vol > 10000 else "steady"
        out.append({"term": term, "series": _synth_series(f"twitter:live:{term}", shape, n)})
    return out


def _fetch_tiktok_apify(token: str, n: int):
    """TikTok via Apify Creative Center trending-hashtags actor.

    Hits an Apify dataset endpoint with a personal token; expects items shaped
    like ``{"hashtag": str, "trend_score": int}``. Series synthesised from the
    score so the pipeline downstream stays uniform.
    """
    import json, urllib.request
    actor_id = os.environ.get("APIFY_TIKTOK_ACTOR", "apify~tiktok-creative-center-trending-hashtags")
    url = f"https://api.apify.com/v2/acts/{actor_id}/run-sync-get-dataset-items?token={token}&memory=512"
    req = urllib.request.Request(url, method="POST",
                                 data=b'{"region":"US","timeframe":"WEEKLY"}',
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        items = json.loads(resp.read())
    out = []
    for it in (items or [])[:15]:
        term  = (it.get("hashtag") or it.get("term") or "").strip().lstrip("#")
        if not term:
            continue
        score = int(it.get("trend_score") or it.get("popularity") or 0)
        shape = "breakout" if score > 70 else "spike" if score > 40 else "steady"
        out.append({"term": term, "series": _synth_series(f"tiktok:live:{term}", shape, n)})
    return out


def _fetch_reddit_live(client_id: str, n: int):
    """Reddit / r/wallstreetbets ticker mention frequency via the public JSON API.

    No PRAW dependency — Reddit's `.json` endpoints are usable read-only with
    an OAuth-style token if you have one, otherwise we hit the anonymous JSON
    listing (rate-limited, sufficient for trend sampling).
    """
    import json, urllib.request, urllib.error, re as _re
    client_secret = os.environ.get("REDDIT_CLIENT_SECRET", "")
    headers = {"User-Agent": "FinDash/0.1 social-trends radar"}

    token = None
    if client_secret:
        try:
            import base64
            auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
            req = urllib.request.Request(
                "https://www.reddit.com/api/v1/access_token",
                data=b"grant_type=client_credentials",
                headers={**headers, "Authorization": f"Basic {auth}"})
            with urllib.request.urlopen(req, timeout=10) as r:
                token = json.loads(r.read()).get("access_token")
        except Exception:
            token = None

    base = "https://oauth.reddit.com" if token else "https://www.reddit.com"
    if token:
        headers["Authorization"] = f"Bearer {token}"

    titles = []
    for sub in ("wallstreetbets", "stocks", "investing"):
        try:
            req = urllib.request.Request(f"{base}/r/{sub}/hot.json?limit=50",
                                          headers=headers)
            with urllib.request.urlopen(req, timeout=12) as r:
                data = json.loads(r.read())
            titles.extend([(c["data"].get("title") or "") for c in
                            data.get("data", {}).get("children", [])])
        except Exception:
            continue

    if not titles:
        return []

    # Count ticker-like all-caps tokens (length 2–5) across all titles.
    counts: dict[str, int] = {}
    pat = _re.compile(r"\b\$?([A-Z]{2,5})\b")
    BLACKLIST = {"USA","CEO","ETF","IPO","FUD","DD","ATH","FOMO","YOLO","WSB",
                 "EOD","CPI","FED","FOMC","SEC","EDT","EST","NYSE","API","ARK"}
    for title in titles:
        for tk in pat.findall(title):
            if tk in BLACKLIST:
                continue
            counts[tk] = counts.get(tk, 0) + 1

    out = []
    for tk, cnt in sorted(counts.items(), key=lambda x: -x[1])[:15]:
        shape = "breakout" if cnt >= 8 else "spike" if cnt >= 4 else "steady"
        out.append({"term": tk, "series": _synth_series(f"reddit:live:{tk}", shape, n)})
    return out


# ── Lightweight sentiment lexicon (Phase κ.2) ───────────────────────────────
# Hand-picked finance/social vocabulary; no model dependencies.
_POS = {"moon","mooning","bullish","rally","rallied","ripping","squeeze","breakout","ath",
        "win","wins","beat","beats","crushed","record","strong","jumped","soared","gain",
        "gains","rocket","rockets","green","up","love","amazing","fire","🔥","🚀","🌙"}
_NEG = {"crash","crashed","crashing","dump","dumped","plunge","plunged","bearish","tank",
        "tanked","red","down","loss","losses","miss","missed","weak","fall","falls","fell",
        "fraud","scam","warning","drop","drops","sell","selling","short","fading","fade",
        "dying","dead"}


def sentiment_score(text: str) -> dict:
    """Crude lexicon-based sentiment.

    Returns ``{"score": -1.0..+1.0, "label": str, "pos": int, "neg": int}``.
    Good enough as a relative ranking signal; not a substitute for FinBERT.
    """
    if not text:
        return {"score": 0.0, "label": "neutral", "pos": 0, "neg": 0}
    tokens = re.findall(r"[A-Za-z🚀🌙🔥]+", text.lower())
    pos = sum(1 for t in tokens if t in _POS)
    neg = sum(1 for t in tokens if t in _NEG)
    total = pos + neg
    score = 0.0 if total == 0 else (pos - neg) / total
    label = "positive" if score > 0.2 else "negative" if score < -0.2 else "neutral"
    return {"score": round(score, 2), "label": label, "pos": pos, "neg": neg}


def _fetch_keyed(source_id: str, n: int, geo: str = "US"):
    """TikTok / Twitter / Instagram: real call when a key is set, seed otherwise.

    Twitter/X uses ``TWITTER_BEARER_TOKEN`` (v2 trends/by/woeid).
    TikTok uses ``APIFY_TOKEN`` (Apify Creative Center actor).
    Instagram has no viable trends API — seed only.
    """
    token = os.environ.get(SOURCE_ENV.get(source_id, ""))
    if token:
        try:
            if source_id == "twitter":
                items = _fetch_twitter_live(token, n, geo)
                if items:
                    return items, True
            elif source_id == "tiktok":
                items = _fetch_tiktok_apify(token, n)
                if items:
                    return items, True
            elif source_id == "reddit":
                items = _fetch_reddit_live(token, n)
                if items:
                    return items, True
            else:
                raise NotImplementedError(
                    f"No live integration wired for {source_id}; add one in "
                    f"social_trends._fetch_keyed()."
                )
        except Exception as exc:
            print(f"!! social_trends: {source_id} live fetch failed ({exc}); using seed data")
    return _seed_for(source_id, n), False


_PROVIDERS = {
    "google":    lambda n, geo: _fetch_google(n, geo),
    "tiktok":    lambda n, geo: _fetch_keyed("tiktok",    n, geo),
    "twitter":   lambda n, geo: _fetch_keyed("twitter",   n, geo),
    "reddit":    lambda n, geo: _fetch_keyed("reddit",    n, geo),
    "instagram": lambda n, geo: _fetch_keyed("instagram", n, geo),
}


# ── Stock matching ───────────────────────────────────────────────────────────
def _purity_label(p: float) -> str:
    return ("Pure"       if p >= 0.85 else
            "High"       if p >= 0.65 else
            "Moderate"   if p >= 0.45 else
            "Tangential")


def _stock_move(ticker: str):
    """N-day % return for a ticker from locally-stored OHLCV (None if no data).

    Reads only what's already in SQLite — never triggers a network fetch — so
    untracked tickers simply return Nones and are flagged 'no price data'.
    """
    try:
        df = db.get_ohlcv_df(ticker, "daily", limit=40)
    except Exception:
        return {"ret_5d": None, "ret_20d": None, "price": None}
    if df is None or df.empty or "close" not in df.columns:
        return {"ret_5d": None, "ret_20d": None, "price": None}
    closes = [float(c) for c in df["close"].tolist() if c and c > 0]
    if len(closes) < 6:
        return {"ret_5d": None, "ret_20d": None, "price": None}

    def _ret(lookback):
        if len(closes) <= lookback:
            return None
        prev = closes[-1 - lookback]
        return round((closes[-1] / prev - 1.0) * 100.0, 1) if prev > 0 else None

    return {"ret_5d": _ret(5), "ret_20d": _ret(20), "price": round(closes[-1], 2)}


def _catch_up(trend_mom: int, theme_dir: str, move: dict):
    """Combine trend heat with the stock's actual move into a 'catch-up' read.

    The edge we want: trend is hot but the stock hasn't run yet. Returns a
    catch_up score (0–100, higher = more room) plus a status flag for badging.
    """
    ret20 = move.get("ret_20d")
    if ret20 is None:
        return {"catch_up": None, "status": "no_data", "stock_heat": None}

    # Map the 20d stock move onto a 0–100 "heat" scale: +30% ≈ fully run.
    stock_heat = int(round(max(0.0, min(100.0, ret20 / 30.0 * 100.0))))
    catch_up   = int(round(max(0.0, min(100.0, trend_mom - stock_heat))))

    if theme_dir == "falling" or trend_mom < 35:
        status = "fading"            # ❄️ trend cooling — chasing is late
    elif stock_heat >= 60:
        status = "moved"             # ✅ stock already ran with the trend
    elif trend_mom >= 50 and stock_heat < 40:
        status = "catch_up"          # 🚀 trend hot, stock still cold
    else:
        status = "neutral"
    return {"catch_up": catch_up, "status": status, "stock_heat": stock_heat}


def _match_stocks(trends):
    """Map ranked trends onto pure-play tickers; dedupe by best score.

    Always runs fresh against the DB (watchlist membership + stored price
    moves) — only the upstream trend computation is cached.
    """
    watchlist = {s["symbol"] for s in db.list_symbols()}
    ideas = {}
    for th in THEME_MAP:
        matched = [t for t in trends
                   if any(_kw_in_term(t["term"].lower(), kw) for kw in th["keywords"])]
        if not matched:
            continue
        matched.sort(key=lambda t: -t["momentum"])
        theme_mom = matched[0]["momentum"]
        theme_dir = matched[0]["direction"]
        drivers = [{
            "term":       t["term"],
            "momentum":   t["momentum"],
            "change_pct": t["change_pct"],
            "direction":  t["direction"],
        } for t in matched[:4]]

        for st in th["stocks"]:
            score = round(st["purity"] * theme_mom, 1)
            prev = ideas.get(st["ticker"])
            if prev and prev["score"] >= score:
                continue
            move = _stock_move(st["ticker"])
            cu   = _catch_up(theme_mom, theme_dir, move)
            ideas[st["ticker"]] = {
                "ticker":         st["ticker"],
                "name":           st["name"],
                "theme":          th["theme"],
                "purity":         st["purity"],
                "purity_label":   _purity_label(st["purity"]),
                "note":           st["note"],
                "trend_momentum": theme_mom,
                "trend_dir":      theme_dir,
                "score":          score,
                "drivers":        drivers,
                "in_watchlist":   st["ticker"] in watchlist,
                "ret_5d":         move["ret_5d"],
                "ret_20d":        move["ret_20d"],
                "price":          move["price"],
                "catch_up":       cu["catch_up"],
                "stock_heat":     cu["stock_heat"],
                "status":         cu["status"],
            }
    return sorted(ideas.values(), key=lambda i: -i["score"])[:40]


# ── Trend computation (cached) ───────────────────────────────────────────────
# The provider sweep (esp. live pytrends) is the slow part and doesn't depend
# on DB state, so we memoise it with a short TTL keyed on the request params.
# Stock matching always runs fresh on top of the cached trends.
_CACHE_TTL_SEC = 600          # 10 minutes
_trend_cache   = {}           # key -> {"at": epoch, "trends": [...], "sources": [...]}


def _compute_trends(n: int, geo: str, wanted: set):
    """Run the source providers and build the ranked trend list (no DB access).

    Per-source series are retained so each trend can report which source is
    driving it (``driven_by``). Anomaly tagging (new / accelerating / fading
    fast) happens after this step using DB snapshots.
    """
    source_meta = []
    merged = {}
    for src in SOURCES:
        sid = src["id"]
        if sid not in wanted:
            continue
        try:
            items, live = _PROVIDERS[sid](n, geo)
        except Exception as exc:
            print(f"!! social_trends: provider {sid} crashed ({exc})")
            items, live = [], False
        source_meta.append({"id": sid, "name": src["name"], "live": live, "count": len(items)})
        for it in items:
            key = it["term"].strip().lower()
            entry = merged.setdefault(key, {"term": it["term"].strip(),
                                            "series_list": [], "sources": [],
                                            "per_source": {}})
            entry["series_list"].append(it["series"])
            entry["per_source"][sid] = it["series"]
            if sid not in entry["sources"]:
                entry["sources"].append(sid)

    trends = []
    for entry in merged.values():
        series = _combine_series(entry["series_list"])
        if not series:
            continue
        analysis = _analyze_series(series)
        category, tickers = _theme_for_term(entry["term"])

        # Driven-by: which source's own series has the highest momentum
        per_src_mom = {}
        for sid, s in entry["per_source"].items():
            if s:
                per_src_mom[sid] = _analyze_series(s)["momentum"]
        driven_by = max(per_src_mom, key=per_src_mom.get) if per_src_mom else None

        trends.append({
            "term":       entry["term"],
            "sources":    entry["sources"],
            "source_mom": per_src_mom,
            "driven_by":  driven_by,
            "spark":      series,
            "category":   category,
            "tickers":    tickers,
            **analysis,
        })
    trends.sort(key=lambda t: (-t["momentum"], -abs(t["change_pct"])))

    # ── Snapshot + anomaly tagging (DB-backed) ──────────────────────────────
    today_iso = datetime.now(timezone.utc).date().isoformat()
    yest_iso  = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
    wk_ago_iso = (datetime.now(timezone.utc).date() - timedelta(days=7)).isoformat()

    try:
        yest_terms = db.get_snapshot_terms(yest_iso)
    except Exception:
        yest_terms = set()

    for t in trends[:50]:                       # only snapshot the top movers
        try:
            db.upsert_snapshot(today_iso, t["term"], t["momentum"],
                               t["change_pct"], t["direction"], t["level"],
                               t["phase"], t["sources"])
        except Exception as exc:
            print(f"!! social_trends: snapshot upsert failed for {t['term']} ({exc})")

        t["new_today"]    = bool(yest_terms) and t["term"] not in yest_terms
        t["accelerating"] = False
        t["fading_fast"]  = False
        try:
            prior = db.get_snapshot(wk_ago_iso, t["term"])
            if prior and prior.get("momentum") is not None:
                prior_mom = int(prior["momentum"])
                delta = t["momentum"] - prior_mom
                if delta >= 20:
                    t["accelerating"] = True
                elif delta <= -20:
                    t["fading_fast"] = True
        except Exception:
            pass

    return trends, source_meta


def _cached_trends(n: int, geo: str, wanted: set, force: bool = False):
    import time
    key = (n, geo, tuple(sorted(wanted)))
    hit = _trend_cache.get(key)
    if hit and not force and (time.time() - hit["at"] < _CACHE_TTL_SEC):
        return hit["trends"], hit["sources"], True
    trends, source_meta = _compute_trends(n, geo, wanted)
    _trend_cache[key] = {"at": time.time(), "trends": trends, "sources": source_meta}
    return trends, source_meta, False


# ── Public API ───────────────────────────────────────────────────────────────
def get_social_trends(lookback_days: int = 30, geo: str = "US",
                      sources=None, force: bool = False) -> dict:
    """Aggregate movers across all sources and map them to pure-play stocks.

    The trend sweep is cached for ``_CACHE_TTL_SEC`` (pass ``force=True`` to
    bypass); stock matching is always recomputed against current DB state.
    """
    n = max(7, min(int(lookback_days), 90))
    wanted = set(sources) if sources else {s["id"] for s in SOURCES}

    trends, source_meta, cached = _cached_trends(n, geo, wanted, force=force)
    ideas = _match_stocks(trends)

    return {
        "generated_at":  datetime.now(timezone.utc).isoformat(),
        "lookback_days": n,
        "geo":           geo,
        "sources":       source_meta,
        "any_live":      any(s["live"] for s in source_meta),
        "cached":        cached,
        "trends":        trends,
        "ideas":         ideas,
    }


def get_term_history(term: str, days: int = 90):
    """Backing query for the term drill-down sparkline."""
    return db.get_term_history(term, days=days)


def get_themes_for_ticker(ticker: str):
    """Reverse view — which themes carry this ticker, and at what purity."""
    tk = (ticker or "").strip().upper()
    if not tk:
        return []
    out = []
    for th in load_themes():
        for st in th["stocks"]:
            if st["ticker"].upper() == tk:
                out.append({
                    "theme":  th["theme"],
                    "purity": st["purity"],
                    "purity_label": _purity_label(st["purity"]),
                    "note":   st.get("note", ""),
                    "keywords": list(th["keywords"]),
                })
                break
    return out


def get_theme_cohort_stats(theme_name: str):
    """Aggregate 5d/20d returns across a theme's pure plays — for drill-down.

    Uses only locally-stored OHLCV; missing tickers are reported as 'no_data'.
    """
    for th in load_themes():
        if th["theme"] == theme_name:
            members = []
            r5s, r20s = [], []
            for st in th["stocks"]:
                m = _stock_move(st["ticker"])
                members.append({
                    "ticker": st["ticker"],
                    "name":   st["name"],
                    "purity": st["purity"],
                    "purity_label": _purity_label(st["purity"]),
                    "note":   st.get("note", ""),
                    "ret_5d":  m["ret_5d"],
                    "ret_20d": m["ret_20d"],
                    "price":   m["price"],
                })
                if m["ret_5d"]  is not None: r5s.append(m["ret_5d"])
                if m["ret_20d"] is not None: r20s.append(m["ret_20d"])
            return {
                "theme":   th["theme"],
                "members": members,
                "avg_ret_5d":  round(sum(r5s)/len(r5s),  2) if r5s  else None,
                "avg_ret_20d": round(sum(r20s)/len(r20s), 2) if r20s else None,
                "coverage":    f"{len(r20s)}/{len(th['stocks'])}",
            }
    return None


# ── Price-priming background sweep (so catch-up is populated by default) ─────
_prime_status = {"running": False, "queued": 0, "done": 0, "failed": 0, "current": None}


def prime_status():
    return dict(_prime_status)


def start_prime_sweep(tickers, fetcher_fn, delay: float = 1.0):
    """Fire-and-forget background sweep — fetches OHLCV for each ticker with
    a polite delay so the source provider isn't hammered.

    ``fetcher_fn`` is injected (typically ``data_fetcher.fetch_and_store``)
    so this module doesn't take a hard dependency on the fetcher chain.
    """
    import threading, time
    if _prime_status["running"]:
        return {"started": False, "reason": "already running"}
    seen = set()
    queue = []
    for t in tickers:
        t = (t or "").strip().upper()
        if t and t not in seen:
            seen.add(t)
            queue.append(t)
    if not queue:
        return {"started": False, "reason": "no tickers"}

    _prime_status.update(running=True, queued=len(queue), done=0, failed=0, current=None)

    def _worker():
        try:
            for tk in queue:
                _prime_status["current"] = tk
                try:
                    res = fetcher_fn(tk)
                    if isinstance(res, dict) and res.get("error"):
                        _prime_status["failed"] += 1
                    else:
                        _prime_status["done"] += 1
                except Exception:
                    _prime_status["failed"] += 1
                time.sleep(delay)
        finally:
            _prime_status["current"] = None
            _prime_status["running"] = False

    threading.Thread(target=_worker, daemon=True).start()
    return {"started": True, "queued": len(queue)}
