"""Finviz public quote + screener fetch for the paper desk.

No API keys. No login. Parse public HTML only. Rate-limit and cache in SQLite.
Blocked / empty HTML → honest empty rows — never invent tickers or metrics.
"""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Callable
from urllib.parse import parse_qs, urlparse

from lxml import html

import database as db
import finviz_presets as presets

SOURCE = "finviz public HTML"
UA = (
    "Mozilla/5.0 (compatible; WhatsNewsDesk/1.0; "
    "+https://github.com/hwmenke/Whats-News) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
MIN_INTERVAL_SEC = 1.2
HTTP_TIMEOUT = 18
DEFAULT_TTL_SEC = 3600
DEFAULT_ENABLED = True
NEWS_CAP = 20

# Snapshot labels we surface (raw strings always kept in `fields`).
SNAPSHOT_MAP = {
    "Market Cap": "market_cap",
    "P/E": "pe",
    "EPS (ttm)": "eps_ttm",
    "Target Price": "target_price",
    "RSI (14)": "rsi_14",
    "Perf Week": "perf_week",
    "Perf Month": "perf_month",
    "Perf YTD": "perf_ytd",
    "Short Float": "short_float",
    "Rel Volume": "rel_volume",
    "Avg Volume": "avg_volume",
    "Price": "price",
    "Change %": "change_pct",
    "Change": "change_pct",
    "Sector": "sector",
    "Industry": "industry",
}

_fetch_lock = threading.Lock()
_last_fetch_mono = 0.0

FetchFn = Callable[[str], tuple[int, str]]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm(text) -> str:
    return " ".join((text or "").split())


def empty_quote(symbol: str, reason: str, **extra) -> dict:
    return {
        "symbol": presets.normalize_symbol(symbol) or (symbol or "").upper(),
        "ok": False,
        "ready": False,
        "name": "",
        "sector": "",
        "industry": "",
        "fields": {},
        "snapshot": {},
        "news": [],
        "reason": reason,
        "source": SOURCE,
        "url": presets.quote_url(symbol) if symbol else "",
        **extra,
    }


def empty_screener(preset_id: str, reason: str, **extra) -> dict:
    preset = presets.get_preset(preset_id)
    return {
        "preset": (preset or {}).get("id") or (preset_id or ""),
        "label": (preset or {}).get("label") or "",
        "ok": False,
        "ready": False,
        "rows": [],
        "count": 0,
        "reason": reason,
        "source": SOURCE,
        "filters": (preset or {}).get("filters") or [],
        "filter_docs": {
            code: presets.FILTER_DOCS.get(code, code)
            for code in ((preset or {}).get("filters") or [])
        },
        "url": presets.screener_url((preset or {}).get("filters") or []) if preset else "",
        **extra,
    }


def parse_snapshot_pairs(markup: str) -> dict:
    """Label → value from Finviz snapshot-td2 pairs. Empty dict on junk HTML."""
    if not markup or not markup.strip():
        return {}
    try:
        root = html.fromstring(markup)
    except Exception:
        return {}
    tds = root.xpath('//td[contains(@class,"snapshot-td2")]')
    pairs: dict[str, str] = {}
    for i in range(0, len(tds) - 1, 2):
        key = _norm(tds[i].text_content())
        val = _norm(tds[i + 1].text_content())
        if key and key not in pairs:
            pairs[key] = val
    return pairs


def parse_quote_html(markup: str, symbol: str = "") -> dict:
    """Parse a Finviz quote page. Missing tables → empty fields, not invented."""
    reason = ""
    if not markup or not markup.strip():
        return empty_quote(symbol, "Empty Finviz HTML")
    try:
        root = html.fromstring(markup)
    except Exception:
        return empty_quote(symbol, "Finviz HTML could not be parsed")

    fields = parse_snapshot_pairs(markup)
    if not fields:
        reason = "Finviz HTML had no snapshot table (layout change, block, or challenge)"

    name = ""
    for xp in (
        '//h2[contains(@class,"quote-header")]',
        '//div[contains(@class,"quote-header_ticker-wrapper")]//a',
        '//div[contains(@class,"quote-header")]//a[contains(@class,"tab-link")]',
    ):
        els = root.xpath(xp)
        if els:
            name = _norm(els[0].text_content())
            if name and name.upper() != presets.finviz_ticker(symbol):
                break
    if not name:
        titles = root.xpath("//title")
        if titles:
            title = _norm(titles[0].text_content())
            # "AAPL - Apple Inc Stock Price and Quote"
            if " - " in title:
                name = title.split(" - ", 1)[1]
                name = re.sub(r"\s+Stock Price.*$", "", name).strip()

    sector = fields.get("Sector") or ""
    industry = fields.get("Industry") or ""
    for a in root.xpath('//a[contains(@href,"sec_")]'):
        txt = _norm(a.text_content())
        if txt:
            sector = sector or txt
            break
    for a in root.xpath('//a[contains(@href,"ind_")]'):
        txt = _norm(a.text_content())
        if txt:
            industry = industry or txt
            break

    snapshot = {}
    for label, key in SNAPSHOT_MAP.items():
        if label in fields and key not in snapshot:
            snapshot[key] = fields[label]
    if sector:
        snapshot["sector"] = sector
    if industry:
        snapshot["industry"] = industry

    news = []
    seen = set()
    for tr in root.xpath('//table[contains(@class,"news-table")]//tr'):
        links = tr.xpath(".//a[@href]")
        if not links:
            continue
        title = _norm(links[0].text_content())
        href = (links[0].get("href") or "").strip()
        if not title or not href or href in seen:
            continue
        if href.startswith("/"):
            href = "https://finviz.com" + href
        tds = tr.xpath("./td")
        published = _norm(tds[0].text_content()) if tds else ""
        seen.add(href)
        news.append({"title": title, "url": href, "published": published})
        if len(news) >= NEWS_CAP:
            break

    ready = bool(fields) or bool(news)
    if ready and not reason:
        reason = ""
    elif not ready and not reason:
        reason = "Finviz quote page had no snapshot or news rows"

    return {
        "symbol": presets.normalize_symbol(symbol) or (symbol or "").upper(),
        "ok": ready,
        "ready": ready,
        "name": name,
        "sector": sector,
        "industry": industry,
        "fields": fields,
        "snapshot": snapshot,
        "news": news,
        "reason": reason,
        "source": SOURCE,
        "url": presets.quote_url(symbol) if symbol else "",
    }


def _ticker_from_href(href: str) -> str:
    if not href:
        return ""
    parsed = urlparse(href)
    qs = parse_qs(parsed.query or "")
    raw = (qs.get("t") or [""])[0]
    if not raw and "quote.ashx" in href:
        m = re.search(r"[?&]t=([A-Za-z0-9./-]+)", href)
        raw = m.group(1) if m else ""
    return presets.normalize_symbol(raw)


def parse_screener_html(markup: str) -> list[dict]:
    """Ticker rows from a Finviz screener table. No tickers → []."""
    if not markup or not markup.strip():
        return []
    try:
        root = html.fromstring(markup)
    except Exception:
        return []

    rows = []
    seen = set()
    anchors = root.xpath('//a[contains(@href,"quote.ashx")]')
    for a in anchors:
        href = a.get("href") or ""
        symbol = _ticker_from_href(href)
        if not symbol or symbol in seen:
            continue
        tr = a.getparent()
        while tr is not None and tr.tag != "tr":
            tr = tr.getparent()
        cells = [_norm(td.text_content()) for td in (tr.xpath("./td") if tr is not None else [])]
        company = ""
        sector = ""
        industry = ""
        market_cap = ""
        price = ""
        change = ""
        volume = ""
        pe = ""
        # Typical v=111: No, Ticker, Company, Sector, Industry, Country, MktCap, P/E, Price, Change, Volume
        if len(cells) >= 11:
            company, sector, industry = cells[2], cells[3], cells[4]
            market_cap, pe, price, change, volume = cells[6], cells[7], cells[8], cells[9], cells[10]
        elif len(cells) >= 3:
            company = cells[2] if cells[1].upper() == symbol or cells[1] == a.text_content().strip() else cells[1]
        seen.add(symbol)
        rows.append({
            "symbol": symbol,
            "company": company,
            "sector": sector,
            "industry": industry,
            "market_cap": market_cap,
            "pe": pe,
            "price": price,
            "change": change,
            "volume": volume,
        })
    return rows


def get_settings() -> dict:
    _ensure_tables()
    enabled = DEFAULT_ENABLED
    ttl = DEFAULT_TTL_SEC
    with db.connection() as conn:
        rows = conn.execute("SELECT key, value FROM finviz_meta").fetchall()
    meta = {r["key"]: r["value"] for r in rows}
    if "enabled" in meta:
        enabled = str(meta["enabled"]).strip().lower() in ("1", "true", "yes", "on")
    if "ttl_sec" in meta:
        try:
            ttl = int(float(meta["ttl_sec"]))
        except (TypeError, ValueError):
            ttl = DEFAULT_TTL_SEC
    ttl = max(60, min(86400, ttl))
    return {
        "enabled": enabled,
        "ttl_sec": ttl,
        "min_interval_sec": MIN_INTERVAL_SEC,
        "source": SOURCE,
        "note": "Public Finviz HTML only. No keys. Blocks stay empty — not invented rows.",
    }


def set_settings(*, enabled=None, ttl_sec=None) -> dict:
    _ensure_tables()
    cur = get_settings()
    if enabled is not None:
        cur["enabled"] = bool(enabled)
    if ttl_sec is not None:
        try:
            cur["ttl_sec"] = max(60, min(86400, int(float(ttl_sec))))
        except (TypeError, ValueError):
            pass
    with db.connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO finviz_meta(key, value) VALUES(?, ?)",
            ("enabled", "1" if cur["enabled"] else "0"),
        )
        conn.execute(
            "INSERT OR REPLACE INTO finviz_meta(key, value) VALUES(?, ?)",
            ("ttl_sec", str(cur["ttl_sec"])),
        )
    return get_settings()


def _ensure_tables():
    with db.connection() as conn:
        db._create_research_cache(conn)


def _cache_fresh(fetched_at: str, ttl_sec: int) -> bool:
    if not fetched_at:
        return False
    try:
        ts = datetime.fromisoformat(fetched_at)
    except ValueError:
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - ts).total_seconds()
    return 0 <= age < ttl_sec


def _http_get(url: str) -> tuple[int, str]:
    """Polite GET. Returns (status, body)."""
    global _last_fetch_mono
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.8",
        },
        method="GET",
    )
    with _fetch_lock:
        wait = MIN_INTERVAL_SEC - (time.monotonic() - _last_fetch_mono)
        if wait > 0:
            time.sleep(wait)
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
                status = int(getattr(resp, "status", 200) or 200)
                body = resp.read().decode("utf-8", errors="replace")
                _last_fetch_mono = time.monotonic()
                return status, body
        except urllib.error.HTTPError as exc:
            _last_fetch_mono = time.monotonic()
            raw = exc.read() if hasattr(exc, "read") else b""
            body = raw.decode("utf-8", errors="replace") if raw else ""
            return int(exc.code or 0), body
        except Exception as exc:
            _last_fetch_mono = time.monotonic()
            return 0, str(exc)


def _reason_for_status(status: int, rows_or_fields_empty: bool) -> str:
    if status == 403:
        return "Finviz blocked this request (HTTP 403). Empty rows — not invented."
    if status == 429:
        return "Finviz rate-limited this request (HTTP 429). Cached empty."
    if status == 0:
        return "Finviz fetch failed (network). Empty — not invented."
    if status and status >= 400:
        return f"Finviz returned HTTP {status}. Empty — not invented."
    if rows_or_fields_empty:
        return "Finviz HTML had no rows (layout change, empty screen, or challenge)."
    return ""


def get_quote(symbol: str, *, force: bool = False, fetch: FetchFn | None = None) -> dict:
    sym = presets.normalize_symbol(symbol)
    if not sym:
        return empty_quote("", "Missing symbol")
    settings = get_settings()
    if not settings["enabled"]:
        return empty_quote(sym, "Finviz fetch is disabled in Settings.")

    _ensure_tables()
    if not force:
        with db.connection() as conn:
            row = conn.execute(
                "SELECT fetched_at, http_status, reason, payload_json FROM finviz_quotes WHERE symbol = ?",
                (sym,),
            ).fetchone()
        if row and _cache_fresh(row["fetched_at"], settings["ttl_sec"]):
            try:
                payload = json.loads(row["payload_json"] or "{}")
            except json.JSONDecodeError:
                payload = None
            if isinstance(payload, dict):
                payload["from_cache"] = True
                payload["fetched_at"] = row["fetched_at"]
                payload["http_status"] = row["http_status"]
                return payload

    url = presets.quote_url(sym)
    getter = fetch or _http_get
    status, body = getter(url)
    if status == 200 and body:
        parsed = parse_quote_html(body, sym)
        parsed["http_status"] = status
        parsed["fetched_at"] = _now()
        parsed["from_cache"] = False
        if not parsed["ready"]:
            parsed["reason"] = parsed["reason"] or _reason_for_status(status, True)
    else:
        parsed = empty_quote(sym, _reason_for_status(status, True), http_status=status, fetched_at=_now())
        parsed["from_cache"] = False

    with db.connection() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO finviz_quotes
               (symbol, fetched_at, http_status, reason, payload_json)
               VALUES (?, ?, ?, ?, ?)""",
            (
                sym,
                parsed.get("fetched_at") or _now(),
                int(parsed.get("http_status") or status or 0),
                parsed.get("reason") or "",
                json.dumps(parsed),
            ),
        )
    return parsed


def get_screener(preset_id: str | None = None, *, force: bool = False, fetch: FetchFn | None = None) -> dict:
    preset = presets.get_preset(preset_id)
    if not preset:
        return empty_screener(preset_id or "", "Unknown Finviz preset. No invented rows.")

    settings = get_settings()
    if not settings["enabled"]:
        return empty_screener(preset["id"], "Finviz fetch is disabled in Settings.")

    _ensure_tables()
    if not force:
        with db.connection() as conn:
            row = conn.execute(
                "SELECT fetched_at, http_status, reason, payload_json FROM finviz_screener_cache WHERE preset_id = ?",
                (preset["id"],),
            ).fetchone()
        if row and _cache_fresh(row["fetched_at"], settings["ttl_sec"]):
            try:
                payload = json.loads(row["payload_json"] or "{}")
            except json.JSONDecodeError:
                payload = None
            if isinstance(payload, dict):
                payload["from_cache"] = True
                payload["fetched_at"] = row["fetched_at"]
                payload["http_status"] = row["http_status"]
                return payload

    url = presets.screener_url(preset["filters"])
    getter = fetch or _http_get
    status, body = getter(url)
    rows = parse_screener_html(body) if status == 200 else []
    reason = _reason_for_status(status, not rows)
    payload = {
        "preset": preset["id"],
        "label": preset["label"],
        "blurb": preset.get("blurb") or "",
        "ok": bool(rows),
        "ready": bool(rows),
        "rows": rows,
        "count": len(rows),
        "reason": reason,
        "source": SOURCE,
        "filters": preset["filters"],
        "filter_docs": {c: presets.FILTER_DOCS.get(c, c) for c in preset["filters"]},
        "url": url,
        "http_status": status,
        "fetched_at": _now(),
        "from_cache": False,
    }
    with db.connection() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO finviz_screener_cache
               (preset_id, fetched_at, http_status, reason, payload_json)
               VALUES (?, ?, ?, ?, ?)""",
            (preset["id"], payload["fetched_at"], status, reason, json.dumps(payload)),
        )
    return payload


def list_presets_payload() -> dict:
    return {
        "presets": presets.list_presets(),
        "default": presets.DEFAULT_PRESET,
        "filter_docs": presets.FILTER_DOCS,
        "settings": get_settings(),
        "note": "Named screens map to public Finviz f= codes. Hits come from Finviz HTML only.",
    }
