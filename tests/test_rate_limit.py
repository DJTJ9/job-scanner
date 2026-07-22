from jobscanner.web.rate_limit import RateLimiter


def test_hit_allows_up_to_max_attempts_then_blocks():
    limiter = RateLimiter(window_seconds=600, max_attempts=5)
    for _ in range(5):
        assert limiter.hit("1.2.3.4") is True
    assert limiter.hit("1.2.3.4") is False


def test_hit_is_keyed_independently_per_key():
    limiter = RateLimiter(window_seconds=600, max_attempts=1)
    assert limiter.hit("a") is True
    assert limiter.hit("b") is True
    assert limiter.hit("a") is False


def test_hit_allows_again_after_window_expires(monkeypatch):
    import jobscanner.web.rate_limit as rl
    now = [1000.0]
    monkeypatch.setattr(rl.time, "monotonic", lambda: now[0])
    limiter = RateLimiter(window_seconds=10, max_attempts=1)
    assert limiter.hit("a") is True
    assert limiter.hit("a") is False
    now[0] += 11
    assert limiter.hit("a") is True


def test_count_reports_current_hits_without_consuming_budget():
    limiter = RateLimiter(window_seconds=600, max_attempts=5)
    limiter.hit("a")
    limiter.hit("a")
    assert limiter.count("a") == 2
    assert limiter.count("a") == 2  # count() is a peek operation, not a hit
