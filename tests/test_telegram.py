"""
Tests for alerts/telegram.py — message formatting and sending.
"""

import pytest
from unittest.mock import patch, AsyncMock
from alerts.telegram import (
    build_trade_entry_alert, build_trade_exit_alert,
    build_daily_summary, send_message, _format_price,
)


class TestFormatPrice:
    def test_large_price(self):
        assert _format_price(65432) == "$65,432"

    def test_medium_price(self):
        assert _format_price(123.45) == "$123.45"

    def test_small_price(self):
        assert _format_price(0.1234) == "$0.1234"

    def test_exact_100(self):
        assert _format_price(100.0) == "$100.00"

    def test_exact_10000(self):
        assert _format_price(10000) == "$10,000"


class TestBuildTradeEntryAlert:
    def test_long_entry(self):
        msg = build_trade_entry_alert(
            pair="BTCUSDT", timeframe="1h", side="long",
            entry_price=60000, stop_loss=59000, tp1=61500,
            confidence=85, regime="accumulation", risk_color="green",
            mode="aggressive", leverage=10, size_usd=5000,
        )
        assert "LONG" in msg
        assert "BTC/USDT" in msg
        assert "AGGRESSIVE" in msg
        assert "$60,000" in msg
        assert "1.5R" in msg
        assert "85/100" in msg

    def test_short_entry(self):
        msg = build_trade_entry_alert(
            pair="ETHUSDT", timeframe="4h", side="short",
            entry_price=3500, stop_loss=3600, tp1=3350,
            confidence=90, regime="distribution", risk_color="green",
            mode="conservative", leverage=10, size_usd=2000,
        )
        assert "SHORT" in msg
        assert "ETH/USDT" in msg
        assert "CONSERVATIVE" in msg

    def test_with_tp2(self):
        msg = build_trade_entry_alert(
            pair="BTCUSDT", timeframe="1h", side="long",
            entry_price=60000, stop_loss=59000, tp1=61500,
            confidence=85, regime="accumulation", risk_color="green",
            mode="aggressive", leverage=10, size_usd=5000, tp2=63000,
        )
        assert "TP2" in msg
        assert "3R" in msg

    def test_risk_percent_in_message(self):
        msg = build_trade_entry_alert(
            pair="BTCUSDT", timeframe="1h", side="long",
            entry_price=100, stop_loss=95, tp1=107.5,
            confidence=80, regime="accumulation", risk_color="green",
            mode="aggressive", leverage=10, size_usd=1000,
        )
        assert "5.00% risk" in msg


class TestBuildTradeExitAlert:
    def test_winning_exit(self):
        msg = build_trade_exit_alert(
            pair="BTCUSDT", side="long", entry_price=60000,
            exit_price=61500, exit_reason="tp1",
            net_pnl_usd=150, pnl_pct=0.025,
            hold_hours=8.5, mode="aggressive", equity=10150,
        )
        assert "CLOSED" in msg
        assert "TP1" in msg
        assert "+" in msg
        assert "8.5h" in msg

    def test_losing_exit(self):
        msg = build_trade_exit_alert(
            pair="BTCUSDT", side="long", entry_price=60000,
            exit_price=59000, exit_reason="stop_loss",
            net_pnl_usd=-100, pnl_pct=-0.0167,
            hold_hours=2.0, mode="conservative", equity=9900,
        )
        assert "Stop Loss" in msg
        assert "-" in msg

    def test_all_exit_reasons(self):
        reasons = ["tp1", "tp2", "stop_loss", "regime_red_exit", "time_exit"]
        for reason in reasons:
            msg = build_trade_exit_alert(
                pair="BTCUSDT", side="long", entry_price=100,
                exit_price=105, exit_reason=reason,
                net_pnl_usd=50, pnl_pct=0.05,
                hold_hours=1.0, mode="aggressive", equity=10050,
            )
            assert len(msg) > 0  # Should not crash


class TestBuildDailySummary:
    def test_basic_summary(self):
        pair_data = [
            {
                "pair": "BTCUSDT", "price": 65000, "regime": "accumulation",
                "risk_color": "green", "confidence": 82, "trend": "uptrend",
                "action_bias": "long_bias", "oi_change": 0.02,
                "vol_zscore": 2.1, "funding_rate": 0.0001, "macro_regime": "markup",
            }
        ]
        msg = build_daily_summary(
            pair_data, demo_aggressive_equity=10500,
            demo_conservative_equity=10200,
            aggressive_open=1, conservative_open=0,
        )
        assert "DAILY BRIEFING" in msg
        assert "BTC/USDT" in msg
        assert "Aggressive" in msg
        assert "Conservative" in msg

    def test_multiple_pairs(self):
        pair_data = [
            {"pair": "BTCUSDT", "price": 65000, "regime": "accumulation",
             "risk_color": "green", "confidence": 82, "trend": "uptrend",
             "action_bias": "long_bias", "oi_change": 0.02,
             "vol_zscore": 2.1, "funding_rate": 0.0001, "macro_regime": "markup"},
            {"pair": "ETHUSDT", "price": 3500, "regime": "distribution",
             "risk_color": "yellow", "confidence": 65, "trend": "downtrend",
             "action_bias": "short_bias", "oi_change": -0.01,
             "vol_zscore": 1.5, "funding_rate": -0.0002, "macro_regime": "markdown"},
        ]
        msg = build_daily_summary(pair_data, 10500, 10200, 1, 0)
        assert "BTC/USDT" in msg
        assert "ETH/USDT" in msg


class TestSendMessage:
    @pytest.mark.asyncio
    async def test_no_token_skips(self):
        with patch("alerts.telegram.config") as mock_config:
            mock_config.TELEGRAM_BOT_TOKEN = ""
            mock_config.TELEGRAM_CHAT_ID = "123"
            result = await send_message("test")
            assert result is False

    @pytest.mark.asyncio
    async def test_no_chat_id_skips(self):
        with patch("alerts.telegram.config") as mock_config:
            mock_config.TELEGRAM_BOT_TOKEN = "token"
            mock_config.TELEGRAM_CHAT_ID = ""
            result = await send_message("test")
            assert result is False

    @pytest.mark.asyncio
    async def test_network_error_returns_false(self):
        with patch("alerts.telegram.config") as mock_config:
            mock_config.TELEGRAM_BOT_TOKEN = "fake_token"
            mock_config.TELEGRAM_CHAT_ID = "fake_chat"
            with patch("alerts.telegram.httpx.AsyncClient") as mock_client:
                mock_instance = AsyncMock()
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock(return_value=False)
                mock_instance.post.side_effect = Exception("Network error")
                mock_client.return_value = mock_instance
                result = await send_message("test")
                assert result is False
