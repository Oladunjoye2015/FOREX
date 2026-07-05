"""FastAPI app: serves the dashboard and hosts the trading engine."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from .engine import Engine

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

engine = Engine()


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine.start()
    yield
    await engine.stop()


app = FastAPI(title="OANDA Day Trader", lifespan=lifespan)


@app.get("/healthz")
async def healthz():
    return {"ok": True, "state": engine.status.get("state")}


@app.get("/api/status")
async def status():
    return engine.status


@app.get("/api/trades")
async def trades():
    try:
        open_trades = await engine.client.open_trades()
    except Exception:
        open_trades = []
    return {"open": open_trades, "history": engine.journal.recent("trades", 50)}


@app.get("/api/signals")
async def signals():
    return engine.journal.recent("signals", 50)


@app.get("/api/equity")
async def equity():
    rows = engine.journal.recent("equity", 500)
    rows.reverse()
    return rows


@app.get("/api/summary")
async def summary():
    return engine.journal.summary()


@app.get("/api/config")
async def config():
    cfg = engine.cfg
    return {
        "instruments": cfg.instruments,
        "granularity": cfg.granularity,
        "candle_count": cfg.candle_count,
        "enabled_sessions": cfg.enabled_sessions,
        "disabled_weekdays": cfg.disabled_weekdays,
        "disabled_utc_hours": cfg.disabled_utc_hours,
        "risk_per_trade_pct": cfg.risk_per_trade_pct,
        "max_open_trades": cfg.max_open_trades,
        "max_daily_loss_pct": cfg.max_daily_loss_pct,
        "max_units": cfg.max_units,
        "news_filter_enabled": cfg.news_filter_enabled,
        "news_provider": cfg.news_provider,
        "news_block_before_min": cfg.news_block_before_min,
        "news_block_after_min": cfg.news_block_after_min,
        "news_min_impacts": cfg.news_min_impacts,
        "news_fail_closed": cfg.news_fail_closed,
    }


@app.post("/api/toggle")
async def toggle():
    engine.enabled = not engine.enabled
    return {"enabled": engine.enabled}


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    path = os.path.join(os.path.dirname(__file__), "dashboard.html")
    with open(path, encoding="utf-8") as f:
        return f.read()
