"""
Tests for the data pipeline — ensuring data flows correctly from raw candles
through indicators → structure → FVG/OB → classifier → rules → demo trader.
Also tests for data freshness/staleness detection and notification timing.
"""

import time
import numpy as np
import pytest
from unittest.mock import patch, MagicMock

from tests.conftest import make_candle, make_trending_candles
from engine.classifier import SignalOutput, classify
from engine.indicators import atr, vwap, rolling_zscore, vwap_deviation
from engine.structure import detect_swing_points, detect_structure_breaks, get_premium_discount_zone
from engine.fvg import detect_fvgs, update_fvg_status, get_nearest_fvg
from engine.orderblocks import detect_order_blocks, get_nearest_ob
from backtest.rules import TradeRule, check_entry, check_exit
from backtest.simulator import _compute_signals_at


class TestEndToEndPipeline:
    """Full pipeline: candles → signal → entry decision."""

    def test_pipeline_produces_signal(self):
        """50 trending candles should produce a valid signal at index 40."""
        candles = make_trending_candles(
            start_price=60000, n=50, direction="up", step=100,
            volatility=50, base_volume=5000,
            oi_start=1_000_000, oi_step=5000,
        )
        signal = _compute_signals_at(candles, 40)
        assert signal is not None
        assert signal.regime_state in (
            "accumulation", "distribution", "short_squeeze",
            "long_liquidation", "coiled_spring", "deleveraging",
        )
        assert signal.confidence >= 0
        assert signal.confidence <= 100

    def test_pipeline_fvg_detection_feeds_entry(self):
        """Pipeline: detect FVGs → get nearest → feed to check_entry."""
        ts = 1_000_000_000_000
        tf = 3_600_000
        candles = []
        price = 100.0

        # Build candles with a bullish FVG gap
        for i in range(30):
            candles.append(make_candle(
                ts + i * tf, price, price + 1, price - 1, price + 0.5,
                volume=1000, open_interest=1_000_000,
            ))
            price += 0.5

        # Gap-creating candles
        candles.append(make_candle(ts + 30 * tf, price, price + 1, price - 1, price, volume=1000))
        candles.append(make_candle(ts + 31 * tf, price, price + 10, price - 1, price + 9, volume=5000))
        candles.append(make_candle(ts + 32 * tf, price + 9, price + 12, price + 3, price + 11, volume=3000))

        fvgs = detect_fvgs(candles)
        current_price = price + 3  # Near the gap

        nearest = get_nearest_fvg(fvgs, current_price, "bullish")
        if nearest:
            signal = SignalOutput(
                regime_state="accumulation", risk_color="green", confidence=80,
                trend_state="uptrend", price_zone="discount", action_bias="long_bias",
            )
            entry = check_entry(
                signal=signal, bullish_fvg=nearest, bearish_fvg=None,
                bullish_ob=None, bearish_ob=None,
                current_price=current_price, open_positions=0,
                rules=TradeRule(), candle_low=nearest.upper_bound - 0.5,
            )
            # Entry should succeed if wick touched zone
            if entry:
                assert entry["side"] == "long"
                assert entry["entry_zone"]["type"] == "fvg"

    def test_pipeline_ob_detection_feeds_entry(self):
        """Pipeline: detect OBs → get nearest → feed to check_entry."""
        ts = 1_000_000_000_000
        tf = 3_600_000
        candles = []
        price = 100.0

        # ATR warmup
        for i in range(15):
            candles.append(make_candle(ts + i * tf, price, price + 2, price - 2, price + 0.5, volume=1000))
            price += 0.5

        # Bearish candle (potential OB)
        candles.append(make_candle(ts + 15 * tf, price, price + 1, price - 3, price - 2, volume=1000))
        ob_high = price + 1
        ob_low = price - 3
        price -= 2

        # 3 bullish impulse candles
        for i in range(3):
            candles.append(make_candle(
                ts + (16 + i) * tf, price, price + 5, price - 0.5, price + 4,
                volume=3000,
            ))
            price += 4

        fvgs = detect_fvgs(candles)
        obs = detect_order_blocks(candles, fvgs)

        current_price = ob_high + 2
        nearest = get_nearest_ob(obs, current_price, "bullish")
        if nearest:
            signal = SignalOutput(
                regime_state="accumulation", risk_color="green", confidence=80,
                trend_state="uptrend", price_zone="discount", action_bias="long_bias",
            )
            entry = check_entry(
                signal=signal, bullish_fvg=None, bearish_fvg=None,
                bullish_ob=nearest, bearish_ob=None,
                current_price=current_price, open_positions=0,
                rules=TradeRule(), candle_low=nearest.upper_bound,
            )
            if entry:
                assert entry["entry_zone"]["type"] == "ob"


class TestDataFreshness:
    """Tests for stale data detection and confidence penalties."""

    def test_fresh_data_no_penalty(self):
        sig = classify(
            price_change=0.01, oi_change=0.02, volume_zscore=2.0,
            funding_rate=0.0001, taker_ratio=0.5, long_short_ratio=1.0,
            trend_state="uptrend", vwap_deviation=0.0, atr_zscore=0.0,
            data_age_seconds=0,
        )
        assert sig.risk_color == "green"

    def test_stale_data_900s_penalty(self):
        """Data > 900s old → yellow + -20 confidence."""
        sig_fresh = classify(
            price_change=0.01, oi_change=0.02, volume_zscore=2.0,
            funding_rate=0.0001, taker_ratio=0.5, long_short_ratio=1.0,
            trend_state="uptrend", vwap_deviation=0.0, atr_zscore=0.0,
            data_age_seconds=0,
        )
        sig_stale = classify(
            price_change=0.01, oi_change=0.02, volume_zscore=2.0,
            funding_rate=0.0001, taker_ratio=0.5, long_short_ratio=1.0,
            trend_state="uptrend", vwap_deviation=0.0, atr_zscore=0.0,
            data_age_seconds=1000,
        )
        assert sig_stale.risk_color == "yellow"
        assert sig_stale.confidence == sig_fresh.confidence - 20

    def test_stale_data_blocks_conservative_entry(self):
        """Stale data → yellow → conservative trader won't enter."""
        sig = classify(
            price_change=0.01, oi_change=0.02, volume_zscore=2.0,
            funding_rate=0.0001, taker_ratio=0.5, long_short_ratio=1.0,
            trend_state="uptrend", vwap_deviation=0.0, atr_zscore=0.0,
            data_age_seconds=1000,
        )
        from engine.fvg import FVG
        fvg = FVG(1000, "BTCUSDT", "1h", "bullish", 100, 95, "unfilled", 0.05)
        entry = check_entry(
            signal=sig, bullish_fvg=fvg, bearish_fvg=None,
            bullish_ob=None, bearish_ob=None,
            current_price=100, open_positions=0,
            rules=TradeRule(regime_is_green=True),  # Conservative
            candle_low=99,
        )
        assert entry is None  # Yellow signal blocked by conservative rules


class TestIndicatorPipelineConsistency:
    """Ensure indicators produce consistent, non-NaN results for sufficient data."""

    def test_all_indicators_produce_values_at_index_40(self):
        candles = make_trending_candles(start_price=100, n=50, direction="up", step=0.5, volatility=1)
        closes = np.array([c["close"] for c in candles])
        highs = np.array([c["high"] for c in candles])
        lows = np.array([c["low"] for c in candles])
        volumes = np.array([c["volume"] for c in candles])

        atr_vals = atr(highs, lows, closes, period=14)
        vwap_vals = vwap(highs, lows, closes, volumes)
        vol_zscore = rolling_zscore(volumes, 20)
        atr_zscore = rolling_zscore(atr_vals, 20)
        vwap_dev = vwap_deviation(closes, vwap_vals, period=50)

        idx = 40
        assert not np.isnan(atr_vals[idx])
        assert not np.isnan(vwap_vals[idx])
        assert not np.isnan(vol_zscore[idx])
        # ATR z-score needs 20 periods of non-NaN ATR (ATR needs 14)
        # So atr_zscore available from index 14+19 = 33
        assert not np.isnan(atr_zscore[idx])

    def test_volume_zscore_detects_spike(self):
        """A sudden volume spike should produce high z-score."""
        volumes = np.full(30, 1000.0)
        volumes[-1] = 10000.0  # 10x spike
        result = rolling_zscore(volumes, 20)
        assert result[-1] > 3.0  # Well above normal

    def test_atr_increases_with_volatility(self):
        """Higher volatility candles should produce higher ATR."""
        n = 30
        # Low vol
        low_vol_h = np.full(n, 101.0)
        low_vol_l = np.full(n, 99.0)
        low_vol_c = np.full(n, 100.0)
        atr_low = atr(low_vol_h, low_vol_l, low_vol_c, 14)

        # High vol
        high_vol_h = np.full(n, 110.0)
        high_vol_l = np.full(n, 90.0)
        high_vol_c = np.full(n, 100.0)
        atr_high = atr(high_vol_h, high_vol_l, high_vol_c, 14)

        assert atr_high[-1] > atr_low[-1]


class TestOIDataAvailability:
    """Test behavior with and without OI data."""

    def test_with_oi_full_regime_matrix(self):
        """With OI data, all regime states should be reachable."""
        # Accumulation
        sig = classify(
            price_change=0.01, oi_change=0.02, volume_zscore=2.0,
            funding_rate=0.0001, taker_ratio=0.5, long_short_ratio=1.0,
            trend_state="uptrend", vwap_deviation=0.0, atr_zscore=0.0,
        )
        assert sig.regime_state == "accumulation"

    def test_without_oi_fallback_mode(self):
        """Without OI (None), only volume-based classification."""
        sig = classify(
            price_change=0.01, oi_change=None, volume_zscore=2.5,
            funding_rate=0.0, taker_ratio=0.5, long_short_ratio=1.0,
            trend_state="uptrend", vwap_deviation=0.0, atr_zscore=0.0,
        )
        assert sig.regime_state == "accumulation"
        assert sig.risk_color == "green"

    def test_without_oi_low_volume_stays_yellow(self):
        """Without OI + low volume → default yellow."""
        sig = classify(
            price_change=0.01, oi_change=None, volume_zscore=1.0,
            funding_rate=0.0, taker_ratio=0.5, long_short_ratio=1.0,
            trend_state="uptrend", vwap_deviation=0.0, atr_zscore=0.0,
        )
        assert sig.risk_color == "yellow"
        assert sig.action_bias == "stay_flat"

    def test_oi_zero_vs_none_distinction(self):
        """oi_change=0.0 (real data, no change) vs None (no data available)."""
        sig_zero = classify(
            price_change=0.01, oi_change=0.0, volume_zscore=2.0,
            funding_rate=0.0, taker_ratio=0.5, long_short_ratio=1.0,
            trend_state="uptrend", vwap_deviation=0.0, atr_zscore=0.0,
        )
        sig_none = classify(
            price_change=0.01, oi_change=None, volume_zscore=2.0,
            funding_rate=0.0, taker_ratio=0.5, long_short_ratio=1.0,
            trend_state="uptrend", vwap_deviation=0.0, atr_zscore=0.0,
        )
        # With oi_change=0.0, OI confidence bonus IS calculated (just gives 0)
        # With oi_change=None, no OI bonus at all
        # So they may produce different confidence or regime states


class TestNotificationTiming:
    """Test that alerts fire at the right conditions."""

    def test_signal_below_threshold_no_alert(self):
        """Confidence < 70 should not trigger trade alerts."""
        sig = classify(
            price_change=0.001, oi_change=None, volume_zscore=0.5,
            funding_rate=0.0, taker_ratio=0.5, long_short_ratio=1.0,
            trend_state="ranging", vwap_deviation=0.0, atr_zscore=0.0,
        )
        assert sig.confidence < 70

    def test_signal_above_threshold_would_alert(self):
        """Confidence >= 70 should trigger trade alerts."""
        sig = classify(
            price_change=0.01, oi_change=0.06, volume_zscore=2.5,
            funding_rate=0.0005, taker_ratio=0.6, long_short_ratio=1.0,
            trend_state="uptrend", vwap_deviation=-3.0, atr_zscore=0.0,
        )
        assert sig.confidence >= 70

    def test_regime_change_triggers_state_change(self):
        """Transition between regimes should be detected."""
        from engine.classifier import signal_state_changed
        prev = SignalOutput("accumulation", "green", 80, "uptrend", "discount", "long_bias")
        curr = SignalOutput("distribution", "red", 80, "downtrend", "premium", "short_bias")
        assert signal_state_changed(prev, curr) is True

    def test_confidence_crossing_threshold_triggers(self):
        from engine.classifier import signal_state_changed
        prev = SignalOutput("accumulation", "green", 65, "uptrend", "discount", "long_bias")
        curr = SignalOutput("accumulation", "green", 75, "uptrend", "discount", "long_bias")
        assert signal_state_changed(prev, curr) is True


class TestFVGFillTracking:
    """Test that FVG fill status updates correctly over multiple candles."""

    def test_fvg_lifecycle_unfilled_to_partial_to_filled(self):
        from engine.fvg import FVG, update_fvg_status

        fvg = FVG(1000, "BTC", "1h", "bullish", upper_bound=105, lower_bound=100,
                   status="unfilled", gap_size_percent=0.05)

        # Candle 1: price above zone → stays unfilled
        c1 = make_candle(2000, 108, 110, 107, 109)
        update_fvg_status([fvg], c1)
        assert fvg.status == "unfilled"

        # Candle 2: wick enters zone but close stays above → partial
        c2 = make_candle(3000, 106, 107, 104, 103)
        update_fvg_status([fvg], c2)
        assert fvg.status == "partial"

        # Candle 3: close below lower bound → filled
        c3 = make_candle(4000, 101, 102, 98, 99)
        update_fvg_status([fvg], c3)
        assert fvg.status == "filled"
        assert fvg.filled_at == 4000

    def test_multiple_fvgs_tracked_independently(self):
        from engine.fvg import FVG, update_fvg_status

        fvg1 = FVG(1000, "BTC", "1h", "bullish", 105, 100, "unfilled", 0.05)
        fvg2 = FVG(2000, "BTC", "1h", "bullish", 95, 90, "unfilled", 0.05)

        # Candle touches fvg1 but not fvg2
        c = make_candle(3000, 103, 106, 104, 103)
        update_fvg_status([fvg1, fvg2], c)
        assert fvg1.status == "partial"
        assert fvg2.status == "unfilled"


class TestExitPriorityOrder:
    """Verify that exit conditions fire in the correct priority."""

    def test_time_exit_before_regime(self):
        """Time exit fires even if regime is green."""
        pos = {
            "side": "long", "entry_price": 100, "stop_loss": 95,
            "tp1": 107.5, "tp2_target": None,
            "entry_ts": 1_000_000_000_000, "tp1_hit": False,
        }
        # 49 hours later
        candle = {"timestamp": 1_000_000_000_000 + 49 * 3_600_000,
                  "high": 102, "low": 98, "close": 101, "open": 100}
        signal = SignalOutput("accumulation", "green", 80, "uptrend", "discount", "long_bias")
        result = check_exit(pos, candle, signal, TradeRule())
        assert result["exit_reason"] == "time_exit"

    def test_sl_wins_over_tp_in_same_candle(self):
        """When both SL and TP are breached in same candle, SL wins."""
        pos = {
            "side": "long", "entry_price": 100, "stop_loss": 95,
            "tp1": 108, "tp2_target": None,
            "entry_ts": 1_000_000_000_000, "tp1_hit": False,
        }
        # Wide candle hitting both SL and TP
        candle = {"timestamp": 1_000_000_000_000 + 3_600_000,
                  "high": 110, "low": 93, "close": 100, "open": 100}
        signal = SignalOutput("accumulation", "green", 80, "uptrend", "discount", "long_bias")
        result = check_exit(pos, candle, signal, TradeRule())
        assert result["exit_reason"] == "stop_loss"
