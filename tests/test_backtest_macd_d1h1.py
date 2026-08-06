"""
Verifies scripts/backtest_macd_d1h1.py's daily-regime computation, the
causal once-per-day hourly/daily alignment (the correctness detail this
strategy hinges on), the price-action trailing-stop simulation loop, and
the fold-slicing/pooling logic — against deterministic synthetic candles,
no network calls. compute_macd() itself is covered by
test_signal_generation.py; this covers the strategy logic built on top.
"""
from src.data_ingestion import Candle
from scripts.backtest import DEFAULT_MAX_POSITION_PCT, DEFAULT_RISK_PER_TRADE_PCT
from scripts.backtest_macd_d1h1 import (
    compute_daily_regime_series,
    compute_hourly_entry_indices,
    simulate_macd_d1h1,
    slice_trades_by_folds,
    MacdD1H1Trade,
    BARS_PER_DAY,
)


def _decline_then_rise_series(symbol, decline_bars=40, rise_bars=20, base=200.0, label="t"):
    """
    A mildly-accelerating decline (avoids the exact-float-plateau MACD
    artifact a perfectly linear decline produces) followed by a steady
    rise — long enough to seed MACD(12,26,9) (needs ~34 bars) and then
    produce one clean, unambiguous crossover a few bars into the rise.
    Verified once via compute_macd() and hardcoded below: the crossover
    lands at index 41 (macd[40]=-14.9438 <= signal[40]=-14.4374, then
    macd[41]=-14.0939 > signal[41]=-14.3687).
    """
    candles = []
    price = base
    for i in range(decline_bars):
        price -= (1.0 + 0.05 * i)
        candles.append(Candle(symbol, f"{label}{i}", open=price + 1, high=price + 1.5, low=price - 0.5, close=price, volume=10))
    for i in range(decline_bars, decline_bars + rise_bars):
        price += 5.0
        candles.append(Candle(symbol, f"{label}{i}", open=price - 5, high=price + 0.5, low=price - 5.5, close=price, volume=10))
    return candles


def test_compute_daily_regime_series_is_none_then_bearish_then_bullish():
    daily = _decline_then_rise_series("BTC/USD", label="d")
    regime = compute_daily_regime_series(daily)

    assert regime[:33] == [None] * 33  # not enough history to seed MACD(12,26,9) yet
    assert regime[33] is False         # macd below signal partway through the decline
    assert regime[40] is False         # still bearish right before the crossover
    assert regime[41] is True          # crosses bullish here (hand-verified via compute_macd)
    assert regime[59] is True          # stays bullish through the rest of the rise


def test_hourly_index_maps_to_prior_daily_index_and_is_constant_within_a_day():
    # Direct check of the causal alignment formula compute_hourly_entry_indices
    # relies on (i // BARS_PER_DAY - 1): every hour within calendar day 1 (hours
    # 24..47) must map to the SAME daily index (day 0, the last fully-closed
    # day), and the mapped index must only step forward at the next midnight —
    # this is the mechanism behind "regime updates once per day, not intraday."
    day1_hours = range(24, 48)
    mapped = {h // BARS_PER_DAY - 1 for h in day1_hours}
    assert mapped == {0}                       # constant across all 24 hours of day 1
    assert 47 // BARS_PER_DAY - 1 == 0          # last hour of day 1 -> still day 0's regime
    assert 48 // BARS_PER_DAY - 1 == 1          # first hour of day 2 -> steps forward exactly here


def test_compute_hourly_entry_indices_fires_only_when_daily_regime_is_bullish():
    hourly = _decline_then_rise_series("BTC/USD", label="h")  # same shape as the daily fixture
    # The one crossover in this fixture is at hourly index 41, which is in
    # calendar day 1 (41 // 24 == 1) -> gated by daily_regime_series[0].
    assert 41 // BARS_PER_DAY - 1 == 0

    bullish_regime = [True, True, True]
    entries_allowed, macd_line, signal_line = compute_hourly_entry_indices(hourly, bullish_regime)
    assert 41 in entries_allowed
    assert macd_line[41] > signal_line[41]  # sanity: the raw crossover really is there

    bearish_regime = [False, True, True]  # day 0 (gating index 0) now bearish
    entries_blocked, _, _ = compute_hourly_entry_indices(hourly, bearish_regime)
    assert 41 not in entries_blocked


def test_compute_hourly_entry_indices_skips_when_regime_not_yet_seeded():
    hourly = _decline_then_rise_series("BTC/USD", label="h")
    entries, _, _ = compute_hourly_entry_indices(hourly, daily_regime_series=[None, None, None])
    assert entries == []


def _hold_then_red_candles():
    """entry candle (index 0), two green candles, then a red candle that should trigger the exit."""
    return [
        Candle("BTC/USD", "t0", open=100, high=101, low=99, close=100, volume=10),   # entry candle
        Candle("BTC/USD", "t1", open=100, high=105, low=99, close=104, volume=10),   # green -> hold
        Candle("BTC/USD", "t2", open=104, high=108, low=103, close=107, volume=10),  # green -> hold
        Candle("BTC/USD", "t3", open=107, high=108, low=101, close=102, volume=10),  # red -> exit here
        Candle("BTC/USD", "t4", open=102, high=110, low=101, close=109, volume=10),  # after exit, shouldn't matter
    ]


def test_simulate_macd_d1h1_exits_at_close_of_first_red_candle():
    candles = _hold_then_red_candles()

    trades, equity_curve = simulate_macd_d1h1(candles, entry_indices=[0], capital=100.0, fee_pct=0.0, slippage_bps=0.0)

    assert len(trades) == 1
    trade = trades[0]
    assert trade.entry_index == 0
    assert trade.entry_price == 100
    assert trade.exit_index == 3
    assert trade.exit_price == 102  # close of the first red candle, not its open/low/high
    assert trade.exit_reason == "trend_break"
    assert trade.pnl > 0
    nominal_risk_amount = 100.0 * (DEFAULT_RISK_PER_TRADE_PCT / 100)
    assert round(trade.r_multiple, 6) == round(trade.pnl / nominal_risk_amount, 6)


def test_simulate_macd_d1h1_marks_to_last_close_when_no_red_candle_ever_closes():
    candles = [
        Candle("BTC/USD", "t0", open=100, high=101, low=99, close=100, volume=10),
        Candle("BTC/USD", "t1", open=100, high=105, low=99, close=104, volume=10),
        Candle("BTC/USD", "t2", open=104, high=108, low=103, close=107, volume=10),
        Candle("BTC/USD", "t3", open=107, high=112, low=106, close=110, volume=10),  # still green -> never exits
    ]

    trades, _ = simulate_macd_d1h1(candles, entry_indices=[0], capital=100.0, fee_pct=0.0, slippage_bps=0.0)

    assert len(trades) == 1
    trade = trades[0]
    assert trade.exit_index == 3
    assert trade.exit_price == 110  # marked to the last close
    assert trade.exit_reason == "eol"


def test_simulate_macd_d1h1_applies_fees_to_reduce_net_pnl():
    candles = _hold_then_red_candles()

    with_fees, _ = simulate_macd_d1h1(candles, entry_indices=[0], capital=100.0, fee_pct=0.25, slippage_bps=5.0)
    no_fees, _ = simulate_macd_d1h1(candles, entry_indices=[0], capital=100.0, fee_pct=0.0, slippage_bps=0.0)

    assert len(with_fees) == 1 and len(no_fees) == 1
    assert with_fees[0].gross_pnl == no_fees[0].gross_pnl  # fees don't move the trigger levels
    assert with_fees[0].pnl < no_fees[0].pnl
    assert with_fees[0].fees_paid > 0


def test_simulate_macd_d1h1_sizes_position_flat_at_max_position_pct():
    # No risk_pct/stop-distance sizing here (see module docstring judgment
    # call 1) — every trade is sized at max_position_pct of equity.
    candles = _hold_then_red_candles()

    trades, _ = simulate_macd_d1h1(
        candles, entry_indices=[0], capital=100.0, max_position_pct=25.0, fee_pct=0.0, slippage_bps=0.0,
    )

    trade = trades[0]
    expected_position_size = (100.0 * (25.0 / 100)) / trade.entry_price
    assert round(trade.gross_pnl, 6) == round(expected_position_size * (trade.exit_price - trade.entry_price), 6)


def test_simulate_macd_d1h1_skips_new_signal_while_position_open():
    candles = _hold_then_red_candles()
    # index 2 is also listed as a signal, but the position from index 0
    # hasn't resolved yet (it resolves at index 3) — should be skipped,
    # not opened as a second overlapping position.
    trades, _ = simulate_macd_d1h1(candles, entry_indices=[0, 2], capital=100.0, fee_pct=0.0, slippage_bps=0.0)

    assert len(trades) == 1
    assert trades[0].entry_index == 0


def test_slice_trades_by_folds_splits_and_pools_by_entry_timestamp():
    trades = [
        MacdD1H1Trade(0, 1, "t0", "t1", 100, 110, "trend_break", 10.0, 0.0, 10.0, 1.0),
        MacdD1H1Trade(2, 3, "t31", "t32", 110, 100, "trend_break", -10.0, 0.0, -10.0, -1.0),
        MacdD1H1Trade(4, 5, "t61", "t62", 100, 90, "eol", -10.0, 0.0, -10.0, -1.0),
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
