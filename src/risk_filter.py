"""
Pipeline step 3 (spec §3.1.3): risk & guardrail filter.

Every trade candidate passes through here before execution — no trade
bypasses this stage (spec §3.1). Enforces all of spec §4:

- §4.1 Per-trade: max 1% risk/trade, max 25% notional position size
  (Track B, spec v32: 55% — see config.MAX_SINGLE_POSITION_NOTIONAL_PCT,
  also used by config.get_track_b_guardrail_config())
- §4.2 Daily: max 3% daily loss (circuit breaker), max 6 trades/day
  (Track B, spec v32: 4% / 8, ENTRIES ONLY not entries+exits — see
  config.get_track_b_guardrail_config())
- §4.3 Account: max 10% drawdown, 1.5% combined open-risk budget (BTC+ETH)
  (Track B, spec v32: 8%, deliberately undiscounted — see
  config.get_track_b_guardrail_config()), manual kill switch
- §4.5 System: fail-safe on API/data issues, never fail open

This module is the single place all of §4 is enforced — deliberately
centralized so it's auditable in one file rather than scattered checks
(spec §5 falsifiability/auditability principle).

BUILD-SESSION SCOPE NOTE (Track B guardrail-implementation milestone,
spec v32): the three checks that correspond to the three Track-B-rescaled
numbers (check_trade_count_limit, check_daily_loss_limit,
check_combined_open_risk_budget) were implemented that session, each
against a minimal, locally-documented duck-typed input shape.
check_drawdown_limit() and evaluate() were deliberately left as
NotImplementedError at that point, per that milestone's explicit
instruction not to proceed into execution.py.

UPDATE (execution.py milestone): check_drawdown_limit() and evaluate()
are now implemented — see each function's own docstring. Still no full
AccountState/Position dataclass here; both remain duck-typed to the
minimal attributes each check needs, with execution.py responsible for
building objects that satisfy that shape from Alpaca's real account/
order/position state (this module's own "no local position database"
convention, spec §3.1.4).
"""
from dataclasses import dataclass

from .signal_generation import TradeSignal
from .config import GuardrailConfig
from . import halt_state
from . import telegram_bot


@dataclass
class RiskDecision:
    approved: bool
    reason: str
    position_size: float | None = None


def check_daily_loss_limit(account_state, guardrails: GuardrailConfig) -> bool:
    """
    True = still within today's loss limit, trading may continue. False =
    breached, and this call has ALREADY halted trading via
    halt_state.set_halt() before returning — the same, already-tested,
    persisted-until-a-human-clears-it mechanism halt_state.py provides
    for every other halt reason (spec §4.5/§7), not a new one built for
    Track B. Kept as a direct side effect (rather than deferring the halt
    to some other, undefined caller) to match this module's own framing:
    "the single place all of §4 is enforced — deliberately centralized so
    it's auditable in one file."

    account_state is duck-typed to the minimal shape this one check
    needs: `day_start_equity` (equity at the start of today) and `equity`
    (current equity). A full AccountState type is execution.py's
    milestone, not decided here.
    """
    if account_state.day_start_equity <= 0:
        return True
    daily_pnl_pct = (account_state.equity - account_state.day_start_equity) / account_state.day_start_equity * 100
    within_limit = daily_pnl_pct > -guardrails.max_daily_loss_pct
    if not within_limit:
        halt_state.set_halt(
            f"daily loss limit breached: {daily_pnl_pct:.2f}% (limit -{guardrails.max_daily_loss_pct:.2f}%)"
        )
    return within_limit


def check_trade_count_limit(today_entry_count: int, guardrails: GuardrailConfig) -> bool:
    """
    True = an additional trade today is still within the cap.

    CONTRACT, made explicit (spec v32 clarification pass — the parameter
    was originally named the more generic `today_trade_count`, which left
    this ambiguous): `today_entry_count` MUST count new position ENTRIES
    only, never exits. This matters specifically for Track B's
    MAX_TRADES_PER_DAY_TRACK_B=8 (config.get_track_b_guardrail_config()),
    which is documented as "can never legitimately bind" ONLY because
    entries are structurally capped at one per symbol per day across an
    8-symbol universe. If exits were also counted, that property is
    FALSE: all 8 slots could exit AND all 8 refill with new entries on
    the same shock day (16 events), tripping this cap on an entirely
    ordinary day rather than only on a genuine duplicate-order/
    scheduler-bug. Whatever future caller computes this count
    (execution.py, not built yet) must count entries only.
    """
    return today_entry_count < guardrails.max_trades_per_day


def check_drawdown_limit(account_state, guardrails: GuardrailConfig) -> bool:
    """
    True = current equity is still within guardrails.max_drawdown_pct of
    the account's peak equity, trading may continue. False = breached,
    and this call has ALREADY halted trading via halt_state.set_halt()
    before returning — same mechanism/convention as
    check_daily_loss_limit() above (spec §4.5/§7's persisted-until-a-
    human-clears-it halt).

    account_state is duck-typed to the minimal shape this check needs:
    `equity` (current) and `peak_equity` (the account's all-time-high
    equity). Per this module's "no local position database" convention
    (execution.py's locked design, CLAUDE.md), `peak_equity` is expected
    to be derived by the caller from Alpaca's own account/portfolio-
    history data (e.g. the max of get_portfolio_history()'s equity
    series) — NOT tracked in a local file here. This is the global spec
    §4.3 guardrail (10%, unchanged for Track B — no Track-B override
    exists, see config.get_track_b_guardrail_config()'s docstring), so
    max_drawdown_pct is read the same way regardless of which
    GuardrailConfig (global or Track B) is passed in.

    Breach is defined at-or-past the threshold (drawdown_pct >=
    max_drawdown_pct halts), mirroring check_daily_loss_limit()'s own
    at-or-past-the-limit convention.
    """
    if account_state.peak_equity <= 0:
        return True
    drawdown_pct = (account_state.peak_equity - account_state.equity) / account_state.peak_equity * 100
    within_limit = drawdown_pct < guardrails.max_drawdown_pct
    if not within_limit:
        halt_state.set_halt(
            f"drawdown limit breached: {drawdown_pct:.2f}% from peak (limit {guardrails.max_drawdown_pct:.2f}%)"
        )
    return within_limit


def check_combined_open_risk_budget(open_positions, new_signal: TradeSignal, guardrails: GuardrailConfig) -> float | None:
    """
    Returns remaining risk budget available for this trade, as a % of
    equity (spec §4.3), or None if fully committed. Sizing is capped at
    the smaller of: this remaining budget, and the standard per-trade max
    (§4.1) — the cap-at-the-smaller-of step itself is a position-sizing
    concern (execution.py/position_management.py), not decided here; this
    function only answers "how much budget is left."

    Same equal-risk-contribution concept already implemented and
    validated in the Track B backtest (simulate_rotational_ensemble()'s
    total_risk_budget_pct mechanism, scripts/backtest_donchian_
    ensemble.py — see spec v30 §10.2's notional-concentration milestone
    for why this is deliberately UNDISCOUNTED for Track B, not a new
    correlation-adjusted number), ported here as the live guardrail
    check. `open_positions` is duck-typed to the minimal shape this check
    needs: each position exposes `.risk_pct` (the % of equity committed
    at entry) — full position typing is execution.py/position_
    management.py's milestone, not decided here. `new_signal` is accepted
    per the original stub signature but unused by this minimal
    implementation — no per-signal-specific budget rule exists yet.
    """
    committed_pct = sum(p.risk_pct for p in open_positions)
    available_pct = guardrails.max_combined_open_risk_pct - committed_pct
    return available_pct if available_pct > 0 else None


def evaluate(signal: TradeSignal, account_state, open_positions, today_entry_count: int, guardrails: GuardrailConfig) -> RiskDecision:
    """
    Single entry point — every candidate must go through this before
    execution.py ever sees it (execution.py milestone, spec §3.1.3/§3.1.4
    boundary). Runs, in order:

      1. check_daily_loss_limit() — account-level, halts on breach.
      2. check_drawdown_limit() — account-level, halts on breach.
      3. check_trade_count_limit() — today_entry_count: see check_trade_
         count_limit()'s docstring, entries only, never exits.
      4. check_combined_open_risk_budget() — the remaining portfolio
         risk-budget %, or a reject if fully committed.

    Checks 1-2 run (and can halt) even if an earlier one in this same
    call already breached — cheap and idempotent (halt_state.set_halt()
    just re-writes the same halted=True file), and keeps each check's
    own halt side effect self-contained rather than adding short-circuit
    logic that could accidentally skip a real breach on some future
    reordering.

    Position notional cap (spec §4.1, guardrails.max_position_size_pct —
    the 5th named guardrail) is deliberately NOT a pass/fail gate here,
    same reasoning check_combined_open_risk_budget()'s own docstring
    already gives for why it doesn't decide sizing outright: a candidate
    signal isn't invalid just because ITS eventual position might need to
    be sized down. It can't be evaluated as a simple % gate at this stage
    either way — the actual notional a given risk_pct produces depends on
    the entry-ATR-to-price ratio, which isn't knowable until the sizing
    step (same AGG-style pathology already documented in
    scripts/backtest_donchian_ensemble.py's entry_sizing_log). Whether
    the notional cap actually binds is therefore resolved downstream, in
    execution.py's sizing step, reading guardrails.max_position_size_pct
    directly off the SAME GuardrailConfig object this function was
    called with — not decided here.

    On approval, RiskDecision.position_size carries the GRANTED risk %
    of equity for this trade (min of the standard per-trade target,
    guardrails.max_risk_per_trade_pct, and whatever remains of the open-
    risk budget) — execution.py multiplies this by equity to get the
    live risk_amount for its position-sizing formula, the same
    equal-risk-contribution concept already validated in the Track B
    backtest (simulate_rotational_ensemble()'s total_risk_budget_pct
    mechanism).
    """
    if not check_daily_loss_limit(account_state, guardrails):
        return RiskDecision(approved=False, reason="daily loss limit breached")
    if not check_drawdown_limit(account_state, guardrails):
        return RiskDecision(approved=False, reason="drawdown limit breached")
    if not check_trade_count_limit(today_entry_count, guardrails):
        return RiskDecision(approved=False, reason="trade count limit reached")

    available_risk_pct = check_combined_open_risk_budget(open_positions, signal, guardrails)
    if available_risk_pct is None:
        return RiskDecision(approved=False, reason="open-risk budget exhausted")

    granted_risk_pct = min(guardrails.max_risk_per_trade_pct, available_risk_pct)
    return RiskDecision(approved=True, reason="approved", position_size=granted_risk_pct)


# --- Soft concentration monitoring (spec v32) -------------------------------
# NOT part of the RiskDecision approve/reject flow above and must NEVER
# reject or resize a trade — visibility for a human only, via a
# non-blocking Telegram alert. Grouping confirmed with the user before
# implementation (same "flag it, don't guess" convention as the 55%
# notional-cap threshold deviation, spec v30 §10.2) — see CLAUDE.md
# "Current status" for the confirmation record. Recommended/confirmed
# grouping: International Equities (EFA) and Bonds (AGG) are singleton
# groups and can structurally never trigger this alert alone — a single
# position is capped at 55% notional (MAX_SINGLE_POSITION_NOTIONAL_PCT,
# backtest_etf_donchian.py, spec v30 §10.2), below the 65% threshold —
# only Domestic Equities and Alternatives can realistically ever reach it
# with the current 8-symbol universe and 8-slot cap.
TRACK_B_ASSET_CLASS_GROUPS = {
    "Domestic Equities": {"SPY", "QQQ", "IWM"},
    "International Equities": {"EFA"},
    "Bonds": {"AGG"},
    "Alternatives": {"GLD", "DBC", "VNQ"},
}
CONCENTRATION_ALERT_THRESHOLD_PCT = 65.0


def check_asset_class_concentration(
    open_positions,
    asset_class_groups=TRACK_B_ASSET_CLASS_GROUPS,
    threshold_pct=CONCENTRATION_ALERT_THRESHOLD_PCT,
):
    """
    Soft, non-blocking monitoring check (spec v32) — fires a Telegram
    alert when combined notional across open positions in the same
    asset-class group exceeds threshold_pct of equity. Returns the list
    of triggered group names for logging only; the return value must
    NEVER be used to reject, delay, or resize a trade — this function has
    no opinion on whether a trade proceeds, unlike every check above it
    in this file.

    `open_positions` is duck-typed to the minimal shape this check needs:
    each position exposes `.symbol` and `.notional_pct_of_equity` (the %
    of equity that position's notional currently represents) — same
    field name as the Track B backtest's entry_sizing_log
    (backtest_donchian_ensemble.py, spec v29 §10.1), a deliberate naming
    match, not a coincidence. Full position typing is execution.py's
    milestone, not decided here.
    """
    triggered = []
    for group_name, symbols in asset_class_groups.items():
        group_notional_pct = sum(p.notional_pct_of_equity for p in open_positions if p.symbol in symbols)
        if group_notional_pct > threshold_pct:
            triggered.append(group_name)
            telegram_bot.send_message(
                f"Concentration alert: {group_name} combined notional at {group_notional_pct:.1f}% of equity "
                f"(threshold {threshold_pct:.1f}%). Monitoring only — no trade was blocked or resized."
            )
    return triggered
