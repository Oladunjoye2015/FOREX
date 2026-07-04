"""Thin async client for the OANDA v20 REST API."""
from __future__ import annotations

import logging

import httpx

from .candle import Candle
from .config import settings

log = logging.getLogger("oanda")

__all__ = ["Candle", "OandaClient", "OandaError", "price_precision"]


class OandaError(RuntimeError):
    pass


class OandaClient:
    def __init__(self):
        self._client = httpx.AsyncClient(
            base_url=settings.api_base,
            headers={
                "Authorization": f"Bearer {settings.oanda_token}",
                "Content-Type": "application/json",
            },
            timeout=20.0,
        )
        self.account_id = settings.oanda_account_id

    async def close(self):
        await self._client.aclose()

    async def _get(self, path: str, **params) -> dict:
        r = await self._client.get(path, params=params)
        if r.status_code >= 400:
            raise OandaError(f"GET {path} -> {r.status_code}: {r.text[:300]}")
        return r.json()

    async def _post(self, path: str, payload: dict) -> dict:
        r = await self._client.post(path, json=payload)
        if r.status_code >= 400:
            raise OandaError(f"POST {path} -> {r.status_code}: {r.text[:300]}")
        return r.json()

    # ---- Market data -----------------------------------------------------

    async def candles(self, instrument: str, granularity: str, count: int) -> list[Candle]:
        data = await self._get(
            f"/v3/instruments/{instrument}/candles",
            granularity=granularity, count=count, price="M",
        )
        out = []
        for c in data.get("candles", []):
            mid = c["mid"]
            out.append(Candle(
                time=c["time"], o=float(mid["o"]), h=float(mid["h"]),
                l=float(mid["l"]), c=float(mid["c"]),
                volume=int(c["volume"]), complete=bool(c["complete"]),
            ))
        return out

    async def pricing(self, instruments: list[str]) -> dict[str, dict]:
        data = await self._get(
            f"/v3/accounts/{self.account_id}/pricing",
            instruments=",".join(instruments),
        )
        out = {}
        for p in data.get("prices", []):
            bid = float(p["bids"][0]["price"])
            ask = float(p["asks"][0]["price"])
            out[p["instrument"]] = {
                "bid": bid, "ask": ask, "mid": (bid + ask) / 2,
                "spread": ask - bid, "tradeable": p.get("tradeable", True),
            }
        return out

    # ---- Account ------------------------------------------------------------

    async def account_summary(self) -> dict:
        data = await self._get(f"/v3/accounts/{self.account_id}/summary")
        return data["account"]

    async def open_trades(self) -> list[dict]:
        data = await self._get(f"/v3/accounts/{self.account_id}/openTrades")
        return data.get("trades", [])

    # ---- Orders ----------------------------------------------------------------

    async def market_order(self, instrument: str, units: int,
                           stop_loss: float, take_profit: float,
                           precision: int) -> dict:
        """units > 0 buys, units < 0 sells. SL/TP attached to the fill."""
        payload = {
            "order": {
                "type": "MARKET",
                "instrument": instrument,
                "units": str(units),
                "timeInForce": "FOK",
                "positionFill": "DEFAULT",
                "stopLossOnFill": {"price": f"{stop_loss:.{precision}f}"},
                "takeProfitOnFill": {"price": f"{take_profit:.{precision}f}"},
            }
        }
        log.info("Placing order: %s", payload["order"])
        return await self._post(f"/v3/accounts/{self.account_id}/orders", payload)

    async def close_trade(self, trade_id: str) -> dict:
        r = await self._client.put(
            f"/v3/accounts/{self.account_id}/trades/{trade_id}/close",
            json={"units": "ALL"},
        )
        if r.status_code >= 400:
            raise OandaError(f"close_trade {trade_id} -> {r.status_code}: {r.text[:300]}")
        return r.json()


def price_precision(instrument: str) -> int:
    """JPY pairs quote to 3 decimals, everything else to 5."""
    return 3 if instrument.endswith("_JPY") else 5
