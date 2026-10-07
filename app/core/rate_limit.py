"""Per-visitor request limits for the public demo.

The per-minute limit lives in the process, so it resets on restart and applies
per replica. The daily cap on Azure spend is counted in Postgres instead (see
app/database/daily_cap.py) so restarts and redeploys can't reset it.
"""

import logging
import threading
import time
from collections import deque
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

WINDOW_SECONDS = 60
# Above this many tracked clients, idle ones are dropped so memory stays bounded.
MAX_TRACKED_CLIENTS = 10_000

_logged_forwarded_counts = set()


def utc_today():
    return datetime.now(timezone.utc).date()


def _log_forwarded_count(count):
    # Logs each distinct count once, never the addresses, so TRUSTED_PROXY_HOPS
    # can be set from the deployment's logs.
    if count not in _logged_forwarded_counts:
        _logged_forwarded_counts.add(count)
        logger.info("X-Forwarded-For contains %d address(es)", count)


def client_ip(headers, fallback, trusted_hops=1):
    """The caller's IP, as added to X-Forwarded-For by the trusted proxies.

    Each proxy appends the address it received the request from, so the
    entry trusted_hops from the right was added by our outermost proxy and
    can't be forged. Entries further left come from the client.
    """
    addresses = [part.strip() for part in headers.get("x-forwarded-for", "").split(",") if part.strip()]
    _log_forwarded_count(len(addresses))

    if trusted_hops < 1 or not addresses:
        return fallback or "unknown"
    # Fewer entries than proxies: every entry was added by a proxy.
    return addresses[-min(trusted_hops, len(addresses))]


class DailyCapReached(Exception):
    """Raised instead of calling Azure once today's question cap is used up."""

    message = "The demo has reached its daily question limit. Please try again tomorrow."


class RateLimiter:
    def __init__(self, per_client_per_minute, clock=time.monotonic):
        self.per_client_per_minute = per_client_per_minute
        self._clock = clock
        self._lock = threading.Lock()
        self._hits = {}

    def check(self, client):
        """Record a request from client and return None, or a refusal message if over the limit."""
        with self._lock:
            now = self._clock()
            if len(self._hits) > MAX_TRACKED_CLIENTS:
                self._drop_idle_clients(now)

            hits = self._hits.setdefault(client, deque())
            while hits and now - hits[0] >= WINDOW_SECONDS:
                hits.popleft()
            if len(hits) >= self.per_client_per_minute:
                return "You're asking questions too quickly. Please wait a minute and try again."

            hits.append(now)
            return None

    def _drop_idle_clients(self, now):
        idle = [client for client, hits in self._hits.items() if not hits or now - hits[-1] >= WINDOW_SECONDS]
        for client in idle:
            del self._hits[client]
