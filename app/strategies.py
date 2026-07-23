"""Strategy registry — live engine and backtester both dispatch through here."""
from __future__ import annotations

from . import strategy as _breakout
from . import strategy_meanrev as _meanrev

STRATEGIES = {
    "breakout": _breakout.evaluate,   # London/NY session-range breakout
    "meanrev": _meanrev.evaluate,     # Bollinger-band fade back to the mean
}


def get_evaluator(name: str):
    try:
        return STRATEGIES[name]
    except KeyError:
        raise ValueError(f"unknown strategy '{name}' (valid: {', '.join(STRATEGIES)})")
