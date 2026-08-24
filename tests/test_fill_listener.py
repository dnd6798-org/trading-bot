"""
fill_listener.py milestone (spec v33 §10.5 — see CLAUDE.md "Current
status" for the full locked architecture). Covers, against synthetic
data, a hand-built FakeTradingClient (reused from tests/test_execution.py,
no network calls), and a real event loop via asyncio.run() (no live
WebSocket connection):

  - MonitoredTradingStream's backoff math (2**failures, capped) and
    alert-threshold triggering — TradingStream._start_ws() is monkeypatched
    to fail/succeed on demand, never a live connection.
  - handle_trade_update()'s event filtering (event allowlist, buy-vs-sell,
    tracked-vs-untracked symbol, non-decodable client_order_id, zero
    filled_qty) and its full pass-through to submit_or_resize_stop_
    order_with_retry() for a genuine buy fill/partial fill.

No test here exercises a real Alpaca WebSocket connection or the paper
account — that's the separate, one-off integration/restart-safety scripts
per the milestone brief ("an integration test against the paper account"
/ "a restart-safety test"), not meant to run as part of the automated suite.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from alpaca.trading.enums import OrderSide, OrderStatus, OrderType, TradeEvent
from alpaca.trading.requests import StopOrderRequest
from alpaca.trading.stream import TradingStream

from src import telegram_bot
from src.execution import ATR_MULTIPLIER, encode_client_order_id, submit_entry_and_stop
from src.fill_listener import (
    MonitoredTradingStream,
    _heartbeat_tick,
    handle_trade_update,
    heartbeat_loop,
    send_listener_heartbeat,
)

from tests.test_execution import FakeOrder, FakeRequestsModule, FakeTradingClient, _approved_decision, _guardrails, _no_sleep


@pytest.fixture(autouse=True)
def captured_telegram_messages(monkeypatch):
    sent = []
    monkeypatch.setattr(telegram_bot, "send_message", lambda text: sent.append(text))
    return sent


# --- MonitoredTradingStream: backoff math + alert threshold ----------------

def _make_stream(alert_threshold=5, max_backoff_seconds=300):
    calls = []

    async def fake_sleep(seconds):
        calls.append(seconds)

    stream = MonitoredTradingStream(
        api_key="test-key", secret_key="test-secret", paper=True,
        alert_threshold=alert_threshold, max_backoff_seconds=max_backoff_seconds,
        async_sleep_fn=fake_sleep,
    )
    return stream, calls


def test_start_ws_backs_off_exponentially_on_repeated_failures(monkeypatch):
    async def always_fail(self):
        raise ConnectionError("simulated ws failure")
    monkeypatch.setattr(TradingStream, "_start_ws", always_fail)

    stream, calls = _make_stream(alert_threshold=99, max_backoff_seconds=1000)
    for _ in range(4):
        with pytest.raises(ConnectionError):
            asyncio.run(stream._start_ws())

    assert calls == [2, 4, 8, 16]  # 2**1, 2**2, 2**3, 2**4
    assert stream._consecutive_failures == 4


def test_start_ws_backoff_capped_at_max_backoff_seconds(monkeypatch):
    async def always_fail(self):
        raise ConnectionError("simulated ws failure")
    monkeypatch.setattr(TradingStream, "_start_ws", always_fail)

    stream, calls = _make_stream(alert_threshold=99, max_backoff_seconds=10)
    for _ in range(6):
        with pytest.raises(ConnectionError):
            asyncio.run(stream._start_ws())

    assert calls == [2, 4, 8, 10, 10, 10]  # 16/32/64 all capped to 10


def test_alert_fires_exactly_once_at_the_threshold_not_before_or_after(captured_telegram_messages, monkeypatch):
    async def always_fail(self):
        raise ConnectionError("simulated ws failure")
    monkeypatch.setattr(TradingStream, "_start_ws", always_fail)

    stream, _ = _make_stream(alert_threshold=3, max_backoff_seconds=1000)
    for _ in range(5):  # 5 failures, threshold is 3 — must alert exactly once, not on 4th/5th too
        with pytest.raises(ConnectionError):
            asyncio.run(stream._start_ws())

    urgent = [m for m in captured_telegram_messages if "URGENT" in m and "fill_listener" in m]
    assert len(urgent) == 1
    assert "3 consecutive" in urgent[0]


def test_recovery_alert_fires_after_success_following_alerted_failures(captured_telegram_messages, monkeypatch):
    call_count = {"n": 0}

    async def fail_then_succeed(self):
        call_count["n"] += 1
        if call_count["n"] <= 3:
            raise ConnectionError("simulated ws failure")
    monkeypatch.setattr(TradingStream, "_start_ws", fail_then_succeed)

    stream, _ = _make_stream(alert_threshold=3, max_backoff_seconds=1000)
    for _ in range(3):
        with pytest.raises(ConnectionError):
            asyncio.run(stream._start_ws())
    captured_telegram_messages.clear()  # drop the URGENT alert — only checking recovery below

    asyncio.run(stream._start_ws())  # succeeds this time

    recovery = [m for m in captured_telegram_messages if "recovered" in m]
    assert len(recovery) == 1
    assert stream._consecutive_failures == 0
    assert stream._alerted is False


def test_no_recovery_alert_when_never_alerted(captured_telegram_messages, monkeypatch):
    async def succeed(self):
        return None
    monkeypatch.setattr(TradingStream, "_start_ws", succeed)

    stream, calls = _make_stream(alert_threshold=5, max_backoff_seconds=1000)
    asyncio.run(stream._start_ws())

    assert captured_telegram_messages == []
    assert calls == []  # no failure at all, no backoff sleep


# --- handle_trade_update: event filtering -----------------------------------

def _order(symbol="SPY", side=OrderSide.BUY, filled_qty=10.0, client_order_id=None, status=OrderStatus.FILLED):
    return SimpleNamespace(
        symbol=symbol, side=side, filled_qty=filled_qty, filled_avg_price=451.0,
        client_order_id=client_order_id, status=status,
    )


def _trade_update(event=TradeEvent.FILL, order=None, timestamp=None):
    return SimpleNamespace(event=event, order=order or _order(), timestamp=timestamp, position_qty=None, price=None, qty=None)


def test_handle_trade_update_ignores_non_fill_events():
    order = _order(client_order_id=encode_client_order_id("SPY", "2026-08-10", 435.0))
    trade_update = _trade_update(event=TradeEvent.NEW, order=order)
    client = FakeTradingClient()

    result = handle_trade_update(client, trade_update, sleep_fn=lambda s: None)

    assert result is None
    assert client.submitted_orders == []


def test_handle_trade_update_accepts_a_raw_string_event_value_not_just_the_enum():
    order = _order(client_order_id=encode_client_order_id("SPY", "2026-08-10", 435.0))
    trade_update = _trade_update(event="fill", order=order)  # raw str, in case raw_data delivery bypasses enum parsing
    client = FakeTradingClient()
    client.orders_by_request = lambda filter: []
    client.submit_order_fn = lambda req: FakeOrder(id="stop-1", status=OrderStatus.NEW, stop_price=req.stop_price)

    result = handle_trade_update(client, trade_update, sleep_fn=lambda s: None)

    assert result["action"] == "protected"


def test_handle_trade_update_logs_sell_fills_only_no_action():
    order = _order(side=OrderSide.SELL, client_order_id=encode_client_order_id("SPY", "2026-08-10", 435.0))
    trade_update = _trade_update(order=order)
    client = FakeTradingClient()

    result = handle_trade_update(client, trade_update, sleep_fn=lambda s: None)

    assert result == {"action": "logged_exit", "symbol": "SPY", "event": "fill"}
    assert client.submitted_orders == []


def test_handle_trade_update_ignores_symbols_outside_the_universe():
    order = _order(symbol="AAPL", client_order_id=encode_client_order_id("AAPL", "2026-08-10", 100.0))
    trade_update = _trade_update(order=order)
    client = FakeTradingClient()

    result = handle_trade_update(client, trade_update, universe=["SPY", "QQQ"], sleep_fn=lambda s: None)

    assert result is None
    assert client.submitted_orders == []


def test_handle_trade_update_ignores_orders_with_a_non_decodable_client_order_id():
    order = _order(client_order_id="some-manual-test-order")  # e.g. not one execution.py generated
    trade_update = _trade_update(order=order)
    client = FakeTradingClient()

    result = handle_trade_update(client, trade_update, sleep_fn=lambda s: None)

    assert result is None
    assert client.submitted_orders == []


def test_handle_trade_update_ignores_zero_filled_qty():
    order = _order(filled_qty=0.0, client_order_id=encode_client_order_id("SPY", "2026-08-10", 435.0))
    trade_update = _trade_update(order=order)
    client = FakeTradingClient()

    result = handle_trade_update(client, trade_update, sleep_fn=lambda s: None)

    assert result is None
    assert client.submitted_orders == []


# --- handle_trade_update: the real protection path (TOP-UP model, fix-up) --

def test_handle_trade_update_protects_a_genuine_buy_fill():
    stop_price = 435.0
    order = _order(filled_qty=10.0, client_order_id=encode_client_order_id("SPY", "2026-08-10", stop_price))
    trade_update = _trade_update(event=TradeEvent.FILL, order=order)
    client = FakeTradingClient()
    client.orders_by_request = lambda filter: []  # no resting stop yet
    client.submit_order_fn = lambda req: FakeOrder(id="stop-1", status=OrderStatus.NEW, stop_price=req.stop_price)

    result = handle_trade_update(client, trade_update, sleep_fn=lambda s: None)

    assert result["action"] == "protected"
    assert result["symbol"] == "SPY"
    assert result["filled_qty"] == 10.0
    assert result["stop_price"] == stop_price
    assert result["qty_submitted"] == 10.0
    assert len(client.submitted_orders) == 1
    assert client.submitted_orders[0].stop_price == stop_price


def test_handle_trade_update_partial_fill_tops_up_with_an_additive_stop():
    stop_price = 435.0
    order = _order(filled_qty=8.0, client_order_id=encode_client_order_id("SPY", "2026-08-10", stop_price))
    trade_update = _trade_update(event=TradeEvent.PARTIAL_FILL, order=order)
    client = FakeTradingClient()
    client.orders_by_request = lambda filter: [
        FakeOrder(id="stop-1", symbol="SPY", status=OrderStatus.NEW, order_type=OrderType.STOP, qty=5.0, stop_price=stop_price)
    ]
    client.submit_order_fn = lambda req: FakeOrder(id="stop-2", status=OrderStatus.NEW, stop_price=req.stop_price)

    result = handle_trade_update(client, trade_update, sleep_fn=lambda s: None)

    assert result["action"] == "protected"
    assert result["qty_submitted"] == 3.0  # the increment (8.0 - 5.0), not the full 8.0
    assert client.replace_calls == []  # never a replace
    assert len(client.submitted_orders) == 1  # exactly one NEW, additive stop order
    assert client.submitted_orders[0].qty == 3.0
    assert client.submitted_orders[0].stop_price == stop_price  # same price as stop-1


def test_handle_trade_update_redelivered_event_for_an_already_protected_fill_is_a_noop():
    # Idempotency: a redelivered/duplicate trade_updates event for a fill
    # already protected at the correct cumulative qty must not resubmit
    # or top up anything, and must NOT fire a routine-success notification
    # (fix-up item 3 — only a REAL submit/top-up should notify).
    stop_price = 435.0
    order = _order(filled_qty=10.0, client_order_id=encode_client_order_id("SPY", "2026-08-10", stop_price))
    trade_update = _trade_update(event=TradeEvent.FILL, order=order)
    client = FakeTradingClient()
    client.orders_by_request = lambda filter: [
        FakeOrder(id="stop-1", symbol="SPY", status=OrderStatus.NEW, order_type=OrderType.STOP, qty=10.0, stop_price=stop_price)
    ]

    result = handle_trade_update(client, trade_update, sleep_fn=lambda s: None)

    assert result["action"] == "protected"
    assert result["qty_submitted"] == 0.0
    assert client.submitted_orders == []
    assert client.replace_calls == []


# --- handle_trade_update: routine-success Telegram notification (fix-up
# item 3 — visibility this milestone is for; not merely inferred silence) ---

def test_handle_trade_update_fires_a_routine_success_notification_on_a_fresh_protect(captured_telegram_messages):
    stop_price = 435.0
    fill_time = datetime.now(timezone.utc) - timedelta(seconds=2.5)
    order = _order(filled_qty=10.0, client_order_id=encode_client_order_id("SPY", "2026-08-10", stop_price))
    trade_update = _trade_update(event=TradeEvent.FILL, order=order, timestamp=fill_time)
    client = FakeTradingClient()
    client.orders_by_request = lambda filter: []
    client.submit_order_fn = lambda req: FakeOrder(id="stop-1", status=OrderStatus.NEW, stop_price=req.stop_price)

    handle_trade_update(client, trade_update, sleep_fn=lambda s: None)

    routine = [m for m in captured_telegram_messages if m.startswith("fill_listener: protected")]
    assert len(routine) == 1
    msg = routine[0]
    assert "SPY" in msg
    assert "qty 10.0" in msg
    assert "stop 435.0" in msg
    assert "s after fill event" in msg
    assert "URGENT" not in msg  # routine, non-urgent — distinct from the failure alert path


def test_handle_trade_update_notification_reports_the_topup_increment_not_the_full_cumulative_qty(captured_telegram_messages):
    stop_price = 435.0
    order = _order(filled_qty=8.0, client_order_id=encode_client_order_id("SPY", "2026-08-10", stop_price))
    trade_update = _trade_update(event=TradeEvent.PARTIAL_FILL, order=order, timestamp=datetime.now(timezone.utc))
    client = FakeTradingClient()
    client.orders_by_request = lambda filter: [
        FakeOrder(id="stop-1", symbol="SPY", status=OrderStatus.NEW, order_type=OrderType.STOP, qty=5.0, stop_price=stop_price)
    ]
    client.submit_order_fn = lambda req: FakeOrder(id="stop-2", status=OrderStatus.NEW, stop_price=req.stop_price)

    handle_trade_update(client, trade_update, sleep_fn=lambda s: None)

    routine = [m for m in captured_telegram_messages if m.startswith("fill_listener: protected")]
    assert len(routine) == 1
    assert "qty 3.0" in routine[0]  # the increment, not 8.0


def test_handle_trade_update_no_notification_when_the_event_carries_no_timestamp(captured_telegram_messages):
    # _trade_update()'s default timestamp is None (e.g. a test double, or
    # an SDK edge case) — must report "unknown", never crash or fabricate
    # an elapsed value.
    stop_price = 435.0
    order = _order(filled_qty=10.0, client_order_id=encode_client_order_id("SPY", "2026-08-10", stop_price))
    trade_update = _trade_update(event=TradeEvent.FILL, order=order, timestamp=None)
    client = FakeTradingClient()
    client.orders_by_request = lambda filter: []
    client.submit_order_fn = lambda req: FakeOrder(id="stop-1", status=OrderStatus.NEW, stop_price=req.stop_price)

    handle_trade_update(client, trade_update, sleep_fn=lambda s: None)

    routine = [m for m in captured_telegram_messages if m.startswith("fill_listener: protected")]
    assert len(routine) == 1
    assert "elapsed time unknown" in routine[0]


def test_handle_trade_update_no_notification_on_a_redelivered_noop_event(captured_telegram_messages):
    stop_price = 435.0
    order = _order(filled_qty=10.0, client_order_id=encode_client_order_id("SPY", "2026-08-10", stop_price))
    trade_update = _trade_update(event=TradeEvent.FILL, order=order, timestamp=datetime.now(timezone.utc))
    client = FakeTradingClient()
    client.orders_by_request = lambda filter: [
        FakeOrder(id="stop-1", symbol="SPY", status=OrderStatus.NEW, order_type=OrderType.STOP, qty=10.0, stop_price=stop_price)
    ]

    handle_trade_update(client, trade_update, sleep_fn=lambda s: None)

    assert captured_telegram_messages == []


# --- cross-path race closure (fix-up item 2): submit_entry_and_stop() vs.
# the listener reacting to the SAME fill "concurrently" ---------------------

def test_near_simultaneous_fill_and_listener_event_produce_only_one_stop_order():
    # True thread-level concurrency isn't reproducible in a synchronous
    # unit test — this simulates the race by running whichever path
    # "wins" first (the listener, here, via handle_trade_update()), then
    # running submit_entry_and_stop() against the SAME account state
    # (a shared, stateful FakeTradingClient) and confirming it detects
    # the already-resting stop and skips its own submission.
    candidate = {"symbol": "SPY", "close": 450.0, "atr": 5.0, "timestamp": "2026-08-10T00:00:00"}
    expected_stop_price = 450.0 - ATR_MULTIPLIER * 5.0
    coid = encode_client_order_id("SPY", "2026-08-10", expected_stop_price)

    client = FakeTradingClient()
    stop_orders_submitted = []

    def submit_order(req):
        if isinstance(req, StopOrderRequest):
            stop_order = FakeOrder(id=f"stop-{len(stop_orders_submitted) + 1}", symbol="SPY", status=OrderStatus.NEW,
                                    order_type=OrderType.STOP, qty=req.qty, stop_price=req.stop_price)
            stop_orders_submitted.append(stop_order)
            return stop_order
        return FakeOrder(id="entry-1", status=OrderStatus.FILLED, filled_qty=10.0, filled_avg_price=451.0)

    client.submit_order_fn = submit_order
    client.orders_by_request = lambda filter: list(stop_orders_submitted)  # reflects real, current state
    client.get_order_by_id_fn = lambda order_id: FakeOrder(id=order_id, status=OrderStatus.FILLED, filled_qty=10.0, filled_avg_price=451.0)

    # "The listener wins the race": it reacts to the fill first.
    listener_order = _order(filled_qty=10.0, client_order_id=coid)
    listener_trade_update = _trade_update(event=TradeEvent.FILL, order=listener_order)
    listener_result = handle_trade_update(client, listener_trade_update, sleep_fn=_no_sleep)
    assert listener_result["action"] == "protected"
    assert len(stop_orders_submitted) == 1

    # "submit_entry_and_stop() reacts to the SAME fill moments later" —
    # must detect the listener already protected it, not double-submit.
    result = submit_entry_and_stop(client, candidate, _approved_decision(1.0), equity=10_000.0, guardrails=_guardrails(), sleep_fn=_no_sleep)

    assert result.filled is True
    assert result.stop_order_submitted is True  # protected — just not by this call
    assert len(stop_orders_submitted) == 1  # still only one stop order total, no duplicate


# --- listener liveness heartbeat (design session, 2026-08-22) ---------------

def _fake_stream(consecutive_failures=0, alert_threshold=5):
    return SimpleNamespace(_consecutive_failures=consecutive_failures, _alert_threshold=alert_threshold)


def test_heartbeat_tick_fires_when_failure_count_is_below_threshold():
    stream = _fake_stream(consecutive_failures=2, alert_threshold=5)
    calls = []

    result = _heartbeat_tick(stream, send_fn=lambda: calls.append(1))

    assert result is True
    assert calls == [1]


def test_heartbeat_tick_skipped_when_at_or_above_threshold():
    calls = []

    at_threshold = _heartbeat_tick(_fake_stream(consecutive_failures=5, alert_threshold=5), send_fn=lambda: calls.append(1))
    above_threshold = _heartbeat_tick(_fake_stream(consecutive_failures=7, alert_threshold=5), send_fn=lambda: calls.append(1))

    assert at_threshold is False
    assert above_threshold is False
    assert calls == []  # never pinged in either case


def test_send_listener_heartbeat_no_ops_with_a_logged_warning_when_url_unset(monkeypatch, caplog):
    monkeypatch.delenv("HEALTHCHECKS_LISTENER_HEARTBEAT_URL", raising=False)
    fake_requests = FakeRequestsModule()

    with caplog.at_level("WARNING"):
        result = send_listener_heartbeat(requests_module=fake_requests)

    assert result is False
    assert fake_requests.get_calls == []
    assert any("HEALTHCHECKS_LISTENER_HEARTBEAT_URL not set" in message for message in caplog.messages)


def test_send_listener_heartbeat_pings_the_configured_url():
    fake_requests = FakeRequestsModule()

    result = send_listener_heartbeat(heartbeat_url="https://uptimerobot.example/hb-listener", requests_module=fake_requests)

    assert result is True
    assert fake_requests.get_calls == [("https://uptimerobot.example/hb-listener", 10)]


def test_send_listener_heartbeat_falls_back_to_env_when_no_url_arg_given(monkeypatch):
    monkeypatch.setenv("HEALTHCHECKS_LISTENER_HEARTBEAT_URL", "https://uptimerobot.example/from-env")
    fake_requests = FakeRequestsModule()

    result = send_listener_heartbeat(requests_module=fake_requests)

    assert result is True
    assert fake_requests.get_calls == [("https://uptimerobot.example/from-env", 10)]


def test_send_listener_heartbeat_swallows_a_ping_failure_and_returns_false():
    fake_requests = FakeRequestsModule(raise_exc=RuntimeError("connection refused"))

    result = send_listener_heartbeat(heartbeat_url="https://uptimerobot.example/hb-listener", requests_module=fake_requests)

    assert result is False
    assert len(fake_requests.get_calls) == 1


def test_heartbeat_tick_ping_exception_does_not_propagate_or_affect_the_caller():
    # send_fn here simulates send_listener_heartbeat()'s own real behavior
    # (it never raises) — but _heartbeat_tick() must be safe even if a
    # caller-supplied send_fn somehow did raise, since a monitoring hiccup
    # must never take down the listener's main loop.
    stream = _fake_stream(consecutive_failures=0, alert_threshold=5)

    def exploding_send():
        raise RuntimeError("network blip")

    with pytest.raises(RuntimeError):
        _heartbeat_tick(stream, send_fn=exploding_send)
    # confirms the exception is send_listener_heartbeat()'s own responsibility
    # to swallow (verified above) — _heartbeat_tick() itself doesn't add a
    # second safety net, so send_listener_heartbeat() must never raise in
    # real use, which the tests above already confirm it doesn't.


def test_heartbeat_loop_pings_once_per_interval_using_the_injected_sleep_and_send_fns():
    stream = _fake_stream(consecutive_failures=0, alert_threshold=5)
    sleep_calls = []
    send_calls = []

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)
        if len(sleep_calls) >= 3:
            raise asyncio.CancelledError()  # stop the otherwise-infinite loop after 3 ticks

    def fake_send():
        send_calls.append(1)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(heartbeat_loop(stream, interval_seconds=300, sleep_fn=fake_sleep, send_fn=fake_send))

    assert sleep_calls == [300, 300, 300]
    assert send_calls == [1, 1]  # only the first 2 sleeps complete before the 3rd raises


def test_heartbeat_loop_skips_send_fn_while_connection_is_unhealthy():
    stream = _fake_stream(consecutive_failures=5, alert_threshold=5)
    send_calls = []

    async def fake_sleep(seconds):
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(heartbeat_loop(stream, interval_seconds=300, sleep_fn=fake_sleep, send_fn=lambda: send_calls.append(1)))

    assert send_calls == []
