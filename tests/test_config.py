"""
Smoke test: confirms .env is set up correctly once you've filled in real
keys. Run with: pytest tests/test_config.py -v

This is the one piece of this scaffold that's actually meant to run today,
not a stub for a future session.
"""
import pytest
from src.config import get_alpaca_config, get_telegram_config, get_guardrail_config


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
