"""
Pipeline step 2 (spec §3.1.2): signal generation.

Strategy logic (spec §2, locked v1):
- Type: trend-following
- Signal: EMA crossover, 9-period over 21-period, on 1h candles
  (exact periods pending backtest calibration — playbook v6 §7)
- Confirmation filter: volume above recent average
- Exit logic: ATR-based stop-loss/take-profit (multiplier pending backtest)

"No setup, no trade" is a valid, required outcome (spec §4.1) — this
function returning None is not an error case, it's the common case.
"""
from dataclasses import dataclass
from enum import Enum


class SignalDirection(Enum):
    LONG = "long"
    SHORT = "short"


@dataclass
class TradeSignal:
    symbol: str
    direction: SignalDirection
    entry_price: float
    atr: float
    timestamp: str


def compute_ema(prices, period: int):
    """
    Standard EMA: seeded with a simple average of the first `period` prices,
    then smoothed forward with alpha = 2 / (period + 1). Returns a list the
    same length as `prices`, with the first `period - 1` entries as None
    (not enough data yet to seed the average).
    """
    if period <= 0:
        raise ValueError("period must be positive")
    n = len(prices)
    ema = [None] * n
    if n < period:
        return ema

    seed = sum(prices[:period]) / period
    ema[period - 1] = seed
    alpha = 2 / (period + 1)
    for i in range(period, n):
        ema[i] = prices[i] * alpha + ema[i - 1] * (1 - alpha)
    return ema


def compute_atr(candles, period: int = 14):
    """
    Wilder's ATR. `candles` is a sequence of objects/dicts with high, low,
    close. Returns a list the same length as `candles`, with the first
    `period` entries as None (needs `period` true ranges to seed, which
    requires `period + 1` candles since TR[0] has no prior close).
    """
    if period <= 0:
        raise ValueError("period must be positive")
    n = len(candles)
    atr = [None] * n
    if n <= period:
        return atr

    def _field(c, name):
        return c[name] if isinstance(c, dict) else getattr(c, name)

    true_ranges = [None] * n
    for i in range(1, n):
        high = _field(candles[i], "high")
        low = _field(candles[i], "low")
        prev_close = _field(candles[i - 1], "close")
        true_ranges[i] = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close),
        )

    seed = sum(true_ranges[1:period + 1]) / period
    atr[period] = seed
    for i in range(period + 1, n):
        atr[i] = (atr[i - 1] * (period - 1) + true_ranges[i]) / period
    return atr


def volume_confirms(candles, lookback: int = 20) -> bool:
    """
    Volume above recent average — spec §2 confirmation filter. Compares the
    most recent candle's volume to the average of the `lookback` candles
    preceding it (excludes the candle itself, so it's not comparing a value
    against an average that already contains it).
    """
    if len(candles) < lookback + 1:
        return False

    def _field(c, name):
        return c[name] if isinstance(c, dict) else getattr(c, name)

    recent_volume = _field(candles[-1], "volume")
    window = candles[-(lookback + 1):-1]
    avg_volume = sum(_field(c, "volume") for c in window) / lookback
    return recent_volume > avg_volume


def generate_signal(candles, ema_fast_period: int, ema_slow_period: int) -> TradeSignal | None:
    """
    Returns a TradeSignal on a valid EMA crossover + volume confirmation,
    or None on a no-setup candle (the expected, common case).

    Long-only for now (spec calibration is still open on short handling —
    playbook v6 §7): a signal fires when the fast EMA crosses above the
    slow EMA on the latest candle, confirmed by above-average volume.
    """
    def _field(c, name):
        return c[name] if isinstance(c, dict) else getattr(c, name)

    closes = [_field(c, "close") for c in candles]
    ema_fast = compute_ema(closes, ema_fast_period)
    ema_slow = compute_ema(closes, ema_slow_period)
    atr = compute_atr(candles)

    n = len(candles)
    if n < 2:
        return None
    if ema_fast[-1] is None or ema_slow[-1] is None:
        return None
    if ema_fast[-2] is None or ema_slow[-2] is None:
        return None
    if atr[-1] is None:
        return None

    crossed_up = ema_fast[-2] <= ema_slow[-2] and ema_fast[-1] > ema_slow[-1]
    if not crossed_up:
        return None
    if not volume_confirms(candles):
        return None

    last = candles[-1]
    return TradeSignal(
        symbol=_field(last, "symbol"),
        direction=SignalDirection.LONG,
        entry_price=_field(last, "close"),
        atr=atr[-1],
        timestamp=_field(last, "timestamp"),
    )
