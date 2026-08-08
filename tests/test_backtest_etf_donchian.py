"""
Verifies scripts/backtest_etf_donchian.py's own new pieces only —
compute_channel_long_entry_indices() (reparameterized on channel_length,
unlike backtest_donchian_ensemble.py's hardcoded-global version) and
check_no_same_day_round_trips() (the new PDT guard, crypto has no
equivalent). Everything else this script uses (simulate_rotational_
ensemble, slice_ensemble_trades_by_folds, the buy-and-hold helpers) is
imported unchanged from backtest_donchian_ensemble.py and already has its
own test coverage in test_backtest_donchian_ensemble.py — not duplicated
here. No network calls.
"""
from src.data_ingestion import Candle
from scripts.backtest_donchian_ensemble import EnsembleTrade
from scripts.backtest_etf_donchian import (
    compute_channel_long_entry_indices,
    check_no_same_day_round_trips,
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


# --- compute_channel_long_entry_indices (reparameterized on channel_length) --

def test_channel_entry_does_not_fire_before_window_is_seeded():
    dates = [f"2021-01-{i + 1:02d}" for i in range(21)]
    candles = [_flat_candle("SPY", dates[i]) for i in range(19)]  # one short of a full 20-day window
    candles.append(_candle("SPY", dates[19], close=125, high=130, low=120))

    entry_indices, atr = compute_channel_long_entry_indices(candles, channel_length=20)

    assert 19 not in entry_indices


def test_channel_entry_fires_on_close_above_band_once_window_is_seeded():
    dates = [f"d{i}" for i in range(21)]
    candles = [_flat_candle("SPY", dates[i]) for i in range(20)]
    candles.append(_candle("SPY", dates[20], close=125, high=130, low=120))

    entry_indices, atr = compute_channel_long_entry_indices(candles, channel_length=20)

    assert 20 in entry_indices
    assert atr[20] is not None


def test_channel_entry_defaults_to_module_channel_length_of_100():
    dates = [f"d{i}" for i in range(101)]
    candles = [_flat_candle("SPY", dates[i]) for i in range(100)]
    candles.append(_candle("SPY", dates[100], close=125, high=130, low=120))

    entry_indices, atr = compute_channel_long_entry_indices(candles)

    assert 100 in entry_indices


# --- check_no_same_day_round_trips ------------------------------------------

def test_check_no_same_day_round_trips_flags_a_same_day_entry_and_exit():
    trades = [
        EnsembleTrade("SPY", 0, 1, "2022-01-03T05:00:00", "2022-01-03T05:00:00", 100, 110, "trailing_stop", 10.0, 0.0, 10.0, 1.0),
    ]

    violations = check_no_same_day_round_trips(trades)

    assert len(violations) == 1
    assert violations[0].symbol == "SPY"


def test_check_no_same_day_round_trips_passes_when_entry_and_exit_dates_differ():
    trades = [
        EnsembleTrade("SPY", 0, 1, "2022-01-03T05:00:00", "2022-01-04T05:00:00", 100, 110, "trailing_stop", 10.0, 0.0, 10.0, 1.0),
        EnsembleTrade("QQQ", 2, 5, "2022-01-05T05:00:00", "2022-01-10T05:00:00", 200, 190, "eol", -10.0, 0.0, -10.0, -1.0),
    ]

    violations = check_no_same_day_round_trips(trades)

    assert violations == []


def test_check_no_same_day_round_trips_on_empty_trade_list():
    assert check_no_same_day_round_trips([]) == []
