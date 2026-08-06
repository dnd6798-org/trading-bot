"""
Verifies scripts/backtest_rsi_meanreversion.py's entry gating (RSI
cross-down below 30 + above the SMA regime filter), the resolve_exit()
dual-condition exit (RSI-revert vs. time-stop vs. eol), the trade-
simulation loop, and the fold-slicing/pooling logic — against
deterministic synthetic daily candles, no network calls. compute_rsi()
itself is covered by test_signal_generation.py; this covers the strategy
logic built on top.

The compute_entry_indices fixtures use the real compute_rsi()/compute_sma()
(via small overridden periods, not the production 14/200) to derive their
expected cross/regime values, then hardcode them — same convention
test_backtest_donchian.py already uses for its ATR fixtures.
"""
from src.data_ingestion import Candle
from scripts.backtest import DEFAULT_MAX_POSITION_PCT, DEFAULT_RISK_PER_TRADE_PCT
from scripts.backtest_rsi_meanreversion import (
    compute_entry_indices,
    resolve_exit,
    simulate_rsi_meanreversion,
    slice_trades_by_folds,
    RsiMeanReversionTrade,
    TIME_STOP_DAYS,
)


def _trending_dip_series(rise_bars, rise_step, decline_bars, decline_step, recover_bars, recover_step, tail, symbol="BTC/USD"):
    """
    Builds a daily candle series with a rise, a dip, a recovery, then a
    flat tail — used to produce a controlled RSI cross-down/cross-up
    against a trailing SMA regime filter (small periods, hand-traceable
    via the real compute_rsi()/compute_sma(), not production 14/200).
    """
    candles = []
    price = 100.0

    def _append(p, i):
        candles.append(Candle(symbol, f"d{i}", open=p, high=p + 1, low=p - 1, close=p, volume=10))

    i = 0
    for _ in range(rise_bars):
        price += rise_step
        _append(round(price, 4), i)
        i += 1
    for _ in range(decline_bars):
        price -= decline_step
        _append(round(price, 4), i)
        i += 1
    for _ in range(recover_bars):
        price += recover_step
        _append(round(price, 4), i)
        i += 1
    for _ in range(tail):
        _append(round(price, 4), i)
        i += 1
    return candles


def test_compute_entry_indices_fires_on_rsi_cross_down_when_above_sma_regime():
    # Long uptrend (60 bars) then an 8-bar dip: RSI(3) crosses below 30 at
    # index 61 (rsi[60]=33.33 -> rsi[61]=16.67) while close(152) is still
    # above SMA(30)=147 — regime bullish, entry should fire here.
    # Hand-verified once via the real compute_rsi()/compute_sma() and
    # hardcoded (see module docstring).
    candles = _trending_dip_series(
        rise_bars=60, rise_step=1.0, decline_bars=8, decline_step=4.0,
        recover_bars=8, recover_step=5.0, tail=5,
    )
    indices, rsi, sma = compute_entry_indices(candles, rsi_period=3, sma_period=30, oversold=30)

    assert 61 in indices
    assert round(rsi[60], 2) == 33.33 and round(rsi[61], 2) == 16.67
    assert candles[61].close > sma[61]


def test_compute_entry_indices_blocks_rsi_cross_down_when_below_sma_regime():
    # A long-run downtrend (40 bars) with a brief 4-bar bounce (pushes RSI
    # back above 30 without flipping the long-run regime), then decline
    # resumes -> a FRESH RSI cross-down at index 46, but close(160) is
    # still below SMA(30)=169.83 — regime bearish, entry must be blocked.
    candles = []
    price = 200.0

    def _append(p, i):
        candles.append(Candle("BTC/USD", f"d{i}", open=p, high=p + 1, low=p - 1, close=p, volume=10))

    idx = 0
    for _ in range(40):
        price -= 1.0
        _append(round(price, 4), idx)
        idx += 1
    for _ in range(4):
        price += 3.0
        _append(round(price, 4), idx)
        idx += 1
    for _ in range(6):
        price -= 4.0
        _append(round(price, 4), idx)
        idx += 1
    for _ in range(5):
        _append(round(price, 4), idx)
        idx += 1

    indices, rsi, sma = compute_entry_indices(candles, rsi_period=3, sma_period=30, oversold=30)

    assert round(rsi[45], 2) == 31.66 and round(rsi[46], 2) == 19.89  # fresh cross-down at 46
    assert candles[46].close < sma[46]  # regime bearish
    assert 46 not in indices


def test_resolve_exit_fires_on_rsi_revert_above_threshold():
    candles = [
        Candle("BTC/USD", f"d{i}", open=100, high=101, low=99, close=100 + i, volume=10)
        for i in range(5)
    ]
    rsi = [None, 20.0, 55.0, 10.0, 5.0]  # reverts above 50 at index 2

    exit_index, exit_price, exit_reason = resolve_exit(candles, rsi, entry_index=0, exit_threshold=50, time_stop_days=10)

    assert exit_index == 2
    assert exit_price == candles[2].close
    assert exit_reason == "rsi_revert"


def test_resolve_exit_fires_on_time_stop_when_rsi_never_reverts():
    candles = [
        Candle("BTC/USD", f"d{i}", open=100, high=101, low=99, close=100 + i, volume=10)
        for i in range(6)
    ]
    rsi = [None, 20.0, 15.0, 18.0, 22.0, 25.0]  # never exceeds 50

    exit_index, exit_price, exit_reason = resolve_exit(candles, rsi, entry_index=0, exit_threshold=50, time_stop_days=2)

    assert exit_index == 2  # entry_index(0) + time_stop_days(2)
    assert exit_price == candles[2].close
    assert exit_reason == "time_stop"


def test_resolve_exit_marks_eol_when_neither_condition_is_met_before_data_ends():
    candles = [
        Candle("BTC/USD", f"d{i}", open=100, high=101, low=99, close=100 + i, volume=10)
        for i in range(4)
    ]
    rsi = [None, 20.0, 25.0, 30.0]  # never reverts; time_stop_days=10 never reached in 4 candles

    exit_index, exit_price, exit_reason = resolve_exit(candles, rsi, entry_index=0, exit_threshold=50, time_stop_days=10)

    assert exit_index == 3
    assert exit_price == candles[3].close
    assert exit_reason == "eol"


def test_resolve_exit_defaults_use_module_time_stop_constant():
    # entry at 0, rsi never reverts, exactly TIME_STOP_DAYS candles after
    # entry should trigger — confirms simulate_rsi_meanreversion's callers
    # get the production default without having to pass it explicitly.
    candles = [
        Candle("BTC/USD", f"d{i}", open=100, high=101, low=99, close=100 + i, volume=10)
        for i in range(TIME_STOP_DAYS + 2)
    ]
    rsi = [None] + [10.0] * (TIME_STOP_DAYS + 1)

    exit_index, _, exit_reason = resolve_exit(candles, rsi, entry_index=0)

    assert exit_index == TIME_STOP_DAYS
    assert exit_reason == "time_stop"


def _five_candles():
    return [
        Candle("BTC/USD", "d0", open=100, high=101, low=99, close=100, volume=10),  # entry
        Candle("BTC/USD", "d1", open=100, high=106, low=99, close=105, volume=10),
        Candle("BTC/USD", "d2", open=105, high=103, low=101, close=102, volume=10),  # rsi reverts here
        Candle("BTC/USD", "d3", open=102, high=99, low=97, close=98, volume=10),
        Candle("BTC/USD", "d4", open=98, high=112, low=97, close=110, volume=10),
    ]


def test_simulate_rsi_meanreversion_exits_at_rsi_revert_close():
    candles = _five_candles()
    rsi = [None, 20.0, 55.0, 10.0, 5.0]  # reverts above 50 at index 2

    trades, _ = simulate_rsi_meanreversion(candles, entry_indices=[0], rsi=rsi, capital=100.0, fee_pct=0.0, slippage_bps=0.0)

    assert len(trades) == 1
    trade = trades[0]
    assert trade.entry_index == 0
    assert trade.entry_price == 100
    assert trade.exit_index == 2
    assert trade.exit_price == 102
    assert trade.exit_reason == "rsi_revert"
    nominal_risk_amount = 100.0 * (DEFAULT_RISK_PER_TRADE_PCT / 100)
    assert round(trade.r_multiple, 6) == round(trade.pnl / nominal_risk_amount, 6)


def test_simulate_rsi_meanreversion_applies_fees_to_reduce_net_pnl():
    candles = _five_candles()
    rsi = [None, 20.0, 55.0, 10.0, 5.0]

    with_fees, _ = simulate_rsi_meanreversion(candles, entry_indices=[0], rsi=rsi, capital=100.0, fee_pct=0.25, slippage_bps=5.0)
    no_fees, _ = simulate_rsi_meanreversion(candles, entry_indices=[0], rsi=rsi, capital=100.0, fee_pct=0.0, slippage_bps=0.0)

    assert len(with_fees) == 1 and len(no_fees) == 1
    assert with_fees[0].gross_pnl == no_fees[0].gross_pnl  # fees don't move the trigger levels
    assert with_fees[0].pnl < no_fees[0].pnl
    assert with_fees[0].fees_paid > 0


def test_simulate_rsi_meanreversion_sizes_position_flat_at_max_position_pct():
    # No risk_pct/stop-distance sizing here (see module docstring judgment
    # call 2) — every trade is sized at max_position_pct of equity.
    candles = _five_candles()
    rsi = [None, 20.0, 55.0, 10.0, 5.0]

    trades, _ = simulate_rsi_meanreversion(
        candles, entry_indices=[0], rsi=rsi, capital=100.0, max_position_pct=25.0, fee_pct=0.0, slippage_bps=0.0,
    )

    trade = trades[0]
    expected_position_size = (100.0 * (25.0 / 100)) / trade.entry_price
    assert round(trade.gross_pnl, 6) == round(expected_position_size * (trade.exit_price - trade.entry_price), 6)


def test_simulate_rsi_meanreversion_skips_new_signal_while_position_open():
    candles = _five_candles()
    rsi = [None, 20.0, 55.0, 10.0, 5.0]
    # index 1 is also listed as a signal, but the position from index 0
    # hasn't resolved yet (it resolves at index 2) — should be skipped,
    # not opened as a second overlapping position.
    trades, _ = simulate_rsi_meanreversion(candles, entry_indices=[0, 1], rsi=rsi, capital=100.0, fee_pct=0.0, slippage_bps=0.0)

    assert len(trades) == 1
    assert trades[0].entry_index == 0


def test_slice_trades_by_folds_splits_and_pools_by_entry_timestamp():
    trades = [
        RsiMeanReversionTrade(0, 1, "t0", "t1", 100, 110, "rsi_revert", 10.0, 0.0, 10.0, 1.0),
        RsiMeanReversionTrade(2, 3, "t31", "t32", 110, 100, "time_stop", -10.0, 0.0, -10.0, -1.0),
        RsiMeanReversionTrade(4, 5, "t61", "t62", 100, 90, "eol", -10.0, 0.0, -10.0, -1.0),
    ]
    equity_curve = [100.0, 110.0, 100.0, 90.0]

    class FakeBoundary:
        def __init__(self, s):
            self._s = s
        def isoformat(self):
            return self._s

    folds = [
        {"fold": 1, "test_start": FakeBoundary("t0"), "test_end": FakeBoundary("t31")},
        {"fold": 2, "test_start": FakeBoundary("t31"), "test_end": FakeBoundary("t61")},
        {"fold": 3, "test_start": FakeBoundary("t61"), "test_end": FakeBoundary("t99")},
    ]

    fold_summaries, pooled = slice_trades_by_folds(trades, equity_curve, folds, capital=100.0)

    assert [f["trade_count"] for f in fold_summaries] == [1, 1, 1]
    assert pooled["trade_count"] == 3  # all three trades fall at/after fold 1's test_start
