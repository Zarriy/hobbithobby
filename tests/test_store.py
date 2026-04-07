"""
Tests for core/store.py and demo/store.py — SQLite persistence layer.
Uses temporary in-memory databases to avoid touching production DB.
"""

import sqlite3
import pytest
from unittest.mock import patch
from pathlib import Path
import tempfile
import os


class TestCoreStore:
    """Tests for core/store.py with a temp database."""

    @pytest.fixture(autouse=True)
    def tmp_db(self, tmp_path):
        db_path = tmp_path / "test_signals.db"
        with patch("core.store.DB_PATH", db_path):
            from core import store
            store.initialize_db()
            self.store = store
            yield

    def test_initialize_creates_tables(self):
        conn = self.store.get_connection()
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = {t[0] for t in tables}
        assert "candles" in table_names
        assert "signals" in table_names
        assert "fair_value_gaps" in table_names
        assert "order_blocks" in table_names
        assert "swing_points" in table_names
        conn.close()

    def test_upsert_and_fetch_candles(self):
        candles = [
            {"pair": "BTCUSDT", "timeframe": "1h", "timestamp": 1000,
             "open": 100, "high": 105, "low": 95, "close": 103,
             "volume": 5000, "open_interest": None, "funding_rate": None,
             "long_short_ratio": None, "taker_buy_sell_ratio": None},
            {"pair": "BTCUSDT", "timeframe": "1h", "timestamp": 4600,
             "open": 103, "high": 108, "low": 100, "close": 107,
             "volume": 6000, "open_interest": 1000000, "funding_rate": 0.0001,
             "long_short_ratio": 1.1, "taker_buy_sell_ratio": 0.55},
        ]
        count = self.store.upsert_candles(candles)
        assert count == 2

        fetched = self.store.fetch_candles("BTCUSDT", "1h", limit=10)
        assert len(fetched) == 2
        assert fetched[0]["timestamp"] == 1000  # ASC order
        assert fetched[1]["open_interest"] == 1000000

    def test_upsert_candles_empty(self):
        assert self.store.upsert_candles([]) == 0

    def test_upsert_replaces_on_conflict(self):
        candle = {"pair": "BTCUSDT", "timeframe": "1h", "timestamp": 1000,
                  "open": 100, "high": 105, "low": 95, "close": 103,
                  "volume": 5000, "open_interest": None, "funding_rate": None,
                  "long_short_ratio": None, "taker_buy_sell_ratio": None}
        self.store.upsert_candles([candle])
        candle["close"] = 110  # Update
        self.store.upsert_candles([candle])
        fetched = self.store.fetch_candles("BTCUSDT", "1h")
        assert len(fetched) == 1
        assert fetched[0]["close"] == 110

    def test_get_latest_timestamp(self):
        self.store.upsert_candles([
            {"pair": "BTCUSDT", "timeframe": "1h", "timestamp": 1000,
             "open": 100, "high": 101, "low": 99, "close": 100,
             "volume": 1000, "open_interest": None, "funding_rate": None,
             "long_short_ratio": None, "taker_buy_sell_ratio": None},
            {"pair": "BTCUSDT", "timeframe": "1h", "timestamp": 5000,
             "open": 100, "high": 101, "low": 99, "close": 100,
             "volume": 1000, "open_interest": None, "funding_rate": None,
             "long_short_ratio": None, "taker_buy_sell_ratio": None},
        ])
        assert self.store.get_latest_timestamp("BTCUSDT", "1h") == 5000
        assert self.store.get_latest_timestamp("ETHUSDT", "1h") is None

    def test_detect_gaps(self):
        tf_ms = 3_600_000
        candles = [
            {"pair": "BTCUSDT", "timeframe": "1h", "timestamp": tf_ms * 1,
             "open": 100, "high": 101, "low": 99, "close": 100,
             "volume": 1000, "open_interest": None, "funding_rate": None,
             "long_short_ratio": None, "taker_buy_sell_ratio": None},
            # Gap: missing timestamp at tf_ms * 2
            {"pair": "BTCUSDT", "timeframe": "1h", "timestamp": tf_ms * 3,
             "open": 100, "high": 101, "low": 99, "close": 100,
             "volume": 1000, "open_interest": None, "funding_rate": None,
             "long_short_ratio": None, "taker_buy_sell_ratio": None},
        ]
        self.store.upsert_candles(candles)
        gaps = self.store.detect_and_log_gaps("BTCUSDT", "1h")
        assert len(gaps) == 1

    def test_detect_no_gaps(self):
        tf_ms = 3_600_000
        candles = [
            {"pair": "BTCUSDT", "timeframe": "1h", "timestamp": tf_ms * i,
             "open": 100, "high": 101, "low": 99, "close": 100,
             "volume": 1000, "open_interest": None, "funding_rate": None,
             "long_short_ratio": None, "taker_buy_sell_ratio": None}
            for i in range(1, 6)
        ]
        self.store.upsert_candles(candles)
        gaps = self.store.detect_and_log_gaps("BTCUSDT", "1h")
        assert gaps == []

    def test_fvg_upsert_and_fetch(self):
        fvg = {"pair": "BTCUSDT", "timeframe": "1h", "detected_at": 1000,
               "type": "bullish", "upper_bound": 105, "lower_bound": 100,
               "status": "unfilled", "filled_at": None}
        self.store.upsert_fvg(fvg)
        active = self.store.fetch_active_fvgs("BTCUSDT", "1h")
        assert len(active) == 1
        assert active[0]["type"] == "bullish"

    def test_fvg_status_update(self):
        fvg = {"pair": "BTCUSDT", "timeframe": "1h", "detected_at": 1000,
               "type": "bullish", "upper_bound": 105, "lower_bound": 100,
               "status": "unfilled", "filled_at": None}
        self.store.upsert_fvg(fvg)
        self.store.update_fvg_status("BTCUSDT", "1h", 1000, "bullish", "filled", 2000)
        active = self.store.fetch_active_fvgs("BTCUSDT", "1h")
        assert len(active) == 0  # Filled FVGs excluded

    def test_signal_upsert_and_fetch(self):
        sig = {
            "pair": "BTCUSDT", "timeframe": "1h", "timestamp": 1000,
            "regime_state": "accumulation", "risk_color": "green",
            "confidence": 80, "trend_state": "uptrend", "price_zone": "discount",
            "nearest_bullish_fvg": None, "nearest_bearish_fvg": None,
            "nearest_bullish_ob": None, "nearest_bearish_ob": None,
            "equal_highs": None, "equal_lows": None,
            "volume_zscore": 2.0, "oi_change_percent": 0.02,
            "funding_rate": 0.0001, "taker_ratio": 0.55,
            "atr": 500, "vwap_deviation": -1.0, "metadata": "{}",
        }
        self.store.upsert_signal(sig)
        latest = self.store.fetch_latest_signal("BTCUSDT", "1h")
        assert latest is not None
        assert latest["regime_state"] == "accumulation"
        assert latest["confidence"] == 80

    def test_signal_history(self):
        for i in range(5):
            sig = {
                "pair": "BTCUSDT", "timeframe": "1h", "timestamp": 1000 + i * 1000,
                "regime_state": "accumulation", "risk_color": "green",
                "confidence": 70 + i, "trend_state": "uptrend", "price_zone": "discount",
                "nearest_bullish_fvg": None, "nearest_bearish_fvg": None,
                "nearest_bullish_ob": None, "nearest_bearish_ob": None,
                "equal_highs": None, "equal_lows": None,
                "volume_zscore": 2.0, "oi_change_percent": 0.0,
                "funding_rate": 0.0, "taker_ratio": 0.5,
                "atr": 100, "vwap_deviation": 0.0, "metadata": "{}",
            }
            self.store.upsert_signal(sig)
        history = self.store.fetch_signal_history("BTCUSDT", "1h", limit=3)
        assert len(history) == 3

    def test_wal_mode_enabled(self):
        conn = self.store.get_connection()
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"
        conn.close()


class TestDemoStore:
    @pytest.fixture(autouse=True)
    def tmp_db(self, tmp_path):
        db_path = tmp_path / "test_signals.db"
        with patch("core.store.DB_PATH", db_path):
            from core import store
            from demo import store as demo_store_mod
            store.initialize_db()
            demo_store_mod.initialize_demo_db()
            self.demo_store = demo_store_mod
            yield

    def test_insert_and_fetch_position(self):
        pos = {
            "pair": "BTCUSDT", "timeframe": "1h", "side": "long",
            "entry_price": 100, "stop_loss": 95, "tp1": 107.5,
            "tp2_target": None, "size_usd": 500, "risk_distance": 5,
            "size_multiplier": 1.0, "leverage": 10, "margin_usd": 50,
            "liquidation_price": 90.5, "entry_ts": 1000,
            "regime_at_entry": "accumulation", "risk_color_at_entry": "green",
            "entry_zone_type": "fvg", "confidence_at_entry": 80,
            "mode": "aggressive",
        }
        row_id = self.demo_store.insert_position(pos)
        assert row_id > 0

        open_pos = self.demo_store.fetch_open_positions(mode="aggressive")
        assert len(open_pos) == 1
        assert open_pos[0]["side"] == "long"

    def test_close_position(self):
        pos = {
            "pair": "BTCUSDT", "timeframe": "1h", "side": "long",
            "entry_price": 100, "stop_loss": 95, "tp1": 107.5,
            "tp2_target": None, "size_usd": 500, "risk_distance": 5,
            "size_multiplier": 1.0, "leverage": 10, "margin_usd": 50,
            "liquidation_price": 90.5, "entry_ts": 1000,
            "regime_at_entry": "accumulation", "risk_color_at_entry": "green",
            "entry_zone_type": "fvg", "confidence_at_entry": 80,
            "mode": "aggressive",
        }
        row_id = self.demo_store.insert_position(pos)
        self.demo_store.close_position(row_id, exit_ts=5000)

        open_pos = self.demo_store.fetch_open_positions(mode="aggressive")
        assert len(open_pos) == 0

    def test_mode_isolation(self):
        """Aggressive and conservative positions don't mix."""
        for mode in ("aggressive", "conservative"):
            pos = {
                "pair": "BTCUSDT", "timeframe": "1h", "side": "long",
                "entry_price": 100, "stop_loss": 95, "tp1": 107.5,
                "tp2_target": None, "size_usd": 500, "risk_distance": 5,
                "size_multiplier": 1.0, "leverage": 10, "margin_usd": 50,
                "liquidation_price": 90.5, "entry_ts": 1000,
                "regime_at_entry": "accumulation", "risk_color_at_entry": "green",
                "entry_zone_type": "fvg", "confidence_at_entry": 80,
                "mode": mode,
            }
            self.demo_store.insert_position(pos)

        agg = self.demo_store.fetch_open_positions(mode="aggressive")
        con = self.demo_store.fetch_open_positions(mode="conservative")
        assert len(agg) == 1
        assert len(con) == 1

    def test_equity_snapshot_upsert(self):
        self.demo_store.upsert_equity_snapshot(1000, 10000, 0, 0, "aggressive")
        self.demo_store.upsert_equity_snapshot(1000, 10500, 100, 1, "aggressive")  # Update same ts
        curve = self.demo_store.fetch_equity_curve(mode="aggressive")
        assert len(curve) == 1
        assert curve[0]["equity"] == 10500  # Updated

    def test_equity_mode_isolation(self):
        self.demo_store.upsert_equity_snapshot(1000, 10000, 0, 0, "aggressive")
        self.demo_store.upsert_equity_snapshot(1000, 9000, 0, 0, "conservative")

        agg_eq = self.demo_store.get_current_equity("aggressive")
        con_eq = self.demo_store.get_current_equity("conservative")
        assert agg_eq == 10000
        assert con_eq == 9000

    def test_get_current_equity_default(self):
        """No equity snapshots → returns INITIAL_CAPITAL."""
        eq = self.demo_store.get_current_equity("aggressive")
        assert eq == 10000  # config.INITIAL_CAPITAL

    def test_insert_trade(self):
        trade = {
            "position_id": 1, "pair": "BTCUSDT", "timeframe": "1h",
            "side": "long", "entry_price": 100, "exit_price": 107,
            "entry_ts": 1000, "exit_ts": 5000, "exit_reason": "tp1",
            "pnl_usd": 35, "pnl_percent": 0.07, "fee_usd": 0.5,
            "net_pnl_usd": 34.5, "size_usd": 500, "leverage": 10,
            "margin_usd": 50, "pnl_leveraged_pct": 0.7,
            "regime_at_entry": "accumulation", "confidence_at_entry": 80,
            "entry_zone_type": "fvg", "hold_hours": 1.1, "mode": "aggressive",
        }
        self.demo_store.insert_trade(trade)
        trades = self.demo_store.fetch_closed_trades(mode="aggressive")
        assert len(trades) == 1
        assert trades[0]["exit_reason"] == "tp1"
