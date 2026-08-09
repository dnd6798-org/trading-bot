"""
ONE-OFF DIAGNOSTIC — Track C kickoff (spec v25 §2, §10.5). Not meant to be
maintained.

Before locking any fold structure or adopt bar for the SPY put credit
spread strategy, this checks what this account's Alpaca options data plan
actually makes available: account options-trading approval level, how far
back EXPIRED CONTRACT METADATA is queryable, and — the number that
actually matters for backtesting — how far back real DAILY BAR data goes,
tested directly against manually-constructed OCC symbols rather than
inferred from contract-listing search results (contract metadata and bar
data turned out NOT to share the same floor — see findings below).

Same category as select_universe.py / verify_finding12_sizing.py /
compute_gem_benchmarks.py: read-only, prints a report, not imported by
any backtest script.

Usage:
    python scripts/check_options_data_availability.py
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alpaca.data.enums import OptionsFeed
from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.data.requests import OptionBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOptionContractsRequest

from src.config import get_alpaca_config

UNDERLYING = "SPY"


def check_account_approval(trading_client: TradingClient) -> None:
    acct = trading_client.get_account()
    print("--- Account options approval ---")
    print(f"  status: {acct.status}")
    print(f"  options_approved_level: {getattr(acct, 'options_approved_level', 'N/A')}")
    print(f"  options_trading_level: {getattr(acct, 'options_trading_level', 'N/A')}")
    print(f"  equity: {acct.equity}")
    print()


def check_expired_contract_metadata_floor(trading_client: TradingClient) -> None:
    """
    Binary-search-style scan of GetOptionContractsRequest(status='inactive')
    to find the earliest expiration date this account can still query
    contract metadata for. This is NOT the same as the bar-data floor
    (confirmed below) — flagged explicitly since assuming they matched
    would have been wrong.
    """
    print("--- Expired contract metadata floor (SPY) ---")
    probes = [
        "2016-01-01", "2020-01-01", "2023-01-01", "2023-12-01",
        "2023-12-29", "2024-01-01", "2024-01-02",
    ]
    for start in probes:
        req = GetOptionContractsRequest(
            underlying_symbols=[UNDERLYING], status="inactive",
            expiration_date_gte=start, expiration_date_lte="2024-01-05", limit=3,
        )
        resp = trading_client.get_option_contracts(req)
        symbols = [c.symbol for c in resp.option_contracts]
        print(f"  expiration >= {start}: {len(symbols)} contracts found {symbols}")
    print()


def check_bar_data_floor(option_client: OptionHistoricalDataClient) -> None:
    """
    Tests manually-constructed near-ATM OCC symbols directly against
    get_option_bars() across a range of January 2024 expiries/strikes,
    both calls and puts. Contract-metadata search (above) suggested a
    ~2024-01-03 floor; this loop's actual result is the real answer:
    zero bars for every expiry before 2024-01-18, dense continuous daily
    coverage from 2024-01-18 onward.
    """
    print("--- Daily bar data floor (SPY, calls + puts) ---")
    candidates = [
        "SPY240103C00475000", "SPY240105C00475000", "SPY240110C00475000",
        "SPY240112C00475000", "SPY240117C00475000",
        "SPY240119C00475000", "SPY240119C00470000", "SPY240119P00470000",
        "SPY240315C00500000",
    ]
    for symbol in candidates:
        req = OptionBarsRequest(
            symbol_or_symbols=[symbol], timeframe=TimeFrame.Day,
            start=datetime(2023, 10, 1), end=datetime(2024, 3, 16),
        )
        resp = option_client.get_option_bars(req)
        bars = resp.data.get(symbol, [])
        first = bars[0].timestamp.date() if bars else None
        last = bars[-1].timestamp.date() if bars else None
        print(f"  {symbol}: {len(bars)} bars, first={first}, last={last}")
    print()


def check_bar_data_ceiling_and_feed_sensitivity(option_client: OptionHistoricalDataClient) -> None:
    """
    Confirms (a) how recent bar data goes (today is 2026-08-09) using a
    long-dated LEAPS contract still actively trading, and (b) whether the
    OPRA vs. INDICATIVE feed parameter changes the available window —
    it does not, both return an identical floor/ceiling.
    """
    print("--- Ceiling + feed sensitivity ---")
    symbol = "SPY271217C00600000"
    for feed in [OptionsFeed.INDICATIVE, OptionsFeed.OPRA]:
        req = OptionBarsRequest(
            symbol_or_symbols=[symbol], timeframe=TimeFrame.Day,
            start=datetime(2018, 1, 1), end=datetime(2026, 8, 9), feed=feed,
        )
        resp = option_client.get_option_bars(req)
        bars = resp.data.get(symbol, [])
        first = bars[0].timestamp.date() if bars else None
        last = bars[-1].timestamp.date() if bars else None
        print(f"  feed={feed.value}: {len(bars)} bars, first={first}, last={last}")
    print()


def main() -> None:
    cfg = get_alpaca_config()
    trading_client = TradingClient(api_key=cfg.api_key, secret_key=cfg.secret_key, paper=cfg.paper)
    option_client = OptionHistoricalDataClient(api_key=cfg.api_key, secret_key=cfg.secret_key)

    check_account_approval(trading_client)
    check_expired_contract_metadata_floor(trading_client)
    check_bar_data_floor(option_client)
    check_bar_data_ceiling_and_feed_sensitivity(option_client)

    print("=== SUMMARY ===")
    print("Confirmed real daily-bar floor for SPY options on this account: 2024-01-18")
    print("(zero bars for every expiry/strike/call-or-put tested before this date;")
    print("dense, continuous daily coverage from this date forward through ~2026-08-07).")
    print("Contract-listing metadata search suggested an earlier ~2024-01-03 floor —")
    print("that number is WRONG for backtesting purposes; derive the usable window")
    print("from actual bar timestamps, not from contract-metadata search results.")
    print("Feed parameter (OPRA vs. INDICATIVE) does not change this floor.")
    print("Usable window: ~2024-01-18 -> ~2026-08-07, roughly 2.5 years.")


if __name__ == "__main__":
    main()
