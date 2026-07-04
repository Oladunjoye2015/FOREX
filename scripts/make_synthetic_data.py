"""Generate synthetic M15 candles so the backtester can be exercised offline.

This is a DEMO data source only. It is a driftless geometric random walk with
intraday volatility clustering and realistic per-bar OHLC — it deliberately
contains NO predictable edge. Its purpose is to prove the plumbing (signals,
fills, exits, risk gating, reporting), NOT to estimate the strategy's real
performance. For real numbers, use scripts/fetch_oanda_history.py.

Output matches the fetcher's schema so run_backtest.py treats both identically.
"""
from __future__ import annotations

import argparse
import csv
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

# instrument -> (start_price, annualised vol, price precision)
SPECS = {
    "EUR_USD": (1.0850, 0.07, 5),
    "GBP_USD": (1.2700, 0.08, 5),
    "USD_JPY": (150.00, 0.09, 3),
    "AUD_USD": (0.6650, 0.09, 5),
    "USD_CAD": (1.3600, 0.06, 5),
}

BARS_PER_YEAR = 96 * 252   # M15 bars in a trading year (approx)


def gen_series(inst: str, start: datetime, days: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    price, ann_vol, prec = SPECS[inst]
    per_bar_sigma = ann_vol / math.sqrt(BARS_PER_YEAR)
    rows: list[dict] = []
    t = start
    end = start + timedelta(days=days)
    vol_state = 1.0
    while t < end:
        # Skip weekend (Fri 21:00 UTC -> Sun 21:00 UTC roughly).
        wd = t.weekday()
        if wd == 5 or (wd == 4 and t.hour >= 21) or (wd == 6 and t.hour < 21):
            t += timedelta(minutes=15)
            continue
        # Volatility clustering + session-of-day bump (London/NY busier).
        vol_state = 0.94 * vol_state + 0.06 * rng.uniform(0.5, 1.6)
        session_bump = 1.4 if 7 <= t.hour <= 16 else 0.8
        sigma = per_bar_sigma * vol_state * session_bump
        ret = rng.gauss(0.0, sigma)
        o = price
        c = price * math.exp(ret)
        hi = max(o, c) * (1 + abs(rng.gauss(0, sigma * 0.6)))
        lo = min(o, c) * (1 - abs(rng.gauss(0, sigma * 0.6)))
        rows.append({
            "time": t.strftime("%Y-%m-%dT%H:%M:%S.000000000Z"),
            "open": round(o, prec), "high": round(hi, prec),
            "low": round(lo, prec), "close": round(c, prec),
            "volume": rng.randint(80, 600), "complete": True,
        })
        price = c
        t += timedelta(minutes=15)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instruments", default=",".join(SPECS))
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--start", default="2025-06-01")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="data/history")
    args = ap.parse_args()

    start = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    for k, inst in enumerate([s.strip() for s in args.instruments.split(",")]):
        rows = gen_series(inst, start, args.days, args.seed + k)
        path = out_dir / f"{inst}.csv"
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["time", "open", "high", "low",
                                              "close", "volume", "complete"])
            w.writeheader()
            w.writerows(rows)
        print(f"wrote {len(rows)} synthetic candles -> {path}")


if __name__ == "__main__":
    main()
