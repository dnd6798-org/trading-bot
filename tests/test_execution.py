"""
execution.py milestone (spec v33 execution.py design session — see
CLAUDE.md "Current status"). Covers, against synthetic data and a
hand-built FakeTradingClient (no network calls):

  - sizing/stop-anchoring math: signal-day-close anchoring
    (compute_signal_day_stop_price), the pre-fill qty proxy
    (estimate_pre_fill_qty), the notional second-stage cap
    (cap_qty_to_notional), realized-risk reporting (compute_realized_
    risk), and the ratchet-only replace logic (compute_ratcheted_
    stop_price/replace_stop_order_if_favorable/ratchet_position_stop),
    including the T-1-anchored-ATR reference the daily ratchet uses.
  - order-flow plumbing: fill polling/classification (poll_order_until_
    terminal/confirm_entry_fill, including partial fills), and the
    unprotected-window safeguard (submit_stop_order_with_retry — retries
    with backoff then fires a distinct Telegram alert on total failure).
  - the full per-candidate entry flow (submit_entry_and_stop), including
    a simulated unprotected-window failure end to end: entry fills, then
    every stop-submission attempt fails.
  - state builders (build_open_positions/build_account_state/get_today_
    entry_count) against a FakeTradingClient standing in for Alpaca.

No test here exercises run_daily_execution_job() against a real Alpaca
account — that's the separate, one-off
scripts/dry_run_execution_track_b.py per the milestone brief ("an
end-to-end paper-account dry run placing at least one real entry + stop
pair"), not meant to run as part of the automated suite.
"""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from alpaca.common.exceptions import APIError
from alpaca.trading.enums import OrderStatus, OrderType
from alpaca.trading.requests import MarketOrderRequest, StopOrderRequest

from src import execution, telegram_bot
from src.data_ingestion import Candle
from src.execution import (
    LivePosition,
    TrackBEntryResult,
    compute_signal_day_stop_price,
    estimate_pre_fill_qty,
    cap_qty_to_notional,
    compute_realized_risk,
    compute_extreme_close_since_entry,
    compute_ratcheted_stop_price,
    replace_stop_order_if_favorable,
    ratchet_position_stop,
    confirm_entry_fill,
    poll_order_until_terminal,
    submit_stop_order_with_retry,
    submit_or_resize_stop_order_with_retry,
    submit_entry_and_stop,
    generate_daily_candidates,
    fetch_track_b_symbol_data,
    build_open_positions,
    build_account_state,
    get_today_entry_count,
    compute_stop_price_for_entry_date,
    protect_unprotected_fills,
    has_resting_protective_stop,
    encode_client_order_id,
    decode_client_order_id,
    send_daily_heartbeat,
    main,
    ATR_MULTIPLIER,
)
from src.risk_filter import RiskDecision


@pytest.fixture(autouse=True)
def captured_telegram_messages(monkeypatch):
    sent = []
    monkeypatch.setattr(telegram_bot, "send_message", lambda text: sent.append(text))
    return sent


# --- fakes -------------------------------------------------------------

class FakeOrder:
    def __init__(self, id="order-1", status=OrderStatus.NEW, filled_qty=0.0, filled_avg_price=None,
                 symbol="SPY", qty=1.0, stop_price=None, order_type=OrderType.MARKET,
                 submitted_at=None, filled_at=None, market_value=None, avg_entry_price=None,
                 client_order_id=None):
        self.id = id
        self.status = status
        self.filled_qty = filled_qty
        self.filled_avg_price = filled_avg_price
        self.symbol = symbol
        self.qty = qty
        self.stop_price = stop_price
        self.order_type = order_type
        self.submitted_at = submitted_at or datetime(2026, 8, 10, tzinfo=timezone.utc)
        self.filled_at = filled_at
        self.client_order_id = client_order_id


def _not_found_api_error(client_order_id="some-id"):
    """
    Mirrors the EMPIRICALLY CONFIRMED real behavior of TradingClient.
    get_order_by_client_id() on a genuine not-found lookup (real paper
    account, alpaca-py 0.43.5): raises alpaca.common.exceptions.APIError
    with .status_code == 404 (.code == 40410000). Constructed via a real
    APIError with a fake http_error carrying just enough shape
    (.response.status_code) for the real .status_code property to work,
    not a hand-rolled stand-in exception type.
    """
    return APIError(
        f'{{"code":40410000,"message":"order not found for {client_order_id}"}}',
        http_error=SimpleNamespace(response=SimpleNamespace(status_code=404)),
    )


class FakePosition:
    def __init__(self, symbol, qty, avg_entry_price, market_value):
        self.symbol = symbol
        self.qty = qty
        self.avg_entry_price = avg_entry_price
        self.market_value = market_value


class FakeAccount:
    def __init__(self, equity, last_equity):
        self.equity = equity
        self.last_equity = last_equity


class FakePortfolioHistory:
    def __init__(self, equity):
        self.equity = equity


class FakeTradingClient:
    """Minimal stand-in for alpaca.trading.client.TradingClient."""

    def __init__(self):
        self.submitted_orders = []
        self.replace_calls = []
        self.cancel_calls = []
        self.submit_order_fn = None
        self.get_order_by_id_fn = None
        self.get_order_by_client_id_fn = None
        self.cancel_order_by_id_fn = None
        self.replace_order_by_id_fn = None
        self.orders_by_request = None  # optional callable(filter) -> list[FakeOrder]
        self.positions = []
        self.account = FakeAccount(equity=10_000.0, last_equity=10_000.0)
        self.portfolio_history_equity = [10_000.0]

    def submit_order(self, order_data):
        self.submitted_orders.append(order_data)
        if self.submit_order_fn is not None:
            return self.submit_order_fn(order_data)
        raise NotImplementedError("test must set submit_order_fn")

    def get_order_by_id(self, order_id, filter=None):
        if self.get_order_by_id_fn is not None:
            return self.get_order_by_id_fn(order_id)
        raise NotImplementedError("test must set get_order_by_id_fn")

    def get_order_by_client_id(self, client_order_id):
        # Default: no order found under this id — the ordinary, common
        # case (no earlier same-day submission exists yet). Matches real
        # get_order_by_client_id()'s empirically-confirmed not-found
        # behavior exactly (see _not_found_api_error()), so every existing
        # test that never touches duplicate detection keeps working
        # unchanged. A test exercising the duplicate path sets
        # get_order_by_client_id_fn explicitly.
        if self.get_order_by_client_id_fn is not None:
            return self.get_order_by_client_id_fn(client_order_id)
        raise _not_found_api_error(client_order_id)

    def replace_order_by_id(self, order_id, order_data=None):
        self.replace_calls.append((order_id, order_data))
        if self.replace_order_by_id_fn is not None:
            return self.replace_order_by_id_fn(order_id, order_data)
        return FakeOrder(id=order_id, status=OrderStatus.NEW)

    def cancel_order_by_id(self, order_id):
        self.cancel_calls.append(order_id)
        if self.cancel_order_by_id_fn is not None:
            return self.cancel_order_by_id_fn(order_id)
        return None

    def get_orders(self, filter=None):
        if self.orders_by_request is not None:
            return self.orders_by_request(filter)
        return []

    def get_all_positions(self):
        return self.positions

    def get_account(self):
        return self.account

    def get_portfolio_history(self, history_filter=None):
        return FakePortfolioHistory(self.portfolio_history_equity)


def _no_sleep(_seconds):
    pass


# --- compute_signal_day_stop_price -----------------------------------------

def test_stop_price_anchored_to_signal_day_close_and_atr():
    # close_T=450, ATR(T)=5, multiplier=3.0 -> 450 - 15 = 435
    assert compute_signal_day_stop_price(450.0, 5.0, atr_multiplier=3.0) == 435.0


def test_stop_price_uses_module_default_atr_multiplier_when_not_given():
    assert compute_signal_day_stop_price(450.0, 5.0) == 450.0 - ATR_MULTIPLIER * 5.0


# --- estimate_pre_fill_qty (the flagged pre-fill proxy) ---------------------

def test_estimate_pre_fill_qty_uses_signal_close_as_fill_price_proxy():
    # risk_budget=$100, close_T=450, stop_price=435 -> stop_distance=15 -> qty=100/15
    qty = estimate_pre_fill_qty(100.0, 450.0, 435.0)
    assert abs(qty - (100.0 / 15.0)) < 1e-9


def test_estimate_pre_fill_qty_returns_zero_on_non_positive_stop_distance():
    # Degenerate: stop_price >= signal_close (e.g. an ATR/price anomaly).
    assert estimate_pre_fill_qty(100.0, 450.0, 450.0) == 0.0
    assert estimate_pre_fill_qty(100.0, 450.0, 460.0) == 0.0


# --- cap_qty_to_notional -----------------------------------------------------

def test_cap_qty_to_notional_leaves_qty_unchanged_when_under_the_cap():
    # qty=1 @ $450 = $450 notional, well under 55% of $10,000 = $5,500.
    assert cap_qty_to_notional(1.0, 450.0, 10_000.0, 55.0) == 1.0


def test_cap_qty_to_notional_shrinks_qty_when_over_the_cap():
    # qty=20 @ $450 = $9,000 notional, over 55% of $10,000 = $5,500.
    capped = cap_qty_to_notional(20.0, 450.0, 10_000.0, 55.0)
    assert abs(capped - (5_500.0 / 450.0)) < 1e-9
    assert capped * 450.0 <= 5_500.0 + 1e-9


def test_cap_qty_to_notional_handles_zero_equity_or_price_without_dividing_by_zero():
    assert cap_qty_to_notional(5.0, 450.0, 0.0, 55.0) == 5.0
    assert cap_qty_to_notional(5.0, 0.0, 10_000.0, 55.0) == 5.0


# --- compute_realized_risk ---------------------------------------------------

def test_compute_realized_risk_matches_actual_fill_not_the_pre_fill_proxy():
    # qty=6.67, fill_price=452 (gapped up from close_T=450), stop_price=435.
    # True realized risk is LARGER than the 1%-of-equity target because
    # the actual stop distance (452-435=17) exceeds the proxy's (450-435=15).
    result = compute_realized_risk(fill_price=452.0, stop_price=435.0, qty=100.0 / 15.0, equity=10_000.0)
    expected_risk_amount = (100.0 / 15.0) * (452.0 - 435.0)
    assert abs(result["risk_amount"] - expected_risk_amount) < 1e-6
    assert result["risk_pct"] > 1.0  # exceeds the 1% target, the tracked overnight-gap consequence


# --- ratchet: extreme_close / T-1 ATR anchoring / max()-only -----------------

def _series(dates, closes, atrs):
    candles = [Candle("SPY", f"{d}T00:00:00", open=c, high=c + 1, low=c - 1, close=c, volume=100) for d, c in zip(dates, closes)]
    return {
        "symbol": "SPY",
        "candles": candles,
        "atr": atrs,
        "entry_indices": set(),
        "date_index": {d: i for i, d in enumerate(dates)},
        # spec v42 §10.11: additive keys generate_daily_candidates()'s
        # DEBUG signal logging now reads — arbitrary but consistent
        # placeholder values, not asserted on by most callers of this
        # helper.
        "upper": [c + 5 for c in closes],
        "lower": [c - 5 for c in closes],
    }


def test_compute_extreme_close_since_entry_takes_the_max_close_in_the_window():
    dates = ["2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06"]
    series = _series(dates, closes=[100, 105, 103, 104], atrs=[1, 1, 1, 1])
    assert compute_extreme_close_since_entry(series, "2026-08-03", "2026-08-06") == 105


def test_compute_extreme_close_since_entry_excludes_days_before_entry():
    dates = ["2026-08-03", "2026-08-04", "2026-08-05"]
    series = _series(dates, closes=[999, 100, 102], atrs=[1, 1, 1])  # the 999 spike is BEFORE entry
    assert compute_extreme_close_since_entry(series, "2026-08-04", "2026-08-05") == 102


def test_compute_ratcheted_stop_price_moves_up_when_candidate_is_more_favorable():
    # extreme_close=110, prior_atr=2, multiplier=3 -> candidate = 110 - 6 = 104, above current 100.
    assert compute_ratcheted_stop_price(110.0, 2.0, 3.0, current_stop_price=100.0) == 104.0


def test_compute_ratcheted_stop_price_never_moves_down_ratchet_only():
    # extreme_close pulled back, candidate would be LOWER than current — must stay at current.
    assert compute_ratcheted_stop_price(101.0, 2.0, 3.0, current_stop_price=100.0) == 100.0


def test_ratchet_position_stop_uses_prior_day_atr_not_todays_t1_anchored():
    # today's ATR (index 2) is deliberately large (would produce a LOWER
    # stop if wrongly used); prior day's ATR (index 1) is small and must
    # be what's actually used, matching simulate_rotational_ensemble()'s
    # own prior_atr = atr[idx - 1] convention (no lookahead).
    dates = ["2026-08-03", "2026-08-04", "2026-08-05"]
    series = _series(dates, closes=[100, 105, 106], atrs=[1.0, 1.0, 50.0])
    position = LivePosition(
        symbol="SPY", qty=1.0, entry_price=100.0, entry_date="2026-08-03",
        stop_order_id="stop-1", stop_price=97.0, risk_amount=3.0, risk_pct=0.03, notional_pct_of_equity=1.0,
    )
    client = FakeTradingClient()
    # ratchet_position_stop() now independently re-queries live resting
    # stops (fix-up item 1) rather than trusting position.stop_order_id
    # blindly — a single matching resting stop puts this on the unchanged
    # single-stop replace path.
    client.orders_by_request = lambda filter: [
        FakeOrder(id="stop-1", symbol="SPY", status=OrderStatus.NEW, order_type=OrderType.STOP, qty=1.0, stop_price=97.0)
    ]

    replaced = ratchet_position_stop(client, position, series, today="2026-08-05", atr_multiplier=3.0)

    # extreme_close=106 (max close through today), prior_atr=atr[1]=1.0 -> candidate = 106 - 3 = 103 > 97.
    assert replaced is True
    assert len(client.replace_calls) == 1
    _, replace_request = client.replace_calls[0]
    assert replace_request.stop_price == 103.0


def test_ratchet_position_stop_does_not_replace_when_prior_atr_unavailable():
    # First day of history — no T-1 index to anchor to.
    dates = ["2026-08-03"]
    series = _series(dates, closes=[100], atrs=[None])
    position = LivePosition(
        symbol="SPY", qty=1.0, entry_price=100.0, entry_date="2026-08-03",
        stop_order_id="stop-1", stop_price=97.0, risk_amount=3.0, risk_pct=0.03, notional_pct_of_equity=1.0,
    )
    client = FakeTradingClient()

    assert ratchet_position_stop(client, position, series, today="2026-08-03") is False
    assert client.replace_calls == []


# --- ratchet_position_stop: multi-stop INDEPENDENT RATCHETING (fix-up item 3,
# replaces the removed new-before-cancel consolidation mechanism — see
# module docstring FIX-UP #2/#3 for why: Alpaca's real held-quantity
# validation rejects a new order that duplicates qty already held by
# other still-open resting stops for the same symbol) -----------------------

def test_ratchet_position_stop_replaces_each_resting_stop_independently_when_multiple_exist():
    # Two resting stops (the top-up model's leftover state) both sit
    # below the new candidate price -> EACH gets its own independent
    # PATCH replace call to the SAME target price. No new order is ever
    # submitted and nothing is ever cancelled.
    dates = ["2026-08-03", "2026-08-04", "2026-08-05"]
    series = _series(dates, closes=[100, 110, 105], atrs=[1.0, 2.0, 50.0])
    position = LivePosition(
        symbol="SPY", qty=8.0, entry_price=100.0, entry_date="2026-08-03",
        stop_order_id="stop-1", stop_price=96.0, risk_amount=32.0, risk_pct=0.32, notional_pct_of_equity=1.0,
    )
    client = FakeTradingClient()
    resting = [
        FakeOrder(id="stop-1", symbol="SPY", status=OrderStatus.NEW, order_type=OrderType.STOP, qty=5.0, stop_price=97.0,
                  submitted_at=datetime(2026, 8, 4, tzinfo=timezone.utc)),
        FakeOrder(id="stop-2", symbol="SPY", status=OrderStatus.NEW, order_type=OrderType.STOP, qty=3.0, stop_price=96.0,
                  submitted_at=datetime(2026, 8, 5, tzinfo=timezone.utc)),
    ]
    client.orders_by_request = lambda filter: list(resting)

    result = ratchet_position_stop(client, position, series, today="2026-08-05", atr_multiplier=3.0, sleep_fn=_no_sleep)

    # extreme_close=110 (max close 08-03..08-05), prior_atr=atr[1]=2.0 -> candidate = 110-6=104.
    # worst_current_price = min(97.0, 96.0) = 96.0 -> target = max(104, 96) = 104, above BOTH existing stops.
    assert result is True
    assert client.submitted_orders == []  # no new order ever submitted
    assert client.cancel_calls == []  # nothing ever cancelled
    assert len(client.replace_calls) == 2  # one independent PATCH per resting stop
    replaced_ids = {order_id for order_id, _ in client.replace_calls}
    assert replaced_ids == {"stop-1", "stop-2"}
    for _, replace_request in client.replace_calls:
        assert replace_request.stop_price == 104.0
        assert getattr(replace_request, "qty", None) is None  # qty is never touched by this path


def test_ratchet_position_stop_only_replaces_stops_the_new_price_actually_improves():
    # Stop-1 sits below the new target (gets replaced); stop-2 is already
    # ABOVE the new target (must be left alone, ratchet-only per-order,
    # same rule replace_stop_order_if_favorable() already applies to a
    # single stop — proves the multi-stop path isn't unconditional).
    dates = ["2026-08-03", "2026-08-04", "2026-08-05"]
    series = _series(dates, closes=[100, 110, 105], atrs=[1.0, 2.0, 50.0])
    position = LivePosition(
        symbol="SPY", qty=8.0, entry_price=100.0, entry_date="2026-08-03",
        stop_order_id="stop-1", stop_price=97.0, risk_amount=32.0, risk_pct=0.32, notional_pct_of_equity=1.0,
    )
    client = FakeTradingClient()
    resting = [
        FakeOrder(id="stop-1", symbol="SPY", status=OrderStatus.NEW, order_type=OrderType.STOP, qty=5.0, stop_price=97.0),
        FakeOrder(id="stop-2", symbol="SPY", status=OrderStatus.NEW, order_type=OrderType.STOP, qty=3.0, stop_price=105.0),
    ]
    client.orders_by_request = lambda filter: list(resting)

    result = ratchet_position_stop(client, position, series, today="2026-08-05", atr_multiplier=3.0, sleep_fn=_no_sleep)

    # worst_current_price = min(97.0, 105.0) = 97.0 -> candidate = 110-6=104 -> target = max(104, 97) = 104.
    # 104 > 97 (stop-1 replaced); 104 <= 105 (stop-2 left untouched).
    assert result is True
    assert client.submitted_orders == []
    assert client.cancel_calls == []
    assert len(client.replace_calls) == 1
    replaced_id, replace_request = client.replace_calls[0]
    assert replaced_id == "stop-1"
    assert replace_request.stop_price == 104.0


def test_ratchet_position_stop_returns_false_when_no_resting_stop_improves():
    # Every resting stop already sits at/above the new candidate ->
    # nothing gets replaced and the function reports no change.
    dates = ["2026-08-03", "2026-08-04", "2026-08-05"]
    series = _series(dates, closes=[100, 101, 100.5], atrs=[1.0, 50.0, 1.0])  # huge prior_atr -> candidate far below current
    position = LivePosition(
        symbol="SPY", qty=8.0, entry_price=100.0, entry_date="2026-08-03",
        stop_order_id="stop-1", stop_price=96.0, risk_amount=32.0, risk_pct=0.32, notional_pct_of_equity=1.0,
    )
    client = FakeTradingClient()
    resting = [
        FakeOrder(id="stop-1", symbol="SPY", status=OrderStatus.NEW, order_type=OrderType.STOP, qty=5.0, stop_price=97.0),
        FakeOrder(id="stop-2", symbol="SPY", status=OrderStatus.NEW, order_type=OrderType.STOP, qty=3.0, stop_price=96.0),
    ]
    client.orders_by_request = lambda filter: list(resting)

    result = ratchet_position_stop(client, position, series, today="2026-08-05", atr_multiplier=3.0, sleep_fn=_no_sleep)

    # extreme_close=101, prior_atr=atr[1]=50.0 -> candidate = 101-150 = -49, far below worst_current_price(96.0)
    # -> target stays 96.0 (ratchet-only, never worse) — neither existing stop (97.0, 96.0) is improved on.
    assert result is False
    assert client.submitted_orders == []
    assert client.cancel_calls == []
    assert client.replace_calls == []


# --- ratchet_position_stop: per-stop error isolation (fix-up item 4) -------

def test_ratchet_position_stop_multi_stop_all_succeed_is_unchanged_from_before_fixup(captured_telegram_messages):
    # Baseline: when every per-order replace call succeeds (no exception),
    # behavior/logging must be identical to before this fix-up — both
    # stops replaced, no Telegram summary sent at all.
    dates = ["2026-08-03", "2026-08-04", "2026-08-05"]
    series = _series(dates, closes=[100, 110, 105], atrs=[1.0, 2.0, 50.0])
    position = LivePosition(
        symbol="SPY", qty=8.0, entry_price=100.0, entry_date="2026-08-03",
        stop_order_id="stop-1", stop_price=96.0, risk_amount=32.0, risk_pct=0.32, notional_pct_of_equity=1.0,
    )
    client = FakeTradingClient()
    resting = [
        FakeOrder(id="stop-1", symbol="SPY", status=OrderStatus.NEW, order_type=OrderType.STOP, qty=5.0, stop_price=97.0),
        FakeOrder(id="stop-2", symbol="SPY", status=OrderStatus.NEW, order_type=OrderType.STOP, qty=3.0, stop_price=96.0),
    ]
    client.orders_by_request = lambda filter: list(resting)

    result = ratchet_position_stop(client, position, series, today="2026-08-05", atr_multiplier=3.0, sleep_fn=_no_sleep)

    # extreme_close=110, prior_atr=atr[1]=2.0 -> candidate = 104, above both 97.0 and 96.0 -> both replaced.
    assert result is True
    assert len(client.replace_calls) == 2
    assert captured_telegram_messages == []  # no summary when nothing failed


def test_ratchet_position_stop_multi_stop_partial_failure_still_attempts_and_applies_the_other(captured_telegram_messages):
    # stop-1's replace raises; stop-2 must still be attempted and actually
    # replaced — a failure earlier in the loop must not abort the rest.
    dates = ["2026-08-03", "2026-08-04", "2026-08-05"]
    series = _series(dates, closes=[100, 110, 105], atrs=[1.0, 2.0, 50.0])
    position = LivePosition(
        symbol="SPY", qty=8.0, entry_price=100.0, entry_date="2026-08-03",
        stop_order_id="stop-1", stop_price=96.0, risk_amount=32.0, risk_pct=0.32, notional_pct_of_equity=1.0,
    )
    client = FakeTradingClient()
    resting = [
        FakeOrder(id="stop-1", symbol="SPY", status=OrderStatus.NEW, order_type=OrderType.STOP, qty=5.0, stop_price=97.0),
        FakeOrder(id="stop-2", symbol="SPY", status=OrderStatus.NEW, order_type=OrderType.STOP, qty=3.0, stop_price=96.0),
    ]
    client.orders_by_request = lambda filter: list(resting)

    def replace_order_by_id(order_id, order_data):
        if order_id == "stop-1":
            raise RuntimeError("cannot replace order in accepted status")
        return FakeOrder(id=order_id, status=OrderStatus.NEW)
    client.replace_order_by_id_fn = replace_order_by_id

    # extreme_close=110, prior_atr=atr[1]=2.0 -> candidate = 104, above both 97.0 and 96.0.
    result = ratchet_position_stop(client, position, series, today="2026-08-05", atr_multiplier=3.0, sleep_fn=_no_sleep)

    # Both orders attempted despite stop-1's failure.
    assert {order_id for order_id, _ in client.replace_calls} == {"stop-1", "stop-2"}
    # stop-2's replace actually went through — the PATCH call for it carried the new price.
    stop_2_calls = [req for order_id, req in client.replace_calls if order_id == "stop-2"]
    assert len(stop_2_calls) == 1
    assert stop_2_calls[0].stop_price == 104.0
    # At least one stop ratcheted -> True, not masked by the other's failure.
    assert result is True

    # Non-urgent (NOT the existing URGENT/UNPROTECTED alert path) summary sent.
    assert len(captured_telegram_messages) == 1
    summary = captured_telegram_messages[0]
    assert "URGENT" not in summary
    assert "UNPROTECTED" not in summary
    assert "SPY" in summary
    assert "stop-2" in summary and "104.0" in summary  # the successful one, ratcheted to the new price
    assert "stop-1" in summary and "97.0" in summary and "cannot replace order in accepted status" in summary  # the failed one, still at its old price, with its error


def test_ratchet_position_stop_multi_stop_all_fail_reports_zero_successes(captured_telegram_messages):
    # Both replace calls raise -> no stop actually moves, result is False,
    # but the same non-urgent summary mechanism still fires (zero
    # successes reported, not silently swallowed).
    dates = ["2026-08-03", "2026-08-04", "2026-08-05"]
    series = _series(dates, closes=[100, 110, 105], atrs=[1.0, 2.0, 50.0])
    position = LivePosition(
        symbol="SPY", qty=8.0, entry_price=100.0, entry_date="2026-08-03",
        stop_order_id="stop-1", stop_price=96.0, risk_amount=32.0, risk_pct=0.32, notional_pct_of_equity=1.0,
    )
    client = FakeTradingClient()
    resting = [
        FakeOrder(id="stop-1", symbol="SPY", status=OrderStatus.NEW, order_type=OrderType.STOP, qty=5.0, stop_price=97.0),
        FakeOrder(id="stop-2", symbol="SPY", status=OrderStatus.NEW, order_type=OrderType.STOP, qty=3.0, stop_price=96.0),
    ]
    client.orders_by_request = lambda filter: list(resting)
    client.replace_order_by_id_fn = lambda order_id, order_data: (_ for _ in ()).throw(RuntimeError(f"broker rejected {order_id}"))

    result = ratchet_position_stop(client, position, series, today="2026-08-05", atr_multiplier=3.0, sleep_fn=_no_sleep)

    assert {order_id for order_id, _ in client.replace_calls} == {"stop-1", "stop-2"}  # both still attempted
    assert result is False  # nothing actually ratcheted

    assert len(captured_telegram_messages) == 1
    summary = captured_telegram_messages[0]
    assert "URGENT" not in summary
    assert "0 of 2" in summary  # zero successes, explicitly reported, not omitted
    assert "stop-1" in summary and "broker rejected stop-1" in summary
    assert "stop-2" in summary and "broker rejected stop-2" in summary


def test_replace_stop_order_if_favorable_never_calls_replace_when_not_favorable():
    client = FakeTradingClient()
    replaced = replace_stop_order_if_favorable(client, "stop-1", candidate_stop_price=99.0, current_stop_price=100.0)
    assert replaced is False
    assert client.replace_calls == []


def test_replace_stop_order_if_favorable_uses_patch_replace_not_cancel_resubmit():
    client = FakeTradingClient()
    replaced = replace_stop_order_if_favorable(client, "stop-1", candidate_stop_price=105.0, current_stop_price=100.0)
    assert replaced is True
    assert len(client.replace_calls) == 1
    order_id, request = client.replace_calls[0]
    assert order_id == "stop-1"
    assert request.stop_price == 105.0


# --- confirm_entry_fill: filled / rejected / pending, three-way (spec §4.5) -

def test_confirm_entry_fill_full_fill():
    order = FakeOrder(status=OrderStatus.FILLED, filled_qty=10.0, filled_avg_price=451.23)
    result = confirm_entry_fill(order)
    assert result == {"filled": True, "pending": False, "filled_qty": 10.0, "filled_avg_price": 451.23, "status": str(OrderStatus.FILLED)}


def test_confirm_entry_fill_partial_fill_is_treated_as_a_real_fill():
    # Real, unprotected shares — must still get a stop, not be discarded like a clean reject.
    order = FakeOrder(status=OrderStatus.PARTIALLY_FILLED, filled_qty=4.0, filled_avg_price=451.0)
    result = confirm_entry_fill(order)
    assert result["filled"] is True
    assert result["pending"] is False
    assert result["filled_qty"] == 4.0


def test_confirm_entry_fill_rejection_with_zero_fill_is_not_pending():
    order = FakeOrder(status=OrderStatus.REJECTED, filled_qty=0.0, filled_avg_price=None)
    result = confirm_entry_fill(order)
    assert result == {"filled": False, "pending": False, "filled_qty": 0.0, "filled_avg_price": None, "status": str(OrderStatus.REJECTED)}


def test_confirm_entry_fill_still_open_zero_fill_is_pending_not_rejected():
    # The expected, ordinary state for a next-session-open fill that
    # hasn't happened yet — must NOT be conflated with a genuine reject.
    order = FakeOrder(status=OrderStatus.NEW, filled_qty=0.0, filled_avg_price=None)
    result = confirm_entry_fill(order)
    assert result["filled"] is False
    assert result["pending"] is True


# --- poll_order_until_terminal ----------------------------------------------

def test_poll_order_until_terminal_polls_until_filled():
    statuses = [OrderStatus.NEW, OrderStatus.NEW, OrderStatus.FILLED]
    calls = {"n": 0}

    def get_order_by_id(order_id):
        order = FakeOrder(id=order_id, status=statuses[min(calls["n"], len(statuses) - 1)], filled_qty=10.0 if statuses[calls["n"]] == OrderStatus.FILLED else 0.0)
        calls["n"] += 1
        return order

    client = FakeTradingClient()
    client.get_order_by_id_fn = get_order_by_id

    result = poll_order_until_terminal(client, "order-1", sleep_fn=_no_sleep)

    assert result.status == OrderStatus.FILLED
    assert calls["n"] == 3


def test_poll_order_until_terminal_stops_on_zero_timeout_without_looping():
    client = FakeTradingClient()
    client.get_order_by_id_fn = lambda order_id: FakeOrder(status=OrderStatus.NEW)

    result = poll_order_until_terminal(client, "order-1", timeout_seconds=0, sleep_fn=_no_sleep)

    assert result.status == OrderStatus.NEW


# --- submit_stop_order_with_retry: the unprotected-window safeguard --------

def test_submit_stop_order_with_retry_succeeds_first_try_no_alert():
    client = FakeTradingClient()
    client.submit_order_fn = lambda req: FakeOrder(id="stop-1", status=OrderStatus.NEW, stop_price=req.stop_price)

    order = submit_stop_order_with_retry(client, "SPY", 10.0, 435.0, sleep_fn=_no_sleep)

    assert order is not None
    assert order.stop_price == 435.0
    assert len(client.submitted_orders) == 1


def test_submit_stop_order_with_retry_recovers_after_transient_failures(captured_telegram_messages):
    attempts = {"n": 0}

    def submit_order(req):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("simulated transient API failure")
        return FakeOrder(id="stop-1", status=OrderStatus.NEW, stop_price=req.stop_price)

    client = FakeTradingClient()
    client.submit_order_fn = submit_order

    order = submit_stop_order_with_retry(client, "SPY", 10.0, 435.0, backoff_seconds=(0, 0, 0), sleep_fn=_no_sleep)

    assert order is not None
    assert attempts["n"] == 3
    assert captured_telegram_messages == []  # recovered — no urgent alert needed


def test_submit_stop_order_with_retry_exhausts_all_attempts_fires_urgent_alert_and_returns_none(captured_telegram_messages):
    client = FakeTradingClient()
    client.submit_order_fn = lambda req: (_ for _ in ()).throw(RuntimeError("broker down"))

    order = submit_stop_order_with_retry(client, "SPY", 10.0, 435.0, backoff_seconds=(0, 0), sleep_fn=_no_sleep)

    assert order is None
    assert len(client.submitted_orders) == 3  # initial attempt + 2 backoff retries
    assert len(captured_telegram_messages) == 1
    alert = captured_telegram_messages[0]
    assert "URGENT" in alert
    assert "UNPROTECTED" in alert
    assert "SPY" in alert


# --- submit_entry_and_stop: full per-candidate flow -------------------------

def _approved_decision(risk_pct=1.0):
    return RiskDecision(approved=True, reason="approved", position_size=risk_pct)


def _guardrails(max_position_size_pct=55.0):
    from src.config import GuardrailConfig
    return GuardrailConfig(
        max_risk_per_trade_pct=1.0, max_position_size_pct=max_position_size_pct,
        max_daily_loss_pct=4.0, max_trades_per_day=8, max_combined_open_risk_pct=8.0, max_drawdown_pct=10.0,
    )


def test_submit_entry_and_stop_happy_path_fills_and_protects():
    candidate = {"symbol": "SPY", "close": 450.0, "atr": 5.0, "timestamp": "2026-08-10T00:00:00"}
    def submit_order(req):
        if isinstance(req, StopOrderRequest):
            return FakeOrder(id="stop-1", status=OrderStatus.NEW, stop_price=req.stop_price)
        assert isinstance(req, MarketOrderRequest)
        return FakeOrder(id="entry-1", status=OrderStatus.FILLED, filled_qty=10.0, filled_avg_price=451.0)

    client = FakeTradingClient()
    client.submit_order_fn = submit_order
    client.get_order_by_id_fn = lambda order_id: FakeOrder(id=order_id, status=OrderStatus.FILLED, filled_qty=10.0, filled_avg_price=451.0)

    result = submit_entry_and_stop(client, candidate, _approved_decision(1.0), equity=10_000.0, guardrails=_guardrails(), sleep_fn=_no_sleep)

    assert isinstance(result, TrackBEntryResult)
    assert result.submitted is True
    assert result.filled is True
    assert result.filled_qty == 10.0
    assert result.stop_order_submitted is True
    assert result.stop_price == 450.0 - ATR_MULTIPLIER * 5.0
    # realized risk uses the ACTUAL fill price (451), not the pre-fill proxy (close_T=450).
    assert result.realized_risk_pct is not None


def test_submit_entry_and_stop_unprotected_window_when_stop_submission_exhausts_retries(captured_telegram_messages):
    # Simulated unprotected-window failure (required test, milestone brief,
    # step 6): entry fills cleanly, but every stop-submission attempt fails.
    candidate = {"symbol": "SPY", "close": 450.0, "atr": 5.0, "timestamp": "2026-08-10T00:00:00"}
    client = FakeTradingClient()

    def submit_order(req):
        if isinstance(req, StopOrderRequest):
            raise RuntimeError("broker rejected stop order")
        return FakeOrder(id="entry-1", status=OrderStatus.FILLED, filled_qty=10.0, filled_avg_price=451.0)

    client.submit_order_fn = submit_order
    client.get_order_by_id_fn = lambda order_id: FakeOrder(id=order_id, status=OrderStatus.FILLED, filled_qty=10.0, filled_avg_price=451.0)

    result = submit_entry_and_stop(client, candidate, _approved_decision(1.0), equity=10_000.0, guardrails=_guardrails(), sleep_fn=_no_sleep)

    assert result.filled is True  # the entry itself DID fill — the position is real and open
    assert result.stop_order_submitted is False  # but it is NOT protected
    urgent_alerts = [m for m in captured_telegram_messages if "URGENT" in m and "UNPROTECTED" in m]
    assert len(urgent_alerts) == 1
    assert "SPY" in urgent_alerts[0]


def test_submit_entry_and_stop_skips_order_submission_when_computed_qty_non_positive():
    # Degenerate ATR making the stop cross the close — must not submit any order at all.
    candidate = {"symbol": "SPY", "close": 450.0, "atr": 0.0, "timestamp": "2026-08-10T00:00:00"}
    client = FakeTradingClient()

    result = submit_entry_and_stop(client, candidate, _approved_decision(1.0), equity=10_000.0, guardrails=_guardrails(), sleep_fn=_no_sleep)

    assert result.submitted is False
    assert result.reason == "computed_qty_non_positive"
    assert client.submitted_orders == []


def test_submit_entry_and_stop_pending_order_does_not_alert_or_submit_a_stop(captured_telegram_messages):
    # The realistic outcome for a job run right after post-close, before
    # next session's open — must be treated as ordinary, not a failure.
    candidate = {"symbol": "SPY", "close": 450.0, "atr": 5.0, "timestamp": "2026-08-10T00:00:00"}
    client = FakeTradingClient()
    client.submit_order_fn = lambda req: FakeOrder(id="entry-1", status=OrderStatus.NEW, filled_qty=0.0, filled_avg_price=None)
    client.get_order_by_id_fn = lambda order_id: FakeOrder(id=order_id, status=OrderStatus.NEW, filled_qty=0.0, filled_avg_price=None)

    result = submit_entry_and_stop(
        client, candidate, _approved_decision(1.0), equity=10_000.0, guardrails=_guardrails(),
        sleep_fn=_no_sleep, poll_timeout_seconds=0,
    )

    assert result.filled is False
    assert result.reason == "pending_next_session_fill"
    assert result.stop_order_submitted is False
    assert captured_telegram_messages == []  # not a failure, no alert
    assert len(client.submitted_orders) == 1  # only the entry attempt — no stop submitted for a non-existent fill


def test_submit_entry_and_stop_no_fill_does_not_submit_a_stop():
    candidate = {"symbol": "SPY", "close": 450.0, "atr": 5.0, "timestamp": "2026-08-10T00:00:00"}
    client = FakeTradingClient()
    client.submit_order_fn = lambda req: FakeOrder(id="entry-1", status=OrderStatus.REJECTED, filled_qty=0.0, filled_avg_price=None)
    client.get_order_by_id_fn = lambda order_id: FakeOrder(id=order_id, status=OrderStatus.REJECTED, filled_qty=0.0, filled_avg_price=None)

    result = submit_entry_and_stop(client, candidate, _approved_decision(1.0), equity=10_000.0, guardrails=_guardrails(), sleep_fn=_no_sleep)

    assert result.filled is False
    assert result.stop_order_submitted is False
    assert len(client.submitted_orders) == 1  # only the entry attempt, never a stop


def test_submit_entry_and_stop_skips_stop_submission_when_a_resting_stop_already_exists(captured_telegram_messages):
    # Fix-up item 2: closes the race between this function's own stop
    # submission and fill_listener.py's handler reacting to the SAME fill
    # concurrently — simulates "the listener won the race" by seeding a
    # resting stop for SPY BEFORE this call ever gets to its own stop step.
    candidate = {"symbol": "SPY", "close": 450.0, "atr": 5.0, "timestamp": "2026-08-10T00:00:00"}
    client = FakeTradingClient()
    client.orders_by_request = lambda filter: [
        FakeOrder(id="stop-from-listener", symbol="SPY", status=OrderStatus.NEW, order_type=OrderType.STOP, qty=10.0, stop_price=435.0)
    ]

    def submit_order(req):
        assert not isinstance(req, StopOrderRequest), "must not submit a duplicate stop when one already rests"
        return FakeOrder(id="entry-1", status=OrderStatus.FILLED, filled_qty=10.0, filled_avg_price=451.0)
    client.submit_order_fn = submit_order
    client.get_order_by_id_fn = lambda order_id: FakeOrder(id=order_id, status=OrderStatus.FILLED, filled_qty=10.0, filled_avg_price=451.0)

    result = submit_entry_and_stop(client, candidate, _approved_decision(1.0), equity=10_000.0, guardrails=_guardrails(), sleep_fn=_no_sleep)

    assert result.filled is True
    assert result.stop_order_submitted is True  # protected — just not BY this call
    assert len(client.submitted_orders) == 1  # only the entry — no duplicate stop
    assert captured_telegram_messages == []  # not a failure, nothing to alert on


def test_submit_entry_and_stop_shares_the_has_resting_protective_stop_check():
    # Regression guard, same category as the protect_unprotected_fills()
    # source-inspection guard above: proves submit_entry_and_stop() gates
    # on the SAME shared function, not a private reimplementation.
    import inspect
    from src import execution
    source = inspect.getsource(execution.submit_entry_and_stop)
    assert "has_resting_protective_stop(" in source


# --- submit_entry_and_stop: per-symbol duplicate-entry protection (spec v44 §10.13) ---

def test_submit_entry_and_stop_detects_existing_order_under_client_order_id_and_skips_submission(captured_telegram_messages):
    # An earlier same-day invocation (e.g. a service restart) already
    # submitted this exact symbol/signal/day's entry — get_order_by_
    # client_id() finds it (any status — here still pending, unfilled).
    # Must NOT submit a second entry order, and must NOT alert (a detected
    # duplicate is the guard working as intended, not a failure).
    candidate = {"symbol": "SPY", "close": 450.0, "atr": 5.0, "timestamp": "2026-08-10T00:00:00"}
    client = FakeTradingClient()
    client.get_order_by_client_id_fn = lambda coid: FakeOrder(id="earlier-invocation-order", client_order_id=coid, status=OrderStatus.NEW)

    def submit_order(req):
        raise AssertionError("must not submit any order when a duplicate client_order_id is detected")
    client.submit_order_fn = submit_order

    result = submit_entry_and_stop(client, candidate, _approved_decision(1.0), equity=10_000.0, guardrails=_guardrails(), sleep_fn=_no_sleep)

    assert result.submitted is False
    assert result.filled is False
    assert result.reason == "duplicate_client_order_id_skipped"
    assert client.submitted_orders == []
    assert captured_telegram_messages == []  # not a failure — no alert


def test_submit_entry_and_stop_proceeds_normally_when_no_existing_order_under_client_order_id():
    # The ordinary, common case: get_order_by_client_id() raises the real
    # confirmed not-found error (APIError, status_code == 404) — must
    # proceed exactly as before this milestone, no behavior change.
    candidate = {"symbol": "SPY", "close": 450.0, "atr": 5.0, "timestamp": "2026-08-10T00:00:00"}
    client = FakeTradingClient()
    client.get_order_by_client_id_fn = lambda coid: (_ for _ in ()).throw(_not_found_api_error(coid))

    def submit_order(req):
        if isinstance(req, StopOrderRequest):
            return FakeOrder(id="stop-1", status=OrderStatus.NEW, stop_price=req.stop_price)
        assert isinstance(req, MarketOrderRequest)
        return FakeOrder(id="entry-1", status=OrderStatus.FILLED, filled_qty=10.0, filled_avg_price=451.0)

    client.submit_order_fn = submit_order
    client.get_order_by_id_fn = lambda order_id: FakeOrder(id=order_id, status=OrderStatus.FILLED, filled_qty=10.0, filled_avg_price=451.0)

    result = submit_entry_and_stop(client, candidate, _approved_decision(1.0), equity=10_000.0, guardrails=_guardrails(), sleep_fn=_no_sleep)

    assert result.submitted is True
    assert result.filled is True
    assert result.reason is None
    assert len(client.submitted_orders) == 2  # entry + stop, unchanged from before this milestone


def test_submit_entry_and_stop_duplicate_check_is_independent_of_the_resting_stop_race_closure():
    # Regression guard: the new client_order_id duplicate check and the
    # existing has_resting_protective_stop() race-closure check (fix-up
    # item 2, above) are two independent mechanisms that must both keep
    # working correctly together — this scenario exercises BOTH in one
    # call. No duplicate entry order exists yet (get_order_by_client_id
    # -> not found, so the entry proceeds), but a resting stop for this
    # symbol ALREADY exists (e.g. the fill_listener won a race on this
    # exact fill) — the entry must still submit, and the stop step must
    # still correctly skip submitting a second stop.
    candidate = {"symbol": "SPY", "close": 450.0, "atr": 5.0, "timestamp": "2026-08-10T00:00:00"}
    client = FakeTradingClient()
    client.get_order_by_client_id_fn = lambda coid: (_ for _ in ()).throw(_not_found_api_error(coid))
    client.orders_by_request = lambda filter: [
        FakeOrder(id="stop-from-listener", symbol="SPY", status=OrderStatus.NEW, order_type=OrderType.STOP, qty=10.0, stop_price=435.0)
    ]

    def submit_order(req):
        assert not isinstance(req, StopOrderRequest), "must not submit a duplicate stop when one already rests"
        return FakeOrder(id="entry-1", status=OrderStatus.FILLED, filled_qty=10.0, filled_avg_price=451.0)
    client.submit_order_fn = submit_order
    client.get_order_by_id_fn = lambda order_id: FakeOrder(id=order_id, status=OrderStatus.FILLED, filled_qty=10.0, filled_avg_price=451.0)

    result = submit_entry_and_stop(client, candidate, _approved_decision(1.0), equity=10_000.0, guardrails=_guardrails(), sleep_fn=_no_sleep)

    assert result.submitted is True
    assert result.filled is True
    assert result.reason is None  # not a duplicate — the entry itself went through
    assert result.stop_order_submitted is True  # protected — via the pre-existing resting stop, not a new one
    assert len(client.submitted_orders) == 1  # only the entry — no duplicate entry, no duplicate stop


def test_submit_entry_and_stop_reraises_a_non_404_error_from_the_duplicate_check():
    # A genuine API failure (not a not-found) must NOT be silently treated
    # as either a duplicate or a clear-to-proceed — it propagates to the
    # caller (run_daily_execution_job()'s existing per-candidate
    # try/except), same fail-toward-alert convention as every other check
    # in this function.
    candidate = {"symbol": "SPY", "close": 450.0, "atr": 5.0, "timestamp": "2026-08-10T00:00:00"}
    client = FakeTradingClient()
    server_error = APIError(
        '{"code":50010000,"message":"internal server error"}',
        http_error=SimpleNamespace(response=SimpleNamespace(status_code=500)),
    )
    client.get_order_by_client_id_fn = lambda coid: (_ for _ in ()).throw(server_error)

    with pytest.raises(APIError):
        submit_entry_and_stop(client, candidate, _approved_decision(1.0), equity=10_000.0, guardrails=_guardrails(), sleep_fn=_no_sleep)

    assert client.submitted_orders == []


# --- capital partition: Track B sizes against its 70% sub-balance ----------
# (spec v53 §10.23, Milestone 1)

def _fill_at_requested_qty_client():
    """A FakeTradingClient whose entry order fills at exactly the qty
    submitted, so a test can read the sized qty straight off the entry
    MarketOrderRequest."""
    client = FakeTradingClient()

    def submit_order(req):
        if isinstance(req, StopOrderRequest):
            return FakeOrder(id="stop-1", status=OrderStatus.NEW, stop_price=req.stop_price)
        assert isinstance(req, MarketOrderRequest)
        return FakeOrder(id="entry-1", status=OrderStatus.FILLED, filled_qty=req.qty, filled_avg_price=450.0)

    client.submit_order_fn = submit_order
    client.get_order_by_id_fn = lambda oid: FakeOrder(id=oid, status=OrderStatus.FILLED, filled_qty=1.0, filled_avg_price=450.0)
    return client


def _entry_qty(client):
    market_orders = [o for o in client.submitted_orders if isinstance(o, MarketOrderRequest)]
    assert len(market_orders) == 1
    return market_orders[0].qty


def test_submit_entry_and_stop_qty_scales_linearly_with_the_equity_base_passed_in():
    # The retrofit passes Track B's 70% sub-balance as `equity` at the
    # call site (run_daily_execution_job), so a 7,000 base must produce
    # exactly 0.70x the qty a 10,000 base would.
    candidate = {"symbol": "SPY", "close": 450.0, "atr": 5.0, "timestamp": "2026-08-10T00:00:00"}

    full = _fill_at_requested_qty_client()
    submit_entry_and_stop(full, candidate, _approved_decision(1.0), equity=10_000.0, guardrails=_guardrails(), sleep_fn=_no_sleep)

    sub = _fill_at_requested_qty_client()
    submit_entry_and_stop(sub, candidate, _approved_decision(1.0), equity=7_000.0, guardrails=_guardrails(), sleep_fn=_no_sleep)

    # stop_distance = ATR_MULTIPLIER(3.0) * 5.0 = 15; qty = (equity * 1%) / 15,
    # rounded to 4 dp by submit_entry_and_stop().
    assert _entry_qty(full) == round(100.0 / 15.0, 4)
    assert _entry_qty(sub) == round(70.0 / 15.0, 4)
    # ~0.70x, modulo the 4-dp rounding of each qty independently.
    assert _entry_qty(sub) == pytest.approx(_entry_qty(full) * 0.70, abs=1e-4)


def test_run_daily_execution_job_sizes_new_entry_against_track_b_70pct_subbalance(monkeypatch):
    from src import halt_state
    from src.config import TRACK_B_ALLOCATION_PCT

    client = _fill_at_requested_qty_client()
    client.account = FakeAccount(equity=10_000.0, last_equity=10_000.0)
    client.portfolio_history_equity = [10_000.0]

    candidate = {"symbol": "SPY", "close": 450.0, "atr": 5.0, "timestamp": "2026-08-10T00:00:00"}

    monkeypatch.setattr(execution, "fetch_track_b_symbol_data", lambda universe: {"SPY": {"date_index": {"2026-08-10": 0}}})
    monkeypatch.setattr(execution, "protect_unprotected_fills", lambda *a, **k: [])
    monkeypatch.setattr(execution, "build_open_positions", lambda *a, **k: [])
    monkeypatch.setattr(execution, "_latest_shared_date", lambda sd: "2026-08-10")
    monkeypatch.setattr(execution, "generate_daily_candidates", lambda *a, **k: [candidate])
    monkeypatch.setattr(execution, "get_today_entry_count", lambda *a, **k: 0)
    monkeypatch.setattr(halt_state, "load_halt_state", lambda: halt_state.HaltState(halted=False))

    run_log = execution.run_daily_execution_job(trading_client=client, sleep_fn=_no_sleep)

    assert run_log["errors"] == []
    assert len(run_log["entries_submitted"]) == 1

    # stop_distance = ATR_MULTIPLIER(3.0) * 5.0 = 15.
    # risk budget = 1% of the 70% sub-balance (0.70 * 10,000 = 7,000) = 70.
    expected_qty = round(70.0 / 15.0, 4)
    assert _entry_qty(client) == expected_qty
    # and explicitly NOT the full-account-equity qty (1% of 10,000 = 100).
    assert _entry_qty(client) != round(100.0 / 15.0, 4)
    assert TRACK_B_ALLOCATION_PCT == 0.70  # the value this test's arithmetic assumes


# --- generate_daily_candidates: universe-order tie-break, skip open symbols -

def test_generate_daily_candidates_skips_symbols_already_open():
    dates = ["2026-08-10"]
    symbol_data = {
        "SPY": _series(dates, closes=[450], atrs=[5]),
        "QQQ": _series(dates, closes=[380], atrs=[4]),
    }
    symbol_data["SPY"]["entry_indices"] = {0}
    symbol_data["QQQ"]["entry_indices"] = {0}

    candidates = generate_daily_candidates(symbol_data, ["SPY", "QQQ"], open_symbols={"SPY"}, today="2026-08-10")

    assert [c["symbol"] for c in candidates] == ["QQQ"]


def test_generate_daily_candidates_preserves_universe_order_as_the_tie_break():
    dates = ["2026-08-10"]
    symbol_data = {
        "QQQ": _series(dates, closes=[380], atrs=[4]),
        "SPY": _series(dates, closes=[450], atrs=[5]),
    }
    symbol_data["SPY"]["entry_indices"] = {0}
    symbol_data["QQQ"]["entry_indices"] = {0}

    candidates = generate_daily_candidates(symbol_data, ["SPY", "QQQ"], open_symbols=set(), today="2026-08-10")

    assert [c["symbol"] for c in candidates] == ["SPY", "QQQ"]


# --- state builders: derived from Alpaca, no local DB -----------------------

def test_build_open_positions_derives_risk_from_the_real_resting_stop_order():
    client = FakeTradingClient()
    client.account = FakeAccount(equity=10_000.0, last_equity=10_000.0)
    client.positions = [FakePosition(symbol="SPY", qty=10.0, avg_entry_price=450.0, market_value=4_600.0)]

    def orders_by_request(filter):
        return [FakeOrder(symbol="SPY", status=OrderStatus.NEW, order_type=OrderType.STOP, stop_price=435.0, id="stop-1")]

    client.orders_by_request = orders_by_request

    positions = build_open_positions(client, universe=["SPY", "QQQ"])

    assert len(positions) == 1
    pos = positions[0]
    assert pos.symbol == "SPY"
    assert pos.stop_price == 435.0
    assert abs(pos.risk_amount - 10.0 * (450.0 - 435.0)) < 1e-9
    assert abs(pos.risk_pct - (150.0 / 10_000.0 * 100)) < 1e-9
    assert abs(pos.notional_pct_of_equity - 46.0) < 1e-9


def test_build_open_positions_ignores_symbols_outside_track_b_universe():
    client = FakeTradingClient()
    client.positions = [FakePosition(symbol="BTC/USD", qty=1.0, avg_entry_price=50_000.0, market_value=50_000.0)]

    positions = build_open_positions(client, universe=["SPY", "QQQ"])

    assert positions == []


def test_build_open_positions_excludes_a_position_with_no_resting_stop_found():
    client = FakeTradingClient()
    client.positions = [FakePosition(symbol="SPY", qty=10.0, avg_entry_price=450.0, market_value=4_600.0)]
    client.orders_by_request = lambda filter: []  # no resting stop order at all

    positions = build_open_positions(client, universe=["SPY"])

    assert positions == []


def test_build_account_state_uses_last_equity_as_day_start_equity_and_peak_from_history():
    client = FakeTradingClient()
    client.account = FakeAccount(equity=10_200.0, last_equity=10_000.0)
    client.portfolio_history_equity = [9_000.0, 9_500.0, 10_600.0, 10_100.0]

    account_state = build_account_state(client)

    assert account_state.equity == 10_200.0
    assert account_state.day_start_equity == 10_000.0
    assert account_state.peak_equity == 10_600.0  # max of history, not necessarily current equity


def test_build_account_state_peak_includes_current_equity_if_its_a_new_high():
    client = FakeTradingClient()
    client.account = FakeAccount(equity=11_000.0, last_equity=10_000.0)
    client.portfolio_history_equity = [9_000.0, 10_600.0]  # history hasn't caught up to today's new high yet

    account_state = build_account_state(client)

    assert account_state.peak_equity == 11_000.0


def test_get_today_entry_count_counts_buy_orders_returned_for_today():
    client = FakeTradingClient()
    client.orders_by_request = lambda filter: [FakeOrder(id="1"), FakeOrder(id="2"), FakeOrder(id="3")]

    count = get_today_entry_count(client, universe=["SPY", "QQQ"], today=datetime(2026, 8, 11).date())

    assert count == 3


# --- compute_stop_price_for_entry_date / protect_unprotected_fills ---------
# (module docstring's second flagged design gap: bridging the overnight
# submit-to-fill gap across separate job invocations.)

def test_compute_stop_price_for_entry_date_recomputes_purely_from_that_dates_own_data():
    dates = ["2026-08-03", "2026-08-04"]
    series = _series(dates, closes=[450.0, 455.0], atrs=[5.0, 6.0])

    stop = compute_stop_price_for_entry_date(series, "2026-08-03", atr_multiplier=3.0)

    assert stop == 450.0 - 3.0 * 5.0  # uses entry_date's OWN close/ATR, not a later day's


def test_compute_stop_price_for_entry_date_returns_none_when_date_not_in_series():
    dates = ["2026-08-04"]
    series = _series(dates, closes=[455.0], atrs=[6.0])
    assert compute_stop_price_for_entry_date(series, "2026-08-03") is None


def test_protect_unprotected_fills_finds_and_protects_a_filled_position_with_no_stop(captured_telegram_messages):
    dates = ["2026-08-10", "2026-08-11"]
    symbol_data = {"SPY": _series(dates, closes=[450.0, 452.0], atrs=[5.0, 5.0])}

    client = FakeTradingClient()
    client.positions = [FakePosition(symbol="SPY", qty=10.0, avg_entry_price=451.0, market_value=4_520.0)]
    # No resting stop order found (empty orders list satisfies BOTH the
    # "find resting stop" lookup, which must return none, and the
    # "find entry date" lookup for CLOSED buy orders below).
    entry_order = FakeOrder(symbol="SPY", status=OrderStatus.FILLED, filled_qty=10.0,
                             filled_avg_price=451.0, filled_at=datetime(2026, 8, 10, 15, 0, tzinfo=timezone.utc))

    def orders_by_request(filter):
        if filter.status.value == "open":
            return []  # no resting stop
        return [entry_order]  # closed buy order history

    client.orders_by_request = orders_by_request
    client.submit_order_fn = lambda req: FakeOrder(id="stop-1", status=OrderStatus.NEW, stop_price=req.stop_price)

    protected = protect_unprotected_fills(client, ["SPY"], symbol_data, sleep_fn=_no_sleep)

    assert protected == ["SPY"]
    assert len(client.submitted_orders) == 1
    submitted_stop_price = client.submitted_orders[0].stop_price
    assert submitted_stop_price == 450.0 - ATR_MULTIPLIER * 5.0  # anchored to the entry date (08-10), not today (08-11)
    assert captured_telegram_messages == []  # succeeded, no alert needed


def test_protect_unprotected_fills_skips_positions_that_already_have_a_stop():
    symbol_data = {"SPY": _series(["2026-08-10"], closes=[450.0], atrs=[5.0])}
    client = FakeTradingClient()
    client.positions = [FakePosition(symbol="SPY", qty=10.0, avg_entry_price=451.0, market_value=4_520.0)]
    client.orders_by_request = lambda filter: [FakeOrder(symbol="SPY", status=OrderStatus.NEW, order_type=OrderType.STOP, stop_price=435.0)]

    protected = protect_unprotected_fills(client, ["SPY"], symbol_data, sleep_fn=_no_sleep)

    assert protected == []
    assert client.submitted_orders == []


def test_protect_unprotected_fills_alerts_when_stop_price_cannot_be_recomputed(captured_telegram_messages):
    # No price history available for this symbol at all (e.g. outside the lookback window) — must alert, not silently skip.
    client = FakeTradingClient()
    client.positions = [FakePosition(symbol="SPY", qty=10.0, avg_entry_price=451.0, market_value=4_520.0)]
    client.orders_by_request = lambda filter: []  # no resting stop, and no closed buy-order history either

    protected = protect_unprotected_fills(client, ["SPY"], symbol_data={}, sleep_fn=_no_sleep)

    assert protected == []
    urgent = [m for m in captured_telegram_messages if "URGENT" in m and "UNPROTECTED" in m]
    assert len(urgent) == 1
    assert "SPY" in urgent[0]


# --- fill_listener.py milestone (spec v33 §10.5): client_order_id stop-price
# handoff, has_resting_protective_stop() extraction, submit_or_resize_stop_
# order_with_retry() -----------------------------------------------------

def test_encode_client_order_id_matches_the_locked_design_example():
    # Locked design's own worked example: tb-SPY-20260812-45823.
    assert encode_client_order_id("SPY", "2026-08-12", 458.23) == "tb-SPY-20260812-45823"


def test_encode_decode_client_order_id_round_trip_three_letter_symbol():
    coid = encode_client_order_id("SPY", "2026-08-10", 435.0)
    decoded = decode_client_order_id(coid)
    assert decoded == {"symbol": "SPY", "signal_date": "2026-08-10", "stop_price": 435.0}


def test_encode_decode_client_order_id_round_trip_longer_symbol():
    # No current Track B symbol is longer than 3 letters, but the format
    # must not assume a fixed symbol length.
    coid = encode_client_order_id("GOOGL", "2026-08-10", 120.5)
    decoded = decode_client_order_id(coid)
    assert decoded == {"symbol": "GOOGL", "signal_date": "2026-08-10", "stop_price": 120.5}


def test_encode_decode_client_order_id_round_trip_stop_price_without_cents():
    coid = encode_client_order_id("QQQ", "2026-08-10", 400.0)
    assert coid == "tb-QQQ-20260810-40000"
    assert decode_client_order_id(coid)["stop_price"] == 400.0


def test_encode_decode_client_order_id_round_trip_stop_price_with_cents():
    coid = encode_client_order_id("QQQ", "2026-08-10", 399.99)
    assert coid == "tb-QQQ-20260810-39999"
    assert decode_client_order_id(coid)["stop_price"] == 399.99


def test_decode_client_order_id_returns_none_for_a_non_matching_id():
    assert decode_client_order_id("some-manual-test-order") is None
    assert decode_client_order_id("tb-SPY-2026081-45823") is None  # short date
    assert decode_client_order_id(None) is None
    assert decode_client_order_id("") is None


def test_submit_entry_and_stop_encodes_client_order_id_on_the_entry_order():
    candidate = {"symbol": "SPY", "close": 450.0, "atr": 5.0, "timestamp": "2026-08-10T00:00:00"}
    client = FakeTradingClient()
    client.submit_order_fn = lambda req: FakeOrder(id="entry-1", status=OrderStatus.NEW, filled_qty=0.0, filled_avg_price=None)
    client.get_order_by_id_fn = lambda order_id: FakeOrder(id=order_id, status=OrderStatus.NEW, filled_qty=0.0, filled_avg_price=None)

    submit_entry_and_stop(client, candidate, _approved_decision(1.0), equity=10_000.0, guardrails=_guardrails(),
                           sleep_fn=_no_sleep, poll_timeout_seconds=0)

    entry_request = client.submitted_orders[0]
    expected_stop_price = 450.0 - ATR_MULTIPLIER * 5.0
    assert entry_request.client_order_id == encode_client_order_id("SPY", "2026-08-10", expected_stop_price)


def test_has_resting_protective_stop_true_when_a_stop_order_is_open():
    client = FakeTradingClient()
    client.orders_by_request = lambda filter: [FakeOrder(symbol="SPY", status=OrderStatus.NEW, order_type=OrderType.STOP, stop_price=435.0)]
    assert has_resting_protective_stop(client, "SPY") is True


def test_has_resting_protective_stop_false_when_no_open_orders():
    client = FakeTradingClient()
    client.orders_by_request = lambda filter: []
    assert has_resting_protective_stop(client, "SPY") is False


def test_protect_unprotected_fills_and_listener_share_the_same_idempotency_check():
    # Regression guard: protect_unprotected_fills() must call the SAME
    # function fill_listener.py's handler calls (has_resting_protective_
    # stop), not a private reimplementation — a signature-level proof
    # they can't silently disagree, same category of fix as the v32
    # MAX_SINGLE_POSITION_NOTIONAL_PCT drift bug.
    import inspect
    from src import execution
    source = inspect.getsource(execution.protect_unprotected_fills)
    assert "has_resting_protective_stop(" in source


# --- submit_or_resize_stop_order_with_retry: TOP-UP model (fix-up,
# replaces the original PATCH-replace-qty design — ReplaceOrderRequest.qty
# is Optional[int] in the installed SDK, so a fractional resize can't go
# through PATCH at all; StopOrderRequest.qty IS fractional-capable and
# Alpaca's fractional-trading docs confirm stop orders are supported
# directly) --------------------------------------------------------------

def test_submit_or_resize_stop_order_with_retry_submits_when_no_existing_stop():
    client = FakeTradingClient()
    client.orders_by_request = lambda filter: []  # no resting stop
    client.submit_order_fn = lambda req: FakeOrder(id="stop-1", status=OrderStatus.NEW, stop_price=req.stop_price)

    order, qty_submitted = submit_or_resize_stop_order_with_retry(client, "SPY", 10.0, 435.0, sleep_fn=_no_sleep)

    assert order.id == "stop-1"
    assert qty_submitted == 10.0
    assert len(client.submitted_orders) == 1
    assert isinstance(client.submitted_orders[0], StopOrderRequest)
    assert client.submitted_orders[0].qty == 10.0


def test_submit_or_resize_stop_order_with_retry_is_a_noop_when_qty_already_covered():
    client = FakeTradingClient()
    client.orders_by_request = lambda filter: [FakeOrder(id="stop-1", symbol="SPY", status=OrderStatus.NEW, order_type=OrderType.STOP, qty=10.0, stop_price=435.0)]

    order, qty_submitted = submit_or_resize_stop_order_with_retry(client, "SPY", 10.0, 435.0, sleep_fn=_no_sleep)

    assert order.id == "stop-1"
    assert qty_submitted == 0.0
    assert client.submitted_orders == []  # no new order submitted
    assert client.replace_calls == []  # replace path no longer exists at all


def test_submit_or_resize_stop_order_with_retry_tops_up_with_an_additive_stop_for_the_increment_only():
    client = FakeTradingClient()
    # 5.0 already resting (a first partial fill); a second partial takes
    # the cumulative fill to 10.0 -> the increment (5.0) must be submitted
    # as a NEW, SEPARATE stop order, never a replace of the first.
    client.orders_by_request = lambda filter: [FakeOrder(id="stop-1", symbol="SPY", status=OrderStatus.NEW, order_type=OrderType.STOP, qty=5.0, stop_price=435.0)]
    client.submit_order_fn = lambda req: FakeOrder(id="stop-2", status=OrderStatus.NEW, stop_price=req.stop_price)

    order, qty_submitted = submit_or_resize_stop_order_with_retry(client, "SPY", 10.0, 435.0, sleep_fn=_no_sleep)

    assert order.id == "stop-2"
    assert qty_submitted == 5.0
    assert client.replace_calls == []  # never a replace
    assert len(client.submitted_orders) == 1  # exactly one NEW order — the increment
    assert client.submitted_orders[0].qty == 5.0
    assert client.submitted_orders[0].stop_price == 435.0  # SAME stop price as the first (accepted: two resting stops at one price)


def test_submit_or_resize_stop_order_with_retry_supports_a_fractional_topup_increment():
    # This is the direct proof the fix-up actually resolves the original
    # ReplaceOrderRequest.qty=Optional[int] limitation: a fractional
    # increment must now succeed, not fail toward alert.
    client = FakeTradingClient()
    client.orders_by_request = lambda filter: [FakeOrder(id="stop-1", symbol="SPY", status=OrderStatus.NEW, order_type=OrderType.STOP, qty=5.25, stop_price=435.0)]
    client.submit_order_fn = lambda req: FakeOrder(id="stop-2", status=OrderStatus.NEW, stop_price=req.stop_price, qty=req.qty)

    order, qty_submitted = submit_or_resize_stop_order_with_retry(client, "SPY", 10.7, 435.0, sleep_fn=_no_sleep)

    assert order is not None
    assert abs(qty_submitted - 5.45) < 1e-9
    assert abs(client.submitted_orders[0].qty - 5.45) < 1e-9


def test_submit_or_resize_stop_order_with_retry_exhausts_retries_and_alerts_on_topup_failure(captured_telegram_messages):
    client = FakeTradingClient()
    client.orders_by_request = lambda filter: [FakeOrder(id="stop-1", symbol="SPY", status=OrderStatus.NEW, order_type=OrderType.STOP, qty=5.0, stop_price=435.0)]
    client.submit_order_fn = lambda req: (_ for _ in ()).throw(RuntimeError("broker rejected stop order"))

    order, qty_submitted = submit_or_resize_stop_order_with_retry(client, "SPY", 10.0, 435.0, sleep_fn=_no_sleep)

    assert order is None
    assert qty_submitted == 0.0
    urgent = [m for m in captured_telegram_messages if "URGENT" in m and "UNPROTECTED" in m]
    assert len(urgent) == 1
    assert "SPY" in urgent[0]


# --- send_daily_heartbeat (systemd-units milestone, spec v34 §10.6) ---

class FakeRequestsModule:
    def __init__(self, raise_exc=None):
        self.raise_exc = raise_exc
        self.get_calls = []

    def get(self, url, timeout=None):
        self.get_calls.append((url, timeout))
        if self.raise_exc is not None:
            raise self.raise_exc
        return SimpleNamespace(status_code=200)


def test_send_daily_heartbeat_pings_when_run_log_has_no_errors():
    fake_requests = FakeRequestsModule()

    result = send_daily_heartbeat({"errors": []}, heartbeat_url="https://uptimerobot.example/hb", requests_module=fake_requests)

    assert result is True
    assert fake_requests.get_calls == [("https://uptimerobot.example/hb", 10)]


def test_send_daily_heartbeat_does_not_ping_when_run_log_has_errors():
    fake_requests = FakeRequestsModule()

    result = send_daily_heartbeat({"errors": [{"step": "ratchet", "error": "boom"}]}, heartbeat_url="https://uptimerobot.example/hb", requests_module=fake_requests)

    assert result is False
    assert fake_requests.get_calls == []


def test_send_daily_heartbeat_treats_a_halted_but_error_free_run_as_success():
    fake_requests = FakeRequestsModule()

    result = send_daily_heartbeat({"errors": [], "halted": True, "halt_reason": "daily_loss_limit"}, heartbeat_url="https://uptimerobot.example/hb", requests_module=fake_requests)

    assert result is True
    assert len(fake_requests.get_calls) == 1


def test_send_daily_heartbeat_skips_without_raising_when_no_url_configured(monkeypatch):
    monkeypatch.delenv("HEALTHCHECKS_DAILY_HEARTBEAT_URL", raising=False)
    fake_requests = FakeRequestsModule()

    result = send_daily_heartbeat({"errors": []}, requests_module=fake_requests)

    assert result is False
    assert fake_requests.get_calls == []


def test_send_daily_heartbeat_falls_back_to_env_when_no_url_arg_given(monkeypatch):
    monkeypatch.setenv("HEALTHCHECKS_DAILY_HEARTBEAT_URL", "https://uptimerobot.example/from-env")
    fake_requests = FakeRequestsModule()

    result = send_daily_heartbeat({"errors": []}, requests_module=fake_requests)

    assert result is True
    assert fake_requests.get_calls == [("https://uptimerobot.example/from-env", 10)]


def test_send_daily_heartbeat_swallows_a_network_failure_and_returns_false():
    fake_requests = FakeRequestsModule(raise_exc=RuntimeError("connection refused"))

    result = send_daily_heartbeat({"errors": []}, heartbeat_url="https://uptimerobot.example/hb", requests_module=fake_requests)

    assert result is False
    assert len(fake_requests.get_calls) == 1


# --- fetch_track_b_symbol_data: per-symbol DEBUG fetch logging (spec v42 §10.11) ---

def test_fetch_track_b_symbol_data_logs_bar_count_and_date_range_at_debug(monkeypatch, caplog):
    dates = ["2026-08-01", "2026-08-02", "2026-08-03"]
    series = _series(dates, closes=[100, 101, 102], atrs=[1, 1, 1])
    monkeypatch.setattr(execution, "build_symbol_series", lambda symbol, start, end: series)

    with caplog.at_level("DEBUG", logger="src.execution"):
        symbol_data = fetch_track_b_symbol_data(universe=["SPY"])

    assert symbol_data == {"SPY": series}
    assert "[SPY] fetch: 3 bars, range 2026-08-01 to 2026-08-03" in caplog.messages


def test_fetch_track_b_symbol_data_logs_zero_bars_returned_at_debug(monkeypatch, caplog):
    monkeypatch.setattr(execution, "build_symbol_series", lambda symbol, start, end: None)

    with caplog.at_level("DEBUG", logger="src.execution"):
        symbol_data = fetch_track_b_symbol_data(universe=["QQQ"])

    assert symbol_data == {}  # unchanged behavior: a 0-bar symbol is not added to symbol_data
    assert "[QQQ] fetch: 0 bars returned" in caplog.messages


def test_fetch_track_b_symbol_data_emits_no_debug_lines_when_level_is_info(monkeypatch, caplog):
    dates = ["2026-08-01"]
    series = _series(dates, closes=[100], atrs=[1])
    monkeypatch.setattr(execution, "build_symbol_series", lambda symbol, start, end: series)

    with caplog.at_level("INFO", logger="src.execution"):
        fetch_track_b_symbol_data(universe=["SPY"])

    assert caplog.records == []


# --- generate_daily_candidates: per-symbol DEBUG signal logging (spec v42 §10.11) ---

def test_generate_daily_candidates_logs_debug_signal_line_with_donchian_bands(caplog):
    dates = ["2026-08-10"]
    symbol_data = {
        "SPY": _series(dates, closes=[450], atrs=[5]),
        "QQQ": _series(dates, closes=[380], atrs=[4]),
    }
    symbol_data["SPY"]["entry_indices"] = {0}
    symbol_data["SPY"]["upper"] = [440]
    symbol_data["SPY"]["lower"] = [400]
    symbol_data["QQQ"]["entry_indices"] = set()
    symbol_data["QQQ"]["upper"] = [390]
    symbol_data["QQQ"]["lower"] = [350]

    with caplog.at_level("DEBUG", logger="src.execution"):
        candidates = generate_daily_candidates(symbol_data, ["SPY", "QQQ"], open_symbols=set(), today="2026-08-10")

    assert [c["symbol"] for c in candidates] == ["SPY"]
    assert "[SPY] signal: close=450, donchian_upper=440, donchian_lower=400, signal=entry_signal" in caplog.messages
    assert "[QQQ] signal: close=380, donchian_upper=390, donchian_lower=350, signal=no_signal" in caplog.messages


def test_generate_daily_candidates_logs_debug_signal_line_for_a_symbol_with_no_data(caplog):
    with caplog.at_level("DEBUG", logger="src.execution"):
        candidates = generate_daily_candidates({}, ["SPY"], open_symbols=set(), today="2026-08-10")

    assert candidates == []
    assert "[SPY] signal: no data for 2026-08-10" in caplog.messages


def test_generate_daily_candidates_logs_debug_signal_line_even_when_symbol_already_open(caplog):
    # Requirement (b), spec v42 §10.11: the DEBUG signal-check is computed
    # for every universe symbol regardless of open-position status — the
    # existing open_symbols skip governs candidate generation only.
    dates = ["2026-08-10"]
    symbol_data = {"SPY": _series(dates, closes=[450], atrs=[5])}
    symbol_data["SPY"]["entry_indices"] = {0}
    symbol_data["SPY"]["upper"] = [440]
    symbol_data["SPY"]["lower"] = [400]

    with caplog.at_level("DEBUG", logger="src.execution"):
        candidates = generate_daily_candidates(symbol_data, ["SPY"], open_symbols={"SPY"}, today="2026-08-10")

    assert candidates == []  # still excluded from candidates — unchanged behavior
    assert "[SPY] signal: close=450, donchian_upper=440, donchian_lower=400, signal=entry_signal" in caplog.messages


def test_generate_daily_candidates_emits_no_debug_lines_when_level_is_info(caplog):
    dates = ["2026-08-10"]
    symbol_data = {"SPY": _series(dates, closes=[450], atrs=[5])}
    symbol_data["SPY"]["entry_indices"] = {0}

    with caplog.at_level("INFO", logger="src.execution"):
        generate_daily_candidates(symbol_data, ["SPY"], open_symbols=set(), today="2026-08-10")

    assert caplog.records == []


# --- main(): LOG_LEVEL wiring + byte-for-byte INFO summary-line regression (spec v42 §10.11) ---

def test_main_configures_logging_from_get_log_level_and_logs_unchanged_summary_line(monkeypatch, caplog):
    basic_config_calls = []
    monkeypatch.setattr(execution.logging, "basicConfig", lambda **kwargs: basic_config_calls.append(kwargs))
    monkeypatch.setattr(execution, "get_log_level", lambda: "DEBUG")

    fixed_run_log = {"date": "2026-08-25", "errors": [], "halted": False}
    monkeypatch.setattr(execution, "run_daily_execution_job", lambda: fixed_run_log)
    heartbeat_calls = []
    monkeypatch.setattr(execution, "send_daily_heartbeat", lambda run_log: heartbeat_calls.append(run_log))

    with caplog.at_level("INFO", logger="src.execution"):
        main()

    # LOG_LEVEL wiring: get_log_level()'s return value reaches basicConfig() unchanged.
    assert basic_config_calls == [{"level": "DEBUG", "format": "%(asctime)s %(levelname)s %(message)s"}]
    assert heartbeat_calls == [fixed_run_log]

    # Byte-for-byte regression: the literal format template and args are pinned,
    # not just today's rendered string, so a future accidental format change fails loudly.
    info_records = [r for r in caplog.records if r.levelname == "INFO"]
    assert len(info_records) == 1
    assert info_records[0].msg == "run_daily_execution_job() result: %s"
    # logging.Logger._log() special-cases a single Mapping arg, storing it
    # directly on record.args rather than wrapping it in a 1-tuple — this is
    # pre-existing %-formatting behavior of the unchanged log.info() call,
    # not something introduced by this milestone.
    assert info_records[0].args == fixed_run_log
    assert info_records[0].getMessage() == f"run_daily_execution_job() result: {fixed_run_log}"
