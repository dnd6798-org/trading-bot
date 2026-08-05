"""
Verifies backtest simulation mechanics (entry/exit resolution, fee
modeling, position sizing cap, calibration/validation split, diagnostics)
against deterministic synthetic candles — no network calls. Indicator math
itself is covered by test_signal_generation.py; this covers
scripts/backtest.py's simulate()/summarize()/run_walk_forward() logic
layered on top.
"""
from src.data_ingestion import Candle
from src.signal_generation import volume_confirms
from scripts.backtest import (
    simulate, summarize, diagnose, run_walk_forward, resample_candles,
    compute_sma, compute_trend_filtered_signal_indices, compute_signal_indices,
    Trade, _volume_confirms_series, VOLUME_LOOKBACK,
)


def _crossover_candles():
    """
    Same synthetic series as test_signal_generation's crossover fixture: a
    25-candle decline followed by a 5-candle rise that flips the 9/21 EMA
    crossover (with a volume spike) on the final candle, index 29, entry
    close = 100.0.
    """
    candles = []
    price = 100.0
    for i in range(25):
        price -= 1.0
        candles.append(Candle("BTC/USD", f"t{i}", open=price + 1, high=price + 1.5, low=price - 0.5, close=price, volume=10))
    for i in range(25, 30):
        price += 5.0
        candles.append(Candle("BTC/USD", f"t{i}", open=price - 5, high=price + 0.5, low=price - 5.5, close=price, volume=10 if i < 29 else 100))
    return candles


def test_simulate_exits_at_take_profit_when_high_reaches_it():
    candles = _crossover_candles()
    # ATR(14) at the entry candle (index 29) is ~3.24; atr_multiplier=2 puts
    # take-profit at entry + ~6.48 = ~106.48. This candle's high clears it
    # without its low touching the stop, so the trade should close on a win.
    candles.append(Candle("BTC/USD", "t30", open=101, high=110, low=99, close=105, volume=10))

    trades, equity_curve = simulate(
        candles, ema_fast_period=9, ema_slow_period=21, atr_multiplier=2.0,
        capital=100.0, fee_pct=0.0, slippage_bps=0.0,
    )

    assert len(trades) == 1
    trade = trades[0]
    assert trade.entry_index == 29
    assert trade.exit_index == 30
    assert trade.exit_reason == "take_profit"
    assert trade.pnl > 0
    assert equity_curve[-1] > 100.0


def test_simulate_exits_at_stop_loss_when_low_reaches_it():
    candles = _crossover_candles()
    # Same setup, but this candle's low blows through the stop (~93.52)
    # instead — the trade should close on a loss.
    candles.append(Candle("BTC/USD", "t30", open=99, high=101, low=90, close=95, volume=10))

    trades, equity_curve = simulate(
        candles, ema_fast_period=9, ema_slow_period=21, atr_multiplier=2.0,
        capital=100.0, fee_pct=0.0, slippage_bps=0.0,
    )

    assert len(trades) == 1
    trade = trades[0]
    assert trade.exit_reason == "stop"
    assert trade.pnl < 0
    assert trade.exit_price < trade.entry_price
    assert equity_curve[-1] < 100.0


def test_simulate_prefers_stop_when_both_hit_in_same_bar():
    candles = _crossover_candles()
    # A wide bar whose low clears the stop AND whose high clears the
    # take-profit — worst-case assumption is the stop hit first.
    candles.append(Candle("BTC/USD", "t30", open=100, high=115, low=85, close=100, volume=10))

    trades, _ = simulate(candles, ema_fast_period=9, ema_slow_period=21, atr_multiplier=2.0, capital=100.0)

    assert len(trades) == 1
    assert trades[0].exit_reason == "stop"
    assert trades[0].pnl < 0


def test_simulate_caps_position_size_at_max_notional():
    candles = _crossover_candles()
    # A very tight ATR multiplier makes the risk-sized position far larger
    # than 25% of capital notional-wise, so the max-position cap should bind.
    candles.append(Candle("BTC/USD", "t30", open=101, high=200, low=99, close=150, volume=10))

    trades, _ = simulate(
        candles, ema_fast_period=9, ema_slow_period=21, atr_multiplier=0.1,
        capital=100.0, risk_pct=1.0, max_position_pct=25.0, fee_pct=0.0, slippage_bps=0.0,
    )

    assert len(trades) == 1
    trade = trades[0]
    implied_position_size = trade.gross_pnl / (trade.exit_price - trade.entry_price)
    max_notional = 100.0 * 0.25
    assert implied_position_size * trade.entry_price <= max_notional + 1e-6


def test_simulate_holds_position_open_and_skips_overlapping_signal():
    # Two consecutive signals where the first trade's stop/take-profit
    # hasn't resolved yet by the time the second signal would fire should
    # not open a second, overlapping position.
    candles = _crossover_candles()
    candles.append(Candle("BTC/USD", "t30", open=101, high=101, low=99, close=100, volume=10))  # still open
    candles.append(Candle("BTC/USD", "t31", open=101, high=110, low=99, close=105, volume=10))  # resolves

    trades, _ = simulate(candles, ema_fast_period=9, ema_slow_period=21, atr_multiplier=2.0, capital=100.0)

    assert len(trades) == 1


def test_simulate_applies_fees_and_slippage_to_reduce_net_pnl():
    candles = _crossover_candles()
    candles.append(Candle("BTC/USD", "t30", open=101, high=110, low=99, close=105, volume=10))

    trades_with_fees, _ = simulate(
        candles, ema_fast_period=9, ema_slow_period=21, atr_multiplier=2.0,
        capital=100.0, fee_pct=0.25, slippage_bps=5.0,
    )
    trades_no_fees, _ = simulate(
        candles, ema_fast_period=9, ema_slow_period=21, atr_multiplier=2.0,
        capital=100.0, fee_pct=0.0, slippage_bps=0.0,
    )

    assert len(trades_with_fees) == 1 and len(trades_no_fees) == 1
    with_fees, no_fees = trades_with_fees[0], trades_no_fees[0]

    # Same gross P&L (fees don't affect trigger levels), but net P&L is lower
    # by exactly the modeled round-trip cost: 0.25% + 5bps = 0.30% per leg.
    assert with_fees.gross_pnl == no_fees.gross_pnl
    cost_frac_per_leg = 0.25 / 100 + 5.0 / 10000
    position_size = with_fees.gross_pnl / (with_fees.exit_price - with_fees.entry_price)
    expected_fees = position_size * (with_fees.entry_price + with_fees.exit_price) * cost_frac_per_leg
    assert round(with_fees.fees_paid, 6) == round(expected_fees, 6)
    assert round(with_fees.pnl, 6) == round(with_fees.gross_pnl - expected_fees, 6)
    assert with_fees.pnl < no_fees.pnl


def test_summarize_computes_win_rate_return_and_drawdown():
    trades = [
        Trade(0, 1, "t0", "t1", entry_price=100, exit_price=110, exit_reason="take_profit", gross_pnl=10.0, fees_paid=0.0, pnl=10.0, r_multiple=1.0),
        Trade(2, 3, "t2", "t3", entry_price=110, exit_price=100, exit_reason="stop", gross_pnl=-15.0, fees_paid=0.0, pnl=-15.0, r_multiple=-1.5),
        Trade(4, 6, "t4", "t6", entry_price=100, exit_price=105, exit_reason="eol", gross_pnl=5.0, fees_paid=0.0, pnl=5.0, r_multiple=0.5),
    ]
    # Equity path: 100 -> 110 (peak) -> 95 (trough) -> 100
    equity_curve = [100.0, 110.0, 95.0, 100.0]

    stats = summarize(trades, equity_curve, starting_capital=100.0)

    assert stats["trade_count"] == 3
    assert round(stats["win_rate_pct"], 2) == round(2 / 3 * 100, 2)
    assert stats["total_return_pct"] == 0.0  # ended flat vs. starting capital
    assert round(stats["max_drawdown_pct"], 4) == round((110 - 95) / 110 * 100, 4)
    assert round(stats["avg_r_multiple"], 4) == round((1.0 - 1.5 + 0.5) / 3, 4)
    assert round(stats["stop_rate_pct"], 2) == round(1 / 3 * 100, 2)
    assert round(stats["take_profit_rate_pct"], 2) == round(1 / 3 * 100, 2)
    assert round(stats["eol_rate_pct"], 2) == round(1 / 3 * 100, 2)
    assert stats["avg_holding_bars"] == (1 + 1 + 2) / 3


def test_summarize_handles_no_trades():
    stats = summarize([], [100.0], starting_capital=100.0)
    assert stats["trade_count"] == 0
    assert stats["win_rate_pct"] == 0.0
    assert stats["total_return_pct"] == 0.0


def test_diagnose_reports_buy_hold_return_and_signal_count():
    candles = _crossover_candles()
    diag = diagnose(candles)

    expected_buy_hold = (candles[-1].close - candles[0].close) / candles[0].close * 100
    assert round(diag["buy_hold_return_pct"], 6) == round(expected_buy_hold, 6)
    assert diag["raw_crossover_signal_count"] == 1  # the one crossover built into the fixture
    assert diag["candle_count"] == len(candles)
    assert diag["avg_atr_pct_of_price"] > 0


def test_resample_candles_aggregates_ohlcv_correctly_and_drops_partial_trailing_group():
    candles = [
        Candle("BTC/USD", "t0", open=100, high=105, low=99, close=102, volume=10),
        Candle("BTC/USD", "t1", open=102, high=110, low=101, close=108, volume=20),
        Candle("BTC/USD", "t2", open=108, high=109, low=95, close=97, volume=15),
        Candle("BTC/USD", "t3", open=97, high=100, low=96, close=99, volume=5),
        # Second group of 4
        Candle("BTC/USD", "t4", open=99, high=101, low=98, close=100, volume=8),
        Candle("BTC/USD", "t5", open=100, high=103, low=99, close=101, volume=7),
        Candle("BTC/USD", "t6", open=101, high=104, low=100, close=103, volume=6),
        Candle("BTC/USD", "t7", open=103, high=106, low=102, close=105, volume=9),
        # Incomplete trailing group — should be dropped
        Candle("BTC/USD", "t8", open=105, high=107, low=104, close=106, volume=3),
    ]

    resampled = resample_candles(candles, hours_per_candle=4)

    assert len(resampled) == 2
    first, second = resampled
    assert first.symbol == "BTC/USD"
    assert first.timestamp == "t0"
    assert first.open == 100          # open of the group's first candle
    assert first.high == 110          # max high across the group
    assert first.low == 95            # min low across the group
    assert first.close == 99          # close of the group's last candle
    assert first.volume == 10 + 20 + 15 + 5

    assert second.timestamp == "t4"
    assert second.open == 99
    assert second.high == 106
    assert second.low == 98
    assert second.close == 105
    assert second.volume == 8 + 7 + 6 + 9


def test_resample_candles_is_a_noop_for_1h():
    candles = [Candle("BTC/USD", "t0", 1, 2, 0.5, 1.5, 10)]
    assert resample_candles(candles, hours_per_candle=1) is candles


def test_compute_sma_basic():
    values = [1, 2, 3, 4, 5, 6]
    sma = compute_sma(values, period=3)
    assert sma[:2] == [None, None]
    assert sma[2] == 2  # avg(1,2,3)
    assert sma[3] == 3  # avg(2,3,4)
    assert sma[4] == 4
    assert sma[5] == 5


def test_compute_sma_insufficient_data_returns_all_none():
    assert compute_sma([1, 2], period=5) == [None, None]


def test_simulate_uses_precomputed_signals_override():
    candles = _crossover_candles()
    candles.append(Candle("BTC/USD", "t30", open=101, high=110, low=99, close=105, volume=10))
    base_indices, atr = compute_signal_indices(candles, 9, 21)
    assert base_indices == [29]  # sanity: the base signal does fire here

    # An empty override should suppress the trade even though the base
    # signal would have fired — proves simulate() actually uses the
    # override rather than silently recomputing compute_signal_indices.
    trades, _ = simulate(
        candles, ema_fast_period=9, ema_slow_period=21, atr_multiplier=2.0,
        capital=100.0, precomputed_signals=([], atr),
    )
    assert trades == []


def test_compute_trend_filtered_signal_indices_keeps_signal_above_sma():
    candles = _crossover_candles()  # base signal fires at index 29, entry close = 100.0
    higher_tf_candles = [Candle("BTC/USD", f"d{i}", 90, 91, 89, close=90, volume=1) for i in range(5)]

    filtered, atr = compute_trend_filtered_signal_indices(
        candles, ema_fast_period=9, ema_slow_period=21,
        higher_tf_candles=higher_tf_candles, higher_tf_sma_period=2, bars_per_higher_tf_unit=6,
    )

    assert filtered == [29]  # price (100) is above the daily SMA (90) -> kept


def test_compute_trend_filtered_signal_indices_drops_signal_below_sma():
    candles = _crossover_candles()
    higher_tf_candles = [Candle("BTC/USD", f"d{i}", 110, 111, 109, close=110, volume=1) for i in range(5)]

    filtered, atr = compute_trend_filtered_signal_indices(
        candles, ema_fast_period=9, ema_slow_period=21,
        higher_tf_candles=higher_tf_candles, higher_tf_sma_period=2, bars_per_higher_tf_unit=6,
    )

    assert filtered == []  # price (100) is below the daily SMA (110) -> dropped


def test_compute_trend_filtered_signal_indices_is_causal_rejects_still_forming_bar():
    # Only one higher-tf candle exists — as of the lower-tf signal at index
    # 29 (higher-tf bar index 29 // 6 = 4), the most recently CLOSED
    # higher-tf bar would be index 3, which doesn't exist yet. The filter
    # must reject rather than fall back to some other bar (no lookahead).
    candles = _crossover_candles()
    higher_tf_candles = [Candle("BTC/USD", "d0", 90, 91, 89, close=90, volume=1)]

    filtered, atr = compute_trend_filtered_signal_indices(
        candles, ema_fast_period=9, ema_slow_period=21,
        higher_tf_candles=higher_tf_candles, higher_tf_sma_period=1, bars_per_higher_tf_unit=6,
    )

    assert filtered == []


def test_backtest_volume_confirmation_matches_signal_generation_reference():
    """
    scripts/backtest.py computes volume confirmation with an incremental
    rolling sum for performance (compute_signal_indices, O(n) over a year of
    hourly bars), rather than signal_generation.volume_confirms's per-slice
    O(n) reslice. This locks the two implementations to the same semantics
    — spec §2's volume-above-average confirmation filter — so the backtest
    can't silently drift from the live pipeline's actual signal logic.
    """
    volumes = [10, 12, 8, 15, 20, 9, 11, 30, 7, 14, 18, 22, 5, 16, 13, 19, 25, 6, 17, 21,
               40, 8, 9, 33, 12, 14, 60, 10, 11, 12, 3, 45, 22, 18, 9, 27]
    candles = [Candle("BTC/USD", f"t{i}", 1, 1, 1, 1, volume=v) for i, v in enumerate(volumes)]

    fast_series = _volume_confirms_series(candles, lookback=VOLUME_LOOKBACK)

    for i in range(VOLUME_LOOKBACK, len(candles)):
        reference = volume_confirms(candles[:i + 1], lookback=VOLUME_LOOKBACK)
        assert fast_series[i] == reference, f"mismatch at index {i}"


def test_run_walk_forward_splits_trades_by_entry_timestamp():
    # Two independent crossover setups back to back: the first resolves
    # entirely before the cutoff (calibration), the second fires and
    # resolves after it (validation).
    candles = _crossover_candles()
    candles.append(Candle("BTC/USD", "t30", open=101, high=110, low=99, close=105, volume=10))  # calibration trade resolves here

    # A second decline+rise cycle, offset in price, to produce a second,
    # later crossover.
    price = candles[-1].close
    for i in range(31, 56):
        price -= 1.0
        candles.append(Candle("BTC/USD", f"t{i}", open=price + 1, high=price + 1.5, low=price - 0.5, close=price, volume=10))
    for i in range(56, 61):
        price += 5.0
        candles.append(Candle("BTC/USD", f"t{i}", open=price - 5, high=price + 0.5, low=price - 5.5, close=price, volume=10 if i < 59 else 100))
    candles.append(Candle("BTC/USD", "t61", open=price + 1, high=price + 20, low=price - 1, close=price + 15, volume=10))  # validation trade resolves here

    # Cutoff is any timestamp between the two trades' entries.
    cutoff_ts = candles[40].timestamp

    calibration, validation = run_walk_forward(
        candles, cutoff_ts, ema_fast_period=9, ema_slow_period=21, atr_multiplier=2.0, capital=100.0,
    )

    assert calibration["trade_count"] == 1
    assert validation["trade_count"] == 1
