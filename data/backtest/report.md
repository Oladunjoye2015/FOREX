# Backtest report
> Data source: files in `data/history`. If these are synthetic (make_synthetic_data.py), the numbers below only validate the engine, not real edge.
## Headline
| Metric | Value |
|---|---|
| Starting NAV | $10,000.00 |
| Ending NAV | $6,775.51 |
| Net P&L | $-3,224.49 |
| Return | -32.24% |
| Max drawdown | 33.61% |
| Trades | 587 |
| Win rate | 29.1% |
| Profit factor | 0.82 |
| Expectancy | -0.127 R/trade |
| Avg win | $84.46 |
| Avg loss | $-42.47 |
| Signals evaluated | 44354 |
| Signals vetoed | 43767 |

## Parameters used
- Risk/trade: 0.5%  |  SL: 1.5xATR  |  TP: 2.0R
- EMA 50/200, RSI14 (long>= 55.0, short<= 45.0)
- Range window 0.8-4.0 ATR, max extension 1.0 ATR
- Max open 2, daily stop 3.0%, one trade/pair/session=True

## By instrument
| Instrument | Trades | Win% | Net P&L |
|---|---|---|---|
| AUD_USD | 18 | 28% | $-86.56 |
| EUR_USD | 129 | 31% | $-436.70 |
| GBP_USD | 101 | 34% | $0.49 |
| USD_CAD | 12 | 8% | $-388.04 |
| USD_JPY | 327 | 28% | $-2,313.67 |
