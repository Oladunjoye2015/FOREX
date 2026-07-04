# OANDA Day Trader

Automated forex day-trading system. Session-breakout setups (London and New York opens) gated by a multi-signal confluence approval layer, executed on OANDA v20 with hard risk controls, monitored via a web dashboard, deployable to Railway in one command.

**This is a trading tool, not trading advice. Forex carries substantial risk of loss. It ships pointed at OANDA's practice environment — forward-test there for several weeks before even considering `OANDA_ENV=live`.**

## Strategy

**Setup (trigger).** For each session the bot builds the pre-open range (default: 5 hours before London 07:00 UTC, 4 hours before New York 12:00 UTC) from M15 candles. A completed candle closing beyond the range high or low inside the entry window (first 4 hours of the session) is a breakout candidate.

**Approval layer (all five must pass or the signal is vetoed and journaled).**

| Check | Rule (defaults) |
|---|---|
| Trend | EMA50 vs EMA200 aligned with breakout direction |
| Momentum | RSI14 ≥ 55 (long) / ≤ 45 (short) |
| Volatility | Range height between 0.8× and 4× ATR14 |
| Extension | Close ≤ 1× ATR beyond the broken edge (no chasing) |
| Spread | Live spread ≤ 15% of ATR |

**Trade construction.** Market order with SL/TP attached to the fill. SL = 1.5×ATR from entry (and always beyond the broken range edge); TP = 2R.

**Risk controls.** 0.5% of NAV risked per trade with exact position sizing; max 2 concurrent trades; one trade per pair per session; 3% daily drawdown circuit breaker halts trading until the next UTC day; hard per-order unit cap; dashboard kill switch.

## Backtest first

**Look at the data before you risk a cent.** The backtester replays the exact
same `strategy.evaluate()` and `RiskManager` the live engine uses, so a signal
that would fire (or get vetoed) in production behaves identically here. It needs
no network and no account — just Python's standard library.

**1. Get historical candles.** Either pull real M15 history from OANDA (run
locally, a practice token is enough — candles don't need an account ID):

```bash
export OANDA_API_TOKEN=...        # practice token
python -m scripts.fetch_oanda_history --from 2024-01-01 --to 2026-07-01
```

…or generate offline demo data to try the machinery immediately:

```bash
python scripts/make_synthetic_data.py --days 365
```

Both write `data/history/<INSTRUMENT>.csv`.

**2. Run the backtest.**

```bash
python -m scripts.run_backtest --data data/history --nav 10000
```

This prints a summary and writes to `data/backtest/`:

- `report.md` — headline stats + per-instrument breakdown
- `trades.csv` — one row per closed trade (entry/exit/outcome/P&L/R-multiple)
- `equity.csv` — the NAV curve over time

**3. Tune and re-run.** Every knob the live bot reads from the environment also
drives the backtest, so you can A/B parameters without touching code:

```bash
RISK_PER_TRADE_PCT=0.25 TP_R_MULT=2.5 RSI_LONG_MIN=60 \
  python -m scripts.run_backtest --data data/history
```

### How fills are modelled (and its limits)

- **Entry:** the next bar's open after the breakout close, crossing the spread
  (buy the ask, sell the bid) plus optional slippage — the earliest a live
  market order could realistically fill.
- **Exits:** intrabar against each bar's high/low; if a bar straddles both SL
  and TP, SL is assumed hit first (conservative). No time stop, matching live.
- **Spread** is a fixed per-instrument estimate (`app/backtest.py` →
  `DEFAULT_SPREADS`), used both for the approval check and entry cost. Real
  spreads widen around news and the session opens this strategy trades — treat
  backtested costs as a floor.
- **Caveats:** M15 OHLC hides the intrabar path, so SL/TP-in-same-bar is an
  approximation; no swap/financing, no partial fills, no requote/rejection
  modelling. Synthetic data has **no real edge** by construction — it only
  proves the plumbing. Forward-test on OANDA practice before trusting any
  number here.

## Local run

```bash
cp .env.example .env        # fill in token + account id
pip install -r requirements.txt
export $(grep -v '^#' .env | xargs)
uvicorn app.main:app --port 8000
```

Dashboard at http://localhost:8000.

### Getting OANDA credentials (practice)

1. Create a free demo account at oanda.com → fxTrade Practice.
2. Log into the fxTrade web platform → Manage API Access → generate a token.
3. Your account ID is on the same page (format `101-xxx-xxxxxxx-xxx`).

## Deploy to Railway

Option A — GitHub (recommended):

1. Push this folder to a GitHub repo.
2. In Railway: **New Project → Deploy from GitHub repo**. The `Dockerfile` and `railway.toml` are picked up automatically.
3. In the service → **Variables**, set `OANDA_ENV=practice`, `OANDA_API_TOKEN`, `OANDA_ACCOUNT_ID`.
4. Optional but recommended: **Volumes → attach a volume**, mount path `/data`, and set variable `DATA_DIR=/data` so the trade journal survives redeploys.
5. **Settings → Networking → Generate Domain** to get a URL for the dashboard.

Option B — CLI:

```bash
npm i -g @railway/cli
railway login
railway init          # inside this folder
railway variables set OANDA_ENV=practice OANDA_API_TOKEN=... OANDA_ACCOUNT_ID=...
railway up
```

The `/healthz` endpoint is wired to Railway's healthcheck. Anyone with the URL can see the dashboard and hit the kill switch — keep the domain private or put it behind Railway's private networking / an auth proxy before going live.

## Going live (when you're ready — don't rush this)

1. Run on practice for 4+ weeks; review the signals table for veto quality and the equity curve.
2. Change `OANDA_ENV=live` and use a **live** token and account ID.
3. Start with `RISK_PER_TRADE_PCT=0.25` and a low `MAX_UNITS`.

## Architecture

```
app/
  candle.py      the Candle datatype (dependency-free)
  config.py      env-driven settings (strategy, risk, sessions)
  oanda.py       async OANDA v20 REST client
  indicators.py  EMA / RSI / ATR (Wilder)
  strategy.py    breakout setup + confluence approval
  risk.py        sizing, daily circuit breaker, exposure caps
  backtest.py    event-driven backtester (reuses strategy + risk)
  journal.py     SQLite journal: signals, trades, equity
  engine.py      poll → evaluate → gate → execute loop
  main.py        FastAPI app + dashboard endpoints
  dashboard.html live dashboard (Chart.js)
scripts/
  fetch_oanda_history.py   download real M15 history to CSV
  make_synthetic_data.py   offline demo data (no edge, tests plumbing)
  run_backtest.py          run the backtest, emit report + trade log
```

## Known limitations

Session opens are fixed UTC hours — DST shifts London/NY opens by an hour twice a year (adjust `LONDON_OPEN_UTC`/`NY_OPEN_UTC` or accept the drift). No news filter — consider pausing around top-tier releases (NFP, CPI, central banks). Sizing assumes a USD-denominated account. In-memory session-dedupe state resets on redeploy (worst case: one extra trade per pair per session).
