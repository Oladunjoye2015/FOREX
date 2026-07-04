"""Indicator math on plain lists — no pandas needed, keeps the image small."""
from __future__ import annotations


def ema(values: list[float], period: int) -> list[float]:
    if len(values) < period:
        return []
    k = 2.0 / (period + 1)
    out = [sum(values[:period]) / period]  # seed with SMA
    for v in values[period:]:
        out.append(v * k + out[-1] * (1 - k))
    # left-pad so indices align with input
    return [float("nan")] * (period - 1) + out


def rsi(closes: list[float], period: int = 14) -> list[float]:
    if len(closes) <= period:
        return []
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period
    out = [float("nan")] * period
    for i in range(period, len(gains) + 1):
        if i > period:
            avg_g = (avg_g * (period - 1) + gains[i - 1]) / period
            avg_l = (avg_l * (period - 1) + losses[i - 1]) / period
        rs = avg_g / avg_l if avg_l > 1e-12 else float("inf")
        out.append(100.0 - 100.0 / (1.0 + rs) if rs != float("inf") else 100.0)
    return out


def atr(highs: list[float], lows: list[float], closes: list[float],
        period: int = 14) -> list[float]:
    n = len(closes)
    if n <= period:
        return []
    trs = [highs[0] - lows[0]]
    for i in range(1, n):
        trs.append(max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        ))
    out = [float("nan")] * (period - 1)
    a = sum(trs[:period]) / period
    out.append(a)
    for tr in trs[period:]:
        a = (a * (period - 1) + tr) / period   # Wilder smoothing
        out.append(a)
    return out
