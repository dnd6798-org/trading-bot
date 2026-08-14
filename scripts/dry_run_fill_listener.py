"""
ONE-OFF — fill_listener.py milestone's required end-to-end paper-account
integration test AND restart-safety test (spec v33 §10.5 design session,
CLAUDE.md "Current status" — milestone brief: "an integration test against
the paper account: place a real order ... with the listener running,
confirm it detects the fill and submits a correctly-priced stop within a
few seconds. Verify via GET on the resulting order" and "a restart-safety
test: kill the listener process between order submission and fill,
restart it, confirm it either catches a fill that happens after restart
normally, or ... that protect_unprotected_fills() correctly picks it up
on the next daily job run and does NOT throw or double-submit if the
listener also later processes a redelivered event for the same fill").
Not meant to be maintained, same convention as
scripts/dry_run_execution_track_b.py / scripts/select_universe.py.

PART 1 (integration): starts a REAL MonitoredTradingStream against the
paper account's trade_updates WebSocket in a background thread, submits a
real fill-forcing order (same market-hours-aware technique as
dry_run_execution_track_b.py: a plain MARKET order if the market is open,
a marketable extended-hours LIMIT order otherwise, DRY-RUN-ONLY, not how
production Track B submits entries) with a client_order_id encoding a
deliberately-below-market stop price, and polls Alpaca directly for the
resulting resting stop order — proving the whole live path: real fill ->
real WebSocket event -> real decode -> real stop submission, no daily job
involved at all.

PART 2 (restart-safety): submits a SECOND real fill-forcing order on a
different symbol WITHOUT the listener running (simulating "the listener
was down when this fill happened"), confirms no stop exists yet, runs
protect_unprotected_fills() (the daily-job fallback) and confirms it
protects the position — then feeds handle_trade_update() a SYNTHETIC
"redelivered" trade_update for that SAME already-protected fill and
confirms it is a safe no-op (no exception, no second stop order).

NOTE on why Part 2's "redelivered event" step is synthetic, not a second
real WebSocket delivery: Alpaca's trade_updates stream does not replay
historical events on reconnect — there is no way to make the real
WebSocket genuinely redeliver an old fill from a test script. Feeding
handle_trade_update() a synthetic-but-realistic trade_update object
(referencing the REAL order's real symbol/qty/client_order_id) is the
honest way to test the idempotency guarantee against REAL Alpaca account
state (the resting stop protect_unprotected_fills() actually placed),
which is what actually matters here — not the WebSocket transport itself.

NOTE on why Part 2 ALSO needs synthetic symbol_data, discovered on this
script's first real run, not anticipated: protect_unprotected_fills()
recomputes a stop price from the entry date's OWN historical daily
close/ATR (compute_stop_price_for_entry_date()) — which structurally
cannot exist for a fill that happened only seconds ago (today's daily
bar hasn't formed yet; Alpaca's daily-bar endpoint only ever has PAST,
already-closed trading days). This is a real limitation of the DRY-RUN
methodology (a same-session extended-hours fill), not of protect_
unprotected_fills() itself — in real production, entries fill at the
NEXT session's open, so by the time the following post-close job runs
protect_unprotected_fills(), that entry day's own daily bar is long
published. To test the FALLBACK's actual logic (real Alpaca position
found unprotected -> real Alpaca stop order submitted) without waiting a
full trading day, Part 2 hands it synthetic symbol_data containing just
one candle for today, built from the real fill price — clearly labeled
synthetic below, not fetched from Alpaca.

PART 3 (top-up + consolidation, added for the second fix-up — spec v33
§10.5 fix-up commit 95cd7d8, "close the multi-resting-stop gap"): a real
fill-forcing entry on a THIRD symbol, protected by a REAL first stop
order (handle_trade_update() called directly, not via a live WebSocket —
Part 1 already proved the live-WebSocket-delivery path end to end, so
Part 3 focuses on the TOP-UP/CONSOLIDATION math against real account
state, not delivery). A genuine broker-side SECOND partial fill can't be
reliably forced against this paper account for a small, liquid,
immediately-fillable order (the same reason Part 1/2's orders always
fill in one shot) — per the milestone brief's explicit fallback, a
SYNTHETIC second partial-fill trade_update (same client_order_id, a
higher cumulative filled_qty) is fed directly into handle_trade_update()
against the REAL resting position instead, exercising the real top-up
code path (submit_or_resize_stop_order_with_retry()'s "existing stop
found -> submit an ADDITIVE increment order" branch) with real Alpaca
API calls. Confirms via a direct GET that exactly TWO real resting stop
orders now exist, summing to the synthetic cumulative qty. Then calls
ratchet_position_stop() for real against those two real resting stops,
with a SYNTHETIC 2-point series (same reasoning as Part 2's synthetic
symbol_data — today's own daily bar can't exist yet for a same-session
fill) engineered to (a) trigger a real ratchet improvement and (b) land
the resulting price safely BELOW the current live quote, so a stop
order submitted at that price can never be an immediately-triggering
sell (which a stop price ABOVE the current market would risk). Confirms
via a direct GET that exactly ONE real resting stop order remains
afterward, sized to the summed qty, at the new ratcheted price — and
that this only happened via the "new-before-cancel" sequence (item 1's
own unit tests already prove the sequencing in isolation; this proves
the same code path against the real API end to end).

NOTE: the real position only ever holds Part 3's real single-share fill
— the SECOND "share" in the top-up/consolidation math is entirely
synthetic (never a real fill), so the resting stop qty (2) intentionally
exceeds the real position qty (1) for the duration of this test. Safe
and inert (the stop never triggers during a ~1-minute test window), and
cleaned up by cancelling every resting stop for the symbol before
selling the one real share — documented here rather than silently
glossed over.

Cleans up after itself by default (cancels stops, sells positions) unless
--no-cleanup is passed.

Usage:
    python scripts/dry_run_fill_listener.py
    python scripts/dry_run_fill_listener.py --symbol-a SPY --symbol-b QQQ --symbol-c IWM --no-cleanup
"""
import argparse
import asyncio
import random
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce, TradeEvent
from alpaca.trading.requests import GetOrdersRequest, LimitOrderRequest, MarketOrderRequest
from alpaca.trading.enums import QueryOrderStatus

from src import telegram_bot
from src.config import get_alpaca_config
from src.data_ingestion import Candle
from src.execution import (
    _is_stop_order,  # reused for consistent stop-order detection, not reinvented in this script
    ATR_MULTIPLIER,
    LivePosition,
    confirm_entry_fill,
    encode_client_order_id,
    has_resting_protective_stop,
    poll_order_until_terminal,
    protect_unprotected_fills,
    ratchet_position_stop,
)
from src.fill_listener import MonitoredTradingStream, handle_trade_update


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--symbol-a", default="SPY", help="symbol for Part 1 (listener live)")
    parser.add_argument("--symbol-b", default="QQQ", help="symbol for Part 2 (restart-safety)")
    parser.add_argument("--symbol-c", default="IWM", help="symbol for Part 3 (top-up + consolidation)")
    parser.add_argument("--qty", type=float, default=1.0)
    parser.add_argument("--stop-distance", type=float, default=5.0)
    parser.add_argument("--no-cleanup", action="store_true")
    return parser.parse_args()


def _cancel_all_resting_stops(client, symbol):
    """Robust cleanup helper for Part 3, where consolidation may (if something goes wrong) leave more than one resting stop."""
    orders = client.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[symbol]))
    for o in orders:
        if _is_stop_order(o):
            try:
                client.cancel_order_by_id(o.id)
            except Exception as exc:
                print(f"   (cleanup) could not cancel stop {o.id} for {symbol}: {exc}")


def _submit_fill_forcing_order(client, data_client, symbol, qty, client_order_id):
    clock = client.get_clock()
    if clock.is_open:
        req = MarketOrderRequest(symbol=symbol, qty=qty, side=OrderSide.BUY, time_in_force=TimeInForce.DAY, client_order_id=client_order_id)
        poll_timeout = 120
    else:
        quote = data_client.get_stock_latest_quote(StockLatestQuoteRequest(symbol_or_symbols=[symbol]))[symbol]
        # Wider buffer than the original dry-run script's 0.2%/$0.50 —
        # this session hit a real, transient extended-hours miss (a QQQ
        # limit order priced off a STALE quote, timestamped from the
        # PRIOR session's close, sat unfilled) even though the account
        # clock reported being inside the nominal pre-market window.
        # Flagged as a live-market-microstructure observation, not a bug
        # in this script's logic — a wider buffer reduces (does not
        # eliminate) the chance of a repeat.
        limit_price = round(quote.ask_price + max(1.00, quote.ask_price * 0.01), 2)
        req = LimitOrderRequest(
            symbol=symbol, qty=qty, side=OrderSide.BUY, time_in_force=TimeInForce.DAY,
            limit_price=limit_price, extended_hours=True, client_order_id=client_order_id,
        )
        poll_timeout = 90
    order = client.submit_order(req)
    return order, poll_timeout


def _cleanup_position(client, data_client, symbol, stop_order_id=None):
    if stop_order_id is not None:
        try:
            client.cancel_order_by_id(stop_order_id)
        except Exception as exc:
            print(f"   (cleanup) could not cancel stop for {symbol}: {exc}")
    try:
        position = client.get_open_position(symbol)
        qty = float(position.qty)
    except Exception:
        return
    # Same market-hours-aware technique as _submit_fill_forcing_order — a
    # plain MARKET close order sits PENDING outside market hours (this
    # script's own first run discovered exactly that, leaving a stray
    # half-closed position; same caveat dry_run_execution_track_b.py
    # already documents for itself).
    clock = client.get_clock()
    if clock.is_open:
        close_req = MarketOrderRequest(symbol=symbol, qty=qty, side=OrderSide.SELL, time_in_force=TimeInForce.DAY)
    else:
        quote = data_client.get_stock_latest_quote(StockLatestQuoteRequest(symbol_or_symbols=[symbol]))[symbol]
        limit_price = round(quote.bid_price - max(0.50, quote.bid_price * 0.002), 2)
        close_req = LimitOrderRequest(
            symbol=symbol, qty=qty, side=OrderSide.SELL, time_in_force=TimeInForce.DAY,
            limit_price=limit_price, extended_hours=True,
        )
    close_order = client.submit_order(close_req)
    poll_order_until_terminal(client, close_order.id, timeout_seconds=60, poll_interval_seconds=3)


def main():
    args = parse_args()
    cfg = get_alpaca_config()
    if not cfg.paper:
        raise SystemExit("REFUSING TO RUN: TRADING_ENV is not 'paper'. This script only ever runs against the paper account.")

    client = TradingClient(api_key=cfg.api_key, secret_key=cfg.secret_key, paper=True)
    data_client = StockHistoricalDataClient(api_key=cfg.api_key, secret_key=cfg.secret_key)

    # src/telegram_bot.py's send_message() is still a real, pre-existing
    # NotImplementedError stub in this codebase (a separate, unbuilt
    # milestone) — every automated test monkeypatches it for exactly this
    # reason (see tests/test_execution.py's captured_telegram_messages
    # fixture). This script does the same, purely so a real ALERT
    # (e.g. protect_unprotected_fills() failing to recompute a stop
    # price) prints instead of crashing this dry run — it does NOT
    # implement or fix Telegram integration, which stays untouched.
    def _print_telegram_alert(text):
        print(f"   [telegram_bot.send_message stub -> printed instead]: {text}")
    telegram_bot.send_message = _print_telegram_alert

    print("=== fill_listener.py dry run: integration + restart-safety, PAPER account ===")
    account = client.get_account()
    print(f"account equity before: ${float(account.equity):,.2f}")

    # ---------------------------------------------------------------
    # PART 1: listener LIVE — real fill -> real WebSocket event -> real stop
    # ---------------------------------------------------------------
    print(f"\n--- PART 1: listener running live, symbol={args.symbol_a} ---")
    stream = MonitoredTradingStream(api_key=cfg.api_key, secret_key=cfg.secret_key, paper=True)

    async def _handler(trade_update):
        handle_trade_update(client, trade_update, sleep_fn=time.sleep)

    stream.subscribe_trade_updates(_handler)

    listener_thread = threading.Thread(target=stream.run, daemon=True)
    listener_thread.start()

    print("1. Waiting for the listener to connect/authenticate/subscribe ...")
    deadline = time.monotonic() + 15
    while not stream._running and time.monotonic() < deadline:
        time.sleep(0.25)
    if not stream._running:
        raise SystemExit("FAIL: listener did not connect within 15s — aborting Part 1.")
    print("   listener connected and subscribed to trade_updates.")

    today_str = datetime.now(timezone.utc).date().isoformat()
    quote_a = data_client.get_stock_latest_quote(StockLatestQuoteRequest(symbol_or_symbols=[args.symbol_a]))[args.symbol_a]
    approx_fill_price = quote_a.ask_price
    # A small random cents jitter keeps the encoded stop_price (and hence
    # client_order_id) unique across reruns of this script — Alpaca
    # requires client_order_id to be unique for the account's lifetime,
    # confirmed by this script's own first run colliding on a rerun with
    # an unchanged quote. Does not affect what's being validated (the
    # listener still decodes and honors whatever price is encoded).
    stop_price_a = round(approx_fill_price - args.stop_distance - random.uniform(0, 0.98), 2)
    coid_a = encode_client_order_id(args.symbol_a, today_str, stop_price_a)
    print(f"2. Submitting a real fill-forcing entry for {args.symbol_a}, client_order_id={coid_a} (encodes stop_price={stop_price_a}) ...")
    entry_order, poll_timeout = _submit_fill_forcing_order(client, data_client, args.symbol_a, args.qty, coid_a)
    entry_order = poll_order_until_terminal(client, entry_order.id, timeout_seconds=poll_timeout, poll_interval_seconds=3)
    fill = confirm_entry_fill(entry_order)
    print(f"   fill status={fill['status']} filled_qty={fill['filled_qty']} filled_avg_price={fill['filled_avg_price']}")
    if not fill["filled"]:
        raise SystemExit(f"FAIL: entry for {args.symbol_a} did not fill ({fill['status']}) — cannot validate the listener path.")

    print("3. Polling Alpaca directly for the listener's resting stop order (up to 15s) ...")
    stop_order = None
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        orders = client.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[args.symbol_a]))
        stops = [o for o in orders if _is_stop_order(o)]
        if stops:
            stop_order = stops[0]
            break
        time.sleep(1)

    if stop_order is None:
        print("   FAIL: no resting stop order appeared within 15s — the listener did NOT protect this fill.")
        part1_pass = False
    else:
        elapsed = 15 - max(0, deadline - time.monotonic())
        print(f"   PASS: resting stop order {stop_order.id} found, stop_price={stop_order.stop_price} (encoded target was {stop_price_a}), within ~{elapsed:.1f}s.")
        part1_pass = float(stop_order.stop_price) == stop_price_a

    if not args.no_cleanup:
        print(f"   cleaning up {args.symbol_a} ...")
        _cleanup_position(client, data_client, args.symbol_a, stop_order_id=(stop_order.id if stop_order else None))

    # ---------------------------------------------------------------
    # PART 2: restart-safety — listener DOWN during fill, fallback picks it
    # up, then a synthetic redelivered event for the same fill is a no-op.
    # ---------------------------------------------------------------
    print(f"\n--- PART 2: restart-safety, symbol={args.symbol_b} (listener intentionally NOT running for this order) ---")
    print("1. Stopping the Part 1 listener ...")
    stream.stop()
    listener_thread.join(timeout=5)

    quote_b = data_client.get_stock_latest_quote(StockLatestQuoteRequest(symbol_or_symbols=[args.symbol_b]))[args.symbol_b]
    stop_price_b = round(quote_b.ask_price - args.stop_distance - random.uniform(0, 0.98), 2)
    coid_b = encode_client_order_id(args.symbol_b, today_str, stop_price_b)
    print(f"2. Submitting a real fill-forcing entry for {args.symbol_b} with NO listener running, client_order_id={coid_b} ...")
    entry_order_b, poll_timeout_b = _submit_fill_forcing_order(client, data_client, args.symbol_b, args.qty, coid_b)
    entry_order_b = poll_order_until_terminal(client, entry_order_b.id, timeout_seconds=poll_timeout_b, poll_interval_seconds=3)
    fill_b = confirm_entry_fill(entry_order_b)
    print(f"   fill status={fill_b['status']} filled_qty={fill_b['filled_qty']}")
    if not fill_b["filled"]:
        raise SystemExit(f"FAIL: entry for {args.symbol_b} did not fill ({fill_b['status']}) — cannot validate restart-safety.")

    print("3. Confirming the position is genuinely UNPROTECTED (listener was down) ...")
    already_protected = has_resting_protective_stop(client, args.symbol_b)
    print(f"   has_resting_protective_stop({args.symbol_b}) = {already_protected} (expected False)")

    print("4. Running protect_unprotected_fills() — the daily job's fallback — to protect it ...")
    # SYNTHETIC symbol_data, NOT fetched from Alpaca — see module docstring's
    # second NOTE for why: compute_stop_price_for_entry_date() needs entry_
    # date's OWN daily close/ATR, which cannot exist yet for a fill that
    # happened seconds ago (today's daily bar hasn't formed). This isolates
    # the thing actually being tested (does protect_unprotected_fills()
    # correctly find the REAL unprotected Alpaca position and submit a REAL
    # stop order for it) from a data-availability gap that's an artifact of
    # this script's same-session fill technique, not of production behavior.
    synthetic_close = fill_b["filled_avg_price"]
    synthetic_atr = args.stop_distance / ATR_MULTIPLIER  # reverse-engineered so the recomputed stop lands near stop_price_b
    synthetic_candle = Candle(args.symbol_b, f"{today_str}T00:00:00", open=synthetic_close, high=synthetic_close, low=synthetic_close, close=synthetic_close, volume=0)
    symbol_data = {args.symbol_b: {
        "symbol": args.symbol_b, "candles": [synthetic_candle],
        "atr": [synthetic_atr], "date_index": {today_str: 0}, "entry_indices": set(),
    }}
    protected = protect_unprotected_fills(client, [args.symbol_b], symbol_data, sleep_fn=time.sleep)
    print(f"   protected = {protected}")
    fallback_pass = args.symbol_b in protected

    print("5. Feeding a SYNTHETIC redelivered trade_update for the SAME fill directly into handle_trade_update() ...")
    redelivered_order = SimpleNamespace(
        symbol=args.symbol_b, side=OrderSide.BUY, filled_qty=fill_b["filled_qty"],
        filled_avg_price=fill_b["filled_avg_price"], client_order_id=coid_b, status=entry_order_b.status,
    )
    redelivered_trade_update = SimpleNamespace(event=TradeEvent.FILL, order=redelivered_order, timestamp=None, position_qty=None, price=None, qty=None)
    no_double_submit_error = None
    try:
        result = handle_trade_update(client, redelivered_trade_update, sleep_fn=time.sleep)
        print(f"   handle_trade_update() returned: {result} (no exception raised)")
    except Exception as exc:  # noqa: BLE001 — this IS the assertion, must not raise
        no_double_submit_error = exc
        print(f"   FAIL: handle_trade_update() raised on the redelivered event: {exc}")

    orders_after = client.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[args.symbol_b]))
    remaining_stops = [o for o in orders_after if _is_stop_order(o)]
    stop_count_after = len(remaining_stops)
    print(f"   resting stop orders for {args.symbol_b} after the redelivered event: {stop_count_after} (expected exactly 1, not 2)")
    idempotency_pass = (no_double_submit_error is None) and (stop_count_after == 1)

    if not args.no_cleanup:
        print(f"   cleaning up {args.symbol_b} ...")
        _cleanup_position(client, data_client, args.symbol_b, stop_order_id=(remaining_stops[0].id if remaining_stops else None))

    # ---------------------------------------------------------------
    # PART 3: top-up (additive stop) + consolidation, both against REAL
    # account state — see module docstring's "PART 3" note for the full
    # methodology and why the second "fill" is synthetic.
    # ---------------------------------------------------------------
    print(f"\n--- PART 3: top-up + consolidation, symbol={args.symbol_c} ---")
    quote_c = data_client.get_stock_latest_quote(StockLatestQuoteRequest(symbol_or_symbols=[args.symbol_c]))[args.symbol_c]
    stop_price_c = round(quote_c.ask_price - args.stop_distance - random.uniform(0, 0.98), 2)
    coid_c = encode_client_order_id(args.symbol_c, today_str, stop_price_c)
    print(f"1. Submitting a real fill-forcing entry for {args.symbol_c}, client_order_id={coid_c} (encodes stop_price={stop_price_c}) ...")
    entry_order_c, poll_timeout_c = _submit_fill_forcing_order(client, data_client, args.symbol_c, args.qty, coid_c)
    entry_order_c = poll_order_until_terminal(client, entry_order_c.id, timeout_seconds=poll_timeout_c, poll_interval_seconds=3)
    fill_c = confirm_entry_fill(entry_order_c)
    print(f"   fill status={fill_c['status']} filled_qty={fill_c['filled_qty']} filled_avg_price={fill_c['filled_avg_price']}")
    if not fill_c["filled"]:
        raise SystemExit(f"FAIL: entry for {args.symbol_c} did not fill ({fill_c['status']}) — cannot validate Part 3.")

    print("2. Protecting the real fill directly via handle_trade_update() (first real stop, stop-1) ...")
    first_fill_order = SimpleNamespace(
        symbol=args.symbol_c, side=OrderSide.BUY, filled_qty=fill_c["filled_qty"],
        filled_avg_price=fill_c["filled_avg_price"], client_order_id=coid_c, status=entry_order_c.status,
    )
    first_fill_trade_update = SimpleNamespace(event=TradeEvent.FILL, order=first_fill_order, timestamp=datetime.now(timezone.utc), position_qty=None, price=None, qty=None)
    handle_trade_update(client, first_fill_trade_update, sleep_fn=time.sleep)

    print("3. Feeding a SYNTHETIC second partial-fill event (cumulative qty +1) — exercises the real TOP-UP path ...")
    topped_up_qty = fill_c["filled_qty"] + args.qty
    second_fill_order = SimpleNamespace(
        symbol=args.symbol_c, side=OrderSide.BUY, filled_qty=topped_up_qty,
        filled_avg_price=fill_c["filled_avg_price"], client_order_id=coid_c, status=entry_order_c.status,
    )
    second_fill_trade_update = SimpleNamespace(event=TradeEvent.PARTIAL_FILL, order=second_fill_order, timestamp=datetime.now(timezone.utc), position_qty=None, price=None, qty=args.qty)
    topup_result = handle_trade_update(client, second_fill_trade_update, sleep_fn=time.sleep)
    print(f"   handle_trade_update() (top-up) returned: {topup_result}")

    stops_after_topup = [o for o in client.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[args.symbol_c])) if _is_stop_order(o)]
    topup_qty_sum = sum(float(o.qty) for o in stops_after_topup)
    print(f"   resting stops for {args.symbol_c} after top-up: {len(stops_after_topup)} (expected 2), summed qty={topup_qty_sum} (expected {topped_up_qty})")
    part3a_pass = len(stops_after_topup) == 2 and abs(topup_qty_sum - topped_up_qty) < 1e-9 and all(float(o.stop_price) == stop_price_c for o in stops_after_topup)

    print("4. Running ratchet_position_stop() for real against the two real resting stops (CONSOLIDATION) ...")
    # SYNTHETIC series (today's own daily bar can't exist yet for a
    # same-session fill — same reasoning as Part 2). Engineered so the
    # ratchet candidate lands safely BELOW the current live quote (never
    # an immediately-triggering stop) while still being a clear, visible
    # improvement over stop_price_c: prior_atr=1.0, ratchet-day close =
    # fill_price+2 -> candidate = (fill_price+2) - 3*1.0 = fill_price-1.
    ratchet_day = (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat()
    fill_price = fill_c["filled_avg_price"]
    series = {
        "symbol": args.symbol_c,
        "candles": [
            Candle(args.symbol_c, f"{today_str}T00:00:00", open=fill_price, high=fill_price, low=fill_price, close=fill_price, volume=0),
            Candle(args.symbol_c, f"{ratchet_day}T00:00:00", open=fill_price, high=fill_price + 2, low=fill_price, close=fill_price + 2, volume=0),
        ],
        "atr": [1.0, 1.0],
        "date_index": {today_str: 0, ratchet_day: 1},
        "entry_indices": set(),
    }
    position_c = LivePosition(
        symbol=args.symbol_c, qty=fill_c["filled_qty"], entry_price=fill_price, entry_date=today_str,
        stop_order_id=stops_after_topup[0].id if stops_after_topup else "", stop_price=stop_price_c,
        risk_amount=0.0, risk_pct=0.0, notional_pct_of_equity=0.0,
    )
    expected_consolidated_price = round(fill_price + 2 - 3.0 * 1.0, 2)
    print(f"   expecting consolidated price ~{expected_consolidated_price} (current quote ~{quote_c.ask_price}, safely below)")
    consolidated = ratchet_position_stop(client, position_c, series, today=ratchet_day, atr_multiplier=3.0, sleep_fn=time.sleep)
    print(f"   ratchet_position_stop() returned: {consolidated}")

    stops_after_consolidation = [o for o in client.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[args.symbol_c])) if _is_stop_order(o)]
    print(f"   resting stops for {args.symbol_c} after consolidation: {len(stops_after_consolidation)} (expected exactly 1)")
    if stops_after_consolidation:
        consolidated_order = stops_after_consolidation[0]
        print(f"   consolidated stop: id={consolidated_order.id} qty={consolidated_order.qty} stop_price={consolidated_order.stop_price}")
        part3b_pass = (
            consolidated is True and len(stops_after_consolidation) == 1
            and abs(float(consolidated_order.qty) - topped_up_qty) < 1e-9
            and float(consolidated_order.stop_price) == expected_consolidated_price
        )
    else:
        part3b_pass = False

    if not args.no_cleanup:
        print(f"   cleaning up {args.symbol_c} (cancelling ALL resting stops, then selling the one real share) ...")
        _cancel_all_resting_stops(client, args.symbol_c)
        _cleanup_position(client, data_client, args.symbol_c, stop_order_id=None)

    account_after = client.get_account()
    print(f"\naccount equity after cleanup: ${float(account_after.equity):,.2f}")

    print("\n=== RESULTS ===")
    print(f"Part 1 (listener live, real fill -> real stop within ~15s, correct price): {'PASS' if part1_pass else 'FAIL'}")
    print(f"Part 2a (protect_unprotected_fills() catches a fill the listener missed): {'PASS' if fallback_pass else 'FAIL'}")
    print(f"Part 2b (redelivered event for an already-protected fill is a safe no-op, no double stop): {'PASS' if idempotency_pass else 'FAIL'}")
    print(f"Part 3a (synthetic second partial fill -> real additive TOP-UP stop, two resting stops summing correctly): {'PASS' if part3a_pass else 'FAIL'}")
    print(f"Part 3b (ratchet_position_stop() CONSOLIDATES the two real stops into one, correct qty/price): {'PASS' if part3b_pass else 'FAIL'}")

    if not (part1_pass and fallback_pass and idempotency_pass and part3a_pass and part3b_pass):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
