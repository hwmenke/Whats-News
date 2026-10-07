"""
news_service.py - Yahoo Finance headlines with caching, backoff, and an RSS fallback.

- Thread-safe per-symbol TTL cache shared by /api/news and /api/news/<symbol>
- Concurrent per-symbol fetch (ThreadPoolExecutor) with a short inter-request gap
- yfinance first; if that stream is empty or rate-limited, Yahoo's public headline RSS
- Cross-symbol dedupe (URL, else normalized title) with a `symbols` array
- Event tags are simple headline regex heuristics (not AI / not sentiment)
"""

import copy
import datetime
import email.utils
import html
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

import yfinance as yf

SOURCE = "Yahoo Finance"
DEFAULT_PROVIDER_URL = "https://finance.yahoo.com/"
FEED_YFINANCE = "yfinance"
FEED_YAHOO_RSS = "yahoo_rss"
RSS_URL = "https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=US&lang=en-US"
USER_AGENT = "Mozilla/5.0 (compatible; Whats-News/1.0)"

CACHE_TTL_SEC = int(os.environ.get("NEWS_CACHE_TTL_SEC", "360"))
MAX_WORKERS = 8
_CACHE_MAX_ENTRIES = 512
# Extra waits after a throttle before the next try. Tests set this to ().
DEFAULT_RETRY_DELAYS = (0.6, 1.5)
RETRY_DELAYS = DEFAULT_RETRY_DELAYS
MIN_INTERVAL_SEC = float(os.environ.get("NEWS_MIN_INTERVAL_SEC", "0.35"))

# Mirrors data_fetcher._THROTTLE_MARKERS; kept local so the news path does not
# import the database layer.
_THROTTLE_MARKERS = (
    "too many requests",
    "429",
    "rate limit",
    "ratelimit",
    "yfratelimit",
    "temporarily blocked",
)

# Headline heuristics only: matched against the title, in this display order.
# These flag likely event types; they do not read article bodies.
_TAG_PATTERNS = (
    ("earnings", re.compile(
        r"\bearnings\b|\beps\b|\bq[1-4]\b.*\b(results|revenue|profit|sales)\b"
        r"|\b(first|second|third|fourth)[- ]quarter\b.*\b(results|revenue|profit|sales)\b"
        r"|\bquarterly (results|profit|revenue)\b",
        re.I)),
    ("upgrade", re.compile(r"\bupgrad(e|es|ed|ing)\b", re.I)),
    ("downgrade", re.compile(r"\bdowngrad(e|es|ed|ing)\b", re.I)),
    ("mna", re.compile(
        r"\bmerger\b|\bmerg(e|es|ed|ing) with\b|\bacquir(e|es|ed|ing)\b|\bacquisition\b"
        r"|\btakeover\b|\bbuyout\b|\btake[- ]private\b",
        re.I)),
    ("guidance", re.compile(r"\bguidance\b|\boutlook\b|\bforecast(s)?\b", re.I)),
    ("offering", re.compile(
        r"\boffering\b|\bconvertible (senior )?notes\b|\bat-the-market\b|\bshare sale\b|\bstock sale\b",
        re.I)),
    ("fda", re.compile(r"\bfda\b|food and drug administration|\bpdufa\b|\bclinical hold\b", re.I)),
)

_cache = {}
_cache_lock = threading.Lock()
_pace_lock = threading.Lock()
_next_fetch_at = 0.0


class NewsFetchError(Exception):
    """A symbol fetch failed. `.payload` is the API error dict."""

    def __init__(self, payload):
        super().__init__(payload.get("error") or "Fetch failed")
        self.payload = payload


def classify_yahoo_error(exc) -> dict:
    """Map a Yahoo/yfinance failure into a stable error payload."""
    text = str(exc or "")
    name = type(exc).__name__ if exc is not None else ""
    blob = f"{name} {text}".lower()
    if any(marker in blob for marker in _THROTTLE_MARKERS):
        return {
            "error": "Yahoo is rate-limiting news requests. Try again in a minute.",
            "code": "yahoo_throttle",
            "retry_after_sec": 60,
        }
    return {"error": text or "Fetch failed", "code": "fetch_failed"}


def tag_headline(title: str) -> list:
    """Return event tags inferred from headline keywords."""
    title = title or ""
    return [tag for tag, pattern in _TAG_PATTERNS if pattern.search(title)]


def _normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()


def _extract_thumbnail(content: dict) -> str:
    thumb = content.get("thumbnail")
    if not isinstance(thumb, dict):
        return ""
    resolutions = [r for r in (thumb.get("resolutions") or []) if isinstance(r, dict) and r.get("url")]
    if resolutions:
        sized = [r for r in resolutions if (r.get("width") or 0) >= 100]
        pool = sized or resolutions
        return min(pool, key=lambda r: r.get("width") or 0)["url"]
    return thumb.get("originalUrl") or ""


def _parse_item(item: dict, symbol: str):
    content = item.get("content") or {}
    url = ((content.get("canonicalUrl") or {}).get("url")
           or (content.get("clickThroughUrl") or {}).get("url") or "")
    provider = content.get("provider") or {}
    title = content.get("title", "No title")
    article = {
        "symbol": symbol,
        "symbols": [symbol],
        "title": title,
        "summary": content.get("summary") or content.get("description", ""),
        "url": url,
        "publish_time": content.get("pubDate", ""),
        "provider": provider.get("displayName", SOURCE),
        "provider_url": provider.get("url", DEFAULT_PROVIDER_URL),
        "tags": tag_headline(title),
        "feed": FEED_YFINANCE,
    }
    thumbnail = _extract_thumbnail(content)
    if thumbnail:
        article["thumbnail"] = thumbnail
    return article


def _pace():
    """Keep a small gap between outbound Yahoo calls so a watchlist doesn't stampede."""
    global _next_fetch_at
    gap = MIN_INTERVAL_SEC
    if gap <= 0:
        return
    with _pace_lock:
        now = time.monotonic()
        wait = _next_fetch_at - now
        if wait > 0:
            time.sleep(wait)
            now = time.monotonic()
        _next_fetch_at = now + gap


def _retry(fn):
    """Call fn(); on a Yahoo throttle, wait and try again. Other errors fail immediately."""
    delays = (0.0,) + tuple(RETRY_DELAYS)
    last = None
    for i, delay in enumerate(delays):
        if delay:
            time.sleep(delay)
        try:
            return fn()
        except NewsFetchError:
            raise
        except Exception as exc:
            payload = classify_yahoo_error(exc)
            last = NewsFetchError(payload)
            if payload.get("code") != "yahoo_throttle" or i == len(delays) - 1:
                raise last from exc
    raise last


def _fetch_yfinance(symbol: str) -> list:
    _pace()
    news_items = yf.Ticker(symbol).news or []
    return [_parse_item(item, symbol) for item in news_items]


def _parse_rss_feed(body: bytes, symbol: str) -> list:
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise NewsFetchError({"error": "Yahoo RSS response was not valid XML", "code": "fetch_failed"}) from exc
    articles = []
    for item in root.findall("./channel/item"):
        title = (item.findtext("title") or "No title").strip()
        link = (item.findtext("link") or "").strip()
        raw_summary = item.findtext("description") or ""
        summary = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", raw_summary))).strip()
        pub = (item.findtext("pubDate") or "").strip()
        publish_time = pub
        if pub:
            parsed = email.utils.parsedate_to_datetime(pub)
            if parsed is not None:
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=datetime.timezone.utc)
                publish_time = parsed.astimezone(datetime.timezone.utc).isoformat(timespec="seconds")
        articles.append({
            "symbol": symbol,
            "symbols": [symbol],
            "title": title,
            "summary": summary,
            "url": link,
            "publish_time": publish_time,
            "provider": SOURCE,
            "provider_url": DEFAULT_PROVIDER_URL,
            "tags": tag_headline(title),
            "feed": FEED_YAHOO_RSS,
        })
    return articles


def _fetch_yahoo_rss(symbol: str) -> list:
    """Public Yahoo Finance headline RSS for one symbol. Real stories, no placeholders."""
    _pace()
    url = RSS_URL.format(symbol=urllib.parse.quote(symbol))
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml"})
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            status = getattr(resp, "status", 200) or 200
            body = resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise RuntimeError("429 Too Many Requests") from exc
        raise
    if status == 429:
        raise RuntimeError("429 Too Many Requests")
    return _parse_rss_feed(body, symbol)


def _fetch_symbol_uncached(symbol: str):
    """Return (articles, feed). Prefer yfinance; fall back to Yahoo RSS."""
    yf_failure = None
    articles = []
    try:
        articles = _retry(lambda: _fetch_yfinance(symbol))
    except NewsFetchError as exc:
        yf_failure = exc
    if articles:
        return articles, FEED_YFINANCE

    rss_articles = []
    rss_failure = None
    try:
        rss_articles = _retry(lambda: _fetch_yahoo_rss(symbol))
    except NewsFetchError as exc:
        rss_failure = exc
    if rss_articles:
        return rss_articles, FEED_YAHOO_RSS
    if yf_failure:
        raise yf_failure
    if rss_failure:
        raise rss_failure
    return [], FEED_YFINANCE


def now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def clear_cache():
    with _cache_lock:
        _cache.clear()


def _cache_get(symbol: str, now: float):
    with _cache_lock:
        entry = _cache.get(symbol)
        if entry and now - entry["stored_at"] < CACHE_TTL_SEC:
            return entry
        return None


def _cache_put(symbol: str, articles: list, now: float, fetched_at: str, feed: str):
    with _cache_lock:
        if len(_cache) >= _CACHE_MAX_ENTRIES:
            for key in [k for k, v in _cache.items() if now - v["stored_at"] >= CACHE_TTL_SEC]:
                del _cache[key]
            while len(_cache) >= _CACHE_MAX_ENTRIES:
                del _cache[min(_cache, key=lambda k: _cache[k]["stored_at"])]
        _cache[symbol] = {
            "stored_at": now,
            "fetched_at": fetched_at,
            "articles": articles,
            "feed": feed,
        }


def _load_symbol(symbol: str, refresh: bool, now: float) -> dict:
    """Return {symbol, articles, feed, cached, age, fetched_at} or {symbol, failure}."""
    if not refresh:
        entry = _cache_get(symbol, now)
        if entry:
            return {
                "symbol": symbol,
                "articles": entry["articles"],
                "feed": entry.get("feed") or FEED_YFINANCE,
                "cached": True,
                "age": now - entry["stored_at"],
                "fetched_at": entry["fetched_at"],
            }
    try:
        articles, feed = _fetch_symbol_uncached(symbol)
    except NewsFetchError as exc:
        return {"symbol": symbol, "failure": exc.payload}
    except Exception as exc:
        return {"symbol": symbol, "failure": classify_yahoo_error(exc)}
    fetched_at = now_iso()
    _cache_put(symbol, articles, now, fetched_at, feed)
    return {
        "symbol": symbol,
        "articles": articles,
        "feed": feed,
        "cached": False,
        "age": 0.0,
        "fetched_at": fetched_at,
    }


def merge_articles(per_symbol: list) -> list:
    """Merge per-symbol article lists into unique articles, newest first.

    Duplicates are matched by URL, or by normalized title when URL is missing.
    The first symbol seen stays as `symbol`; all appear in `symbols`.
    """
    merged = []
    by_key = {}
    for articles in per_symbol:
        for source in articles:
            key = source["url"] or ("title:" + _normalize_title(source["title"]))
            existing = by_key.get(key)
            if existing is None:
                article = copy.deepcopy(source)
                by_key[key] = article
                merged.append(article)
                continue
            for sym in source["symbols"]:
                if sym not in existing["symbols"]:
                    existing["symbols"].append(sym)
            for tag in source["tags"]:
                if tag not in existing["tags"]:
                    existing["tags"].append(tag)
            if "thumbnail" not in existing and source.get("thumbnail"):
                existing["thumbnail"] = source["thumbnail"]
    merged.sort(key=lambda a: a.get("publish_time", ""), reverse=True)
    return merged


def fetch_news(symbols: list, refresh: bool = False, now: float = None) -> dict:
    """Fetch (or serve from cache) merged news for symbols.

    Returns articles, errors (list of {symbol, error, code, ...}), cached
    (True only if every symbol came from cache), cache_age_sec (oldest hit),
    cache_hits and fetched_at (oldest data timestamp used).
    """
    now = time.monotonic() if now is None else now
    symbols = list(dict.fromkeys(symbols))

    if len(symbols) <= 1:
        loaded = [_load_symbol(s, refresh, now) for s in symbols]
    else:
        with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(symbols))) as pool:
            loaded = list(pool.map(lambda s: _load_symbol(s, refresh, now), symbols))

    errors = []
    ok = []
    for res in loaded:
        if "failure" in res:
            errors.append({"symbol": res["symbol"], **res["failure"]})
        else:
            ok.append(res)

    hits = [r for r in ok if r["cached"]]
    fetched_times = [r["fetched_at"] for r in ok]
    feeds = []
    for res in ok:
        feed = res.get("feed")
        if feed and feed not in feeds:
            feeds.append(feed)
    return {
        "articles": merge_articles([r["articles"] for r in ok]),
        "errors": errors,
        "feeds": feeds,
        "cached": bool(ok) and len(hits) == len(ok),
        "cache_hits": len(hits),
        "cache_age_sec": round(max((r["age"] for r in hits), default=0.0)),
        "fetched_at": min(fetched_times) if fetched_times else now_iso(),
    }
