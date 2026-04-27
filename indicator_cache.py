"""
indicator_cache.py — LRU memoization for expensive compute functions.

Invalidation is version-based: bump_version(symbol) increments a counter
that becomes part of every cache key, so stale entries are skipped on the
next lookup and aged out via the LRU eviction policy.
"""

import hashlib
import threading
import time
from collections import OrderedDict
from typing import Callable, Optional


_LOCK = threading.RLock()
_OHLCV_VERSION: dict[tuple, int] = {}          # (symbol, freq) -> version int
_CACHE: OrderedDict = OrderedDict()             # key -> (value, timestamp)
_MAX_ENTRIES = 512
_TTL = 3600                                     # hard expiry even if version unchanged
_hits = 0
_misses = 0


def bump_version(symbol: str, freq: Optional[str] = None) -> None:
    """Invalidate all cached results for symbol (optionally restricted to one freq)."""
    with _LOCK:
        if freq is None:
            keys = [k for k in _OHLCV_VERSION if k[0] == symbol]
        else:
            keys = [(symbol, freq)]
        for k in keys:
            _OHLCV_VERSION[k] = _OHLCV_VERSION.get(k, 0) + 1
        # Eagerly evict matching cache entries
        for key in list(_CACHE):
            if symbol in key:
                del _CACHE[key]


def _version(symbol: str, freq: str) -> int:
    return _OHLCV_VERSION.get((symbol, freq), 0)


def _phash(params: dict) -> str:
    return hashlib.blake2b(
        repr(sorted(params.items())).encode(), digest_size=8
    ).hexdigest()


def get_or_compute(fn_name: str, symbol: str, freq: str,
                   producer: Callable, **params):
    """Return cached result or call producer(); LRU-evict when _MAX_ENTRIES exceeded."""
    global _hits, _misses
    key = (fn_name, symbol, freq, _version(symbol, freq), _phash(params))
    with _LOCK:
        hit = _CACHE.get(key)
        if hit is not None:
            value, ts = hit
            if time.time() - ts < _TTL:
                _CACHE.move_to_end(key)
                _hits += 1
                return value
        _misses += 1

    # Compute outside the lock so long computations don't block other readers
    value = producer()

    with _LOCK:
        _CACHE[key] = (value, time.time())
        _CACHE.move_to_end(key)
        while len(_CACHE) > _MAX_ENTRIES:
            _CACHE.popitem(last=False)

    return value


def cache_stats() -> dict:
    with _LOCK:
        return {
            "entries": len(_CACHE),
            "version_map_size": len(_OHLCV_VERSION),
            "hits": _hits,
            "misses": _misses,
        }
