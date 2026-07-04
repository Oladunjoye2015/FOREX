"""News filter tests."""
import asyncio
from datetime import datetime, timezone

from app.config import Settings
from app.news_filter import NewsFilter


def run(coro):
    return asyncio.run(coro)


def test_high_impact_event_blocks_pair_currency():
    cfg = Settings()
    cfg.news_filter_enabled = True
    nf = NewsFilter(cfg)
    nf._events = [{
        "time": "2026-07-06T08:45:00+00:00",
        "currency": "USD",
        "impact": "high",
        "event": "Nonfarm Payrolls",
    }]
    nf._cache_key = ("2026-07-06", "2026-07-06")
    nf._cache_until = datetime(2026, 7, 6, 9, 0, tzinfo=timezone.utc)

    decision = run(nf.allow("EUR_USD", datetime(2026, 7, 6, 8, 30, tzinfo=timezone.utc)))

    assert not decision.allowed
    assert "Nonfarm Payrolls" in decision.reason
    run(nf.close())


def test_low_impact_event_does_not_block():
    cfg = Settings()
    cfg.news_filter_enabled = True
    nf = NewsFilter(cfg)
    nf._events = [{
        "time": "2026-07-06T08:45:00+00:00",
        "currency": "USD",
        "impact": "low",
        "event": "Minor Data",
    }]
    nf._cache_key = ("2026-07-06", "2026-07-06")
    nf._cache_until = datetime(2026, 7, 6, 9, 0, tzinfo=timezone.utc)

    decision = run(nf.allow("EUR_USD", datetime(2026, 7, 6, 8, 30, tzinfo=timezone.utc)))

    assert decision.allowed
    run(nf.close())
