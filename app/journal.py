"""SQLite trade journal + equity history. Attach a Railway volume at DATA_DIR
to persist across deploys; everything is also recoverable from OANDA itself."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone

_SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT, instrument TEXT, session TEXT, direction TEXT,
    entry REAL, stop_loss REAL, take_profit REAL,
    approved INTEGER, executed INTEGER, veto_reason TEXT, checks TEXT
);
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT, instrument TEXT, session TEXT, direction TEXT,
    units INTEGER, entry REAL, stop_loss REAL, take_profit REAL,
    oanda_order_id TEXT, oanda_trade_id TEXT, raw TEXT
);
CREATE TABLE IF NOT EXISTS equity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT, balance REAL, nav REAL, unrealized REAL, open_trades INTEGER
);
"""


class Journal:
    def __init__(self, data_dir: str):
        os.makedirs(data_dir, exist_ok=True)
        self._path = os.path.join(data_dir, "journal.db")
        self._lock = threading.Lock()
        with self._conn() as c:
            c.executescript(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def log_signal(self, sig, executed: bool, veto_reason: str = ""):
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT INTO signals (ts,instrument,session,direction,entry,"
                "stop_loss,take_profit,approved,executed,veto_reason,checks) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (self._now(), sig.instrument, sig.session, sig.direction,
                 sig.entry, sig.stop_loss, sig.take_profit,
                 int(sig.approved), int(executed), veto_reason,
                 json.dumps(sig.checks)),
            )

    def log_trade(self, sig, units: int, order_resp: dict):
        fill = order_resp.get("orderFillTransaction", {})
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT INTO trades (ts,instrument,session,direction,units,entry,"
                "stop_loss,take_profit,oanda_order_id,oanda_trade_id,raw) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (self._now(), sig.instrument, sig.session, sig.direction, units,
                 float(fill.get("price", sig.entry)), sig.stop_loss, sig.take_profit,
                 str(fill.get("orderID", "")),
                 str(fill.get("tradeOpened", {}).get("tradeID", "")),
                 json.dumps(order_resp)[:4000]),
            )

    def log_equity(self, balance: float, nav: float, unrealized: float, open_trades: int):
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT INTO equity (ts,balance,nav,unrealized,open_trades) VALUES (?,?,?,?,?)",
                (self._now(), balance, nav, unrealized, open_trades),
            )

    def recent(self, table: str, limit: int = 100) -> list[dict]:
        assert table in ("signals", "trades", "equity")
        with self._lock, self._conn() as c:
            rows = c.execute(
                f"SELECT * FROM {table} ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]
