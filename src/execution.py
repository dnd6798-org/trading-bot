"""
Pipeline step 4 (spec §3.1.4): execution.

*** OPEN DESIGN ISSUE — RESOLVE BEFORE IMPLEMENTING THIS MODULE ***
Spec §2 originally assumed broker-side bracket orders (entry + stop-loss +
take-profit as one atomic order) as the exit safety net, independent of bot
uptime. Alpaca does NOT support bracket/OCO/OTO order classes for crypto —
only market, limit, and stop_limit are supported for crypto pairs.

Fallback discussed but not yet locked into the spec: place a stop_limit
sell order (stop-loss) and a separate limit sell order (take-profit)
individually after entry fills. Both rest on the exchange (so price-trigger
still works if the bot is briefly down), but Alpaca won't auto-cancel the
other leg when one fills — position_management.py has to detect the fill
and cancel the counterpart. This is a real, partial gap versus the original
"independent of bot uptime" guarantee (spec §4.5) and should be written up
as a spec correction (§2, §4.5) before this module is built for real.

Do not implement order placement here until that's resolved.
"""
from dataclasses import dataclass

from .risk_filter import RiskDecision
from .signal_generation import TradeSignal


@dataclass
class ExecutionResult:
    order_id: str
    filled: bool
    fill_price: float | None
    symbol: str


def place_entry_order(signal: TradeSignal, decision: RiskDecision) -> ExecutionResult:
    raise NotImplementedError("Blocked on the bracket-order design fix above")


def place_exit_orders(entry: ExecutionResult, signal: TradeSignal) -> tuple[str, str]:
    """
    Places the stop-loss and take-profit legs. Returns (stop_order_id,
    take_profit_order_id) so position_management.py can watch both and
    cancel the counterpart when either fills (software-emulated OCO).
    """
    raise NotImplementedError("Blocked on the bracket-order design fix above")
