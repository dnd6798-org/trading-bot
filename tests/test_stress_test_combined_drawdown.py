"""
Unit tests for scripts/stress_test_combined_drawdown.py's PURE functions
(v85 read-only analysis, Part A). All expected values below are
hand-computed in the corresponding docstring/comment, not just asserted
against the implementation's own output. No network/Alpaca access, no
src/ or existing-script strategy logic exercised here — these tests only
exercise this milestone's own new, additive helper functions.
"""
import math

import pytest

from scripts.backtest_donchian_ensemble import EnsembleTrade
from scripts.stress_test_combined_drawdown import (
    pearson_correlation,
    build_combined_curve,
    compute_global_max_drawdown,
    detect_drawdown_episodes,
    contribution_pp,
    running_drawdown_series,
    find_blocked_entries,
)


# =============================================================================
# pearson_correlation
# =============================================================================
def test_pearson_correlation_perfect_positive():
    assert pearson_correlation([1, 2, 3, 4], [2, 4, 6, 8]) == pytest.approx(1.0)


def test_pearson_correlation_perfect_negative():
    assert pearson_correlation([1, 2, 3, 4], [8, 6, 4, 2]) == pytest.approx(-1.0)


def test_pearson_correlation_hand_computed_partial():
    # mean_x=2, mean_y=2; cov=(1-2)(1-2)+(2-2)(3-2)+(3-2)(2-2)=1+0+0=1
    # var_x=1+0+1=2; var_y=1+1+0=2; rho=1/sqrt(2*2)=0.5
    assert pearson_correlation([1, 2, 3], [1, 3, 2]) == pytest.approx(0.5)


def test_pearson_correlation_zero_variance_returns_none():
    assert pearson_correlation([1, 1, 1], [1, 2, 3]) is None


def test_pearson_correlation_too_few_points_returns_none():
    assert pearson_correlation([1], [2]) is None


# =============================================================================
# build_combined_curve
# =============================================================================
def test_build_combined_curve_no_rebalance():
    dates = ["d0", "d1", "d2"]
    values_b = [100.0, 110.0, 121.0]   # +10% each day
    values_c = [100.0, 90.0, 81.0]     # -10% each day
    combined, sub_b, sub_c = build_combined_curve(
        dates, values_b, values_c, rebalance_dates=[], track_b_alloc_pct=0.7, track_c_alloc_pct=0.3, initial_capital=1000.0
    )
    # day0: sub_b=700, sub_c=300, combined=1000
    # day1: sub_b=700*1.10=770, sub_c=300*0.90=270, combined=1040
    # day2: sub_b=770*1.10=847, sub_c=270*0.90=243, combined=1090
    assert sub_b == pytest.approx([700.0, 770.0, 847.0])
    assert sub_c == pytest.approx([300.0, 270.0, 243.0])
    assert combined == pytest.approx([1000.0, 1040.0, 1090.0])
    # combined must equal sub_b + sub_c at every point, always.
    for i in range(3):
        assert combined[i] == pytest.approx(sub_b[i] + sub_c[i])


def test_build_combined_curve_with_rebalance_resets_split():
    dates = ["d0", "d1", "d2"]
    values_b = [100.0, 110.0, 121.0]   # +10% each day
    values_c = [100.0, 90.0, 81.0]     # -10% each day
    combined, sub_b, sub_c = build_combined_curve(
        dates, values_b, values_c, rebalance_dates=["d1"], track_b_alloc_pct=0.7, track_c_alloc_pct=0.3, initial_capital=1000.0
    )
    # day0: sub_b=700, sub_c=300, combined=1000 (no rebalance on d0)
    # day1 pre-reset: sub_b=770, sub_c=270, combined=1040
    #      d1 is a rebalance date -> reset: sub_b=1040*0.7=728, sub_c=1040*0.3=312
    # day2: sub_b=728*1.10=800.8, sub_c=312*0.90=280.8, combined=1081.6
    assert sub_b == pytest.approx([700.0, 728.0, 800.8])
    assert sub_c == pytest.approx([300.0, 312.0, 280.8])
    assert combined == pytest.approx([1000.0, 1040.0, 1081.6])
    # rebalancing must never change the combined total at the reset instant.
    assert combined[1] == pytest.approx(1040.0)


def test_build_combined_curve_rebalance_on_first_date():
    dates = ["d0", "d1"]
    values_b = [100.0, 100.0]
    values_c = [100.0, 100.0]
    combined, sub_b, sub_c = build_combined_curve(
        dates, values_b, values_c, rebalance_dates=["d0"], track_b_alloc_pct=0.6, track_c_alloc_pct=0.4, initial_capital=500.0
    )
    assert sub_b[0] == pytest.approx(300.0)
    assert sub_c[0] == pytest.approx(200.0)


# =============================================================================
# compute_global_max_drawdown
# =============================================================================
def test_compute_global_max_drawdown_hand_computed():
    dates = ["d0", "d1", "d2", "d3", "d4", "d5", "d6"]
    values = [100, 120, 90, 95, 130, 80, 110]
    # running peak/drawdown trace:
    #   d0: peak=100 dd=0
    #   d1: peak=120 dd=0
    #   d2: peak=120 v=90  dd=25.0
    #   d3: peak=120 v=95  dd=20.8333...
    #   d4: peak=130 v=130 dd=0
    #   d5: peak=130 v=80  dd=38.461538...  <- global max
    #   d6: peak=130 v=110 dd=15.3846...
    # never returns to >=130 after d5 -> not recovered.
    result = compute_global_max_drawdown(dates, values)
    assert result["peak_date"] == "d4"
    assert result["peak_value"] == pytest.approx(130)
    assert result["trough_date"] == "d5"
    assert result["trough_value"] == pytest.approx(80)
    assert result["max_dd_pct"] == pytest.approx(50 / 130 * 100)
    assert result["recovered"] is False
    assert result["recovery_date"] is None


def test_compute_global_max_drawdown_recovers():
    dates = ["d0", "d1", "d2", "d3"]
    values = [100, 80, 100, 105]
    # d0: peak=100 dd=0; d1: peak=100 v=80 dd=20.0 (max); d2: v=100>=peak(100) -> recovered at d2
    result = compute_global_max_drawdown(dates, values)
    assert result["max_dd_pct"] == pytest.approx(20.0)
    assert result["trough_date"] == "d1"
    assert result["recovered"] is True
    assert result["recovery_date"] == "d2"


# =============================================================================
# detect_drawdown_episodes
# =============================================================================
def test_detect_drawdown_episodes_two_episodes_hand_computed():
    dates = ["d0", "d1", "d2", "d3", "d4", "d5", "d6"]
    values = [100, 120, 90, 95, 130, 80, 110]
    episodes = detect_drawdown_episodes(dates, values, threshold_pct=20.0)
    assert len(episodes) == 2

    e1 = episodes[0]
    assert e1["first_cross_date"] == "d2"
    assert e1["peak_date"] == "d1"
    assert e1["peak_value"] == pytest.approx(120)
    assert e1["trough_date"] == "d2"
    assert e1["trough_value"] == pytest.approx(90)
    assert e1["max_depth_pct"] == pytest.approx(25.0)
    assert e1["end_date"] == "d4"
    assert e1["recovered"] is True
    assert e1["duration_trading_days"] == 2  # index(d4)=4 - index(d2)=2

    e2 = episodes[1]
    assert e2["first_cross_date"] == "d5"
    assert e2["peak_date"] == "d4"
    assert e2["peak_value"] == pytest.approx(130)
    assert e2["trough_date"] == "d5"
    assert e2["trough_value"] == pytest.approx(80)
    assert e2["max_depth_pct"] == pytest.approx(50 / 130 * 100)
    assert e2["end_date"] == "d6"
    assert e2["recovered"] is True
    assert e2["duration_trading_days"] == 1


def test_detect_drawdown_episodes_unrecovered_episode_at_series_end():
    dates = ["d0", "d1", "d2"]
    values = [100, 85, 80]
    episodes = detect_drawdown_episodes(dates, values, threshold_pct=10.0)
    assert len(episodes) == 1
    e = episodes[0]
    assert e["first_cross_date"] == "d1"
    assert e["max_depth_pct"] == pytest.approx(20.0)  # at d2: (100-80)/100*100
    assert e["end_date"] == "d2"
    assert e["recovered"] is False
    assert e["duration_trading_days"] == 1


def test_detect_drawdown_episodes_no_episode_below_threshold():
    dates = ["d0", "d1", "d2"]
    values = [100, 95, 100]
    assert detect_drawdown_episodes(dates, values, threshold_pct=10.0) == []


# =============================================================================
# contribution_pp
# =============================================================================
def test_contribution_pp_sums_exactly_to_combined_drawdown():
    sub_b = [500.0, 400.0]
    sub_c = [500.0, 450.0]
    combined_peak = 1000.0  # = sub_b[0] + sub_c[0]
    cb = contribution_pp(sub_b, peak_idx=0, trough_idx=1, denom=combined_peak)
    cc = contribution_pp(sub_c, peak_idx=0, trough_idx=1, denom=combined_peak)
    assert cb == pytest.approx(10.0)   # (500-400)/1000*100
    assert cc == pytest.approx(5.0)    # (500-450)/1000*100
    combined_dd = (1000.0 - 850.0) / 1000.0 * 100  # = 15.0
    assert cb + cc == pytest.approx(combined_dd)


def test_contribution_pp_zero_denom_returns_zero():
    assert contribution_pp([1.0, 2.0], 0, 1, denom=0.0) == 0.0


# =============================================================================
# running_drawdown_series
# =============================================================================
def test_running_drawdown_series_hand_computed():
    dates = ["d0", "d1", "d2"]
    values = [100.0, 80.0, 90.0]
    result = running_drawdown_series(dates, values)
    assert result == {"d0": pytest.approx(0.0), "d1": pytest.approx(20.0), "d2": pytest.approx(10.0)}


# =============================================================================
# find_blocked_entries
# =============================================================================
def _make_trade(symbol, entry_ts, entry_price, exit_price, position_size, cost_frac_per_leg):
    gross_pnl = position_size * (exit_price - entry_price)
    fees_paid = position_size * (entry_price + exit_price) * cost_frac_per_leg
    pnl = gross_pnl - fees_paid
    return EnsembleTrade(
        symbol=symbol, entry_index=0, exit_index=1,
        entry_timestamp=entry_ts, exit_timestamp="2020-01-05T00:00:00",
        entry_price=entry_price, exit_price=exit_price, exit_reason="trailing_stop",
        gross_pnl=gross_pnl, fees_paid=fees_paid, pnl=pnl,
        r_multiple=0.0,
    )


def test_find_blocked_entries_hand_computed():
    cost_frac = 0.0005
    trade_blocked = _make_trade("SPY", "2020-01-01T00:00:00", 100.0, 110.0, 10.0, cost_frac)
    trade_not_blocked = _make_trade("QQQ", "2020-01-02T00:00:00", 200.0, 210.0, 5.0, cost_frac)
    trade_outside_window = _make_trade("AGG", "2020-01-03T00:00:00", 50.0, 55.0, 20.0, cost_frac)

    drawdown_by_date = {"2020-01-01": 12.0, "2020-01-02": 5.0}  # 2020-01-03 absent -> outside overlap window

    result = find_blocked_entries(
        [trade_blocked, trade_not_blocked, trade_outside_window], drawdown_by_date, threshold_pct=10.0, cost_frac_per_leg=cost_frac
    )

    assert len(result) == 1
    r = result[0]
    assert r["symbol"] == "SPY"
    assert r["signal_date"] == "2020-01-01"
    assert r["drawdown_pct"] == pytest.approx(12.0)
    # pnl = 100 - 1.05 = 98.95; notional = 10*100 = 1000; pnl_pct = 9.895
    assert r["pnl_pct"] == pytest.approx(9.895)


def test_find_blocked_entries_boundary_exactly_at_threshold_is_blocked():
    cost_frac = 0.0005
    trade = _make_trade("SPY", "2020-01-01T00:00:00", 100.0, 105.0, 10.0, cost_frac)
    drawdown_by_date = {"2020-01-01": 10.0}
    result = find_blocked_entries([trade], drawdown_by_date, threshold_pct=10.0, cost_frac_per_leg=cost_frac)
    assert len(result) == 1


def test_find_blocked_entries_empty_when_no_trade_in_window():
    cost_frac = 0.0005
    trade = _make_trade("SPY", "2020-06-01T00:00:00", 100.0, 105.0, 10.0, cost_frac)
    drawdown_by_date = {"2020-01-01": 15.0}
    assert find_blocked_entries([trade], drawdown_by_date, threshold_pct=10.0, cost_frac_per_leg=cost_frac) == []
