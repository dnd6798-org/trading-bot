"""
Verifies scripts/backtest_gem.py: month-end calendar construction, GEM's
relative/absolute-momentum selection rule, the CONTINUOUS DAY-BY-DAY
holding-period simulation (simulate_gem — iterates the full daily
calendar so the circuit breaker can check drawdown daily and force a
mid-month exit), the PEAK-RESET FIX (tracked peak resets to current
equity at resume, not the strategy's never-reset all-time peak),
slice_gem_trades_by_folds()'s exit-date bucketing, and the continuous-
drawdown/cost-attribution helpers (compute_max_drawdown_pct,
slice_continuous_drawdown_by_folds, compute_leg_max_drawdowns,
attribute_breaker_costs) — against deterministic synthetic daily candles
and hand-built symbol_data dicts, no network calls.
"""
from src.data_ingestion import Candle
from scripts.backtest_gem import (
    compute_month_end_dates,
    select_gem_asset,
    simulate_gem,
    compute_gem_fold_boundaries,
    slice_gem_trades_by_folds,
    compute_max_drawdown_pct,
    slice_continuous_drawdown_by_folds,
    compute_leg_max_drawdowns,
    attribute_breaker_costs,
    GemTrade,
    MOMENTUM_LOOKBACK_MONTHS,
)


def _daily_candle(symbol, date, close):
    return Candle(symbol, f"{date}T05:00:00+00:00", open=close, high=close, low=close, close=close, volume=100)


def _make_series(symbol, dates, closes):
    candles = [_daily_candle(symbol, d, c) for d, c in zip(dates, closes)]
    date_index = {c.timestamp[:10]: i for i, c in enumerate(candles)}
    return {"symbol": symbol, "candles": candles, "date_index": date_index}


# --- compute_month_end_dates -------------------------------------------

def test_compute_month_end_dates_excludes_dates_in_the_same_month_as_their_successor():
    calendar = ["2016-01-29", "2016-01-30", "2016-02-27", "2016-02-28", "2016-03-15"]
    result = compute_month_end_dates(calendar)
    assert result == ["2016-01-30", "2016-02-28"]


def test_compute_month_end_dates_excludes_the_final_still_open_month():
    calendar = ["2016-01-31", "2016-02-15", "2016-02-16"]
    result = compute_month_end_dates(calendar)
    assert result == ["2016-01-31"]


# --- select_gem_asset ----------------------------------------------------

def _one_eval_point_symbol_data(spy_now, efa_now, bil_now, spy_then=100.0, efa_then=100.0, bil_then=100.0):
    dates = [f"2016-{m:02d}-01" for m in range(1, 13)] + ["2017-01-01"]
    spy_closes = [spy_then] + [100.0] * 11 + [spy_now]
    efa_closes = [efa_then] + [100.0] * 11 + [efa_now]
    bil_closes = [bil_then] + [100.0] * 11 + [bil_now]
    symbol_data = {
        "SPY": _make_series("SPY", dates, spy_closes),
        "EFA": _make_series("EFA", dates, efa_closes),
        "BIL": _make_series("BIL", dates, bil_closes),
    }
    return symbol_data, dates


def test_select_gem_asset_picks_relative_momentum_winner_when_it_beats_bil():
    symbol_data, dates = _one_eval_point_symbol_data(spy_now=130.0, efa_now=110.0, bil_now=105.0)
    assert select_gem_asset(symbol_data, dates, t=MOMENTUM_LOOKBACK_MONTHS) == "SPY"


def test_select_gem_asset_picks_efa_when_it_is_the_relative_momentum_winner():
    symbol_data, dates = _one_eval_point_symbol_data(spy_now=104.0, efa_now=115.0, bil_now=90.0)
    assert select_gem_asset(symbol_data, dates, t=MOMENTUM_LOOKBACK_MONTHS) == "EFA"


def test_select_gem_asset_falls_back_to_agg_when_the_winner_underperforms_bil():
    symbol_data, dates = _one_eval_point_symbol_data(spy_now=90.0, efa_now=80.0, bil_now=100.0)
    assert select_gem_asset(symbol_data, dates, t=MOMENTUM_LOOKBACK_MONTHS) == "AGG"


# --- compute_max_drawdown_pct -------------------------------------------

def test_compute_max_drawdown_pct_basic_peak_to_trough():
    assert abs(compute_max_drawdown_pct([100, 120, 90, 100, 95]) - 25.0) < 1e-9


def test_compute_max_drawdown_pct_empty_series_returns_zero():
    assert compute_max_drawdown_pct([]) == 0.0


# --- fixture: a scenario with a mid-month circuit-breaker trigger -------

def _breach_scenario():
    """
    14 month-end dates (t=12,13 live). t=12 ("2017-01-31"): SPY wins
    outright (100% trailing return vs EFA's 50%, beats BIL's 5%) -> opens
    SPY @200. Between t=12 and t=13, 5 intra-month trading days are added
    to `calendar` (not part of month_end_dates) during which SPY's price
    falls from 200 to 169 (-15.5%) then partially "recovers" to 198 --
    enough to cross a 15% breaker threshold but NOT a 20% one, and enough
    to test that recovery doesn't cause an early resume. t=13
    ("2017-02-28"): SPY(0%) beats EFA(-10%) but loses to BIL(10%) -> AGG
    selected, testing that resume lands wherever GEM currently prescribes
    (not necessarily back into the asset that breached, and not into
    BIL itself).

    Returns (symbol_data, month_end_dates, calendar).
    """
    month_end_dates = [f"2016-{m:02d}-01" for m in range(1, 13)] + ["2017-01-31", "2017-02-28"]
    intramonth = ["2017-02-01", "2017-02-02", "2017-02-03", "2017-02-06", "2017-02-07"]
    calendar = ["2017-01-31"] + intramonth + ["2017-02-28"]

    # idx0=100 (t=12's -12mo ref), idx1=195 (t=13's -12mo ref -- matched to
    # idx13 below so SPY's OWN trailing return at t=13 is exactly 0%
    # without implying any extra intrinsic price move beyond the
    # intra-month path already modeled -- keeping SPY's t=13 exit price
    # close to where the intra-month path leaves it, isolating the
    # breach test from an unrelated large move at the month-end switch).
    spy_closes_monthend = [100.0, 195.0] + [100.0] * 10 + [200.0, 195.0]  # idx0,idx1,idx2..11,idx12=200,idx13=195
    efa_closes_monthend = [100.0] + [100.0] * 11 + [150.0, 90.0]
    bil_closes_monthend = [100.0] + [100.0] * 11 + [105.0, 110.0]
    agg_closes_monthend = [100.0] * 12 + [100.0, 100.0]

    spy_intramonth = {"2017-02-01": 180.0, "2017-02-02": 169.0, "2017-02-03": 165.0, "2017-02-06": 195.0, "2017-02-07": 198.0}
    bil_intramonth = {d: 105.0 for d in intramonth}
    efa_intramonth = {d: 100.0 for d in intramonth}
    agg_intramonth = {d: 100.0 for d in intramonth}

    def _series(symbol, monthend_closes, intramonth_closes):
        dates = month_end_dates[:12] + ["2017-01-31"] + intramonth + ["2017-02-28"]
        closes = monthend_closes[:12] + [monthend_closes[12]] + [intramonth_closes[d] for d in intramonth] + [monthend_closes[13]]
        return _make_series(symbol, dates, closes)

    symbol_data = {
        "SPY": _series("SPY", spy_closes_monthend, spy_intramonth),
        "EFA": _series("EFA", efa_closes_monthend, efa_intramonth),
        "BIL": _series("BIL", bil_closes_monthend, bil_intramonth),
        "AGG": _series("AGG", agg_closes_monthend, agg_intramonth),
    }
    return symbol_data, month_end_dates, calendar


# --- simulate_gem: circuit breaker mechanics ----------------------------

def test_simulate_gem_no_breaker_holds_through_the_full_drawdown():
    symbol_data, month_end_dates, calendar = _breach_scenario()
    trades, trade_curve, daily_curve, reset_dates = simulate_gem(
        symbol_data, calendar, month_end_dates, capital=1000.0, fee_pct=0.0, slippage_bps=0.0,
        breaker_drawdown_pct=None,
    )
    # No breach: SPY is held straight through to the next scheduled switch at t=13.
    assert [t.asset for t in trades] == ["SPY", "AGG"]
    assert trades[0].exit_reason == "switch"
    assert trades[0].exit_price == 195.0  # SPY's own price at "2017-02-28"


def test_simulate_gem_breach_triggers_when_drawdown_crosses_threshold():
    symbol_data, month_end_dates, calendar = _breach_scenario()
    trades, trade_curve, daily_curve, reset_dates = simulate_gem(
        symbol_data, calendar, month_end_dates, capital=1000.0, fee_pct=0.0, slippage_bps=0.0,
        breaker_drawdown_pct=15.0,
    )

    spy_trade = trades[0]
    assert spy_trade.exit_reason == "circuit_breaker"
    assert spy_trade.exit_timestamp[:10] == "2017-02-02"  # first day drawdown reaches -15.5%
    assert spy_trade.exit_price == 169.0
    # position_size = 1000/200 = 5; gross_pnl = 5*(169-200) = -155
    assert abs(spy_trade.gross_pnl - (-155.0)) < 1e-9

    bil_trade = trades[1]
    assert bil_trade.asset == "BIL"
    assert bil_trade.entry_timestamp[:10] == "2017-02-02"
    assert bil_trade.entry_price == 105.0


def test_simulate_gem_no_breach_when_drawdown_stays_below_threshold():
    symbol_data, month_end_dates, calendar = _breach_scenario()
    # Same price path (max drawdown ~15.5%) but a 20% threshold should never trigger.
    trades, trade_curve, daily_curve, reset_dates = simulate_gem(
        symbol_data, calendar, month_end_dates, capital=1000.0, fee_pct=0.0, slippage_bps=0.0,
        breaker_drawdown_pct=20.0,
    )
    assert all(t.exit_reason != "circuit_breaker" for t in trades)
    assert [t.asset for t in trades] == ["SPY", "AGG"]


def test_simulate_gem_stays_in_breach_across_multiple_days_without_rechecking():
    symbol_data, month_end_dates, calendar = _breach_scenario()
    trades, trade_curve, daily_curve, reset_dates = simulate_gem(
        symbol_data, calendar, month_end_dates, capital=1000.0, fee_pct=0.0, slippage_bps=0.0,
        breaker_drawdown_pct=15.0,
    )
    # Exactly one circuit_breaker trade -- SPY's later "recovery" to 195/198
    # (irrelevant once out of the position) must not cause a second breach
    # or an early switch back before the next scheduled evaluation.
    breach_trades = [t for t in trades if t.exit_reason == "circuit_breaker"]
    assert len(breach_trades) == 1
    assert trades[1].asset == "BIL"
    assert trades[1].exit_timestamp[:10] == "2017-02-28"  # BIL held all the way to the next scheduled eval


def test_simulate_gem_resumes_unconditionally_at_next_evaluation_into_whatever_gem_prescribes():
    symbol_data, month_end_dates, calendar = _breach_scenario()
    trades, trade_curve, daily_curve, reset_dates = simulate_gem(
        symbol_data, calendar, month_end_dates, capital=1000.0, fee_pct=0.0, slippage_bps=0.0,
        breaker_drawdown_pct=15.0,
    )
    # Resume lands on AGG (what GEM prescribes at t=13), not back into SPY
    # (the asset that breached) and not staying in BIL.
    resumed = trades[2]
    assert resumed.asset == "AGG"
    assert resumed.entry_timestamp[:10] == "2017-02-28"
    assert trades[1].exit_reason == "resume"  # the BIL holding closes via a forced resume, distinct from a normal switch


def test_simulate_gem_daily_equity_curve_has_one_entry_per_calendar_day():
    symbol_data, month_end_dates, calendar = _breach_scenario()
    trades, trade_curve, daily_curve, reset_dates = simulate_gem(
        symbol_data, calendar, month_end_dates, capital=1000.0, fee_pct=0.0, slippage_bps=0.0,
        breaker_drawdown_pct=15.0,
    )
    assert len(daily_curve) == len(calendar) == 7
    assert [d for d, _ in daily_curve] == calendar
    assert abs(daily_curve[0][1] - 1000.0) < 1e-9  # entry day, no return yet
    assert abs(daily_curve[1][1] - 900.0) < 1e-9   # 1000 * 180/200


def test_simulate_gem_breach_exit_reflects_post_fee_equity_in_the_daily_curve():
    symbol_data, month_end_dates, calendar = _breach_scenario()
    _, _, daily_curve_no_fees, _ = simulate_gem(
        symbol_data, calendar, month_end_dates, capital=1000.0, fee_pct=0.0, slippage_bps=0.0,
        breaker_drawdown_pct=15.0,
    )
    _, _, daily_curve_with_fees, _ = simulate_gem(
        symbol_data, calendar, month_end_dates, capital=1000.0, fee_pct=0.25, slippage_bps=5.0,
        breaker_drawdown_pct=15.0,
    )
    # The breach day's recorded equity must be strictly lower with fees than
    # without -- confirming the daily curve was overwritten with post-fee
    # equity, not left at the pre-fee mark-to-market value.
    breach_day_equity_no_fees = dict(daily_curve_no_fees)["2017-02-02"]
    breach_day_equity_with_fees = dict(daily_curve_with_fees)["2017-02-02"]
    assert breach_day_equity_with_fees < breach_day_equity_no_fees


def test_simulate_gem_reset_dates_start_with_calendar_start_and_gain_one_entry_per_resume():
    symbol_data, month_end_dates, calendar = _breach_scenario()
    trades, trade_curve, daily_curve, reset_dates = simulate_gem(
        symbol_data, calendar, month_end_dates, capital=1000.0, fee_pct=0.0, slippage_bps=0.0,
        breaker_drawdown_pct=15.0,
    )
    assert reset_dates[0] == calendar[0]
    assert reset_dates[-1] == "2017-02-28"  # the one resume in this scenario
    assert len(reset_dates) == 2


# --- PEAK-RESET FIX: the core regression test for this session's fix ---

def _reset_fix_scenario():
    """
    t=12 opens SPY, which then drops 50% intramonth (idx13, "2017-02-01")
    -- a genuine breach into BIL. At t=13 ("2017-02-28"), GEM resumes into
    AGG. Under the FIX, the tracked peak resets to equity AT THE MOMENT
    OF RESUME (550, in this scenario), not the original all-time peak
    (1000). A subsequent MODEST 10% decline in AGG (well under the 15%
    threshold measured from the reset point) must NOT trigger a second
    breach -- even though, measured against the ORIGINAL peak, that same
    equity level would represent a ~50% drawdown and have immediately
    re-triggered under the pre-fix (rejected) design.
    """
    month_end_dates = [f"2016-{m:02d}-01" for m in range(1, 13)] + ["2017-01-31", "2017-02-28"]
    calendar = ["2017-01-31", "2017-02-01", "2017-02-28", "2017-03-15"]

    # idx0..11 = warm-up (all 100, including idx0/idx1 used as -12mo refs),
    # then idx12="2017-01-31"(t12), idx13="2017-02-01"(breach day),
    # idx14="2017-02-28"(t13), idx15="2017-03-15"(post-resume decline day).
    spy_closes = [100.0] * 12 + [200.0, 100.0, 100.0, 100.0]   # t12 entry 200 -> breach day 100 (-50%); idx14=100 -> t13 trailing return 0%
    efa_closes = [100.0] * 12 + [100.0, 100.0, 90.0, 100.0]     # t12: 0% (loses to SPY's 100%); idx14=90 -> t13 trailing return -10%
    bil_closes = [100.0] * 12 + [100.0, 100.0, 110.0, 100.0]    # t12: 0% (SPY beats it); idx14=110 -> t13 trailing return +10% (beats both SPY/EFA -> AGG selected)
    agg_closes = [100.0] * 12 + [100.0, 100.0, 100.0, 90.0]     # entered @100 at t13, drops 10% intramonth to 90

    symbol_data = {
        "SPY": _make_series("SPY", month_end_dates[:12] + calendar, spy_closes),
        "EFA": _make_series("EFA", month_end_dates[:12] + calendar, efa_closes),
        "BIL": _make_series("BIL", month_end_dates[:12] + calendar, bil_closes),
        "AGG": _make_series("AGG", month_end_dates[:12] + calendar, agg_closes),
    }
    return symbol_data, month_end_dates, calendar


def test_simulate_gem_peak_reset_prevents_immediate_rebreach_on_resume():
    symbol_data, month_end_dates, calendar = _reset_fix_scenario()
    trades, trade_curve, daily_curve, reset_dates = simulate_gem(
        symbol_data, calendar, month_end_dates, capital=1000.0, fee_pct=0.0, slippage_bps=0.0,
        breaker_drawdown_pct=15.0,
    )

    # Exactly one genuine breach (SPY, multi-day), one resume (BIL -> AGG),
    # and NO second breach despite AGG's later 10%-from-reset-peak decline
    # -- confirming the reset actually prevents the whipsaw the pre-fix
    # design fell into.
    assert [t.exit_reason for t in trades] == ["circuit_breaker", "resume", "eol"]
    assert trades[0].entry_timestamp[:10] != trades[0].exit_timestamp[:10]  # genuine, not zero-day

    resumed = trades[2]
    assert resumed.asset == "AGG"
    # entry_equity at resume = 500 (post-breach) + 50 (BIL's tiny gain while held) = 550
    assert abs(resumed.entry_price - 100.0) < 1e-9


def test_simulate_gem_peak_resets_to_post_resume_equity_not_the_original_peak():
    symbol_data, month_end_dates, calendar = _reset_fix_scenario()
    trades, trade_curve, daily_curve, reset_dates = simulate_gem(
        symbol_data, calendar, month_end_dates, capital=1000.0, fee_pct=0.0, slippage_bps=0.0,
        breaker_drawdown_pct=15.0,
    )
    resume_equity = dict(daily_curve)["2017-02-28"]
    # The post-resume mark (550) is nowhere near the original peak (1000)
    # -- if the peak had NOT been reset, this same day would already read
    # as a (1000-550)/1000 = 45% drawdown, well past the 15% threshold,
    # and would have immediately re-triggered. It didn't (see the
    # previous test), confirming the reset actually took effect.
    assert abs(resume_equity - 550.0) < 1e-9
    original_peak_relative_dd = (1000.0 - resume_equity) / 1000.0 * 100
    assert original_peak_relative_dd > 15.0  # would have re-triggered under the old, rejected design
    assert trades[1].exit_reason == "resume" and len(trades) == 3  # confirms no re-breach actually occurred


# --- compute_leg_max_drawdowns -------------------------------------------

def test_compute_leg_max_drawdowns_splits_by_reset_points_and_uses_local_peaks():
    daily_equity_curve = [("d1", 1000.0), ("d2", 500.0), ("d3", 550.0), ("d4", 495.0)]
    reset_dates = ["d1", "d3"]

    leg_dds, worst = compute_leg_max_drawdowns(daily_equity_curve, reset_dates)

    assert len(leg_dds) == 2
    assert abs(leg_dds[0] - 50.0) < 1e-9  # leg 1 [d1,d3): peak 1000 (d1), trough 500 (d2) -> 50%
    assert abs(leg_dds[1] - 10.0) < 1e-9  # leg 2 [d3,d4]: peak resets to 550 (d3), trough 495 (d4) -> 10%
    assert abs(worst - 50.0) < 1e-9


def test_compute_leg_max_drawdowns_empty_curve_returns_empty():
    leg_dds, worst = compute_leg_max_drawdowns([], [])
    assert leg_dds == []
    assert worst == 0.0


# --- attribute_breaker_costs ---------------------------------------------

def test_attribute_breaker_costs_splits_fees_by_exit_reason():
    trades = [
        GemTrade("SPY", 0, 1, "t0", "t1", 100, 90, "circuit_breaker", -10.0, 5.0, -15.0, -1.0),
        GemTrade("BIL", 1, 2, "t1", "t2", 90, 92, "resume", 2.0, 1.0, 1.0, 0.1),
        GemTrade("AGG", 2, 3, "t2", "t3", 92, 95, "switch", 3.0, 2.0, 1.0, 0.1),
        GemTrade("AGG", 3, 4, "t3", "t4", 95, 96, "eol", 1.0, 0.5, 0.5, 0.05),
    ]

    breach_fees, resume_fees, normal_fees = attribute_breaker_costs(trades)

    assert abs(breach_fees - 5.0) < 1e-9
    assert abs(resume_fees - 1.0) < 1e-9
    assert abs(normal_fees - 2.5) < 1e-9  # switch(2.0) + eol(0.5)


# --- compute_gem_fold_boundaries / slice_gem_trades_by_folds -----------

def test_compute_gem_fold_boundaries_splits_usable_window_into_two_halves():
    month_end_dates = [f"2016-{m:02d}-01" for m in range(1, 13)] + ["2017-01-01", "2017-02-01", "2017-03-01"]
    folds = compute_gem_fold_boundaries(month_end_dates, num_folds=2)
    assert len(folds) == 2
    assert folds[0]["test_start"] == month_end_dates[12]
    assert folds[1]["test_end"] == month_end_dates[14]
    assert folds[0]["test_end"] == folds[1]["test_start"]


def test_slice_gem_trades_by_folds_last_fold_includes_the_final_eol_trade_and_counts_breaches_separately():
    trades = [
        GemTrade("SPY", 0, 1, "2017-01-01T05:00:00+00:00", "2017-02-01T05:00:00+00:00", 100, 90, "circuit_breaker", -10.0, 0.0, -10.0, -1.0),
        GemTrade("BIL", 1, 2, "2017-02-01T05:00:00+00:00", "2017-03-01T05:00:00+00:00", 105, 106, "eol", 1.0, 0.0, 1.0, 0.1),
    ]
    equity_curve = [1000.0, 990.0, 991.0]
    folds = [
        {"fold": 1, "test_start": "2017-01-01", "test_end": "2017-02-01"},
        {"fold": 2, "test_start": "2017-02-01", "test_end": "2017-03-01"},
    ]

    fold_summaries, fold_switches, fold_breaches, pooled_summary, pooled_switches, pooled_breaches = slice_gem_trades_by_folds(
        trades, equity_curve, folds, capital=1000.0
    )

    assert sum(f["trade_count"] for f in fold_summaries) == pooled_summary["trade_count"] == 2
    assert fold_summaries[0]["trade_count"] == 0
    assert fold_summaries[1]["trade_count"] == 2  # both land in fold 2, including the eol trade
    assert pooled_breaches == 1
    assert pooled_switches == 0  # neither trade's exit_reason is "switch"/"resume" in this scenario
    assert sum(fold_breaches) == pooled_breaches


def test_slice_gem_trades_by_folds_counts_resume_as_a_switch_for_position_change_purposes():
    trades = [
        GemTrade("SPY", 0, 1, "2017-01-01T05:00:00+00:00", "2017-01-15T05:00:00+00:00", 100, 90, "circuit_breaker", -10.0, 0.0, -10.0, -1.0),
        GemTrade("BIL", 1, 2, "2017-01-15T05:00:00+00:00", "2017-02-01T05:00:00+00:00", 105, 106, "resume", 1.0, 0.0, 1.0, 0.1),
    ]
    equity_curve = [1000.0, 990.0, 991.0]
    folds = [{"fold": 1, "test_start": "2017-01-01", "test_end": "2017-02-01"}]

    _, fold_switches, fold_breaches, _, pooled_switches, pooled_breaches = slice_gem_trades_by_folds(
        trades, equity_curve, folds, capital=1000.0
    )

    assert pooled_switches == 1  # the "resume" trade counts as a position change
    assert pooled_breaches == 1


# --- slice_continuous_drawdown_by_folds ---------------------------------

def test_slice_continuous_drawdown_by_folds_fold_relative_vs_global_peak():
    # Peak of 120 occurs in fold 1 (at d2); fold 2's OWN local peak resets
    # to 100 (at d4), understating the true worst-case relative to the
    # actual all-time high. The pooled figure must use the GLOBAL peak
    # and therefore match fold 1's own number (the worst drop happened
    # relative to the all-time peak, which sits in fold 1's window).
    daily_equity_curve = [("d1", 100.0), ("d2", 120.0), ("d3", 90.0), ("d4", 100.0), ("d5", 95.0)]
    folds = [
        {"fold": 1, "test_start": "d1", "test_end": "d3"},
        {"fold": 2, "test_start": "d3", "test_end": "d5"},
    ]

    fold_dds, pooled_global_dd = slice_continuous_drawdown_by_folds(daily_equity_curve, folds)

    assert abs(fold_dds[0] - 25.0) < 1e-9   # (120-90)/120
    assert abs(fold_dds[1] - 5.0) < 1e-9    # fold-relative peak resets to 100 at d4; (100-95)/100
    assert abs(pooled_global_dd - 25.0) < 1e-9  # global peak (120) drives the pooled figure, not fold 2's local one
