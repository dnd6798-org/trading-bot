"""
ONE-OFF — execution.py milestone's required end-to-end paper-account dry
run (spec v33 execution.py design session, CLAUDE.md "Current status" —
milestone brief step 6: "an end-to-end paper-account dry run placing at
least one real entry + stop pair"). Not meant to be maintained, same
convention as scripts/select_universe.py / scripts/stress_test_track_b_
risk_budget.py / scripts/quantify_track_b_notional_concentration.py.

WHAT THIS DOES: places one REAL order pair on the PAPER account (hard
safety assert below refuses to run against a live account) — a small,
fixed 1-share BUY on a fixed, liquid symbol (SPY), followed by a GTC stop
SELL a few dollars below the fill, exercising the exact same functions
run_daily_execution_job() uses for a real Track B signal: (market-hours
path) submit_entry_market_order() -> poll_order_until_terminal() ->
confirm_entry_fill() -> submit_stop_order_with_retry() ->
replace_stop_order_if_favorable(). This is a PIPELINE validation, not a
real Track B trading signal — it does NOT go through risk_filter.
evaluate() or any Donchian breakout check; the whole point is to prove
the order-submission/fill/stop-protection mechanics work end-to-end
against the real Alpaca paper API (things a FakeTradingClient-based unit
test, however careful, cannot actually prove: real request/response
schemas, real fractional-share handling, real stop-order acceptance,
real PATCH-replace semantics).

MARKET-HOURS-AWARE, DRY-RUN-ONLY DEVIATION: production Track B entries
are always plain TIF=DAY MARKET orders, submitted post-close, correctly
expected to sit PENDING until next session's open (see src/execution.py's
module docstring, "second flagged design gap" — poll_order_until_
terminal()'s short default timeout will NOT see a fill in that case, and
that's the expected, healthy outcome, not a failure). To let this
validation script prove the FULL fill+stop flow in one sitting, including
outside market hours, it checks the account clock first: if the market is
open, it submits a plain MARKET order exactly like production; if closed,
it submits a marketable extended-hours LIMIT order instead (ask + a small
buffer) purely so a real fill happens in THIS session rather than waiting
for the next open — this substitution is scoped to this script only, not
to execution.py's real entry path.

By default, once the stop order is confirmed resting, this script
CLEANS UP after itself (cancels the stop, sells the shares) so it
doesn't leave a stray test position sitting in the paper account between
real Track B runs. Pass --no-cleanup to leave the position and stop in
place for manual inspection in the Alpaca paper dashboard.

Usage:
    python scripts/dry_run_execution_track_b.py
    python scripts/dry_run_execution_track_b.py --symbol QQQ --qty 1 --no-cleanup
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import LimitOrderRequest, MarketOrderRequest

from src.config import get_alpaca_config
from src.execution import (
    poll_order_until_terminal,
    confirm_entry_fill,
    submit_stop_order_with_retry,
    replace_stop_order_if_favorable,
)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--symbol", default="SPY")
    parser.add_argument("--qty", type=float, default=1.0)
    parser.add_argument("--stop-distance", type=float, default=5.0, help="dollars below fill price for the test stop")
    parser.add_argument("--no-cleanup", action="store_true", help="leave the test position + stop resting instead of closing them out")
    return parser.parse_args()


def main():
    args = parse_args()
    cfg = get_alpaca_config()
    if not cfg.paper:
        raise SystemExit("REFUSING TO RUN: TRADING_ENV is not 'paper'. This script only ever runs against the paper account.")

    client = TradingClient(api_key=cfg.api_key, secret_key=cfg.secret_key, paper=True)

    print(f"=== execution.py dry run: {args.qty} share(s) of {args.symbol} on the PAPER account ===")
    print(f"account base URL: {cfg.base_url}")

    account = client.get_account()
    print(f"account equity before: ${float(account.equity):,.2f}")

    clock = client.get_clock()
    print(f"market clock: is_open={clock.is_open}  next_open={clock.next_open}  next_close={clock.next_close}")

    if clock.is_open:
        print(f"\n1. Market is OPEN — submitting a plain entry MARKET order (production path): BUY {args.qty} {args.symbol}, TIF=DAY ...")
        entry_request = MarketOrderRequest(symbol=args.symbol, qty=args.qty, side=OrderSide.BUY, time_in_force=TimeInForce.DAY)
        poll_timeout = 120
    else:
        print("\nMarket is CLOSED — a real TIF=DAY market order would be accepted but sit PENDING until next session's "
              "open (the expected, healthy outcome in production — see src/execution.py's 'second flagged design gap'). "
              "Using a marketable extended-hours LIMIT order instead, DRY-RUN-ONLY, so this script can validate the full "
              "fill+stop flow in this session rather than waiting for tomorrow's open.")
        data_client = StockHistoricalDataClient(api_key=cfg.api_key, secret_key=cfg.secret_key)
        quote = data_client.get_stock_latest_quote(StockLatestQuoteRequest(symbol_or_symbols=[args.symbol]))[args.symbol]
        limit_price = round(quote.ask_price + max(0.50, quote.ask_price * 0.002), 2)
        print(f"   latest quote: bid={quote.bid_price} ask={quote.ask_price} -> marketable limit_price={limit_price}")
        entry_request = LimitOrderRequest(
            symbol=args.symbol, qty=args.qty, side=OrderSide.BUY, time_in_force=TimeInForce.DAY,
            limit_price=limit_price, extended_hours=True,
        )
        poll_timeout = 60

    entry_order = client.submit_order(entry_request)
    print(f"   order id {entry_order.id}, initial status {entry_order.status}")

    print("2. Polling for fill confirmation ...")
    entry_order = poll_order_until_terminal(client, entry_order.id, timeout_seconds=poll_timeout, poll_interval_seconds=3, sleep_fn=time.sleep)
    fill = confirm_entry_fill(entry_order)
    print(f"   final status {fill['status']}, filled_qty={fill['filled_qty']}, filled_avg_price={fill['filled_avg_price']}")

    if fill["pending"]:
        print("\nPENDING: order is still open with zero fill — this is the expected outcome for a real post-close "
              "market order submitted while the market is closed. Nothing more to validate in this session; rerun "
              "during market hours (or accept the extended-hours limit-order path above) to see a real fill.")
        return
    if not fill["filled"]:
        print(f"\nFAIL: entry order ended in a genuinely terminal no-fill state ({fill['status']}) — nothing to protect, dry run stops here.")
        return

    stop_price = round(fill["filled_avg_price"] - args.stop_distance, 2)
    print(f"\n3. Submitting resting GTC stop: SELL {fill['filled_qty']} {args.symbol} @ stop {stop_price} ...")
    stop_order = submit_stop_order_with_retry(client, args.symbol, fill["filled_qty"], stop_price, sleep_fn=time.sleep)

    if stop_order is None:
        print("\nFAIL: stop order submission exhausted all retries — this is exactly the unprotected-window state execution.py's "
              "submit_stop_order_with_retry() alerts on. Check Telegram/logs for the URGENT alert this should have fired.")
        return

    print(f"   stop order id {stop_order.id}, status {stop_order.status}, resting stop_price {stop_order.stop_price}")

    print("\n4. Exercising the ratchet-only replace path (PATCH, not cancel-then-resubmit) with a deliberately WORSE candidate ...")
    replaced = replace_stop_order_if_favorable(client, stop_order.id, candidate_stop_price=stop_price - 1.0, current_stop_price=stop_price)
    print(f"   replaced={replaced} (expected False — a lower candidate must never move a long stop down)")

    better_stop_price = round(stop_price + 0.50, 2)
    replaced = replace_stop_order_if_favorable(client, stop_order.id, candidate_stop_price=better_stop_price, current_stop_price=stop_price)
    print(f"   replaced={replaced} (expected True — {better_stop_price} is more favorable than {stop_price})")

    print(f"\n=== PASS: real entry order filled ({fill['filled_qty']} {args.symbol} @ {fill['filled_avg_price']}) "
          f"and a real GTC stop order is resting and PATCH-replaceable. ===")

    if args.no_cleanup:
        print("\n--no-cleanup passed: leaving the test position and stop order in place for manual inspection.")
        return

    print("\n5. Cleaning up: cancelling the test stop and selling the test position ...")
    client.cancel_order_by_id(stop_order.id)
    close_request = MarketOrderRequest(symbol=args.symbol, qty=fill["filled_qty"], side=OrderSide.SELL, time_in_force=TimeInForce.DAY)
    close_order = client.submit_order(close_request)
    close_order = poll_order_until_terminal(client, close_order.id, timeout_seconds=120, poll_interval_seconds=3, sleep_fn=time.sleep)
    close_fill = confirm_entry_fill(close_order)
    print(f"   close order status {close_fill['status']}, filled_qty={close_fill['filled_qty']}")

    account_after = client.get_account()
    print(f"\naccount equity after cleanup: ${float(account_after.equity):,.2f}")


if __name__ == "__main__":
    main()
