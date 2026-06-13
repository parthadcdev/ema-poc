"""Thread-safe per-target rate limiter enforcing a minimum interval between
requests to honor a requests-per-minute cap (FR-207). clock/sleep are
injectable for deterministic tests."""

from __future__ import annotations

import threading
import time


class RateLimiter:
    def __init__(self, requests_per_minute: int, *, clock=time.monotonic, sleep=time.sleep):
        self._min_interval = 60.0 / requests_per_minute if requests_per_minute > 0 else 0.0
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._next_allowed = 0.0

    def acquire(self) -> None:
        if self._min_interval <= 0:
            return
        with self._lock:
            now = self._clock()
            wait = self._next_allowed - now
            if wait > 0:
                self._sleep(wait)
                now = self._clock()
            self._next_allowed = max(now, self._next_allowed) + self._min_interval
