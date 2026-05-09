"""
news.py - Fetch news headlines from Yahoo Finance RSS.
No extra dependencies — uses stdlib urllib + xml.etree.ElementTree.
"""

import logging
import time
import xml.etree.ElementTree as ET
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

_cache: dict[str, tuple[float, list]] = {}
CACHE_TTL = 300  # seconds

_RSS = "https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=US&lang=en-US"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; FinDash/1.0)"}


def fetch_news(symbol: str, limit: int = 20) -> list[dict]:
    sym = symbol.upper()
    now = time.time()

    if sym in _cache and now - _cache[sym][0] < CACHE_TTL:
        return _cache[sym][1][:limit]

    articles = _fetch_rss(sym)
    _cache[sym] = (now, articles)
    return articles[:limit]


def _fetch_rss(sym: str) -> list[dict]:
    try:
        req = Request(_RSS.format(symbol=sym), headers=_HEADERS)
        with urlopen(req, timeout=8) as r:
            body = r.read()
        return _parse_rss(body)
    except Exception as exc:
        logger.warning("RSS fetch failed for %s: %s", sym, exc)
        return []


def _parse_rss(body: bytes) -> list[dict]:
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return []

    articles = []
    for item in root.findall(".//item"):
        title    = _text(item, "title")
        link     = _text(item, "link")
        pub_date = _text(item, "pubDate")
        desc     = _text(item, "description")
        src_el   = item.find("source")
        source   = src_el.text.strip() if src_el is not None and src_el.text else ""

        if not title:
            continue
        articles.append({
            "title":    title[:200],
            "link":     link,
            "pub_date": pub_date,
            "source":   source,
            "summary":  (desc or "")[:300].strip(),
        })
    return articles


def _text(el, tag: str) -> str:
    child = el.find(tag)
    return child.text.strip() if child is not None and child.text else ""
