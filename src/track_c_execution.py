"""
Track C (DMSR) live execution — the monthly sector-rotation rebalance
job (spec v59 §10.29, Milestone 4; corrected spec v60 §10.30). One call
to run_track_c_execution_job() is the whole job; the timer fires it
every weekday post-close and the job self-gates internally so almost
every run is a cheap no-op. Structurally mirrors src/execution.py's role
for Track B.

=====================================================================
SEQUENCE (every invocation)
=====================================================================
1.  HALT CHECK — halt_state.load_track_c_halt(). If halted: log and
    return immediately. No orders, no ledger heal. (Track C's own halt
    file, independent of Track B's — spec v55 §10.25.)
2.  HEAL (start-of-run) — track_positions.heal_track_c_ownership_ledger()
    over SECTOR_UNIVERSE + [AGG]. A heal failure aborts the run before
    any decision — a wrong ledger must never drive a sell.
2b. RESOLVE PENDING WORK (spec v60 §10.30) — runs on EVERY invocation,
    rebalance day or not, before the fetch/self-gate. Retries any buy
    leg a prior rebalance couldn't fill, and runs the MANDATORY
    reconcile-with-halt (track_positions.reconcile_symbol()) for symbols
    a prior rebalance touched — see the "PENDING-COMPLETION TRACKING"
    section below.
3.  FETCH + SELF-GATE — ~450 trailing calendar days of Adjustment.SPLIT
    daily bars for the 11 sectors + AGG + SPY; derive the trading
    calendar from SPY's own bar timestamps; dmsr_signal.is_rebalance_
    day(). Not a rebalance day (the common case) -> skip to step 7.
4.  DECIDE — trailing-12-month SPY return (absolute-momentum filter),
    sector ranks, current_holdings from the FRESHLY-HEALED track_c
    ledger (NEVER Alpaca's raw positions), dmsr_signal.select_target_
    holdings().
5.  EXECUTE, SELL THEN BUY, sequentially:
    a) SELLs — for each held name not in target, a QUANTITY-BASED market
       SELL for EXACTLY track_positions.get_track_qty("track_c", symbol)
       shares. *** SAFETY-CRITICAL: the quantity is the LEDGER's figure,
       never Alpaca's raw combined position. For AGG (shared with Track
       B) the raw position includes Track B's shares; selling that would
       liquidate Track B's holding. See _submit_sell(). ***
       A submitted sell -> that symbol is added to
       pending_reconcile_symbols for a LATER invocation to reconcile.
    b) allocated_capital = capital_ledger.get_available_capital(...,
       config.TRACK_C_ALLOCATION_PCT), fetched fresh AFTER the sells.
    c) BUYs — for each target name not already held, a NOTIONAL market
       BUY: 100% of allocated_capital if risk-off (buying AGG), else
       allocated_capital / 3. A submitted buy -> pending_reconcile_
       symbols. A buy that FAILS to submit / is rejected (GAP B —
       insufficient buying power until the sells settle) -> pending_
       retry_buys, retried on later invocations, NOT a job failure.
    Every order carries client_order_id "tc-{symbol}-{YYYYMMDD}" (spec
    v57 §10.27 — the "tc-" prefix is what lets the shared fill listener
    attribute the fill to Track C).
6.  RECONCILE (soft) — re-fetch resulting positions, compare to target,
    send a NON-halting Telegram note if a leg looks unfilled. This is a
    "did the rebalance do what it intended" sanity check, SEPARATE from
    the mandatory ledger-integrity reconcile in step 2b.
7.  HEAL (end-of-run) — heal the track_c ledger again to pick up today's
    fills; persist pending state; then main() pings the heartbeat.

=====================================================================
PENDING-COMPLETION TRACKING (spec v60 §10.30 correction)
=====================================================================
WHY: track_positions.reconcile_symbol()'s check (ledger_b + ledger_c ==
alpaca_total for a symbol) is only meaningful once the fills it is
checking have actually SETTLED. Track C orders are submitted post-close
and fill at the NEXT session's open (the same mechanical fact behind GAP
A/B below). Calling reconcile_symbol() in the SAME invocation that just
submitted still-pending orders would guarantee a mismatch on EVERY
rebalance — a false-halt "crying wolf" risk. So the mandatory reconcile
is DEFERRED to a later invocation via a persisted state file.

track_c_pending_state.json (path overridable via TRACK_C_PENDING_STATE_
PATH; gitignored; same read-fresh / write-back / hand-auditable JSON
convention as halt_state.json / track_positions_state.json). Shape:

    {"pending_reconcile_symbols": ["AGG", "XLK"],
     "pending_retry_buys": {"XLK": 1}}

pending_retry_buys maps symbol -> consecutive-failed-retry count; at
_MAX_BUY_RETRIES (3) the retry is abandoned with an URGENT alert until
the next scheduled monthly rebalance.

ORDERING GUARANTEE (walk-through): within one invocation, step 2b runs
BEFORE steps 3-6. The reconcile pass in 2b operates on a SNAPSHOT of
pending_reconcile_symbols taken at the START of 2b — so the ONLY symbols
it can reconcile are ones written by a PRIOR invocation's step 5. The
symbols today's step 5 adds are appended to the state AFTER 2b has
already finished and are first seen by the NEXT invocation's 2b. A buy
retried successfully during 2b is likewise added to pending_reconcile_
symbols for a LATER invocation, never checked in the same 2b that
retried it. Net: reconcile_symbol() is NEVER called in the same
invocation that submitted the orders being reconciled.

=====================================================================
FLAGGED DESIGN GAP — still open after the v60 correction
=====================================================================
GAP A — post-close fill timing. "Confirm each fill before moving to the
next" cannot be literally satisfied within one post-close invocation: a
market order submitted at ~17:00 ET fills at the next session's open,
hours (or over a weekend, days) later. This module mirrors execution.py's
short poll (poll_order_until_terminal, 60s) and treats a still-open
zero-fill order as an EXPECTED "pending" outcome, not a failure. The v60
pending-completion mechanism is what makes this correct end to end (the
mandatory reconcile and any buy retry both happen on a later invocation,
once fills have settled) — but the raw fact that a Track C order is
unconfirmed for up to ~1 trading day after submission remains, and is
inherent to a daily-cadence, post-close job.

RESOLVED by the v60 correction: GAP B (buy-rejection retry — bounded at
_MAX_BUY_RETRIES consecutive business-day attempts via pending_retry_
buys), GAP C (the mandatory reconcile_symbol()-with-halt from spec v55
§10.25, deferred via pending_reconcile_symbols), GAP D (fetch window
400 -> 450 calendar days).

NOTE (spec v60 §10.30, flagged not silent): the brief listed step 2b's
retry pass before its reconcile pass. Taken literally that would let a
buy retried-successfully in 2b be reconciled by the SAME 2b — a
same-invocation reconcile of a just-submitted (still-pending) order, the
exact false-halt the whole correction avoids. Resolved by the SNAPSHOT
above (reconcile pass sees only what was pending at 2b entry). Also
flagged: after 2b's reconcile halts Track C on a mismatch, this
invocation does NOT proceed to submit a new rebalance's orders (a safety
addition beyond the brief's literal text — the brief only guarantees the
NEXT invocation's step-1 halt-check short-circuits; submitting orders
into a just-detected integrity failure would be wrong).
"""
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone

import requests
from alpaca.common.exceptions import APIError
from alpaca.data.enums import Adjustment
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, OrderStatus, TimeInForce
from alpaca.trading.requests import MarketOrderRequest

from . import capital_ledger
from . import config
from . import dmsr_signal
from . import halt_state
from . import telegram_bot
from . import track_positions
from .config import get_alpaca_config, get_log_level, get_track_c_heartbeat_config
from .data_ingestion import fetch_historical_stock_candles
from .execution import poll_order_until_terminal

log = logging.getLogger(__name__)

# Trailing daily-bar history to pull each run. 450 calendar days (spec
# v60 §10.30, up from 400) comfortably covers a 12-month month-end-to-
# month-end trailing return plus a holiday/weekend buffer. The DECIDE
# step still guards against it being too short rather than assuming.
SIGNAL_LOOKBACK_DAYS = 450

# Track C's (not-yet-built) execution... symbols whose track_c ownership
# the ledger heal covers (spec v57 §10.27): the 11 sectors + the
# risk-off asset.
HEAL_UNIVERSE = dmsr_signal.SECTOR_UNIVERSE + [dmsr_signal.DEFENSIVE_ASSET]

# All symbols the signal needs priced: sectors + risk-off asset + market
# filter. (BIL, the backtest's Sharpe risk-free proxy, is reporting-only
# and not needed live.)
_FETCH_UNIVERSE = dmsr_signal.SECTOR_UNIVERSE + [dmsr_signal.DEFENSIVE_ASSET, dmsr_signal.MARKET_FILTER_SYMBOL]

# Pending-completion state (spec v60 §10.30) — Track-C-only, NOT in the
# shared track_positions.py. Same env-overridable / gitignored / default-
# at-CWD convention as halt_state.json.
_PENDING_STATE_PATH = os.environ.get("TRACK_C_PENDING_STATE_PATH", "track_c_pending_state.json")
_MAX_BUY_RETRIES = 3

_TERMINAL_NO_FILL_STATUSES = {
    OrderStatus.CANCELED, OrderStatus.EXPIRED, OrderStatus.REJECTED,
    OrderStatus.DONE_FOR_DAY, OrderStatus.STOPPED,
}


def _build_live_trading_client() -> TradingClient:
    cfg = get_alpaca_config()
    return TradingClient(api_key=cfg.api_key, secret_key=cfg.secret_key, paper=cfg.paper)


def _client_order_id(symbol: str, date_compact: str) -> str:
    """
    "tc-{symbol}-{YYYYMMDD}" (spec v57 §10.27 / v59 brief Change C). The
    "tc-" prefix is track_positions.is_track_c_client_order_id()'s check
    — the ONLY signal the shared fill listener has to attribute a fill to
    Track C. No sequence suffix: Track C trades a symbol at most once per
    day by construction; an accidental same-day re-run is caught by
    _order_already_submitted() (and would be rejected by Alpaca anyway).
    A buy RETRY (spec v60) uses the retry-invocation's own date here, so
    each retry gets a fresh id rather than colliding with the failed
    original.
    """
    return f"{track_positions.TRACK_C_CLIENT_ORDER_ID_PREFIX}-{symbol}-{date_compact}"


# =====================================================================
# Pending-completion state (spec v60 §10.30)
# =====================================================================

def _empty_pending() -> dict:
    return {"pending_reconcile_symbols": [], "pending_retry_buys": {}}


def load_pending_state() -> dict:
    """Read fresh at the start of every invocation. A missing/short file normalises to the empty shape, never raises."""
    if not os.path.exists(_PENDING_STATE_PATH):
        return _empty_pending()
    with open(_PENDING_STATE_PATH) as f:
        raw = json.load(f)
    return {
        "pending_reconcile_symbols": list(raw.get("pending_reconcile_symbols") or []),
        "pending_retry_buys": {k: int(v) for k, v in (raw.get("pending_retry_buys") or {}).items()},
    }


def save_pending_state(state: dict) -> None:
    with open(_PENDING_STATE_PATH, "w") as f:
        json.dump(
            {
                "pending_reconcile_symbols": sorted(set(state.get("pending_reconcile_symbols") or [])),
                "pending_retry_buys": dict(state.get("pending_retry_buys") or {}),
            },
            f, indent=2, sort_keys=True,
        )


def _queue_reconcile(state: dict, symbol: str) -> None:
    if symbol not in state["pending_reconcile_symbols"]:
        state["pending_reconcile_symbols"].append(symbol)


def _queue_retry_buy(state: dict, symbol: str) -> None:
    state["pending_retry_buys"].setdefault(symbol, 0)


# =====================================================================
# Signal data
# =====================================================================

def fetch_track_c_symbol_data(end=None, lookback_days=SIGNAL_LOOKBACK_DAYS) -> dict:
    """
    Trailing daily-bar pull for the signal, Adjustment.SPLIT (the
    backtest's validated basis — split-adjusted, NOT dividend-adjusted;
    Adjustment.RAW is broken for this universe, the 2025-12-05 SPDR 2:1
    splits). Returns {symbol: {"symbol", "candles", "date_index"}}.
    Raises if any symbol returns no bars — the signal cannot be computed
    with a gap.
    """
    if end is None:
        end = datetime.now(timezone.utc) - timedelta(minutes=20)  # SIP recent-data embargo, same convention as the backtests
    start = end - timedelta(days=lookback_days)

    symbol_data = {}
    for symbol in _FETCH_UNIVERSE:
        candles = fetch_historical_stock_candles(symbol, start, end, adjustment=Adjustment.SPLIT)
        if not candles:
            raise RuntimeError(f"no daily bars returned for {symbol} over the trailing {lookback_days}-day window")
        date_index = {c.timestamp[:10]: i for i, c in enumerate(candles)}
        symbol_data[symbol] = {"symbol": symbol, "candles": candles, "date_index": date_index}
        log.debug("[%s] fetch: %d bars, %s -> %s", symbol, len(candles), candles[0].timestamp[:10], candles[-1].timestamp[:10])
    return symbol_data


def _spy_calendar(symbol_data) -> list:
    """The trading calendar, derived from SPY's own returned bar timestamps (v59 brief step 3)."""
    return sorted(symbol_data[dmsr_signal.MARKET_FILTER_SYMBOL]["date_index"].keys())


# =====================================================================
# Order plumbing
# =====================================================================

def _order_already_submitted(trading_client, client_order_id: str) -> bool:
    """
    Mirrors execution.py's spec v44 per-symbol duplicate-entry guard: a
    genuine not-found get_order_by_client_id() lookup raises APIError
    with .status_code == 404 (empirically confirmed, alpaca-py 0.43.5).
    404 -> proceed; an existing order -> already submitted (an accidental
    same-day re-run), skip; any other APIError -> re-raise.
    """
    try:
        trading_client.get_order_by_client_id(client_order_id)
    except APIError as exc:
        if exc.status_code == 404:
            return False
        raise
    return True


def _classify_order(polled) -> str:
    """filled (any real fill) / rejected (terminal, zero fill) / pending (still open, zero fill — the expected post-close state)."""
    if float(getattr(polled, "filled_qty", 0) or 0) > 0:
        return "filled"
    if getattr(polled, "status", None) in _TERMINAL_NO_FILL_STATUSES:
        return "rejected"
    return "pending"


def _current_holdings_from_ledger() -> list:
    """
    Symbols Track C currently owns, per the (freshly healed) track_c
    ownership ledger — NEVER Alpaca's raw positions. A prior risk-off
    month shows up here as exactly ["AGG"].
    """
    return [
        s for s in HEAL_UNIVERSE
        if track_positions.get_track_qty("track_c", s) > track_positions.RECONCILE_EPSILON
    ]


def _submit_sell(trading_client, symbol: str, date_compact: str, sleep_fn) -> dict:
    """
    QUANTITY-BASED market SELL of EXACTLY Track C's ledgered share count.

    *** SAFETY-CRITICAL (spec v56 §10.26 hard precondition): the quantity
    is track_positions.get_track_qty("track_c", symbol) — Track C's OWN
    ledgered holding — and NEVER Alpaca's raw combined position. For AGG,
    which Track B also trades directly, the raw combined position
    includes Track B's shares; selling "the AGG position" would liquidate
    Track B's holding. This function calls no Alpaca position endpoint. ***
    """
    qty = track_positions.get_track_qty("track_c", symbol)
    if qty <= track_positions.RECONCILE_EPSILON:
        return {"symbol": symbol, "action": "sell", "skipped": "ledger_qty_zero", "qty": 0.0}

    client_order_id = _client_order_id(symbol, date_compact)
    if _order_already_submitted(trading_client, client_order_id):
        return {"symbol": symbol, "action": "sell", "skipped": "duplicate_client_order_id",
                "qty": qty, "client_order_id": client_order_id}

    order = trading_client.submit_order(MarketOrderRequest(
        symbol=symbol, qty=qty, side=OrderSide.SELL,
        time_in_force=TimeInForce.DAY, client_order_id=client_order_id,
    ))
    polled = poll_order_until_terminal(trading_client, order.id, sleep_fn=sleep_fn)
    return {
        "symbol": symbol, "action": "sell", "qty": qty, "client_order_id": client_order_id,
        "order_id": str(order.id), "status": str(polled.status), "filled_qty": float(polled.filled_qty or 0),
        "outcome": _classify_order(polled),
    }


def _submit_buy(trading_client, symbol: str, notional: float, date_compact: str, sleep_fn) -> dict:
    """NOTIONAL market BUY sized in dollars."""
    client_order_id = _client_order_id(symbol, date_compact)
    if _order_already_submitted(trading_client, client_order_id):
        return {"symbol": symbol, "action": "buy", "skipped": "duplicate_client_order_id",
                "notional": round(notional, 2), "client_order_id": client_order_id}

    order = trading_client.submit_order(MarketOrderRequest(
        symbol=symbol, notional=round(notional, 2), side=OrderSide.BUY,
        time_in_force=TimeInForce.DAY, client_order_id=client_order_id,
    ))
    polled = poll_order_until_terminal(trading_client, order.id, sleep_fn=sleep_fn)
    return {
        "symbol": symbol, "action": "buy", "notional": round(notional, 2), "client_order_id": client_order_id,
        "order_id": str(order.id), "status": str(polled.status), "filled_qty": float(polled.filled_qty or 0),
        "outcome": _classify_order(polled),
    }


# =====================================================================
# STEP 2b — resolve pending work from a prior rebalance (spec v60 §10.30)
# =====================================================================

def _retry_buy_notional(trading_client, symbol: str) -> float:
    """FRESH sizing for a retried buy — recomputed from CURRENT equity, never the stale failed amount."""
    allocated = capital_ledger.get_available_capital(trading_client, config.TRACK_C_ALLOCATION_PCT)
    return allocated if symbol == dmsr_signal.DEFENSIVE_ASSET else allocated / dmsr_signal.TOP_N_HOLD


def _resolve_pending_work(trading_client, state: dict, run_log: dict, sleep_fn) -> None:
    """
    Runs on EVERY invocation, before the fetch/self-gate, regardless of
    whether today is a rebalance day. See the module docstring's
    "PENDING-COMPLETION TRACKING" section for the ordering guarantee that
    keeps reconcile_symbol() out of the same invocation that submitted
    the orders being reconciled.
    """
    step_log = {"retries_attempted": [], "retries_succeeded": [], "retries_gave_up": [], "reconciled": []}

    # Snapshot BEFORE the retry pass — a retry that succeeds below is
    # queued for a LATER invocation's reconcile, not this one.
    reconcile_snapshot = list(state["pending_reconcile_symbols"])

    # --- retry pass ---
    for symbol in list(state["pending_retry_buys"].keys()):
        step_log["retries_attempted"].append(symbol)
        today_compact = datetime.now(timezone.utc).strftime("%Y%m%d")
        try:
            notional = _retry_buy_notional(trading_client, symbol)
            rec = _submit_buy(trading_client, symbol, notional, today_compact, sleep_fn)
            failed = rec.get("outcome") == "rejected"
            detail = rec.get("outcome") or rec.get("skipped")
        except Exception as exc:  # noqa: BLE001 — a retry failure is a handled, bounded condition, not a job crash
            failed, detail = True, str(exc)

        if not failed:
            state["pending_retry_buys"].pop(symbol, None)
            _queue_reconcile(state, symbol)
            step_log["retries_succeeded"].append(symbol)
        else:
            state["pending_retry_buys"][symbol] = state["pending_retry_buys"].get(symbol, 0) + 1
            if state["pending_retry_buys"][symbol] >= _MAX_BUY_RETRIES:
                state["pending_retry_buys"].pop(symbol, None)
                step_log["retries_gave_up"].append(symbol)
                telegram_bot.send_message(
                    f"URGENT — track_c_execution: BUY for {symbol} has failed {_MAX_BUY_RETRIES} consecutive "
                    f"business-day retry attempts (last: {detail}). Giving up until the next scheduled monthly "
                    f"rebalance — Track C is under-allocated for {symbol}. Manual review required."
                )
        save_pending_state(state)

    # --- reconcile pass (on the pre-retry snapshot only) ---
    for symbol in reconcile_snapshot:
        try:
            result = track_positions.reconcile_symbol(trading_client, symbol)
        except Exception as exc:  # noqa: BLE001 — a transient reconcile failure leaves the symbol queued for next time
            run_log["errors"].append({"step": "step_2b_reconcile", "symbol": symbol, "error": str(exc)})
            telegram_bot.send_message(
                f"track_c_execution: deferred reconcile for {symbol} raised ({exc}) — left queued, retried next invocation."
            )
            continue
        step_log["reconciled"].append(
            {"symbol": symbol, "matched": result.matched, "halted_track_c": result.halted_track_c}
        )
        # Remove regardless of matched/mismatched outcome — reconcile_
        # symbol() has already halted + alerted on a mismatch itself.
        if symbol in state["pending_reconcile_symbols"]:
            state["pending_reconcile_symbols"].remove(symbol)
        save_pending_state(state)

    run_log["step_2b"] = step_log


# =====================================================================
# Rebalance body (steps 3-6)
# =====================================================================

def _reconcile_after_rebalance(trading_client, target, run_log) -> None:
    """
    v59 brief step 6 — SOFT, alert-only "did the rebalance do what it
    intended" check. SEPARATE from step 2b's mandatory ledger-integrity
    reconcile_symbol()-with-halt. Never halts, never resizes.
    """
    positions = {p.symbol: float(p.qty) for p in trading_client.get_all_positions()}
    problems = []
    for s in target:
        if positions.get(s, 0.0) <= track_positions.RECONCILE_EPSILON:
            problems.append(f"{s}: in target but no resulting position (entry likely still pending — market orders submitted post-close fill at next open)")
    for entry in run_log["sold"]:
        s = entry["symbol"]
        if entry.get("skipped"):
            continue
        if positions.get(s, 0.0) > track_positions.RECONCILE_EPSILON:
            problems.append(f"{s}: sold this rebalance but a position remains (exit likely still pending)")

    run_log["reconcile"] = problems
    if problems:
        telegram_bot.send_message(
            "track_c_execution: post-rebalance reconciliation — "
            f"{len(problems)} position(s) not yet matching target:\n" + "\n".join(problems)
            + "\nExpected when orders are submitted post-close (they fill at next session's open); a problem "
            "only if it persists past the next trading session. The mandatory ledger-integrity reconcile runs "
            "on a later invocation once fills settle (spec v60 §10.30). No automatic action taken here."
        )


def _heal_end_of_run(trading_client, run_log) -> None:
    try:
        run_log["track_c_ledger_end"] = track_positions.heal_track_c_ownership_ledger(trading_client, HEAL_UNIVERSE)
    except Exception as exc:  # noqa: BLE001 — corrected on the next run
        telegram_bot.send_message(f"track_c_execution: end-of-run track_c ledger heal failed ({exc}).")
        run_log["errors"].append({"step": "heal_end", "error": str(exc)})


def _run_rebalance_body(trading_client, sleep_fn, run_log, pending) -> None:
    """Steps 3-6. Catches its own per-step failures into run_log; never raises. Mutates `pending` in place (step 5)."""
    try:
        symbol_data = fetch_track_c_symbol_data()
    except Exception as exc:  # noqa: BLE001 — fail-safe: skip today, nothing left unprotected (Track C is no-stop-by-design)
        telegram_bot.send_message(
            f"track_c_execution: data fetch failed ({exc}) — rebalance skipped for today. Track C holds no stop "
            f"orders (no-stop-by-design), so nothing is left unprotected; the next run retries."
        )
        run_log["errors"].append({"step": "data_fetch", "error": str(exc)})
        return

    calendar = _spy_calendar(symbol_data)
    run_log["date"] = calendar[-1] if calendar else None

    if not dmsr_signal.is_rebalance_day(calendar):
        log.info("track_c_execution: %s is not a rebalance day — no-op.", run_log["date"])
        return

    run_log["rebalance_day"] = True

    try:
        month_end_dates = dmsr_signal.compute_month_end_dates(calendar)
        t = len(month_end_dates) - 1
        if t < dmsr_signal.LOOKBACK_MONTHS:
            raise RuntimeError(
                f"only {len(month_end_dates)} completed month-end(s) in the {SIGNAL_LOOKBACK_DAYS}-day window; "
                f"need {dmsr_signal.LOOKBACK_MONTHS + 1} for a {dmsr_signal.LOOKBACK_MONTHS}-month trailing return"
            )
        if month_end_dates[t] != calendar[-2]:
            raise RuntimeError(
                f"rebalance-day invariant violated: most recent month-end {month_end_dates[t]} != yesterday {calendar[-2]}"
            )
        signal_date = month_end_dates[t]
        spy_return = dmsr_signal.trailing_return(symbol_data[dmsr_signal.MARKET_FILTER_SYMBOL], month_end_dates, t)
        ranked = dmsr_signal.rank_sectors(symbol_data, month_end_dates, t)
        current_holdings = _current_holdings_from_ledger()
        target, risk_off = dmsr_signal.select_target_holdings(current_holdings, ranked, spy_return)
    except Exception as exc:  # noqa: BLE001 — a signal failure on a rebalance day must NOT submit any order
        telegram_bot.send_message(
            f"track_c_execution: signal computation failed on rebalance day {run_log['date']} ({exc}) — "
            f"NO orders submitted. Manual review required."
        )
        run_log["errors"].append({"step": "decide", "error": str(exc)})
        return

    run_log["signal_date"] = signal_date
    run_log["risk_off"] = risk_off
    run_log["spy_trailing_return"] = spy_return
    run_log["ranked"] = [(s, r) for s, r in ranked]
    run_log["current_holdings"] = list(current_holdings)
    run_log["target"] = list(target)

    date_compact = run_log["date"].replace("-", "")

    # --- 5a. SELLs ---
    for symbol in [s for s in current_holdings if s not in target]:
        try:
            rec = _submit_sell(trading_client, symbol, date_compact, sleep_fn)
            run_log["sold"].append(rec)
            if not rec.get("skipped"):
                _queue_reconcile(pending, symbol)
        except Exception as exc:  # noqa: BLE001 — one leg's failure must not sink the rest
            telegram_bot.send_message(
                f"URGENT — track_c_execution: SELL for {symbol} failed on rebalance {run_log['date']} ({exc}). "
                f"Track C may still hold a position it intended to exit. Manual intervention required."
            )
            run_log["errors"].append({"symbol": symbol, "step": "sell", "error": str(exc)})

    # --- 5b. allocated capital, fetched fresh AFTER the sells ---
    allocated_capital = capital_ledger.get_available_capital(trading_client, config.TRACK_C_ALLOCATION_PCT)
    run_log["allocated_capital"] = allocated_capital
    per_name_notional = allocated_capital if risk_off else allocated_capital / dmsr_signal.TOP_N_HOLD

    # --- 5c. BUYs ---
    for symbol in [s for s in target if s not in current_holdings]:
        try:
            rec = _submit_buy(trading_client, symbol, per_name_notional, date_compact, sleep_fn)
            run_log["bought"].append(rec)
            if rec.get("skipped"):
                _queue_reconcile(pending, symbol)  # a same-day duplicate means the order WAS submitted
            elif rec["outcome"] == "rejected":
                _queue_retry_buy(pending, symbol)
                telegram_bot.send_message(
                    f"track_c_execution: BUY for {symbol} was rejected (status {rec['status']}) on rebalance "
                    f"{run_log['date']} — queued for retry (up to {_MAX_BUY_RETRIES} business-day attempts)."
                )
            else:  # filled or pending
                _queue_reconcile(pending, symbol)
        except Exception as exc:  # noqa: BLE001 — GAP B: a rejected buy (e.g. insufficient buying power) is retried, not a job failure
            _queue_retry_buy(pending, symbol)
            run_log["bought"].append({
                "symbol": symbol, "action": "buy", "notional": round(per_name_notional, 2),
                "outcome": "submit_failed", "error": str(exc), "queued_retry": True,
            })
            telegram_bot.send_message(
                f"track_c_execution: BUY for {symbol} (notional ${per_name_notional:,.2f}) failed to submit on "
                f"rebalance {run_log['date']} ({exc}) — queued for retry (up to {_MAX_BUY_RETRIES} business-day attempts)."
            )

    # --- 6. soft reconcile ---
    _reconcile_after_rebalance(trading_client, target, run_log)


# =====================================================================
# Orchestrator
# =====================================================================

def run_track_c_execution_job(trading_client: TradingClient = None, sleep_fn=time.sleep) -> dict:
    """
    The whole Track C rebalance job. Returns a plain dict log of what
    happened — the caller (main()) logs it and pings the heartbeat;
    durable journaling is spec §3.2, a separate concern.

    trading_client defaults to a real paper/live client (built from
    config) when not supplied, matching execution.run_daily_execution_
    job()'s signature.
    """
    if trading_client is None:
        trading_client = _build_live_trading_client()

    run_log = {
        "date": None,
        "rebalance_day": False,
        "halted": False,
        "risk_off": None,
        "current_holdings": [],
        "target": [],
        "sold": [],
        "bought": [],
        "reconcile": [],
        "step_2b": None,
        "track_c_ledger_start": {},
        "track_c_ledger_end": {},
        "pending_state_after": None,
        "errors": [],
    }

    # 1. HALT CHECK — return immediately, no orders, no heal, no step 2b.
    halt = halt_state.load_track_c_halt()
    if halt.halted:
        run_log["halted"] = True
        run_log["halt_reason"] = halt.reason
        log.info("track_c_execution: Track C is halted (%s) — skipping run entirely.", halt.reason)
        return run_log

    # 2. HEAL (start-of-run). A wrong ledger must never drive a sell.
    try:
        run_log["track_c_ledger_start"] = track_positions.heal_track_c_ownership_ledger(trading_client, HEAL_UNIVERSE)
    except Exception as exc:  # noqa: BLE001
        telegram_bot.send_message(
            f"track_c_execution: start-of-run track_c ledger heal failed ({exc}) — run aborted, no orders submitted."
        )
        run_log["errors"].append({"step": "heal_start", "error": str(exc)})
        return run_log

    # 2b. RESOLVE PENDING WORK (spec v60 §10.30) — retries + the mandatory
    # deferred reconcile. Runs regardless of whether today is a rebalance day.
    pending = load_pending_state()
    try:
        _resolve_pending_work(trading_client, pending, run_log, sleep_fn)
    except Exception as exc:  # noqa: BLE001 — defensive; individual sub-ops already isolate their own failures
        run_log["errors"].append({"step": "step_2b", "error": str(exc)})
        telegram_bot.send_message(f"track_c_execution: step 2b (resolve pending work) raised ({exc}).")
    save_pending_state(pending)

    # If step 2b's reconcile just halted Track C on a mismatch, do NOT
    # proceed to submit a new rebalance's orders (safety addition beyond
    # the brief's literal text — see module docstring). End-of-run heal is
    # also skipped, matching step 1's "halted -> no heal".
    halt = halt_state.load_track_c_halt()
    if halt.halted:
        run_log["halted"] = True
        run_log["halt_reason"] = halt.reason
        run_log["halted_during"] = "step_2b_reconcile"
        run_log["pending_state_after"] = load_pending_state()
        log.info("track_c_execution: halted during step 2b reconcile (%s) — stopping this invocation.", halt.reason)
        return run_log

    # 3-6 in the body; 7 (end-of-run heal + pending persist) always runs afterward.
    try:
        _run_rebalance_body(trading_client, sleep_fn, run_log, pending)
    finally:
        _heal_end_of_run(trading_client, run_log)
        save_pending_state(pending)
        run_log["pending_state_after"] = load_pending_state()

    return run_log


def send_track_c_heartbeat(run_log: dict, heartbeat_url: str = None, requests_module=requests) -> bool:
    """
    Dead-man's-switch ping for the Track C rebalance job — mirrors
    execution.send_daily_heartbeat() exactly. Fired once at the end of a
    run that recorded no per-step errors. A HALTED run still counts as
    healthy. Best-effort: a failed ping is logged and returns False,
    never raised. Pings HEALTHCHECKS_TRACK_C_HEARTBEAT_URL; a
    missing/blank URL logs a warning and skips.
    """
    if heartbeat_url is None:
        heartbeat_url = get_track_c_heartbeat_config().daily_job_url
    if not heartbeat_url:
        log.warning("send_track_c_heartbeat: HEALTHCHECKS_TRACK_C_HEARTBEAT_URL not set — skipping heartbeat ping.")
        return False
    if run_log.get("errors"):
        return False
    try:
        requests_module.get(heartbeat_url, timeout=10)
        return True
    except Exception as exc:  # noqa: BLE001 — a monitoring ping failure must never fail the job
        log.warning("send_track_c_heartbeat: ping failed (%s) — job itself still succeeded.", exc)
        return False


def main() -> None:
    """
    systemd ExecStart target for trading-bot-track-c.service (spec v59
    §10.29). Mirrors execution.main(): configure logging from LOG_LEVEL,
    run the job, log the result dict, ping the heartbeat. Halt-state is
    handled inside run_track_c_execution_job(). An unhandled exception is
    left to propagate (traceback + non-zero exit) as the correct "this
    oneshot run failed" signal for systemd/journalctl.
    """
    logging.basicConfig(level=get_log_level(), format="%(asctime)s %(levelname)s %(message)s")
    run_log = run_track_c_execution_job()
    log.info("run_track_c_execution_job() result: %s", run_log)
    send_track_c_heartbeat(run_log)


if __name__ == "__main__":
    main()
