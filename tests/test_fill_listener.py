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
from types import SimpleNamespace

import pytest

from alpaca.trading.enums import OrderSide, OrderStatus, OrderType, TradeEvent
from alpaca.trading.stream import TradingStream

from src import telegram_bot
from src.execution import encode_client_order_id
from src.fill_listener import MonitoredTradingStream, handle_trade_update

from tests.test_execution import FakeOrder, FakeTradingClient


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


def _trade_update(event=TradeEvent.FILL, order=None):
    return SimpleNamespace(event=event, order=order or _order(), timestamp=None, position_qty=None, price=None, qty=None)


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


# --- handle_trade_update: the real protection path --------------------------

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
    assert len(client.submitted_orders) == 1
    assert client.submitted_orders[0].stop_price == stop_price


def test_handle_trade_update_partial_fill_resizes_an_existing_stop():
    stop_price = 435.0
    order = _order(filled_qty=8.0, client_order_id=encode_client_order_id("SPY", "2026-08-10", stop_price))
    trade_update = _trade_update(event=TradeEvent.PARTIAL_FILL, order=order)
    client = FakeTradingClient()
    client.orders_by_request = lambda filter: [
        FakeOrder(id="stop-1", symbol="SPY", status=OrderStatus.NEW, order_type=OrderType.STOP, qty=5.0, stop_price=stop_price)
    ]
    client.get_order_by_id_fn = lambda order_id: FakeOrder(id=order_id, status=OrderStatus.NEW, qty=8.0, stop_price=stop_price)

    result = handle_trade_update(client, trade_update, sleep_fn=lambda s: None)

    assert result["action"] == "protected"
    assert client.submitted_orders == []  # resized via PATCH, never resubmitted
    assert len(client.replace_calls) == 1
    assert client.replace_calls[0][1].qty == 8


def test_handle_trade_update_redelivered_event_for_an_already_protected_fill_is_a_noop():
    # Idempotency: a redelivered/duplicate trade_updates event for a fill
    # already protected at the correct cumulative qty must not resubmit
    # or replace anything.
    stop_price = 435.0
    order = _order(filled_qty=10.0, client_order_id=encode_client_order_id("SPY", "2026-08-10", stop_price))
    trade_update = _trade_update(event=TradeEvent.FILL, order=order)
    client = FakeTradingClient()
    client.orders_by_request = lambda filter: [
        FakeOrder(id="stop-1", symbol="SPY", status=OrderStatus.NEW, order_type=OrderType.STOP, qty=10.0, stop_price=stop_price)
    ]

    result = handle_trade_update(client, trade_update, sleep_fn=lambda s: None)

    assert result["action"] == "protected"
    assert client.submitted_orders == []
    assert client.replace_calls == []
