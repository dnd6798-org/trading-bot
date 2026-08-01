"""
Promotion pipeline (spec §2, §3.3, §7 — locked v6).

Evaluates a paper-tested code change (new ticker, new logic) against
promotion criteria before requesting Telegram approval to merge `paper`
into `main`/live. Structurally similar to the capital-scaling criteria
(spec §4.4) but a separate gate — this asks "should this code ship,"
not "should we trust the system with more money."

Exact thresholds (soak period length, minimum trades, expectancy/drawdown
cutoffs) are NOT YET LOCKED — tracked as an open item in
session-playbook-v6.md §7. Do not hardcode numbers here until that
session happens.
"""
from dataclasses import dataclass


@dataclass
class PromotionCriteria:
    min_soak_days: int
    min_trades: int
    min_expectancy: float
    max_drawdown_pct: float


@dataclass
class PromotionEvaluation:
    eligible: bool
    summary: str
    metrics: dict


def evaluate_for_promotion(paper_trade_history, criteria: PromotionCriteria) -> PromotionEvaluation:
    raise NotImplementedError("Locked criteria needed first — playbook v6 §7")
