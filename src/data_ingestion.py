"""
Pipeline step 1 (spec §3.1.1): market data ingestion.

Pulls price/volume candles for the trading universe (BTC/USD, ETH/USD —
spec §2) on the locked timeframe (1h). Feeds signal_generation.py.

TODO (next coding session — backtest first, per playbook v6 §9):
- Historical candle fetch for backtesting (Alpaca Market Data API)
- Live/streaming candle fetch for the intraday loop
- Data quality checks per spec §4.5: bad/missing data must halt
  decision-making, never trade on garbage input — implement here as a
  validation gate before data reaches signal_generation.py
"""

TRADING_PAIRS = ["BTC/USD", "ETH/USD"]  # spec §2, locked
TIMEFRAME = "1Hour"  # spec §2, locked — hourly candles


def fetch_historical_candles(symbol: str, start, end, timeframe: str = TIMEFRAME):
    """Fetch historical candles for backtesting. Not yet implemented."""
    raise NotImplementedError("Implement with Alpaca Market Data API — backtest session")


def fetch_latest_candle(symbol: str, timeframe: str = TIMEFRAME):
    """Fetch the most recent completed candle for live/paper trading."""
    raise NotImplementedError("Implement during live-loop build session")


def validate_data(candle) -> bool:
    """
    Data quality gate (spec §4.5): return False on missing/bad data so the
    caller halts rather than trading on it. Never silently pass through.
    """
    raise NotImplementedError
