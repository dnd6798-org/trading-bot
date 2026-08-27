"""
src/track_positions.py (spec v55 §10.25, Milestone 2) — the position-
ownership ledger and its reconciliation check.

Covers, against an isolated throwaway JSON file and a minimal fake
trading client (no network):
  - the ledger read/write/adjust primitives (load_ledger, get/set/adjust_
    track_qty), including the floor-at-0 and near-zero-key-removal rules;
  - reconcile_symbol() on a match (no side effects) and on a deliberate
    mismatch (URGENT Telegram alert + Track C halt via halt_state, and
    NOT Track B's halt — the two are independent).

Track C has no execution code yet (that's Milestone 3), so track_c-side
ledger state is set directly here with fake data, per the brief.
"""
from types import SimpleNamespace

import pytest

from src import halt_state, telegram_bot, track_positions


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


class _FakeTradingClient:
    def __init__(self, positions):
        # positions: dict {symbol: qty}
        self._positions = [SimpleNamespace(symbol=s, qty=str(q)) for s, q in positions.items()]

    def get_all_positions(self):
        return list(self._positions)


# --- ledger primitives ----------------------------------------------------

def test_load_ledger_defaults_to_empty_shape_when_no_file():
    assert track_positions.load_ledger() == {"track_b": {}, "track_c": {}}


def test_set_and_get_track_qty_round_trip_for_both_tracks():
    track_positions.set_track_qty("track_b", "SPY", 10.0)
    track_positions.set_track_qty("track_c", "AGG", 4.5)

    assert track_positions.get_track_qty("track_b", "SPY") == 10.0
    assert track_positions.get_track_qty("track_c", "AGG") == 4.5
    assert track_positions.get_track_qty("track_b", "AGG") == 0.0  # unset -> 0
    assert track_positions.load_ledger() == {"track_b": {"SPY": 10.0}, "track_c": {"AGG": 4.5}}


def test_set_track_qty_at_or_below_epsilon_removes_the_key():
    track_positions.set_track_qty("track_b", "SPY", 10.0)
    track_positions.set_track_qty("track_b", "SPY", 0.0)
    assert "SPY" not in track_positions.load_ledger()["track_b"]


def test_adjust_track_qty_increments_and_decrements():
    assert track_positions.adjust_track_qty("track_b", "SPY", 6.0) == 6.0
    assert track_positions.adjust_track_qty("track_b", "SPY", 4.0) == 10.0
    assert track_positions.adjust_track_qty("track_b", "SPY", -3.0) == 7.0


def test_adjust_track_qty_floors_at_zero_and_removes_the_key():
    track_positions.set_track_qty("track_b", "SPY", 5.0)
    assert track_positions.adjust_track_qty("track_b", "SPY", -9.0) == 0.0
    assert "SPY" not in track_positions.load_ledger()["track_b"]


def test_track_primitives_reject_an_unknown_track_name():
    for fn in (
        lambda: track_positions.get_track_qty("track_x", "SPY"),
        lambda: track_positions.set_track_qty("track_x", "SPY", 1.0),
        lambda: track_positions.adjust_track_qty("track_x", "SPY", 1.0),
    ):
        with pytest.raises(ValueError):
            fn()


def test_load_ledger_tolerates_a_file_missing_a_top_level_track_key(tmp_path):
    import json
    path = track_positions._STATE_PATH
    with open(path, "w") as f:
        json.dump({"track_b": {"SPY": "3"}}, f)  # no track_c key, string value
    assert track_positions.load_ledger() == {"track_b": {"SPY": 3.0}, "track_c": {}}


# --- reconcile_symbol: match --------------------------------------------------

def test_reconcile_symbol_match_has_no_side_effects(captured_telegram):
    track_positions.set_track_qty("track_b", "AGG", 3.0)
    track_positions.set_track_qty("track_c", "AGG", 4.0)  # fake track_c data
    client = _FakeTradingClient({"AGG": 7.0})

    result = track_positions.reconcile_symbol(client, "AGG")

    assert result.matched is True
    assert result.expected == 7.0
    assert result.actual == 7.0
    assert result.halted_track_c is False
    assert captured_telegram == []
    assert halt_state.load_track_c_halt().halted is False


def test_reconcile_symbol_match_within_epsilon_for_fractional_shares(captured_telegram):
    track_positions.set_track_qty("track_b", "SPY", 6.6667)
    client = _FakeTradingClient({"SPY": 6.66670000004})  # < 1e-6 away

    result = track_positions.reconcile_symbol(client, "SPY")

    assert result.matched is True
    assert captured_telegram == []


def test_reconcile_symbol_zero_on_both_sides_matches(captured_telegram):
    client = _FakeTradingClient({})  # symbol not held at all
    result = track_positions.reconcile_symbol(client, "QQQ")
    assert result.matched is True
    assert result.expected == 0.0 and result.actual == 0.0


# --- reconcile_symbol: deliberate mismatch (brief requirement #5) ------------

def test_reconcile_symbol_mismatch_fires_urgent_alert_and_halts_track_c(captured_telegram):
    # real track_b ledger data + fake track_c ledger data; Alpaca disagrees.
    track_positions.set_track_qty("track_b", "AGG", 3.0)
    track_positions.set_track_qty("track_c", "AGG", 4.0)
    client = _FakeTradingClient({"AGG": 5.0})  # expected 7.0, actual 5.0 -> mismatch

    result = track_positions.reconcile_symbol(client, "AGG")

    assert result.matched is False
    assert result.expected == 7.0
    assert result.actual == 5.0
    assert result.halted_track_c is True

    urgent = [m for m in captured_telegram if m.startswith("URGENT — POSITION LEDGER MISMATCH")]
    assert len(urgent) == 1
    assert "AGG" in urgent[0]

    tc_halt = halt_state.load_track_c_halt()
    assert tc_halt.halted is True
    assert "AGG" in tc_halt.reason


def test_reconcile_symbol_mismatch_does_not_touch_track_b_halt(captured_telegram):
    track_positions.set_track_qty("track_b", "SPY", 10.0)
    client = _FakeTradingClient({"SPY": 4.0})

    track_positions.reconcile_symbol(client, "SPY")

    assert halt_state.load_track_c_halt().halted is True
    assert halt_state.load_halt_state().halted is False  # Track B / global halt untouched


def test_reconcile_symbol_mismatch_when_alpaca_shows_a_position_the_ledger_doesnt(captured_telegram):
    client = _FakeTradingClient({"IWM": 12.0})  # ledger has nothing for IWM

    result = track_positions.reconcile_symbol(client, "IWM")

    assert result.matched is False
    assert result.expected == 0.0
    assert result.actual == 12.0
    assert halt_state.load_track_c_halt().halted is True


def test_reconcile_symbol_halted_track_c_flag_false_when_already_halted(captured_telegram):
    halt_state.set_track_c_halt("pre-existing halt for some other reason")
    track_positions.set_track_qty("track_b", "SPY", 10.0)
    client = _FakeTradingClient({"SPY": 4.0})

    result = track_positions.reconcile_symbol(client, "SPY")

    assert result.matched is False
    assert result.halted_track_c is False  # was already halted, this call didn't newly halt it
    assert halt_state.load_track_c_halt().halted is True
