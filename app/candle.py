"""The Candle datatype, kept dependency-free.

Living in its own module (rather than inside oanda.py) means the strategy,
indicators, and backtester can be imported and run without pulling in httpx or
any network stack — you can backtest with nothing but the standard library.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Candle:
    time: str
    o: float
    h: float
    l: float
    c: float
    volume: int
    complete: bool
