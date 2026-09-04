"""
scripts/service_alert.py — Telegram alert on trading-bot-listener.service
start/stop/restart (Tier 1 monitoring redesign, CLAUDE.md "Session
update ... 2026-09-04, spec/playbook v76").

Covers message-composition logic only (per the milestone brief) — no
real Telegram network call, send_message() is monkeypatched throughout.
"""
import pytest

from scripts import service_alert


@pytest.fixture(autouse=True)
def captured_send(monkeypatch):
    sent = []
    monkeypatch.setattr(service_alert, "send_message", lambda text: sent.append(text))
    return sent


def test_compose_starting_message():
    assert service_alert.compose_starting_message() == "trading-bot-listener.service: started."


def test_compose_stopped_message_with_real_values():
    text = service_alert.compose_stopped_message("success", "0", "0/SUCCESS")
    assert text == (
        "trading-bot-listener.service: stopped. "
        "result=success exit_code=0 exit_status=0/SUCCESS"
    )


def test_env_or_unknown_defaults_to_unknown_when_unset(monkeypatch):
    monkeypatch.delenv("SERVICE_RESULT", raising=False)
    assert service_alert._env_or_unknown("SERVICE_RESULT") == "unknown"


def test_env_or_unknown_defaults_to_unknown_when_empty(monkeypatch):
    # systemd/systemd#4770 — SERVICE_RESULT/EXIT_CODE/EXIT_STATUS aren't
    # reliably populated on every failure path; an empty string must
    # degrade the same way as a fully unset var, not render as "".
    monkeypatch.setenv("SERVICE_RESULT", "")
    assert service_alert._env_or_unknown("SERVICE_RESULT") == "unknown"


def test_env_or_unknown_passes_through_a_real_value(monkeypatch):
    monkeypatch.setenv("SERVICE_RESULT", "success")
    assert service_alert._env_or_unknown("SERVICE_RESULT") == "success"


def test_main_starting_event_sends_the_starting_message(captured_send):
    service_alert.main(["--event=starting"])

    assert captured_send == ["trading-bot-listener.service: started."]


def test_main_stopped_event_reads_env_vars_and_sends_composed_message(monkeypatch, captured_send):
    monkeypatch.setenv("SERVICE_RESULT", "success")
    monkeypatch.setenv("EXIT_CODE", "0")
    monkeypatch.setenv("EXIT_STATUS", "0/SUCCESS")

    service_alert.main(["--event=stopped"])

    assert captured_send == [
        "trading-bot-listener.service: stopped. "
        "result=success exit_code=0 exit_status=0/SUCCESS"
    ]


def test_main_stopped_event_with_missing_env_vars_degrades_to_unknown(monkeypatch, captured_send):
    monkeypatch.delenv("SERVICE_RESULT", raising=False)
    monkeypatch.delenv("EXIT_CODE", raising=False)
    monkeypatch.delenv("EXIT_STATUS", raising=False)

    service_alert.main(["--event=stopped"])

    assert captured_send == [
        "trading-bot-listener.service: stopped. "
        "result=unknown exit_code=unknown exit_status=unknown"
    ]


def test_main_stopped_event_with_empty_env_vars_degrades_to_unknown(monkeypatch, captured_send):
    monkeypatch.setenv("SERVICE_RESULT", "")
    monkeypatch.setenv("EXIT_CODE", "")
    monkeypatch.setenv("EXIT_STATUS", "")

    service_alert.main(["--event=stopped"])

    assert captured_send == [
        "trading-bot-listener.service: stopped. "
        "result=unknown exit_code=unknown exit_status=unknown"
    ]


def test_main_never_raises_when_send_message_itself_raises(monkeypatch):
    # send_message() already never raises in production (its own
    # best-effort contract) — this proves the ExecStartPost/ExecStopPost
    # lifecycle step is ALSO protected if that contract were ever broken,
    # per the brief's "must never block the lifecycle step" requirement.
    def boom(text):
        raise RuntimeError("network unreachable")

    monkeypatch.setattr(service_alert, "send_message", boom)

    service_alert.main(["--event=starting"])  # must not raise
