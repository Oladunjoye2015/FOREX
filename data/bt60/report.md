# Backtest report
> Data source: files in `data/hist60`. If these are synthetic (make_synthetic_data.py), the numbers below only validate the engine, not real edge.
## Headline
| Metric | Value |
|---|---|
| Starting NAV | $10,000.00 |
| Ending NAV | $9,221.10 |
| Net P&L | $-778.90 |
| Return | -7.79% |
| Max drawdown | 10.52% |
| Trades | 115 |
| Win rate | 28.7% |
| Profit factor | 0.80 |
| Expectancy | -0.137 R/trade |
| Avg win | $94.27 |
| Avg loss | $-47.44 |
| Signals evaluated | 2230 |
| Signals vetoed | 2115 |

## Parameters used
- Risk/trade: 0.5%  |  SL: 1.5xATR  |  TP: 2.0R
- EMA 50/200, RSI14 (long>= 55.0, short<= 45.0)
- Range window 0.8-4.0 ATR, max extension 1.0 ATR
- Max open 2, daily stop 3.0%, one trade/pair/session=True

## By instrument
| Instrument | Trades | Win% | Net P&L |
|---|---|---|---|
| AUD_USD | 15 | 27% | $-140.03 |
| EUR_USD | 32 | 34% | $24.67 |
| GBP_USD | 38 | 29% | $-244.10 |
| USD_CAD | 3 | 33% | $-0.30 |
| USD_JPY | 27 | 22% | $-419.13 |
