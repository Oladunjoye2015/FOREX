"""Run the backtest over CSV history and emit a report + trade log + equity curve.

    python -m scripts.run_backtest --data data/history --nav 10000

Reads data/history/<INSTRUMENT>.csv (from fetch_oanda_history.py or
make_synthetic_data.py), runs app.backtest.Backtester with the live Settings,
and writes into data/backtest/:
    report.md      human-readable summary
    trades.csv     one row per closed trade
    equity.csv     time, nav

Every knob the live bot exposes via env vars also affects the backtest, so you
can A/B parameters:  RISK_PER_TRADE_PCT=0.25 TP_R_MULT=2.5 python -m scripts.run_backtest
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

from app.backtest import Backtester, BacktestConfig
from app.candle import Candle
from app.config import Settings


def load_csv(path: Path) -> list[Candle]:
    out = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            out.append(Candle(
                time=row["time"], o=float(row["open"]), h=float(row["high"]),
                l=float(row["low"]), c=float(row["close"]),
                volume=int(float(row["volume"])),
                complete=str(row["complete"]).strip().lower() in ("true", "1"),
            ))
    return out


def fmt_money(x: float) -> str:
    return f"${x:,.2f}"


def write_report(rep: dict, cfg: Settings, out_dir: Path, data_note: str):
    lines = []
    lines.append("# Backtest report\n")
    lines.append(data_note + "\n")
    lines.append("## Headline\n")
    pf = rep["profit_factor"]
    pf_s = "inf" if pf == float("inf") else f"{pf:.2f}"
    lines.append(
        f"| Metric | Value |\n|---|---|\n"
        f"| Starting NAV | {fmt_money(rep['starting_nav'])} |\n"
        f"| Ending NAV | {fmt_money(rep['ending_nav'])} |\n"
        f"| Net P&L | {fmt_money(rep['net_pnl'])} |\n"
        f"| Return | {rep['return_pct']:.2f}% |\n"
        f"| Max drawdown | {rep['max_drawdown_pct']:.2f}% |\n"
        f"| Trades | {rep['trades']} |\n"
        f"| Win rate | {rep['win_rate']:.1f}% |\n"
        f"| Profit factor | {pf_s} |\n"
        f"| Expectancy | {rep['expectancy_r']:.3f} R/trade |\n"
        f"| Avg win | {fmt_money(rep['avg_win'])} |\n"
        f"| Avg loss | {fmt_money(rep['avg_loss'])} |\n"
        f"| Signals evaluated | {rep['signals_evaluated']} |\n"
        f"| Signals vetoed | {rep['signals_vetoed']} |\n"
    )
    lines.append("\n## Parameters used\n")
    lines.append(
        f"- Risk/trade: {cfg.risk_per_trade_pct}%  |  SL: {cfg.sl_atr_mult}xATR  |  TP: {cfg.tp_r_mult}R\n"
        f"- EMA {cfg.ema_fast}/{cfg.ema_slow}, RSI{cfg.rsi_period} (long>= {cfg.rsi_long_min}, short<= {cfg.rsi_short_max})\n"
        f"- Range window {cfg.range_atr_min}-{cfg.range_atr_max} ATR, max extension {cfg.max_extension_atr} ATR\n"
        f"- Max open {cfg.max_open_trades}, daily stop {cfg.max_daily_loss_pct}%, one trade/pair/session={cfg.one_trade_per_session}\n"
        f"- Instruments: {','.join(cfg.instruments)}  |  Enabled sessions: {','.join(cfg.enabled_sessions)}\n"
        f"- Disabled weekdays: {','.join(cfg.disabled_weekdays) or 'none'}  |  "
        f"Disabled UTC hours: {','.join(str(h) for h in cfg.disabled_utc_hours) or 'none'}\n"
    )
    # Per-instrument breakdown.
    trades = rep["trade_list"]
    by_inst: dict[str, list] = {}
    for t in trades:
        by_inst.setdefault(t.instrument, []).append(t)
    lines.append("\n## By instrument\n")
    lines.append("| Instrument | Trades | Win% | Net P&L |\n|---|---|---|---|\n")
    for inst, ts in sorted(by_inst.items()):
        w = sum(1 for t in ts if t.pnl_usd > 0)
        net = sum(t.pnl_usd for t in ts)
        lines.append(f"| {inst} | {len(ts)} | {w/len(ts)*100:.0f}% | {fmt_money(net)} |\n")

    (out_dir / "report.md").write_text("".join(lines))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/history")
    ap.add_argument("--out", default="data/backtest")
    ap.add_argument("--nav", type=float, default=10_000.0)
    args = ap.parse_args()

    cfg = Settings()
    data_dir = Path(args.data)
    files = sorted(data_dir.glob("*.csv"))
    if not files:
        raise SystemExit(f"No CSVs in {data_dir}. Run make_synthetic_data.py or fetch_oanda_history.py first.")

    data = {}
    for p in files:
        inst = p.stem
        if inst not in cfg.instruments:
            continue
        data[inst] = load_csv(p)
    if not data:
        raise SystemExit(
            f"No CSVs in {data_dir} match INSTRUMENTS={','.join(cfg.instruments)}."
        )

    bt = Backtester(cfg, BacktestConfig(starting_nav=args.nav))
    rep = bt.run(data)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # trades.csv
    with open(out_dir / "trades.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["instrument", "session", "direction", "units", "entry_time",
                    "entry", "stop_loss", "take_profit", "exit_time", "exit",
                    "outcome", "pnl_usd", "r_multiple", "nav_after"])
        for t in rep["trade_list"]:
            w.writerow([t.instrument, t.session, t.direction, t.units,
                        t.entry_time, t.entry, t.stop_loss, t.take_profit,
                        t.exit_time, t.exit, t.outcome, round(t.pnl_usd, 2),
                        round(t.r_multiple, 3), round(t.nav_after, 2)])

    # equity.csv
    with open(out_dir / "equity.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time", "nav"])
        for tm, nav in rep["equity_curve"]:
            w.writerow([tm, round(nav, 2)])

    note = ("> Data source: files in `%s`. If these are synthetic "
            "(make_synthetic_data.py), the numbers below only validate the "
            "engine, not real edge." % args.data)
    write_report(rep, cfg, out_dir, note)

    # Console summary
    pf = rep["profit_factor"]
    pf_s = "inf" if pf == float("inf") else f"{pf:.2f}"
    print("=" * 52)
    print(f"  Trades {rep['trades']:>4}   Win% {rep['win_rate']:5.1f}   PF {pf_s}")
    print(f"  Net    {fmt_money(rep['net_pnl']):>12}   Return {rep['return_pct']:6.2f}%")
    print(f"  MaxDD  {rep['max_drawdown_pct']:5.2f}%   Expectancy {rep['expectancy_r']:+.3f} R")
    print(f"  Signals evaluated {rep['signals_evaluated']}, vetoed {rep['signals_vetoed']}")
    print("=" * 52)
    print(f"Wrote report.md, trades.csv, equity.csv -> {out_dir}")


if __name__ == "__main__":
    main()
