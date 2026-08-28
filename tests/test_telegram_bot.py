"""
src/telegram_bot.py send_message() — implemented 2026-08-28 (the actual
fix for the cascading-crash finding: a raising send_message() called
from inside error-handling code turned one failure into two). Plain
synchronous requests.post(), best-effort, NEVER raises. Same pattern as
execution.send_daily_heartbeat() / fill_listener.send_listener_heartbeat().
"""
from types import SimpleNamespace

import pytest

from src import telegram_bot


@pytest.fixture(autouse=True)
def telegram_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "test-chat")


def test_send_message_returns_true_on_a_successful_post():
    calls = []
    fake_requests = SimpleNamespace(post=lambda url, json, timeout: calls.append((url, json, timeout)))

    result = telegram_bot.send_message("hello world", requests_module=fake_requests)

    assert result is True
    assert len(calls) == 1
    url, payload, timeout = calls[0]
    assert url == "https://api.telegram.org/bottest-token/sendMessage"
    assert payload == {"chat_id": "test-chat", "text": "hello world"}
    assert timeout == 10


def test_send_message_swallows_a_post_exception_and_returns_false():
    def boom(url, json, timeout):
        raise RuntimeError("network unreachable / non-2xx")

    fake_requests = SimpleNamespace(post=boom)

    # Must NOT propagate — this is the whole point of the fix.
    result = telegram_bot.send_message("alert text", requests_module=fake_requests)

    assert result is False


def test_send_message_swallows_missing_telegram_config_and_returns_false(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    posted = []
    fake_requests = SimpleNamespace(post=lambda **kwargs: posted.append(kwargs))

    # get_telegram_config() raises RuntimeError("Missing required env var")
    # here — that must be caught too, not just POST failures.
    result = telegram_bot.send_message("alert text", requests_module=fake_requests)

    assert result is False
    assert posted == []  # never reached the POST
