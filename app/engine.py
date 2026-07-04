"""The trading loop: poll -> evaluate -> gate -> execute -> journal."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from .config import settings
from .journal import Journal
from .news_filter import NewsFilter
from .oanda import OandaClient, OandaError, price_precision
from .risk import RiskManager
from .strategy import active_session, evaluate

log = logging.getLogger("engine")


class Engine:
    def __init__(self):
        self.cfg = settings
        self.client = OandaClient()
        self.news_filter = NewsFilter(self.cfg)
        self.risk = RiskManager(self.cfg)
        self.journal = Journal(self.cfg.data_dir)
        self.enabled = self.cfg.trading_enabled
        self.status: dict = {"state": "starting"}
        self._task: asyncio.Task | None = None

    def start(self):
        self._task = asyncio.create_task(self._run())

    async def stop(self):
        if self._task:
            self._task.cancel()
        await self.news_filter.close()
        await self.client.close()

    async def _run(self):
        problems = self.cfg.validate()
        if problems:
            self.status = {"state": "misconfigured", "problems": problems}
            log.error("Engine not started: %s", problems)
            return
        log.info("Engine started (%s, %s)", self.cfg.oanda_env,
                 ",".join(self.cfg.instruments))
        while True:
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Tick failed")
                self.status = {**self.status, "state": "error-retrying"}
            await asyncio.sleep(self.cfg.poll_seconds)

    async def _tick(self):
        now = datetime.now(timezone.utc)
        acct = await self.client.account_summary()
        nav = float(acct["NAV"])
        balance = float(acct["balance"])
        unrealized = float(acct.get("unrealizedPL", 0))
        trades = await self.client.open_trades()

        self.risk.roll_day(nav, now)
        can_trade = self.risk.check_daily_loss(nav)
        session = active_session(now, self.cfg)

        self.journal.log_equity(balance, nav, unrealized, len(trades))
        self.status = {
            "state": "running",
            "time_utc": now.isoformat(),
            "env": self.cfg.oanda_env,
            "enabled": self.enabled,
            "session": session.name if session else None,
            "nav": nav, "balance": balance, "unrealized_pl": unrealized,
            "open_trades": len(trades),
            "daily_halt": self.risk.halted_today,
            "day_start_nav": self.risk.day_start_nav,
            "news_filter": self.news_filter.last_status,
        }

        if not (self.enabled and can_trade and session):
            return

        pricing = await self.client.pricing(list(self.cfg.instruments))
        open_instruments = {t["instrument"] for t in trades}

        for inst in self.cfg.instruments:
            inst = inst.strip()
            if inst in open_instruments:
                continue
            px = pricing.get(inst)
            if not px or not px["tradeable"]:
                continue
            try:
                candles = await self.client.candles(
                    inst, self.cfg.granularity, self.cfg.candle_count)
            except OandaError as e:
                log.warning("Candles failed for %s: %s", inst, e)
                continue

            sig = evaluate(inst, candles, px["spread"], self.cfg, now)
            if sig is None:
                continue
            if not sig.approved:
                self.journal.log_signal(sig, executed=False,
                                        veto_reason="confluence checks failed")
                continue

            news_decision = await self.news_filter.allow(inst, now)
            self.status = {**self.status, "news_filter": self.news_filter.last_status}
            if not news_decision.allowed:
                self.journal.log_signal(sig, executed=False,
                                        veto_reason=news_decision.reason)
                log.info("Signal vetoed (%s %s): %s", inst, sig.direction,
                         news_decision.reason)
                continue

            decision = self.risk.evaluate(sig, nav, len(trades), px["mid"])
            if not decision.allowed:
                self.journal.log_signal(sig, executed=False, veto_reason=decision.reason)
                log.info("Signal vetoed (%s %s): %s", inst, sig.direction, decision.reason)
                continue

            units = decision.units if sig.direction == "long" else -decision.units
            try:
                resp = await self.client.market_order(
                    inst, units, sig.stop_loss, sig.take_profit,
                    price_precision(inst))
            except OandaError as e:
                self.journal.log_signal(sig, executed=False, veto_reason=f"order rejected: {e}")
                log.error("Order rejected for %s: %s", inst, e)
                continue

            self.risk.record_trade(sig)
            self.journal.log_signal(sig, executed=True)
            self.journal.log_trade(sig, units, resp)
            trades = await self.client.open_trades()
            log.info("EXECUTED %s %s %s units @~%.5f SL %.5f TP %.5f",
                     sig.direction.upper(), inst, units,
                     sig.entry, sig.stop_loss, sig.take_profit)
