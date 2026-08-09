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

from alpaca.data.enums import Adjustment
from alpaca.data.historical.crypto import CryptoHistoricalDataClient
from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.requests import CryptoBarsRequest, StockBarsRequest
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


def fetch_historical_stock_candles(
    symbol: str, start: datetime, end: datetime, adjustment: Adjustment = Adjustment.RAW
) -> list[Candle]:
    """
    Fetch historical daily candles for backtesting via Alpaca's stock/ETF
    market data API (spec v23 §10.1, Track B) — a separate product/data
    plan from crypto market data, hence its own client class, but reuses
    the same paper Alpaca keys (get_alpaca_config()), no new credential
    path. Daily bars only (unlike the crypto path's hourly-then-resample
    pattern): Track B's signal is daily-only, and Alpaca serves stock
    daily bars directly, so there's no need to fetch a finer timeframe.

    KNOWN ACCOUNT-LEVEL LIMIT, confirmed empirically before Track B's
    first backtest (not assumed): this account's historical stock data
    is truncated at 2016-01-04 regardless of the requested `start` date
    or feed parameter (SIP/IEX both truncate identically) — a data-plan
    tier limit, not a per-symbol gap (verified uniformly across all 8
    Track B tickers, including GLD/AGG/QQQ whose real inception dates are
    2004/2003/1999). Callers should derive their actual usable window from
    the returned candles' own timestamps, not assume `start` was honored.

    `adjustment` defaults to RAW (unadjusted close), matching Track B's
    already-locked/passed behavior exactly — Track B's Donchian breakout
    is a price-channel signal, not a total-return comparison, so dividend
    adjustment wasn't a correctness question there. Track A (GEM) passes
    Adjustment.ALL explicitly: GEM's signal IS a total-return comparison
    (12-month momentum ranking, absolute-momentum filter), and RAW prices
    are demonstrably wrong for that — confirmed empirically before Track
    A's first backtest, BIL's raw series shows an uncorrected ~2x
    discontinuity (an unadjusted split event) and AGG's raw price-only
    return is negative over a window where its true total return
    (dividend-inclusive) is positive. This is a correctness fix, not a
    style preference — RAW would silently break GEM's absolute-momentum
    filter, not just shift results slightly.
    """
    cfg = get_alpaca_config()
    client = StockHistoricalDataClient(api_key=cfg.api_key, secret_key=cfg.secret_key)
    request = StockBarsRequest(
        symbol_or_symbols=[symbol],
        timeframe=TimeFrame.Day,
        start=start,
        end=end,
        adjustment=adjustment,
    )
    barset = client.get_stock_bars(request)
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
