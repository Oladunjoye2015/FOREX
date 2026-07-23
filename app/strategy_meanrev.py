"""Mean-reversion strategy: fade closes beyond the Bollinger Bands back to
the mean, in flat regimes only.

Setup (the trigger):
    A completed M15 candle CLOSING below the lower band (long) or above the
    upper band (short), inside an enabled session window.

Approval layer (every enabled check must pass):
    rsi_extreme — RSI confirms exhaustion (<= 30 long / >= 70 short default).
    flat_regime — EMA fast/slow gap small vs ATR: only fade in ranges, never
                  against a real trend (this is the mean-reversion analogue of
                  the breakout's trend filter).
    extension   — close not more than max_extension_atr beyond the band
                  (don't catch a falling knife).
    reward      — distance back to the mean must be >= mr_min_rr * risk.
    spread      — live spread <= max_spread_atr * ATR (same as breakout).

Trade construction:
    SL = mr_sl_atr_mult * ATR beyond entry.  TP = the middle band (the mean).
"""
from __future__ import annotations

from datetime import datetime, timezone
from statistics import fmean, pstdev

from .candle import Candle
from .config import Settings
from .indicators import atr, ema, rsi
from .strategy import Signal, active_session, _parse_time


def evaluate(instrument: str, candles: list[Candle], spread: float,
             cfg: Settings, now: datetime | None = None) -> Signal | None:
    """Same contract as strategy.evaluate: Signal or None."""
    now = now or datetime.now(timezone.utc)
    session = active_session(now, cfg)
    if session is None:
        return None

    completed = [c for c in candles if c.complete]
    if len(completed) < max(cfg.ema_slow, cfg.bb_period) + 5:
        return None

    last = completed[-1]
    open_dt = now.replace(hour=session.open_hour_utc, minute=0, second=0, microsecond=0)
    if _parse_time(last.time) < open_dt:
        return None

    closes = [c.c for c in completed]
    highs = [c.h for c in completed]
    lows = [c.l for c in completed]

    window = closes[-cfg.bb_period:]
    mean = fmean(window)
    sd = pstdev(window)
    upper = mean + cfg.bb_std * sd
    lower = mean - cfg.bb_std * sd

    if last.c < lower:
        direction, band = "long", lower
    elif last.c > upper:
        direction, band = "short", upper
    else:
        return None

    ema_f = ema(closes, cfg.ema_fast)[-1]
    ema_s = ema(closes, cfg.ema_slow)[-1]
    rsi_v = rsi(closes, cfg.rsi_period)[-1]
    atr_v = atr(highs, lows, closes, cfg.atr_period)[-1]
    if atr_v <= 0 or sd <= 0:
        return None

    entry = last.c
    if direction == "long":
        sl = entry - cfg.mr_sl_atr_mult * atr_v
        tp = mean
        reward = tp - entry
    else:
        sl = entry + cfg.mr_sl_atr_mult * atr_v
        tp = mean
        reward = entry - tp
    risk = abs(entry - sl)
    extension = abs(entry - band)

    checks = {
        "rsi_extreme": rsi_v <= cfg.mr_rsi_long_max if direction == "long"
                       else rsi_v >= cfg.mr_rsi_short_min,
        "flat_regime": abs(ema_f - ema_s) <= cfg.mr_max_trend_atr * atr_v,
        "extension": extension <= cfg.max_extension_atr * atr_v,
        "reward": risk > 0 and reward >= cfg.mr_min_rr * risk,
        "spread": spread <= cfg.max_spread_atr * atr_v,
    }
    for name, on in (("rsi_extreme", cfg.check_momentum),
                     ("flat_regime", cfg.check_trend),
                     ("extension", cfg.check_extension),
                     ("spread", cfg.check_spread)):
        if not on:
            checks[name] = True

    metrics = {
        "rsi": round(rsi_v, 1), "atr": round(atr_v, 6),
        "bb_mean": round(mean, 6), "bb_upper": round(upper, 6),
        "bb_lower": round(lower, 6),
        "trend_gap_atr": round(abs(ema_f - ema_s) / atr_v, 2),
        "extension_atr_ratio": round(extension / atr_v, 2),
        "reward_risk": round(reward / risk, 2) if risk > 0 else 0.0,
        "spread": round(spread, 6),
        "spread_atr_ratio": round(spread / atr_v, 3),
    }

    return Signal(
        instrument=instrument, session=session.name, direction=direction,
        entry=entry, stop_loss=sl, take_profit=tp, atr=atr_v,
        range_high=upper, range_low=lower,
        checks={**{k: bool(v) for k, v in checks.items()}, "_values": metrics},
        approved=all(checks.values()),
    )
