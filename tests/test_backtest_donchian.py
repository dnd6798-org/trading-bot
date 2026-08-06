"""
Verifies scripts/backtest_donchian.py's Donchian channel math, the
long/short breakout signal, the ATR trailing-stop simulation loop, and the
fold-slicing/pooling logic — against deterministic synthetic daily
candles, no network calls.

Candle fixtures use high=close+5, low=close-5 and day-over-day close
changes of at most 5 so the true range stays exactly 10 (and ATR stays
locked at exactly 10.0 once seeded) through the flat "seasoning" period —
this makes ATR values before a breakout day predictable by construction.
Values after a breakout (where price gaps beyond the 5-wide band) are
computed once via the real compute_atr() and hardcoded, the same way
test_backtest.py hardcodes an approximate ATR value in its own fixture
comment.
"""
from src.data_ingestion import Candle
from scripts.backtest import ATR_PERIOD
from scripts.backtest_donchian import (
    compute_donchian_levels,
    compute_donchian_signal_indices,
    simulate_donchian,
    slice_trades_by_folds,
    DonchianTrade,
)


def _flat_candle(i, close=100.0, volume=10):
    return Candle("BTC/USD", f"d{i}", open=close, high=close + 5, low=close - 5, close=close, volume=volume)


def _candle(i, close, high=None, low=None, volume=10):
    return Candle(
        "BTC/USD", f"d{i}",
        open=close,
        high=high if high is not None else close + 5,
        low=low if low is not None else close - 5,
        close=close,
        volume=volume,
    )


def _seasoned_flat_candles(count=20, close=100.0):
    """20 flat days: enough to seed ATR(14) at exactly 10.0 and to fill any Donchian window used in these tests (channel_length <= 20)."""
    return [_flat_candle(i, close) for i in range(count)]


def test_compute_donchian_levels_is_causal_and_uses_prior_n_days_only():
    candles = [
        _candle(0, 100, high=10, low=5),
        _candle(1, 100, high=11, low=6),
        _candle(2, 100, high=12, low=7),
        _candle(3, 100, high=20, low=1),  # would blow out the band if it leaked into its own window
        _candle(4, 100, high=13, low=8),
    ]
    upper, lower = compute_donchian_levels(candles, channel_length=3)

    assert upper[:3] == [None, None, None]  # not enough prior history yet
    assert upper[3] == 12 and lower[3] == 5   # window = candles[0:3], excludes candle 3 itself
    assert upper[4] == 20 and lower[4] == 1   # window = candles[1:4], now includes candle 3


def test_compute_donchian_signal_indices_fires_long_on_close_above_band_and_short_on_close_below():
    candles = _seasoned_flat_candles(20) + [
        _candle(20, 125, high=130, low=120),  # closes above the flat 105 band -> long
    ]
    candles += [_flat_candle(i) for i in range(21, 26)]  # settle back to flat so the channel resets
    candles.append(_candle(26, 75, high=80, low=70))     # closes below the flat 95 band -> short

    long_indices, short_indices, atr = compute_donchian_signal_indices(candles, channel_length=5)

    assert 20 in long_indices
    assert 26 in short_indices
    assert set(long_indices) & set(short_indices) == set()  # mutually exclusive per day
    assert atr[20] is not None  # ATR(14) seeded well before the breakout at index 20


def test_simulate_donchian_long_trailing_stop_ratchets_up_past_the_original_entry_stop():
    # Flat seasoning locks ATR(14) at exactly 10.0 through index 19. A long
    # breakout at index 20 (close 125), then two more up days (128, 131)
    # that should ratchet the trailing stop upward. A pullback at index 23
    # (low=105) sits ABOVE the original entry-based stop (125 - 2*ATR[20])
    # but AT/BELOW the ratcheted trailing stop (131 - 2*ATR[22]) — so if
    # the exit fires here, that proves the stop actually trailed rather
    # than staying fixed at entry.
    candles = _seasoned_flat_candles(20) + [
        _candle(20, 125, high=130, low=120),
        _candle(21, 128, high=133, low=123),
        _candle(22, 131, high=136, low=126),
        _candle(23, 129, high=133, low=105),
    ]

    trades, equity_curve = simulate_donchian(
        candles, channel_length=5, atr_multiplier=2.0, capital=100.0, fee_pct=0.0, slippage_bps=0.0,
    )

    assert len(trades) == 1
    trade = trades[0]
    assert trade.direction == "long"
    assert trade.entry_index == 20
    assert trade.exit_index == 23
    assert trade.exit_reason == "trailing_stop"

    original_entry_stop = 125 - 2.0 * 11.428571428571429  # ATR[20], computed once via compute_atr and hardcoded
    trailed_stop = 131 - 2.0 * 11.231778425655977          # ATR[22]
    assert round(trade.exit_price, 4) == round(trailed_stop, 4)
    assert trade.exit_price > original_entry_stop  # ratcheted up, not the fixed entry-based level
    assert trade.pnl < 0  # trail caught the pullback below entry (125) before it reversed further


def test_simulate_donchian_short_trailing_stop_ratchets_down_past_the_original_entry_stop():
    # Mirror image of the long test: a short breakout at index 20 (close
    # 75), two more down days (72, 69) ratcheting the trailing stop
    # downward, then a bounce at index 23 (high=94) that sits BELOW the
    # original entry-based stop (75 + 2*ATR[20] = ~97.9) but AT/ABOVE the
    # ratcheted trailing stop (69 + 2*ATR[22] = ~91.5).
    candles = _seasoned_flat_candles(20) + [
        _candle(20, 75, high=80, low=70),
        _candle(21, 72, high=77, low=67),
        _candle(22, 69, high=74, low=64),
        _candle(23, 71, high=94, low=67),
    ]

    trades, equity_curve = simulate_donchian(
        candles, channel_length=5, atr_multiplier=2.0, capital=100.0, fee_pct=0.0, slippage_bps=0.0,
    )

    assert len(trades) == 1
    trade = trades[0]
    assert trade.direction == "short"
    assert trade.entry_index == 20
    assert trade.exit_index == 23
    assert trade.exit_reason == "trailing_stop"

    original_entry_stop = 75 + 2.0 * 11.428571428571429  # ATR[20]
    trailed_stop = 69 + 2.0 * 11.231778425655977          # ATR[22]
    assert round(trade.exit_price, 4) == round(trailed_stop, 4)
    assert trade.exit_price < original_entry_stop  # ratcheted down, not the fixed entry-based level
    assert trade.pnl < 0  # trail caught the bounce above entry (75) before it reversed further


def test_simulate_donchian_applies_fees_to_reduce_net_pnl():
    candles = _seasoned_flat_candles(20) + [
        _candle(20, 125, high=130, low=120),
        _candle(21, 128, high=133, low=123),
        _candle(22, 131, high=136, low=126),
        _candle(23, 129, high=133, low=105),
    ]

    with_fees, _ = simulate_donchian(candles, channel_length=5, atr_multiplier=2.0, capital=100.0, fee_pct=0.25, slippage_bps=5.0)
    no_fees, _ = simulate_donchian(candles, channel_length=5, atr_multiplier=2.0, capital=100.0, fee_pct=0.0, slippage_bps=0.0)

    assert len(with_fees) == 1 and len(no_fees) == 1
    assert with_fees[0].gross_pnl == no_fees[0].gross_pnl  # fees don't move the trigger levels
    assert with_fees[0].pnl < no_fees[0].pnl
    assert with_fees[0].fees_paid > 0


def test_simulate_donchian_caps_position_size_at_max_notional():
    candles = _seasoned_flat_candles(20) + [
        _candle(20, 125, high=130, low=120),
    ] + [_flat_candle(i, 125) for i in range(21, 40)]  # never resolves -> exits "eol"

    trades, _ = simulate_donchian(
        candles, channel_length=5, atr_multiplier=0.05,  # tiny stop distance -> oversized risk-based position
        capital=100.0, risk_pct=1.0, max_position_pct=25.0, fee_pct=0.0, slippage_bps=0.0,
    )

    assert len(trades) == 1
    trade = trades[0]
    position_size = trade.gross_pnl / (trade.exit_price - trade.entry_price) if trade.exit_price != trade.entry_price else None
    max_notional = 100.0 * 0.25
    if position_size:
        assert position_size * trade.entry_price <= max_notional + 1e-6


def test_simulate_donchian_skips_new_signal_while_position_open():
    # A long breakout at index 20 that hasn't resolved yet by the time a
    # second breakout (short, at a much lower band) would fire shouldn't
    # open a second, overlapping position.
    candles = _seasoned_flat_candles(20) + [
        _candle(20, 125, high=130, low=120),  # long entry; stop far away, stays open
        _candle(21, 124, high=129, low=119),
        _candle(22, 60, high=65, low=55),     # would be a short breakout if flat, but position is already open
    ]

    trades, _ = simulate_donchian(candles, channel_length=5, atr_multiplier=5.0, capital=100.0, fee_pct=0.0, slippage_bps=0.0)

    assert len(trades) == 1
    assert trades[0].direction == "long"


def test_slice_trades_by_folds_splits_and_pools_by_entry_timestamp():
    trades = [
        DonchianTrade(0, 1, "t0", "t1", "long", 100, 110, "trailing_stop", 10.0, 0.0, 10.0, 1.0),
        DonchianTrade(2, 3, "t31", "t32", "short", 110, 100, "trailing_stop", 10.0, 0.0, 10.0, 1.0),
        DonchianTrade(4, 5, "t61", "t62", "long", 100, 90, "eol", -10.0, 0.0, -10.0, -1.0),
    ]
    equity_curve = [100.0, 110.0, 120.0, 110.0]

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
