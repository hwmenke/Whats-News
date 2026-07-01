"""
econ_calendar.py — US macro-economic event calendar.

Two data layers:
  1. Built-in schedule — exact FOMC dates (officially published) plus
     rule-based estimates for recurring releases (NFP first Friday, CPI
     mid-month, OPEX third Friday…). Estimated events carry approx=True.
  2. FRED connectivity — when a FRED API key is configured (Settings →
     Economic Data), actual release dates are fetched from the St. Louis
     Fed releases/dates endpoint and replace the nearby estimates.

Event shape:
  { date, type, label, category, importance (3=high 2=med 1=low),
    approx, color }
"""

import json
import logging
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta

logger = logging.getLogger(__name__)

# ── category colors (match terminal palette) ─────────────────────────────────
CATEGORY_COLORS = {
    "fed":       "#3b82f6",
    "inflation": "#f97316",
    "jobs":      "#22c55e",
    "growth":    "#06b6d4",
    "sentiment": "#8e9bb0",
    "market":    "#eab308",
    "earnings":  "#a855f7",
}

# Officially published FOMC meeting dates (decision day = second day).
FOMC_DATES = [
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18",
    "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-17",
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
    "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-16",
]


# ── date-rule helpers ─────────────────────────────────────────────────────────

def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """n-th occurrence of weekday (0=Mon … 4=Fri) in a month."""
    d = date(year, month, 1)
    offset = (weekday - d.weekday()) % 7
    return d + timedelta(days=offset + 7 * (n - 1))


def _busday_adjust(d: date) -> date:
    """Shift weekend dates to the nearest weekday (Sat→Fri, Sun→Mon)."""
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


def _nth_business_day(year: int, month: int, n: int) -> date:
    d = date(year, month, 1)
    count = 0
    while True:
        if d.weekday() < 5:
            count += 1
            if count == n:
                return d
        d += timedelta(days=1)


def _month_iter(start: date, end: date):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        m += 1
        if m > 12:
            m, y = 1, y + 1


# ── built-in schedule ─────────────────────────────────────────────────────────

def _ev(d: date, typ: str, label: str, category: str, importance: int,
        approx: bool = False) -> dict:
    return {
        "date":       d.isoformat(),
        "type":       typ,
        "label":      label,
        "category":   category,
        "importance": importance,
        "approx":     approx,
        "color":      CATEGORY_COLORS.get(category, "#8e9bb0"),
    }


def builtin_events(start: date, end: date) -> list:
    """All built-in macro events in [start, end]."""
    events = []

    # FOMC — exact published dates
    for ds in FOMC_DATES:
        d = date.fromisoformat(ds)
        if start <= d <= end:
            events.append(_ev(d, "FOMC", "FOMC Rate Decision", "fed", 3))

    gdp_cycle = {1: "Advance", 2: "Second", 3: "Third"}
    for y, m in _month_iter(start, end):
        # Jobs report — first Friday (BLS, fixed rule)
        nfp = _nth_weekday(y, m, 4, 1)
        events.append(_ev(nfp, "NFP", "Jobs Report (NFP)", "jobs", 3))

        # CPI — BLS releases mid-month; estimate ~13th business-day adjusted
        cpi = _busday_adjust(date(y, m, 13))
        events.append(_ev(cpi, "CPI", "CPI Release", "inflation", 3, approx=True))

        # PPI — typically the day after CPI
        ppi = _busday_adjust(date(y, m, 14))
        events.append(_ev(ppi, "PPI", "PPI Release", "inflation", 2, approx=True))

        # Retail Sales — mid-month
        rs = _busday_adjust(date(y, m, 16))
        events.append(_ev(rs, "RETAIL", "Retail Sales", "growth", 2, approx=True))

        # GDP — end of month, Advance/Second/Third rotating by quarter month
        est = gdp_cycle[(m - 1) % 3 + 1]
        gdp = _busday_adjust(date(y, m, 27))
        events.append(_ev(gdp, "GDP", f"GDP ({est} Estimate)", "growth",
                          3 if est == "Advance" else 2, approx=True))

        # Core PCE — Fed's preferred inflation gauge, end of month
        pce = _busday_adjust(date(y, m, 28))
        events.append(_ev(pce, "PCE", "Core PCE (Fed's gauge)", "inflation", 3, approx=True))

        # ISM Manufacturing — 1st business day
        events.append(_ev(_nth_business_day(y, m, 1), "ISM-MFG",
                          "ISM Manufacturing PMI", "growth", 2, approx=True))

        # ISM Services — 3rd business day
        events.append(_ev(_nth_business_day(y, m, 3), "ISM-SVC",
                          "ISM Services PMI", "growth", 2, approx=True))

        # JOLTS — job openings, first week
        events.append(_ev(_busday_adjust(date(y, m, 4)), "JOLTS",
                          "JOLTS Job Openings", "jobs", 1, approx=True))

        # Michigan Consumer Sentiment (final) — 4th Friday
        umich = _nth_weekday(y, m, 4, 4)
        events.append(_ev(umich, "UMICH", "Michigan Consumer Sentiment", "sentiment", 1, approx=True))

        # Monthly options expiration — 3rd Friday (exact rule)
        opex = _nth_weekday(y, m, 4, 3)
        if m in (3, 6, 9, 12):
            events.append(_ev(opex, "QUAD-WITCH", "Quad Witching OPEX", "market", 3))
        else:
            events.append(_ev(opex, "OPEX", "Monthly Options Expiration", "market", 2))

    return [e for e in events if start.isoformat() <= e["date"] <= end.isoformat()]


# ── FRED connectivity ─────────────────────────────────────────────────────────

# FRED release names → our event types (only types we can refine with FRED)
_FRED_RELEASE_MAP = {
    "Consumer Price Index":                              ("CPI",    "CPI Release",            "inflation", 3),
    "Employment Situation":                              ("NFP",    "Jobs Report (NFP)",      "jobs",      3),
    "Producer Price Index":                              ("PPI",    "PPI Release",            "inflation", 2),
    "Gross Domestic Product":                            ("GDP",    "GDP Release",            "growth",    3),
    "Personal Income and Outlays":                       ("PCE",    "Core PCE (Fed's gauge)", "inflation", 3),
    "Advance Monthly Sales for Retail and Food Services":("RETAIL", "Retail Sales",           "growth",    2),
    "Job Openings and Labor Turnover Survey":            ("JOLTS",  "JOLTS Job Openings",     "jobs",      1),
}

_fred_cache = {"key": None, "range": None, "data": None, "ts": 0}
_FRED_TTL = 6 * 3600   # 6 hours


def fetch_fred_release_dates(api_key: str, start: date, end: date) -> list:
    """Actual scheduled release dates from FRED. Returns [] on any failure."""
    cache_range = (start.isoformat(), end.isoformat())
    if (_fred_cache["data"] is not None
            and _fred_cache["key"] == api_key
            and _fred_cache["range"] == cache_range
            and time.time() - _fred_cache["ts"] < _FRED_TTL):
        return _fred_cache["data"]

    params = urllib.parse.urlencode({
        "api_key":                              api_key,
        "file_type":                            "json",
        "realtime_start":                       start.isoformat(),
        "realtime_end":                         end.isoformat(),
        "include_release_dates_with_no_data":   "true",
        "limit":                                1000,
        "sort_order":                           "asc",
    })
    url = f"https://api.stlouisfed.org/fred/releases/dates?{params}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "whats-news-dashboard"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.warning("FRED release-dates fetch failed: %s", e)
        return []

    events = []
    for rd in payload.get("release_dates", []):
        name = rd.get("release_name", "")
        ds   = rd.get("date", "")
        if name in _FRED_RELEASE_MAP and start.isoformat() <= ds <= end.isoformat():
            typ, label, cat, imp = _FRED_RELEASE_MAP[name]
            events.append(_ev(date.fromisoformat(ds), typ, label, cat, imp, approx=False))

    _fred_cache.update(key=api_key, range=cache_range, data=events, ts=time.time())
    return events


def get_events(start: date, end: date, fred_api_key: str = None) -> list:
    """Merged calendar: built-in schedule, refined by FRED when available.

    A FRED exact date supersedes the built-in estimate of the same type
    within ±5 days, so users with a key see actual release dates while
    everyone else gets the rule-based approximation.
    """
    events = builtin_events(start, end)

    fred_events = fetch_fred_release_dates(fred_api_key, start, end) if fred_api_key else []
    if fred_events:
        fred_by_type: dict = {}
        for fe in fred_events:
            fred_by_type.setdefault(fe["type"], []).append(fe["date"])

        def _superseded(e):
            if not e.get("approx"):
                return False
            dates = fred_by_type.get(e["type"])
            if not dates:
                return False
            ed = date.fromisoformat(e["date"])
            return any(abs((date.fromisoformat(fd) - ed).days) <= 5 for fd in dates)

        events = [e for e in events if not _superseded(e)] + fred_events

    events.sort(key=lambda e: (e["date"], -e["importance"]))
    return events
