"""London/NY session-breakout setup with a multi-signal confluence approval layer.

Setup (the trigger):
    Build the pre-session range from the N hours before the session open.
    A completed candle CLOSING beyond the range high/low inside the entry
    window is a breakout candidate.

Approval layer (every check must pass):
    1. Trend      — EMA(fast) vs EMA(slow) aligned with breakout direction.
    2. Momentum   — RSI confirms (>= rsi_long_min for longs, <= rsi_short_max shorts).
    3. Volatility — range height between range_atr_min and range_atr_max ATRs.
    4. Extension  — close is not more than max_extension_atr ATRs past the edge
                    (don't chase an exhausted candle).
    5. Spread     — live spread <= max_spread_atr * ATR.

Trade construction:
    SL = entry -/+ sl_atr_mult * ATR   (never inside the broken range edge)
    TP = entry +/- tp_r_mult * risk    (default 2R)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .candle import Candle
from .config import Settings, SessionWindow
from .indicators import atr, ema, rsi


@dataclass
class Signal:
    instrument: str
    session: str
    direction: str            # "long" | "short"
    entry: float              # breakout close (reference; fills are market)
    stop_loss: float
    take_profit: float
    atr: float
    range_high: float
    range_low: float
    checks: dict = field(default_factory=dict)
    approved: bool = False

    @property
    def risk_per_unit(self) -> float:
        return abs(self.entry - self.stop_loss)


def _parse_time(ts: str) -> datetime:
    # OANDA RFC3339 with nanoseconds, e.g. 2026-07-04T07:00:00.000000000Z
    return datetime.fromisoformat(ts.split(".")[0] + "+00:00")


def active_session(now: datetime, cfg: Settings) -> SessionWindow | None:
    """Return the session whose entry window contains `now`, if any."""
    for s in cfg.sessions:
        open_dt = now.replace(hour=s.open_hour_utc, minute=0, second=0, microsecond=0)
        if open_dt <= now < open_dt + timedelta(hours=s.entry_hours):
            return s
    return None


def session_range(candles: list[Candle], session: SessionWindow,
                  now: datetime) -> tuple[float, float] | None:
    """High/low of completed candles in the pre-open range window."""
    open_dt = now.replace(hour=session.open_hour_utc, minute=0, second=0, microsecond=0)
    start = open_dt - timedelta(hours=session.range_hours)
    highs, lows = [], []
    for c in candles:
        t = _parse_time(c.time)
        if c.complete and start <= t < open_dt:
            highs.append(c.h)
            lows.append(c.l)
    if len(highs) < 3:            # not enough data to define a range
        return None
    return max(highs), min(lows)


def evaluate(instrument: str, candles: list[Candle], spread: float,
             cfg: Settings, now: datetime | None = None) -> Signal | None:
    """Return a Signal (approved or vetoed, for journaling) or None if no setup."""
    now = now or datetime.now(timezone.utc)
    session = active_session(now, cfg)
    if session is None:
        return None

    completed = [c for c in candles if c.complete]
    if len(completed) < cfg.ema_slow + 5:
        return None

    rng = session_range(completed, session, now)
    if rng is None:
        return None
    range_high, range_low = rng

    last = completed[-1]
    t_last = _parse_time(last.time)
    open_dt = now.replace(hour=session.open_hour_utc, minute=0, second=0, microsecond=0)
    if t_last < open_dt:          # breakout candle must be inside the session
        return None

    if last.c > range_high:
        direction = "long"
    elif last.c < range_low:
        direction = "short"
    else:
        return None               # no breakout — nothing to evaluate

    closes = [c.c for c in completed]
    highs = [c.h for c in completed]
    lows = [c.l for c in completed]

    ema_f = ema(closes, cfg.ema_fast)[-1]
    ema_s = ema(closes, cfg.ema_slow)[-1]
    rsi_v = rsi(closes, cfg.rsi_period)[-1]
    atr_v = atr(highs, lows, closes, cfg.atr_period)[-1]
    if atr_v <= 0:
        return None

    range_h = range_high - range_low
    edge = range_high if direction == "long" else range_low
    extension = abs(last.c - edge)

    checks = {
        "trend": ema_f > ema_s if direction == "long" else ema_f < ema_s,
        "momentum": rsi_v >= cfg.rsi_long_min if direction == "long"
                    else rsi_v <= cfg.rsi_short_max,
        "volatility": cfg.range_atr_min <= range_h / atr_v <= cfg.range_atr_max,
        "extension": extension <= cfg.max_extension_atr * atr_v,
        "spread": spread <= cfg.max_spread_atr * atr_v,
    }

    entry = last.c
    if direction == "long":
        sl = min(entry - cfg.sl_atr_mult * atr_v, range_high - 0.1 * atr_v)
        tp = entry + cfg.tp_r_mult * (entry - sl)
    else:
        sl = max(entry + cfg.sl_atr_mult * atr_v, range_low + 0.1 * atr_v)
        tp = entry - cfg.tp_r_mult * (sl - entry)

    return Signal(
        instrument=instrument, session=session.name, direction=direction,
        entry=entry, stop_loss=sl, take_profit=tp, atr=atr_v,
        range_high=range_high, range_low=range_low,
        checks={k: bool(v) for k, v in checks.items()},
        approved=all(checks.values()),
    )
