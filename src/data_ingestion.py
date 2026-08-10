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
from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.requests import CryptoBarsRequest, OptionBarsRequest, StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOptionContractsRequest

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


@dataclass
class OptionContract:
    symbol: str
    strike_price: float
    expiration_date: str  # "YYYY-MM-DD"
    option_type: str  # "put" | "call"


def fetch_option_contracts(
    underlying: str, expiration_date: str, option_type: str = "put"
) -> list[OptionContract]:
    """
    Track C (spec v25 §10.5, put credit spread): the strike ladder for one
    specific expiration, queried directly by that expiration date — NOT
    from today's active-contract list (CLAUDE.md Track C finding 2: far-
    dated series list progressively, so "today's chain" can silently omit
    contracts that existed as of an earlier historical date). Querying by
    the target expiration_date itself sidesteps that entirely: a contract's
    metadata (strike, expiration) is static regardless of when it's
    queried, so there's no "as of" ambiguity to get wrong here.

    Queries BOTH 'active' and 'inactive' status and merges the results
    (deduplicated by symbol) — Alpaca's contract-search defaults to
    'active' only, which returns nothing for any already-expired
    expiration (confirmed empirically: a 0-result query for a March 2024
    expiry with status omitted, 208 contracts with status='inactive'
    explicitly passed). Since backtesting is inherently retrospective,
    most expirations queried here will be 'inactive' by the time this
    runs, but 'active' is checked too for expirations that haven't
    resolved yet.
    """
    cfg = get_alpaca_config()
    client = TradingClient(api_key=cfg.api_key, secret_key=cfg.secret_key, paper=cfg.paper)

    by_symbol: dict[str, OptionContract] = {}
    for status in ("inactive", "active"):
        request = GetOptionContractsRequest(
            underlying_symbols=[underlying],
            expiration_date=expiration_date,
            type=option_type,
            status=status,
            limit=1000,
        )
        response = client.get_option_contracts(request)
        for c in response.option_contracts:
            by_symbol[c.symbol] = OptionContract(
                symbol=c.symbol,
                strike_price=float(c.strike_price),
                expiration_date=c.expiration_date.isoformat(),
                option_type=str(c.type.value) if hasattr(c.type, "value") else str(c.type),
            )
    return sorted(by_symbol.values(), key=lambda c: c.strike_price)


def fetch_option_bars(symbol: str, start: datetime, end: datetime) -> list[Candle]:
    """
    Daily OHLCV bars for one option contract (Track C — see
    fetch_option_contracts()'s docstring for why the chain itself is
    queried per-expiration rather than from today's list). Reuses the
    Candle dataclass — an option daily bar has the same OHLCV shape as a
    stock/crypto one; no bid/ask or greeks fields exist historically on
    this account regardless (CLAUDE.md Track C finding 2), so there is
    nothing to add.
    """
    cfg = get_alpaca_config()
    client = OptionHistoricalDataClient(api_key=cfg.api_key, secret_key=cfg.secret_key)
    request = OptionBarsRequest(
        symbol_or_symbols=[symbol],
        timeframe=TimeFrame.Day,
        start=start,
        end=end,
    )
    response = client.get_option_bars(request)
    bars = response.data.get(symbol, [])
    return [
        Candle(
            symbol=symbol,
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
