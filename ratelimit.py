import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request


class RateLimiter:
    """Allows `limit` requests per `window_seconds` for each client IP."""

    def __init__(self, limit: int, window_seconds: int):
        self.limit = limit
        self.window = window_seconds
        self.hits = defaultdict(deque)
        self.lock = threading.Lock()
        self.enabled = True

    def __call__(self, request: Request):
        if not self.enabled:
            return
        client = request.client.host if request.client else "unknown"
        now = time.monotonic()
        with self.lock:
            recent = self.hits[client]
            while recent and now - recent[0] > self.window:
                recent.popleft()
            if len(recent) >= self.limit:
                raise HTTPException(status_code=429, detail="Too many requests")
            recent.append(now)