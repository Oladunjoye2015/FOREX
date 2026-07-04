"""Download historical M15 candles from OANDA into per-instrument CSVs.

Run this LOCALLY (where OANDA's API is reachable) with your practice token:

    export OANDA_API_TOKEN=...        # a practice token is fine for candles
    export OANDA_ENV=practice
    python -m scripts.fetch_oanda_history --from 2024-01-01 --to 2026-07-01

Output: data/history/<INSTRUMENT>.csv with columns
    time,open,high,low,close,volume,complete

Notes
-----
* Candle data only needs a token, not an account ID.
* OANDA caps each request at 5000 candles, so we page by time.
* Times are UTC RFC3339. Only completed candles are written.
"""
from __future__ import annotations

import argparse
import csv
import os
import ssl
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API = {
    "practice": "https://api-fxpractice.oanda.com",
    "live": "https://api-fxtrade.oanda.com",
}


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


def _get(base: str, token: str, path: str, **params) -> dict:
    import json
    url = f"{base}{path}?{urlencode(params)}"
    req = Request(url, headers={"Authorization": f"Bearer {token}"})
    with urlopen(req, timeout=30, context=_ssl_context()) as r:
        return json.loads(r.read().decode())


def fetch_instrument(base: str, token: str, instrument: str,
                     start: datetime, end: datetime, granularity: str) -> list[dict]:
    rows: list[dict] = []
    cursor = start
    while cursor < end:
        data = _get(
            base, token, f"/v3/instruments/{instrument}/candles",
            granularity=granularity, price="M", count=5000,
            **{"from": cursor.isoformat().replace("+00:00", "Z")},
        )
        candles = data.get("candles", [])
        if not candles:
            break
        for c in candles:
            t = datetime.fromisoformat(c["time"].split(".")[0] + "+00:00")
            if t >= end:
                break
            if not c["complete"]:
                continue
            m = c["mid"]
            rows.append({
                "time": c["time"], "open": m["o"], "high": m["h"],
                "low": m["l"], "close": m["c"], "volume": c["volume"],
                "complete": c["complete"],
            })
        last_t = datetime.fromisoformat(candles[-1]["time"].split(".")[0] + "+00:00")
        if last_t <= cursor:
            cursor = cursor + timedelta(minutes=15)
        else:
            cursor = last_t + timedelta(seconds=1)
        time.sleep(0.15)   # be polite to the API
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instruments",
                    default=os.getenv("INSTRUMENTS", "EUR_USD,GBP_USD,USD_JPY,AUD_USD,USD_CAD"))
    ap.add_argument("--granularity", default=os.getenv("GRANULARITY", "M15"))
    ap.add_argument("--from", dest="start", required=True, help="YYYY-MM-DD")
    ap.add_argument("--to", dest="end", required=True, help="YYYY-MM-DD")
    ap.add_argument("--out", default="data/history")
    args = ap.parse_args()

    token = os.getenv("OANDA_API_TOKEN")
    if not token:
        sys.exit("Set OANDA_API_TOKEN (a practice token works for candles).")
    base = API[os.getenv("OANDA_ENV", "practice")]

    start = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
    end = datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    for inst in [s.strip() for s in args.instruments.split(",")]:
        print(f"Fetching {inst} {args.granularity} {args.start}..{args.end} ...", flush=True)
        rows = fetch_instrument(base, token, inst, start, end, args.granularity)
        path = out_dir / f"{inst}.csv"
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["time", "open", "high", "low",
                                              "close", "volume", "complete"])
            w.writeheader()
            w.writerows(rows)
        print(f"  wrote {len(rows)} candles -> {path}")


if __name__ == "__main__":
    main()
