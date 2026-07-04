# Backtest report
> Data source: files in `data/history`. If these are synthetic (make_synthetic_data.py), the numbers below only validate the engine, not real edge.
## Headline
| Metric | Value |
|---|---|
| Starting NAV | $10,000.00 |
| Ending NAV | $10,073.29 |
| Net P&L | $73.29 |
| Return | 0.73% |
| Max drawdown | 1.74% |
| Trades | 30 |
| Win rate | 36.7% |
| Profit factor | 1.15 |
| Expectancy | 0.100 R/trade |
| Avg win | $50.28 |
| Avg loss | $-25.25 |
| Signals evaluated | 8305 |
| Signals vetoed | 8275 |

## Parameters used
- Risk/trade: 0.25%  |  SL: 1.5xATR  |  TP: 2.0R
- EMA 50/200, RSI14 (long>= 55.0, short<= 45.0)
- Range window 0.8-4.0 ATR, max extension 1.0 ATR
- Max open 1, daily stop 1.0%, one trade/pair/session=True
- Instruments: EUR_USD,GBP_USD  |  Enabled sessions: LONDON
- Disabled weekdays: FRI  |  Disabled UTC hours: none

## By instrument
| Instrument | Trades | Win% | Net P&L |
|---|---|---|---|
| EUR_USD | 20 | 35% | $23.68 |
| GBP_USD | 10 | 40% | $49.62 |
