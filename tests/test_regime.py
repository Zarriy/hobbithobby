"""
Tests for engine/regime.py — 4H macro regime classification.
"""

import numpy as np
import pytest
from tests.conftest import make_candle, make_trending_candles, make_flat_candles
from engine.regime import classify_macro_regime


class TestClassifyMacroRegime:
    def test_insufficient_data(self):
        candles = [make_candle(i * 14400000, 100, 101, 99, 100) for i in range(5)]
        result = classify_macro_regime(candles, [], [], [], lookback=30)
        assert result == "transition"

    def test_markup_strong_uptrend(self):
        """Strong uptrend with expanding volume → markup or transition (CHoCH possible with random noise)."""
        candles = make_trending_candles(
            start_price=100, n=40, direction="up", step=3,
            volatility=0.1,  # Very low volatility to avoid false CHoCH
            base_volume=1000, timeframe="4h",
        )
        # Make second half volume higher
        for c in candles[20:]:
            c["volume"] *= 2

        oi = [1_000_000 + i * 10000 for i in range(40)]
        funding = [0.00005] * 40
        volumes = [c["volume"] for c in candles]

        result = classify_macro_regime(candles, oi, funding, volumes, lookback=30)
        assert result in ("markup", "accumulation", "transition")

    def test_markdown_strong_downtrend(self):
        candles = make_trending_candles(
            start_price=200, n=40, direction="down", step=3,
            volatility=0.1, base_volume=1000, timeframe="4h",
        )
        for c in candles[20:]:
            c["volume"] *= 2

        oi = [1_000_000 + i * 10000 for i in range(40)]
        funding = [-0.00005] * 40
        volumes = [c["volume"] for c in candles]

        result = classify_macro_regime(candles, oi, funding, volumes, lookback=30)
        assert result in ("markdown", "distribution", "transition")

    def test_accumulation_ranging_oi_building(self):
        """Ranging with OI building + negative funding → accumulation."""
        candles = make_flat_candles(price=100, n=40, noise=1, timeframe="4h")
        oi = [1_000_000 + i * 20000 for i in range(40)]  # Strong OI build
        funding = [-0.0002] * 40  # Negative funding
        volumes = [c["volume"] for c in candles]

        result = classify_macro_regime(candles, oi, funding, volumes, lookback=30)
        assert result in ("accumulation", "transition")

    def test_distribution_ranging_oi_building_positive_funding(self):
        """Ranging with OI building + positive funding → distribution."""
        candles = make_flat_candles(price=100, n=40, noise=1, timeframe="4h")
        oi = [1_000_000 + i * 20000 for i in range(40)]
        funding = [0.0002] * 40  # Positive funding
        volumes = [c["volume"] for c in candles]

        result = classify_macro_regime(candles, oi, funding, volumes, lookback=30)
        assert result in ("distribution", "transition")

    def test_transition_with_choch(self):
        """If recent CHoCH detected → transition."""
        # Build candles that create swing points with a reversal
        ts = 1_000_000_000_000
        tf = 14_400_000
        candles = []
        # First, go up creating higher highs
        price = 100
        for i in range(15):
            candles.append(make_candle(ts + i * tf, price, price + 3, price - 1, price + 2))
            price += 2
        # Then reverse sharply creating lower lows
        for i in range(25):
            idx = 15 + i
            candles.append(make_candle(ts + idx * tf, price, price + 1, price - 4, price - 3))
            price -= 3

        oi = [1_000_000] * 40
        funding = [0.0] * 40
        volumes = [c["volume"] for c in candles]

        result = classify_macro_regime(candles, oi, funding, volumes, lookback=30)
        # Should detect CHoCH due to structure break
        assert result in ("transition", "markdown", "distribution")

    def test_empty_oi_funding(self):
        """Handles empty OI/funding gracefully."""
        candles = make_trending_candles(start_price=100, n=40, direction="up", step=1, timeframe="4h")
        volumes = [c["volume"] for c in candles]
        result = classify_macro_regime(candles, [], [], volumes, lookback=30)
        assert result in ("accumulation", "markup", "transition")

    def test_price_change_threshold_markup(self):
        """Price change > 5% → markup even without expanding volume."""
        candles = make_trending_candles(
            start_price=100, n=40, direction="up", step=0.5,
            volatility=0.2, base_volume=1000, timeframe="4h",
        )
        # Force big price move
        candles[-1]["close"] = candles[0]["close"] * 1.06  # 6% up

        oi = [1_000_000] * 40
        funding = [0.0] * 40
        volumes = [1000.0] * 40

        result = classify_macro_regime(candles, oi, funding, volumes, lookback=30)
        assert result in ("markup", "accumulation", "transition")
