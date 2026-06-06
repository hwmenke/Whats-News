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
from datetime import datetime, timezone

import database as db


# ── Sources ────────────────────────────────────────────────────────────────
SOURCES = [
    {"id": "google",    "name": "Google Trends"},
    {"id": "tiktok",    "name": "TikTok"},
    {"id": "twitter",   "name": "Twitter / X"},
    {"id": "instagram", "name": "Instagram"},
]

# Env vars that unlock a live provider (Google needs none).
SOURCE_ENV = {
    "tiktok":    "TIKTOK_API_KEY",
    "twitter":   "TWITTER_BEARER_TOKEN",
    "instagram": "INSTAGRAM_API_KEY",
}


# ── Curated theme → ticker knowledge base ───────────────────────────────────
# purity: how concentrated the company's business is on the theme (0–1).
#   >= 0.85 Pure · >= 0.65 High · >= 0.45 Moderate · else Tangential
THEME_MAP = [
    {
        "theme": "GLP-1 / Weight Loss",
        "keywords": ["ozempic", "wegovy", "mounjaro", "zepbound", "semaglutide",
                     "tirzepatide", "glp-1", "glp1", "weight loss", "skinny jab",
                     "ozempic face"],
        "stocks": [
            {"ticker": "NVO",  "name": "Novo Nordisk",          "purity": 0.95, "note": "Maker of Ozempic & Wegovy — the defining GLP-1 name (US-listed ADR)."},
            {"ticker": "LLY",  "name": "Eli Lilly",             "purity": 0.90, "note": "Maker of Mounjaro & Zepbound; GLP-1 is the core growth engine."},
            {"ticker": "VKTX", "name": "Viking Therapeutics",   "purity": 0.85, "note": "Clinical-stage obesity-drug developer; high-beta GLP-1 pure play."},
            {"ticker": "HIMS", "name": "Hims & Hers Health",    "purity": 0.55, "note": "Telehealth platform selling compounded GLP-1 weight-loss programs."},
        ],
    },
    {
        "theme": "Artificial Intelligence",
        "keywords": ["ai", "artificial intelligence", "chatgpt", "openai", "sora",
                     "llm", "generative ai", "deepseek", "gemini", "copilot",
                     "ai girlfriend", "chatbot", "nvidia", "palantir", "soundhound"],
        "stocks": [
            {"ticker": "NVDA", "name": "NVIDIA",                "purity": 0.85, "note": "GPUs are the core hardware behind the entire AI build-out."},
            {"ticker": "AI",   "name": "C3.ai",                 "purity": 0.90, "note": "Enterprise AI software — near-pure thematic exposure."},
            {"ticker": "SOUN", "name": "SoundHound AI",         "purity": 0.85, "note": "Voice / conversational-AI pure play."},
            {"ticker": "BBAI", "name": "BigBear.ai",            "purity": 0.80, "note": "Small-cap AI analytics pure play."},
            {"ticker": "SMCI", "name": "Super Micro Computer",  "purity": 0.75, "note": "AI server / rack maker levered directly to GPU demand."},
            {"ticker": "PLTR", "name": "Palantir",              "purity": 0.70, "note": "AI-driven analytics (AIP) platform; a retail AI favorite."},
        ],
    },
    {
        "theme": "Electric Vehicles",
        "keywords": ["tesla", "cybertruck", "ev", "electric vehicle", "model 3",
                     "model y", "robotaxi"],
        "stocks": [
            {"ticker": "RIVN", "name": "Rivian Automotive",     "purity": 0.92, "note": "Pure-play EV maker."},
            {"ticker": "LCID", "name": "Lucid Group",           "purity": 0.92, "note": "Pure-play luxury EV maker."},
            {"ticker": "NIO",  "name": "NIO Inc.",              "purity": 0.88, "note": "China EV pure play."},
            {"ticker": "TSLA", "name": "Tesla",                 "purity": 0.75, "note": "Cybertruck / robotaxi headlines; the EV bellwether (also AI/robotics)."},
        ],
    },
    {
        "theme": "Meme Stocks",
        "keywords": ["roaring kitty", "gamestop", "gme", "amc", "meme stock",
                     "short squeeze", "deep value"],
        "stocks": [
            {"ticker": "GME", "name": "GameStop",               "purity": 1.00, "note": "The original meme stock; moves on Roaring Kitty / social buzz."},
            {"ticker": "AMC", "name": "AMC Entertainment",      "purity": 0.95, "note": "Core meme-stock complex."},
        ],
    },
    {
        "theme": "Crypto",
        "keywords": ["bitcoin", "btc", "crypto", "ethereum", "bitcoin etf",
                     "dogecoin", "doge", "altcoin", "crypto rally"],
        "stocks": [
            {"ticker": "MARA", "name": "MARA Holdings",         "purity": 0.95, "note": "Bitcoin-mining pure play."},
            {"ticker": "RIOT", "name": "Riot Platforms",        "purity": 0.95, "note": "Bitcoin-mining pure play."},
            {"ticker": "COIN", "name": "Coinbase",              "purity": 0.85, "note": "Largest US crypto exchange; direct crypto-volume proxy."},
            {"ticker": "MSTR", "name": "MicroStrategy",         "purity": 0.85, "note": "Leveraged Bitcoin holder / proxy."},
            {"ticker": "HOOD", "name": "Robinhood",             "purity": 0.55, "note": "Retail brokerage levered to crypto / meme trading."},
        ],
    },
    {
        "theme": "Live Events / Concerts",
        "keywords": ["eras tour", "taylor swift", "concert", "tour", "ticketmaster",
                     "live nation", "beyonce"],
        "stocks": [
            {"ticker": "LYV",  "name": "Live Nation",           "purity": 0.85, "note": "Owns Ticketmaster — direct beneficiary of tour demand."},
            {"ticker": "MSGE", "name": "MSG Entertainment",     "purity": 0.55, "note": "Live-venue exposure (The Sphere, Garden)."},
        ],
    },
    {
        "theme": "Energy Drinks",
        "keywords": ["celsius", "energy drink", "prime energy", "prime hydration",
                     "monster energy"],
        "stocks": [
            {"ticker": "CELH", "name": "Celsius Holdings",      "purity": 0.95, "note": "Viral energy-drink pure play."},
            {"ticker": "MNST", "name": "Monster Beverage",      "purity": 0.85, "note": "Energy-drink pure play."},
            {"ticker": "KDP",  "name": "Keurig Dr Pepper",      "purity": 0.40, "note": "Distributes Celsius; partial exposure."},
        ],
    },
    {
        "theme": "Viral Drinkware",
        "keywords": ["stanley cup", "stanley tumbler", "tumbler", "water bottle",
                     "hydration"],
        "stocks": [
            {"ticker": "YETI", "name": "YETI Holdings",         "purity": 0.65, "note": "Premium drinkware / cooler brand; closest listed proxy."},
            {"ticker": "SWK",  "name": "Stanley Black & Decker","purity": 0.25, "note": "Owns the Stanley brand, but it's a tiny share of revenue."},
        ],
    },
    {
        "theme": "Beauty / Skincare",
        "keywords": ["e.l.f.", "elf cosmetics", "skincare", "sephora",
                     "drunk elephant", "rare beauty", "makeup", "glow"],
        "stocks": [
            {"ticker": "ELF",  "name": "e.l.f. Beauty",         "purity": 0.90, "note": "TikTok-viral cosmetics pure play."},
            {"ticker": "ULTA", "name": "Ulta Beauty",           "purity": 0.65, "note": "Beauty specialty retailer."},
            {"ticker": "EL",   "name": "Estée Lauder",          "purity": 0.55, "note": "Prestige-beauty exposure."},
        ],
    },
    {
        "theme": "Discount E-Commerce",
        "keywords": ["temu", "shein", "haul", "dupe", "dupes", "fast fashion"],
        "stocks": [
            {"ticker": "PDD", "name": "PDD Holdings",           "purity": 0.70, "note": "Parent of Temu; direct beneficiary of haul culture."},
        ],
    },
    {
        "theme": "Quantum Computing",
        "keywords": ["quantum", "quantum computing", "qubit"],
        "stocks": [
            {"ticker": "IONQ", "name": "IonQ",                  "purity": 0.90, "note": "Quantum-computing pure play."},
            {"ticker": "RGTI", "name": "Rigetti Computing",     "purity": 0.90, "note": "Quantum-computing pure play."},
            {"ticker": "QBTS", "name": "D-Wave Quantum",        "purity": 0.90, "note": "Quantum-computing pure play."},
        ],
    },
    {
        "theme": "Nuclear / SMR / Uranium",
        "keywords": ["nuclear", "uranium", "smr", "small modular reactor",
                     "nuscale", "reactor"],
        "stocks": [
            {"ticker": "SMR",  "name": "NuScale Power",         "purity": 0.90, "note": "Small-modular-reactor pure play."},
            {"ticker": "OKLO", "name": "Oklo",                  "purity": 0.90, "note": "Advanced-nuclear pure play."},
            {"ticker": "LEU",  "name": "Centrus Energy",        "purity": 0.85, "note": "Enriched-uranium pure play."},
            {"ticker": "CCJ",  "name": "Cameco",                "purity": 0.80, "note": "Uranium-mining pure play."},
        ],
    },
    {
        "theme": "Space",
        "keywords": ["space", "spacex", "rocket", "satellite", "moon landing",
                     "starship"],
        "stocks": [
            {"ticker": "RKLB", "name": "Rocket Lab",            "purity": 0.90, "note": "Launch / space-systems pure play."},
            {"ticker": "ASTS", "name": "AST SpaceMobile",       "purity": 0.90, "note": "Satellite-to-phone pure play."},
            {"ticker": "LUNR", "name": "Intuitive Machines",    "purity": 0.85, "note": "Lunar-lander pure play."},
        ],
    },
    {
        "theme": "Sports Betting",
        "keywords": ["draftkings", "sports betting", "parlay", "fanduel", "betting"],
        "stocks": [
            {"ticker": "DKNG", "name": "DraftKings",            "purity": 0.95, "note": "Online sports-betting pure play."},
            {"ticker": "PENN", "name": "PENN Entertainment",    "purity": 0.55, "note": "ESPN Bet exposure plus casinos."},
            {"ticker": "MGM",  "name": "MGM Resorts",           "purity": 0.40, "note": "BetMGM stake plus casinos."},
        ],
    },
    {
        "theme": "Gaming / Metaverse",
        "keywords": ["roblox", "fortnite", "gaming", "video game", "metaverse"],
        "stocks": [
            {"ticker": "RBLX", "name": "Roblox",                "purity": 0.95, "note": "UGC-gaming platform pure play."},
            {"ticker": "TTWO", "name": "Take-Two Interactive",  "purity": 0.70, "note": "GTA publisher."},
            {"ticker": "EA",   "name": "Electronic Arts",       "purity": 0.65, "note": "Major game publisher."},
        ],
    },
    {
        "theme": "Athleisure / Sneakers",
        "keywords": ["hoka", "lululemon", "leggings", "on running", "sneakers",
                     "running shoes", "athleisure"],
        "stocks": [
            {"ticker": "ONON", "name": "On Holding",            "purity": 0.90, "note": "On Running shoe pure play."},
            {"ticker": "DECK", "name": "Deckers Outdoor",       "purity": 0.85, "note": "Owns HOKA & UGG; viral footwear pure play."},
            {"ticker": "LULU", "name": "Lululemon",             "purity": 0.80, "note": "Athleisure pure play."},
            {"ticker": "NKE",  "name": "Nike",                  "purity": 0.60, "note": "Athletic-apparel bellwether."},
        ],
    },
    {
        "theme": "Cannabis",
        "keywords": ["cannabis", "marijuana", "weed", "rescheduling", "420"],
        "stocks": [
            {"ticker": "TLRY", "name": "Tilray Brands",         "purity": 0.90, "note": "Cannabis pure play."},
            {"ticker": "CGC",  "name": "Canopy Growth",         "purity": 0.90, "note": "Cannabis pure play."},
            {"ticker": "CRON", "name": "Cronos Group",          "purity": 0.85, "note": "Cannabis pure play."},
        ],
    },
    {
        "theme": "Solar / Clean Energy",
        "keywords": ["solar", "solar panel", "clean energy", "rooftop solar"],
        "stocks": [
            {"ticker": "ENPH", "name": "Enphase Energy",        "purity": 0.90, "note": "Solar-microinverter pure play."},
            {"ticker": "FSLR", "name": "First Solar",           "purity": 0.85, "note": "Utility-scale solar pure play."},
            {"ticker": "RUN",  "name": "Sunrun",                "purity": 0.85, "note": "Residential-solar pure play."},
        ],
    },
    {
        "theme": "Dating Apps",
        "keywords": ["tinder", "hinge", "dating app", "bumble", "online dating"],
        "stocks": [
            {"ticker": "BMBL", "name": "Bumble",                "purity": 0.95, "note": "Dating-app pure play."},
            {"ticker": "MTCH", "name": "Match Group",           "purity": 0.90, "note": "Tinder / Hinge owner; dating pure play."},
        ],
    },
    {
        "theme": "Social Media",
        "keywords": ["tiktok ban", "tiktok", "snapchat", "reddit", "pinterest",
                     "threads", "x app"],
        "stocks": [
            {"ticker": "RDDT", "name": "Reddit",                "purity": 0.90, "note": "Social-platform pure play."},
            {"ticker": "SNAP", "name": "Snap Inc.",             "purity": 0.85, "note": "Social-media pure play."},
            {"ticker": "PINS", "name": "Pinterest",             "purity": 0.85, "note": "Visual-discovery social pure play."},
            {"ticker": "META", "name": "Meta Platforms",        "purity": 0.55, "note": "Instagram / Threads owner; a TikTok-ban beneficiary."},
        ],
    },
    {
        "theme": "Robotics",
        "keywords": ["humanoid robot", "optimus", "robot", "robotics", "automation"],
        "stocks": [
            {"ticker": "SERV", "name": "Serve Robotics",        "purity": 0.80, "note": "Sidewalk delivery-robot pure play."},
            {"ticker": "TSLA", "name": "Tesla",                 "purity": 0.40, "note": "Optimus humanoid-robot program."},
        ],
    },
    {
        "theme": "Mixed Reality",
        "keywords": ["vision pro", "apple vision", "vr", "ar", "mixed reality",
                     "headset"],
        "stocks": [
            {"ticker": "META", "name": "Meta Platforms",        "purity": 0.45, "note": "Quest / Reality Labs exposure."},
            {"ticker": "AAPL", "name": "Apple",                 "purity": 0.30, "note": "Vision Pro maker; tiny share of revenue."},
        ],
    },
    {
        "theme": "Telehealth",
        "keywords": ["telehealth", "hims", "online prescription"],
        "stocks": [
            {"ticker": "HIMS", "name": "Hims & Hers Health",    "purity": 0.85, "note": "Direct-to-consumer telehealth pure play."},
        ],
    },
]


# ── Seed dataset (used when a live provider is unavailable) ──────────────────
# shape ∈ {breakout, spike, steady, decline, volatile}
# sources = which platforms the term is seeded onto.
SEED_TRENDS = [
    {"term": "Ozempic",              "sources": ["google", "twitter", "tiktok", "instagram"], "shape": "spike"},
    {"term": "Wegovy",               "sources": ["google", "twitter"],                        "shape": "breakout"},
    {"term": "Zepbound",             "sources": ["google", "twitter"],                        "shape": "breakout"},
    {"term": "ChatGPT",              "sources": ["google", "twitter", "tiktok"],              "shape": "steady"},
    {"term": "Sora AI",              "sources": ["google", "twitter", "tiktok"],              "shape": "breakout"},
    {"term": "DeepSeek",             "sources": ["google", "twitter"],                        "shape": "spike"},
    {"term": "AI girlfriend",        "sources": ["tiktok", "twitter"],                        "shape": "volatile"},
    {"term": "Cybertruck",           "sources": ["google", "tiktok", "twitter", "instagram"], "shape": "volatile"},
    {"term": "Roaring Kitty",        "sources": ["twitter", "google"],                        "shape": "spike"},
    {"term": "GameStop GME",         "sources": ["twitter", "google"],                        "shape": "spike"},
    {"term": "Bitcoin ETF",          "sources": ["google", "twitter"],                        "shape": "breakout"},
    {"term": "Dogecoin",             "sources": ["twitter", "tiktok"],                        "shape": "volatile"},
    {"term": "Eras Tour",            "sources": ["instagram", "tiktok", "twitter", "google"], "shape": "decline"},
    {"term": "Taylor Swift",         "sources": ["instagram", "twitter", "tiktok"],           "shape": "steady"},
    {"term": "Celsius energy drink", "sources": ["tiktok", "instagram"],                      "shape": "breakout"},
    {"term": "Stanley cup tumbler",  "sources": ["tiktok", "instagram", "google"],            "shape": "spike"},
    {"term": "e.l.f. cosmetics",     "sources": ["tiktok", "instagram"],                      "shape": "steady"},
    {"term": "Temu haul",            "sources": ["tiktok", "twitter"],                        "shape": "breakout"},
    {"term": "Shein haul",           "sources": ["tiktok", "instagram"],                      "shape": "steady"},
    {"term": "quantum computing",    "sources": ["twitter", "google"],                        "shape": "breakout"},
    {"term": "small modular reactor","sources": ["twitter", "google"],                        "shape": "breakout"},
    {"term": "Rocket Lab",           "sources": ["twitter"],                                  "shape": "breakout"},
    {"term": "Reddit IPO",           "sources": ["twitter", "google"],                        "shape": "spike"},
    {"term": "DraftKings",           "sources": ["twitter", "tiktok"],                        "shape": "volatile"},
    {"term": "Roblox",               "sources": ["tiktok", "google"],                         "shape": "steady"},
    {"term": "Hoka shoes",           "sources": ["tiktok", "instagram"],                      "shape": "breakout"},
    {"term": "Lululemon dupes",      "sources": ["tiktok", "instagram"],                      "shape": "steady"},
    {"term": "uranium",              "sources": ["twitter"],                                  "shape": "breakout"},
    {"term": "humanoid robot",       "sources": ["twitter", "tiktok"],                        "shape": "breakout"},
    {"term": "weight loss",          "sources": ["google", "tiktok", "instagram"],            "shape": "steady"},
    {"term": "Nvidia",               "sources": ["twitter", "google"],                        "shape": "steady"},
    {"term": "Palantir",             "sources": ["twitter"],                                  "shape": "breakout"},
    {"term": "Vision Pro",           "sources": ["tiktok", "twitter", "google"],              "shape": "decline"},
    {"term": "cannabis rescheduling","sources": ["twitter", "google"],                        "shape": "spike"},
    {"term": "solar panels",         "sources": ["google"],                                   "shape": "decline"},
    {"term": "Hims weight loss",     "sources": ["tiktok", "twitter"],                        "shape": "breakout"},
    {"term": "SoundHound",           "sources": ["twitter"],                                  "shape": "volatile"},
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
    return [th for th in THEME_MAP
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
    """Derive momentum (0–100), 30d change %, and direction from a series."""
    n = len(series)
    if n < 4:
        return {"momentum": 0, "change_pct": 0.0, "direction": "flat", "level": 0, "peak": 0}
    head = series[: max(2, n // 4)]
    tail = series[-max(2, n // 7):]
    base   = sum(head) / len(head)
    recent = sum(tail) / len(tail)
    denom  = max(base, 5.0)
    change_pct = (recent - base) / denom * 100.0
    abs_move   = min(abs(change_pct), 300.0)
    momentum   = recent * 0.25 + (abs_move / 300.0) * 100.0 * 0.75
    momentum   = int(round(max(0.0, min(100.0, momentum))))
    direction  = "rising" if change_pct > 12 else "falling" if change_pct < -12 else "flat"
    return {
        "momentum":   momentum,
        "change_pct": round(change_pct, 1),
        "direction":  direction,
        "level":      int(round(recent)),
        "peak":       int(round(max(series))),
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


def _fetch_keyed(source_id: str, n: int):
    """TikTok / Twitter / Instagram: live when a key + integration is wired,
    otherwise seed. The live branch is a documented hook — these platforms have
    no free official trends API, so the actual call is left for the operator to
    implement against their chosen provider."""
    token = os.environ.get(SOURCE_ENV.get(source_id, ""))
    if token:
        try:
            raise NotImplementedError(
                f"No live integration wired for {source_id}; add one in "
                f"social_trends._fetch_keyed() using your provider."
            )
        except Exception as exc:
            print(f"!! social_trends: {source_id} live fetch unavailable ({exc}); using seed data")
    return _seed_for(source_id, n), False


_PROVIDERS = {
    "google":    lambda n, geo: _fetch_google(n, geo),
    "tiktok":    lambda n, geo: _fetch_keyed("tiktok", n),
    "twitter":   lambda n, geo: _fetch_keyed("twitter", n),
    "instagram": lambda n, geo: _fetch_keyed("instagram", n),
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
    """Run the source providers and build the ranked trend list (no DB access)."""
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
                                            "series_list": [], "sources": []})
            entry["series_list"].append(it["series"])
            if sid not in entry["sources"]:
                entry["sources"].append(sid)

    trends = []
    for entry in merged.values():
        series = _combine_series(entry["series_list"])
        if not series:
            continue
        analysis = _analyze_series(series)
        category, tickers = _theme_for_term(entry["term"])
        trends.append({
            "term":       entry["term"],
            "sources":    entry["sources"],
            "spark":      series,
            "category":   category,
            "tickers":    tickers,
            **analysis,
        })
    trends.sort(key=lambda t: (-t["momentum"], -abs(t["change_pct"])))
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
