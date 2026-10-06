from datetime import date

from app.core import rate_limit
from app.core.rate_limit import RateLimiter, client_ip


class FakeTime:
    def __init__(self):
        self.now = 0.0
        self.day = date(2026, 1, 1)

    def clock(self):
        return self.now

    def today(self):
        return self.day


def make_limiter(per_minute=2, per_day=100):
    fake = FakeTime()
    return RateLimiter(per_minute, per_day, clock=fake.clock, today=fake.today), fake


def test_allows_up_to_per_minute_limit_then_refuses():
    limiter, _ = make_limiter(per_minute=2)

    assert limiter.check("a") is None
    assert limiter.check("a") is None
    assert "too quickly" in limiter.check("a")


def test_per_minute_limit_is_per_client():
    limiter, _ = make_limiter(per_minute=1)

    assert limiter.check("a") is None
    assert limiter.check("b") is None
    assert limiter.check("a") is not None


def test_per_minute_window_slides():
    limiter, fake = make_limiter(per_minute=1)

    assert limiter.check("a") is None
    fake.now = 59.9
    assert limiter.check("a") is not None
    fake.now = 60.0
    assert limiter.check("a") is None


def test_refused_requests_do_not_count():
    limiter, fake = make_limiter(per_minute=1, per_day=2)

    assert limiter.check("a") is None
    assert limiter.check("a") is not None
    fake.now = 60.0
    assert limiter.check("a") is None


def test_daily_limit_applies_across_clients_and_resets_next_day():
    limiter, fake = make_limiter(per_minute=10, per_day=2)

    assert limiter.check("a") is None
    assert limiter.check("b") is None
    assert "daily question limit" in limiter.check("c")

    fake.day = date(2026, 1, 2)
    assert limiter.check("c") is None


def test_client_ip_uses_address_added_by_the_trusted_proxy():
    assert client_ip({"x-forwarded-for": "1.2.3.4"}, "10.0.0.9", trusted_hops=1) == "1.2.3.4"


def test_client_ip_ignores_addresses_the_client_forged():
    # The client sent "6.6.6.6"; the proxy appended the real address.
    headers = {"x-forwarded-for": "6.6.6.6, 1.2.3.4"}

    assert client_ip(headers, "10.0.0.9", trusted_hops=1) == "1.2.3.4"


def test_client_ip_counts_hops_from_the_right():
    headers = {"x-forwarded-for": "6.6.6.6, 1.2.3.4, 10.0.0.1"}

    assert client_ip(headers, "10.0.0.9", trusted_hops=2) == "1.2.3.4"


def test_client_ip_with_fewer_addresses_than_hops_uses_the_leftmost():
    assert client_ip({"x-forwarded-for": "1.2.3.4"}, "10.0.0.9", trusted_hops=2) == "1.2.3.4"


def test_client_ip_falls_back_to_the_connection_address():
    assert client_ip({}, "10.0.0.9", trusted_hops=1) == "10.0.0.9"
    assert client_ip({"x-forwarded-for": " , "}, "10.0.0.9", trusted_hops=1) == "10.0.0.9"
    assert client_ip({"x-forwarded-for": "1.2.3.4"}, "10.0.0.9", trusted_hops=0) == "10.0.0.9"
    assert client_ip({}, None, trusted_hops=1) == "unknown"


def test_client_ip_logs_only_the_address_count(caplog, monkeypatch):
    # Each count is logged once per process; start from none logged.
    monkeypatch.setattr(rate_limit, "_logged_forwarded_counts", set())
    caplog.set_level("INFO", logger="app.core.rate_limit")

    client_ip({"x-forwarded-for": "6.6.6.6, 1.2.3.4, 10.0.0.1, 10.0.0.2"}, "10.0.0.9", trusted_hops=1)

    assert "X-Forwarded-For contains 4 address(es)" in caplog.text
    assert "6.6.6.6" not in caplog.text
    assert "1.2.3.4" not in caplog.text
