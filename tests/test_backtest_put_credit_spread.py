"""
Verifies scripts/backtest_put_credit_spread.py's expiry selection (3rd-
Friday computation, 30-45 DTE band + widen-fallback), strike selection
(long-strictly-below-short constraint), the data-gap fallback helper, and
simulate_from_cycles()'s pure P&L/sizing arithmetic (spec §4.1 sizing,
zero-sizing skip, expiration payoff formula) — against deterministic
synthetic data / hand-built cycle dicts, no network calls. Real calendar
values below (third-Friday dates, DTE) were computed once via the actual
functions and confirmed, not hand-guessed.
"""
from datetime import date, timedelta

from src.data_ingestion import Candle, OptionContract
from scripts.backtest_put_credit_spread import (
    third_friday,
    select_expiry,
    select_spread_strikes,
    nearest_bar_close,
    simulate_from_cycles,
    DTE_LOW,
    DTE_HIGH,
)


# --- third_friday / select_expiry --------------------------------------

def test_third_friday_is_a_friday_between_day_15_and_21():
    for year, month in [(2024, 1), (2024, 2), (2023, 12), (2025, 6), (2026, 12)]:
        d = third_friday(year, month)
        assert d.weekday() == 4
        assert 15 <= d.day <= 21


def test_select_expiry_picks_soonest_in_band_expiry():
    # 2023-12-16 (day after Dec 2023's own 3rd Friday, 2023-12-15) -> next
    # monthly expiry is 2024-01-19, DTE 34 -- inside [30, 45].
    expiry, dte, note = select_expiry(date(2023, 12, 16))
    assert expiry == date(2024, 1, 19)
    assert dte == 34
    assert DTE_LOW <= dte <= DTE_HIGH
    assert note is None


def test_select_expiry_widens_band_when_no_candidate_falls_inside():
    # 2024-01-20 (day after Jan 2024's own 3rd Friday) -> next monthly
    # expiry (2024-02-16) is only 27 DTE, below the 30-45 band -- confirmed
    # by direct computation, not assumed.
    expiry, dte, note = select_expiry(date(2024, 1, 20))
    assert expiry == date(2024, 2, 16)
    assert dte == 27
    assert note is not None
    assert "widened" in note


# --- select_spread_strikes ------------------------------------------------

def _put(strike, expiry="2024-03-15"):
    return OptionContract(symbol=f"SPY240315P{int(strike * 1000):08d}", strike_price=strike, expiration_date=expiry, option_type="put")


def test_select_spread_strikes_keeps_long_strictly_below_short():
    contracts = [_put(s) for s in [480, 490, 500, 510, 520, 530, 540]]
    # spot ~550 -> short target 522.5 (nearest 520 or 530), long target 506 (nearest 510... but must be < short)
    short_c, long_c, note = select_spread_strikes(contracts, short_target=522.5, long_target=506.0)
    assert long_c.strike_price < short_c.strike_price
    assert note is None


def test_select_spread_strikes_forces_long_below_short_even_when_targets_would_tie():
    # Coarse ladder where both targets round to the SAME nearest strike --
    # long must still land on a DIFFERENT, lower strike, not the same one.
    contracts = [_put(s) for s in [480, 500, 520]]
    short_c, long_c, note = select_spread_strikes(contracts, short_target=505.0, long_target=505.0)
    assert short_c.strike_price == 500
    assert long_c.strike_price == 480
    assert long_c.strike_price < short_c.strike_price


def test_select_spread_strikes_flags_when_no_lower_strike_exists():
    contracts = [_put(500)]
    short_c, long_c, note = select_spread_strikes(contracts, short_target=500.0, long_target=460.0)
    assert long_c is None
    assert note == "no_lower_strike_available"


# --- nearest_bar_close (data-gap fallback) ------------------------------

def _bar(date_str, close):
    return Candle(symbol="X", timestamp=f"{date_str}T00:00:00+00:00", open=close, high=close, low=close, close=close, volume=1)


def test_nearest_bar_close_exact_date_hit():
    bars = [_bar("2024-03-01", 5.0), _bar("2024-03-04", 5.5)]
    close, used_date, distance = nearest_bar_close(bars, date(2024, 3, 4))
    assert close == 5.5
    assert used_date == date(2024, 3, 4)
    assert distance == 0


def test_nearest_bar_close_falls_back_to_nearest_within_window():
    bars = [_bar("2024-03-01", 5.0), _bar("2024-03-06", 6.0)]
    close, used_date, distance = nearest_bar_close(bars, date(2024, 3, 4), max_days=5)
    # 2024-03-04 is 3 days from 03-01 and 2 days from 03-06 -- nearest is 03-06.
    assert close == 6.0
    assert used_date == date(2024, 3, 6)
    assert distance == 2


def test_nearest_bar_close_returns_none_beyond_max_days():
    bars = [_bar("2024-03-01", 5.0)]
    close, used_date, distance = nearest_bar_close(bars, date(2024, 3, 20), max_days=5)
    assert close is None


def test_nearest_bar_close_returns_none_for_empty_bars():
    assert nearest_bar_close([], date(2024, 3, 4)) == (None, None, None)


# --- simulate_from_cycles: expiration payoff + sizing -------------------

def _spy_series(dates_closes):
    candles = [_bar(d, c) for d, c in dates_closes]
    return {"symbol": "SPY", "candles": candles, "date_index": {c.timestamp[:10]: i for i, c in enumerate(candles)}}


def _cycle(entry_date, expiry_date, short_strike, long_strike, credit, spy_at_expiry, idx=0):
    return {
        "cycle_index": idx,
        "entry_date": entry_date,
        "expiry_date": expiry_date,
        "expiry_used_date": expiry_date,
        "dte": 35,
        "dte_band_note": None,
        "spot_at_entry": short_strike / 0.95,
        "short_strike": short_strike,
        "long_strike": long_strike,
        "short_symbol": "SHORT",
        "long_symbol": "LONG",
        "credit_gross_per_share": credit,
        "short_fallback_level": 0,
        "short_date_distance": 0,
        "long_fallback_level": 0,
        "long_date_distance": 0,
        "spy_close_at_expiry": spy_at_expiry,
    }


def test_expired_otm_keeps_full_credit():
    # Short 480, long 460, spot never breaches short -> spread expires worthless, full credit kept.
    spy = _spy_series([("2024-03-01", 500), ("2024-04-19", 510)])
    cycles = [_cycle("2024-03-01", "2024-04-19", short_strike=480, long_strike=460, credit=2.0, spy_at_expiry=510)]
    trades, curve, skipped = simulate_from_cycles(cycles, spy, capital=1_000_000, slippage_per_leg_dollars=0.0)
    assert len(trades) == 1
    t = trades[0]
    assert t.exit_reason == "expired_otm"
    assert t.pnl == 2.0 * 100 * t.contracts
    assert not skipped


def test_expired_itm_max_loss_caps_at_spread_width():
    # SPY collapses below BOTH strikes -> max loss = (width - credit) per contract, not unbounded.
    spy = _spy_series([("2024-03-01", 500), ("2024-04-19", 400)])
    cycles = [_cycle("2024-03-01", "2024-04-19", short_strike=480, long_strike=460, credit=2.0, spy_at_expiry=400)]
    trades, curve, skipped = simulate_from_cycles(cycles, spy, capital=1_000_000, slippage_per_leg_dollars=0.0)
    t = trades[0]
    assert t.exit_reason == "expired_itm_max_loss"
    width = 480 - 460
    expected_loss_per_share = width - 2.0  # credit only partially offsets the max width loss
    assert t.pnl == -expected_loss_per_share * 100 * t.contracts


def test_expired_itm_partial_between_strikes():
    # SPY settles strictly between the two strikes -> partial intrinsic loss, not the full width.
    spy = _spy_series([("2024-03-01", 500), ("2024-04-19", 470)])
    cycles = [_cycle("2024-03-01", "2024-04-19", short_strike=480, long_strike=460, credit=2.0, spy_at_expiry=470)]
    trades, curve, skipped = simulate_from_cycles(cycles, spy, capital=1_000_000, slippage_per_leg_dollars=0.0)
    t = trades[0]
    assert t.exit_reason == "expired_itm_partial"
    intrinsic = 480 - 470  # short leg intrinsic only, long leg still worthless
    assert 0 < intrinsic < (480 - 460)
    assert t.pnl == (2.0 - intrinsic) * 100 * t.contracts


def test_sizing_floors_to_zero_and_skips_when_risk_budget_too_small():
    # Tiny capital relative to a wide spread's max loss -> 0 contracts, cycle skipped, equity unchanged.
    spy = _spy_series([("2024-03-01", 500), ("2024-04-19", 510)])
    cycles = [_cycle("2024-03-01", "2024-04-19", short_strike=480, long_strike=460, credit=2.0, spy_at_expiry=510)]
    trades, curve, skipped = simulate_from_cycles(cycles, spy, capital=100.0, slippage_per_leg_dollars=0.0)
    assert trades == []
    assert curve == [100.0]
    assert len(skipped) == 1
    assert skipped[0]["reason"] == "sizing_floor_zero"


def test_slippage_reduces_credit_and_can_change_sizing_vs_gross():
    # Same cycle, same capital: a slippage assumption large enough to erase
    # the credit should make max_loss_per_contract larger (or credit
    # non-positive), producing fewer or zero contracts vs. a zero-slippage run.
    spy = _spy_series([("2024-03-01", 500), ("2024-04-19", 505)])
    cycles = [_cycle("2024-03-01", "2024-04-19", short_strike=480, long_strike=460, credit=0.05, spy_at_expiry=505)]
    net_trades, _, net_skipped = simulate_from_cycles(cycles, spy, capital=1_000_000, slippage_per_leg_dollars=0.10)
    gross_trades, _, _ = simulate_from_cycles(cycles, spy, capital=1_000_000, slippage_per_leg_dollars=0.0)
    assert gross_trades  # a real (tiny) credit still produces a trade gross-of-cost
    assert not net_trades  # 0.05 credit minus 2*0.10 slippage is negative -> skipped net-of-cost
    assert net_skipped[0]["reason"] == "non_positive_credit"


def test_cycle_advances_calendar_even_when_skipped():
    # Sizing skip must not stall the cycle clock -- verified at the
    # simulate_from_cycles level: a skip still consumes the cycle, equity
    # curve stays exactly at the starting value (no phantom P&L).
    spy = _spy_series([("2024-03-01", 500), ("2024-04-19", 510), ("2024-05-17", 520)])
    cycles = [
        _cycle("2024-03-01", "2024-04-19", short_strike=480, long_strike=460, credit=2.0, spy_at_expiry=510, idx=0),
        _cycle("2024-04-22", "2024-05-17", short_strike=490, long_strike=470, credit=3.0, spy_at_expiry=520, idx=1),
    ]
    trades, curve, skipped = simulate_from_cycles(cycles, spy, capital=100.0, slippage_per_leg_dollars=0.0)
    assert trades == []
    assert len(skipped) == 2
    assert curve == [100.0]
