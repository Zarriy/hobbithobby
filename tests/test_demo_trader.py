"""
Tests for demo/trader.py — DemoTrader paper trading engine.
Tests mark-to-market, liquidation prices, position sizing, TP1 partial exits.
Uses mocked DB to avoid touching real database.
"""

import asyncio
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from tests.conftest import make_candle

from demo.trader import DemoTrader, set_live_state_ref
from engine.classifier import SignalOutput
from engine.fvg import FVG
from engine.orderblocks import OrderBlock


class TestMarkToMarket:
    def setup_method(self):
        with patch("demo.trader.demo_store"):
            self.trader = DemoTrader(initial_capital=10000, leverage=10, mode="aggressive")

    def test_long_profit(self):
        pos = {"entry_price": 100, "size_usd": 1000, "side": "long"}
        mtm = self.trader.mark_to_market(pos, 105)
        assert mtm == pytest.approx(50.0)  # 5% * 1000

    def test_long_loss(self):
        pos = {"entry_price": 100, "size_usd": 1000, "side": "long"}
        mtm = self.trader.mark_to_market(pos, 95)
        assert mtm == pytest.approx(-50.0)

    def test_short_profit(self):
        pos = {"entry_price": 100, "size_usd": 1000, "side": "short"}
        mtm = self.trader.mark_to_market(pos, 95)
        assert mtm == pytest.approx(50.0)

    def test_short_loss(self):
        pos = {"entry_price": 100, "size_usd": 1000, "side": "short"}
        mtm = self.trader.mark_to_market(pos, 105)
        assert mtm == pytest.approx(-50.0)

    def test_zero_entry_price(self):
        pos = {"entry_price": 0, "size_usd": 1000, "side": "long"}
        mtm = self.trader.mark_to_market(pos, 100)
        assert mtm == 0.0

    def test_same_price_zero_pnl(self):
        pos = {"entry_price": 100, "size_usd": 1000, "side": "long"}
        assert self.trader.mark_to_market(pos, 100) == pytest.approx(0.0)


class TestLiquidationPrice:
    def setup_method(self):
        with patch("demo.trader.demo_store"):
            self.trader = DemoTrader(initial_capital=10000, leverage=10, mode="aggressive")

    def test_long_liquidation(self):
        # liq = entry * (1 - 1/lev + mm) = 100 * (1 - 0.1 + 0.005) = 90.5
        liq = self.trader._liquidation_price(100, "long", 10)
        assert liq == pytest.approx(90.5)

    def test_short_liquidation(self):
        # liq = entry * (1 + 1/lev - mm) = 100 * (1 + 0.1 - 0.005) = 109.5
        liq = self.trader._liquidation_price(100, "short", 10)
        assert liq == pytest.approx(109.5)

    def test_high_leverage_tighter_liq(self):
        liq_100x = self.trader._liquidation_price(100, "long", 100)
        liq_10x = self.trader._liquidation_price(100, "long", 10)
        assert liq_100x > liq_10x  # Higher leverage = closer liquidation


class TestPortfolioSummary:
    def setup_method(self):
        with patch("demo.trader.demo_store"):
            self.trader = DemoTrader(initial_capital=10000, leverage=10, mode="aggressive")

    def test_empty_portfolio(self):
        summary = self.trader.get_portfolio_summary({})
        assert summary["total_margin_used"] == 0
        assert summary["total_unrealized_pnl_usd"] == 0
        assert summary["current_equity"] == 10000
        assert summary["available_margin"] == 10000

    def test_with_positions(self):
        self.trader._open_positions = [
            {
                "pair": "BTCUSDT", "side": "long", "entry_price": 100,
                "size_usd": 500, "margin_usd": 50, "leverage": 10,
            }
        ]
        live_state = {"BTCUSDT": {"last_price": 105}}
        summary = self.trader.get_portfolio_summary(live_state)
        assert summary["total_margin_used"] == 50
        assert summary["total_notional_exposure"] == 500
        assert summary["total_unrealized_pnl_usd"] > 0
        assert summary["effective_leverage"] > 0


class TestPositionsWithMTM:
    def setup_method(self):
        with patch("demo.trader.demo_store"):
            self.trader = DemoTrader(initial_capital=10000, leverage=10, mode="aggressive")

    def test_enrichment(self):
        self.trader._open_positions = [
            {
                "pair": "BTCUSDT", "side": "long", "entry_price": 100,
                "size_usd": 1000, "margin_usd": 100, "leverage": 10,
                "stop_loss": 95, "tp1": 107.5, "tp2_target": None,
                "liquidation_price": 90.5, "entry_ts": 1_000_000_000_000,
            }
        ]
        live_state = {"BTCUSDT": {"last_price": 105}}
        positions = self.trader.get_positions_with_mtm(live_state)
        assert len(positions) == 1
        p = positions[0]
        assert p["current_price"] == 105
        assert p["unrealized_pnl"]["usd"] > 0
        assert p["risk_reward"]["current_rr"] > 0
        assert p["risk_to_liq_pct"] > 0

    def test_no_price_uses_entry(self):
        """When live_state has no price, use entry_price (zero pnl)."""
        self.trader._open_positions = [
            {
                "pair": "ETHUSDT", "side": "long", "entry_price": 100,
                "size_usd": 1000, "margin_usd": 100, "leverage": 10,
                "stop_loss": 95, "tp1": 107.5, "tp2_target": None,
                "liquidation_price": 90.5, "entry_ts": 1_000_000_000_000,
            }
        ]
        positions = self.trader.get_positions_with_mtm({})
        assert positions[0]["unrealized_pnl"]["usd"] == 0


class TestDemoTraderModes:
    def test_aggressive_allows_yellow(self):
        with patch("demo.trader.demo_store"):
            trader = DemoTrader(mode="aggressive")
        assert trader._rules.regime_is_green is False

    def test_conservative_requires_green(self):
        with patch("demo.trader.demo_store"):
            trader = DemoTrader(mode="conservative")
        assert trader._rules.regime_is_green is True


class TestOnSignalIntegration:
    """Integration test: signal → entry → exit flow with mocked DB."""

    @pytest.fixture
    def trader(self):
        with patch("demo.trader.demo_store") as mock_store:
            mock_store.insert_position.return_value = 1
            mock_store.fetch_open_positions.return_value = []
            mock_store.get_current_equity.return_value = 10000.0
            trader = DemoTrader(initial_capital=10000, leverage=10, mode="aggressive")
            set_live_state_ref({"BTCUSDT": {"last_price": 100}})
            yield trader

    @pytest.mark.asyncio
    async def test_entry_on_valid_signal(self, trader):
        signal = SignalOutput(
            regime_state="accumulation", risk_color="green", confidence=85,
            trend_state="uptrend", price_zone="discount", action_bias="long_bias",
        )
        fvg = FVG(1000, "BTCUSDT", "1h", "bullish", 100, 95, "unfilled", 0.05)
        candle = make_candle(2000, 100, 102, 99, 101)

        with patch("demo.trader.telegram") as mock_tg:
            mock_tg.send_message = AsyncMock(return_value=True)
            await trader.on_signal(
                signal=signal, pair="BTCUSDT", timeframe="1h",
                current_price=101, current_candle=candle,
                bullish_fvg=fvg, bearish_fvg=None,
                bullish_ob=None, bearish_ob=None,
                timestamp_ms=2000,
            )

        assert len(trader._open_positions) == 1
        pos = trader._open_positions[0]
        assert pos["side"] == "long"
        assert pos["leverage"] == 10
        assert trader._equity < 10000  # Entry fee deducted

    @pytest.mark.asyncio
    async def test_no_entry_on_red_signal(self, trader):
        signal = SignalOutput(
            regime_state="deleveraging", risk_color="red", confidence=85,
            trend_state="downtrend", price_zone="premium", action_bias="reduce_exposure",
        )
        candle = make_candle(2000, 100, 102, 99, 101)

        await trader.on_signal(
            signal=signal, pair="BTCUSDT", timeframe="1h",
            current_price=101, current_candle=candle,
            bullish_fvg=None, bearish_fvg=None,
            bullish_ob=None, bearish_ob=None,
            timestamp_ms=2000,
        )

        assert len(trader._open_positions) == 0
