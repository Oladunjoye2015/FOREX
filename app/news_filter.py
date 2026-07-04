"""Economic-calendar filter for skipping trades around noisy macro events."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx

from .config import Settings

log = logging.getLogger("news_filter")

INSTRUMENT_CURRENCIES = {
    "EUR_USD": ("EUR", "USD"),
    "GBP_USD": ("GBP", "USD"),
    "USD_JPY": ("USD", "JPY"),
    "AUD_USD": ("AUD", "USD"),
    "USD_CAD": ("USD", "CAD"),
    "NZD_USD": ("NZD", "USD"),
    "USD_CHF": ("USD", "CHF"),
    "EUR_GBP": ("EUR", "GBP"),
}

COUNTRY_CURRENCY = {
    "united states": "USD",
    "us": "USD",
    "usa": "USD",
    "euro area": "EUR",
    "euro zone": "EUR",
    "eurozone": "EUR",
    "germany": "EUR",
    "france": "EUR",
    "italy": "EUR",
    "spain": "EUR",
    "united kingdom": "GBP",
    "uk": "GBP",
    "great britain": "GBP",
    "japan": "JPY",
    "australia": "AUD",
    "canada": "CAD",
    "new zealand": "NZD",
    "switzerland": "CHF",
}


@dataclass
class NewsDecision:
    allowed: bool
    reason: str = ""


class NewsFilter:
    def __init__(self, cfg: Settings):
        self.cfg = cfg
        self._client = httpx.AsyncClient(timeout=15.0)
        self._cache_key: tuple[str, str] | None = None
        self._cache_until: datetime = datetime.min.replace(tzinfo=timezone.utc)
        self._events: list[dict] = []
        self.last_status: dict = {"enabled": cfg.news_filter_enabled}

    async def close(self):
        await self._client.aclose()

    async def allow(self, instrument: str, now: datetime) -> NewsDecision:
        if not self.cfg.news_filter_enabled:
            self.last_status = {"enabled": False}
            return NewsDecision(True)

        currencies = set(INSTRUMENT_CURRENCIES.get(instrument, instrument.split("_")))
        start = now - timedelta(minutes=self.cfg.news_block_after_min)
        end = now + timedelta(minutes=self.cfg.news_block_before_min)

        try:
            events = await self._events_between(start, end)
        except Exception as exc:
            log.warning("News filter failed: %s", exc)
            self.last_status = {
                "enabled": True,
                "state": "error",
                "error": str(exc)[:200],
                "fail_closed": self.cfg.news_fail_closed,
            }
            if self.cfg.news_fail_closed:
                return NewsDecision(False, f"news filter unavailable: {exc}")
            return NewsDecision(True)

        min_impacts = {x.lower() for x in self.cfg.news_min_impacts}
        for event in events:
            impact = str(event.get("impact", "")).lower()
            currency = self._event_currency(event)
            if impact not in min_impacts or currency not in currencies:
                continue
            name = str(event.get("event") or event.get("title") or "macro event")
            when = str(event.get("time") or event.get("datetime") or "")
            self.last_status = {
                "enabled": True,
                "state": "blocked",
                "instrument": instrument,
                "currency": currency,
                "impact": impact,
                "event": name,
                "time": when,
            }
            return NewsDecision(False, f"news filter: {impact} {currency} event: {name}")

        self.last_status = {
            "enabled": True,
            "state": "clear",
            "instrument": instrument,
            "currencies": sorted(currencies),
            "checked_events": len(events),
        }
        return NewsDecision(True)

    async def _events_between(self, start: datetime, end: datetime) -> list[dict]:
        now = datetime.now(timezone.utc)
        key = (start.date().isoformat(), end.date().isoformat())
        if self._cache_key == key and now < self._cache_until:
            return [e for e in self._events if self._in_window(e, start, end)]

        events = await self._fetch_calendar(start, end)
        self._cache_key = key
        self._cache_until = now + timedelta(seconds=self.cfg.news_cache_seconds)
        self._events = events
        return [e for e in events if self._in_window(e, start, end)]

    async def _fetch_calendar(self, start: datetime, end: datetime) -> list[dict]:
        if self.cfg.news_calendar_url:
            url = self.cfg.news_calendar_url.format(
                start=start.date().isoformat(),
                end=end.date().isoformat(),
            )
            resp = await self._client.get(url)
            resp.raise_for_status()
            data = resp.json()
        elif self.cfg.news_provider == "finnhub":
            if not self.cfg.news_api_key:
                raise RuntimeError("NEWS_API_KEY or FINNHUB_API_KEY is required")
            qs = urlencode({
                "from": start.date().isoformat(),
                "to": end.date().isoformat(),
                "token": self.cfg.news_api_key,
            })
            url = f"https://finnhub.io/api/v1/calendar/economic?{qs}"
            resp = await self._client.get(url)
            resp.raise_for_status()
            data = resp.json()
        else:
            raise RuntimeError(f"Unsupported NEWS_PROVIDER={self.cfg.news_provider}")

        if isinstance(data, dict):
            raw_events = data.get("economicCalendar") or data.get("events") or data.get("calendar") or []
        elif isinstance(data, list):
            raw_events = data
        else:
            raw_events = []
        return [e for e in raw_events if isinstance(e, dict)]

    def _in_window(self, event: dict, start: datetime, end: datetime) -> bool:
        event_time = self._event_time(event)
        return event_time is not None and start <= event_time <= end

    def _event_time(self, event: dict) -> datetime | None:
        raw = event.get("time") or event.get("datetime") or event.get("date")
        if not raw:
            return None
        if isinstance(raw, (int, float)):
            return datetime.fromtimestamp(raw, tz=timezone.utc)
        text = str(raw).replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            try:
                dt = datetime.strptime(str(raw), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            except ValueError:
                return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    def _event_currency(self, event: dict) -> str:
        currency = str(event.get("currency") or event.get("curr") or "").upper()
        if currency:
            return currency
        country = str(event.get("country") or "").strip().lower()
        return COUNTRY_CURRENCY.get(country, country.upper())
