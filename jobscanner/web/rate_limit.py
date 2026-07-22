"""In-Memory Sliding-Window-Rate-Limiter — pro App-Instanz auf app.state, kein
Cross-Process-Sync nötig (jobscanner-web läuft als einzelner uvicorn-Worker)."""
from __future__ import annotations

import time
from collections import defaultdict, deque

DEFAULT_WINDOW_SECONDS = 600
DEFAULT_MAX_ATTEMPTS = 5


class RateLimiter:
    def __init__(self, window_seconds: int = DEFAULT_WINDOW_SECONDS,
                 max_attempts: int = DEFAULT_MAX_ATTEMPTS):
        self.window_seconds = window_seconds
        self.max_attempts = max_attempts
        self._hits: dict[str, deque] = defaultdict(deque)

    def _purge(self, key: str) -> deque:
        dq = self._hits[key]
        cutoff = time.monotonic() - self.window_seconds
        while dq and dq[0] < cutoff:
            dq.popleft()
        return dq

    def hit(self, key: str) -> bool:
        dq = self._purge(key)
        if len(dq) >= self.max_attempts:
            return False
        dq.append(time.monotonic())
        return True

    def count(self, key: str) -> int:
        return len(self._purge(key))
