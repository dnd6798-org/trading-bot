"""
src/halt_state.py — Track-C halt functions (spec v55 §10.25, Milestone 2).

The global / Track-B halt (load_halt_state/set_halt/clear_halt) is already
exercised indirectly by tests/test_risk_filter.py; this file covers the
NEW Track-C-specific halt and, critically, its independence from the
global halt.
"""
import pytest

from src import halt_state


@pytest.fixture(autouse=True)
def isolated_halt_files(tmp_path, monkeypatch):
    monkeypatch.setattr(halt_state, "_STATE_PATH", str(tmp_path / "halt_state.json"))
    monkeypatch.setattr(halt_state, "_TRACK_C_STATE_PATH", str(tmp_path / "track_c_halt_state.json"))


def test_track_c_halt_defaults_to_not_halted_when_no_file():
    assert halt_state.load_track_c_halt().halted is False


def test_set_and_clear_track_c_halt_round_trip():
    halt_state.set_track_c_halt("ledger mismatch for AGG")
    state = halt_state.load_track_c_halt()
    assert state.halted is True
    assert state.reason == "ledger mismatch for AGG"
    assert state.halted_at is not None

    halt_state.clear_track_c_halt()
    assert halt_state.load_track_c_halt().halted is False


def test_track_c_halt_is_independent_of_the_global_halt():
    halt_state.set_track_c_halt("track C only")
    assert halt_state.load_track_c_halt().halted is True
    assert halt_state.load_halt_state().halted is False

    halt_state.clear_track_c_halt()
    halt_state.set_halt("global / track B only")
    assert halt_state.load_halt_state().halted is True
    assert halt_state.load_track_c_halt().halted is False
