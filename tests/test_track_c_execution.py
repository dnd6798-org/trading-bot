"""
src/track_c_execution.py (spec v59 §10.29, Milestone 4) — Track C's
live DMSR rebalance job. All tests against a hand-built fake trading
client and synthetic symbol_data (no network), an isolated throwaway
track_positions ledger + track_c halt file, and captured Telegram.

Covers the brief's required test list:
  - halt-gating (no orders, no heal),
  - no-op on a non-rebalance day (heal still runs, zero orders),
  - risk-on rebalance: correct sell/buy sets + allocated_capital / 3 sizing,
  - risk-off transition: AGG at 100% of allocated_capital, not / 3,
  - THE SAFETY TEST: sell qty sourced from the ledger, proven against a
    mocked Alpaca combined position LARGER than the ledger entry,
  - reconciliation Telegram alert on a leg that deviates from target.
Plus the send_track_c_heartbeat() best-effort behaviour.
"""
from types import SimpleNamespace

import pytest

from alpaca.common.exceptions import APIError
from alpaca.trading.enums import OrderSide, OrderStatus

from src import dmsr_signal, halt_state, telegram_bot, track_c_execution, track_positions
from src.data_ingestion import Candle


# --- fixtures ---------------------------------------------------------

@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setattr(track_positions, "_STATE_PATH", str(tmp_path / "track_positions_state.json"))
    monkeypatch.setattr(halt_state, "_TRACK_C_STATE_PATH", str(tmp_path / "track_c_halt_state.json"))
    monkeypatch.setattr(halt_state, "_STATE_PATH", str(tmp_path / "halt_state.json"))


@pytest.fixture(autouse=True)
def captured_telegram(monkeypatch):
    sent = []
    monkeypatch.setattr(telegram_bot, "send_message", lambda text: sent.append(text))
    return sent


def _no_sleep(_seconds):
    pass


# --- fakes -----------------------------------------------------------

def _not_found_api_error(client_order_id="x"):
    return APIError(
        f'{{"code":40410000,"message":"order not found for {client_order_id}"}}',
        http_error=SimpleNamespace(response=SimpleNamespace(status_code=404)),
    )


class FakeOrder:
    def __init__(self, id="o1", status=OrderStatus.FILLED, filled_qty=0.0):
        self.id = id
        self.status = status
        self.filled_qty = filled_qty


def _tc_order(symbol, side, filled_qty, day="20250901"):
    return SimpleNamespace(
        symbol=symbol, side=side, filled_qty=str(filled_qty),
        client_order_id=f"tc-{symbol}-{day}",
    )


class FakeTradingClient:
    def __init__(self, equity=10_000.0, positions=None, tc_orders=None):
        self.account = SimpleNamespace(equity=equity, last_equity=equity)
        self._positions = [SimpleNamespace(symbol=s, qty=str(q)) for s, q in (positions or {}).items()]
        self._tc_orders = list(tc_orders or [])
        self.submitted = []
        self.poll_status = OrderStatus.FILLED
        self.get_order_by_client_id_fn = None

    def get_account(self):
        return self.account

    def get_all_positions(self):
        return list(self._positions)

    def get_orders(self, filter=None):
        wanted = set(getattr(filter, "symbols", None) or [])
        return [o for o in self._tc_orders if not wanted or o.symbol in wanted]

    def get_order_by_client_id(self, client_order_id):
        if self.get_order_by_client_id_fn is not None:
            return self.get_order_by_client_id_fn(client_order_id)
        raise _not_found_api_error(client_order_id)

    def submit_order(self, request):
        self.submitted.append(request)
        n = len(self.submitted)
        qty = float(getattr(request, "qty", None) or 0.0)
        return FakeOrder(id=f"ord-{n}", status=self.poll_status, filled_qty=qty)

    def get_order_by_id(self, order_id, filter=None):
        return FakeOrder(id=order_id, status=self.poll_status,
                         filled_qty=1.0 if self.poll_status == OrderStatus.FILLED else 0.0)


# --- synthetic symbol_data ------------------------------------------

MONTH_ENDS = [
    "2025-01-31", "2025-02-28", "2025-03-31", "2025-04-30", "2025-05-30", "2025-06-30",
    "2025-07-31", "2025-08-29", "2025-09-30", "2025-10-31", "2025-11-28", "2025-12-31", "2026-01-30",
]
REBALANCE_TAIL = ("2026-02-02",)      # calendar[-2] = 2026-01-30 (a month-end) -> is_rebalance_day True
NOOP_TAIL = ("2026-02-02", "2026-02-03")  # calendar[-2] = 2026-02-02 -> not a month-end


def _one_series(symbol, last_close, tail_dates):
    dated = [(d, 100.0) for d in MONTH_ENDS[:-1]] + [(MONTH_ENDS[-1], last_close)]
    dated += [(d, last_close) for d in tail_dates]
    candles = [Candle(symbol, f"{d}T00:00:00+00:00", open=c, high=c, low=c, close=c, volume=1000) for d, c in dated]
    return {"symbol": symbol, "candles": candles, "date_index": {c.timestamp[:10]: i for i, c in enumerate(candles)}}


def _symbol_data(spy_12m_return=0.10, sector_12m_returns=None, tail_dates=REBALANCE_TAIL):
    sr = sector_12m_returns or {}
    data = {"SPY": _one_series("SPY", 100.0 * (1 + spy_12m_return), tail_dates)}
    for i, s in enumerate(dmsr_signal.SECTOR_UNIVERSE):
        r = sr.get(s, -0.5 + i * 0.01)  # distinct, deterministic default
        data[s] = _one_series(s, 100.0 * (1 + r), tail_dates)
    data["AGG"] = _one_series("AGG", 100.0, tail_dates)
    return data


def _patch_fetch(monkeypatch, data):
    monkeypatch.setattr(track_c_execution, "fetch_track_c_symbol_data", lambda *a, **k: data)


# --- halt gating -------------------------------------------------------

def test_halt_gating_submits_nothing_and_does_not_heal(monkeypatch):
    halt_state.set_track_c_halt("manual test — verifying halt")
    client = FakeTradingClient()
    heal_calls, fetch_calls = [], []
    monkeypatch.setattr(track_positions, "heal_track_c_ownership_ledger",
                        lambda *a, **k: heal_calls.append(a) or {})
    monkeypatch.setattr(track_c_execution, "fetch_track_c_symbol_data",
                        lambda *a, **k: fetch_calls.append(1) or {})

    result = track_c_execution.run_track_c_execution_job(client, sleep_fn=_no_sleep)

    assert result["halted"] is True
    assert result["halt_reason"] == "manual test — verifying halt"
    assert client.submitted == []
    assert heal_calls == []
    assert fetch_calls == []


# --- no-op on a non-rebalance day -----------------------------------

def test_noop_non_rebalance_day_still_heals_but_submits_nothing(monkeypatch):
    client = FakeTradingClient()
    _patch_fetch(monkeypatch, _symbol_data(tail_dates=NOOP_TAIL))
    heal_calls = []
    real_heal = track_positions.heal_track_c_ownership_ledger
    monkeypatch.setattr(track_positions, "heal_track_c_ownership_ledger",
                        lambda tc, uni: (heal_calls.append(1), real_heal(tc, uni))[1])

    result = track_c_execution.run_track_c_execution_job(client, sleep_fn=_no_sleep)

    assert result["rebalance_day"] is False
    assert client.submitted == []
    assert len(heal_calls) == 2  # start-of-run + end-of-run
    assert result["errors"] == []


# --- risk-on rebalance --------------------------------------------

def test_risk_on_rebalance_sells_dropped_names_and_buys_new_names_sized_by_thirds(monkeypatch):
    client = FakeTradingClient(equity=10_000.0)
    # Held: XLP, XLU, XLB (via tc- order history). Top-5 sectors are
    # XLK/XLV/XLE/XLF/XLY; the held names rank last -> all sold, clean
    # top-3 bought.
    client._tc_orders = [_tc_order(s, OrderSide.BUY, 3.0) for s in ("XLP", "XLU", "XLB")]
    sr = {s: -0.9 for s in dmsr_signal.SECTOR_UNIVERSE}
    sr.update({"XLK": 0.5, "XLV": 0.4, "XLE": 0.3, "XLF": 0.2, "XLY": 0.1})
    _patch_fetch(monkeypatch, _symbol_data(spy_12m_return=0.15, sector_12m_returns=sr))

    result = track_c_execution.run_track_c_execution_job(client, sleep_fn=_no_sleep)

    assert result["rebalance_day"] is True
    assert result["risk_off"] is False
    assert set(result["current_holdings"]) == {"XLP", "XLU", "XLB"}
    assert set(result["target"]) == {"XLK", "XLV", "XLE"}

    sells = {r["symbol"]: r for r in result["sold"] if not r.get("skipped")}
    buys = {r["symbol"]: r for r in result["bought"]}
    assert set(sells) == {"XLP", "XLU", "XLB"}
    assert set(buys) == {"XLK", "XLV", "XLE"}

    # allocated = 0.30 * 10_000 = 3_000 -> 1_000 per new name
    assert all(r["notional"] == 1000.0 for r in buys.values())
    assert all(r["qty"] == 3.0 for r in sells.values())

    sell_reqs = [r for r in client.submitted if r.side == OrderSide.SELL]
    buy_reqs = [r for r in client.submitted if r.side == OrderSide.BUY]
    assert all(r.qty == 3.0 and r.notional is None for r in sell_reqs)
    assert all(r.notional == 1000.0 and r.qty is None for r in buy_reqs)
    assert all(r.client_order_id.startswith("tc-") for r in client.submitted)


# --- risk-off transition -----------------------------------------

def test_risk_off_transition_buys_agg_at_full_allocated_capital_not_a_third(monkeypatch):
    client = FakeTradingClient(equity=10_000.0)
    client._tc_orders = [_tc_order(s, OrderSide.BUY, 2.0) for s in ("XLK", "XLV", "XLE")]
    sr = {s: 0.1 for s in dmsr_signal.SECTOR_UNIVERSE}
    _patch_fetch(monkeypatch, _symbol_data(spy_12m_return=-0.05, sector_12m_returns=sr))

    result = track_c_execution.run_track_c_execution_job(client, sleep_fn=_no_sleep)

    assert result["risk_off"] is True
    assert result["target"] == ["AGG"]
    assert {r["symbol"] for r in result["sold"] if not r.get("skipped")} == {"XLK", "XLV", "XLE"}
    assert [r["symbol"] for r in result["bought"]] == ["AGG"]
    assert result["bought"][0]["notional"] == 3000.0  # 100% of allocated, NOT 3000/3

    buy_req = [r for r in client.submitted if r.side == OrderSide.BUY]
    assert len(buy_req) == 1
    assert buy_req[0].symbol == "AGG" and buy_req[0].notional == 3000.0


# --- THE SAFETY TEST -------------------------------------------------

def test_sell_quantity_comes_from_the_ledger_never_from_alpacas_combined_position(monkeypatch):
    """
    Track C's ledger says it owns 5 AGG shares. Alpaca reports a COMBINED
    AGG position of 25 (20 are Track B's). A risk-ON rebalance sells AGG
    (held from a prior risk-off month, never in the sector ranking). The
    submitted SELL must be for 5 shares (the ledger), NOT 25 (Alpaca) —
    selling 25 would liquidate Track B's holding.
    """
    client = FakeTradingClient(equity=10_000.0, positions={"AGG": 25.0})
    client._tc_orders = [_tc_order("AGG", OrderSide.BUY, 5.0)]
    sr = {s: 0.1 for s in dmsr_signal.SECTOR_UNIVERSE}
    _patch_fetch(monkeypatch, _symbol_data(spy_12m_return=0.20, sector_12m_returns=sr))

    result = track_c_execution.run_track_c_execution_job(client, sleep_fn=_no_sleep)

    assert result["risk_off"] is False
    assert result["current_holdings"] == ["AGG"]
    assert "AGG" not in result["target"]

    agg_sells = [r for r in client.submitted if r.side == OrderSide.SELL and r.symbol == "AGG"]
    assert len(agg_sells) == 1
    assert agg_sells[0].qty == 5.0          # ledger figure
    assert agg_sells[0].qty != 25.0         # NOT Alpaca's combined position
    assert result["sold"][0]["symbol"] == "AGG" and result["sold"][0]["qty"] == 5.0


# --- reconciliation alert -----------------------------------------

def test_reconcile_alerts_when_a_resulting_position_deviates_from_target(monkeypatch, captured_telegram):
    client = FakeTradingClient(equity=10_000.0)
    sr = {s: -0.9 for s in dmsr_signal.SECTOR_UNIVERSE}
    sr.update({"XLK": 0.5, "XLV": 0.4, "XLE": 0.3})
    _patch_fetch(monkeypatch, _symbol_data(spy_12m_return=0.15, sector_12m_returns=sr))
    # After the "rebalance" Alpaca shows only 2 of the 3 target names.
    client._positions = [SimpleNamespace(symbol="XLK", qty="2"), SimpleNamespace(symbol="XLV", qty="2")]

    result = track_c_execution.run_track_c_execution_job(client, sleep_fn=_no_sleep)

    assert set(result["target"]) == {"XLK", "XLV", "XLE"}
    assert len(result["reconcile"]) == 1
    assert "XLE" in result["reconcile"][0]
    assert any("post-rebalance reconciliation" in m for m in captured_telegram)


# --- heartbeat ---------------------------------------------------------

def test_send_track_c_heartbeat_skips_when_url_unset(monkeypatch):
    monkeypatch.delenv("HEALTHCHECKS_TRACK_C_HEARTBEAT_URL", raising=False)
    assert track_c_execution.send_track_c_heartbeat({"errors": []}) is False


def test_send_track_c_heartbeat_skips_when_run_had_errors():
    calls = []
    fake_requests = SimpleNamespace(get=lambda url, timeout: calls.append(url))
    ok = track_c_execution.send_track_c_heartbeat(
        {"errors": [{"step": "x"}]}, heartbeat_url="http://hc.example/x", requests_module=fake_requests
    )
    assert ok is False and calls == []


def test_send_track_c_heartbeat_pings_on_a_clean_run():
    calls = []
    fake_requests = SimpleNamespace(get=lambda url, timeout: calls.append(url))
    ok = track_c_execution.send_track_c_heartbeat(
        {"errors": []}, heartbeat_url="http://hc.example/x", requests_module=fake_requests
    )
    assert ok is True and calls == ["http://hc.example/x"]
