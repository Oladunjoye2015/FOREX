"""Event-driven backtester for the session-breakout strategy.

Design goal: **parity with live trading.** The backtest reuses the exact same
`strategy.evaluate()` and `risk.RiskManager` the live engine uses, so a signal
that would fire (or be vetoed) in production fires (or is vetoed) here too.

How a bar is processed (no look-ahead):
    1. First, manage OPEN positions against this bar's high/low — check SL/TP.
    2. Then, treat this newly-completed bar as the breakout candidate: feed
       candles[:i+1] into evaluate() with now = bar close time.
    3. An approved + risk-approved signal is entered at the NEXT bar's open
       (that's the earliest a live market order could realistically fill),
       adjusted for spread.

Fills, costs, exits:
    - Entry fill = next open +/- half spread (buy the ask, sell the bid).
    - Intrabar SL/TP: if a bar's range straddles both, assume SL hits first
      (conservative). SL/TP levels come straight from the Signal.
    - No time stop (matches live) — a trade rides until SL or TP; any still
      open at the end of data is marked-to-market and closed.

P&L is booked in the account currency (assumed USD) with the same quote->USD
conversion logic the live sizer uses.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .candle import Candle
from .config import Settings
from .risk import RiskManager
from .strategies import get_evaluator
from .strategy import Signal, active_session, _parse_time


# Typical dealing spreads in PRICE units, used both for the approval "spread"
# check and for entry cost. Override per instrument via BacktestConfig.spreads.
DEFAULT_SPREADS = {
    "EUR_USD": 0.00012, "GBP_USD": 0.00016, "AUD_USD": 0.00014,
    "USD_CAD": 0.00020, "USD_JPY": 0.012,   "NZD_USD": 0.00020,
    "EUR_GBP": 0.00016, "USD_CHF": 0.00018,
}


@dataclass
class BacktestConfig:
    starting_nav: float = 10_000.0
    spreads: dict = field(default_factory=lambda: dict(DEFAULT_SPREADS))
    # slippage added to the entry fill, in price units (per instrument default 0)
    slippage: float = 0.0

    def spread_for(self, instrument: str) -> float:
        if instrument in self.spreads:
            return self.spreads[instrument]
        return 0.012 if instrument.endswith("_JPY") else 0.00016


@dataclass
class Trade:
    instrument: str
    session: str
    direction: str
    units: int
    entry_time: str
    entry: float
    stop_loss: float
    take_profit: float
    exit_time: str = ""
    exit: float = 0.0
    outcome: str = ""          # "tp" | "sl" | "eod"
    pnl_usd: float = 0.0
    r_multiple: float = 0.0
    nav_after: float = 0.0

    @property
    def risk_per_unit(self) -> float:
        return abs(self.entry - self.stop_loss)


def _quote_to_usd(instrument: str, pnl_quote: float, price: float) -> float:
    """Convert a P&L expressed in the pair's quote currency into USD.

    xxx_USD -> quote already USD.  USD_xxx -> divide by the exchange rate.
    Cross pairs (no USD leg) are approximated 1:1 and flagged by the caller's
    universe choice; the default universe avoids them.
    """
    quote = instrument.split("_")[1]
    if quote == "USD":
        return pnl_quote
    if instrument.split("_")[0] == "USD":
        return pnl_quote / price if price else pnl_quote
    return pnl_quote  # cross pair fallback


@dataclass
class OpenPosition:
    signal: Signal
    trade: Trade


class Backtester:
    def __init__(self, cfg: Settings, bt: BacktestConfig | None = None):
        self.cfg = cfg
        self.bt = bt or BacktestConfig()
        self.risk = RiskManager(cfg)
        self.nav = self.bt.starting_nav
        self.equity_curve: list[tuple[str, float]] = []
        self.trades: list[Trade] = []
        self.open_positions: list[OpenPosition] = []
        self.signals_evaluated = 0
        self.signals_vetoed = 0

    # -- position management ------------------------------------------------

    def _check_exits(self, instrument: str, now_bar: Candle):
        """Close open positions ON THIS INSTRUMENT touched by this bar."""
        still_open: list[OpenPosition] = []
        for pos in self.open_positions:
            t = pos.trade
            if t.instrument != instrument:
                still_open.append(pos)
                continue
            hit_sl = hit_tp = False
            if t.direction == "long":
                hit_sl = now_bar.l <= t.stop_loss
                hit_tp = now_bar.h >= t.take_profit
            else:
                hit_sl = now_bar.h >= t.stop_loss
                hit_tp = now_bar.l <= t.take_profit

            if hit_sl and hit_tp:
                exit_px, outcome = t.stop_loss, "sl"   # conservative: SL first
            elif hit_sl:
                exit_px, outcome = t.stop_loss, "sl"
            elif hit_tp:
                exit_px, outcome = t.take_profit, "tp"
            else:
                still_open.append(pos)
                continue
            self._close(pos, now_bar.time, exit_px, outcome)
        self.open_positions = still_open

    def _close(self, pos: OpenPosition, when: str, exit_px: float, outcome: str):
        t = pos.trade
        sign = 1 if t.direction == "long" else -1
        pnl_quote = sign * (exit_px - t.entry) * t.units
        pnl_usd = _quote_to_usd(t.instrument, pnl_quote, exit_px)
        self.nav += pnl_usd
        t.exit_time, t.exit, t.outcome = when, exit_px, outcome
        t.pnl_usd = pnl_usd
        risk_usd = _quote_to_usd(t.instrument, t.risk_per_unit * t.units, t.entry)
        t.r_multiple = pnl_usd / risk_usd if risk_usd else 0.0
        t.nav_after = self.nav
        self.trades.append(t)

    # -- entries ------------------------------------------------------------

    def _try_enter(self, instrument: str, sig: Signal, next_open: float,
                   bar_time: str, now: datetime):
        spread = self.bt.spread_for(instrument)
        # Entry fill: cross the spread + slippage.
        if sig.direction == "long":
            fill = next_open + spread / 2 + self.bt.slippage
        else:
            fill = next_open - spread / 2 - self.bt.slippage

        # Re-derive SL/TP from the actual fill so risk geometry stays correct.
        rpu = abs(sig.entry - sig.stop_loss)
        if sig.direction == "long":
            sl = fill - rpu
            tp = fill + self.cfg.tp_r_mult * rpu
        else:
            sl = fill + rpu
            tp = fill - self.cfg.tp_r_mult * rpu

        sig_fill = Signal(
            instrument=instrument, session=sig.session, direction=sig.direction,
            entry=fill, stop_loss=sl, take_profit=tp, atr=sig.atr,
            range_high=sig.range_high, range_low=sig.range_low,
            checks=sig.checks, approved=True,
        )
        decision = self.risk.evaluate(sig_fill, self.nav, len(self.open_positions),
                                      price_mid=fill)
        if not decision.allowed:
            self.signals_vetoed += 1
            return
        self.risk.record_trade(sig_fill)
        trade = Trade(
            instrument=instrument, session=sig.session, direction=sig.direction,
            units=decision.units, entry_time=bar_time, entry=fill,
            stop_loss=sl, take_profit=tp,
        )
        self.open_positions.append(OpenPosition(sig_fill, trade))

    # -- main loop ----------------------------------------------------------

    def run(self, data: dict[str, list[Candle]]):
        """`data` maps instrument -> chronological list of completed candles.

        We drive the clock off a single merged timeline of bar-close events so
        portfolio-level rules (max concurrent trades, daily circuit breaker)
        see instruments in true time order.
        """
        # Build one merged, time-sorted stream of (time, instrument, index).
        events = []
        for inst, candles in data.items():
            for i, c in enumerate(candles):
                if c.complete:
                    events.append((_parse_time(c.time), inst, i))
        events.sort(key=lambda e: e[0])

        for now, inst, i in events:
            candles = data[inst]
            bar = candles[i]

            # 1. Manage the daily circuit breaker off current NAV.
            self.risk.roll_day(self.nav, now)
            self.risk.check_daily_loss(self.nav)

            # 2. Exits first (this bar could close positions on ANY instrument
            #    that shares this timestamp; we handle per-instrument bar here).
            self._check_exits(inst, bar)

            # 3. Record equity after exits.
            self.equity_curve.append((bar.time, self.nav))

            # 4. Look for a new setup on this instrument.
            if inst in {p.trade.instrument for p in self.open_positions}:
                continue
            if active_session(now, self.cfg) is None:
                continue

            # Live only ever fetches the last `candle_count` candles, so the
            # backtest feeds evaluate() the same trailing window. This is both
            # faithful to production AND keeps the run O(n) instead of O(n^2).
            lo = max(0, i + 1 - self.cfg.candle_count)
            sig = get_evaluator(self.cfg.strategy)(inst, candles[lo:i + 1],
                                                   self.bt.spread_for(inst), self.cfg, now)
            if sig is None:
                continue
            self.signals_evaluated += 1
            if not sig.approved:
                self.signals_vetoed += 1
                continue
            if i + 1 >= len(candles):        # no next bar to fill against
                continue
            next_open = candles[i + 1].o
            self._try_enter(inst, sig, next_open, candles[i + 1].time, now)

        # Close anything still open at the last seen price.
        for pos in list(self.open_positions):
            t = pos.trade
            last = data[t.instrument][-1]
            self._close(pos, last.time, last.c, "eod")
        self.open_positions.clear()

        return self.report()

    # -- reporting ----------------------------------------------------------

    def report(self) -> dict:
        trades = self.trades
        n = len(trades)
        wins = [t for t in trades if t.pnl_usd > 0]
        losses = [t for t in trades if t.pnl_usd <= 0]
        gross_win = sum(t.pnl_usd for t in wins)
        gross_loss = -sum(t.pnl_usd for t in losses)
        net = sum(t.pnl_usd for t in trades)

        # Max drawdown off the equity curve.
        peak = self.bt.starting_nav
        max_dd = 0.0
        for _, eq in self.equity_curve:
            peak = max(peak, eq)
            max_dd = max(max_dd, (peak - eq) / peak if peak else 0.0)

        # Expectancy in R.
        r_vals = [t.r_multiple for t in trades]
        avg_r = sum(r_vals) / n if n else 0.0

        return {
            "starting_nav": self.bt.starting_nav,
            "ending_nav": self.nav,
            "net_pnl": net,
            "return_pct": (self.nav / self.bt.starting_nav - 1) * 100 if self.bt.starting_nav else 0.0,
            "trades": n,
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": len(wins) / n * 100 if n else 0.0,
            "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else float("inf"),
            "avg_win": gross_win / len(wins) if wins else 0.0,
            "avg_loss": -gross_loss / len(losses) if losses else 0.0,
            "expectancy_r": avg_r,
            "max_drawdown_pct": max_dd * 100,
            "signals_evaluated": self.signals_evaluated,
            "signals_vetoed": self.signals_vetoed,
            "trade_list": trades,
            "equity_curve": self.equity_curve,
        }
