"""
Verifies scripts/backtest_gem.py's month-end calendar construction, GEM's
relative/absolute-momentum selection rule, the holding-period trade
simulation (simulate_gem — a different trade model from every prior
finding, see module docstring), and slice_gem_trades_by_folds()'s
exit-date bucketing (including the deliberate last-fold-extends-to-end
fix and the full-vs-truncated-timestamp comparison fix) — against
deterministic synthetic daily candles and hand-built symbol_data dicts,
no network calls.
"""
from src.data_ingestion import Candle
from scripts.backtest_gem import (
    compute_month_end_dates,
    select_gem_asset,
    simulate_gem,
    compute_gem_fold_boundaries,
    slice_gem_trades_by_folds,
    GemTrade,
    MOMENTUM_LOOKBACK_MONTHS,
)


def _monthly_candle(symbol, date, close):
    return Candle(symbol, f"{date}T05:00:00+00:00", open=close, high=close, low=close, close=close, volume=100)


def _make_series(symbol, dates, closes):
    candles = [_monthly_candle(symbol, d, c) for d, c in zip(dates, closes)]
    date_index = {c.timestamp[:10]: i for i, c in enumerate(candles)}
    return {"symbol": symbol, "candles": candles, "date_index": date_index}


# --- compute_month_end_dates -------------------------------------------

def test_compute_month_end_dates_excludes_dates_in_the_same_month_as_their_successor():
    calendar = ["2016-01-29", "2016-01-30", "2016-02-27", "2016-02-28", "2016-03-15"]
    result = compute_month_end_dates(calendar)
    # Jan's last date (01-30) and Feb's last date (02-28) both have a
    # successor in a different month; 03-15 has no successor at all
    # (still the "current" month as far as this calendar knows) and 01-29
    # has a same-month successor -- neither counts.
    assert result == ["2016-01-30", "2016-02-28"]


def test_compute_month_end_dates_excludes_the_final_still_open_month():
    calendar = ["2016-01-31", "2016-02-15", "2016-02-16"]
    result = compute_month_end_dates(calendar)
    assert result == ["2016-01-31"]  # Feb has no later different-month date yet -> not a confirmed month-end


# --- select_gem_asset ----------------------------------------------------

def _one_eval_point_symbol_data(spy_now, efa_now, bil_now, spy_then=100.0, efa_then=100.0, bil_then=100.0):
    """Builds symbol_data + month_end_dates with exactly one live evaluation point (t=12)."""
    dates = [f"2016-{m:02d}-01" for m in range(1, 13)] + ["2017-01-01"]  # 13 month-end dates, t=12 is the 13th (index 12)
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
    # SPY: +30%, EFA: +10%, BIL: +5% -- SPY wins relative momentum and beats BIL
    result = select_gem_asset(symbol_data, dates, t=MOMENTUM_LOOKBACK_MONTHS)
    assert result == "SPY"


def test_select_gem_asset_picks_efa_when_it_is_the_relative_momentum_winner():
    symbol_data, dates = _one_eval_point_symbol_data(spy_now=104.0, efa_now=115.0, bil_now=90.0)
    # EFA: +15% beats SPY: +4%, and EFA beats BIL: -10%
    result = select_gem_asset(symbol_data, dates, t=MOMENTUM_LOOKBACK_MONTHS)
    assert result == "EFA"


def test_select_gem_asset_falls_back_to_agg_when_the_winner_underperforms_bil():
    symbol_data, dates = _one_eval_point_symbol_data(spy_now=90.0, efa_now=80.0, bil_now=100.0)
    # SPY: -10% (relative winner over EFA's -20%), but BIL: 0% beats it -- absolute momentum fails
    result = select_gem_asset(symbol_data, dates, t=MOMENTUM_LOOKBACK_MONTHS)
    assert result == "AGG"


# --- simulate_gem: holding-period trade model ---------------------------

def _build_switch_scenario():
    """
    15 month-end dates (indices 0-14), t=12,13,14 are live evaluation
    points. t=12: SPY wins outright (opens SPY, not a switch -- no prior
    holding). t=13: both SPY and EFA underperform BIL -> AGG selected
    (a real switch, SPY closed). t=14: SPY again underperforms BIL and
    EFA underperforms too -> AGG selected again (no switch -- final
    holding period spans t13->t14, a genuine non-zero-length eol trade).
    """
    dates = [f"2016-{m:02d}-01" for m in range(1, 13)] + ["2017-01-01", "2017-02-01", "2017-03-01"]
    spy_closes = [100.0] * 3 + [100.0] * 9 + [200.0, 90.0, 100.0]     # idx0..2 refs, idx12=200, idx13=90, idx14=100
    efa_closes = [100.0] * 3 + [100.0] * 9 + [150.0, 80.0, 80.0]      # idx12=150, idx13=80, idx14=80
    bil_closes = [100.0] * 3 + [100.0] * 9 + [105.0, 100.0, 110.0]    # idx12=105, idx13=100, idx14=110
    agg_closes = [100.0] * 3 + [100.0] * 9 + [100.0, 100.0, 105.0]    # AGG entered @t13=100, held to t14=105

    symbol_data = {
        "SPY": _make_series("SPY", dates, spy_closes),
        "EFA": _make_series("EFA", dates, efa_closes),
        "BIL": _make_series("BIL", dates, bil_closes),
        "AGG": _make_series("AGG", dates, agg_closes),
    }
    return symbol_data, dates


def test_simulate_gem_first_pick_is_not_counted_as_a_switch():
    symbol_data, dates = _build_switch_scenario()
    trades, equity_curve = simulate_gem(symbol_data, dates, capital=1000.0, fee_pct=0.0, slippage_bps=0.0)

    first_trade = trades[0]
    assert first_trade.asset == "SPY"
    assert first_trade.entry_price == 200.0


def test_simulate_gem_switch_closes_the_old_position_and_opens_the_new_one_same_day():
    symbol_data, dates = _build_switch_scenario()
    trades, equity_curve = simulate_gem(symbol_data, dates, capital=1000.0, fee_pct=0.0, slippage_bps=0.0)

    spy_trade = trades[0]
    assert spy_trade.exit_reason == "switch"
    assert spy_trade.entry_price == 200.0 and spy_trade.exit_price == 90.0
    # position_size = 1000/200 = 5; gross_pnl = 5*(90-200) = -550
    assert abs(spy_trade.gross_pnl - (-550.0)) < 1e-9
    assert abs(spy_trade.pnl - (-550.0)) < 1e-9  # zero fees in this test
    assert spy_trade.exit_timestamp == trades[1].entry_timestamp  # AGG opens same day SPY closes


def test_simulate_gem_final_holding_period_marks_to_market_as_eol_not_switch():
    symbol_data, dates = _build_switch_scenario()
    trades, equity_curve = simulate_gem(symbol_data, dates, capital=1000.0, fee_pct=0.0, slippage_bps=0.0)

    agg_trade = trades[1]
    assert agg_trade.asset == "AGG"
    assert agg_trade.exit_reason == "eol"
    assert agg_trade.entry_price == 100.0 and agg_trade.exit_price == 105.0
    assert agg_trade.entry_timestamp != agg_trade.exit_timestamp  # genuine non-zero-length holding
    assert len(trades) == 2  # exactly SPY then AGG -- no 3rd trade opened for the no-op t=14 re-selection of AGG


def test_simulate_gem_applies_fees_to_reduce_net_pnl():
    symbol_data, dates = _build_switch_scenario()
    with_fees, _ = simulate_gem(symbol_data, dates, capital=1000.0, fee_pct=0.25, slippage_bps=5.0)
    no_fees, _ = simulate_gem(symbol_data, dates, capital=1000.0, fee_pct=0.0, slippage_bps=0.0)

    assert with_fees[0].gross_pnl == no_fees[0].gross_pnl
    assert with_fees[0].pnl < no_fees[0].pnl
    assert with_fees[0].fees_paid > 0


def test_simulate_gem_sizes_at_full_notional_not_a_fraction_of_equity():
    symbol_data, dates = _build_switch_scenario()
    trades, _ = simulate_gem(symbol_data, dates, capital=1000.0, fee_pct=0.0, slippage_bps=0.0)

    position_size = trades[0].gross_pnl / (trades[0].exit_price - trades[0].entry_price)
    assert abs(position_size * trades[0].entry_price - 1000.0) < 1e-9  # full $1000 notional, not 25%


# --- compute_gem_fold_boundaries / slice_gem_trades_by_folds -----------

def test_compute_gem_fold_boundaries_splits_usable_window_into_two_halves():
    symbol_data, dates = _build_switch_scenario()  # 15 month-end dates, live_eval = dates[12:] = 3 points

    folds = compute_gem_fold_boundaries(dates, num_folds=2)

    assert len(folds) == 2
    assert folds[0]["test_start"] == dates[12]
    assert folds[1]["test_end"] == dates[14]
    assert folds[0]["test_end"] == folds[1]["test_start"]  # contiguous


def test_slice_gem_trades_by_folds_last_fold_includes_the_final_eol_trade():
    # Regression test for the deliberate fix in slice_gem_trades_by_folds:
    # a strict "<test_end" comparison on the last fold would silently drop
    # the final eol trade (its exit date exactly equals the last fold's
    # test_end by construction) -- both trades here exit ON a fold
    # boundary date (SPY on fold1/fold2's shared boundary, AGG on fold2's
    # own end), so without the fix, sum(fold trade_counts) would be 1
    # (only the switch trade counted in fold2) while pooled stays 2 -- a
    # mismatch. With the fix both land in fold 2 and the totals agree.
    symbol_data, dates = _build_switch_scenario()
    trades, equity_curve = simulate_gem(symbol_data, dates, capital=1000.0, fee_pct=0.0, slippage_bps=0.0)
    folds = compute_gem_fold_boundaries(dates, num_folds=2)

    fold_summaries, fold_switches, pooled_summary, pooled_switches = slice_gem_trades_by_folds(
        trades, equity_curve, folds, capital=1000.0
    )

    assert sum(f["trade_count"] for f in fold_summaries) == pooled_summary["trade_count"]
    assert pooled_summary["trade_count"] == 2
    assert fold_summaries[0]["trade_count"] == 0  # neither trade exits before fold1's own end boundary
    assert fold_summaries[1]["trade_count"] == 2  # both land in fold 2, including the eol trade -- not dropped


def test_slice_gem_trades_by_folds_counts_switches_but_not_eol():
    symbol_data, dates = _build_switch_scenario()
    trades, equity_curve = simulate_gem(symbol_data, dates, capital=1000.0, fee_pct=0.0, slippage_bps=0.0)
    folds = compute_gem_fold_boundaries(dates, num_folds=2)

    fold_summaries, fold_switches, pooled_summary, pooled_switches = slice_gem_trades_by_folds(
        trades, equity_curve, folds, capital=1000.0
    )

    assert pooled_switches == 1  # only the SPY->AGG switch counts, not the initial pick or the eol close
    assert sum(fold_switches) == pooled_switches


def test_slice_gem_trades_by_folds_a_trade_exiting_exactly_on_a_boundary_date_lands_in_the_later_fold():
    # Both trades here exit exactly ON a fold boundary date (SPY on the
    # fold1/fold2 shared boundary, AGG on fold2's own end). Fold
    # boundaries are bare 10-char dates while trade exit_timestamp values
    # carry a full time component -- confirmed (not assumed) that this
    # length difference doesn't change any "<" comparison outcome the
    # function relies on, so both same-boundary-date trades correctly
    # fall through to fold 2 rather than being miscounted or dropped.
    trades = [
        GemTrade("SPY", 0, 1, "2017-01-01T05:00:00+00:00", "2017-02-01T05:00:00+00:00", 100, 110, "switch", 10.0, 0.0, 10.0, 1.0),
        GemTrade("AGG", 1, 2, "2017-02-01T05:00:00+00:00", "2017-03-01T05:00:00+00:00", 110, 112, "eol", 2.0, 0.0, 2.0, 0.2),
    ]
    equity_curve = [1000.0, 1010.0, 1012.0]
    folds = [
        {"fold": 1, "test_start": "2017-01-01", "test_end": "2017-02-01"},
        {"fold": 2, "test_start": "2017-02-01", "test_end": "2017-03-01"},
    ]

    fold_summaries, fold_switches, pooled_summary, pooled_switches = slice_gem_trades_by_folds(
        trades, equity_curve, folds, capital=1000.0
    )

    assert fold_summaries[0]["trade_count"] == 0
    assert fold_summaries[1]["trade_count"] == 2  # both trades, including the eol one, land here -- neither dropped
    assert pooled_summary["trade_count"] == 2
