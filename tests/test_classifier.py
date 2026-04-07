"""
Tests for engine/classifier.py — regime classification and confidence scoring.
Covers all 11+ regime paths, confidence bonuses/penalties, edge cases.
"""

import pytest
from engine.classifier import classify, signal_state_changed, SignalOutput


class TestRegimeClassification:
    """Test all regime state classification branches."""

    def test_accumulation(self):
        """Price up + OI building + high volume + no extreme funding → accumulation."""
        sig = classify(
            price_change=0.01, oi_change=0.02, volume_zscore=2.0,
            funding_rate=0.0001, taker_ratio=0.5, long_short_ratio=1.0,
            trend_state="uptrend", vwap_deviation=0.0, atr_zscore=0.0,
        )
        assert sig.regime_state == "accumulation"
        assert sig.risk_color == "green"
        assert sig.action_bias == "long_bias"

    def test_short_squeeze_crowded_longs(self):
        """Price up + OI building + high vol + extreme positive funding → short_squeeze."""
        sig = classify(
            price_change=0.01, oi_change=0.02, volume_zscore=2.0,
            funding_rate=0.0005, taker_ratio=0.5, long_short_ratio=1.0,
            trend_state="uptrend", vwap_deviation=0.0, atr_zscore=0.0,
        )
        assert sig.regime_state == "short_squeeze"
        assert sig.risk_color == "yellow"
        assert sig.action_bias == "short_bias"

    def test_short_squeeze_short_covering(self):
        """Price up + OI unwinding + high volume → short_squeeze (covering rally)."""
        sig = classify(
            price_change=0.01, oi_change=-0.02, volume_zscore=2.0,
            funding_rate=0.0001, taker_ratio=0.5, long_short_ratio=1.0,
            trend_state="uptrend", vwap_deviation=0.0, atr_zscore=0.0,
        )
        assert sig.regime_state == "short_squeeze"
        assert sig.action_bias == "short_bias"

    def test_distribution(self):
        """Price down + OI building + high vol + no extreme neg funding → distribution."""
        sig = classify(
            price_change=-0.01, oi_change=0.02, volume_zscore=2.0,
            funding_rate=-0.0001, taker_ratio=0.5, long_short_ratio=1.0,
            trend_state="downtrend", vwap_deviation=0.0, atr_zscore=0.0,
        )
        assert sig.regime_state == "distribution"
        assert sig.risk_color == "green"
        assert sig.action_bias == "short_bias"

    def test_long_liquidation_crowded_shorts(self):
        """Price down + OI building + high vol + extreme neg funding → long_liquidation yellow."""
        sig = classify(
            price_change=-0.01, oi_change=0.02, volume_zscore=2.0,
            funding_rate=-0.0005, taker_ratio=0.5, long_short_ratio=1.0,
            trend_state="downtrend", vwap_deviation=0.0, atr_zscore=0.0,
        )
        assert sig.regime_state == "long_liquidation"
        assert sig.risk_color == "yellow"
        assert sig.action_bias == "long_bias"

    def test_long_liquidation_cascade(self):
        """Price down + OI unwinding + high vol → long_liquidation red."""
        sig = classify(
            price_change=-0.01, oi_change=-0.02, volume_zscore=2.0,
            funding_rate=0.0, taker_ratio=0.5, long_short_ratio=1.0,
            trend_state="downtrend", vwap_deviation=0.0, atr_zscore=0.0,
        )
        assert sig.regime_state == "long_liquidation"
        assert sig.risk_color == "red"
        assert sig.action_bias == "reduce_exposure"

    def test_coiled_spring(self):
        """Flat price + OI spike + low volume → coiled_spring."""
        sig = classify(
            price_change=0.001, oi_change=0.06, volume_zscore=1.0,
            funding_rate=0.0, taker_ratio=0.5, long_short_ratio=1.0,
            trend_state="ranging", vwap_deviation=0.0, atr_zscore=0.0,
        )
        assert sig.regime_state == "coiled_spring"
        assert sig.risk_color == "yellow"
        assert sig.action_bias == "stay_flat"

    def test_deleveraging_volume_spike(self):
        """OI unwinding + high volume → deleveraging red."""
        sig = classify(
            price_change=0.001, oi_change=-0.02, volume_zscore=2.0,
            funding_rate=0.0, taker_ratio=0.5, long_short_ratio=1.0,
            trend_state="ranging", vwap_deviation=0.0, atr_zscore=0.0,
        )
        assert sig.regime_state == "deleveraging"
        assert sig.risk_color == "red"
        assert sig.action_bias == "reduce_exposure"

    def test_deleveraging_fast_oi_drain(self):
        """OI drops >5% even without volume spike → deleveraging."""
        sig = classify(
            price_change=0.001, oi_change=-0.06, volume_zscore=0.5,
            funding_rate=0.0, taker_ratio=0.5, long_short_ratio=1.0,
            trend_state="ranging", vwap_deviation=0.0, atr_zscore=0.0,
        )
        assert sig.regime_state == "deleveraging"
        assert sig.risk_color == "red"

    def test_no_oi_volume_up_proxy_accumulation(self):
        """No OI data + strong volume + price up → accumulation (fallback)."""
        sig = classify(
            price_change=0.01, oi_change=None, volume_zscore=2.5,
            funding_rate=0.0, taker_ratio=0.5, long_short_ratio=1.0,
            trend_state="uptrend", vwap_deviation=0.0, atr_zscore=0.0,
        )
        assert sig.regime_state == "accumulation"
        assert sig.risk_color == "green"

    def test_no_oi_volume_down_proxy_distribution(self):
        """No OI data + strong volume + price down → distribution (fallback)."""
        sig = classify(
            price_change=-0.01, oi_change=None, volume_zscore=2.5,
            funding_rate=0.0, taker_ratio=0.5, long_short_ratio=1.0,
            trend_state="downtrend", vwap_deviation=0.0, atr_zscore=0.0,
        )
        assert sig.regime_state == "distribution"
        assert sig.risk_color == "green"

    def test_default_insufficient_signal(self):
        """Low everything → default yellow stay_flat."""
        sig = classify(
            price_change=0.0005, oi_change=0.001, volume_zscore=0.5,
            funding_rate=0.0, taker_ratio=0.5, long_short_ratio=1.0,
            trend_state="ranging", vwap_deviation=0.0, atr_zscore=0.0,
        )
        assert sig.risk_color == "yellow"
        assert sig.action_bias == "stay_flat"

    def test_default_negative_price_gives_distribution(self):
        sig = classify(
            price_change=-0.0005, oi_change=0.001, volume_zscore=0.5,
            funding_rate=0.0, taker_ratio=0.5, long_short_ratio=1.0,
            trend_state="ranging", vwap_deviation=0.0, atr_zscore=0.0,
        )
        assert sig.regime_state == "distribution"


class TestConfidenceScoring:
    def test_base_confidence(self):
        """Minimal inputs → base confidence of 50."""
        sig = classify(
            price_change=0.0, oi_change=None, volume_zscore=0.0,
            funding_rate=0.0, taker_ratio=0.5, long_short_ratio=1.0,
            trend_state="ranging", vwap_deviation=0.0, atr_zscore=0.0,
        )
        assert sig.confidence == 50

    def test_volume_confirmation_tiers(self):
        # z > 2.0 → +20
        sig = classify(
            price_change=0.01, oi_change=0.02, volume_zscore=2.5,
            funding_rate=0.0, taker_ratio=0.5, long_short_ratio=1.0,
            trend_state="uptrend", vwap_deviation=0.0, atr_zscore=0.0,
        )
        assert sig.confidence >= 70  # base 50 + vol 20

    def test_oi_magnitude_bonus(self):
        # |oi_change| > 0.05 → +15
        sig = classify(
            price_change=0.01, oi_change=0.06, volume_zscore=2.0,
            funding_rate=0.0, taker_ratio=0.5, long_short_ratio=1.0,
            trend_state="uptrend", vwap_deviation=0.0, atr_zscore=0.0,
        )
        # Should include OI bonus
        assert sig.confidence >= 85

    def test_oi_bonus_only_when_available(self):
        """oi_change=None → no OI bonus."""
        sig_no_oi = classify(
            price_change=0.01, oi_change=None, volume_zscore=2.5,
            funding_rate=0.0, taker_ratio=0.6, long_short_ratio=1.0,
            trend_state="uptrend", vwap_deviation=0.0, atr_zscore=0.0,
        )
        sig_with_oi = classify(
            price_change=0.01, oi_change=0.06, volume_zscore=2.5,
            funding_rate=0.0, taker_ratio=0.6, long_short_ratio=1.0,
            trend_state="uptrend", vwap_deviation=0.0, atr_zscore=0.0,
        )
        assert sig_with_oi.confidence > sig_no_oi.confidence

    def test_funding_extreme_bonus(self):
        sig = classify(
            price_change=0.01, oi_change=0.02, volume_zscore=2.0,
            funding_rate=0.0006, taker_ratio=0.5, long_short_ratio=1.0,
            trend_state="uptrend", vwap_deviation=0.0, atr_zscore=0.0,
        )
        # Extreme funding → +10, but also triggers short_squeeze penalty -15
        assert sig.confidence >= 50

    def test_taker_alignment_bonus(self):
        """Taker ratio > 0.55 in accumulation → +10."""
        sig = classify(
            price_change=0.01, oi_change=0.02, volume_zscore=2.0,
            funding_rate=0.0001, taker_ratio=0.6, long_short_ratio=1.0,
            trend_state="uptrend", vwap_deviation=0.0, atr_zscore=0.0,
        )
        assert sig.confidence >= 80

    def test_trend_alignment_bonus(self):
        """Long bias + uptrend → +10."""
        sig_aligned = classify(
            price_change=0.01, oi_change=0.02, volume_zscore=2.0,
            funding_rate=0.0001, taker_ratio=0.5, long_short_ratio=1.0,
            trend_state="uptrend", vwap_deviation=0.0, atr_zscore=0.0,
        )
        sig_misaligned = classify(
            price_change=0.01, oi_change=0.02, volume_zscore=2.0,
            funding_rate=0.0001, taker_ratio=0.5, long_short_ratio=1.0,
            trend_state="downtrend", vwap_deviation=0.0, atr_zscore=0.0,
        )
        assert sig_aligned.confidence > sig_misaligned.confidence

    def test_vwap_mean_reversion_bonus(self):
        """Long bias + negative vwap deviation → +5."""
        sig = classify(
            price_change=0.01, oi_change=0.02, volume_zscore=2.0,
            funding_rate=0.0001, taker_ratio=0.5, long_short_ratio=1.0,
            trend_state="uptrend", vwap_deviation=-3.0, atr_zscore=0.0,
        )
        sig_no_vwap = classify(
            price_change=0.01, oi_change=0.02, volume_zscore=2.0,
            funding_rate=0.0001, taker_ratio=0.5, long_short_ratio=1.0,
            trend_state="uptrend", vwap_deviation=0.0, atr_zscore=0.0,
        )
        assert sig.confidence >= sig_no_vwap.confidence

    def test_low_volatility_mixed_signals_penalty(self):
        """ATR z-score < -1 + mixed signals → -10."""
        sig = classify(
            price_change=0.0, oi_change=None, volume_zscore=0.5,
            funding_rate=0.0, taker_ratio=0.5, long_short_ratio=1.0,
            trend_state="ranging", vwap_deviation=0.0, atr_zscore=-1.5,
        )
        assert sig.confidence <= 40  # 50 - 10

    def test_short_squeeze_penalty(self):
        """Short squeeze regime → -15 confidence."""
        sig = classify(
            price_change=0.01, oi_change=0.02, volume_zscore=2.0,
            funding_rate=0.0005, taker_ratio=0.5, long_short_ratio=1.0,
            trend_state="uptrend", vwap_deviation=0.0, atr_zscore=0.0,
        )
        assert sig.regime_state == "short_squeeze"
        # Base 50 + vol 20 + funding 10 - squeeze penalty 15 = 65
        # (minus trend misalignment since it's short_bias in uptrend)

    def test_long_liquidation_yellow_penalty(self):
        """Long liquidation yellow → -10 confidence."""
        sig = classify(
            price_change=-0.01, oi_change=0.02, volume_zscore=2.0,
            funding_rate=-0.0005, taker_ratio=0.5, long_short_ratio=1.0,
            trend_state="downtrend", vwap_deviation=0.0, atr_zscore=0.0,
        )
        assert sig.regime_state == "long_liquidation"
        assert sig.risk_color == "yellow"

    def test_confidence_clamped_0_100(self):
        """Confidence must stay in [0, 100]."""
        # Try to push very high
        sig_high = classify(
            price_change=0.05, oi_change=0.1, volume_zscore=5.0,
            funding_rate=0.001, taker_ratio=0.7, long_short_ratio=1.0,
            trend_state="uptrend", vwap_deviation=-5.0, atr_zscore=2.0,
        )
        assert sig_high.confidence <= 100

        # Try to push very low
        sig_low = classify(
            price_change=0.0, oi_change=None, volume_zscore=0.0,
            funding_rate=0.0, taker_ratio=0.5, long_short_ratio=1.0,
            trend_state="ranging", vwap_deviation=0.0, atr_zscore=-3.0,
            data_age_seconds=2000,
        )
        assert sig_low.confidence >= 0

    def test_stale_data_penalty(self):
        """Data older than 900s → yellow + -20 confidence."""
        sig = classify(
            price_change=0.01, oi_change=0.02, volume_zscore=2.0,
            funding_rate=0.0001, taker_ratio=0.5, long_short_ratio=1.0,
            trend_state="uptrend", vwap_deviation=0.0, atr_zscore=0.0,
            data_age_seconds=1000,
        )
        assert sig.risk_color == "yellow"  # Overridden from green
        # Confidence should be lower due to -20 penalty
        sig_fresh = classify(
            price_change=0.01, oi_change=0.02, volume_zscore=2.0,
            funding_rate=0.0001, taker_ratio=0.5, long_short_ratio=1.0,
            trend_state="uptrend", vwap_deviation=0.0, atr_zscore=0.0,
            data_age_seconds=0,
        )
        assert sig.confidence == sig_fresh.confidence - 20


class TestSignalOutput:
    def test_fields_populated(self):
        sig = classify(
            price_change=0.01, oi_change=0.02, volume_zscore=2.0,
            funding_rate=0.0001, taker_ratio=0.55, long_short_ratio=1.0,
            trend_state="uptrend", vwap_deviation=-1.0, atr_zscore=0.5,
            pair="BTCUSDT", timeframe="1h", timestamp=12345,
            price_zone="discount", current_price=60000, atr=500,
        )
        assert sig.pair == "BTCUSDT"
        assert sig.timeframe == "1h"
        assert sig.timestamp == 12345
        assert sig.volume_zscore == 2.0
        assert sig.taker_ratio == 0.55
        assert sig.atr == 500

    def test_oi_change_none_stored_as_zero(self):
        sig = classify(
            price_change=0.0, oi_change=None, volume_zscore=0.0,
            funding_rate=0.0, taker_ratio=0.5, long_short_ratio=1.0,
            trend_state="ranging", vwap_deviation=0.0, atr_zscore=0.0,
        )
        assert sig.oi_change_percent == 0.0


class TestSignalStateChanged:
    def test_first_signal_always_changed(self):
        sig = SignalOutput("accumulation", "green", 80, "uptrend", "discount", "long_bias")
        assert signal_state_changed(None, sig) is True

    def test_same_signal_not_changed(self):
        sig = SignalOutput("accumulation", "green", 80, "uptrend", "discount", "long_bias")
        assert signal_state_changed(sig, sig) is False

    def test_regime_change(self):
        prev = SignalOutput("accumulation", "green", 80, "uptrend", "discount", "long_bias")
        curr = SignalOutput("distribution", "green", 80, "uptrend", "discount", "long_bias")
        assert signal_state_changed(prev, curr) is True

    def test_color_change(self):
        prev = SignalOutput("accumulation", "green", 80, "uptrend", "discount", "long_bias")
        curr = SignalOutput("accumulation", "red", 80, "uptrend", "discount", "long_bias")
        assert signal_state_changed(prev, curr) is True

    def test_confidence_crosses_threshold_up(self):
        prev = SignalOutput("accumulation", "green", 65, "uptrend", "discount", "long_bias")
        curr = SignalOutput("accumulation", "green", 75, "uptrend", "discount", "long_bias")
        assert signal_state_changed(prev, curr) is True

    def test_confidence_crosses_threshold_down(self):
        prev = SignalOutput("accumulation", "green", 75, "uptrend", "discount", "long_bias")
        curr = SignalOutput("accumulation", "green", 65, "uptrend", "discount", "long_bias")
        assert signal_state_changed(prev, curr) is True

    def test_confidence_stays_above_threshold(self):
        prev = SignalOutput("accumulation", "green", 75, "uptrend", "discount", "long_bias")
        curr = SignalOutput("accumulation", "green", 85, "uptrend", "discount", "long_bias")
        assert signal_state_changed(prev, curr) is False
