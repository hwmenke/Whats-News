"""
precache.py — reversible TTL cache + prewarm helper for expensive reads.

Problem: several GET endpoints fan out per watchlist symbol on every call
(/api/news hits Yahoo once per symbol; /api/scanner, /api/trend-scan and
/api/portfolio/snapshot each pull full OHLCV frames per symbol; /api/knn and
/api/backtest refit models from up to 5000 bars). Page loads therefore feel
janky and hammer Yahoo/DB repeatedly.

What this module provides:
  * tiny bounded TTL caches, one per endpoint family, with env-tunable TTLs
  * `?refresh=1` bypass + `cached` flag (dict payloads) / `X-Cache` header
  * in-flight dedupe so concurrent identical requests share one compute
    instead of stampeding (no refetch storms)
  * boot-time prewarm + lazy background refresh for DB-backed computes,
    threaded, non-blocking and failure-tolerant (never raises)

Reversible: delete this file's import/use sites in app.py (each is marked
with `# precache:`) to restore direct-compute behaviour. No schema or
on-disk state is involved.

Environment knobs (all optional, sane defaults):
  NEWS_TTL_S, SCANNER_TTL_S, TRENDSCAN_TTL_S, PORTFOLIO_TTL_S,
  KNN_TTL_S, BACKTEST_TTL_S, SETUPS_TTL_S   — seconds, 0 disables caching
  PRECACHE_MAX_ENTRIES  — per-cache entry bound (default 64)
  PREFETCH_SYMBOLS      — prewarm symbol cap (default 25, 0 = skip prewarm)
  PREWARM_ENABLED       — 1/true/yes to prewarm on boot (default 1)
  PREWARM_DELAY_S       — wait before prewarming so the port binds first
  NEWS_GAP_S            — pause between per-symbol Yahoo news calls
  NEWS_LIMIT_CAP, SCANNER_SYMBOL_CAP, TRENDSCAN_SYMBOL_CAP,
  SETUPS_LIMIT_CAP, KNN_K_CAP — per-request caps
"""

from __future__ import annotations

import os
import threading
import time


def _env_int(name: str, default: int, lo: int, hi: int) -> int:
    try:
        val = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default
    return max(lo, min(val, hi))


def _env_float(name: str, default: float, lo: float, hi: float) -> float:
    try:
        val = float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default
    return max(lo, min(val, hi))


def _env_flag(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


# ── Tunables ──────────────────────────────────────────────────────────────
NEWS_TTL_S = _env_int("NEWS_TTL_S", 300, 0, 3600)
SCANNER_TTL_S = _env_int("SCANNER_TTL_S", 120, 0, 3600)
TRENDSCAN_TTL_S = _env_int("TRENDSCAN_TTL_S", 120, 0, 3600)
PORTFOLIO_TTL_S = _env_int("PORTFOLIO_TTL_S", 60, 0, 3600)
KNN_TTL_S = _env_int("KNN_TTL_S", 600, 0, 7200)
BACKTEST_TTL_S = _env_int("BACKTEST_TTL_S", 600, 0, 7200)
SETUPS_TTL_S = _env_int("SETUPS_TTL_S", 120, 0, 3600)

CACHE_MAX_ENTRIES = _env_int("PRECACHE_MAX_ENTRIES", 64, 8, 512)
PREFETCH_SYMBOLS = _env_int("PREFETCH_SYMBOLS", 25, 0, 500)
PREWARM_ENABLED = _env_flag("PREWARM_ENABLED", True)
PREWARM_DELAY_S = _env_float("PREWARM_DELAY_S", 2.0, 0.0, 60.0)
NEWS_GAP_S = _env_float("NEWS_GAP_S", 0.25, 0.0, 5.0)

NEWS_LIMIT_CAP = _env_int("NEWS_LIMIT_CAP", 500, 1, 2000)
SCANNER_SYMBOL_CAP = _env_int("SCANNER_SYMBOL_CAP", 250, 1, 1000)
TRENDSCAN_SYMBOL_CAP = _env_int("TRENDSCAN_SYMBOL_CAP", 250, 1, 1000)
SETUPS_LIMIT_CAP = _env_int("SETUPS_LIMIT_CAP", 500, 1, 2000)
KNN_K_CAP = _env_int("KNN_K_CAP", 100, 1, 500)

CACHE_NAMES = (
    "news", "scanner", "trendscan", "portfolio", "knn", "backtest", "setups",
)


class _TTLCache:
    """Thread-safe bounded TTL map. Oldest entries are evicted past the cap."""

    def __init__(self, max_entries: int = 64):
        self._lock = threading.Lock()
        self._max = max(1, max_entries)
        self._store: dict = {}

    def get(self, key):
        with self._lock:
            entry = self._store.get(key)
            if not entry:
                return None, None
            payload, expires = entry
            now = time.time()
            if now > expires:
                self._store.pop(key, None)
                return None, None
            return payload, expires - now

    def set(self, key, payload, ttl_s: float):
        if ttl_s <= 0:
            return
        with self._lock:
            if len(self._store) >= self._max:
                self._store.pop(next(iter(self._store)), None)
            self._store[key] = (payload, time.time() + ttl_s)

    def clear(self):
        with self._lock:
            self._store.clear()

    def __len__(self):
        with self._lock:
            return len(self._store)


_caches = {name: _TTLCache(CACHE_MAX_ENTRIES) for name in CACHE_NAMES}


def _db_path_now():
    try:
        import database as db
        return getattr(db, "DB_PATH", None)
    except Exception:
        return None


_db_path_seen: list = [None]


def _invalidate_on_db_switch():
    """Drop caches when the backing DB file changes underneath us.

    Production never swaps DB_PATH at runtime (one check, ~free). Tests
    patch database.DB_PATH per fixture — without this, a cache entry keyed
    by ("portfolio", ("AAPL",)) from one temp DB would leak into the next.
    Failure-tolerant: if the DB module is unavailable, do nothing.
    """
    try:
        now = _db_path_now()
    except Exception:
        return
    if _db_path_seen[0] is None:
        _db_path_seen[0] = now
        return
    if now != _db_path_seen[0]:
        _db_path_seen[0] = now
        cache_clear()


def cache_get(name: str, key):
    """Return (payload, ttl_remaining_s) or (None, None) on miss/expiry."""
    _invalidate_on_db_switch()
    return _caches[name].get(key)


def cache_set(name: str, key, payload, ttl_s: float):
    _caches[name].set(key, payload, ttl_s)


def cache_clear(name: str | None = None):
    """Clear one cache, or all when name is None. Used by tests + prewarm."""
    if name is None:
        for cache in _caches.values():
            cache.clear()
    else:
        _caches[name].clear()


def cache_stats() -> dict:
    return {
        "entries": {name: len(cache) for name, cache in _caches.items()},
        "ttl_s": {
            "news": NEWS_TTL_S,
            "scanner": SCANNER_TTL_S,
            "trendscan": TRENDSCAN_TTL_S,
            "portfolio": PORTFOLIO_TTL_S,
            "knn": KNN_TTL_S,
            "backtest": BACKTEST_TTL_S,
            "setups": SETUPS_TTL_S,
        },
        "caps": {
            "max_entries": CACHE_MAX_ENTRIES,
            "prefetch_symbols": PREFETCH_SYMBOLS,
            "news_limit": NEWS_LIMIT_CAP,
            "scanner_symbols": SCANNER_SYMBOL_CAP,
            "trendscan_symbols": TRENDSCAN_SYMBOL_CAP,
            "setups_limit": SETUPS_LIMIT_CAP,
            "knn_k": KNN_K_CAP,
        },
        "prewarm_enabled": PREWARM_ENABLED,
    }


# ── In-flight dedupe ──────────────────────────────────────────────────────
_inflight_lock = threading.Lock()
_inflight: dict = {}


class _Call:
    def __init__(self):
        self.event = threading.Event()
        self.payload = None
        self.error = None


def compute_coalesced(key, fn, timeout: float = 120.0):
    """Run fn() once per key even under concurrent requests.

    The first caller becomes the leader and computes; concurrent callers
    wait on the leader's event and share its result (or its exception).
    Always cleans up, never deadlocks the leader path.
    """
    with _inflight_lock:
        call = _inflight.get(key)
        if call is None:
            call = _Call()
            _inflight[key] = call
            leader = True
        else:
            leader = False
    if leader:
        try:
            call.payload = fn()
        except Exception as exc:  # noqa: BLE001 - shared with followers
            call.error = exc
        finally:
            with _inflight_lock:
                _inflight.pop(key, None)
            call.event.set()
        if call.error is not None:
            raise call.error
        return call.payload
    if not call.event.wait(timeout=timeout):
        # Leader is stuck; compute locally rather than hanging the request.
        return fn()
    if call.error is not None:
        raise call.error
    return call.payload


def cached_call(name: str, key, fn, ttl_s: float, refresh: bool = False,
                should_cache=None):
    """TTL lookup with in-flight coalesced compute.

    Returns (payload, was_cached). Errors from fn propagate and are never
    cached — callers decide how to surface them as JSON. Pass
    should_cache(payload)->bool to skip caching values such as API-level
    {"error": ...} dicts (avoids poisoning the cache with transient misses).
    """
    if not refresh and ttl_s > 0:
        payload, _remaining = cache_get(name, key)
        if payload is not None:
            return payload, True
    payload = compute_coalesced((name, key), fn)
    if ttl_s > 0 and (should_cache is None or should_cache(payload)):
        cache_set(name, key, payload, ttl_s)
    return payload, False


def cache_age(name: str, key):
    """Seconds remaining on a cache entry, or None on miss. For tests."""
    _payload, remaining = cache_get(name, key)
    return remaining


# ── Request helpers ───────────────────────────────────────────────────────
def wants_refresh(args) -> bool:
    """`?refresh=1` bypass for any cached read endpoint."""
    try:
        val = args.get("refresh", "")
    except AttributeError:
        return False
    return str(val).strip().lower() in ("1", "true", "yes", "on")


def parse_capped_int(raw, *, default: int, lo: int, hi: int):
    """Parse an optional int query param, clamped to [lo, hi].

    Returns (value, error_message). error_message is None on success;
    callers surface it as a JSON 400 without HTML stack traces.
    """
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return default, None
    try:
        val = int(raw)
    except (TypeError, ValueError):
        return default, "must be an integer"
    if val < lo or val > hi:
        return default, f"must be between {lo} and {hi}"
    return val, None


# ── Background work (never raises) ────────────────────────────────────────
def schedule_background(fn, delay_s: float = 0.0) -> threading.Thread:
    """Run fn() on a daemon thread; swallow all errors (prewarm/refresh)."""

    def _run():
        try:
            if delay_s > 0:
                time.sleep(delay_s)
            fn()
        except Exception:
            pass

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return thread


def maybe_refresh_in_background(name: str, key, fn, ttl_s: float,
                                remaining_s: float | None):
    """Lazy refresh: recompute a half-stale entry without blocking the UI."""
    if ttl_s <= 0 or remaining_s is None:
        return
    if remaining_s < ttl_s / 2:
        def _refresh():
            try:
                payload = fn()
            except Exception:
                return
            cache_set(name, key, payload, ttl_s)

        schedule_background(_refresh)


def prewarm_sync(symbol_cap: int = PREFETCH_SYMBOLS) -> dict:
    """Warm DB-backed caches (portfolio + scanner). No Yahoo calls.

    Failure-tolerant by design: every step is guarded so a missing DB or
    empty watchlist yields a summary dict instead of raising.
    """
    summary: dict = {"warmed": [], "skipped": [], "symbols": 0}
    if symbol_cap <= 0:
        summary["skipped"].append("prefetch_symbols=0")
        return summary
    try:
        import market_data as md
        import portfolio as portfolio_mod
        import scanner as scanner_mod
    except Exception as exc:  # noqa: BLE001 - report, don't raise
        summary["skipped"].append(f"imports: {exc}")
        return summary
    # Use the same symbol sources as the routes so cache keys match.
    try:
        watchlist = [s["symbol"] for s in md.list_symbols()]
        with_data = md.list_symbols_with_ohlcv("daily", min_bars=30)
    except Exception as exc:  # noqa: BLE001
        summary["skipped"].append(f"symbols: {exc}")
        return summary
    symbols = watchlist[:symbol_cap]
    scan_symbols = with_data[:symbol_cap]
    summary["symbols"] = len(watchlist)
    if not watchlist:
        summary["skipped"].append("empty watchlist")
        return summary
    key_symbols = tuple(sorted(symbols))
    try:
        payload = portfolio_mod.portfolio_snapshot()
        if isinstance(payload, dict) and "error" not in payload:
            cache_set("portfolio", ("portfolio", key_symbols), payload,
                      PORTFOLIO_TTL_S)
            summary["warmed"].append("portfolio")
    except Exception as exc:  # noqa: BLE001
        summary["skipped"].append(f"portfolio: {exc}")
    if not scan_symbols:
        summary["skipped"].append("scanner: no symbols with data")
        return summary
    scan_key = tuple(sorted(scan_symbols))
    try:
        payload = scanner_mod.compute_scanner(list(scan_key))
        if isinstance(payload, list):
            cache_set("scanner",
                      ("scanner", True, scan_key, len(scan_key)),
                      payload, SCANNER_TTL_S)
            summary["warmed"].append("scanner")
    except Exception as exc:  # noqa: BLE001
        summary["skipped"].append(f"scanner: {exc}")
    return summary


def prewarm_async() -> threading.Thread | None:
    """Boot-time prewarm on a daemon thread. No-op when disabled."""
    if not PREWARM_ENABLED:
        return None
    return schedule_background(prewarm_sync, delay_s=PREWARM_DELAY_S)
