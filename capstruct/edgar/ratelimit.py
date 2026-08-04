"""
ratelimit.py - Token-bucket limiter for SEC's hard 10 requests/second cap.

Thread-safe: the EDGAR client may be driven from a thread pool, and going
over the limit gets the IP blocked, so the bucket is guarded by a lock and
blocks rather than dropping requests.
"""
from __future__ import annotations

import threading
import time


# Accumulated float error leaves the bucket a hair under a whole token
# (0.9999999999999998), making the deficit ~1e-16 and the resulting sleep
# smaller than the clock's resolution — the loop then spins forever without
# time advancing. Compare with a tolerance instead.
_EPS = 1e-9


class TokenBucket:
    """
    Classic token bucket. `rate` tokens are added per second up to `capacity`;
    acquire() blocks until a token is available.

    Defaults to 9/sec rather than SEC's stated 10 — the limit is enforced on
    their side over a sliding window, and clock skew on a full-rate client is
    what turns "at the limit" into "over it".
    """

    def __init__(self, rate: float = 9.0, capacity: float | None = None,
                 time_fn=time.monotonic, sleep_fn=time.sleep):
        if rate <= 0:
            raise ValueError("rate must be positive")
        self.rate = rate
        self.capacity = capacity if capacity is not None else rate
        self._tokens = self.capacity
        self._last = time_fn()
        self._lock = threading.Lock()
        self._time = time_fn
        self._sleep = sleep_fn

    def _refill(self) -> None:
        now = self._time()
        elapsed = now - self._last
        if elapsed > 0:
            self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
            self._last = now

    def acquire(self, tokens: float = 1.0) -> float:
        """Block until `tokens` are available. Returns seconds waited."""
        if tokens > self.capacity:
            raise ValueError("requested tokens exceed bucket capacity")

        waited = 0.0
        while True:
            with self._lock:
                self._refill()
                if self._tokens + _EPS >= tokens:
                    self._tokens = max(0.0, self._tokens - tokens)
                    return waited
                deficit = tokens - self._tokens
                # Floor the delay so a rounding-sized deficit still advances
                # the clock; without it the loop can spin without progress.
                delay = max(deficit / self.rate, _EPS)
            self._sleep(delay)
            waited += delay

    @property
    def tokens(self) -> float:
        with self._lock:
            self._refill()
            return self._tokens
