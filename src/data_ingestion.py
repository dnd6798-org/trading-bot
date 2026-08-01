"""
Pipeline step 1 (spec §3.1.1): market data ingestion.

Pulls price/volume candles for the trading universe (BTC/USD, ETH/USD —
spec §2) on the locked timeframe (1h). Feeds signal_generation.py.

TODO (live-loop build session, not this one — backtest first, playbook v6 §9):
- Live/streaming candle fetch for the intraday loop
- Data quality checks per spec §4.5: bad/missing data must halt
  decision-making, never trade on garbage input — implement here as a
  validation gate before data reaches signal_generation.py
"""
from dataclasses import dataclass
from datetime import datetime

from alpaca.data.historical.crypto import CryptoHistoricalDataClient
from alpaca.data.requests import CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame

from .config import get_alpaca_config

TRADING_PAIRS = ["BTC/USD", "ETH/USD"]  # spec §2, locked
TIMEFRAME = "1Hour"  # spec §2, locked — hourly candles


@dataclass
class Candle:
    symbol: str
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float


def fetch_historical_candles(symbol: str, start: datetime, end: datetime, timeframe: str = TIMEFRAME) -> list[Candle]:
    """
    Fetch historical 1h candles for backtesting via Alpaca's crypto market
    data API. Crypto market data is unauthenticated-tier public data, but
    this reuses the paper Alpaca keys already configured in .env rather
    than introducing a separate credential path.
    """
    if timeframe != TIMEFRAME:
        raise ValueError(f"Only {TIMEFRAME} candles are supported (spec §2, locked)")

    cfg = get_alpaca_config()
    client = CryptoHistoricalDataClient(api_key=cfg.api_key, secret_key=cfg.secret_key)
    request = CryptoBarsRequest(
        symbol_or_symbols=[symbol],
        timeframe=TimeFrame.Hour,
        start=start,
        end=end,
    )
    barset = client.get_crypto_bars(request)
    bars = barset[symbol]
    return [
        Candle(
            symbol=bar.symbol,
            timestamp=bar.timestamp.isoformat(),
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
        )
        for bar in bars
    ]


def fetch_latest_candle(symbol: str, timeframe: str = TIMEFRAME):
    """Fetch the most recent completed candle for live/paper trading."""
    raise NotImplementedError("Implement during live-loop build session")


def validate_data(candle) -> bool:
    """
    Data quality gate (spec §4.5): return False on missing/bad data so the
    caller halts rather than trading on it. Never silently pass through.
    """
    raise NotImplementedError
