"""
Smoke test: confirms .env is set up correctly once you've filled in real
keys. Run with: pytest tests/test_config.py -v

This is the one piece of this scaffold that's actually meant to run today,
not a stub for a future session.
"""
import pytest
from src import config
from src.config import (
    get_alpaca_config,
    get_telegram_config,
    get_guardrail_config,
    get_heartbeat_config,
    get_listener_heartbeat_config,
    get_log_level,
    _validate_allocations,
)


def test_alpaca_config_loads():
    cfg = get_alpaca_config()
    assert cfg.api_key, "ALPACA_PAPER_API_KEY missing from .env"
    assert cfg.secret_key, "ALPACA_PAPER_SECRET_KEY missing from .env"
    assert cfg.paper is True, "TRADING_ENV should be 'paper' at this stage"


def test_telegram_config_loads():
    cfg = get_telegram_config()
    assert cfg.bot_token
    assert cfg.chat_id


def test_guardrails_match_spec():
    """Guards against a typo silently drifting from the locked spec numbers."""
    g = get_guardrail_config()
    assert g.max_risk_per_trade_pct == 1.0
    assert g.max_position_size_pct == 25.0
    assert g.max_daily_loss_pct == 3.0
    assert g.max_trades_per_day == 6
    assert g.max_combined_open_risk_pct == 1.5
    assert g.max_drawdown_pct == 10.0


def test_heartbeat_config_defaults_to_none_when_unset(monkeypatch):
    monkeypatch.delenv("HEALTHCHECKS_DAILY_HEARTBEAT_URL", raising=False)
    assert get_heartbeat_config().daily_job_url is None


def test_heartbeat_config_reads_url_when_set(monkeypatch):
    monkeypatch.setenv("HEALTHCHECKS_DAILY_HEARTBEAT_URL", "https://uptimerobot.example/heartbeat/abc123")
    assert get_heartbeat_config().daily_job_url == "https://uptimerobot.example/heartbeat/abc123"


def test_listener_heartbeat_config_defaults_to_none_when_unset(monkeypatch):
    monkeypatch.delenv("HEALTHCHECKS_LISTENER_HEARTBEAT_URL", raising=False)
    assert get_listener_heartbeat_config().listener_url is None


def test_listener_heartbeat_config_reads_url_when_set(monkeypatch):
    monkeypatch.setenv("HEALTHCHECKS_LISTENER_HEARTBEAT_URL", "https://uptimerobot.example/heartbeat/listener-xyz")
    assert get_listener_heartbeat_config().listener_url == "https://uptimerobot.example/heartbeat/listener-xyz"


def test_log_level_defaults_to_info_when_unset(monkeypatch):
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    assert get_log_level() == "INFO"


def test_log_level_reads_value_when_set(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    assert get_log_level() == "DEBUG"


# --- capital partition (spec v53 §10.23, Milestone 1) ----------------------

def test_allocation_pcts_default_to_the_locked_70_30_split():
    """Guards against a typo drifting the locked partition. .env / .env.example
    both ship 0.70 / 0.30; config.py also defaults to those if the vars are
    absent, so this holds either way."""
    assert config.TRACK_B_ALLOCATION_PCT == 0.70
    assert config.TRACK_C_ALLOCATION_PCT == 0.30
    # stored as fractions in [0, 1], NOT percentages out of 100
    assert 0.0 <= config.TRACK_B_ALLOCATION_PCT <= 1.0


def test_validate_allocations_accepts_a_valid_split():
    _validate_allocations(0.70, 0.30)   # sums to exactly 1.0
    _validate_allocations(0.60, 0.30)   # sums to < 1.0 — leaving a cash buffer is allowed
    _validate_allocations(0.0, 1.0)     # boundary values allowed


def test_validate_allocations_rejects_a_fraction_outside_0_to_1():
    with pytest.raises(RuntimeError, match="TRACK_B_ALLOCATION_PCT must be between 0 and 1"):
        _validate_allocations(-0.1, 0.3)
    with pytest.raises(RuntimeError, match="TRACK_C_ALLOCATION_PCT must be between 0 and 1"):
        _validate_allocations(0.5, 1.5)


def test_validate_allocations_rejects_a_partition_that_sums_over_one():
    with pytest.raises(RuntimeError, match="must sum to no more than 1.0"):
        _validate_allocations(0.80, 0.30)
