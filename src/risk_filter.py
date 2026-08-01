"""
Pipeline step 3 (spec §3.1.3): risk & guardrail filter.

Every trade candidate passes through here before execution — no trade
bypasses this stage (spec §3.1). Enforces all of spec §4:

- §4.1 Per-trade: max 1% risk/trade, max 25% notional position size
- §4.2 Daily: max 3% daily loss (circuit breaker), max 6 trades/day
- §4.3 Account: max 10% drawdown, 1.5% combined open-risk budget (BTC+ETH),
  manual kill switch
- §4.5 System: fail-safe on API/data issues, never fail open

This module is the single place all of §4 is enforced — deliberately
centralized so it's auditable in one file rather than scattered checks
(spec §5 falsifiability/auditability principle).
"""
from dataclasses import dataclass

from .signal_generation import TradeSignal
from .config import GuardrailConfig


@dataclass
class RiskDecision:
    approved: bool
    reason: str
    position_size: float | None = None


def check_daily_loss_limit(account_state, guardrails: GuardrailConfig) -> bool:
    raise NotImplementedError


def check_trade_count_limit(today_trade_count: int, guardrails: GuardrailConfig) -> bool:
    raise NotImplementedError


def check_drawdown_limit(account_state, guardrails: GuardrailConfig) -> bool:
    raise NotImplementedError


def check_combined_open_risk_budget(open_positions, new_signal: TradeSignal, guardrails: GuardrailConfig) -> float | None:
    """
    Returns remaining risk budget available for this trade (spec §4.3), or
    None if fully committed. Sizing is capped at the smaller of: remaining
    budget, and the standard per-trade max (§4.1).
    """
    raise NotImplementedError


def evaluate(signal: TradeSignal, account_state, open_positions, today_trade_count: int, guardrails: GuardrailConfig) -> RiskDecision:
    """
    Single entry point — every candidate must go through this before
    execution.py ever sees it.
    """
    raise NotImplementedError("Build session — implement each check above first, then wire together")
