"""
yahoo_news.py — Yahoo Finance headlines for Whats-News.

Shared by the analysis dashboard (app.py) and the data service so Dash
and the iPhone client read the same article shape. No API keys: uses
yfinance's public Yahoo news payload (same source as the existing /news page).
"""

from __future__ import annotations

from typing import Any, Callable, Optional

import yfinance as yf

DEFAULT_PROVIDER = "Yahoo Finance"
DEFAULT_PROVIDER_URL = "https://finance.yahoo.com/"


def _url_from_content(content: dict) -> str:
    for key in ("canonicalUrl", "clickThroughUrl"):
        nested = content.get(key) or {}
        if isinstance(nested, dict):
            url = nested.get("url") or ""
            if url:
                return url
        elif isinstance(nested, str) and nested:
            return nested
    return ""


def article_from_item(item: Any, symbol: Optional[str] = None) -> dict:
    """Normalize one yfinance news item into the Whats-News article dict."""
    if not isinstance(item, dict):
        item = {}
    content = item.get("content")
    if not isinstance(content, dict):
        content = {}

    if content:
        provider = content.get("provider") or {}
        if not isinstance(provider, dict):
            provider = {}
        article = {
            "title": content.get("title") or "No title",
            "summary": content.get("summary") or content.get("description") or "",
            "url": _url_from_content(content),
            "publish_time": content.get("pubDate") or "",
            "provider": provider.get("displayName") or DEFAULT_PROVIDER,
            "provider_url": provider.get("url") or DEFAULT_PROVIDER_URL,
        }
    else:
        # Older yfinance shape (title/link at top level).
        ts = item.get("providerPublishTime")
        publish_time = ""
        if isinstance(ts, (int, float)) and ts > 0:
            from datetime import datetime, timezone

            publish_time = datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
        article = {
            "title": item.get("title") or "No title",
            "summary": item.get("summary") or "",
            "url": item.get("link") or item.get("url") or "",
            "publish_time": publish_time,
            "provider": item.get("publisher") or DEFAULT_PROVIDER,
            "provider_url": DEFAULT_PROVIDER_URL,
        }

    if symbol:
        article["symbol"] = symbol
    return article


def articles_from_news_items(
    news_items: Any,
    *,
    symbol: Optional[str] = None,
    seen_urls: Optional[set[str]] = None,
) -> list[dict]:
    """Convert a ticker.news list; optionally skip URLs already in seen_urls."""
    articles: list[dict] = []
    if not news_items:
        return articles
    for item in news_items:
        article = article_from_item(item, symbol=symbol)
        url = article.get("url") or ""
        if seen_urls is not None and url:
            if url in seen_urls:
                continue
            seen_urls.add(url)
        articles.append(article)
    return articles


def _ticker_news(symbol: str, ticker_factory: Optional[Callable[[str], Any]] = None) -> list:
    factory = ticker_factory or yf.Ticker
    ticker = factory(symbol)
    return list(ticker.news or [])


def watchlist_news(
    symbols: list[str],
    *,
    ticker_factory: Optional[Callable[[str], Any]] = None,
) -> dict:
    """Headlines across a watchlist, newest first, de-duplicated by URL."""
    if not symbols:
        return {"articles": [], "message": "No symbols in watchlist"}

    all_articles: list[dict] = []
    seen_urls: set[str] = set()
    errors: list[dict] = []

    for symbol in symbols:
        try:
            items = _ticker_news(symbol, ticker_factory)
            all_articles.extend(
                articles_from_news_items(items, symbol=symbol, seen_urls=seen_urls)
            )
        except Exception as exc:
            errors.append({"symbol": symbol, "error": str(exc)})

    all_articles.sort(key=lambda x: x.get("publish_time") or "", reverse=True)

    result: dict = {
        "articles": all_articles,
        "source": DEFAULT_PROVIDER,
        "symbol_count": len(symbols),
        "article_count": len(all_articles),
    }
    if errors:
        result["errors"] = errors
    return result


def symbol_news(
    symbol: str,
    *,
    ticker_factory: Optional[Callable[[str], Any]] = None,
) -> tuple[dict, int]:
    """Headlines for one ticker. Returns (payload, http_status)."""
    sym = (symbol or "").strip().upper()
    try:
        items = _ticker_news(sym, ticker_factory)
        if not items:
            return (
                {
                    "symbol": sym,
                    "articles": [],
                    "message": f"No news available for {sym}",
                    "source": DEFAULT_PROVIDER,
                },
                200,
            )
        articles = articles_from_news_items(items)
        return (
            {
                "symbol": sym,
                "articles": articles,
                "article_count": len(articles),
                "source": DEFAULT_PROVIDER,
            },
            200,
        )
    except Exception as exc:
        return (
            {
                "symbol": sym,
                "articles": [],
                "message": str(exc),
                "source": DEFAULT_PROVIDER,
            },
            200,
        )
