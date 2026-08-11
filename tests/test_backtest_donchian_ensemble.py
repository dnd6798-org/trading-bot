"""
Verifies scripts/backtest_donchian_ensemble.py's finding-14 single-channel
100-day entry signal (widened from finding 12-13's 55-day), the rotational
portfolio simulation loop (8-slot cap, same-day slot reuse, shared-equity
position sizing, EOL exit per symbol), the exit-timestamp-based
fold-slicing, finding 13's two infrastructure pieces (portfolio-level
total-risk-budget sizing, still active in finding 14; weekly
entry-evaluation gating, still available but no longer invoked by
finding 14's main()), and finding 14's buy-and-hold benchmark helpers —
against deterministic synthetic daily candles and hand-built symbol_data
dicts, no network calls.
"""
from src.data_ingestion import Candle
from scripts.backtest_donchian_ensemble import (
    compute_channel_long_entry_indices,
    compute_weekly_entry_evaluation_dates,
    compute_buy_and_hold_symbol_return,
    compute_buy_and_hold_portfolio_return,
    simulate_rotational_ensemble,
    slice_ensemble_trades_by_folds,
    EnsembleTrade,
)


def _flat_candle(symbol, date, close=100.0, volume=10):
    return Candle(symbol, date, open=close, high=close + 5, low=close - 5, close=close, volume=volume)


def _candle(symbol, date, close, high=None, low=None, volume=10):
    return Candle(
        symbol, date, open=close,
        high=high if high is not None else close + 5,
        low=low if low is not None else close - 5,
        close=close, volume=volume,
    )


def _make_series(symbol, candles, atr, entry_indices):
    return {
        "symbol": symbol,
        "candles": candles,
        "atr": atr,
        "entry_indices": set(entry_indices),
        "date_index": {c.timestamp[:10]: i for i, c in enumerate(candles)},
    }


# --- compute_channel_long_entry_indices --------------------------------

def test_channel_entry_does_not_fire_before_100d_window_is_seeded():
    # Only 20 seasoning days — the 100-day band isn't defined yet, so even
    # a sharp breakout candle must not register as an entry.
    dates = [f"2021-01-{i + 1:02d}" for i in range(21)]
    candles = [_flat_candle("BTC/USD", dates[i]) for i in range(20)]
    candles.append(_candle("BTC/USD", dates[20], close=125, high=130, low=120))

    entry_indices, atr = compute_channel_long_entry_indices(candles)

    assert 20 not in entry_indices


def test_channel_entry_fires_on_close_above_100d_band_once_window_is_seeded():
    # 100 seasoning days (enough for the 100-day band to be fully defined),
    # then a single breakout day.
    dates = [f"d{i}" for i in range(101)]
    candles = [_flat_candle("BTC/USD", dates[i]) for i in range(100)]
    candles.append(_candle("BTC/USD", dates[100], close=125, high=130, low=120))

    entry_indices, atr = compute_channel_long_entry_indices(candles)

    assert 100 in entry_indices
    assert atr[100] is not None


# --- simulate_rotational_ensemble: slot cap & skip logging ------------------

def test_simulate_rotational_ensemble_skips_signal_when_all_slots_full():
    dates = ["2021-01-01", "2021-01-02"]
    universe = ["A", "B", "C", "D", "E"]
    symbol_data = {}
    for sym in universe:
        candles = [_candle(sym, dates[0], close=100, high=105, low=95), _flat_candle(sym, dates[1], close=100)]
        symbol_data[sym] = _make_series(sym, candles, atr=[10.0, 10.0], entry_indices=[0])

    trades, equity_curve, skipped_log = simulate_rotational_ensemble(
        symbol_data, universe, max_positions=4, atr_multiplier=2.5,
        capital=100.0, fee_pct=0.0, slippage_bps=0.0,
    )

    entered_symbols = {t.symbol for t in trades}
    assert entered_symbols == {"A", "B", "C", "D"}
    assert any(s["symbol"] == "E" and s["date"] == "2021-01-01" for s in skipped_log)


# --- simulate_rotational_ensemble: same-day slot reuse -----------------------

def test_simulate_rotational_ensemble_reuses_slot_freed_by_same_day_exit():
    d0, d1, d2 = "2021-01-01", "2021-01-02", "2021-01-03"
    universe = ["A", "B", "C", "D", "E"]
    symbol_data = {}

    # A: enters day0 at 100, ATR 10 -> stop = 100 - 2.5*10 = 75. Day1 low=70 hits it.
    symbol_data["A"] = _make_series(
        "A",
        [_candle("A", d0, close=100, high=105, low=95),
         _candle("A", d1, close=80, high=85, low=70)],
        atr=[10.0, 10.0], entry_indices=[0],
    )
    # B, C, D: enter day0 at 200, stay well above their stop (175) through day1, EOL-close day2.
    for sym in ("B", "C", "D"):
        symbol_data[sym] = _make_series(
            sym,
            [_candle(sym, d0, close=200, high=205, low=195),
             _candle(sym, d1, close=200, high=205, low=195),
             _flat_candle(sym, d2, close=200)],
            atr=[10.0, 10.0, 10.0], entry_indices=[0],
        )
    # E: only appears starting day1, fires an entry that day.
    symbol_data["E"] = _make_series(
        "E",
        [_candle("E", d1, close=50, high=55, low=45),
         _flat_candle("E", d2, close=50)],
        atr=[10.0, 10.0], entry_indices=[0],
    )

    trades, equity_curve, skipped_log = simulate_rotational_ensemble(
        symbol_data, universe, max_positions=4, atr_multiplier=2.5,
        capital=100.0, fee_pct=0.0, slippage_bps=0.0,
    )

    a_trade = next(t for t in trades if t.symbol == "A")
    assert a_trade.exit_reason == "trailing_stop"
    assert a_trade.exit_timestamp == d1

    e_trade = next((t for t in trades if t.symbol == "E"), None)
    assert e_trade is not None, "E should have entered day1 once A's exit freed a slot"
    assert e_trade.entry_timestamp == d1
    assert not any(s["symbol"] == "E" for s in skipped_log)


# --- simulate_rotational_ensemble: sizing & EOL ------------------------------

def test_simulate_rotational_ensemble_sizes_off_shared_equity_and_caps_at_notional_sanity_backstop():
    dates = ["2021-01-01", "2021-01-02"]
    symbol_data = {
        "A": _make_series(
            "A",
            # Day1's low (99.6) stays just above the tiny 0.05*ATR stop
            # (100 - 0.5 = 99.5), so this resolves as "eol" rather than
            # "trailing_stop" — isolates the position-size cap from the
            # exit-trigger mechanics already covered elsewhere.
            [_candle("A", dates[0], close=100, high=105, low=95), _candle("A", dates[1], close=100, high=100.5, low=99.6)],
            atr=[10.0, 10.0], entry_indices=[0],
        ),
    }

    # Finding 13: the flat max_position_pct notional cap is gone — this
    # now exercises the loose notional_sanity_cap_pct backstop instead
    # (a tiny atr_multiplier still produces an oversized risk-based size).
    trades, equity_curve, skipped_log = simulate_rotational_ensemble(
        symbol_data, ["A"], max_positions=4, atr_multiplier=0.05,  # tiny stop distance -> oversized risk-based size
        capital=100.0, risk_pct=1.0, notional_sanity_cap_pct=25.0, fee_pct=0.0, slippage_bps=0.0,
    )

    assert len(trades) == 1
    trade = trades[0]
    assert trade.exit_reason == "eol"
    position_size = trade.gross_pnl / (trade.exit_price - trade.entry_price) if trade.exit_price != trade.entry_price else None
    if position_size:
        assert position_size * trade.entry_price <= 100.0 * 0.25 + 1e-6


# --- simulate_rotational_ensemble: finding 13 risk-budget sizing -------------

def test_simulate_rotational_ensemble_shrinks_new_trade_risk_to_remaining_budget():
    # A and B both fire entries the same day, universe-order A-then-B.
    # total_risk_budget_pct=1.5% ($1.50 on $100 equity) is deliberately
    # smaller than 2x the 1% per-trade target ($1 each, $2 total), so A
    # gets its full $1 target (nothing committed yet) but B, evaluated
    # after A is already open, only has $0.50 of budget left.
    d0, d1 = "2021-01-01", "2021-01-02"
    symbol_data = {
        "A": _make_series("A", [_candle("A", d0, close=100, high=105, low=95),
                                 _candle("A", d1, close=110, high=115, low=90)],
                           atr=[10.0, 10.0], entry_indices=[0]),
        "B": _make_series("B", [_candle("B", d0, close=100, high=105, low=95),
                                 _candle("B", d1, close=110, high=115, low=90)],
                           atr=[10.0, 10.0], entry_indices=[0]),
    }

    trades, equity_curve, skipped_log = simulate_rotational_ensemble(
        symbol_data, ["A", "B"], max_positions=2, atr_multiplier=2.5,
        capital=100.0, risk_pct=1.0, total_risk_budget_pct=1.5,
        fee_pct=0.0, slippage_bps=0.0,
    )

    a_trade = next(t for t in trades if t.symbol == "A")
    b_trade = next(t for t in trades if t.symbol == "B")
    a_size = a_trade.gross_pnl / (a_trade.exit_price - a_trade.entry_price)
    b_size = b_trade.gross_pnl / (b_trade.exit_price - b_trade.entry_price)

    assert abs(a_size - (1.0 / 25.0)) < 1e-9   # A: full $1 target / 25 stop distance
    assert abs(b_size - (0.5 / 25.0)) < 1e-9   # B: shrunk to remaining $0.50 / 25 stop distance
    assert not skipped_log


def test_simulate_rotational_ensemble_skips_when_risk_budget_exhausted_even_with_free_slots():
    # Same setup as above but a third symbol C, with a slot still free
    # (max_positions=3) but zero risk budget left after A+B consume the
    # full 1.5% budget — must be skipped for "no_risk_budget_available",
    # a distinct reason from the slot-count cap.
    d0, d1 = "2021-01-01", "2021-01-02"
    symbol_data = {
        sym: _make_series(sym, [_candle(sym, d0, close=100, high=105, low=95), _flat_candle(sym, d1, close=100)],
                           atr=[10.0, 10.0], entry_indices=[0])
        for sym in ("A", "B", "C")
    }

    trades, equity_curve, skipped_log = simulate_rotational_ensemble(
        symbol_data, ["A", "B", "C"], max_positions=3, atr_multiplier=2.5,
        capital=100.0, risk_pct=1.0, total_risk_budget_pct=1.5,
        fee_pct=0.0, slippage_bps=0.0,
    )

    entered_symbols = {t.symbol for t in trades}
    assert entered_symbols == {"A", "B"}
    assert any(s["symbol"] == "C" and s["reason"] == "no_risk_budget_available" for s in skipped_log)


# --- Track B risk-budget stress-test milestone (spec v29 §10.1) -------------
# Diagnostic milestone, NOT a re-test of Track B's already-passed verdict —
# see CLAUDE.md. Track B's original run had MAX_CONCURRENT_POSITIONS == the
# full 8-symbol universe size, so the slot cap could never bind and the
# portfolio risk budget was the only thing that could ever shrink a trade
# (and even that path was never exercised: 0 no_risk_budget_available skips
# in that run). These tests construct a single scenario where BOTH
# constraints are forced to bind together, to close that honesty gap at the
# unit level before the real-data rerun below.

def test_simulate_rotational_ensemble_binds_both_slot_cap_and_risk_budget_in_one_scenario():
    # 6 symbols (A-F, universe order) all fire an entry signal on day0.
    # max_positions=4 and total_risk_budget_pct=3.5% ($3.50 on $100 equity)
    # are chosen so that, walking the universe in order:
    #   A: available=3.50, target=1.00 -> granted 1.00 (committed 1.00)
    #   B: available=2.50, target=1.00 -> granted 1.00 (committed 2.00)
    #   C: available=1.50, target=1.00 -> granted 1.00 (committed 3.00)
    #   D: available=0.50, target=1.00 -> SHRUNK to 0.50 (committed 3.50,
    #      this is also the 4th and final slot)
    #   E: len(open_positions) == max_positions(4) already -> skipped
    #      "no_slot_available" (slot check runs before the budget check,
    #      so this is true even though the budget also happens to be
    #      exhausted at this point)
    #   F: same as E
    # This exercises the slot-count cap AND the risk-budget shrink AND a
    # partial-shrink (not just a full skip) in a single, real-shaped run.
    # day1 closes away from day0 (110, not flat at 100) so exit_price !=
    # entry_price for every symbol — needed to recover each trade's
    # position_size below as gross_pnl / (exit_price - entry_price)
    # without a division-by-zero on a flat trade.
    d0, d1 = "2021-01-01", "2021-01-02"
    universe = ["A", "B", "C", "D", "E", "F"]
    symbol_data = {
        sym: _make_series(sym, [_candle(sym, d0, close=100, high=105, low=95),
                                 _candle(sym, d1, close=110, high=115, low=90)],
                           atr=[10.0, 10.0], entry_indices=[0])
        for sym in universe
    }

    trades, equity_curve, skipped_log = simulate_rotational_ensemble(
        symbol_data, universe, max_positions=4, atr_multiplier=2.5,
        capital=100.0, risk_pct=1.0, total_risk_budget_pct=3.5,
        fee_pct=0.0, slippage_bps=0.0,
    )

    entered_symbols = {t.symbol for t in trades}
    assert entered_symbols == {"A", "B", "C", "D"}
    assert len(trades) == 4  # no over-allocation: exactly 4 slots filled, not 6

    sizes = {t.symbol: t.gross_pnl / (t.exit_price - t.entry_price) for t in trades}
    # A/B/C got their full $1.00 target (25 = 2.5x ATR(10) stop distance).
    assert abs(sizes["A"] - (1.00 / 25.0)) < 1e-9
    assert abs(sizes["B"] - (1.00 / 25.0)) < 1e-9
    assert abs(sizes["C"] - (1.00 / 25.0)) < 1e-9
    # D was shrunk to the $0.50 remaining in the budget, not rejected
    # outright and not silently granted its full $1.00 target.
    assert abs(sizes["D"] - (0.50 / 25.0)) < 1e-9

    e_skip = next(s for s in skipped_log if s["symbol"] == "E")
    f_skip = next(s for s in skipped_log if s["symbol"] == "F")
    assert e_skip["reason"] == "no_slot_available"
    assert f_skip["reason"] == "no_slot_available"
    # No crash, no incorrect rejection of a valid trade: D (whose target
    # exceeded the remaining budget) was still granted a shrunk trade, not
    # skipped outright the way E/F (genuinely out of slots) were.
    assert not any(s["symbol"] == "D" for s in skipped_log)


def test_simulate_rotational_ensemble_entry_sizing_log_attributes_shrink_to_risk_budget_not_notional_cap():
    # Same A/B two-symbol shrink setup as the existing finding-13 test
    # above, but exercised through the new entry_sizing_log instrumentation
    # (added for this milestone) to directly verify the target-vs-granted
    # arithmetic and the shrink attribution, not just the resulting trade
    # sizes.
    d0, d1 = "2021-01-01", "2021-01-02"
    symbol_data = {
        "A": _make_series("A", [_candle("A", d0, close=100, high=105, low=95),
                                 _candle("A", d1, close=110, high=115, low=90)],
                           atr=[10.0, 10.0], entry_indices=[0]),
        "B": _make_series("B", [_candle("B", d0, close=100, high=105, low=95),
                                 _candle("B", d1, close=110, high=115, low=90)],
                           atr=[10.0, 10.0], entry_indices=[0]),
    }
    entry_sizing_log = []

    trades, _, skipped_log = simulate_rotational_ensemble(
        symbol_data, ["A", "B"], max_positions=2, atr_multiplier=2.5,
        capital=100.0, risk_pct=1.0, total_risk_budget_pct=1.5,
        fee_pct=0.0, slippage_bps=0.0, entry_sizing_log=entry_sizing_log,
    )

    assert len(entry_sizing_log) == 2
    a_log = next(e for e in entry_sizing_log if e["symbol"] == "A")
    b_log = next(e for e in entry_sizing_log if e["symbol"] == "B")

    assert abs(a_log["target_risk_amount"] - 1.0) < 1e-9
    assert abs(a_log["granted_risk_amount"] - 1.0) < 1e-9
    assert a_log["shrunk_by_risk_budget"] is False
    assert a_log["shrunk_by_notional_cap"] is False

    assert abs(b_log["target_risk_amount"] - 1.0) < 1e-9
    assert abs(b_log["granted_risk_amount"] - 0.5) < 1e-9
    assert b_log["shrunk_by_risk_budget"] is True
    assert b_log["shrunk_by_notional_cap"] is False
    # available_risk_budget at B's entry = 1.5 budget - 1.0 already
    # committed by A = 0.5, matching the granted amount exactly.
    assert abs(b_log["available_risk_budget"] - 0.5) < 1e-9


def test_simulate_rotational_ensemble_entry_sizing_log_reports_notional_and_atr_price_fields():
    # Notional-concentration milestone (spec v30 §10.2): entry_sizing_log
    # gained entry_price/entry_atr/atr_to_price_pct and uncapped/final
    # notional_pct_of_equity fields, used to root-cause and quantify the
    # notional-backstop finding. A: ATR=10 on a $100 close -> stop_distance
    # = 2.5*10 = 25, target risk $1 on $100 equity -> position_size =
    # 1/25 = 0.04, notional = 0.04*100 = $4 = 4% of equity, well under
    # the loose 100% default backstop, so uncapped == final here.
    d0, d1 = "2021-01-01", "2021-01-02"
    symbol_data = {
        "A": _make_series("A", [_candle("A", d0, close=100, high=105, low=95),
                                 _candle("A", d1, close=110, high=115, low=90)],
                           atr=[10.0, 10.0], entry_indices=[0]),
    }
    entry_sizing_log = []

    simulate_rotational_ensemble(
        symbol_data, ["A"], max_positions=1, atr_multiplier=2.5,
        capital=100.0, risk_pct=1.0, fee_pct=0.0, slippage_bps=0.0,
        entry_sizing_log=entry_sizing_log,
    )

    assert len(entry_sizing_log) == 1
    log = entry_sizing_log[0]
    assert abs(log["entry_price"] - 100.0) < 1e-9
    assert abs(log["entry_atr"] - 10.0) < 1e-9
    assert abs(log["atr_to_price_pct"] - 10.0) < 1e-9  # 10/100 * 100
    assert abs(log["uncapped_notional_pct_of_equity"] - 4.0) < 1e-9  # $4 notional / $100 equity
    assert abs(log["notional_pct_of_equity"] - 4.0) < 1e-9  # not capped, so matches uncapped
    assert log["shrunk_by_notional_cap"] is False


def test_simulate_rotational_ensemble_notional_pct_diverges_from_uncapped_when_backstop_binds():
    # Same tiny-atr_multiplier setup as the existing notional-backstop
    # test above (test_simulate_rotational_ensemble_sizes_off_shared_
    # equity_and_caps_at_notional_sanity_backstop), but checked through
    # entry_sizing_log: uncapped_notional_pct_of_equity should reflect
    # what the risk-based formula NATURALLY wanted (>100%, since the
    # tiny atr_multiplier makes the stop distance tiny), while
    # notional_pct_of_equity (final) should be pinned at the 25% backstop
    # actually applied — the two fields must diverge exactly when the
    # backstop binds, not report the same (already-capped) number twice.
    d0, d1 = "2021-01-01", "2021-01-02"
    symbol_data = {
        "A": _make_series(
            "A",
            [_candle("A", d0, close=100, high=105, low=95), _candle("A", d1, close=100, high=100.5, low=99.6)],
            atr=[10.0, 10.0], entry_indices=[0],
        ),
    }
    entry_sizing_log = []

    simulate_rotational_ensemble(
        symbol_data, ["A"], max_positions=4, atr_multiplier=0.05,  # tiny stop distance -> oversized risk-based size
        capital=100.0, risk_pct=1.0, notional_sanity_cap_pct=25.0, fee_pct=0.0, slippage_bps=0.0,
        entry_sizing_log=entry_sizing_log,
    )

    assert len(entry_sizing_log) == 1
    log = entry_sizing_log[0]
    assert log["shrunk_by_notional_cap"] is True
    assert log["uncapped_notional_pct_of_equity"] > 25.0  # what the formula wanted, uncapped
    assert abs(log["notional_pct_of_equity"] - 25.0) < 1e-6  # what it actually got, pinned at the backstop
    assert log["uncapped_notional_pct_of_equity"] != log["notional_pct_of_equity"]


def test_simulate_rotational_ensemble_default_entry_sizing_log_is_none_and_unaffects_return_signature():
    # Backward-compatibility guard: every existing caller (Track A, Track
    # B, this file's other ~20 tests) calls without entry_sizing_log — the
    # new parameter must be fully opt-in, with the return shape unchanged.
    d0, d1 = "2021-01-01", "2021-01-02"
    symbol_data = {
        "A": _make_series("A", [_candle("A", d0, close=100, high=105, low=95), _flat_candle("A", d1, close=100)],
                           atr=[10.0, 10.0], entry_indices=[0]),
    }

    result = simulate_rotational_ensemble(symbol_data, ["A"], capital=100.0, fee_pct=0.0, slippage_bps=0.0)

    assert len(result) == 3
    trades, equity_curve, skipped_log = result
    assert len(trades) == 1


# --- simulate_rotational_ensemble: finding 13 weekly entry cadence -----------

def test_simulate_rotational_ensemble_never_enters_a_signal_outside_entry_eval_dates():
    d0, d1 = "2021-01-01", "2021-01-02"
    symbol_data = {
        "A": _make_series("A", [_candle("A", d0, close=125, high=130, low=120), _flat_candle("A", d1, close=125)],
                           atr=[10.0, 10.0], entry_indices=[0]),
    }

    # d0 (the only day the signal fires) is excluded from entry_eval_dates
    # — the signal must never be picked up, not merely deferred.
    trades, _, _ = simulate_rotational_ensemble(
        symbol_data, ["A"], capital=100.0, fee_pct=0.0, slippage_bps=0.0, entry_eval_dates={d1},
    )
    assert trades == []


def test_simulate_rotational_ensemble_enters_a_signal_on_an_included_entry_eval_date():
    d0, d1 = "2021-01-01", "2021-01-02"
    symbol_data = {
        "A": _make_series("A", [_candle("A", d0, close=125, high=130, low=120), _flat_candle("A", d1, close=125)],
                           atr=[10.0, 10.0], entry_indices=[0]),
    }

    trades, _, _ = simulate_rotational_ensemble(
        symbol_data, ["A"], capital=100.0, fee_pct=0.0, slippage_bps=0.0, entry_eval_dates={d0},
    )
    assert len(trades) == 1


def test_compute_weekly_entry_evaluation_dates_selects_a_single_fixed_weekday():
    from datetime import datetime as _dt
    calendar = [f"2024-01-{d:02d}" for d in range(1, 22)]  # 3 full weeks

    result = compute_weekly_entry_evaluation_dates(calendar)

    assert result == {d for d in calendar if _dt.fromisoformat(d).weekday() == 0}
    assert len(result) == 3
    assert all(_dt.fromisoformat(d).weekday() == 0 for d in result)


def test_simulate_rotational_ensemble_applies_fees_to_reduce_net_pnl():
    dates = ["2021-01-01", "2021-01-02"]
    symbol_data = {
        "A": _make_series(
            "A",
            [_candle("A", dates[0], close=100, high=105, low=95), _flat_candle("A", dates[1], close=100)],
            atr=[10.0, 10.0], entry_indices=[0],
        ),
    }

    with_fees, _, _ = simulate_rotational_ensemble(symbol_data, ["A"], capital=100.0, fee_pct=0.25, slippage_bps=5.0)
    no_fees, _, _ = simulate_rotational_ensemble(symbol_data, ["A"], capital=100.0, fee_pct=0.0, slippage_bps=0.0)

    assert len(with_fees) == 1 and len(no_fees) == 1
    assert with_fees[0].gross_pnl == no_fees[0].gross_pnl
    assert with_fees[0].pnl < no_fees[0].pnl
    assert with_fees[0].fees_paid > 0


# --- slice_ensemble_trades_by_folds: buckets by EXIT timestamp --------------

def test_slice_ensemble_trades_by_folds_buckets_by_exit_not_entry_timestamp():
    # This trade ENTERS inside fold 1's window (t5) but EXITS inside fold
    # 2's window (t40) — a portfolio-only scenario (concurrent positions
    # can make entry/exit order diverge) that never arises in the
    # single-position-at-a-time scripts. It must land in fold 2, proving
    # the slice is keyed on exit_timestamp, not entry_timestamp (which
    # would have put it in fold 1).
    trades = [
        EnsembleTrade("A", 0, 1, "t5", "t40", 100, 110, "trailing_stop", 10.0, 0.0, 10.0, 1.0),
    ]
    equity_curve = [100.0, 110.0]

    class FakeBoundary:
        def __init__(self, s):
            self._s = s
        def isoformat(self):
            return self._s

    folds = [
        {"fold": 1, "test_start": FakeBoundary("t0"), "test_end": FakeBoundary("t31")},
        {"fold": 2, "test_start": FakeBoundary("t31"), "test_end": FakeBoundary("t99")},
    ]

    fold_summaries, pooled = slice_ensemble_trades_by_folds(trades, equity_curve, folds, capital=100.0)

    assert fold_summaries[0]["trade_count"] == 0
    assert fold_summaries[1]["trade_count"] == 1
    assert pooled["trade_count"] == 1


# --- finding 14: buy-and-hold benchmark helpers ------------------------

def test_compute_buy_and_hold_symbol_return_uses_first_and_last_close_in_window():
    dates = ["2022-01-01", "2022-01-02", "2022-01-03", "2022-01-04"]
    candles = [_flat_candle("A", dates[0], close=100), _flat_candle("A", dates[1], close=120),
               _flat_candle("A", dates[2], close=150), _flat_candle("A", dates[3], close=90)]
    series = _make_series("A", candles, atr=[None] * 4, entry_indices=[])

    r = compute_buy_and_hold_symbol_return(series, "2022-01-01", "2022-01-03")

    assert abs(r - 50.0) < 1e-9  # 100 -> 150 over the windowed subset, day4 excluded


def test_compute_buy_and_hold_symbol_return_uses_first_available_close_when_history_starts_late():
    # Symbol's own data only starts on 01-03, inside a window that
    # nominally begins 01-01 — entry falls back to the first available
    # close rather than being treated as missing.
    dates = ["2022-01-03", "2022-01-04"]
    candles = [_flat_candle("A", dates[0], close=200), _flat_candle("A", dates[1], close=220)]
    series = _make_series("A", candles, atr=[None, None], entry_indices=[])

    r = compute_buy_and_hold_symbol_return(series, "2022-01-01", "2022-01-04")

    assert abs(r - 10.0) < 1e-9  # 200 -> 220, not treated as missing/None


def test_compute_buy_and_hold_symbol_return_returns_none_when_fully_outside_window():
    candles = [_flat_candle("A", "2020-01-01", close=100)]
    series = _make_series("A", candles, atr=[None], entry_indices=[])

    r = compute_buy_and_hold_symbol_return(series, "2022-01-01", "2022-01-04")

    assert r is None


def test_compute_buy_and_hold_portfolio_return_is_equal_weighted_simple_average():
    # A: +50%, B: -20% over the same window -> equal-weighted average +15%,
    # not a dollar-weighted or price-weighted blend.
    symbol_data = {
        "A": _make_series("A", [_flat_candle("A", "2022-01-01", close=100), _flat_candle("A", "2022-01-02", close=150)],
                           atr=[None, None], entry_indices=[]),
        "B": _make_series("B", [_flat_candle("B", "2022-01-01", close=100), _flat_candle("B", "2022-01-02", close=80)],
                           atr=[None, None], entry_indices=[]),
    }

    portfolio_return, per_symbol = compute_buy_and_hold_portfolio_return(symbol_data, ["A", "B"], "2022-01-01", "2022-01-02")

    assert abs(portfolio_return - 15.0) < 1e-9
    assert abs(per_symbol["A"] - 50.0) < 1e-9
    assert abs(per_symbol["B"] - (-20.0)) < 1e-9


def test_compute_buy_and_hold_portfolio_return_excludes_symbols_with_no_data_in_window():
    symbol_data = {
        "A": _make_series("A", [_flat_candle("A", "2022-01-01", close=100), _flat_candle("A", "2022-01-02", close=110)],
                           atr=[None, None], entry_indices=[]),
        "B": _make_series("B", [_flat_candle("B", "2019-01-01", close=100)], atr=[None], entry_indices=[]),
    }

    portfolio_return, per_symbol = compute_buy_and_hold_portfolio_return(symbol_data, ["A", "B"], "2022-01-01", "2022-01-02")

    assert "B" not in per_symbol
    assert abs(portfolio_return - 10.0) < 1e-9  # driven by A alone


def test_compute_buy_and_hold_portfolio_return_returns_none_when_no_symbol_has_data():
    symbol_data = {
        "A": _make_series("A", [_flat_candle("A", "2019-01-01", close=100)], atr=[None], entry_indices=[]),
    }

    portfolio_return, per_symbol = compute_buy_and_hold_portfolio_return(symbol_data, ["A"], "2022-01-01", "2022-01-02")

    assert portfolio_return is None
    assert per_symbol == {}
