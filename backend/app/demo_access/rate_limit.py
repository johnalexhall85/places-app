from __future__ import annotations

from collections import defaultdict, deque
from time import monotonic


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._attempts: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, *, max_attempts: int, window_seconds: int) -> bool:
        now = monotonic()
        window_start = now - window_seconds
        attempts = self._attempts[key]
        while attempts and attempts[0] < window_start:
            attempts.popleft()
        if len(attempts) >= max_attempts:
            return False
        attempts.append(now)
        return True


validation_rate_limiter = InMemoryRateLimiter()

