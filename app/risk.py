"""Risk manager — position sizing, daily circuit breaker, exposure caps."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from .config import Settings
from .strategy import Signal

log = logging.getLogger("risk")


@dataclass
class RiskDecision:
    allowed: bool
    units: int = 0
    reason: str = ""


class RiskManager:
    def __init__(self, cfg: Settings):
        self.cfg = cfg
        self.day: str | None = None
        self.day_start_nav: float | None = None
        self.halted_today = False
        # (instrument, session, yyyy-mm-dd) already traded
        self._session_trades: set[tuple[str, str, str]] = set()

    # ---- daily circuit breaker -------------------------------------------

    def roll_day(self, nav: float, now: datetime | None = None):
        now = now or datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")
        if today != self.day:
            self.day = today
            self.day_start_nav = nav
            self.halted_today = False
            self._session_trades = {k for k in self._session_trades if k[2] == today}
            log.info("New trading day %s, start NAV %.2f", today, nav)

    def check_daily_loss(self, nav: float) -> bool:
        """True if trading may continue."""
        if self.day_start_nav is None or self.day_start_nav <= 0:
            return True
        dd_pct = (self.day_start_nav - nav) / self.day_start_nav * 100
        if dd_pct >= self.cfg.max_daily_loss_pct:
            if not self.halted_today:
                log.warning("DAILY LOSS LIMIT HIT (%.2f%%) — halting for the day", dd_pct)
            self.halted_today = True
        return not self.halted_today

    # ---- per-trade gate -------------------------------------------------------

    def evaluate(self, sig: Signal, nav: float, open_trade_count: int,
                 price_mid: float) -> RiskDecision:
        if self.halted_today:
            return RiskDecision(False, reason="daily loss limit reached")
        if open_trade_count >= self.cfg.max_open_trades:
            return RiskDecision(False, reason=f"max open trades ({self.cfg.max_open_trades})")

        key = (sig.instrument, sig.session, self.day or "")
        if self.cfg.one_trade_per_session and key in self._session_trades:
            return RiskDecision(False, reason="already traded this instrument this session")

        if sig.risk_per_unit <= 0:
            return RiskDecision(False, reason="zero stop distance")

        units = self._size(sig, nav, price_mid)
        if units < 1:
            return RiskDecision(False, reason="position size rounds to zero")
        return RiskDecision(True, units=units)

    def record_trade(self, sig: Signal):
        self._session_trades.add((sig.instrument, sig.session, self.day or ""))

    # ---- sizing -----------------------------------------------------------------

    def _size(self, sig: Signal, nav: float, price_mid: float) -> int:
        """P&L per unit is sl-distance in QUOTE currency. Convert the risk
        budget (account currency, assumed USD) into quote currency.

        - xxx_USD pairs (EUR_USD, GBP_USD, AUD_USD): quote IS USD.
        - USD_xxx pairs (USD_JPY, USD_CAD): 1 USD = price_mid quote units.
        Cross pairs without USD would need an extra conversion leg — the
        default universe avoids them.
        """
        risk_usd = nav * self.cfg.risk_per_trade_pct / 100.0
        quote = sig.instrument.split("_")[1]
        risk_quote = risk_usd if quote == "USD" else risk_usd * price_mid
        units = int(risk_quote / sig.risk_per_unit)
        return min(units, self.cfg.max_units)
