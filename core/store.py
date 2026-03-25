"""
SQLite persistence layer with WAL mode, atomic writes, and gap detection.
"""

import sqlite3
import logging
import json
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / "db" / "signals.db"

CREATE_CANDLES = """
CREATE TABLE IF NOT EXISTS candles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pair TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    timestamp INTEGER NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL NOT NULL,
    open_interest REAL,
    funding_rate REAL,
    long_short_ratio REAL,
    taker_buy_sell_ratio REAL,
    UNIQUE(pair, timeframe, timestamp)
);
"""

CREATE_SIGNALS = """
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pair TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    timestamp INTEGER NOT NULL,
    regime_state TEXT NOT NULL,
    risk_color TEXT NOT NULL,
    confidence INTEGER NOT NULL,
    trend_state TEXT,
    price_zone TEXT,
    nearest_bullish_fvg TEXT,
    nearest_bearish_fvg TEXT,
    nearest_bullish_ob TEXT,
    nearest_bearish_ob TEXT,
    equal_highs TEXT,
    equal_lows TEXT,
    volume_zscore REAL,
    oi_change_percent REAL,
    funding_rate REAL,
    taker_ratio REAL,
    atr REAL,
    vwap_deviation REAL,
    metadata TEXT,
    UNIQUE(pair, timeframe, timestamp)
);
"""

CREATE_FVGS = """
CREATE TABLE IF NOT EXISTS fair_value_gaps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pair TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    detected_at INTEGER NOT NULL,
    type TEXT NOT NULL,
    upper_bound REAL NOT NULL,
    lower_bound REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'unfilled',
    filled_at INTEGER,
    UNIQUE(pair, timeframe, detected_at, type, upper_bound)
);
"""

CREATE_ORDER_BLOCKS = """
CREATE TABLE IF NOT EXISTS order_blocks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pair TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    detected_at INTEGER NOT NULL,
    type TEXT NOT NULL,
    upper_bound REAL NOT NULL,
    lower_bound REAL NOT NULL,
    fvg_overlap INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active',
    mitigated_at INTEGER,
    UNIQUE(pair, timeframe, detected_at, type, upper_bound)
);
"""

CREATE_SWING_POINTS = """
CREATE TABLE IF NOT EXISTS swing_points (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pair TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    timestamp INTEGER NOT NULL,
    type TEXT NOT NULL,
    price REAL NOT NULL,
    UNIQUE(pair, timeframe, timestamp, type)
);
"""

TIMEFRAME_MS = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def initialize_db() -> None:
    with get_connection() as conn:
        conn.executescript(
            CREATE_CANDLES
            + CREATE_SIGNALS
            + CREATE_FVGS
            + CREATE_ORDER_BLOCKS
            + CREATE_SWING_POINTS
        )
        # Integrity check
        result = conn.execute("PRAGMA integrity_check").fetchone()
        if result[0] != "ok":
            raise RuntimeError(f"SQLite integrity check failed: {result[0]}")
    logger.info("Database initialized at %s", DB_PATH)


def get_latest_timestamp(pair: str, timeframe: str) -> Optional[int]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT MAX(timestamp) FROM candles WHERE pair=? AND timeframe=?",
            (pair, timeframe),
        ).fetchone()
        return row[0] if row and row[0] is not None else None


def upsert_candles(candles: list[dict]) -> int:
    """Insert or replace candles. Returns count written."""
    if not candles:
        return 0
    with get_connection() as conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO candles
            (pair, timeframe, timestamp, open, high, low, close, volume,
             open_interest, funding_rate, long_short_ratio, taker_buy_sell_ratio)
            VALUES (:pair, :timeframe, :timestamp, :open, :high, :low, :close, :volume,
                    :open_interest, :funding_rate, :long_short_ratio, :taker_buy_sell_ratio)
            """,
            candles,
        )
    return len(candles)


def detect_and_log_gaps(pair: str, timeframe: str) -> list[tuple[int, int]]:
    """
    Return list of (gap_start_ms, gap_end_ms) for missing candles.
    Logs each gap found.
    """
    tf_ms = TIMEFRAME_MS.get(timeframe)
    if not tf_ms:
        return []

    with get_connection() as conn:
        rows = conn.execute(
            "SELECT timestamp FROM candles WHERE pair=? AND timeframe=? ORDER BY timestamp",
            (pair, timeframe),
        ).fetchall()

    if len(rows) < 2:
        return []

    timestamps = [r[0] for r in rows]
    gaps = []
    for i in range(1, len(timestamps)):
        expected = timestamps[i - 1] + tf_ms
        actual = timestamps[i]
        if actual > expected:
            gaps.append((expected, actual - tf_ms))
            logger.warning(
                "Gap detected in %s %s: %d -> %d (%d missing candles)",
                pair,
                timeframe,
                timestamps[i - 1],
                timestamps[i],
                (actual - expected) // tf_ms,
            )
    return gaps


def fetch_candles(
    pair: str,
    timeframe: str,
    limit: int = 500,
    since_ts: Optional[int] = None,
) -> list[dict]:
    with get_connection() as conn:
        if since_ts is not None:
            rows = conn.execute(
                """SELECT * FROM candles WHERE pair=? AND timeframe=? AND timestamp>=?
                   ORDER BY timestamp DESC LIMIT ?""",
                (pair, timeframe, since_ts, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM candles WHERE pair=? AND timeframe=?
                   ORDER BY timestamp DESC LIMIT ?""",
                (pair, timeframe, limit),
            ).fetchall()
    result = [dict(r) for r in reversed(rows)]
    return result


def upsert_fvg(fvg: dict) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO fair_value_gaps
            (pair, timeframe, detected_at, type, upper_bound, lower_bound, status, filled_at)
            VALUES (:pair, :timeframe, :detected_at, :type, :upper_bound, :lower_bound, :status, :filled_at)
            """,
            fvg,
        )


def update_fvg_status(pair: str, timeframe: str, detected_at: int, fvg_type: str, status: str, filled_at: Optional[int] = None) -> None:
    with get_connection() as conn:
        conn.execute(
            """UPDATE fair_value_gaps SET status=?, filled_at=?
               WHERE pair=? AND timeframe=? AND detected_at=? AND type=?""",
            (status, filled_at, pair, timeframe, detected_at, fvg_type),
        )


def fetch_active_fvgs(pair: str, timeframe: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT * FROM fair_value_gaps
               WHERE pair=? AND timeframe=? AND status != 'filled'
               ORDER BY detected_at DESC""",
            (pair, timeframe),
        ).fetchall()
    return [dict(r) for r in rows]


def upsert_order_block(ob: dict) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO order_blocks
            (pair, timeframe, detected_at, type, upper_bound, lower_bound, fvg_overlap, status, mitigated_at)
            VALUES (:pair, :timeframe, :detected_at, :type, :upper_bound, :lower_bound, :fvg_overlap, :status, :mitigated_at)
            """,
            ob,
        )


def update_ob_status(pair: str, timeframe: str, detected_at: int, ob_type: str, status: str, mitigated_at: Optional[int] = None) -> None:
    with get_connection() as conn:
        conn.execute(
            """UPDATE order_blocks SET status=?, mitigated_at=?
               WHERE pair=? AND timeframe=? AND detected_at=? AND type=?""",
            (status, mitigated_at, pair, timeframe, detected_at, ob_type),
        )


def fetch_active_obs(pair: str, timeframe: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT * FROM order_blocks
               WHERE pair=? AND timeframe=? AND status='active'
               ORDER BY detected_at DESC""",
            (pair, timeframe),
        ).fetchall()
    return [dict(r) for r in rows]


def upsert_signal(signal: dict) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO signals
            (pair, timeframe, timestamp, regime_state, risk_color, confidence,
             trend_state, price_zone, nearest_bullish_fvg, nearest_bearish_fvg,
             nearest_bullish_ob, nearest_bearish_ob, equal_highs, equal_lows,
             volume_zscore, oi_change_percent, funding_rate, taker_ratio, atr,
             vwap_deviation, metadata)
            VALUES (:pair, :timeframe, :timestamp, :regime_state, :risk_color, :confidence,
                    :trend_state, :price_zone, :nearest_bullish_fvg, :nearest_bearish_fvg,
                    :nearest_bullish_ob, :nearest_bearish_ob, :equal_highs, :equal_lows,
                    :volume_zscore, :oi_change_percent, :funding_rate, :taker_ratio, :atr,
                    :vwap_deviation, :metadata)
            """,
            signal,
        )


def fetch_latest_signal(pair: str, timeframe: str) -> Optional[dict]:
    with get_connection() as conn:
        row = conn.execute(
            """SELECT * FROM signals WHERE pair=? AND timeframe=?
               ORDER BY timestamp DESC LIMIT 1""",
            (pair, timeframe),
        ).fetchone()
    return dict(row) if row else None


def fetch_signal_history(pair: str, timeframe: str, limit: int = 100) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT * FROM signals WHERE pair=? AND timeframe=?
               ORDER BY timestamp DESC LIMIT ?""",
            (pair, timeframe, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def upsert_swing_point(sp: dict) -> None:
    with get_connection() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO swing_points (pair, timeframe, timestamp, type, price)
               VALUES (:pair, :timeframe, :timestamp, :type, :price)""",
            sp,
        )


def fetch_swing_points(pair: str, timeframe: str, limit: int = 100) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT * FROM swing_points WHERE pair=? AND timeframe=?
               ORDER BY timestamp DESC LIMIT ?""",
            (pair, timeframe, limit),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]
