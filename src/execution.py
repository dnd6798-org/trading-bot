"""
Pipeline step 4 (spec §3.1.4): execution.

*** LEGACY OPEN DESIGN ISSUE — crypto/Track A path only, still unresolved,
still blocking. Track B is NOT blocked by this — see below. ***
Spec §2 originally assumed broker-side bracket orders (entry + stop-loss +
take-profit as one atomic order) as the exit safety net, independent of bot
uptime. Alpaca does NOT support bracket/OCO/OTO order classes for crypto —
only market, limit, and stop_limit are supported for crypto pairs. The
crypto EMA-crossover design (scripts/backtest.py) uses a SYMMETRIC
stop-loss + take-profit exit, which is exactly the shape that needs OCO
emulation. That fallback (a resting stop_limit sell + a separate resting
limit sell, with position_management.py detecting whichever fills first
and cancelling the other) is discussed but not yet locked into the spec —
`place_entry_order()`/`place_exit_orders()` below stay NotImplementedError
for that path until it is. Do not implement crypto/Track A order placement
here until that's resolved (see "Hard rules", CLAUDE.md).

=============================================================================
TRACK B (spec v33 execution.py design session, chat interface — see
CLAUDE.md "Current status" for the full locked brief this module
implements). NOT blocked by the gap above: Track B's exit is a single ATR
trailing STOP only, no take-profit leg at all (finding 14/15's design,
ported unchanged — see scripts/backtest_donchian_ensemble.py /
scripts/backtest_etf_donchian.py) — there is nothing to OCO-emulate, so
Alpaca's native support for real stop orders on stocks/ETFs is sufficient
as-is.

Cadence: daily, ~30-60 min post-market-close — NOT the continuous intraday
loop spec §3.1 originally described (that applies to crypto). One call to
run_daily_execution_job() is the whole job.

Signal generation: reuses build_symbol_series()/compute_channel_long_entry_
indices()/UNIVERSE/CHANNEL_LENGTH/ATR_MULTIPLIER directly from
scripts/backtest_etf_donchian.py (Track B's own already-locked/passed
150-line backtest module) — NOT reimplemented here, per the milestone
brief. That module itself reuses simulate_rotational_ensemble() et al.
from scripts/backtest_donchian_ensemble.py, so this file's signal path
traces back to the exact same compute_donchian_levels()/compute_atr()
primitives the Track B backtest validated, transitively, without a second
copy of that logic anywhere. Slot-priority tie-break when multiple signals
compete for fewer free slots than signals fire (universe_order = fixed
list order: SPY, QQQ, IWM, EFA, AGG, GLD, DBC, VNQ) falls naturally out of
iterating `universe` in order — Track B's MAX_CONCURRENT_POSITIONS(8)
equals the full 8-symbol universe size, so (per CLAUDE.md's guardrail-
rescaling milestone) the slot cap can never actually bind: each symbol
holds at most one position, so len(open_positions) can never exceed 8.
No explicit slot-count gate exists in this file for that reason — it is
structurally satisfied by "skip any symbol already in open_positions".

Position/state source of truth: Alpaca's account/position/order state
directly, queried fresh every run — NO local position database anywhere
in this file (locked design decision). Every field build_open_positions()
reports (stop_price, entry_date, risk_pct, ...) is DERIVED from a live
Alpaca query each time, never cached to disk. The one exception is
signal-lookback market data itself (fetched fresh each run too, not
cached) and audit logging (this module doesn't write logs; the caller of
run_daily_execution_job() is expected to persist its returned dict for an
audit trail — spec §3.2 journaling, a different milestone).

Guardrail integration: every candidate signal is passed through
risk_filter.evaluate() (Track B's config, config.get_track_b_guardrail_
config()) before any entry order is submitted — hard prerequisite, which
is why check_drawdown_limit()/evaluate() were this milestone's required
first step (see risk_filter.py).

*** FLAGGED, UNRESOLVED DESIGN GAP — entry-qty-before-fill sequencing ***
The locked design says position sizing is "computed AFTER fill
confirmation, using the actual fill price and the pre-computed fixed stop
price (qty = risk_budget / (fill_price - stop_price))". But Alpaca
requires a qty (or notional) ON the entry order at submission time —
before the next-session fill price is known (entry is a market order
submitted post-close, filled at next session's open; the fixed stop price
itself IS fully known pre-submission, since it's anchored to the signal
day's own close/ATR, but the fill price is not). These two statements
cannot both be literally true for the SAME order: you cannot submit a
market order with a qty computed from a price you don't have yet.

Resolution implemented here (see estimate_pre_fill_qty()'s own docstring
for the full mechanics), NOT confirmed with the user/chat-interface design
session — flagged as a judgment call standing in for a real design gap,
same "flag it, don't guess" convention as this repo's other judgment
calls (e.g. the AGG notional-backstop finding, the 55% cap threshold):
  - The entry order's qty is computed BEFORE submission using the SIGNAL
    DAY's close (close_T) as a proxy for the unknown fill price — the
    best price information available at submission time, and the same
    anchor the stop price itself already uses.
  - The entry order is submitted and filled at that qty. It is NEVER
    resubmitted or resized after the fact — Alpaca has no mechanism to
    change a market order's qty post-fill, and re-trading to true up the
    qty would add a second, un-planned-for execution leg.
  - AFTER fill, compute_realized_risk() computes what risk was ACTUALLY
    taken (using the real fill price), purely for reporting/tracking.
    Any deviation from the 1% target is treated as an accepted, tracked
    consequence of the next-open-fill design — the exact same "signal-
    to-fill overnight gap" the locked design already names and accepts
    for TIMING, just showing up here as NOTIONAL SIZE variance instead
    (same root cause: the fill price isn't known at submission time,
    surfacing in two different visible places).
This is very likely NOT what "computed AFTER fill confirmation" in the
locked design intended (it reads as though qty itself is set post-fill),
but no literal implementation of that sentence is possible given Alpaca's
order API. Recommend this get a real design-call confirmation in the
chat interface before this module is trusted with live capital — this
implementation should be treated as a documented placeholder resolution,
not a locked decision.

*** SECOND FLAGGED, UNRESOLVED DESIGN GAP — bridging the overnight
submit-to-fill gap across separate job invocations ***
Discovered while building the required end-to-end paper dry run (this
milestone's step 6), not anticipated by the locked brief. The brief says
entries are "submitted post-close, filled at next session's open" and
that stop submission happens "immediately after entry fill confirms" —
but the daily job's own cadence is "~30-60 min post-market-close", a
single discrete invocation. Between submission and the next session's
open can be many HOURS (overnight) or DAYS (a weekend/holiday) — a
single process call cannot block that long waiting for
poll_order_until_terminal() without tying up a resource for the entire
gap, and a short poll timeout would otherwise misclassify a perfectly
healthy, still-resting order as "rejected" (no stop ever gets submitted,
and the position silently sits unprotected until some later run happens
to notice).

Resolution implemented here, NOT confirmed with the user/chat-interface
design session — same "flag it, don't guess" status as the gap above:
  - poll_order_until_terminal()'s default timeout is short (60s) —
    enough to catch an IMMEDIATE outcome (invalid symbol, insufficient
    buying power, an actual same-session fill during market hours), not
    enough to wait for a genuine next-session-open fill.
  - confirm_entry_fill() distinguishes three outcomes, not two: filled
    (real shares, needs a stop now), rejected (a genuinely terminal
    zero-fill status — canceled/expired/rejected/done_for_day/stopped,
    nothing to protect, alert and move on), and PENDING (still
    open/new/accepted with zero fill so far — the expected, ordinary
    state for an order that will fill at next session's open; NOT
    treated as a failure, no stop is submitted this run because there
    is nothing to protect yet).
  - A new function, protect_unprotected_fills(), is meant to run as the
    FIRST phase of every run_daily_execution_job() call (including
    "tomorrow's" run, which is realistically the next time this job
    fires after a pending order has since filled): it finds any Alpaca
    position in the universe with NO resting stop order yet, recomputes
    that position's stop price purely from ITS OWN entry date's
    signal-day close/ATR (via compute_stop_price_for_entry_date() — the
    stop formula only ever depends on public price history for the
    entry date, so it is always re-derivable on demand and never needs
    to be persisted anywhere, consistent with this module's "no local
    position database" convention), and protects it via submit_stop_
    order_with_retry().
  - Net effect: a position that fills between two daily job runs can be
    unprotected for up to about one full trading day (the gap between
    "submitted post-close" and "next post-close run discovers the fill
    and protects it") — WORSE than the locked design's apparent
    assumption of near-immediate post-fill protection. This is a real,
    material gap in the locked design as read literally, not
    introduced by this implementation; a genuinely correct fix likely
    needs a THIRD, separate scheduled invocation shortly after each
    session's open (calling protect_unprotected_fills() on its own,
    independent of the post-close job) rather than waiting for the next
    post-close run — not built here, flagged for the same chat-interface
    design-call as the qty gap above.

*** PER-SYMBOL DUPLICATE-ENTRY PROTECTION (spec v44 §10.13, CLOSES a real
gap surfaced by an unplanned same-day restart of trading-bot-daily.service
— see CLAUDE.md "Current status") ***
check_trade_count_limit()'s today_entry_count cap (risk_filter.py) is a
coarse, WHOLE-UNIVERSE limit (8, sized to the full universe) — it cannot
catch a single symbol being double-entered by two same-day invocations of
run_daily_execution_job() (e.g. a service restart). generate_daily_
candidates()'s open_symbols skip only reflects FILLED positions
(build_open_positions()) — a pending, unfilled entry order from an
earlier same-day invocation (Track B entries are always submitted
post-close, meant to fill at next session's open, so they are ALWAYS
pending at the moment of any same-day second invocation) does not block a
second candidate for that same symbol.

Fix: client_order_id (encode_client_order_id(), just below) is already
fully deterministic from that trading day's own closing bar — the SAME
symbol firing the SAME signal on the SAME day always produces the
IDENTICAL id, regardless of how many times this function runs that day.
submit_entry_and_stop() now looks up that exact client_order_id via
trading_client.get_order_by_client_id() BEFORE submitting a new entry
order; if ANY order already exists under it (any status), this is a
detected duplicate — no new order is submitted, and TrackBEntryResult's
reason is "duplicate_client_order_id_skipped" (deliberately NOT a
Telegram alert — a detected duplicate is the guard working as intended,
not an error).

Empirically confirmed against the real paper account (alpaca-py 0.43.5,
per this module's own established "verify, don't guess" convention —
see the client_order_id max-length and ReplaceOrderRequest.qty typing
findings elsewhere in this file): a genuine not-found lookup raises
alpaca.common.exceptions.APIError with .status_code == 404 (.code ==
40410000, message "order not found for {id}") — NOT a None return and
NOT a different exception type. Only that specific outcome is treated as
"no duplicate, proceed normally"; any other APIError status or exception
propagates up to run_daily_execution_job()'s existing per-candidate
try/except (same fail-toward-alert convention as every other check in
this function), rather than being silently treated as either a duplicate
or a clear-to-proceed.

Fail-safe behavior (spec §4.5): any data-fetch or API failure during the
daily job's data-gathering step halts NEW ENTRIES for that day only —
existing positions stay protected by their resting GTC stop orders
independent of bot uptime (nothing in this file ever cancels or weakens a
resting stop as a side effect of a failure; the daily ratchet step can
only ever move a stop MORE favorably, never remove it — see
compute_ratcheted_stop_price()'s max()-only ratchet). A halted account
(halt_state.py) skips new entries the same way, but the daily ratchet
step for already-open positions still runs even while halted, since it
only ever tightens protection and never opens new risk.

Unprotected-window safeguard: the period between entry-fill confirmation
and a resting stop order successfully being placed is this system's
highest-risk failure state (a filled position with zero downside
protection). submit_stop_order_with_retry() retries with backoff and
fires an immediate, distinct Telegram alert on total failure — kept
separate from this module's generic per-symbol error handling, per the
locked design's explicit instruction not to fold this into a catch-all.

=============================================================================
FILL-PROTECTION LISTENER milestone (spec v33 §10.5 — CLAUDE.md "Current
status" has the full locked architecture; src/fill_listener.py is the
module that implements it). This milestone closes the SECOND flagged gap
above (the overnight submit-to-fill gap across daily-job invocations,
which could otherwise leave a position unprotected for up to ~1 trading
day) with a persistent, event-driven WebSocket listener — this file's
own contribution to that milestone is threefold, all purely additive,
no existing behavior changed for any caller that doesn't opt in:
  1. encode_client_order_id()/decode_client_order_id() — the stop-price
     handoff (no local position DB exists, same convention as the rest
     of this module): submit_entry_and_stop() now encodes the pre-
     computed stop price into every entry order's client_order_id;
     fill_listener.py decodes it on fill. Format locked as
     tb-{symbol}-{YYYYMMDD}-{stop_price_cents}.
  2. has_resting_protective_stop() — extracted out of protect_
     unprotected_fills()'s own filtering so it, fill_listener.py's
     handler, AND (as of the fix-up below) submit_entry_and_stop() all
     share the IDENTICAL "is this symbol already protected" check (see
     its own docstring for the full reasoning).
  3. submit_or_resize_stop_order_with_retry() — fill_listener.py's entry
     point for protecting a fill; submit_stop_order_with_retry() itself
     is UNCHANGED and still used directly by submit_entry_and_stop() (and
     internally by the function above).

VERIFIED THIS MILESTONE, not assumed:
  - client_order_id max length for this account's Trading API is 128
    characters (Alpaca's own docs disagree: 48 vs 128 in different
    reference pages) — confirmed empirically against the real paper
    account by submitting real (never-fillable, immediately-cancelled)
    limit orders with client_order_id lengths up to 256 chars: 128 was
    accepted, 129 was rejected with HTTP "client_order_id must be no
    more than 128 characters". The encoded format above is ~22-30 chars
    for Track B's real 8-symbol universe — nowhere near either candidate
    limit; this verification matters for future formats, not this one.

FIX-UP #1, commit 95cd7d8 (both items resolved rather than left flagged):
  1. submit_or_resize_stop_order_with_retry() no longer uses Alpaca's
     PATCH replace for a partial-fill follow-up (ReplaceOrderRequest.qty
     is Optional[int] in the installed alpaca-py version, 0.43.5 —
     confirmed against the pydantic model — unlike every order-
     SUBMISSION request's qty field in the same SDK, which IS fractional
     -capable and, per Alpaca's own fractional-trading docs, explicitly
     supports stop orders). It now submits a SECOND, ADDITIVE stop order
     sized to just the newly-filled increment instead — see that
     function's own docstring for the full "TOP-UP MODEL" reasoning.
     Flagged there at the time: build_open_positions()/ratchet_position_
     stop() still assumed exactly one resting stop per symbol — see
     FIX-UP #2 below, this was addressed next.
  2. submit_entry_and_stop()'s own stop submission now gates on has_
     resting_protective_stop() before submitting — closing (to the same
     check-then-act degree as every other use of this pattern in this
     module, not via a distributed lock) the race between this
     function's own stop submission and fill_listener.py's handler
     reacting to the same fill concurrently. See the comment at the
     client_order_id encoding call site in submit_entry_and_stop() for
     the full reasoning.

FIX-UP #2 (multi-stop consolidation — REMOVED, see FIX-UP #3): the
original attempt merged multiple resting stops into one via a
new-before-cancel PATCH sequence (_consolidate_resting_stops(),
submit a new combined-qty order, confirm it resting, only then cancel
the olds). Live re-verification against the real paper account found
this REJECTED by Alpaca's own held-quantity validation in exactly the
scenario it exists for: when the existing resting stops already fully
cover the real position's share count, a NEW sell order requesting that
same qty is rejected outright — "insufficient qty available for order"
— because Alpaca will not let a new order reserve share quantity other
still-open sell orders already hold, even though no shares have
actually been sold yet. No ordering trick around submit-vs-cancel
avoids this without either reintroducing a real coverage gap
(cancel-then-patch) or ReplaceOrderRequest.qty's Optional[int] typing
(the exact constraint FIX-UP #1 built the top-up model to avoid) —
so the mechanism itself was replaced, not patched. See FIX-UP #3.

FIX-UP #3 (independent per-stop ratcheting — replaces FIX-UP #2's
consolidation entirely): when ratchet_position_stop() finds multiple
resting stops for a symbol, it no longer merges them. Instead it
computes one target ratchet price (off the worst/lowest of the existing
stops' prices, same conservative basis consolidation used) and applies
it to EACH resting stop independently via its own
ReplaceOrderRequest(stop_price=...) — the same single-stop PATCH-replace
mechanism already used and already confirmed working live, just called
once per order instead of once per position. No new order is ever
submitted for this path and nothing is ever cancelled — qty is untouched
on every call, so this has no dependency on ReplaceOrderRequest.qty at
all. build_open_positions()'s existing worst-price rule (see
_find_all_resting_stop_orders()) already keeps risk/state reporting
correct with any number of resting stops per symbol, so there is no
remaining requirement to collapse them into one — a symbol may now
legitimately carry N independently-ratcheted resting stops for its
entire holding period, and that is an accepted, permanent state, not a
leftover to be cleaned up.

FIX-UP #4 (per-stop error isolation — closes the gap FIX-UP #3 left
open): FIX-UP #3's loop did not catch per-order exceptions, so a
partial-replace-failure mid-loop (one resting stop's PATCH succeeds, a
later one for the SAME symbol raises) would abort the remaining stops
and propagate to run_daily_execution_job()'s per-position try/except,
whose alert text ("existing resting stop unchanged") is INACCURATE for
a partial success. Fixed: each per-order replace call in ratchet_
position_stop()'s multi-stop branch is now wrapped in its own try/
except — every resting stop is always attempted regardless of an
earlier one's outcome. A partial or total per-stop failure is
deliberately NOT escalated through the outer per-position try/except
(build_open_positions()'s worst-price rule already means the symbol is
exactly as protected as before the attempt, and tomorrow's ratchet pass
retries automatically) — instead ratchet_position_stop() sends its own
non-urgent Telegram summary directly (_send_ratchet_failure_summary()),
naming which order(s) ratcheted and which remain at their old price with
the error hit, so the failure stays visible without paging a human.

=============================================================================
CAPITAL PARTITION (spec v53 §10.23, Milestone 1). Track B will eventually
share one Alpaca account with Track C, and Alpaca has no sub-account
feature for individual retail accounts — so the 70/30 split is enforced
in application code. run_daily_execution_job() now sizes every new entry
against Track B's 70% sub-balance of current account equity
(capital_ledger.get_available_capital(trading_client,
config.TRACK_B_ALLOCATION_PCT), fetched fresh each run) instead of full
account equity. This is the ONLY behavioral change from that milestone:
signal generation, entry logic, stop-loss/ratchet logic, and the
account-level HALT guardrails (daily-loss/drawdown, which halt the whole
bot and correctly still see full-account equity) are all untouched.
Track C has no execution code yet — this milestone only makes Track B
partition-aware so it is ready for it.

=============================================================================
POSITION-OWNERSHIP LEDGER (spec v55 §10.25, Milestone 2). Alpaca reports
one combined position per symbol with no per-strategy attribution, and
Track C's risk-off asset (AGG) overlaps a symbol Track B trades directly.
src/track_positions.py tracks each track's own share count. This module's
contribution: heal_track_b_ownership_ledger() sets the "track_b" ledger
to Alpaca's actual per-symbol qty every run_daily_execution_job() call —
the daily fallback for anything fill_listener.py's real-time per-fill
updates missed (same listener-plus-daily-job pattern as protect_
unprotected_fills()). The risk-reporting rebase in build_open_positions()
(Milestone 2's other half — 70% sub-balance basis for risk_pct/
notional_pct_of_equity, see that function's docstring) is unrelated to
the ledger; both just landed in the same milestone.
"""
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import requests

from alpaca.common.exceptions import APIError
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, OrderStatus, OrderType, QueryOrderStatus, TimeInForce
from alpaca.trading.requests import (
    GetOrdersRequest,
    GetPortfolioHistoryRequest,
    MarketOrderRequest,
    ReplaceOrderRequest,
    StopOrderRequest,
)

from . import capital_ledger
from . import halt_state
from . import telegram_bot
from . import track_positions
from .config import (
    TRACK_B_ALLOCATION_PCT,
    get_alpaca_config,
    get_heartbeat_config,
    get_log_level,
    get_track_b_guardrail_config,
)
from .risk_filter import RiskDecision, evaluate
from .signal_generation import SignalDirection, TradeSignal

log = logging.getLogger(__name__)

# Track B's own already-locked signal/universe machinery — reused
# directly, not reimplemented (see module docstring).
from scripts.backtest_etf_donchian import (
    UNIVERSE as TRACK_B_UNIVERSE,
    ATR_MULTIPLIER,
    build_symbol_series,
)


@dataclass
class ExecutionResult:
    """Legacy crypto/Track A shape — see the blocked functions below."""
    order_id: str
    filled: bool
    fill_price: float | None
    symbol: str


def place_entry_order(signal: TradeSignal, decision: RiskDecision) -> ExecutionResult:
    raise NotImplementedError("Blocked on the crypto bracket-order design fix above — irrelevant to Track B, see module docstring")


def place_exit_orders(entry: ExecutionResult, signal: TradeSignal) -> tuple[str, str]:
    """
    Places the stop-loss and take-profit legs. Returns (stop_order_id,
    take_profit_order_id) so position_management.py can watch both and
    cancel the counterpart when either fills (software-emulated OCO).
    """
    raise NotImplementedError("Blocked on the crypto bracket-order design fix above — irrelevant to Track B, see module docstring")


# =============================================================================
# Track B — live position state, derived fresh from Alpaca every run
# (no local database, see module docstring).
# =============================================================================

@dataclass
class LivePosition:
    symbol: str
    qty: float
    entry_price: float
    entry_date: str  # "YYYY-MM-DD"
    stop_order_id: str
    stop_price: float
    risk_amount: float
    risk_pct: float
    notional_pct_of_equity: float


@dataclass
class TrackBEntryResult:
    symbol: str
    submitted: bool
    filled: bool
    filled_qty: float = 0.0
    filled_avg_price: float | None = None
    stop_price: float | None = None
    stop_order_submitted: bool = False
    realized_risk_pct: float | None = None
    target_risk_pct: float | None = None
    reason: str | None = None


def _is_stop_order(order) -> bool:
    order_type = getattr(order, "order_type", None) or getattr(order, "type", None)
    return order_type == OrderType.STOP


def get_peak_equity(trading_client: TradingClient) -> float:
    """
    All-time-high equity, from Alpaca's own portfolio history — no local
    tracking (module's "no local position database" convention). Falls
    back to current equity if history is empty (e.g. a brand-new
    account has no drawdown history yet).
    """
    history = trading_client.get_portfolio_history(GetPortfolioHistoryRequest(period="all", timeframe="1D"))
    equity_values = [e for e in (history.equity or []) if e is not None]
    if not equity_values:
        account = trading_client.get_account()
        return float(account.equity)
    return max(equity_values)


def build_account_state(trading_client: TradingClient):
    """
    Duck-typed to exactly what risk_filter.py's checks need: `equity`,
    `day_start_equity` (Alpaca's own `last_equity` — equity as of the
    previous trading day's close, the correct proxy for "today's
    starting equity" without tracking it locally), `peak_equity`.
    """
    account = trading_client.get_account()
    equity = float(account.equity)
    peak_equity = max(get_peak_equity(trading_client), equity)
    return SimpleNamespace(
        equity=equity,
        day_start_equity=float(account.last_equity),
        peak_equity=peak_equity,
    )


def _find_resting_stop_order(trading_client: TradingClient, symbol: str):
    orders = trading_client.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[symbol]))
    stop_orders = [o for o in orders if _is_stop_order(o)]
    if not stop_orders:
        return None
    return sorted(stop_orders, key=lambda o: o.submitted_at, reverse=True)[0]


def _find_all_resting_stop_orders(trading_client: TradingClient, symbol: str) -> list:
    """
    Returns ALL currently resting stop orders for `symbol`, sorted by
    submitted_at ascending — unlike _find_resting_stop_order() (which
    returns only the single most-recently-submitted one), this exists
    for the multi-stop independent-ratchet path (ratchet_position_stop(),
    fix-up item 3) and build_open_positions()'s conservative stop_price/
    risk calculation below, both of which need full awareness of every
    resting stop for a symbol — the top-up model
    (submit_or_resize_stop_order_with_retry()) can leave more than one
    resting for a symbol until the next daily ratchet consolidates them.
    """
    orders = trading_client.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[symbol]))
    return sorted((o for o in orders if _is_stop_order(o)), key=lambda o: o.submitted_at)


def has_resting_protective_stop(trading_client: TradingClient, symbol: str) -> bool:
    """
    Shared idempotency check — "does this symbol already have a resting
    protective stop order" (fill_listener.py milestone, spec v33 §10.5).
    Extracted out of protect_unprotected_fills()'s own filtering (it used
    to inline `_find_resting_stop_order(...) is not None`) so that
    function and fill_listener.py's handle_trade_update() call the
    IDENTICAL check rather than each reimplementing it — the locked
    design's explicit reasoning is the same fix pattern as the v32
    MAX_SINGLE_POSITION_NOTIONAL_PCT drift bug (CLAUDE.md "Current
      status": two independently-set copies of the same fact silently
    disagreeing), applied proactively here instead of discovered after
    the fact.

    Lives in THIS module rather than a new shared module: it is a thin
    wrapper over _find_resting_stop_order(), which already lives here and
    is tightly coupled to this module's Alpaca query machinery
    (GetOrdersRequest, QueryOrderStatus, _is_stop_order) — fill_listener.py
    imports this function directly instead of a second module needing to
    duplicate (or re-import piecemeal) that machinery.
    """
    return _find_resting_stop_order(trading_client, symbol) is not None


def _find_entry_date(trading_client: TradingClient, symbol: str) -> str | None:
    """
    Most recent FILLED buy order's fill date for `symbol` — correct
    because Track B never pyramids (one position per symbol at a time,
    locked design) and a symbol only reaches this function because it
    currently holds an open position, so its most recent filled buy IS
    that holding's entry.
    """
    orders = trading_client.get_orders(
        GetOrdersRequest(status=QueryOrderStatus.CLOSED, symbols=[symbol], side=OrderSide.BUY)
    )
    filled = sorted((o for o in orders if o.filled_at is not None), key=lambda o: o.filled_at, reverse=True)
    if not filled:
        return None
    return filled[0].filled_at.date().isoformat()


def build_open_positions(trading_client: TradingClient, universe=None) -> list[LivePosition]:
    """
    Builds live Track B position state entirely from Alpaca's own
    account/position/order state (see module docstring). Only symbols in
    `universe` are considered — ignores any position this account might
    hold outside Track B (e.g. Track A/crypto positions in the same
    account). A position with no resting stop order found is EXCLUDED
    here (not raised) — the daily job's caller is responsible for
    treating a missing stop as its own alert-worthy condition; this
    function's job is state reporting, not alerting.

    MULTI-STOP AWARENESS (fix-up, item 1): the top-up model can leave
    MORE THAN ONE resting stop for a symbol, each ratcheted independently
    going forward (ratchet_position_stop(), fix-up item 3) rather than
    ever merged into one. Uses
    _find_all_resting_stop_orders() (not the single-order _find_resting_
    stop_order()) and, when several exist, takes the WORST (lowest, for a
    long) of their prices as this position's `stop_price` — the
    conservative choice, since this value feeds risk_amount/risk_pct
    (spec §4.1, consumed by risk_filter.check_combined_open_risk_budget())
    and must never overstate how well-protected the position actually is.
    `stop_order_id` stays informational only (the most-recently-submitted
    of the resting stops) — ratchet_position_stop() re-queries all
    resting stops independently for its own per-stop ratchet decisions
    rather than trusting this single id, so nothing downstream relies on
    it representing the WHOLE resting-stop state in the multi-stop case.

    CAPITAL PARTITION (spec v55 §10.25, Milestone 2 — the risk-reporting
    rebase tracked since v54): `risk_pct` and `notional_pct_of_equity`
    below are measured against Track B's 70% sub-balance of current
    account equity (capital_ledger.get_available_capital(trading_client,
    TRACK_B_ALLOCATION_PCT)), NOT full account equity — matching how
    submit_entry_and_stop() (via compute_realized_risk()) and
    run_daily_execution_job()'s in-loop live_open_positions already size/
    report newly-entered positions post-Milestone-1. Before this change,
    pre-existing positions under-reported their risk (divided by full
    equity instead of the 0.70x base), so risk_filter.check_combined_
    open_risk_budget()'s 8% Track B budget (= 8 slots x 1%, itself on the
    0.70x base) was effectively too loose whenever a position was already
    open. build_account_state()'s equity is deliberately NOT rebased —
    the account-level daily-loss/drawdown HALT checks still see
    full-account equity, per the module docstring's "CAPITAL PARTITION"
    section.
    """
    if universe is None:
        universe = TRACK_B_UNIVERSE
    equity = capital_ledger.get_available_capital(trading_client, TRACK_B_ALLOCATION_PCT)
    positions = trading_client.get_all_positions()

    result = []
    for p in positions:
        if p.symbol not in universe:
            continue
        stop_orders = _find_all_resting_stop_orders(trading_client, p.symbol)
        if not stop_orders:
            continue
        entry_date = _find_entry_date(trading_client, p.symbol)
        qty = float(p.qty)
        entry_price = float(p.avg_entry_price)
        stop_price = min(float(o.stop_price) for o in stop_orders)
        risk_amount = qty * (entry_price - stop_price)
        result.append(LivePosition(
            symbol=p.symbol,
            qty=qty,
            entry_price=entry_price,
            entry_date=entry_date,
            stop_order_id=str(stop_orders[-1].id),
            stop_price=stop_price,
            risk_amount=risk_amount,
            risk_pct=(risk_amount / equity * 100) if equity else 0.0,
            notional_pct_of_equity=(float(p.market_value) / equity * 100) if equity else 0.0,
        ))
    return result


def heal_track_b_ownership_ledger(trading_client: TradingClient, universe=None) -> dict:
    """
    Daily self-heal for src/track_positions.py's "track_b" ledger (spec
    v55 §10.25, Milestone 2) — the fallback half of the same listener-
    plus-daily-job pair protect_unprotected_fills() already uses for stop
    protection. For every universe symbol, SET the track_b ledger entry to
    Alpaca's actual combined position qty (0 if not held), correcting any
    drift from WebSocket events fill_listener.py missed (listener
    downtime, redelivery arithmetic, a crash mid-event).

    Deliberately keyed off the raw get_all_positions() list, NOT
    build_open_positions() — the ledger is about OWNERSHIP, not
    protection, so a filled-but-not-yet-stopped position (which build_
    open_positions() excludes) must still be counted here.

    spec v57 §10.27: for a symbol Track C also trades (AGG), this heal now
    subtracts track_c's CURRENT ledger entry before assigning the
    remainder to track_b — max(0, alpaca_total - track_c_known) — closing
    the AGG-sharing gap from spec v56 §10.26 (previously it set track_b to
    Alpaca's whole total, which silently erased Track C's rightful share
    once Track C held any). For every symbol Track C doesn't trade,
    track_positions.get_track_qty("track_c", symbol) returns 0.0, so this
    is a no-op versus the pre-v57 formula. track_c's own ledger is healed
    independently from Track C's "tc-" order history alone
    (track_positions.heal_track_c_ownership_ledger()), never from the
    combined total — so there is no circular trust here.

    Returns the healed track_b sub-ledger for the run log.
    """
    if universe is None:
        universe = TRACK_B_UNIVERSE
    actual_by_symbol = {p.symbol: float(p.qty) for p in trading_client.get_all_positions()}
    healed = {}
    for symbol in universe:
        total = actual_by_symbol.get(symbol, 0.0)
        track_c_known = track_positions.get_track_qty("track_c", symbol)
        qty = max(total - track_c_known, 0.0)
        track_positions.set_track_qty("track_b", symbol, qty)
        if qty > track_positions.RECONCILE_EPSILON:
            healed[symbol] = qty
    return healed


def get_today_entry_count(trading_client: TradingClient, universe=None, today=None) -> int:
    """
    Derived from Alpaca's real order history for the current calendar day
    (any BUY order submitted today for a Track-B-universe symbol,
    regardless of current status) — NOT a local in-memory counter, so a
    job restart mid-day still sees prior entries already placed. This is
    exactly the "defense-in-depth duplicate-order/scheduler-bug catcher"
    risk_filter.check_trade_count_limit()'s docstring already describes
    (spec v32) — entries-only, matching that check's documented contract.
    """
    if universe is None:
        universe = TRACK_B_UNIVERSE
    if today is None:
        today = datetime.now(timezone.utc).date()
    start_of_day = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc)
    orders = trading_client.get_orders(
        GetOrdersRequest(status=QueryOrderStatus.ALL, side=OrderSide.BUY, symbols=list(universe), after=start_of_day)
    )
    return len(orders)


# =============================================================================
# Track B — signal generation (post-close job)
# =============================================================================

def fetch_track_b_symbol_data(universe=None, end=None, lookback_days=780):
    """
    Post-close daily data pull, reusing build_symbol_series() from
    scripts/backtest_etf_donchian.py UNCHANGED (do not reimplement, per
    the milestone brief) — that function itself computes entry-signal
    indices via compute_channel_long_entry_indices() and ATR(14) off the
    same compute_atr()/compute_donchian_levels() primitives the Track B
    backtest validated. lookback_days=780 (> CHANNEL_LENGTH(100) +
    ATR_PERIOD(14), wide margin) is enough trailing history to seed both
    the 100-day Donchian channel and ATR for a live daily job — NOT the
    account's entire ~10-year backtest history, which a live job has no
    need to re-fetch every day.
    """
    if universe is None:
        universe = TRACK_B_UNIVERSE
    if end is None:
        end = datetime.now(timezone.utc) - timedelta(minutes=20)  # SIP recent-data embargo, same convention as backtest_etf_donchian.py
    start = end - timedelta(days=lookback_days)

    symbol_data = {}
    for symbol in universe:
        series = build_symbol_series(symbol, start, end)
        if series is None:
            log.debug(f"[{symbol}] fetch: 0 bars returned")
        else:
            candles = series["candles"]
            log.debug(f"[{symbol}] fetch: {len(candles)} bars, range {candles[0].timestamp[:10]} to {candles[-1].timestamp[:10]}")
            symbol_data[symbol] = series
    return symbol_data


def _latest_shared_date(symbol_data) -> str | None:
    dates = set()
    for series in symbol_data.values():
        dates |= set(series["date_index"].keys())
    return max(dates) if dates else None


def generate_daily_candidates(symbol_data, universe_order, open_symbols, today):
    """
    Candidate long-entry signals for `today`, in universe_order priority
    (see module docstring — this IS the slot-priority tie-break; no
    separate slot-count gate exists since MAX_CONCURRENT_POSITIONS equals
    the universe size). Skips any symbol already in `open_symbols` —
    Track B never pyramids, one position per symbol at a time.

    Per-symbol DEBUG signal logging (spec v42 §10.11) is emitted for
    EVERY universe_order symbol regardless of open-position status —
    deliberately computed before the open_symbols skip below, so the
    DEBUG log always shows the day's real close/Donchian bands/signal
    even for a symbol already holding a position. This does not change
    which symbols become candidates — that still depends only on
    open_symbols/entry_indices/atr, exactly as before this milestone.
    """
    candidates = []
    for symbol in universe_order:
        series = symbol_data.get(symbol)
        idx = series["date_index"].get(today) if series is not None else None
        if series is None or idx is None:
            log.debug(f"[{symbol}] signal: no data for {today}")
        else:
            candle = series["candles"][idx]
            upper = series["upper"][idx]
            lower = series["lower"][idx]
            has_signal = idx in series["entry_indices"]
            signal_label = "entry_signal" if has_signal else "no_signal"
            log.debug(
                f"[{symbol}] signal: close={candle.close}, donchian_upper={upper}, "
                f"donchian_lower={lower}, signal={signal_label}"
            )

        if symbol in open_symbols:
            continue
        if series is None:
            continue
        if idx is None or idx not in series["entry_indices"]:
            continue
        atr = series["atr"][idx]
        if atr is None or atr <= 0:
            continue
        candle = series["candles"][idx]
        candidates.append({"symbol": symbol, "close": candle.close, "atr": atr, "timestamp": candle.timestamp})
    return candidates


# =============================================================================
# Track B — sizing / stop-anchoring math (pure functions, no I/O)
# =============================================================================

def compute_signal_day_stop_price(signal_close: float, signal_atr: float, atr_multiplier: float = ATR_MULTIPLIER) -> float:
    """
    Initial fixed stop level, anchored to the SIGNAL day's close and that
    day's own ATR — both fully known before the entry order is even
    submitted (locked design: `extreme_close_0` anchors to close_T, not
    the fill day's, matching the backtest's first stop check exactly and
    avoiding a one-directional bug where a fill-day anchor would make the
    live stop looser than the backtest's on breakout-then-reversal
    trades).
    """
    return signal_close - atr_multiplier * signal_atr


def estimate_pre_fill_qty(risk_budget_amount: float, signal_close: float, stop_price: float) -> float:
    """
    *** See module docstring's "FLAGGED, UNRESOLVED DESIGN GAP" section
    for full context — this function IS that resolution. *** Alpaca
    requires a qty on the entry order at submission time, before the
    next-session fill price is known. This is the pre-fill PROXY: it
    substitutes signal_close (close_T, the same anchor the stop price
    itself uses) for the unknown fill price. Realized risk after the
    actual fill is computed separately, see compute_realized_risk().
    Returns 0.0 if the implied stop distance is non-positive (degenerate
    input, e.g. an ATR spike making the stop price cross the close).
    """
    stop_distance = signal_close - stop_price
    if stop_distance <= 0:
        return 0.0
    return risk_budget_amount / stop_distance


def cap_qty_to_notional(qty: float, price: float, equity: float, max_position_size_pct: float) -> float:
    """
    Second-stage cap (spec §4.1's max_position_size_pct — Track B: 55%,
    config.MAX_SINGLE_POSITION_NOTIONAL_PCT) — same two-stage risk-then-
    notional pattern as simulate_rotational_ensemble()'s sizing (risk
    budget first, notional sanity backstop underneath,
    scripts/backtest_donchian_ensemble.py), applied live rather than in
    a backtest loop.
    """
    if equity <= 0 or price <= 0:
        return qty
    max_notional = equity * (max_position_size_pct / 100)
    notional = qty * price
    if notional <= max_notional:
        return qty
    return max_notional / price


def compute_realized_risk(fill_price: float, stop_price: float, qty: float, equity: float) -> dict:
    """
    Realized risk after the actual fill — reporting/tracking only, used
    to measure the overnight-gap deviation named in estimate_pre_fill_
    qty()'s docstring. Never used to resubmit or resize the already-
    filled entry order.
    """
    risk_amount = qty * (fill_price - stop_price)
    risk_pct = (risk_amount / equity * 100) if equity else 0.0
    return {"risk_amount": risk_amount, "risk_pct": risk_pct}


def compute_stop_price_for_entry_date(series, entry_date: str, atr_multiplier: float = ATR_MULTIPLIER) -> float | None:
    """
    Re-derives compute_signal_day_stop_price() purely from `entry_date`'s
    own close/ATR in an already-fetched symbol series — the stop formula
    only ever depends on public price history for the entry date, so it
    is always recomputable on demand and never needs to be persisted
    anywhere (module docstring's second flagged design gap). Returns
    None if entry_date isn't in this series (data lookback didn't reach
    that far back, or ATR wasn't yet seeded on that date) — caller must
    treat that as "cannot determine, alert for manual intervention", not
    silently skip.
    """
    idx = series["date_index"].get(entry_date)
    if idx is None:
        return None
    atr = series["atr"][idx]
    if atr is None:
        return None
    return compute_signal_day_stop_price(series["candles"][idx].close, atr, atr_multiplier)


# =============================================================================
# Track B — client_order_id stop-price handoff (fill_listener.py milestone,
# spec v33 §10.5 — CLAUDE.md "Current status" is the full locked design).
# No local position database exists (module docstring convention above), so
# fill_listener.py's event-driven WebSocket handler has no other way to
# learn a fill's pre-computed stop price. encode_client_order_id() is
# called here at entry-submission time (see submit_entry_and_stop());
# decode_client_order_id() is called by fill_listener.py on every fill
# event. Both are pure functions, independently unit-testable of any live
# order submission, per the milestone brief.
# =============================================================================

CLIENT_ORDER_ID_PREFIX = "tb"
# Format: tb-{symbol}-{YYYYMMDD}-{stop_price_cents}, e.g. tb-SPY-20260812-45823
# (locked design's own example). Symbol pattern allows a literal "." for
# share classes like BRK.B, even though no current Track B universe symbol
# needs it — cheap to allow, not exercised by the 8-symbol universe today.
_CLIENT_ORDER_ID_RE = re.compile(r"^tb-([A-Za-z.]+)-(\d{8})-(\d+)$")


def encode_client_order_id(symbol: str, signal_date: str, stop_price: float) -> str:
    """
    signal_date must be an ISO "YYYY-MM-DD" string — the SAME signal day
    whose close/ATR compute_signal_day_stop_price() was called with for
    this stop_price (matches this module's date_index convention, e.g.
    the `today` value run_daily_execution_job() already uses).
    stop_price is encoded in CENTS, rounded to the nearest cent — Alpaca
    stop_price itself is only ever submitted rounded to 2dp (see
    submit_stop_order()), so no precision is lost by this round-trip.
    """
    date_compact = signal_date.replace("-", "")
    stop_cents = round(stop_price * 100)
    return f"{CLIENT_ORDER_ID_PREFIX}-{symbol}-{date_compact}-{stop_cents}"


def decode_client_order_id(client_order_id: str | None) -> dict | None:
    """
    Inverse of encode_client_order_id(). Returns None — never raises —
    for anything that doesn't match the expected shape (a manually-
    submitted order, an order from a different client/track, or a
    missing client_order_id entirely): fill_listener.py's handler must
    treat a non-matching id as "not a Track B entry order we generated,"
    not as a parse error to alert on.
    """
    if not client_order_id:
        return None
    match = _CLIENT_ORDER_ID_RE.match(client_order_id)
    if not match:
        return None
    symbol, date_compact, stop_cents = match.groups()
    signal_date = f"{date_compact[0:4]}-{date_compact[4:6]}-{date_compact[6:8]}"
    return {"symbol": symbol, "signal_date": signal_date, "stop_price": int(stop_cents) / 100}


def protect_unprotected_fills(trading_client: TradingClient, universe, symbol_data, sleep_fn=time.sleep) -> list[str]:
    """
    Finds any Alpaca position in `universe` that has filled but has NO
    resting stop order yet, and protects it (module docstring's second
    flagged design gap — this is the mechanism that bridges the
    overnight submit-to-fill gap, meant to run as the FIRST phase of
    every run_daily_execution_job() call). Returns the list of symbols
    successfully protected this call.
    """
    positions = trading_client.get_all_positions()
    protected = []
    for p in positions:
        if p.symbol not in universe:
            continue
        if has_resting_protective_stop(trading_client, p.symbol):
            continue  # already protected, nothing to do — shared check, see has_resting_protective_stop()
        entry_date = _find_entry_date(trading_client, p.symbol)
        series = symbol_data.get(p.symbol)
        stop_price = compute_stop_price_for_entry_date(series, entry_date) if (entry_date and series) else None
        if stop_price is None:
            telegram_bot.send_message(
                f"URGENT — UNPROTECTED POSITION: {p.symbol} is filled with no resting stop, and its signal-day "
                f"stop price could not be recomputed (missing entry date or price history). Manual intervention required."
            )
            continue
        stop_order = submit_stop_order_with_retry(trading_client, p.symbol, float(p.qty), stop_price, sleep_fn=sleep_fn)
        if stop_order is not None:
            protected.append(p.symbol)
    return protected


def compute_extreme_close_since_entry(series, entry_date: str, as_of_date: str) -> float:
    """Max close from entry_date to as_of_date inclusive — recomputed fresh each run, never stored locally."""
    entry_idx = series["date_index"][entry_date]
    as_of_idx = series["date_index"][as_of_date]
    closes = [series["candles"][i].close for i in range(entry_idx, as_of_idx + 1)]
    return max(closes)


def compute_ratcheted_stop_price(extreme_close: float, prior_atr: float, atr_multiplier: float, current_stop_price: float) -> float:
    """
    Chandelier-style ratchet — IDENTICAL formula to simulate_rotational_
    ensemble()'s exit block (backtest_donchian_ensemble.py): candidate =
    extreme_close - atr_multiplier * prior_atr, using the PRIOR day's ATR
    (T-1-anchored) so today's check has no lookahead. max()-only ratchet:
    the stop can only move in the position's favor (up, for a long),
    never back down, matching the backtest's own extreme_close max()-only
    ratchet exactly.
    """
    candidate = extreme_close - atr_multiplier * prior_atr
    return max(candidate, current_stop_price)


# =============================================================================
# Track B — order flow (I/O, all take a trading_client so tests can inject
# a fake one; sleep_fn is injectable too so retry/backoff tests don't
# actually sleep).
# =============================================================================

_TERMINAL_STATUSES = {
    OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.EXPIRED,
    OrderStatus.REJECTED, OrderStatus.DONE_FOR_DAY, OrderStatus.STOPPED,
}
_GENUINELY_TERMINAL_NO_FILL = {
    OrderStatus.CANCELED, OrderStatus.EXPIRED, OrderStatus.REJECTED,
    OrderStatus.DONE_FOR_DAY, OrderStatus.STOPPED,
}
_STOP_RETRY_BACKOFF_SECONDS = (5, 15, 30)


def submit_entry_market_order(trading_client: TradingClient, symbol: str, qty: float, client_order_id: str | None = None):
    """
    client_order_id defaults to None (Alpaca assigns its own if omitted)
    so every existing caller/test is unaffected — submit_entry_and_stop()
    below is the only caller that passes one, per the fill_listener.py
    milestone's stop-price handoff (encode_client_order_id()).
    """
    request = MarketOrderRequest(
        symbol=symbol, qty=qty, side=OrderSide.BUY, time_in_force=TimeInForce.DAY, client_order_id=client_order_id,
    )
    return trading_client.submit_order(request)


def poll_order_until_terminal(
    trading_client: TradingClient, order_id, timeout_seconds=60, poll_interval_seconds=5,
    sleep_fn=time.sleep, clock_fn=time.monotonic,
):
    """
    Polls for fill confirmation (spec §4.5: handle partial fills and
    rejections — required, not optional). Stops polling once the order
    reaches a fully terminal status OR a PARTIALLY_FILLED order has held
    that status past the timeout (a persistent partial fill is treated as
    the final outcome — real, unprotected shares that still need a stop,
    not a clean reject).

    SHORT default timeout (60s), deliberately — see module docstring's
    second flagged design gap. This is only meant to catch an IMMEDIATE
    outcome (an invalid symbol, insufficient buying power, or an actual
    fast fill during market hours); it does NOT wait long enough for a
    genuine next-session-open fill, which can be hours away. A timeout
    with zero fill is NOT a rejection — see confirm_entry_fill()'s
    "pending" outcome.
    """
    deadline = clock_fn() + timeout_seconds
    order = trading_client.get_order_by_id(order_id)
    while order.status not in _TERMINAL_STATUSES and order.status != OrderStatus.PARTIALLY_FILLED and clock_fn() < deadline:
        sleep_fn(poll_interval_seconds)
        order = trading_client.get_order_by_id(order_id)
    return order


def confirm_entry_fill(order) -> dict:
    """
    Classifies a polled entry order's outcome, THREE-way (see module
    docstring's second flagged design gap):
      - filled=True: FILLED or any non-zero PARTIALLY_FILLED — real,
        unprotected shares that need a stop now.
      - filled=False, pending=False: a genuinely terminal zero-fill
        status (REJECTED/CANCELED/EXPIRED/DONE_FOR_DAY/STOPPED) — no
        shares, nothing to protect, safe to alert and move on.
      - filled=False, pending=True: still open/new/accepted with zero
        fill so far — the EXPECTED, ordinary state for an order that
        will fill at next session's open. Not a failure — no stop is
        submitted this run because there's nothing to protect yet;
        protect_unprotected_fills() is what catches this up on a later
        run, once it has actually filled.
    """
    filled_qty = float(order.filled_qty or 0)
    if filled_qty > 0:
        return {
            "filled": True, "pending": False, "filled_qty": filled_qty,
            "filled_avg_price": float(order.filled_avg_price), "status": str(order.status),
        }
    if order.status in _GENUINELY_TERMINAL_NO_FILL:
        return {"filled": False, "pending": False, "filled_qty": 0.0, "filled_avg_price": None, "status": str(order.status)}
    return {"filled": False, "pending": True, "filled_qty": 0.0, "filled_avg_price": None, "status": str(order.status)}


def submit_stop_order(trading_client: TradingClient, symbol: str, qty: float, stop_price: float):
    request = StopOrderRequest(
        symbol=symbol, qty=qty, side=OrderSide.SELL, time_in_force=TimeInForce.GTC, stop_price=round(stop_price, 2)
    )
    return trading_client.submit_order(request)


def submit_stop_order_with_retry(
    trading_client: TradingClient, symbol: str, qty: float, stop_price: float,
    backoff_seconds=_STOP_RETRY_BACKOFF_SECONDS, sleep_fn=time.sleep,
):
    """
    A filled position with no resting stop is this system's single
    highest-risk state (locked design's "Unprotected-window safeguard")
    — retried with backoff rather than failing silently, and fires its
    own IMMEDIATE, DISTINCT Telegram alert on total failure, deliberately
    NOT folded into generic error handling. Returns the stop Order on
    success, or None if every attempt failed (caller must NOT treat None
    as "no stop needed" — it means the position is unprotected).
    """
    last_error = None
    for delay in (0,) + tuple(backoff_seconds):
        if delay:
            sleep_fn(delay)
        try:
            return submit_stop_order(trading_client, symbol, qty, stop_price)
        except Exception as exc:  # noqa: BLE001 — must never crash the caller, this IS the alerting path
            last_error = exc
    telegram_bot.send_message(
        f"URGENT — UNPROTECTED POSITION: stop order for {symbol} (qty {qty}) failed after "
        f"{len(backoff_seconds) + 1} attempts (last error: {last_error}). This position has NO resting "
        f"stop-loss. Manual intervention required immediately."
    )
    return None


_MIN_TOPUP_QTY = 1e-6  # floating-point tolerance — a redelivered event's increment should compute to ~0, not a real top-up


def _sum_resting_stop_qty(trading_client: TradingClient, symbol: str) -> float:
    """
    Sums qty across ALL currently resting stop orders for `symbol` — the
    TOP-UP model (submit_or_resize_stop_order_with_retry(), below) can
    leave MULTIPLE resting stop orders open for one symbol simultaneously
    (one per partial-fill increment), unlike every other path in this
    module, which assumes exactly one resting stop per symbol.
    has_resting_protective_stop() (a boolean "at least one exists") is
    unaffected by this and stays correct; anywhere that needs a total
    protected QUANTITY must use this function instead of _find_resting_
    stop_order()'s single-order (most-recent-only) return. Thin wrapper
    over _find_all_resting_stop_orders() (the same multi-stop query the
    ratchet-consolidation path uses) so the two never disagree.
    """
    return sum(float(o.qty) for o in _find_all_resting_stop_orders(trading_client, symbol))


def submit_or_resize_stop_order_with_retry(
    trading_client: TradingClient, symbol: str, qty: float, stop_price: float,
    backoff_seconds=_STOP_RETRY_BACKOFF_SECONDS, sleep_fn=time.sleep,
):
    """
    fill_listener.py's entry point for protecting a fill (spec v33 §10.5
    "Handler logic", TOP-UP variant — see the "FIX-UP" note below for why
    this replaced an earlier PATCH-replace-based design). Returns
    (order, qty_submitted):
      - `order` is the resulting/most-recent resting stop Order for this
        symbol, or None if a real top-up submission failed after
        exhausting retries (same "None means unprotected, don't treat it
        as success" contract submit_stop_order_with_retry() already has).
      - `qty_submitted` is the ACTUAL increment just submitted THIS call
        — 0.0 for a genuine no-op (a redelivered/duplicate event whose
        cumulative filled_qty is already fully covered by existing
        resting stop(s)). fill_listener.py's routine-success Telegram
        notification uses this to decide whether to fire at all, since
        `order` alone is also truthy on a no-op.

    TOP-UP MODEL (FIX-UP, replacing this function's original PATCH-
    replace-qty design): ReplaceOrderRequest.qty is typed Optional[int]
    in the installed alpaca-py version (0.43.5, confirmed against the
    pydantic model) — unlike every order-SUBMISSION request's qty field
    in the same SDK (StopOrderRequest.qty, MarketOrderRequest.qty, both
    Optional[float]), which IS fractional-capable and, per Alpaca's own
    fractional-trading documentation, explicitly supports stop orders
    directly (not just market orders). So a partial-fill follow-up now
    submits a SECOND, ADDITIVE stop order at the same stop price, sized
    to just the newly-filled INCREMENT (cumulative filled_qty minus qty
    already covered by every resting stop for this symbol) — never a
    replace, never a cancel-then-resubmit. Two resting stops at the same
    price for one symbol is an accepted, safe outcome (per instruction):
    if the first fills and closes the position, the second is rejected
    by the broker as an oversell (this account has no margin/shorting),
    not silently mis-executed.

    Idempotency: sums qty across ALL resting stop orders for `symbol`
    (_sum_resting_stop_qty(), not _find_resting_stop_order()'s single-
    order return, since multiple can now coexist) — a redelivered/
    duplicate event whose cumulative filled_qty is already fully covered
    computes a non-positive increment and is a safe no-op. The initial
    existence check is has_resting_protective_stop() — the SAME shared
    check protect_unprotected_fills() and submit_entry_and_stop() (the
    fill_listener.py fix-up's item 2) both gate on, so all three
    stop-submission paths in this module agree on "is this symbol
    already protected at all," not three separate reimplementations.

    KNOWN, FLAGGED CONSEQUENCE of allowing multiple resting stops per
    symbol, NOT resolved by this fix-up: build_open_positions() and
    ratchet_position_stop() (both this module) still assume exactly ONE
    resting stop per symbol — build_open_positions() calls _find_
    resting_stop_order(), which returns only the MOST RECENTLY submitted
    one when several exist. If a partial fill ever actually produces two
    resting stops, the daily ratchet will only ratchet whichever one
    build_open_positions() happened to pick, silently leaving the other
    at its original, increasingly-stale price. This is a real,
    previously-unconsidered gap surfaced by this fix-up, not fixed here
    — flagged for a fresh design call on whether build_open_positions()/
    ratchet_position_stop() need to sum/ratchet multiple resting stops,
    same "flag it, don't guess" convention as this module's other open
    gaps (module docstring).
    """
    if not has_resting_protective_stop(trading_client, symbol):
        order = submit_stop_order_with_retry(
            trading_client, symbol, qty, stop_price, backoff_seconds=backoff_seconds, sleep_fn=sleep_fn,
        )
        return order, (qty if order is not None else 0.0)

    total_protected = _sum_resting_stop_qty(trading_client, symbol)
    increment = qty - total_protected
    if increment <= _MIN_TOPUP_QTY:
        return _find_resting_stop_order(trading_client, symbol), 0.0

    order = submit_stop_order_with_retry(
        trading_client, symbol, increment, stop_price, backoff_seconds=backoff_seconds, sleep_fn=sleep_fn,
    )
    return order, (increment if order is not None else 0.0)


def replace_stop_order_if_favorable(trading_client: TradingClient, stop_order_id, candidate_stop_price: float, current_stop_price: float) -> bool:
    """
    Ratchet-only replace via Alpaca's order-replace (PATCH), not
    cancel-then-resubmit — avoids a window with no resting stop. Only
    replaces when the candidate is strictly more favorable (higher, for a
    long), matching compute_ratcheted_stop_price()'s max()-only ratchet.

    CONFIRMED AGAINST THE REAL PAPER API (dry-run milestone step):
    Alpaca rejects a PATCH replace on an order that is still in
    'accepted' status (HTTP 422, "cannot replace order in accepted
    status") — a newly-submitted stop order needs a short settle window
    (observed: still 'accepted' several seconds after submission) before
    it becomes replaceable. NOT expected to matter in real production
    use — the daily ratchet only ever runs once per day, long after any
    stop order submitted earlier that day (or on a prior day) has
    settled past 'accepted' — but exceptions from this call ARE allowed
    to propagate uncaught here; run_daily_execution_job()'s per-position
    try/except around ratchet_position_stop() is what turns this into a
    safe no-op (alert + "existing resting stop unchanged"), not this
    function itself.
    """
    if candidate_stop_price <= current_stop_price:
        return False
    trading_client.replace_order_by_id(stop_order_id, ReplaceOrderRequest(stop_price=round(candidate_stop_price, 2)))
    return True


def ratchet_position_stop(
    trading_client: TradingClient, position: LivePosition, series, today: str,
    atr_multiplier=ATR_MULTIPLIER, sleep_fn=time.sleep,
) -> bool:
    """
    Daily ratchet for one open position — recomputes extreme_close and
    the candidate new stop, then replaces EVERY resting stop for this
    symbol independently (fix-up item 3 — replaces the removed
    consolidation mechanism, see module docstring). Returns True if at
    least one resting stop's price actually changed.

    Independently re-queries ALL resting stops for position.symbol
    (_find_all_resting_stop_orders()) rather than trusting position.
    stop_order_id/stop_price alone — build_open_positions() already
    computes those conservatively (the worst/lowest price) for
    reporting/risk purposes, but the ACTUAL ratchet needs the full,
    current list of resting orders, not just a derived summary.

    MULTI-STOP CASE (the top-up model's leftover state — more than one
    resting stop for this symbol): a single target price is computed off
    the WORST/lowest of the existing stops' prices (same conservative
    basis the removed consolidation mechanism used), then applied to
    EACH resting stop independently via replace_stop_order_if_favorable()
    — the same single-stop PATCH-replace primitive already used and
    already confirmed working live, just invoked once per order. No new
    order is submitted, nothing is cancelled, qty is never touched on any
    of these calls — a symbol may legitimately carry N independently-
    ratcheted resting stops for its entire holding period; that is an
    accepted, permanent state now, not a leftover to be collapsed (see
    module docstring FIX-UP #3 for why the collapse attempt was removed).

    FIX-UP #4 (per-stop error isolation — closes the gap FIX-UP #3 left
    open): each resting stop's replace call below is wrapped in its OWN
    try/except, so one stop's failure no longer aborts the remaining
    stops for the same symbol — every resting stop is always attempted.
    Because build_open_positions()'s worst-price rule already means the
    symbol is exactly as protected after a partial (or total) failure as
    it was before this ratchet attempt (an unreplaced stop simply keeps
    its prior, still-valid price), a per-stop failure is deliberately NOT
    escalated through run_daily_execution_job()'s existing per-position
    try/except (whose alert text assumes all-or-nothing and would
    misdescribe a partial success) — instead this function sends its own
    single, non-urgent Telegram summary (see _send_ratchet_failure_
    summary()) naming which order(s) ratcheted to the new price and which
    remain at their old price with the error hit. Not urgent: tomorrow's
    ratchet pass will retry the stragglers automatically, unprompted. If
    every stop in the loop succeeds (regardless of whether any candidate
    was actually favorable enough to replace), no summary is sent and
    behavior is unchanged from before this fix-up.
    """
    as_of_idx = series["date_index"].get(today)
    if as_of_idx is None:
        return False
    prior_idx = as_of_idx - 1
    prior_atr = series["atr"][prior_idx] if prior_idx >= 0 else None
    if prior_atr is None:
        return False

    resting_stops = _find_all_resting_stop_orders(trading_client, position.symbol)
    if not resting_stops:
        return False  # defensive — build_open_positions() only ever includes positions WITH a resting stop

    extreme_close = compute_extreme_close_since_entry(series, position.entry_date, today)

    if len(resting_stops) == 1:
        candidate_stop = compute_ratcheted_stop_price(extreme_close, prior_atr, atr_multiplier, position.stop_price)
        return replace_stop_order_if_favorable(trading_client, position.stop_order_id, candidate_stop, position.stop_price)

    worst_current_price = min(float(o.stop_price) for o in resting_stops)
    candidate_stop = compute_ratcheted_stop_price(extreme_close, prior_atr, atr_multiplier, worst_current_price)
    results = []
    for order in resting_stops:
        old_price = float(order.stop_price)
        try:
            replaced = replace_stop_order_if_favorable(trading_client, order.id, candidate_stop, old_price)
            results.append({"order_id": order.id, "old_price": old_price, "replaced": replaced, "error": None})
        except Exception as exc:  # noqa: BLE001 — one stop's replace failure must not block ratcheting the rest of this symbol's resting stops
            results.append({"order_id": order.id, "old_price": old_price, "replaced": False, "error": str(exc)})

    if any(r["error"] is not None for r in results):
        _send_ratchet_failure_summary(position.symbol, candidate_stop, results)

    return any(r["replaced"] for r in results)


def _send_ratchet_failure_summary(symbol: str, candidate_stop: float, results: list) -> None:
    """
    Non-urgent Telegram summary for ratchet_position_stop()'s multi-stop
    branch (fix-up item 4) when one or more — up to all — per-order
    replace calls failed. Deliberately NOT the URGENT alert path: see
    that function's own docstring for why (build_open_positions()'s
    worst-price rule means the symbol is exactly as protected as before
    this ratchet attempt, and tomorrow's pass retries automatically).
    Always sent whenever any failure occurred, including when EVERY stop
    failed (zero successes) — so a persistent pattern (e.g. every replace
    for a symbol failing every day) stays visible in whatever this
    module's only reporting sink (telegram_bot.send_message()) records,
    even though it never pages a human.
    """
    succeeded = [r for r in results if r["error"] is None and r["replaced"]]
    failed = [r for r in results if r["error"] is not None]
    succeeded_desc = ", ".join(f"{r['order_id']} ({r['old_price']} -> {candidate_stop})" for r in succeeded) or "none"
    failed_desc = ", ".join(f"{r['order_id']} (stays at {r['old_price']}, error: {r['error']})" for r in failed) or "none"
    telegram_bot.send_message(
        f"execution.py: stop-ratchet for {symbol} — {len(succeeded)} of {len(results)} resting stop(s) ratcheted "
        f"to {candidate_stop}, {len(failed)} failed. Ratcheted: {succeeded_desc}. NOT ratcheted (unchanged price, "
        f"error): {failed_desc}. Not urgent — {symbol} is exactly as protected as before this ratchet attempt "
        f"(build_open_positions()'s worst-price rule), and tomorrow's ratchet pass will retry the stragglers "
        f"automatically."
    )


def submit_entry_and_stop(trading_client, candidate, decision, equity, guardrails, sleep_fn=time.sleep, poll_timeout_seconds=60) -> TrackBEntryResult:
    """
    Full entry flow for one approved candidate: compute the fixed stop
    price and pre-fill qty estimate, submit the entry market order, poll
    for fill, and (on any real fill) submit the resting GTC stop with
    retry+alert. See module docstring's flagged design-gap section for
    why the entry qty is a pre-fill PROXY, not the true post-fill
    risk-pinned size.

    `equity` (spec v53 §10.23, Milestone 1): the caller passes Track B's
    ALLOCATED sub-balance here (capital_ledger.get_available_capital(
    trading_client, config.TRACK_B_ALLOCATION_PCT) — 70% of current
    account equity), NOT the full account equity. Every equity-derived
    number computed below — the risk budget (`equity * position_size`),
    the notional cap (`cap_qty_to_notional`), and the realized-risk
    reporting (`compute_realized_risk`) — is therefore scaled to Track
    B's capital partition. The function itself is agnostic to what
    `equity` means; the partition is applied entirely at the call site.
    """
    symbol = candidate["symbol"]
    stop_price = compute_signal_day_stop_price(candidate["close"], candidate["atr"])
    risk_budget_amount = equity * (decision.position_size / 100)
    qty = estimate_pre_fill_qty(risk_budget_amount, candidate["close"], stop_price)
    qty = cap_qty_to_notional(qty, candidate["close"], equity, guardrails.max_position_size_pct)
    qty = round(qty, 4)

    if qty <= 0:
        return TrackBEntryResult(symbol=symbol, submitted=False, filled=False, reason="computed_qty_non_positive")

    # fill_listener.py stop-price handoff (spec v33 §10.5) — encoded
    # UNCONDITIONALLY, not just for the "pending" branch below, since a
    # market-hours same-session fill (confirmed synchronously in this
    # call) is ALSO visible to the listener over the trade_updates
    # WebSocket. FIX-UP (closes the race originally flagged here, not
    # just documents it): the stop submission below now gates on
    # has_resting_protective_stop(), the SAME shared check protect_
    # unprotected_fills() and fill_listener.py's handler already use —
    # if the listener (or a redelivered/near-simultaneous event) already
    # protected this exact fill via the SAME client_order_id-encoded
    # stop_price by the time this function gets there, this call detects
    # the existing resting stop and does NOT submit a duplicate. Same
    # caveat as every other check-then-act use of this pattern in this
    # module (protect_unprotected_fills() vs. the listener): this closes
    # the race to the SAME degree those two already close it for each
    # other, not via a distributed lock — a true same-instant race is
    # still theoretically possible, just no more so here than anywhere
    # else this pattern is already relied on. Real Track B entries are
    # always submitted post-close, so a genuine same-session fill
    # essentially never happens in production regardless (the original
    # execution.py dry run only saw one because it deliberately forced
    # an extended-hours fill for testing).
    signal_date = candidate["timestamp"][:10]
    client_order_id = encode_client_order_id(symbol, signal_date, stop_price)

    # Idempotency guard (spec v44 §10.13, module docstring's "PER-SYMBOL
    # DUPLICATE-ENTRY PROTECTION" section) — the SAME symbol firing the
    # SAME signal on the SAME day always produces this IDENTICAL client_
    # order_id, so an existing order under it means an earlier same-day
    # invocation of this function already submitted this exact entry.
    # Empirically confirmed (real paper account, alpaca-py 0.43.5): a
    # genuine not-found lookup raises APIError with status_code == 404 —
    # that is the ONLY outcome treated as "no duplicate, proceed"; any
    # other exception propagates to the caller's existing per-candidate
    # try/except rather than being silently resolved either way here.
    try:
        trading_client.get_order_by_client_id(client_order_id)
    except APIError as exc:
        if exc.status_code != 404:
            raise
    else:
        return TrackBEntryResult(symbol=symbol, submitted=False, filled=False, reason="duplicate_client_order_id_skipped")

    entry_order = submit_entry_market_order(trading_client, symbol, qty, client_order_id=client_order_id)
    entry_order = poll_order_until_terminal(trading_client, entry_order.id, timeout_seconds=poll_timeout_seconds, sleep_fn=sleep_fn)
    fill = confirm_entry_fill(entry_order)

    if fill["pending"]:
        # Expected, ordinary outcome for an order that will fill at next
        # session's open — NOT a failure, no alert. protect_unprotected_
        # fills() picks this up on a later run once it has actually
        # filled (module docstring's second flagged design gap).
        return TrackBEntryResult(symbol=symbol, submitted=True, filled=False, reason="pending_next_session_fill")

    if not fill["filled"]:
        telegram_bot.send_message(
            f"execution.py: entry order for {symbol} did not fill (status={fill['status']}) — no position opened, no stop needed."
        )
        return TrackBEntryResult(symbol=symbol, submitted=True, filled=False, reason=fill["status"])

    realized = compute_realized_risk(fill["filled_avg_price"], stop_price, fill["filled_qty"], equity)
    if has_resting_protective_stop(trading_client, symbol):
        # Already protected — by the listener, or a prior invocation —
        # before this call got here. Use the existing resting stop rather
        # than submitting a duplicate (see the comment at the client_
        # order_id encoding call site above for the full race-closure
        # reasoning).
        stop_order = _find_resting_stop_order(trading_client, symbol)
    else:
        stop_order = submit_stop_order_with_retry(trading_client, symbol, fill["filled_qty"], stop_price, sleep_fn=sleep_fn)

    return TrackBEntryResult(
        symbol=symbol,
        submitted=True,
        filled=True,
        filled_qty=fill["filled_qty"],
        filled_avg_price=fill["filled_avg_price"],
        stop_price=stop_price,
        stop_order_submitted=stop_order is not None,
        realized_risk_pct=realized["risk_pct"],
        target_risk_pct=decision.position_size,
    )


# =============================================================================
# Track B — daily orchestrator
# =============================================================================

def _build_live_trading_client() -> TradingClient:
    cfg = get_alpaca_config()
    return TradingClient(api_key=cfg.api_key, secret_key=cfg.secret_key, paper=cfg.paper)


def run_daily_execution_job(trading_client: TradingClient = None, universe=None, sleep_fn=time.sleep) -> dict:
    """
    The whole daily post-close job (spec's locked design). Returns a
    plain dict log of what happened — the caller is responsible for
    persisting it (spec §3.2 journaling is a separate milestone, not
    built here).

    Order of operations, per module docstring's fail-safe section:
      0. protect_unprotected_fills() — catches up any position that
         filled since the last run but never got a stop (module
         docstring's second flagged design gap: the overnight submit-to-
         fill gap generally spans multiple job invocations). Runs even
         while halted, same reasoning as the ratchet step below.
      1. Fetch account/position/market data. Any failure here halts BOTH
         the daily ratchet and new entries for today, but changes nothing
         about any resting stop order already on the exchange — existing
         positions stay exactly as protected as they were before this
         run, per the "independent of bot uptime" guarantee.
      2. Daily stop-ratchet for every open position — runs even if
         halt_state.py reports halted, since it only ever tightens
         protection, never opens new risk.
      3. New entries — skipped entirely while halted.
    """
    if trading_client is None:
        trading_client = _build_live_trading_client()
    if universe is None:
        universe = TRACK_B_UNIVERSE

    run_log = {"date": None, "protected": [], "ratcheted": [], "entries_submitted": [], "entries_skipped": [], "errors": [], "halted": False, "track_b_ledger": {}}

    try:
        symbol_data = fetch_track_b_symbol_data(universe)
        run_log["protected"] = protect_unprotected_fills(trading_client, universe, symbol_data, sleep_fn=sleep_fn)
        open_positions = build_open_positions(trading_client, universe)
        account_state = build_account_state(trading_client)
        # spec v55 §10.25: self-heal the position-ownership ledger from
        # Alpaca truth every run — the daily fallback for anything
        # fill_listener.py's real-time updates missed.
        run_log["track_b_ledger"] = heal_track_b_ownership_ledger(trading_client, universe)
    except Exception as exc:  # noqa: BLE001 — fail-safe boundary, must not crash the caller
        telegram_bot.send_message(
            f"execution.py: daily job data fetch failed ({exc}) — skipped for today. "
            f"Existing positions remain protected by their resting GTC stop orders regardless of bot uptime."
        )
        run_log["errors"].append({"step": "data_fetch", "error": str(exc)})
        return run_log

    today = _latest_shared_date(symbol_data)
    run_log["date"] = today
    if today is None:
        return run_log

    for position in open_positions:
        series = symbol_data.get(position.symbol)
        if series is None:
            continue
        try:
            if ratchet_position_stop(trading_client, position, series, today, sleep_fn=sleep_fn):
                run_log["ratcheted"].append(position.symbol)
        except Exception as exc:  # noqa: BLE001 — one symbol's ratchet failure must not sink the run
            telegram_bot.send_message(
                f"execution.py: stop-ratchet failed for {position.symbol} ({exc}) — existing resting stop unchanged."
            )
            run_log["errors"].append({"symbol": position.symbol, "step": "ratchet", "error": str(exc)})

    halt = halt_state.load_halt_state()
    if halt.halted:
        run_log["halted"] = True
        run_log["halt_reason"] = halt.reason
        return run_log

    guardrails = get_track_b_guardrail_config()
    # Capital partition (spec v53 §10.23, Milestone 1): Track B sizes
    # every new position against its 70% sub-balance of current account
    # equity, not the full account — so it never double-counts capital
    # reserved for the future Track C. Pulled fresh here (its own GET
    # /v2/account) at the moment of sizing, per capital_ledger's
    # no-stale-value contract. Account-level HALT guardrails
    # (daily-loss / drawdown in evaluate() below) deliberately still see
    # full-account equity via `account_state` — those halt the whole bot
    # and are not a per-track sizing concern.
    track_b_sizing_equity = capital_ledger.get_available_capital(trading_client, TRACK_B_ALLOCATION_PCT)
    open_symbols = {p.symbol for p in open_positions}
    candidates = generate_daily_candidates(symbol_data, universe, open_symbols, today)
    today_entry_count = get_today_entry_count(trading_client, universe, today=datetime.fromisoformat(today).date())
    live_open_positions = list(open_positions)

    for candidate in candidates:
        signal = TradeSignal(
            symbol=candidate["symbol"], direction=SignalDirection.LONG,
            entry_price=candidate["close"], atr=candidate["atr"], timestamp=candidate["timestamp"],
        )
        decision = evaluate(signal, account_state, live_open_positions, today_entry_count, guardrails)
        if not decision.approved:
            run_log["entries_skipped"].append({"symbol": candidate["symbol"], "reason": decision.reason})
            continue

        try:
            result = submit_entry_and_stop(trading_client, candidate, decision, track_b_sizing_equity, guardrails, sleep_fn=sleep_fn)
        except Exception as exc:  # noqa: BLE001 — one symbol's entry failure must not sink the run or other candidates
            telegram_bot.send_message(f"execution.py: entry flow raised for {candidate['symbol']} ({exc})")
            run_log["errors"].append({"symbol": candidate["symbol"], "step": "entry", "error": str(exc)})
            continue

        run_log["entries_submitted"].append(result)
        if result.filled:
            today_entry_count += 1
            live_open_positions.append(SimpleNamespace(symbol=candidate["symbol"], risk_pct=result.realized_risk_pct or 0.0))

    return run_log


def send_daily_heartbeat(run_log: dict, heartbeat_url: str = None, requests_module=requests) -> bool:
    """
    Dead-man's-switch ping (spec v34 §10.6, systemd-units milestone) —
    fired once at the end of a run_daily_execution_job() call that
    completed with no per-step errors recorded in run_log["errors"].
    Healthchecks.io alerts if this ping doesn't arrive within its
    configured window (~26h) — this catches the daily job/timer not
    running at all (crash before returning, disabled timer, host down), a
    failure mode none of this module's existing Telegram alerts cover,
    since those all fire FROM INSIDE a run that's already happening. A
    halted run (halt_state.py) still counts as healthy for this purpose —
    halting is an intentional, already-alerted state (see
    check_daily_loss_limit()/check_drawdown_limit(), risk_filter.py), not
    a job malfunction; the heartbeat's only job is proving the process
    itself is still alive and completing runs.

    Best-effort only, deliberately: a failed ping is logged and returns
    False, never raised — a monitoring-side hiccup (network blip,
    Healthchecks.io outage) must never be mistaken for, or cause, a daily
    job failure.

    Provider note (spec v38 §10.8): pings HEALTHCHECKS_DAILY_HEARTBEAT_URL
    (renamed from UPTIMEROBOT_DAILY_JOB_HEARTBEAT_URL when the
    heartbeat-monitoring provider switched from UptimeRobot to
    Healthchecks.io) — rename only, this function's behavior is unchanged.
    """
    if heartbeat_url is None:
        heartbeat_url = get_heartbeat_config().daily_job_url
    if not heartbeat_url:
        log.warning("send_daily_heartbeat: HEALTHCHECKS_DAILY_HEARTBEAT_URL not set — skipping heartbeat ping.")
        return False
    if run_log.get("errors"):
        return False
    try:
        requests_module.get(heartbeat_url, timeout=10)
        return True
    except Exception as exc:  # noqa: BLE001 — a monitoring ping failure must never fail the job
        log.warning(f"send_daily_heartbeat: ping failed ({exc}) — job itself still succeeded.")
        return False


def main() -> None:
    """
    systemd ExecStart target for trading-bot-daily.service (spec v34
    §10.6). Extracted from a bare `if __name__ == "__main__":` block into
    this callable (spec v42 §10.11, daily-job per-symbol DEBUG-logging
    milestone) so LOG_LEVEL wiring and the INFO summary line are both
    directly unit-testable — same calls, same order, no behavior change
    from before this milestone.

    Halt-state-on-boot is already handled inside run_daily_execution_job()
    itself (gates new entries only, per its own docstring's "Order of
    operations" — the ratchet step deliberately still runs while halted)
    — no separate check needed here. An unhandled exception escaping
    run_daily_execution_job() itself (e.g. missing required config) is
    intentionally left unswallowed: it propagates, prints a traceback,
    and exits non-zero, which is the correct, visible "this oneshot run
    failed" signal for systemd/journalctl, distinct from and
    complementary to the per-step Telegram alerts already inside the job
    for known error paths.
    """
    logging.basicConfig(level=get_log_level(), format="%(asctime)s %(levelname)s %(message)s")
    run_log = run_daily_execution_job()
    log.info("run_daily_execution_job() result: %s", run_log)
    send_daily_heartbeat(run_log)


if __name__ == "__main__":
    main()
