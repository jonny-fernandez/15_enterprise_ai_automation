"""Fail-closed, locally scoped credentials and fixed-window throttling.

This is an offline API-key demonstrator, NOT OAuth or a distributed gateway.
Secrets are injected at run time, never stored or logged by this module.
"""
from collections import defaultdict, deque
from dataclasses import dataclass, field
import hmac
import os
import threading
import time

from fastapi import HTTPException


KEYS = {"operator": "PROJECT15_CP3_OPERATOR_KEY", "reviewer": "PROJECT15_CP3_REVIEWER_KEY"}


def authorize(provided: str | None, scope: str) -> str:
    if scope not in KEYS:
        raise ValueError("Unknown scope")
    configured = {s: os.environ.get(var, "") for s, var in KEYS.items()}
    if not all(configured.values()) or configured["operator"] == configured["reviewer"]:
        raise HTTPException(503, "Local scoped API is disabled or misconfigured")
    if (not isinstance(provided, str) or not provided or len(provided) > 512
            or not hmac.compare_digest(configured[scope], provided)):
        raise HTTPException(401, "Unauthorized")
    return scope


@dataclass
class LocalRateLimiter:
    max_requests: int = 10
    window_seconds: int = 60
    _history: dict[str, deque] = field(default_factory=lambda: defaultdict(deque))
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def enforce(self, scope: str, *, now: float | None = None):
        now = time.monotonic() if now is None else now
        with self._lock:
            history = self._history[scope]
            while history and now - history[0] >= self.window_seconds:
                history.popleft()
            if len(history) >= self.max_requests:
                raise HTTPException(429, "Local rate limit exceeded")
            history.append(now)


def public_error(exc: BaseException) -> str:
    """Only exception class, never exception message or user input."""
    return type(exc).__name__
