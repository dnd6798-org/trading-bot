"""
ONE-OFF — universe selection for the 10-asset rotational Donchian ensemble
milestone (CLAUDE.md finding 10). Not meant to be maintained/re-run as
part of the regular backtest suite (same status as
sanity_check_daily_signal.py) — its output (the locked 10-symbol list) is
what gets hardcoded into the ensemble backtest and, eventually,
data_ingestion.py's TRADING_PAIRS.

Method (per instruction — query Alpaca live, don't guess a symbol list):
  1. Pull every active, tradable crypto asset from Alpaca's
     /v2/assets?asset_class=crypto via TradingClient.get_all_assets().
  2. Keep only USD-quoted pairs ("XXX/USD"), drop stablecoin bases (a
     stablecoin-vs-USD pair has ~no directional price action for a
     trend-following signal to trade) and PAXG (gold-tracking token, same
     reasoning — it's not a stablecoin but it isn't a growth/momentum
     asset either... actually see note below, kept in as a candidate,
     ranked on volume like everything else, not hand-excluded).
  3. BTC/USD and ETH/USD are excluded from the ranking (they're included
     in the final universe by default, per instruction) but always
     fetched and reported for reference.
  4. For every remaining candidate, fetch the last LOOKBACK_DAYS of 1h
     candles (data_ingestion.py's only supported timeframe) and compute
     average daily dollar volume = sum(volume * close over all fetched
     hourly candles) / LOOKBACK_DAYS — a liquidity proxy using the same
     OHLCV data the rest of this repo already fetches, not a separate
     data source.
  5. Rank descending by average daily dollar volume, report the full
     candidate list, and print the top N.

Judgment call, flagged: PAXG (Pax Gold) is not a stablecoin (it tracks
gold spot price, not USD 1:1) so it is NOT hand-excluded here — it's
ranked on volume with everything else and only drops out if it doesn't
place in the top 8.

Usage:
    python scripts/select_universe.py
    python scripts/select_universe.py --lookback-days 30 --top-n 8
"""
import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetAssetsRequest
from alpaca.trading.enums import AssetClass, AssetStatus

from src.config import get_alpaca_config
from src.data_ingestion import fetch_historical_candles

DEFAULT_LOOKBACK_DAYS = 30
DEFAULT_TOP_N = 8
DEFAULT_EXCLUDE = {"BTC/USD", "ETH/USD"}  # included by default, not ranked

# Stablecoin bases (vs. USD, ~no directional price action to trade) —
# any "<BASE>/USD" symbol whose base is in this set is dropped before
# ranking, not just naturally out-ranked by volume.
STABLECOIN_BASES = {"USDC", "USDT", "USDG", "DAI", "BUSD", "TUSD", "GUSD", "PAX", "PYUSD", "EURC", "USDP"}


def list_usd_crypto_candidates():
    cfg = get_alpaca_config()
    client = TradingClient(cfg.api_key, cfg.secret_key, paper=cfg.paper)
    req = GetAssetsRequest(asset_class=AssetClass.CRYPTO, status=AssetStatus.ACTIVE)
    assets = client.get_all_assets(req)
    usd_assets = [a for a in assets if a.tradable and a.symbol.endswith("/USD")]

    excluded_stablecoin = []
    candidates = []
    for a in usd_assets:
        base = a.symbol.split("/")[0]
        if base in STABLECOIN_BASES:
            excluded_stablecoin.append(a.symbol)
        else:
            candidates.append(a.symbol)
    return sorted(candidates), sorted(excluded_stablecoin)


def average_daily_dollar_volume(symbol, start, end, lookback_days):
    candles = fetch_historical_candles(symbol, start, end)
    if not candles:
        return 0.0, 0
    dollar_volume = sum(c.volume * c.close for c in candles)
    return dollar_volume / lookback_days, len(candles)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS)
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N)
    return parser.parse_args()


def main():
    args = parse_args()
    end = datetime.now(timezone.utc) - timedelta(minutes=20)  # crypto bars need a short settle delay
    start = end - timedelta(days=args.lookback_days)

    candidates, excluded_stablecoin = list_usd_crypto_candidates()
    print(f"Active, tradable USD-quoted crypto pairs on Alpaca: {len(candidates) + len(excluded_stablecoin) + len(DEFAULT_EXCLUDE)}")
    print(f"Excluded as stablecoin pairs ({len(excluded_stablecoin)}): {', '.join(excluded_stablecoin)}")
    print(f"Excluded, included-by-default ({len(DEFAULT_EXCLUDE)}): {', '.join(sorted(DEFAULT_EXCLUDE))}")
    rankable = [s for s in candidates if s not in DEFAULT_EXCLUDE]
    print(f"Candidates to rank by liquidity: {len(rankable)}")
    print(f"Volume window: last {args.lookback_days}d ending {end.date()}\n")

    results = []
    for symbol in DEFAULT_EXCLUDE | set(rankable):
        avg_dollar_vol, n_candles = average_daily_dollar_volume(symbol, start, end, args.lookback_days)
        results.append({"symbol": symbol, "avg_daily_dollar_volume": avg_dollar_vol, "candles": n_candles})

    results.sort(key=lambda r: r["avg_daily_dollar_volume"], reverse=True)

    print(f"{'symbol':<12}{'avg daily $ volume':>22}{'candles fetched':>18}")
    print("-" * 52)
    for r in results:
        flag = " (default)" if r["symbol"] in DEFAULT_EXCLUDE else ""
        print(f"{r['symbol']:<12}{r['avg_daily_dollar_volume']:>22,.0f}{r['candles']:>18}{flag}")

    ranked_candidates = [r for r in results if r["symbol"] not in DEFAULT_EXCLUDE]
    top_n = ranked_candidates[:args.top_n]
    print(f"\nTop {args.top_n} by avg daily dollar volume (excl. BTC/ETH, excl. stablecoins):")
    for r in top_n:
        print(f"  {r['symbol']:<10} ${r['avg_daily_dollar_volume']:,.0f}/day")

    final_universe = sorted(DEFAULT_EXCLUDE) + [r["symbol"] for r in top_n]
    print(f"\nProposed final universe ({len(final_universe)} symbols): {', '.join(final_universe)}")


if __name__ == "__main__":
    main()
