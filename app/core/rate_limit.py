"""In-memory request limits that cap Azure OpenAI spend on a public demo.

State lives in the process, so limits reset on restart and apply per replica.
That is enough for a single-replica deployment (Hugging Face Spaces, or
Container Apps at 0-1 replicas).
"""

import threading
import time
from collections import deque
from datetime import datetime, timezone

WINDOW_SECONDS = 60
# Above this many tracked clients, idle ones are dropped so memory stays bounded.
MAX_TRACKED_CLIENTS = 10_000


def utc_today():
    return datetime.now(timezone.utc).date()


def client_ip(headers, fallback):
    """The caller's IP, taken from X-Forwarded-For when behind a proxy."""
    forwarded = headers.get("x-forwarded-for", "")
    first = forwarded.split(",")[0].strip()
    return first or fallback or "unknown"


class RateLimiter:
    def __init__(self, per_client_per_minute, global_per_day, clock=time.monotonic, today=utc_today):
        self.per_client_per_minute = per_client_per_minute
        self.global_per_day = global_per_day
        self._clock = clock
        self._today = today
        self._lock = threading.Lock()
        self._hits = {}
        self._day = today()
        self._day_count = 0

    def check(self, client):
        """Record a request from client and return None, or a refusal message if over a limit."""
        with self._lock:
            today = self._today()
            if today != self._day:
                self._day = today
                self._day_count = 0
                self._hits.clear()

            if self._day_count >= self.global_per_day:
                return "The demo has reached its daily question limit. Please try again tomorrow."

            now = self._clock()
            if len(self._hits) > MAX_TRACKED_CLIENTS:
                self._drop_idle_clients(now)

            hits = self._hits.setdefault(client, deque())
            while hits and now - hits[0] >= WINDOW_SECONDS:
                hits.popleft()
            if len(hits) >= self.per_client_per_minute:
                return "You're asking questions too quickly. Please wait a minute and try again."

            hits.append(now)
            self._day_count += 1
            return None

    def _drop_idle_clients(self, now):
        idle = [client for client, hits in self._hits.items() if not hits or now - hits[-1] >= WINDOW_SECONDS]
        for client in idle:
            del self._hits[client]
