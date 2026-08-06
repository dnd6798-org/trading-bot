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


def compute_macd(prices, fast_period: int = 12, slow_period: int = 26, signal_period: int = 9):
    """
    Standard MACD: macd_line = EMA(fast) - EMA(slow), signal_line =
    EMA(macd_line, signal_period) — computed by feeding the macd_line's
    valid (non-None) tail back through compute_ema(), so the signal line
    is seeded via SMA of its first `signal_period` values exactly like any
    other EMA in this module (same seeding convention as compute_ema,
    applied recursively). Returns (macd_line, signal_line, histogram),
    each the same length as `prices`, with leading Nones wherever the
    underlying EMAs aren't seeded yet.
    """
    n = len(prices)
    ema_fast = compute_ema(prices, fast_period)
    ema_slow = compute_ema(prices, slow_period)

    macd_line = [None] * n
    for i in range(n):
        if ema_fast[i] is not None and ema_slow[i] is not None:
            macd_line[i] = ema_fast[i] - ema_slow[i]

    first_valid = next((i for i, v in enumerate(macd_line) if v is not None), None)
    signal_line = [None] * n
    if first_valid is not None:
        signal_tail = compute_ema(macd_line[first_valid:], signal_period)
        for offset, value in enumerate(signal_tail):
            signal_line[first_valid + offset] = value

    histogram = [None] * n
    for i in range(n):
        if macd_line[i] is not None and signal_line[i] is not None:
            histogram[i] = macd_line[i] - signal_line[i]

    return macd_line, signal_line, histogram


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
