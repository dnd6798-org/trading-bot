"""
Verifies scripts/backtest_walkforward.py's fold-boundary math and
multi-fold trade-splitting logic against deterministic synthetic candles —
no network calls. simulate()/summarize() themselves are already covered by
test_backtest.py; this only covers the new anchored-walk-forward slicing
built on top of them.
"""
from datetime import datetime, timezone

from src.data_ingestion import Candle
from scripts.backtest_walkforward import (
    compute_fold_boundaries,
    run_multi_fold_walk_forward,
)


def test_compute_fold_boundaries_anchors_train_and_splits_test_evenly():
    start = datetime(2021, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 1, 1, tzinfo=timezone.utc)  # 5 years = 1826 days

    folds = compute_fold_boundaries(start, end, num_folds=5, initial_train_days=365)

    assert len(folds) == 5
    # Every fold's train window is anchored at history start...
    assert all(f["train_start"] == start for f in folds)
    # ...and grows: each fold's train_end is the previous fold's test_end.
    for i in range(1, 5):
        assert folds[i]["train_end"] == folds[i - 1]["test_end"]
    # Test windows are contiguous and non-overlapping.
    for i in range(4):
        assert folds[i]["test_end"] == folds[i + 1]["test_start"]
    # First test window starts right after the initial training period.
    assert folds[0]["test_start"] == start.replace(year=2022)
    # Last fold's test window ends exactly at the requested end.
    assert folds[-1]["test_end"] == end
    # Roughly-even test windows: (1826 - 365) / 5 ~= 292.2 days each.
    first_window_days = (folds[0]["test_end"] - folds[0]["test_start"]).days
    assert 290 <= first_window_days <= 294


def test_compute_fold_boundaries_rejects_train_window_longer_than_history():
    start = datetime(2021, 1, 1, tzinfo=timezone.utc)
    end = datetime(2021, 6, 1, tzinfo=timezone.utc)  # 5 months, less than a 365-day train window
    try:
        compute_fold_boundaries(start, end, num_folds=5, initial_train_days=365)
        assert False, "expected ValueError"
    except ValueError:
        pass


def _step_candles(symbol, start_index, count, price_step, base_price, volume=10):
    candles = []
    price = base_price
    for i in range(count):
        price += price_step
        candles.append(Candle(
            symbol, f"t{start_index + i}",
            open=price, high=price + 0.5, low=price - 0.5, close=price, volume=volume,
        ))
    return candles


def _crossover_setup(start_index, base_price=100.0):
    """
    One decline-then-rise cycle producing a single 9/21 EMA crossover with
    volume confirmation, mirroring test_backtest.py's fixture. Volume is
    spiked on the last two rise candles rather than just the last one:
    when this is chained after an earlier setup, residual EMA state from
    the prior cycle can shift exactly which bar the crossunder/crossover
    lands on by one, so spiking two candles reliably covers it either way
    (matches test_backtest.py's own chained-cycle fixture).
    """
    candles = _step_candles("BTC/USD", start_index, 25, -1.0, base_price + 1.0)
    rise = _step_candles("BTC/USD", start_index + 25, 5, 5.0, candles[-1].close)
    for r in rise[-2:]:
        r.volume = 100
    return candles + rise


def test_run_multi_fold_walk_forward_assigns_trades_to_correct_fold_by_entry_timestamp():
    # Two independent crossover setups, far enough apart in index (hence
    # timestamp, since Candle timestamps here are just "t{i}" strings that
    # sort lexicographically-then-numerically-enough for this test) that a
    # 2-fold boundary drawn between them puts one trade in each fold.
    setup_a = _crossover_setup(0)  # crossover at index 29
    setup_a.append(Candle("BTC/USD", "t30", open=101, high=110, low=99, close=105, volume=10))  # resolves trade 1

    setup_b = _crossover_setup(31, base_price=105.0)  # crossover at index 60
    setup_b.append(Candle("BTC/USD", "t61", open=101, high=110, low=99, close=105, volume=10))  # resolves trade 2

    candles = setup_a + setup_b

    # Fake "datetime-like" boundaries: since Candle.timestamp here is a
    # plain string ("t0".."t61"), and compute_fold_boundaries expects real
    # datetimes, build folds by hand using string cutoffs instead — the
    # function under test only compares fold["test_start"].isoformat()
    # against trade.entry_timestamp as strings, so a lightweight stand-in
    # with .isoformat() is enough to isolate the slicing logic.
    class FakeBoundary:
        def __init__(self, s):
            self._s = s
        def isoformat(self):
            return self._s

    folds = [
        {"fold": 1, "train_start": FakeBoundary("t0"), "train_end": FakeBoundary("t0"),
         "test_start": FakeBoundary("t0"), "test_end": FakeBoundary("t31")},
        {"fold": 2, "train_start": FakeBoundary("t0"), "train_end": FakeBoundary("t31"),
         "test_start": FakeBoundary("t31"), "test_end": FakeBoundary("t99")},
    ]

    fold_summaries, pooled = run_multi_fold_walk_forward(
        candles, folds, ema_fast_period=9, ema_slow_period=21, atr_multiplier=2.0, capital=100.0,
    )

    assert len(fold_summaries) == 2
    assert fold_summaries[0]["trade_count"] == 1
    assert fold_summaries[1]["trade_count"] == 1
    # Pooled combines both folds' trades (both fall at/after fold 1's test_start).
    assert pooled["trade_count"] == 2


def test_run_multi_fold_walk_forward_handles_fold_with_no_trades():
    candles = _crossover_setup(0)
    candles.append(Candle("BTC/USD", "t30", open=101, high=110, low=99, close=105, volume=10))

    class FakeBoundary:
        def __init__(self, s):
            self._s = s
        def isoformat(self):
            return self._s

    # Fold 1 covers the only trade; fold 2 covers a window with nothing in it.
    folds = [
        {"fold": 1, "train_start": FakeBoundary("t0"), "train_end": FakeBoundary("t0"),
         "test_start": FakeBoundary("t0"), "test_end": FakeBoundary("t31")},
        {"fold": 2, "train_start": FakeBoundary("t0"), "train_end": FakeBoundary("t31"),
         "test_start": FakeBoundary("t31"), "test_end": FakeBoundary("t99")},
    ]

    fold_summaries, pooled = run_multi_fold_walk_forward(
        candles, folds, ema_fast_period=9, ema_slow_period=21, atr_multiplier=2.0, capital=100.0,
    )

    assert fold_summaries[0]["trade_count"] == 1
    assert fold_summaries[1]["trade_count"] == 0
    assert fold_summaries[1]["total_return_pct"] == 0.0
    assert pooled["trade_count"] == 1
