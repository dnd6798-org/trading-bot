"""
Single source of truth for environment/config loading.

Every other module reads settings from here — nothing else should call
os.environ directly or hardcode paper vs. live. This keeps the environment
switch (spec §2, v6 "Environment separation & code promotion pipeline")
a config-only decision, never a code fork.
"""
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


def _get(name: str, required: bool = True, default=None):
    val = os.environ.get(name, default)
    if required and not val:
        raise RuntimeError(f"Missing required env var: {name}")
    return val


@dataclass(frozen=True)
class AlpacaConfig:
    api_key: str
    secret_key: str
    base_url: str
    paper: bool


@dataclass(frozen=True)
class TelegramConfig:
    bot_token: str
    chat_id: str


@dataclass(frozen=True)
class GuardrailConfig:
    max_risk_per_trade_pct: float
    max_position_size_pct: float
    max_daily_loss_pct: float
    max_trades_per_day: int
    max_combined_open_risk_pct: float
    max_drawdown_pct: float


@dataclass(frozen=True)
class StrategyConfig:
    ema_fast_period: int
    ema_slow_period: int
    atr_multiplier: float | None  # None until locked via backtest (playbook v6 §7)


TRADING_ENV = _get("TRADING_ENV", default="paper")
IS_PAPER = TRADING_ENV.lower() == "paper"


def get_alpaca_config() -> AlpacaConfig:
    prefix = "ALPACA_PAPER" if IS_PAPER else "ALPACA_LIVE"
    return AlpacaConfig(
        api_key=_get(f"{prefix}_API_KEY"),
        secret_key=_get(f"{prefix}_SECRET_KEY"),
        base_url=_get(f"{prefix}_BASE_URL"),
        paper=IS_PAPER,
    )


def get_telegram_config() -> TelegramConfig:
    return TelegramConfig(
        bot_token=_get("TELEGRAM_BOT_TOKEN"),
        chat_id=_get("TELEGRAM_CHAT_ID"),
    )


def get_guardrail_config() -> GuardrailConfig:
    return GuardrailConfig(
        max_risk_per_trade_pct=float(_get("MAX_RISK_PER_TRADE_PCT")),
        max_position_size_pct=float(_get("MAX_POSITION_SIZE_PCT")),
        max_daily_loss_pct=float(_get("MAX_DAILY_LOSS_PCT")),
        max_trades_per_day=int(_get("MAX_TRADES_PER_DAY")),
        max_combined_open_risk_pct=float(_get("MAX_COMBINED_OPEN_RISK_PCT")),
        max_drawdown_pct=float(_get("MAX_DRAWDOWN_PCT")),
    )


def get_strategy_config() -> StrategyConfig:
    atr_raw = _get("ATR_MULTIPLIER", required=False, default="")
    return StrategyConfig(
        ema_fast_period=int(_get("EMA_FAST_PERIOD", default="9")),
        ema_slow_period=int(_get("EMA_SLOW_PERIOD", default="21")),
        atr_multiplier=float(atr_raw) if atr_raw else None,
    )
