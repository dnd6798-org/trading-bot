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
    raise NotImplementedError("Backtest session — validate against known-good EMA values")


def compute_atr(candles, period: int = 14):
    raise NotImplementedError("Backtest session")


def volume_confirms(candles) -> bool:
    """Volume above recent average — spec §2 confirmation filter."""
    raise NotImplementedError


def generate_signal(candles, ema_fast_period: int, ema_slow_period: int) -> TradeSignal | None:
    """
    Returns a TradeSignal on a valid EMA crossover + volume confirmation,
    or None on a no-setup candle (the expected, common case).
    """
    raise NotImplementedError("Backtest session — this is the core logic to validate first")
