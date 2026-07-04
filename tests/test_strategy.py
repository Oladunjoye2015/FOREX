"""Smoke tests: indicators, breakout detection, confluence vetoes, sizing.
Run: python -m pytest tests/ -q   (or plain: python tests/test_strategy.py)"""
import sys, os
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.config import Settings
from app.indicators import ema, rsi, atr
from app.candle import Candle
from app.strategy import evaluate, session_range, active_session
from app.risk import RiskManager


def make_candles(start: datetime, prices: list[float], spread=0.0004) -> list[Candle]:
    out = []
    for i, p in enumerate(prices):
        t = start + timedelta(minutes=15 * i)
        out.append(Candle(
            time=t.strftime("%Y-%m-%dT%H:%M:%S.000000000Z"),
            o=p, h=p + 0.0008, l=p - 0.0008, c=p, volume=100, complete=True,
        ))
    return out


def test_indicators():
    closes = [float(i) for i in range(1, 300)]
    assert abs(ema(closes, 50)[-1] - closes[-1]) < 25       # trails a trend
    r = rsi(closes, 14)
    assert r[-1] > 90                                        # monotone up => high RSI
    a = atr([c + 1 for c in closes], [c - 1 for c in closes], closes, 14)
    assert 1.9 < a[-1] < 2.1                                 # TR includes gap between bars
    print("indicators ok")


def breakout_long_signal():
    cfg = Settings()
    now = datetime(2026, 7, 6, 8, 30, tzinfo=timezone.utc)   # inside London entry window
    start = now - timedelta(minutes=15 * 399)
    # gentle uptrend so EMA50>EMA200 and RSI>55, then a range, then breakout
    prices = []
    base = 1.0800
    n_pre = 380
    for i in range(n_pre):
        prices.append(base + i * 0.00005)                    # uptrend
    range_level = prices[-1]
    for i in range(15):
        prices.append(range_level + (0.0003 if i % 2 else -0.0003))  # tight range
    for i in range(4):
        prices.append(range_level + 0.0015 + i * 0.0004)     # breakout up
    candles = make_candles(start, prices)

    sess = active_session(now, cfg)
    assert sess and sess.name == "LONDON"
    rng = session_range(candles, sess, now)
    assert rng is not None

    sig = evaluate("EUR_USD", candles, spread=0.00008, cfg=cfg, now=now)
    assert sig is not None, "expected a breakout signal"
    assert sig.direction == "long"
    print("checks:", sig.checks, "approved:", sig.approved)
    assert sig.checks["trend"] and sig.checks["momentum"]
    assert sig.stop_loss < sig.entry < sig.take_profit
    # TP should be ~2R
    r = sig.entry - sig.stop_loss
    assert abs((sig.take_profit - sig.entry) - 2 * r) < 1e-9
    return sig


def test_breakout_long_approved():
    breakout_long_signal()
    print("breakout long ok")


def test_spread_veto():
    cfg = Settings()
    now = datetime(2026, 7, 6, 8, 30, tzinfo=timezone.utc)
    start = now - timedelta(minutes=15 * 399)
    prices = [1.08 + i * 0.00005 for i in range(380)]
    level = prices[-1]
    prices += [level + (0.0003 if i % 2 else -0.0003) for i in range(15)]
    prices += [level + 0.0015 + i * 0.0004 for i in range(4)]
    candles = make_candles(start, prices)
    sig = evaluate("EUR_USD", candles, spread=0.01, cfg=cfg, now=now)  # huge spread
    assert sig is not None and not sig.checks["spread"] and not sig.approved
    print("spread veto ok")


def test_no_session():
    cfg = Settings()
    now = datetime(2026, 7, 6, 22, 0, tzinfo=timezone.utc)   # outside both windows
    assert active_session(now, cfg) is None
    print("session gating ok")


def test_session_filters():
    cfg = Settings()
    london = datetime(2026, 7, 6, 8, 30, tzinfo=timezone.utc)  # Monday
    assert active_session(london, cfg).name == "LONDON"

    cfg.enabled_sessions = ("NEWYORK",)
    assert active_session(london, cfg) is None

    cfg.enabled_sessions = ("LONDON",)
    cfg.disabled_weekdays = ("MON",)
    assert active_session(london, cfg) is None

    cfg.disabled_weekdays = ()
    cfg.disabled_utc_hours = (8,)
    assert active_session(london, cfg) is None
    print("session filters ok")


def test_sizing_and_circuit_breaker():
    cfg = Settings()
    rm = RiskManager(cfg)
    now = datetime(2026, 7, 6, 8, 30, tzinfo=timezone.utc)
    rm.roll_day(10_000.0, now)
    sig = breakout_long_signal()

    d = rm.evaluate(sig, nav=10_000.0, open_trade_count=0, price_mid=sig.entry)
    assert d.allowed and d.units > 0
    # 0.5% of 10k = $50 risk; USD-quoted pair so units = 50 / stop distance
    expected = int(50.0 / sig.risk_per_unit)
    assert d.units == min(expected, cfg.max_units), (d.units, expected)

    rm.record_trade(sig)
    d2 = rm.evaluate(sig, 10_000.0, 0, sig.entry)
    assert not d2.allowed and "already traded" in d2.reason

    assert rm.check_daily_loss(9_800.0) is True      # -2%: under the 3% limit
    assert rm.check_daily_loss(9_600.0) is False     # -4%: halted
    assert not rm.evaluate(sig, 9_600.0, 0, sig.entry).allowed
    print("sizing + circuit breaker ok")


if __name__ == "__main__":
    test_indicators()
    test_breakout_long_approved()
    test_spread_veto()
    test_no_session()
    test_sizing_and_circuit_breaker()
    print("\nALL TESTS PASSED")
