"""Alpaca PAPER read-only sync — not live P&L, no orders.

Env (never commit keys):
  APCA_API_KEY_ID
  APCA_API_SECRET_KEY
  APCA_API_BASE_URL  default https://paper-api.alpaca.markets

This module only GETs account / positions (optional history / activities).
POST/PATCH/DELETE, orders, and close-position helpers are refused in code.
Live host api.alpaca.markets is refused — paper=true is hard-coded.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from urllib.parse import urlparse

import paper_book as pb

NOTE = "Alpaca paper — not live P&L. Marks still come from stored Yahoo closes."
PAPER_BASE = "https://paper-api.alpaca.markets"
PAPER_HOST = "paper-api.alpaca.markets"
LIVE_HOST = "api.alpaca.markets"
SOURCE = "alpaca_paper"
ALLOWED_GET = frozenset({
    "/v2/account",
    "/v2/positions",
    "/v2/account/portfolio/history",
    "/v2/account/activities",
})
TIMEOUT = 20


class AlpacaDenied(Exception):
    """Raised when a write / order / live URL is refused."""


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def credentials() -> tuple[str, str]:
    return _env("APCA_API_KEY_ID"), _env("APCA_API_SECRET_KEY")


def configured() -> bool:
    key, secret = credentials()
    return bool(key and secret)


def resolve_base_url(raw: str | None = None) -> str:
    url = (raw if raw is not None else _env("APCA_API_BASE_URL") or PAPER_BASE).strip()
    if not url:
        url = PAPER_BASE
    if "://" not in url:
        url = "https://" + url
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host == LIVE_HOST:
        raise AlpacaDenied(
            "Live Alpaca URL (api.alpaca.markets) refused. "
            "Paper sync is hard-coded to paper-api.alpaca.markets."
        )
    if host != PAPER_HOST:
        raise AlpacaDenied(
            f"Refusing Alpaca host {host or url!r}. "
            "Only paper-api.alpaca.markets is allowed on this path."
        )
    return f"{parsed.scheme or 'https'}://{PAPER_HOST}"


def _normalize_path(path: str) -> str:
    p = (path or "").strip()
    if not p.startswith("/"):
        p = "/" + p
    return p.split("?")[0].rstrip("/") or "/"


def assert_read_only(method: str, path: str) -> str:
    """Refuse anything that is not an allow-listed GET."""
    verb = (method or "").upper()
    norm = _normalize_path(path)
    if verb != "GET":
        raise AlpacaDenied(f"{verb} {norm} refused — Alpaca paper is read-only (no orders).")
    low = norm.lower()
    if "/orders" in low or "/close" in low:
        raise AlpacaDenied(f"GET {norm} refused — orders / close-position are denied.")
    if norm in ALLOWED_GET or norm == "/v2/positions":
        return norm
    if norm.startswith("/v2/positions/"):
        return norm
    if norm.startswith("/v2/account/activities"):
        return norm
    if norm.startswith("/v2/account/portfolio/history"):
        return norm
    raise AlpacaDenied(f"GET {norm} not on the paper allow-list.")


def _http_get(url: str, headers: dict) -> tuple[int, str]:
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return int(getattr(resp, "status", 200) or 200), resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raw = exc.read() if hasattr(exc, "read") else b""
        return int(exc.code or 0), raw.decode("utf-8", errors="replace") if raw else str(exc)
    except Exception as exc:
        return 0, str(exc)


def alpaca_get(path: str, *, fetch=None, params: dict | None = None) -> tuple[int, object]:
    """GET an allow-listed Alpaca paper path. Never sends keys in the return body."""
    norm = assert_read_only("GET", path)
    key, secret = credentials()
    if not key or not secret:
        raise AlpacaDenied("Missing APCA_API_KEY_ID / APCA_API_SECRET_KEY. Env only.")
    base = resolve_base_url()
    qs = ""
    if params:
        from urllib.parse import urlencode
        qs = "?" + urlencode(params)
    url = f"{base}{norm}{qs}"
    headers = {
        "APCA-API-KEY-ID": key,
        "APCA-API-SECRET-KEY": secret,
        "Accept": "application/json",
    }
    getter = fetch or _http_get
    status, body = getter(url, headers)
    payload: object = body
    if body:
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = body
    return status, payload


def status() -> dict:
    key, secret = credentials()
    live_refused = False
    base = PAPER_BASE
    reason = ""
    try:
        base = resolve_base_url()
    except AlpacaDenied as exc:
        live_refused = LIVE_HOST in str(exc) or "Live Alpaca" in str(exc)
        reason = str(exc)
        base = PAPER_BASE
    return {
        "configured": bool(key and secret),
        "has_key_id": bool(key),
        "has_secret": bool(secret),
        "paper": True,
        "base_url": base,
        "live_refused": live_refused,
        "source": SOURCE,
        "note": NOTE,
        "reason": reason or (
            "" if (key and secret) else
            "Missing APCA_API_KEY_ID / APCA_API_SECRET_KEY. Env only — Alpaca paper, not live P&L."
        ),
    }


def parse_positions(payload) -> list[dict]:
    """Map Alpaca GET /v2/positions into paper_book rows. No invented qty."""
    rows = payload if isinstance(payload, list) else []
    out = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        qty = item.get("qty")
        side = item.get("side") or ""
        avg = item.get("avg_entry_price") or item.get("avg_entry_price")
        if avg is None:
            avg = item.get("cost_basis")
        signed, side_n = pb._signed_qty(qty, side)
        if signed is None or signed == 0:
            continue
        out.append({
            "symbol": symbol,
            "qty": signed,
            "side": side_n,
            "avg_cost": pb._finite(avg),
            "note": str(item.get("asset_class") or "").strip(),
            "source": SOURCE,
        })
    return out


def _account_public(payload) -> dict:
    if not isinstance(payload, dict):
        return {}
    acct = str(payload.get("account_number") or "")
    tail = acct[-4:] if len(acct) >= 4 else ""
    return {
        "status": payload.get("status") or "",
        "account_tail": tail,
        "currency": payload.get("currency") or "USD",
        "cash": pb._finite(payload.get("cash")),
        "buying_power": pb._finite(payload.get("buying_power")),
        "equity": pb._finite(payload.get("equity")),
        "equity_note": "Alpaca paper equity (broker snapshot) — not Whats-News Yahoo P&L",
    }


def empty_sync(reason: str, **extra) -> dict:
    return {
        "ok": False,
        "paper": True,
        "source": SOURCE,
        "imported": 0,
        "positions": [],
        "account": {},
        "note": NOTE,
        "reason": reason,
        **extra,
    }


def sync(*, fetch=None, replace: bool = True) -> dict:
    """Pull paper positions. Replaces only alpaca_paper rows. paper=True hard-coded."""
    st = status()
    if st.get("live_refused"):
        extra = {k: v for k, v in st.items() if k != "reason"}
        return empty_sync(st.get("reason") or "Live Alpaca URL refused.", **extra)
    if not st["configured"]:
        extra = {k: v for k, v in st.items() if k != "reason"}
        return empty_sync(st.get("reason") or "Missing Alpaca paper keys.", **extra)
    try:
        resolve_base_url()
    except AlpacaDenied as exc:
        return empty_sync(str(exc), paper=True, live_refused=True)

    try:
        acct_status, acct_body = alpaca_get("/v2/account", fetch=fetch)
        pos_status, pos_body = alpaca_get("/v2/positions", fetch=fetch)
    except AlpacaDenied as exc:
        return empty_sync(str(exc), paper=True)

    if acct_status != 200:
        return empty_sync(
            f"Alpaca paper account GET failed (HTTP {acct_status}). Not live P&L.",
            paper=True,
            http_status=acct_status,
        )
    if pos_status != 200:
        return empty_sync(
            f"Alpaca paper positions GET failed (HTTP {pos_status}). Empty — not invented.",
            paper=True,
            http_status=pos_status,
            account=_account_public(acct_body),
        )

    parsed = parse_positions(pos_body)
    if replace:
        pb.clear_source(SOURCE)
    imported = [pb.upsert_position(**row) for row in parsed]
    return {
        "ok": True,
        "paper": True,
        "source": SOURCE,
        "imported": len(imported),
        "positions": imported,
        "account": _account_public(acct_body),
        "note": NOTE,
        "reason": NOTE if imported else "Alpaca paper account ok; no positions. Empty book from broker — not invented.",
        "configured": True,
        "base_url": PAPER_BASE,
    }
