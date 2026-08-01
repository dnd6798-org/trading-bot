"""
Pipeline §3.2: daily learning & governance loop.

Step 1-2: end-of-day aggregation + factual daily journal. No strategy
changes triggered from this alone (spec §5 — journaling != mutation).

Step 3-4 (periodic strategy review, capital governance) are separate,
lower-frequency processes — likely their own module once there's enough
trade history to make them meaningful. Stubbed here as placeholders only.
"""
from dataclasses import dataclass


@dataclass
class DailyJournalEntry:
    date: str
    trades_taken: int
    pnl: float
    notes: str


def aggregate_day(trade_log) -> DailyJournalEntry:
    raise NotImplementedError


def format_journal_message(entry: DailyJournalEntry) -> str:
    """Formats the daily journal for Telegram delivery."""
    raise NotImplementedError


def propose_strategy_review(trade_history) -> str | None:
    """
    Only meaningful after a statistically significant sample (spec §4.4/§5).
    Returns None until that threshold is met — not implemented until the
    threshold itself is defined (playbook v6 §7 open item).
    """
    raise NotImplementedError
