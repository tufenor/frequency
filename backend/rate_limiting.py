"""Small bounded per-process rate limiter for login failures."""

from __future__ import annotations

import hashlib
import hmac
import math
import time
from collections import OrderedDict, deque
from threading import Lock


class LoginRateLimiter:
    def __init__(
        self,
        secret: str,
        *,
        max_attempts: int = 8,
        window_seconds: int = 900,
        max_keys: int = 4096,
    ):
        if not secret:
            raise ValueError("A secret is required for login rate limiting.")
        if max_attempts < 1 or window_seconds < 1 or max_keys < 1:
            raise ValueError("Rate limit settings must be positive.")
        self._secret = secret.encode("utf-8")
        self._max_attempts = max_attempts
        self._window_seconds = window_seconds
        self._max_keys = max_keys
        self._failures: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = Lock()

    def _key(self, username: str, client_ip: str | None) -> str:
        identity = username.strip().lower()
        source = client_ip or "unknown"
        message = f"{len(identity)}:{identity}\0{source}".encode("utf-8")
        return hmac.new(self._secret, message, hashlib.sha256).hexdigest()

    def _recent_failures(self, key: str, now: float) -> deque[float] | None:
        failures = self._failures.get(key)
        if failures is None:
            return None
        cutoff = now - self._window_seconds
        while failures and failures[0] <= cutoff:
            failures.popleft()
        if not failures:
            del self._failures[key]
            return None
        self._failures.move_to_end(key)
        return failures

    def retry_after(self, username: str, client_ip: str | None, *, now: float | None = None) -> int:
        current = time.monotonic() if now is None else now
        key = self._key(username, client_ip)
        with self._lock:
            failures = self._recent_failures(key, current)
            if failures is None or len(failures) < self._max_attempts:
                return 0
            return max(1, math.ceil(failures[0] + self._window_seconds - current))

    def record_failure(
        self,
        username: str,
        client_ip: str | None,
        *,
        now: float | None = None,
    ) -> None:
        current = time.monotonic() if now is None else now
        key = self._key(username, client_ip)
        with self._lock:
            failures = self._recent_failures(key, current)
            if failures is None:
                failures = deque()
                self._failures[key] = failures
            failures.append(current)
            self._failures.move_to_end(key)
            while len(self._failures) > self._max_keys:
                self._failures.popitem(last=False)

    def clear(self, username: str, client_ip: str | None) -> None:
        key = self._key(username, client_ip)
        with self._lock:
            self._failures.pop(key, None)
