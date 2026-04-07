"""
Tests for engine/levels.py — liquidation level estimation.
"""

import pytest
from engine.levels import estimate_liquidation_levels, find_nearest_liquidation_cluster


class TestEstimateLiquidationLevels:
    def test_basic_from_current_price(self):
        result = estimate_liquidation_levels(
            current_price=50000,
            open_interest=1_000_000,
            recent_oi_changes=[],
        )
        assert 10 in result
        # Long liq at 10x: 50000 * (1 - 1/10) = 45000
        assert result[10]["from_current"]["long_liq"] == pytest.approx(45000)
        # Short liq at 10x: 50000 * (1 + 1/10) = 55000
        assert result[10]["from_current"]["short_liq"] == pytest.approx(55000)

    def test_high_leverage_tighter(self):
        result = estimate_liquidation_levels(50000, 1_000_000, [])
        # 100x: liq at 50000*(1-0.01) = 49500
        assert result[100]["from_current"]["long_liq"] == pytest.approx(49500)

    def test_oi_change_entries(self):
        oi_changes = [
            {"price": 48000, "oi_change_percent": 0.05},  # Significant
            {"price": 49000, "oi_change_percent": 0.01},  # Below 2% threshold → ignored
        ]
        result = estimate_liquidation_levels(50000, 1_000_000, oi_changes)
        # 10x: 48000 * (1 - 0.1) = 43200
        assert 43200 in result[10]["long_liq_levels"]
        # 49000 should NOT appear (oi_change < 2%)
        assert 49000 * 0.9 not in result[10]["long_liq_levels"]

    def test_no_price_in_entry_ignored(self):
        oi_changes = [{"oi_change_percent": 0.05}]  # Missing price
        result = estimate_liquidation_levels(50000, 1_000_000, oi_changes)
        assert result[10]["long_liq_levels"] == []

    def test_custom_leverage_assumptions(self):
        result = estimate_liquidation_levels(
            50000, 1_000_000, [],
            leverage_assumptions=[2, 3],
        )
        assert 2 in result
        assert 3 in result
        assert 10 not in result

    def test_deduplication_of_levels(self):
        """Same entry price should produce one level, not duplicates."""
        oi_changes = [
            {"price": 48000, "oi_change_percent": 0.05},
            {"price": 48000, "oi_change_percent": 0.08},
        ]
        result = estimate_liquidation_levels(50000, 1_000_000, oi_changes)
        assert len(result[10]["long_liq_levels"]) == 1  # Deduped via set


class TestFindNearestLiquidationCluster:
    def test_nearest_below(self):
        liq_levels = estimate_liquidation_levels(50000, 1_000_000, [
            {"price": 48000, "oi_change_percent": 0.05},
        ])
        nearest = find_nearest_liquidation_cluster(liq_levels, 50000, "below")
        assert nearest is not None
        assert nearest < 50000

    def test_nearest_above(self):
        liq_levels = estimate_liquidation_levels(50000, 1_000_000, [
            {"price": 48000, "oi_change_percent": 0.05},
        ])
        nearest = find_nearest_liquidation_cluster(liq_levels, 50000, "above")
        assert nearest is not None
        assert nearest > 50000

    def test_no_levels_returns_none(self):
        liq_levels = estimate_liquidation_levels(50000, 1_000_000, [])
        # Only from_current levels exist, but they should still work
        nearest = find_nearest_liquidation_cluster(liq_levels, 50000, "below")
        assert nearest is not None  # from_current long_liq is below
