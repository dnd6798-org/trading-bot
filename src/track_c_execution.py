"""
Track C (DMSR) live execution — the monthly sector-rotation rebalance
job (spec v59 §10.29, Milestone 4). Structurally mirrors
src/execution.py's role for Track B: one call to
run_track_c_execution_job() is the whole job, the timer fires it every
weekday post-close, and the job self-gates internally so almost every
run is a cheap no-op.

=====================================================================
SEQUENCE (every invocation)
=====================================================================
1. HALT CHECK — halt_state.load_track_c_halt(). If halted: log and
   return immediately. No orders, no ledger heal. (This is Track C's
   own halt file, independent of Track B's — spec v55 §10.25.)
2. HEAL (start-of-run) — track_positions.heal_track_c_ownership_ledger()
   over SECTOR_UNIVERSE + [AGG]. Corrects any ledger drift BEFORE
   today's decision is made. If this fails, the run is aborted (no
   orders) — a wrong ledger must never drive a sell (see the
   safety-critical note below).
3. FETCH + SELF-GATE — pull ~400 trailing calendar days of daily bars
   (Adjustment.SPLIT) for the 11 sectors + AGG + SPY, derive the trading
   calendar from SPY's own bar timestamps, and call
   dmsr_signal.is_rebalance_day(). If it's not a rebalance day (the
   common case), skip straight to step 7.
4. DECIDE — compute the trailing-12-month SPY return (absolute-momentum
   filter), rank the 11 sectors, read current_holdings from the
   FRESHLY-HEALED track_c ledger (NEVER Alpaca's raw positions), and
   call dmsr_signal.select_target_holdings().
5. EXECUTE, SELL THEN BUY, sequentially:
   a) SELLs — for each held name not in target, a QUANTITY-BASED market
      SELL for EXACTLY track_positions.get_track_qty("track_c", symbol)
      shares. *** SAFETY-CRITICAL: the quantity is the LEDGER's figure,
      never Alpaca's raw combined position. For AGG (shared with Track
      B) the raw position includes Track B's shares; selling that would
      liquidate Track B's holding. See _submit_sell(). ***
   b) allocated_capital = capital_ledger.get_available_capital(...,
      config.TRACK_C_ALLOCATION_PCT) — Track C's 30% sub-balance,
      fetched fresh AFTER the sells.
   c) BUYs — for each target name not already held, a NOTIONAL market
      BUY: 100% of allocated_capital if risk-off (buying AGG), else
      allocated_capital / 3 (a fixed fresh-capital split, NOT the
      backtest's self-funding convention).
   Every order carries client_order_id = "tc-{symbol}-{YYYYMMDD}"
   (spec v57 §10.27 — the "tc-" prefix is what lets the shared fill
   listener attribute the fill to Track C).
6. RECONCILE — re-fetch resulting positions, compare to target, send a
   (non-halting) Telegram alert if a leg looks unfilled / a position
   deviates from target.
7. HEAL (end-of-run) — heal the track_c ledger again to pick up today's
   fills, then main() pings the Track C Healthchecks.io heartbeat.

=====================================================================
FLAGGED DESIGN GAPS — inherited from the same root cause execution.py
already flags for Track B (post-close market orders fill at NEXT
session's open, not synchronously). NOT resolved here; flagged per the
"flag it, don't guess" convention. Recommend a chat-interface design
call before this module is trusted with live capital.
=====================================================================
GAP A — "confirm each fill before moving to the next" (brief step 5)
cannot be literally satisfied within one post-close invocation: a
market order submitted at ~17:00 ET fills at the next session's open,
hours (or, over a weekend, days) later. This module mirrors
execution.py's short-poll (poll_order_until_terminal, 60s) and treats a
still-open zero-fill order as an EXPECTED "pending" outcome, not a
failure — recorded in the run log, surfaced by step 6's non-urgent
reconcile note, and left for the fill to complete before the next
session. There is NO re-submission on the following (non-rebalance)
day.

GAP B — "allocated_capital fetched AFTER the sells settle" (brief step
5b): the sells have been SUBMITTED but not settled at buy time, so the
cash they free is not yet in buying power. On a risk-off transition
(sell 3 sectors, buy AGG for the full 30% sleeve) the AGG buy can be
rejected for insufficient buying power until the sells fill. Step 6's
reconcile note surfaces this; it self-resolves once the sells fill, but
the buy is not retried.

GAP C — hard ledger-integrity reconciliation. CLAUDE.md (spec v55/v56
§10.25/§10.26) describes a MANDATORY reconcile-and-HALT
(track_positions.reconcile_symbol()) "after every Track C rebalance".
The Milestone 4 brief's step 6, by contrast, specifies a SOFT,
alert-only "positions vs. target" check that does not halt. This module
implements the brief's step 6 as written. Whether reconcile_symbol()'s
hard halt should ALSO run here — and if so, how to sequence it around
the two ledger heals to avoid a false halt on the shared Track B / Track
C AGG boundary (Track C's job does not heal the track_b ledger) — needs
a chat-interface decision.

GAP D — the trailing fetch window is 400 calendar days per the brief.
That yields ~12-13 completed month-ends, and a 12-month trailing return
needs 13 (indices t and t-12). It should be sufficient in practice but
is genuinely marginal; the DECIDE step raises (and alerts, no orders)
if it ever proves too short. Recommend widening to ~450 days.
"""
import logging
import time
from datetime import datetime, timedelta, timezone

import requests
from alpaca.common.exceptions import APIError
from alpaca.data.enums import Adjustment
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
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

# Trailing daily-bar history to pull each run. ~400 calendar days is
# enough for a 12-month month-end-to-month-end trailing return plus a
# holiday/weekend buffer — see the module docstring's GAP D. The DECIDE
# step guards against it being too short rather than assuming.
SIGNAL_LOOKBACK_DAYS = 400

# Symbols whose track_c ownership the ledger heal covers (spec v57
# §10.27 / brief step 2): the 11 sectors plus the risk-off asset.
HEAL_UNIVERSE = dmsr_signal.SECTOR_UNIVERSE + [dmsr_signal.DEFENSIVE_ASSET]

# All symbols the signal needs priced: sectors + risk-off asset + market
# filter. (BIL, the backtest's Sharpe risk-free proxy, is a reporting-
# only input and is not needed live.)
_FETCH_UNIVERSE = dmsr_signal.SECTOR_UNIVERSE + [dmsr_signal.DEFENSIVE_ASSET, dmsr_signal.MARKET_FILTER_SYMBOL]


def _build_live_trading_client() -> TradingClient:
    cfg = get_alpaca_config()
    return TradingClient(api_key=cfg.api_key, secret_key=cfg.secret_key, paper=cfg.paper)


def _client_order_id(symbol: str, date_compact: str) -> str:
    """
    "tc-{symbol}-{YYYYMMDD}" (spec v57 §10.27 / brief Change C). The
    "tc-" prefix is track_positions.is_track_c_client_order_id()'s check
    — it is the ONLY signal the shared fill listener has to attribute a
    fill to Track C. No sequence suffix: Track C trades a symbol at most
    once per rebalance day by construction, so date+symbol is already
    unique, and an identical id on an accidental same-day re-run is
    detected by _order_already_submitted() below (and would be rejected
    by Alpaca regardless).
    """
    return f"{track_positions.TRACK_C_CLIENT_ORDER_ID_PREFIX}-{symbol}-{date_compact}"


def fetch_track_c_symbol_data(end=None, lookback_days=SIGNAL_LOOKBACK_DAYS) -> dict:
    """
    Trailing daily-bar pull for the signal, Adjustment.SPLIT (the
    backtest's validated basis — split-adjusted, NOT dividend-adjusted;
    Adjustment.RAW is broken for this universe because of the 2025-12-05
    SPDR 2:1 splits). Returns {symbol: {"symbol", "candles",
    "date_index"}}, same shape the backtests use. Raises if any symbol
    returns no bars — the signal cannot be computed with a gap.
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
    """The trading calendar, derived from SPY's own returned bar timestamps (brief step 3)."""
    return sorted(symbol_data[dmsr_signal.MARKET_FILTER_SYMBOL]["date_index"].keys())


def _order_already_submitted(trading_client, client_order_id: str) -> bool:
    """
    Mirrors execution.py's spec v44 per-symbol duplicate-entry guard: a
    genuine not-found get_order_by_client_id() lookup raises APIError
    with .status_code == 404 (empirically confirmed against the real
    paper account, alpaca-py 0.43.5 — see execution.py's module
    docstring). 404 -> proceed; an existing order -> already submitted
    this rebalance (an accidental same-day re-run), skip; any other
    APIError -> re-raise (a real failure, not silently swallowed).
    """
    try:
        trading_client.get_order_by_client_id(client_order_id)
    except APIError as exc:
        if exc.status_code == 404:
            return False
        raise
    return True


def _current_holdings_from_ledger() -> list:
    """
    Symbols Track C currently owns, per the (freshly healed) track_c
    ownership ledger — NEVER Alpaca's raw positions. `select_target_
    holdings()` compares this against the sector ranking; a prior
    risk-off month shows up here as exactly ["AGG"].
    """
    return [
        s for s in HEAL_UNIVERSE
        if track_positions.get_track_qty("track_c", s) > track_positions.RECONCILE_EPSILON
    ]


def _submit_sell(trading_client, symbol: str, date_compact: str, sleep_fn) -> dict:
    """
    QUANTITY-BASED market SELL of EXACTLY Track C's ledgered share count
    for `symbol`.

    *** SAFETY-CRITICAL (spec v56 §10.26 hard precondition, spec v59
    §10.29 brief step 5a): the quantity is
    track_positions.get_track_qty("track_c", symbol) — Track C's OWN
    ledgered holding — and NEVER Alpaca's raw combined position
    (get_all_positions() / get_open_position()). For AGG, which Track B
    also trades directly, the raw combined position includes Track B's
    shares; selling "the AGG position" would liquidate Track B's
    holding. This function never calls any Alpaca position endpoint. ***
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
    }


def _submit_buy(trading_client, symbol: str, notional: float, date_compact: str, sleep_fn) -> dict:
    """NOTIONAL market BUY sized in dollars (brief step 5c)."""
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
    }


def _reconcile_after_rebalance(trading_client, target, run_log) -> None:
    """
    Brief step 6 — SOFT, alert-only "did the rebalance do what it
    intended" check (NOT track_positions.reconcile_symbol()'s hard
    ledger-integrity halt — see module docstring GAP C). Re-fetches
    resulting positions, compares to `target`, and sends one non-urgent
    Telegram message if anything looks unfilled / off-target. Never
    halts, never resizes.
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
            "only if it persists past the next trading session. No automatic action taken."
        )


def _heal_end_of_run(trading_client, run_log) -> None:
    """Step 7 end-of-run heal — best-effort, always attempted (runs from the finally block)."""
    try:
        run_log["track_c_ledger_end"] = track_positions.heal_track_c_ownership_ledger(trading_client, HEAL_UNIVERSE)
    except Exception as exc:  # noqa: BLE001 — a heal failure must not crash the caller; it is corrected next run
        telegram_bot.send_message(f"track_c_execution: end-of-run track_c ledger heal failed ({exc}).")
        run_log["errors"].append({"step": "heal_end", "error": str(exc)})


def _run_rebalance_body(trading_client, sleep_fn, run_log) -> None:
    """Steps 3-6. Catches its own per-step failures into run_log; never raises."""
    try:
        symbol_data = fetch_track_c_symbol_data()
    except Exception as exc:  # noqa: BLE001 — fail-safe: skip today, nothing left unprotected (Track C is no-stop-by-design)
        telegram_bot.send_message(
            f"track_c_execution: data fetch failed ({exc}) — rebalance skipped for today. Track C holds no "
            f"stop orders (no-stop-by-design), so nothing is left unprotected; the next run retries."
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
                f"need {dmsr_signal.LOOKBACK_MONTHS + 1} for a {dmsr_signal.LOOKBACK_MONTHS}-month trailing return "
                f"(GAP D — widen SIGNAL_LOOKBACK_DAYS)"
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

    # --- 5a. SELLs (held names not in target) ---
    for symbol in [s for s in current_holdings if s not in target]:
        try:
            run_log["sold"].append(_submit_sell(trading_client, symbol, date_compact, sleep_fn))
        except Exception as exc:  # noqa: BLE001 — one leg's failure must not sink the rest of the rebalance
            telegram_bot.send_message(
                f"URGENT — track_c_execution: SELL for {symbol} failed on rebalance {run_log['date']} ({exc}). "
                f"Track C may still hold a position it intended to exit. Manual intervention required."
            )
            run_log["errors"].append({"symbol": symbol, "step": "sell", "error": str(exc)})

    # --- 5b. allocated capital, fetched fresh AFTER the sells ---
    allocated_capital = capital_ledger.get_available_capital(trading_client, config.TRACK_C_ALLOCATION_PCT)
    run_log["allocated_capital"] = allocated_capital
    per_name_notional = allocated_capital if risk_off else allocated_capital / dmsr_signal.TOP_N_HOLD

    # --- 5c. BUYs (target names not already held) ---
    for symbol in [s for s in target if s not in current_holdings]:
        try:
            run_log["bought"].append(_submit_buy(trading_client, symbol, per_name_notional, date_compact, sleep_fn))
        except Exception as exc:  # noqa: BLE001
            telegram_bot.send_message(
                f"track_c_execution: BUY for {symbol} (notional ${per_name_notional:,.2f}) failed on rebalance "
                f"{run_log['date']} ({exc}). Manual review required."
            )
            run_log["errors"].append({"symbol": symbol, "step": "buy", "error": str(exc)})

    # --- 6. reconcile ---
    _reconcile_after_rebalance(trading_client, target, run_log)


def run_track_c_execution_job(trading_client: TradingClient = None, sleep_fn=time.sleep) -> dict:
    """
    The whole Track C rebalance job. Returns a plain dict log of what
    happened — the caller (main()) logs it and pings the heartbeat;
    durable journaling of it is spec §3.2, a separate concern (same as
    Track B's run_daily_execution_job()).

    trading_client defaults to a real paper/live client (built from
    config) when not supplied, matching execution.run_daily_execution_
    job()'s signature — the brief's signature omits the default; adding
    it is a small liberty so main() and tests can both call this
    cleanly.
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
        "track_c_ledger_start": {},
        "track_c_ledger_end": {},
        "errors": [],
    }

    # 1. HALT CHECK — return immediately, no orders, no heal.
    halt = halt_state.load_track_c_halt()
    if halt.halted:
        run_log["halted"] = True
        run_log["halt_reason"] = halt.reason
        log.info("track_c_execution: Track C is halted (%s) — skipping run entirely.", halt.reason)
        return run_log

    # 2. HEAL (start-of-run). A wrong ledger must never drive a sell, so
    # a heal failure aborts the run before any decision is made.
    try:
        run_log["track_c_ledger_start"] = track_positions.heal_track_c_ownership_ledger(trading_client, HEAL_UNIVERSE)
    except Exception as exc:  # noqa: BLE001
        telegram_bot.send_message(
            f"track_c_execution: start-of-run track_c ledger heal failed ({exc}) — run aborted, no orders submitted."
        )
        run_log["errors"].append({"step": "heal_start", "error": str(exc)})
        return run_log

    # 3-6 in the body; 7 (end-of-run heal) always runs afterward.
    try:
        _run_rebalance_body(trading_client, sleep_fn, run_log)
    finally:
        _heal_end_of_run(trading_client, run_log)

    return run_log


def send_track_c_heartbeat(run_log: dict, heartbeat_url: str = None, requests_module=requests) -> bool:
    """
    Dead-man's-switch ping for the Track C rebalance job — mirrors
    execution.send_daily_heartbeat() exactly. Fired once at the end of a
    run that recorded no per-step errors (run_log["errors"] empty). A
    HALTED run still counts as healthy (halting is intentional and
    already alerted — the heartbeat only proves the process itself is
    alive and completing runs, a failure mode none of this module's
    Telegram alerts can catch). Best-effort: a failed ping is logged and
    returns False, never raised.

    Pings HEALTHCHECKS_TRACK_C_HEARTBEAT_URL (get_track_c_heartbeat_
    config()); a missing/blank URL logs a warning and skips.
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
    handled inside run_track_c_execution_job() itself. An unhandled
    exception is left to propagate (traceback + non-zero exit) as the
    correct "this oneshot run failed" signal for systemd/journalctl.
    """
    logging.basicConfig(level=get_log_level(), format="%(asctime)s %(levelname)s %(message)s")
    run_log = run_track_c_execution_job()
    log.info("run_track_c_execution_job() result: %s", run_log)
    send_track_c_heartbeat(run_log)


if __name__ == "__main__":
    main()
