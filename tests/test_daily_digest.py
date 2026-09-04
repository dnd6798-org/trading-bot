"""
src/daily_digest.py — the daily automated Telegram digest (Tier 1
monitoring redesign, CLAUDE.md "Session update ... 2026-09-04, spec/
playbook v76").

Covers build_digest() against isolated ledger/halt-state files (no
network, no trading client), format_digest_message()'s rendering, and
run_daily_digest_job()/main()'s wiring — including the three sections
this milestone explicitly flags as "not yet available" rather than
fabricating placeholder data (today's fills, today's errors, listener
restart count).
"""
from datetime import datetime, timezone

import pytest

from src import daily_digest, execution, halt_state, track_c_execution, track_positions


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setattr(track_positions, "_STATE_PATH", str(tmp_path / "track_positions_state.json"))
    monkeypatch.setattr(halt_state, "_STATE_PATH", str(tmp_path / "halt_state.json"))
    monkeypatch.setattr(halt_state, "_TRACK_C_STATE_PATH", str(tmp_path / "track_c_halt_state.json"))


def _fixed_now():
    return datetime(2026, 9, 4, 21, 30, 0, tzinfo=timezone.utc)


# --- build_digest() ---------------------------------------------------

def test_build_digest_reports_no_positions_and_no_halts_by_default():
    digest = daily_digest.build_digest(now_fn=_fixed_now)

    assert digest["date"] == "2026-09-04"
    assert digest["track_b_positions"] == {}
    assert digest["track_c_positions"] == {}
    assert digest["halted"] is False
    assert digest["halt_reason"] is None
    assert digest["track_c_halted"] is False
    assert digest["track_c_halt_reason"] is None


def test_build_digest_reports_real_ledger_positions_for_both_tracks():
    track_positions.set_track_qty("track_b", "SPY", 12.3456)
    track_positions.set_track_qty("track_b", "AGG", 5.0)
    track_positions.set_track_qty("track_c", "XLK", 20.1)
    track_positions.set_track_qty("track_c", "AGG", 3.5)

    digest = daily_digest.build_digest(now_fn=_fixed_now)

    assert digest["track_b_positions"] == {"SPY": 12.3456, "AGG": 5.0}
    assert digest["track_c_positions"] == {"XLK": 20.1, "AGG": 3.5}


def test_build_digest_only_uses_get_track_qty_over_the_real_universes():
    # A symbol not in either track's universe must never surface, even
    # if it somehow ended up in the ledger file directly.
    track_positions.set_track_qty("track_b", "NOT_IN_UNIVERSE", 1.0)

    digest = daily_digest.build_digest(now_fn=_fixed_now)

    assert digest["track_b_positions"] == {}
    # Sanity: the universes this reads over are the real, already-locked ones.
    assert set(execution.TRACK_B_UNIVERSE) == {"SPY", "QQQ", "IWM", "EFA", "AGG", "GLD", "DBC", "VNQ"}
    assert "AGG" in track_c_execution.HEAL_UNIVERSE


def test_build_digest_reports_track_b_halt_independent_of_track_c():
    halt_state.set_halt("daily loss limit breached")

    digest = daily_digest.build_digest(now_fn=_fixed_now)

    assert digest["halted"] is True
    assert digest["halt_reason"] == "daily loss limit breached"
    assert digest["track_c_halted"] is False


def test_build_digest_reports_track_c_halt_independent_of_track_b():
    halt_state.set_track_c_halt("position ledger mismatch for AGG")

    digest = daily_digest.build_digest(now_fn=_fixed_now)

    assert digest["track_c_halted"] is True
    assert digest["track_c_halt_reason"] == "position ledger mismatch for AGG"
    assert digest["halted"] is False


def test_build_digest_flags_the_three_unavailable_sections_explicitly():
    digest = daily_digest.build_digest(now_fn=_fixed_now)

    assert digest["todays_fills"] == daily_digest.NOT_YET_AVAILABLE
    assert digest["todays_errors"] == daily_digest.NOT_YET_AVAILABLE
    assert digest["listener_restart_count_today"] == daily_digest.NOT_YET_AVAILABLE
    # Never a fabricated zero/empty-looking value standing in for "unmeasured".
    assert digest["todays_fills"] != 0
    assert digest["todays_errors"] != 0
    assert digest["listener_restart_count_today"] != 0


# --- format_digest_message() -------------------------------------------

def test_format_digest_message_renders_positions_halts_and_unavailable_sections():
    digest = {
        "date": "2026-09-04",
        "track_b_positions": {"SPY": 12.3456},
        "track_c_positions": {},
        "halted": True,
        "halt_reason": "daily loss limit breached",
        "track_c_halted": False,
        "track_c_halt_reason": None,
        "todays_fills": daily_digest.NOT_YET_AVAILABLE,
        "todays_errors": daily_digest.NOT_YET_AVAILABLE,
        "listener_restart_count_today": daily_digest.NOT_YET_AVAILABLE,
    }

    text = daily_digest.format_digest_message(digest)

    assert "Daily Digest — 2026-09-04" in text
    assert "SPY: 12.3456" in text
    assert "  none" in text  # Track C positions section, empty
    assert "Track B halt: HALTED — daily loss limit breached" in text
    assert "Track C halt: OK (not halted)" in text
    assert "Today's fills: not yet available" in text
    assert "Today's errors: not yet available" in text
    assert "Listener restarts today: not yet available" in text


# --- run_daily_digest_job() ---------------------------------------------

def test_run_daily_digest_job_sends_the_formatted_message_and_reports_sent(monkeypatch):
    monkeypatch.setattr(daily_digest, "build_digest", lambda: {
        "date": "2026-09-04", "track_b_positions": {}, "track_c_positions": {},
        "halted": False, "halt_reason": None, "track_c_halted": False, "track_c_halt_reason": None,
        "todays_fills": daily_digest.NOT_YET_AVAILABLE, "todays_errors": daily_digest.NOT_YET_AVAILABLE,
        "listener_restart_count_today": daily_digest.NOT_YET_AVAILABLE,
    })
    sent = []

    def fake_send(text):
        sent.append(text)
        return True

    run_log = daily_digest.run_daily_digest_job(send_fn=fake_send)

    assert run_log["errors"] == []
    assert run_log["sent"] is True
    assert run_log["date"] == "2026-09-04"
    assert len(sent) == 1
    assert "Daily Digest — 2026-09-04" in sent[0]


def test_run_daily_digest_job_defaults_send_fn_to_telegram_bot_send_message(monkeypatch):
    calls = []
    monkeypatch.setattr(daily_digest.telegram_bot, "send_message", lambda text: calls.append(text) or True)

    run_log = daily_digest.run_daily_digest_job()

    assert run_log["sent"] is True
    assert len(calls) == 1


def test_run_daily_digest_job_catches_a_build_digest_failure_and_reports_it(monkeypatch):
    def boom():
        raise RuntimeError("corrupt ledger file")

    monkeypatch.setattr(daily_digest, "build_digest", boom)

    run_log = daily_digest.run_daily_digest_job(send_fn=lambda text: True)

    assert run_log["sent"] is False
    assert len(run_log["errors"]) == 1
    assert run_log["errors"][0]["step"] == "build_or_send"
    assert "corrupt ledger file" in run_log["errors"][0]["error"]


# --- main(): LOG_LEVEL wiring + summary-line logging ---------------------

def test_main_configures_logging_from_get_log_level_and_logs_the_result(monkeypatch, caplog):
    basic_config_calls = []
    monkeypatch.setattr(daily_digest.logging, "basicConfig", lambda **kwargs: basic_config_calls.append(kwargs))
    monkeypatch.setattr(daily_digest, "get_log_level", lambda: "DEBUG")

    fixed_run_log = {"date": "2026-09-04", "digest": {}, "sent": True, "errors": []}
    monkeypatch.setattr(daily_digest, "run_daily_digest_job", lambda: fixed_run_log)

    with caplog.at_level("INFO", logger="src.daily_digest"):
        daily_digest.main()

    assert basic_config_calls == [{"level": "DEBUG", "format": "%(asctime)s %(levelname)s %(message)s"}]

    info_records = [r for r in caplog.records if r.levelname == "INFO"]
    assert len(info_records) == 1
    assert info_records[0].msg == "run_daily_digest_job() result: %s"
    assert info_records[0].args == fixed_run_log
