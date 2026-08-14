"""
Track B fill-protection listener (spec v33 §10.5 design session — see
CLAUDE.md "Current status" for the full locked architecture this module
implements; nothing here should diverge from it without a fresh
chat-interface design-call confirmation, same "flag it, don't guess"
convention as execution.py's own two flagged open gaps).

WHAT THIS CLOSES: execution.py's run_daily_execution_job() runs once
daily, post-close. protect_unprotected_fills() (its first phase) only
catches an unprotected fill on the NEXT run — up to ~1 trading day later
(execution.py's own "SECOND FLAGGED, UNRESOLVED DESIGN GAP"). This module
closes that gap with a persistent, event-driven listener on Alpaca's
trade_updates WebSocket stream — a filled Track B entry gets its resting
GTC stop submitted within seconds of the fill, not up to a day later.

ARCHITECTURE (locked, see CLAUDE.md "Current status"):
  - Runs as its own standalone systemd service, separate from the daily
    job's own scheduled invocation — this module has no daily cadence of
    its own, it just runs continuously (run_listener() blocks forever).
    NOTE, verified not assumed: no systemd unit file is checked into this
    repo for EITHER the daily job or this listener — deployment
    configuration lives on the DigitalOcean droplet itself, out of this
    repo's scope (same as every other deployment-adjacent milestone to
    date). There is therefore no existing in-repo naming convention to
    follow; a real unit file/name is a droplet-deployment decision, not
    a code decision, and is left for that step.
  - MonitoredTradingStream (below) wraps alpaca.trading.stream.
    TradingStream with exponential backoff + Telegram alerting around
    the connect/auth/subscribe step — alpaca-py's own built-in reconnect
    loop has NO backoff at all (a flat 0.01s sleep between attempts,
    confirmed from the installed alpaca-py 0.43.5 source,
    venv/Lib/site-packages/alpaca/trading/stream.py, TradingStream.
    _run_forever()) and would otherwise spin-retry forever on both
    network failures and bad credentials.
  - No local position database (same convention as execution.py): the
    stop price is handed off via client_order_id, encoded by execution.
    py's encode_client_order_id() at entry-submission time and decoded
    here by decode_client_order_id() on fill.
  - Idempotency: has_resting_protective_stop()/submit_or_resize_stop_
    order_with_retry() (both execution.py) are the SAME functions
    protect_unprotected_fills() uses — this module never reimplements
    that check, so the listener and the daily fallback can never
    silently disagree about whether a symbol is already protected (same
    fix pattern as the v32 MAX_SINGLE_POSITION_NOTIONAL_PCT drift bug,
    CLAUDE.md "Current status" — applied proactively here).
  - protect_unprotected_fills() is UNCHANGED in role: this listener does
    not replace it, only shortens the exposure window in the normal
    case. Timing analysis (locked design): the listener and the daily
    fallback never actually race in normal operation, since fills happen
    at next-session open and the fallback runs hours later post-close
    the FOLLOWING day — the only real exposure window this listener
    closes is the listener being DOWN at the moment of a fill, which the
    daily fallback still catches on its next run regardless (see
    execution.py's module docstring for a SEPARATE, narrower race this
    milestone newly flagged: this listener vs. execution.py's OWN
    synchronous stop-submission for a same-session fill).
  - Halt-state independence (locked design, deliberate): this module
    never checks halt_state.py. It only reacts to fills that have
    already happened and already passed risk_filter.evaluate() before
    the entry order was ever submitted — gating stop PROTECTION on halt
    state would contradict the existing fail-safe principle that open
    positions stay protected independent of bot uptime/halt status
    (execution.py's module docstring, "Fail-safe behavior").

WHAT THIS MODULE DOES NOT DO: submit entry orders, evaluate signals, or
run any guardrail check — it is purely reactive to fills that already
happened. It also persists nothing locally; every fact it needs (stop
price, whether a symbol is already protected) is either encoded in the
fill event's own client_order_id or queried fresh from Alpaca.

VERIFIED THIS MILESTONE, not assumed:
  - client_order_id max length for this account's Trading API: 128
    characters (see execution.py's module docstring for the full
    empirical confirmation — Alpaca's own docs disagree, 48 vs 128).
  - TradeUpdate/Order field names (installed alpaca-py 0.43.5, confirmed
    via direct inspection of alpaca.trading.models, not memory of the
    API): TradeUpdate has .event (a TradeEvent enum or raw str,
    Union[TradeEvent, str]), .order (a NESTED Order object — NOT flat
    fields on TradeUpdate itself), .timestamp, .position_qty, .price,
    .qty (this last pair describe the CURRENT execution's size/price,
    not the order's cumulative fill — this module uses order.filled_qty,
    the CUMULATIVE figure, per the locked design's "resize the stop to
    cumulative filled_qty"). The nested Order has .symbol, .side (an
    OrderSide enum), .filled_qty, .filled_avg_price, .client_order_id,
    .status. TradeEvent's fill/partial-fill members serialize to the
    literal strings "fill" and "partial_fill" (confirmed via
    alpaca.trading.enums.TradeEvent) — matching the locked design's own
    {fill, partial_fill} naming exactly, not a coincidence worth
    re-deriving.
  - alpaca.trading.stream.TradingStream is present in the installed
    alpaca-py version (0.43.5). requirements.txt currently pins only a
    floor ("alpaca-py>=0.30.0", no upper bound) — presence is confirmed
    at the exact installed version, not assumed from the floor alone;
    whether to add an upper/pinned bound given this module's dependence
    on TradingStream's internal _start_ws() override point is a
    dependency-management decision flagged for the chat interface, not
    made unilaterally here.
"""
import asyncio
import logging
import time
from datetime import datetime, timezone

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TradeEvent
from alpaca.trading.stream import TradingStream

from . import telegram_bot
from .config import get_alpaca_config
from .execution import (
    TRACK_B_UNIVERSE,
    decode_client_order_id,
    submit_or_resize_stop_order_with_retry,
)

log = logging.getLogger(__name__)

_ALERT_THRESHOLD = 5
_MAX_BACKOFF_SECONDS = 300
_TRACKED_EVENT_VALUES = {TradeEvent.FILL.value, TradeEvent.PARTIAL_FILL.value}


class MonitoredTradingStream(TradingStream):
    """
    Subclasses alpaca-py's TradingStream purely to add exponential
    backoff + Telegram alerting around the connect/auth/subscribe step
    (_start_ws()) — no other TradingStream behavior is overridden. See
    module docstring for why this is necessary (alpaca-py's own
    reconnect loop has no backoff at all and would otherwise spin-retry
    forever on both network failures and bad credentials).
    """

    def __init__(
        self, *args,
        alert_threshold: int = _ALERT_THRESHOLD,
        max_backoff_seconds: int = _MAX_BACKOFF_SECONDS,
        async_sleep_fn=None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self._consecutive_failures = 0
        self._alert_threshold = alert_threshold
        self._max_backoff_seconds = max_backoff_seconds
        self._async_sleep_fn = async_sleep_fn or asyncio.sleep
        self._alerted = False

    async def _start_ws(self):
        """
        Wraps TradingStream._start_ws() (connect + authenticate +
        subscribe to trade_updates). On failure: increments a
        consecutive-failure counter, fires an URGENT Telegram alert the
        FIRST time the counter reaches alert_threshold (not on every
        failure past it — a real prolonged outage would otherwise spam
        one alert per reconnect attempt), sleeps 2**failures seconds
        (capped at max_backoff_seconds) BEFORE re-raising, then
        re-raises so alpaca-py's own _run_forever() loop retries (its
        own 0.01s sleep in the finally-block still runs after ours, but
        is negligible next to the real backoff already applied here). On
        a SUCCESSFUL connect after having alerted, fires one
        informational recovery message and resets the counter.
        """
        try:
            await super()._start_ws()
        except Exception:
            self._consecutive_failures += 1
            if self._consecutive_failures == self._alert_threshold:
                self._alerted = True
                telegram_bot.send_message(
                    f"URGENT — fill_listener: {self._consecutive_failures} consecutive WebSocket connection "
                    f"failures. Fill protection is degraded — protect_unprotected_fills() in the next daily "
                    f"job run remains the fallback, but a fill in the meantime could sit unprotected longer "
                    f"than normal. Investigate connectivity/credentials."
                )
            backoff = min(2 ** self._consecutive_failures, self._max_backoff_seconds)
            await self._async_sleep_fn(backoff)
            raise
        else:
            if self._alerted:
                telegram_bot.send_message(
                    f"fill_listener: WebSocket connection recovered after {self._consecutive_failures} "
                    f"consecutive failures."
                )
            self._consecutive_failures = 0
            self._alerted = False


def _event_value(event) -> str:
    """TradeEvent may arrive as the parsed enum or a raw str depending on SDK parsing — normalize to str."""
    return event.value if isinstance(event, TradeEvent) else str(event)


def _side_value(side) -> str:
    return side.value if isinstance(side, OrderSide) else str(side)


def _seconds_since(timestamp) -> float | None:
    """None-safe elapsed-time helper for the routine-success notification (FIX-UP, item 3) — returns None (not a
    fabricated 0.0 or an exception) when `timestamp` itself is None, e.g. a test double that didn't set one."""
    if timestamp is None:
        return None
    ts = timestamp if timestamp.tzinfo is not None else timestamp.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - ts).total_seconds()


def handle_trade_update(trading_client, trade_update, universe=None, sleep_fn=time.sleep) -> dict | None:
    """
    The listener's core handler (locked design's "Handler logic") — a
    plain, synchronous, fully unit-testable function (no asyncio, no
    network I/O beyond what trading_client/telegram_bot do internally),
    wrapped by the async dispatcher registered with TradingStream.
    subscribe_trade_updates() in run_listener() below. Returns a small
    result dict describing what was done, or None if the event was
    filtered out and no action was taken.

    Filtering, in order (locked design's exact rules):
      1. event not in {fill, partial_fill} -> ignored. Other trade_
         updates events (new/canceled/rejected/replaced/...) carry no
         fill information relevant to stop protection.
      2. order.side == sell -> LOGGED ONLY, no action. A sell fill is an
         EXIT (the position closing — often because the resting stop
         itself just triggered), never something that needs a NEW stop.
      3. order.symbol not in `universe` (default TRACK_B_UNIVERSE) ->
         ignored. Not a Track B order — could be Track A/crypto activity
         on the same account.
      4. order.client_order_id doesn't decode (decode_client_order_id()
         returns None) -> ignored, NOT alerted. A real Track B entry
         ALWAYS carries a decodable client_order_id (execution.py's
         submit_entry_and_stop() encodes one unconditionally on every
         entry submission) — a non-matching id means "not an order we
         generated" (e.g. a manual test order), not "we lost data".
      5. filled_qty (order.filled_qty, the order's CUMULATIVE fill, per
         the locked design) <= 0 -> ignored (defensive; a fill/
         partial_fill event should never carry a zero cumulative fill,
         but this function must never call submit_or_resize_stop_order_
         with_retry() with a non-positive qty).

    FIX-UP, item 3 (routine-success visibility — the whole point of this
    milestone, not left to be inferred from silence): fires a single,
    non-urgent Telegram message whenever this call ACTUALLY submits or
    tops up a protective stop — i.e. submit_or_resize_stop_order_with_
    retry()'s qty_submitted is > 0, NOT merely whenever a resting stop
    exists afterward (which is also true on a genuine no-op — a
    redelivered/duplicate event for a fill already fully protected must
    NOT re-alert). Message includes symbol, the qty just protected THIS
    call (the top-up increment, if this was a follow-up to an earlier
    partial fill — not necessarily the fill's full cumulative qty), the
    stop price, and elapsed time since trade_update.timestamp (the
    event's own timestamp field, confirmed on the installed alpaca-py
    TradeUpdate model — module docstring) to "now" — None/unavailable if
    the event carried no timestamp, rather than a fabricated number.
    """
    if universe is None:
        universe = TRACK_B_UNIVERSE

    event = _event_value(trade_update.event)
    if event not in _TRACKED_EVENT_VALUES:
        return None

    order = trade_update.order
    side = _side_value(order.side)

    if side == OrderSide.SELL.value:
        return {"action": "logged_exit", "symbol": order.symbol, "event": event}

    if order.symbol not in universe:
        return None

    decoded = decode_client_order_id(order.client_order_id)
    if decoded is None:
        return None

    filled_qty = float(order.filled_qty or 0)
    if filled_qty <= 0:
        return None

    stop_order, qty_submitted = submit_or_resize_stop_order_with_retry(
        trading_client, order.symbol, filled_qty, decoded["stop_price"], sleep_fn=sleep_fn,
    )

    if stop_order is not None and qty_submitted > 0:
        elapsed = _seconds_since(getattr(trade_update, "timestamp", None))
        elapsed_str = f"{elapsed:.1f}s after fill event" if elapsed is not None else "elapsed time unknown (no event timestamp)"
        telegram_bot.send_message(
            f"fill_listener: protected {order.symbol} — qty {qty_submitted} @ stop {decoded['stop_price']}, {elapsed_str}."
        )

    return {
        "action": "protected" if stop_order is not None else "protection_failed",
        "symbol": order.symbol,
        "event": event,
        "filled_qty": filled_qty,
        "stop_price": decoded["stop_price"],
        "qty_submitted": qty_submitted,
    }


def _build_trading_client() -> TradingClient:
    cfg = get_alpaca_config()
    return TradingClient(api_key=cfg.api_key, secret_key=cfg.secret_key, paper=cfg.paper)


def _build_stream() -> MonitoredTradingStream:
    cfg = get_alpaca_config()
    return MonitoredTradingStream(api_key=cfg.api_key, secret_key=cfg.secret_key, paper=cfg.paper)


def run_listener(trading_client: TradingClient = None, universe=None, sleep_fn=time.sleep) -> None:
    """
    Process entry point — the systemd ExecStart target for the listener's
    standalone service (locked design's "own standalone systemd service"
    architecture point; see module docstring for why no unit file is
    checked into this repo). Builds a real TradingClient (for order
    actions) and a MonitoredTradingStream (for the trade_updates
    WebSocket), registers the async handler wrapper, and blocks forever
    via TradingStream.run().
    """
    if trading_client is None:
        trading_client = _build_trading_client()
    if universe is None:
        universe = TRACK_B_UNIVERSE

    stream = _build_stream()

    async def _handler(trade_update):
        try:
            handle_trade_update(trading_client, trade_update, universe=universe, sleep_fn=sleep_fn)
        except Exception as exc:  # noqa: BLE001 — one bad event must never kill the listener process
            log.exception("fill_listener: unhandled error processing a trade update")
            telegram_bot.send_message(
                f"fill_listener: unhandled error processing a trade update ({exc}) — listener is still running."
            )

    stream.subscribe_trade_updates(_handler)
    stream.run()


if __name__ == "__main__":
    run_listener()
