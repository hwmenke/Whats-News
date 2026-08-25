"""
data_client.py — HTTP client for the Data Management service.

The analysis app (app.py) uses this to read watchlist/OHLCV and to request
fetches. Set DATA_SERVICE_URL (default http://127.0.0.1:8051).

For unit tests / single-process mode, set DATA_SERVICE_MODE=embedded so calls
go straight to local database.py / data_fetcher.py (no HTTP).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

import pandas as pd

DATA_SERVICE_URL = os.environ.get("DATA_SERVICE_URL", "http://127.0.0.1:8051").rstrip("/")
DATA_SERVICE_MODE = os.environ.get("DATA_SERVICE_MODE", "http").strip().lower()


def use_embedded() -> bool:
    return DATA_SERVICE_MODE in ("embedded", "local", "direct")


class DataServiceError(RuntimeError):
    def __init__(self, message: str, status: Optional[int] = None, payload: Any = None):
        super().__init__(message)
        self.status = status
        self.payload = payload


def _request(
    method: str,
    path: str,
    *,
    query: Optional[dict] = None,
    body: Any = None,
    timeout: float = 120.0,
) -> Any:
    url = f"{DATA_SERVICE_URL}{path}"
    if query:
        url = f"{url}?{urllib.parse.urlencode(query)}"

    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            if not raw:
                return None
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        payload = None
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except Exception:
            payload = None
        msg = (payload or {}).get("error") if isinstance(payload, dict) else None
        raise DataServiceError(msg or f"Data service HTTP {exc.code}", status=exc.code, payload=payload) from exc
    except urllib.error.URLError as exc:
        raise DataServiceError(
            f"Data service unreachable at {DATA_SERVICE_URL}: {exc.reason}. "
            "Start it with: python -m data_service.app"
        ) from exc


# ── Read API ─────────────────────────────────────────────────────────────────

def list_symbols() -> list[dict]:
    if use_embedded():
        import database as db
        return db.list_symbols()
    return _request("GET", "/api/symbols") or []


def list_symbol_codes() -> list[str]:
    if use_embedded():
        import database as db
        if hasattr(db, "list_symbol_codes"):
            return db.list_symbol_codes()
        return [s["symbol"] for s in db.list_symbols()]
    data = _request("GET", "/api/symbols/codes")
    if isinstance(data, dict):
        return data.get("symbols", [])
    return data or []


def get_ohlcv(symbol: str, freq: str = "daily", limit: int = 500) -> list[dict]:
    if use_embedded():
        import database as db
        return db.get_ohlcv(symbol, freq, limit)
    try:
        return _request(
            "GET",
            f"/api/ohlcv/{urllib.parse.quote(symbol.upper())}",
            query={"freq": freq, "limit": limit},
        ) or []
    except DataServiceError as exc:
        if exc.status == 404:
            return []
        raise


def get_ohlcv_df(symbol: str, freq: str = "daily", limit: int = 1000) -> pd.DataFrame:
    rows = get_ohlcv(symbol, freq, limit=limit)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df.set_index("date", inplace=True)
    df.sort_index(inplace=True)
    return df


def get_db_stats() -> dict:
    if use_embedded():
        import database as db
        if hasattr(db, "get_db_stats"):
            return db.get_db_stats()
        return {"symbol_count": len(db.list_symbols()), "mode": "embedded"}
    return _request("GET", "/api/db/stats") or {}


def health() -> dict:
    if use_embedded():
        return {"ok": True, "mode": "embedded"}
    return _request("GET", "/api/health") or {"ok": False}


# ── Write / fetch API (owned by data service) ────────────────────────────────

def add_symbol(symbol: str) -> dict:
    if use_embedded():
        import database as db
        added = db.add_symbol(symbol)
        return {"message": f"{symbol.upper()} added" if added else f"{symbol.upper()} already in watchlist",
                "added": added}
    return _request("POST", "/api/symbols", body={"symbol": symbol})


def add_symbols(symbols: list[str]) -> dict:
    if use_embedded():
        import database as db
        if hasattr(db, "add_symbols"):
            return db.add_symbols(symbols)
        added, skipped = [], []
        for s in symbols:
            if db.add_symbol(s):
                added.append(s.upper())
            else:
                skipped.append(s.upper())
        return {"added": added, "skipped": skipped}
    return _request("POST", "/api/symbols", body={"symbols": symbols})


def remove_symbol(symbol: str) -> dict:
    if use_embedded():
        import database as db
        db.remove_symbol(symbol)
        return {"message": f"{symbol.upper()} removed"}
    return _request("DELETE", f"/api/symbols/{urllib.parse.quote(symbol.upper())}")


def set_symbol_group(symbol: str, group_tag: str) -> dict:
    if use_embedded():
        import database as db
        db.set_symbol_group(symbol, group_tag)
        return {"message": "ok"}
    return _request(
        "PUT",
        f"/api/symbols/{urllib.parse.quote(symbol.upper())}/group",
        body={"group_tag": group_tag},
    )


def is_recently_fetched(symbol: str, hours: int = 23) -> bool:
    if use_embedded():
        import database as db
        return db.is_recently_fetched(symbol, hours)
    data = _request(
        "GET",
        f"/api/symbols/{urllib.parse.quote(symbol.upper())}/fresh",
        query={"hours": hours},
    ) or {}
    return bool(data.get("fresh"))


def fetch_symbol(symbol: str) -> dict:
    if use_embedded():
        import data_fetcher as fetcher
        return fetcher.fetch_and_store(symbol.upper())
    return _request("POST", f"/api/fetch/{urllib.parse.quote(symbol.upper())}", timeout=180.0)


def refresh_all(overlap_days: int = 3) -> list:
    if use_embedded():
        import data_fetcher as fetcher
        results = []
        for s in list_symbol_codes():
            try:
                results.append(fetcher.fetch_and_store(s, overlap_days=overlap_days))
            except Exception as exc:
                results.append({"symbol": s, "error": str(exc)})
        return results
    return _request("POST", "/api/refresh", timeout=600.0) or []


def list_desk_symbols() -> list[dict]:
    if use_embedded():
        import database as db
        return db.list_desk_symbols()
    data = _request("GET", "/api/symbols", query={"desk": "1"})
    return data or []


def list_symbols_with_ohlcv(freq: str = "daily", min_bars: int = 30) -> list[str]:
    if use_embedded():
        import database as db
        return db.list_symbols_with_ohlcv(freq, min_bars)
    data = _request(
        "GET",
        "/api/symbols/with-data",
        query={"freq": freq, "min_bars": min_bars},
    )
    if isinstance(data, dict):
        return data.get("symbols", [])
    return data or []


def promote_to_desk(symbol: str) -> dict:
    if use_embedded():
        import database as db
        ok = db.promote_to_desk(symbol)
        return {"symbol": symbol.upper(), "promoted": ok}
    return _request("POST", f"/api/symbols/{urllib.parse.quote(symbol.upper())}/promote")


# ── Precomputed metrics cache ────────────────────────────────────────────────

def upsert_symbol_metrics(rows: list) -> int:
    if use_embedded():
        import database as db
        return db.upsert_symbol_metrics(rows)
    data = _request("POST", "/api/metrics/upsert", body={"rows": rows}, timeout=300.0) or {}
    return int(data.get("written") or 0)


def get_symbol_metrics(symbol: str) -> Optional[dict]:
    if use_embedded():
        import database as db
        return db.get_symbol_metrics(symbol)
    return _request("GET", f"/api/metrics/{urllib.parse.quote(symbol.upper())}")


def get_symbol_metrics_many(symbols: Optional[list] = None, ready_only: bool = True) -> list:
    if use_embedded():
        import database as db
        return db.get_symbol_metrics_many(symbols, ready_only=ready_only)
    body = {"ready_only": ready_only}
    if symbols is not None:
        body["symbols"] = list(symbols)
    data = _request("POST", "/api/metrics/query", body=body, timeout=120.0) or {}
    return data.get("rows") or []


def metrics_status() -> dict:
    if use_embedded():
        import database as db
        return db.metrics_status()
    return _request("GET", "/api/metrics/status") or {}


def get_max_ohlcv_date(freq: str = "daily"):
    if use_embedded():
        import database as db
        return db.get_max_ohlcv_date(freq)
    data = _request("GET", "/api/ohlcv/max-date", query={"freq": freq}) or {}
    return data.get("date")
