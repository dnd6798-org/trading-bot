"""
Verifies the EMA/ATR/volume indicator math against hand-checked values,
independent of the backtest run itself (backtest session, see
scripts/backtest.py).
"""
from dataclasses import dataclass

from src.signal_generation import (
    compute_ema,
    compute_atr,
    volume_confirms,
    generate_signal,
    SignalDirection,
)


@dataclass
class Candle:
    symbol: str
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float


def test_compute_ema_seeds_with_sma_then_smooths():
    # period=3 seeds on the SMA of the first 3 prices, alpha = 2/(3+1) = 0.5
    prices = [10, 11, 12, 13, 14]
    ema = compute_ema(prices, period=3)
    assert ema[0] is None and ema[1] is None
    assert ema[2] == 11        # SMA(10, 11, 12)
    assert ema[3] == 12        # 13*0.5 + 11*0.5
    assert ema[4] == 13        # 14*0.5 + 12*0.5


def test_compute_ema_insufficient_data_returns_all_none():
    assert compute_ema([1, 2], period=5) == [None, None]


def test_compute_atr_seeds_with_average_tr_then_wilder_smooths():
    candles = [
        Candle("BTC/USD", "t0", open=9, high=10, low=8, close=9, volume=1),
        Candle("BTC/USD", "t1", open=9, high=11, low=9, close=10, volume=1),   # TR = 2
        Candle("BTC/USD", "t2", open=10, high=12, low=10, close=11, volume=1),  # TR = 2
        Candle("BTC/USD", "t3", open=11, high=13, low=9, close=12, volume=1),   # TR = max(4, 2, 2) = 4
    ]
    atr = compute_atr(candles, period=2)
    assert atr[0] is None and atr[1] is None
    assert atr[2] == 2   # avg(TR1, TR2) = avg(2, 2)
    assert atr[3] == 3   # (2*(2-1) + 4) / 2


def test_volume_confirms_true_when_above_average():
    candles = [Candle("BTC/USD", f"t{i}", 1, 1, 1, 1, volume=v) for i, v in enumerate([10, 10, 10, 20])]
    assert volume_confirms(candles, lookback=3) is True


def test_volume_confirms_false_when_below_average():
    candles = [Candle("BTC/USD", f"t{i}", 1, 1, 1, 1, volume=v) for i, v in enumerate([10, 10, 20, 5])]
    assert volume_confirms(candles, lookback=3) is False


def test_volume_confirms_false_with_insufficient_history():
    candles = [Candle("BTC/USD", "t0", 1, 1, 1, 1, volume=100)]
    assert volume_confirms(candles, lookback=20) is False


def _build_crossover_candles():
    """
    A synthetic 1h series: a decline (fast EMA below slow EMA) followed by
    a sharp rise that flips the fast EMA above the slow EMA on the final
    candle, with a volume spike on that same candle.
    """
    candles = []
    price = 100.0
    # Downtrend long enough to seed both EMAs (21) and ATR (14) with the
    # fast EMA below the slow EMA.
    for i in range(25):
        price -= 1.0
        candles.append(Candle(
            symbol="BTC/USD", timestamp=f"t{i}",
            open=price + 1, high=price + 1.5, low=price - 0.5, close=price,
            volume=10,
        ))
    # Sharp rise to force a crossover, volume spike on the last candle.
    for i in range(25, 30):
        price += 5.0
        candles.append(Candle(
            symbol="BTC/USD", timestamp=f"t{i}",
            open=price - 5, high=price + 0.5, low=price - 5.5, close=price,
            volume=10 if i < 29 else 100,
        ))
    return candles


def test_generate_signal_fires_long_on_crossover_with_volume_confirmation():
    candles = _build_crossover_candles()
    signal = generate_signal(candles, ema_fast_period=9, ema_slow_period=21)
    assert signal is not None
    assert signal.direction == SignalDirection.LONG
    assert signal.symbol == "BTC/USD"
    assert signal.entry_price == candles[-1].close
    assert signal.atr is not None


def test_generate_signal_returns_none_with_no_crossover():
    # Flat prices never cross.
    candles = [
        Candle("BTC/USD", f"t{i}", open=100, high=100.5, low=99.5, close=100, volume=10)
        for i in range(30)
    ]
    assert generate_signal(candles, ema_fast_period=9, ema_slow_period=21) is None


def test_generate_signal_returns_none_without_volume_confirmation():
    candles = _build_crossover_candles()
    # Kill the volume spike on the final candle so confirmation fails.
    candles[-1] = Candle(
        symbol=candles[-1].symbol, timestamp=candles[-1].timestamp,
        open=candles[-1].open, high=candles[-1].high, low=candles[-1].low,
        close=candles[-1].close, volume=1,
    )
    assert generate_signal(candles, ema_fast_period=9, ema_slow_period=21) is None
