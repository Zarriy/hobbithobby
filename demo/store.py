"""
Demo trading persistence layer.
Writes to the same signals.db file as core/store.py (WAL mode safe).
"""

import logging
import sqlite3
from typing import Optional

import config
from core.store import DB_PATH, get_connection

logger = logging.getLogger(__name__)

CREATE_DEMO_POSITIONS = """
CREATE TABLE IF NOT EXISTS demo_positions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    pair                TEXT    NOT NULL,
    timeframe           TEXT    NOT NULL,
    side                TEXT    NOT NULL,
    entry_price         REAL    NOT NULL,
    stop_loss           REAL    NOT NULL,
    tp1                 REAL    NOT NULL,
    tp2_target          REAL,
    size_usd            REAL    NOT NULL,
    risk_distance       REAL    NOT NULL,
    size_multiplier     REAL    NOT NULL,
    leverage            REAL    NOT NULL DEFAULT 10.0,
    margin_usd          REAL    NOT NULL DEFAULT 0.0,
    liquidation_price   REAL,
    entry_ts            INTEGER NOT NULL,
    exit_ts             INTEGER,
    regime_at_entry     TEXT    NOT NULL,
    risk_color_at_entry TEXT,
    entry_zone_type     TEXT,
    confidence_at_entry INTEGER NOT NULL DEFAULT 0,
    tp1_hit             INTEGER NOT NULL DEFAULT 0,
    partial_exit_pnl    REAL    NOT NULL DEFAULT 0.0,
    status              TEXT    NOT NULL DEFAULT 'open'
);
"""

CREATE_DEMO_TRADES = """
CREATE TABLE IF NOT EXISTS demo_trades (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id         INTEGER NOT NULL,
    pair                TEXT    NOT NULL,
    timeframe           TEXT    NOT NULL,
    side                TEXT    NOT NULL,
    entry_price         REAL    NOT NULL,
    exit_price          REAL    NOT NULL,
    entry_ts            INTEGER NOT NULL,
    exit_ts             INTEGER NOT NULL,
    exit_reason         TEXT    NOT NULL,
    pnl_usd             REAL    NOT NULL,
    pnl_percent         REAL    NOT NULL,
    fee_usd             REAL    NOT NULL,
    net_pnl_usd         REAL    NOT NULL,
    size_usd            REAL    NOT NULL,
    leverage            REAL    NOT NULL DEFAULT 10.0,
    margin_usd          REAL    NOT NULL DEFAULT 0.0,
    pnl_leveraged_pct   REAL    NOT NULL DEFAULT 0.0,
    regime_at_entry     TEXT    NOT NULL,
    confidence_at_entry INTEGER NOT NULL DEFAULT 0,
    entry_zone_type     TEXT,
    hold_hours          REAL    NOT NULL DEFAULT 0.0
);
"""

CREATE_DEMO_EQUITY = """
CREATE TABLE IF NOT EXISTS demo_equity (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   INTEGER NOT NULL UNIQUE,
    equity      REAL    NOT NULL,
    open_pnl    REAL    NOT NULL DEFAULT 0.0,
    open_count  INTEGER NOT NULL DEFAULT 0
);
"""


def initialize_demo_db() -> None:
    with get_connection() as conn:
        conn.executescript(
            CREATE_DEMO_POSITIONS + CREATE_DEMO_TRADES + CREATE_DEMO_EQUITY
        )
    logger.info("Demo DB tables initialized.")


def insert_position(pos: dict) -> int:
    """Insert a new open position. Returns the new row id."""
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO demo_positions
            (pair, timeframe, side, entry_price, stop_loss, tp1, tp2_target,
             size_usd, risk_distance, size_multiplier, leverage, margin_usd,
             liquidation_price, entry_ts, regime_at_entry, risk_color_at_entry,
             entry_zone_type, confidence_at_entry, status)
            VALUES (:pair, :timeframe, :side, :entry_price, :stop_loss, :tp1, :tp2_target,
                    :size_usd, :risk_distance, :size_multiplier, :leverage, :margin_usd,
                    :liquidation_price, :entry_ts, :regime_at_entry, :risk_color_at_entry,
                    :entry_zone_type, :confidence_at_entry, 'open')
            """,
            pos,
        )
        return cur.lastrowid


def update_position(pos_id: int, updates: dict) -> None:
    """Update specific fields of an open position (TP1 partial close, stop move, etc.)."""
    if not updates:
        return
    set_clause = ", ".join(f"{k}=:{k}" for k in updates)
    updates["_id"] = pos_id
    with get_connection() as conn:
        conn.execute(
            f"UPDATE demo_positions SET {set_clause} WHERE id=:_id",
            updates,
        )


def close_position(pos_id: int, exit_ts: int) -> None:
    """Mark a position as closed."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE demo_positions SET status='closed', exit_ts=? WHERE id=?",
            (exit_ts, pos_id),
        )


def fetch_open_positions() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM demo_positions WHERE status='open' ORDER BY entry_ts ASC"
        ).fetchall()
    return [dict(r) for r in rows]


def insert_trade(trade: dict) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO demo_trades
            (position_id, pair, timeframe, side, entry_price, exit_price,
             entry_ts, exit_ts, exit_reason, pnl_usd, pnl_percent, fee_usd,
             net_pnl_usd, size_usd, leverage, margin_usd, pnl_leveraged_pct,
             regime_at_entry, confidence_at_entry, entry_zone_type, hold_hours)
            VALUES
            (:position_id, :pair, :timeframe, :side, :entry_price, :exit_price,
             :entry_ts, :exit_ts, :exit_reason, :pnl_usd, :pnl_percent, :fee_usd,
             :net_pnl_usd, :size_usd, :leverage, :margin_usd, :pnl_leveraged_pct,
             :regime_at_entry, :confidence_at_entry, :entry_zone_type, :hold_hours)
            """,
            trade,
        )


def fetch_closed_trades(limit: int = 50) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM demo_trades ORDER BY exit_ts DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def fetch_all_closed_trades() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM demo_trades ORDER BY exit_ts ASC"
        ).fetchall()
    return [dict(r) for r in rows]


def upsert_equity_snapshot(
    ts: int, equity: float, open_pnl: float, open_count: int
) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO demo_equity (timestamp, equity, open_pnl, open_count)
            VALUES (?, ?, ?, ?)
            """,
            (ts, equity, open_pnl, open_count),
        )


def fetch_equity_curve(limit: int = 500) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT timestamp, equity, open_pnl, open_count FROM demo_equity ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


def get_current_equity() -> float:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT equity FROM demo_equity ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
    return float(row[0]) if row else float(config.INITIAL_CAPITAL)
