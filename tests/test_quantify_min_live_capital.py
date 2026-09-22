"""
Unit tests for scripts/quantify_min_live_capital.py's PURE functions
(v85 read-only analysis, Part B). All expected values are hand-computed
in the comments below, not just asserted against the implementation's
own output. No network/Alpaca access, no src/ or existing-script
strategy logic exercised here — these tests only exercise this
milestone's own new, additive helper functions.
"""
import pytest

from scripts.quantify_min_live_capital import (
    percentile,
    apply_live_cap,
    min_equity_for_n_shares,
    unfloored_shares,
    floor_shares,
    undersizing_pct,
)


# =============================================================================
# percentile
# =============================================================================
def test_percentile_median_linear_interpolation():
    # [10,20,30,40]: k=(4-1)*0.5=1.5, f=1,c=2 -> 20 + (30-20)*0.5 = 25.0
    assert percentile([10, 20, 30, 40], 0.5) == pytest.approx(25.0)


def test_percentile_p10_linear_interpolation():
    # k=(4-1)*0.1=0.3, f=0,c=1 -> 10 + (20-10)*0.3 = 13.0
    assert percentile([10, 20, 30, 40], 0.1) == pytest.approx(13.0)


def test_percentile_unsorted_input_is_sorted_first():
    assert percentile([40, 10, 30, 20], 0.5) == pytest.approx(25.0)


def test_percentile_single_value():
    assert percentile([5.0], 0.3) == pytest.approx(5.0)


def test_percentile_p1_returns_max():
    assert percentile([10, 20, 30], 1.0) == pytest.approx(30.0)


def test_percentile_p0_returns_min():
    assert percentile([10, 20, 30], 0.0) == pytest.approx(10.0)


def test_percentile_empty_returns_none():
    assert percentile([], 0.5) is None


# =============================================================================
# apply_live_cap
# =============================================================================
def test_apply_live_cap_shrinks_above_cap():
    assert apply_live_cap(70.0, 55.0) == 55.0


def test_apply_live_cap_leaves_below_cap_unchanged():
    assert apply_live_cap(40.0, 55.0) == 40.0


def test_apply_live_cap_exactly_at_cap():
    assert apply_live_cap(55.0, 55.0) == 55.0


# =============================================================================
# min_equity_for_n_shares
# =============================================================================
def test_min_equity_for_n_shares_hand_computed():
    # E = 1 * 100 / (0.7 * 0.25) = 100 / 0.175 = 571.4285714285714...
    assert min_equity_for_n_shares(1, 100.0, 0.7, 25.0) == pytest.approx(100.0 / 0.175)


def test_min_equity_for_n_shares_scales_linearly_with_n():
    e1 = min_equity_for_n_shares(1, 50.0, 0.5, 10.0)
    e5 = min_equity_for_n_shares(5, 50.0, 0.5, 10.0)
    assert e5 == pytest.approx(e1 * 5)
    assert e1 == pytest.approx(50.0 / 0.05)  # = 1000.0


# =============================================================================
# unfloored_shares
# =============================================================================
def test_unfloored_shares_hand_computed():
    # 1000 * 0.7 * 0.25 / 100 = 175 / 100 = 1.75
    assert unfloored_shares(1000.0, 0.7, 25.0, 100.0) == pytest.approx(1.75)


def test_unfloored_shares_round_trips_with_min_equity_for_n_shares():
    # The E returned by min_equity_for_n_shares() must produce EXACTLY n
    # unfloored shares when fed back through unfloored_shares() — this is
    # the defining property of "minimum equity for N shares".
    n, price, alloc_pct, notional_pct = 3, 80.0, 0.6, 15.0
    e = min_equity_for_n_shares(n, price, alloc_pct, notional_pct)
    shares = unfloored_shares(e, alloc_pct, notional_pct, price)
    assert shares == pytest.approx(n)
    assert floor_shares(shares) == n


# =============================================================================
# floor_shares
# =============================================================================
def test_floor_shares_hand_computed():
    assert floor_shares(1.75) == 1
    assert floor_shares(3.0) == 3
    assert floor_shares(0.999999999) == 0


# =============================================================================
# undersizing_pct
# =============================================================================
def test_undersizing_pct_hand_computed():
    # (1.75 - 1) / 1.75 * 100 = 42.857142857142854
    assert undersizing_pct(1.75, 1) == pytest.approx(0.75 / 1.75 * 100)


def test_undersizing_pct_zero_reduction():
    assert undersizing_pct(3.0, 3) == pytest.approx(0.0)


def test_undersizing_pct_non_positive_unfloored_returns_zero():
    assert undersizing_pct(0.0, 0) == 0.0
    assert undersizing_pct(-1.0, 0) == 0.0
