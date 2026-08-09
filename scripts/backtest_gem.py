"""
Track A (spec v24 §10.2): Dual Momentum / GEM (Gary Antonacci's classic
design) — locked as a candidate in a prior planning-chat session (spec
v22 §10.1) but never actually backtested (superseded by the three-track
pivot before its first run). First non-crypto, non-Track-B strategy in
this repo, and the first whose signal is a TOTAL-RETURN comparison rather
than a price-channel/indicator-crossover rule.

Universe (4 ETFs): SPY (US equities), EFA (developed ex-US equities), AGG
(aggregate bonds — the defensive holding), BIL (1-3mo T-bill proxy — an
absolute-momentum REFERENCE rate in base GEM, and the breaker variants'
own defensive holding — see below).

Signal, evaluated once per fully-completed calendar month (month-end
close), fixed rule per spec v22 §10.1 — externally-evidenced parameters
(Antonacci's original design), not swept or tuned this round:
  1. Relative momentum: whichever of SPY/EFA has the higher trailing
     12-month total return is this month's "risky pick".
  2. Absolute momentum filter: if the risky pick's trailing 12-month
     total return exceeds BIL's trailing 12-month total return, hold the
     risky pick for the following month. Otherwise hold AGG instead.
  3. Full notional, single position at a time. GEM's actual specified
     design IS 100%-of-equity rotation — unlike MACD D1H1/RSI-mean-
     reversion's flat-25%-cap fallback (a workaround for lacking a
     natural risk-based sizing anchor, crypto findings 8/9), full
     notional isn't a fallback here, it's the strategy.

CORRECTNESS FIX, not a style choice (see src/data_ingestion.py's
fetch_historical_stock_candles() docstring for the empirical evidence
gathered before writing this file): momentum is computed on Alpaca's
split+dividend-ADJUSTED close series (Adjustment.ALL), not the RAW prices
Track B used. GEM's signal IS a total-return comparison — RAW prices
would badly distort or outright invalidate the absolute-momentum filter
(BIL's raw series has an uncorrected ~2x split discontinuity; AGG's raw
price-only return is negative over a window where its true
dividend-inclusive return is positive).

12-MONTH LOOKBACK = INDICATOR WARM-UP, NOT A TRAINING/TUNING PERIOD (user
instruction) — GEM's parameters are fixed, externally-evidenced values,
the same epistemic status as Track B's carried-over 100d/3.0x parameters,
so nothing is actually fit/selected across folds. The first evaluation
point with a full 12-month lookback (computed from real fetched data, not
hardcoded) is where the 2-fold walk-forward's USABLE window begins.

DATA WINDOW: the same account-level 2016-01-04 truncation Track B
discovered applies identically here — confirmed for all 4 tickers before
writing any Track A code, per explicit instruction. ~10.6yr raw window,
but GEM's own 12-month warm-up consumes the first year regardless, so the
USABLE (tradeable) window is ~9.6yr starting ~2017-01.

WALK-FORWARD: 2 anchored, contiguous, non-overlapping folds (not 3, per
user instruction) — GEM's monthly cadence and low turnover risk the same
sample-starvation failure mode as the crypto RSI mean-reversion finding
(finding 9) if split any finer. Folds are built by splitting the usable
monthly-evaluation-point sequence into two roughly-equal-count halves;
fold boundary DATES are what trades get bucketed against, by EXIT
timestamp — same convention as backtest_donchian_ensemble.py's
slice_ensemble_trades_by_folds(). ONE DELIBERATE DEVIATION, not a
copy-paste: see slice_gem_trades_by_folds()'s docstring — the last
fold's upper boundary is forced to extend through the end of the trade
list rather than using a strict "<test_end" comparison, otherwise the
final eol trade would be silently dropped from the per-fold count while
still appearing in the pooled number.

ADOPT BAR (user instruction — reported as raw numbers, not self-rendered
as a verdict, same convention as every prior finding): pooled net-of-cost
positive AND BOTH folds individually positive. Per-fold POSITION-CHANGE
(switch + circuit-breaker exit) counts are reported explicitly; any fold
with fewer than SWITCH_COUNT_THIN_THRESHOLD (3) is flagged as a possible
sample-starvation risk.

TRADE MODEL: a "trade" is a continuous HOLDING PERIOD in one asset,
opened when GEM (or the breaker) selects a different asset than
currently held and closed when that later changes again, or at the end
of the data ("eol"). `r_multiple` is a NOMINAL scorecard only (against
spec §4.1's 1%-of-equity figure), not tied to actual sizing — same
documented caveat as MACD D1H1/RSI mean-reversion (findings 8/9).

Fee model: reused directly from Track B (0% commission + 5bps/leg
slippage) — a judgment call, not a newly-derived number, since Track A
wasn't given its own fee instruction.

============================================================================
CONTINUOUS DAILY SIMULATION (this revision — replaces the original
month-end-only simulate_gem()). Two things forced this rewrite, both from
explicit instruction:
  (a) the trade-close-sampled max_drawdown_pct the first base-GEM run
      reported was confirmed (by reading summarize()'s code) to be a
      LOWER BOUND, not a true mark-to-market number — GEM can hold a
      single position up to two years, and any intra-holding drawdown
      was completely invisible to a metric that only samples equity when
      a trade closes;
  (b) the circuit-breaker variants need to check drawdown from the
      ALL-TIME-PEAK strategy equity EVERY DAY, which is a fundamentally
      different loop structure than evaluating only at month-end.

simulate_gem() now iterates the FULL daily trading calendar (not just
month-end dates) from the first live evaluation date through the last
confirmed month-end (see compute_month_end_dates — the still-open current
month is excluded, same as before). Each day:
  1. IF today is a scheduled month-end evaluation date: run GEM's normal
     decision (select_gem_asset). If currently in a breach state (holding
     BIL because of a prior circuit-breaker trigger), this UNCONDITIONALLY
     resumes normal GEM allocation regardless of what price did while
     breached — the explicit, instructed simplification (see below).
     Otherwise, switch only if the desired asset differs from the one
     currently held.
  2. Mark today's equity to market using the currently-held asset's
     close price relative to the current holding period's own entry
     price/entry equity.
  3. IF a breaker threshold is configured and we are NOT already in a
     breach state: compute drawdown from the running ALL-TIME peak of
     this continuous equity series; if it meets/exceeds the threshold,
     immediately close the current holding (exit price = today's close
     of the held asset) and open a BIL holding (entry price = today's
     close of BIL) — this is a same-day forced move, exit_reason
     "circuit_breaker", distinct from a normal "switch".
JUDGMENT CALL, flagged: step 1 (scheduled evaluation) runs BEFORE step 3
(breach check) when both would apply to the same calendar day — monthly
rebalancing is treated as GEM's primary signal, with the breaker acting
as an overlay that can override/interrupt it, including immediately
after a rebalance on the same day. The two-instruction ordering wasn't
specified by the user for this exact same-day-coincidence edge case; this
choice is stated, not silently made. In practice this coincidence is rare
across the ~9.6yr test window.

RESUME RULE, per explicit instruction, logged here AND at runtime, not
just in this docstring: once breached, the position stays in BIL through
however many daily marks pass (BIL barely moves, so this is close to
inert) UNTIL THE NEXT SCHEDULED MONTHLY EVALUATION, regardless of any
price recovery in the interim. THIS IS A BACKTEST SIMPLIFICATION — real
deployment would require a human to manually clear/review the halt per
spec §7 (this repo's halt-state convention — see halt_state.py's
docstring for the live equivalent), so a live circuit-breaker resume
would likely be SLOWER and MORE conservative than what this backtest
simulates. The backtest's "resume automatically, unconditionally, at the
next scheduled date" is the simplest testable proxy for that process, not
a claim that live trading would behave identically.

PEAK-RESET FIX (this revision, user instruction — see simulate_gem()'s
docstring for full detail): the ORIGINAL variants (CLAUDE.md Track A
finding 2, now logged as REJECTED — specification flaw) tracked the
breach trigger's peak as the strategy's TRUE all-time high, never reset.
Combined with unconditional resume, this was diagnosed as a permanent
lockout: once equity fell behind that peak by more than the threshold,
every freshly-resumed position read as already-breached on day 0 (no
price movement needed), forcing an immediate re-exit with no way to ever
close the gap — ~89-97% of that version's "circuit_breaker" exits were
zero-day whipsaws, not genuine drawdown events. THE FIX: the tracked
peak now RESETS to current equity at the moment of resuming (not at the
moment of breach, and not before) — deliberately changing what the
guardrail promises, from "bounds cumulative drawdown from the strategy's
true all-time peak" to "bounds drawdown since the last resume." The
alternative (not resetting) was a lockout, not stricter protection, so
this is a correctness fix, not a loosening of the guardrail. The TRUE
cumulative all-time-peak drawdown is still fully recoverable for
REPORTING purposes from `daily_equity_curve` alone (see
slice_continuous_drawdown_by_folds()) — only the TRIGGER's internal peak
resets, not the reporting.

Two parallel equity series are returned by simulate_gem(), not one:
  - `trades` / a TRADE-CLOSE equity curve (via slice_gem_trades_by_folds,
    unchanged from before) — still used for net%/gross%/win-rate/etc.
    reporting, exactly as before.
  - `daily_equity_curve` — a NEW (date, equity) series with one entry per
    TRADING DAY, used exclusively for (1) reporting a true continuous
    max drawdown (compute_max_drawdown_pct /
    slice_continuous_drawdown_by_folds) and (2) driving the breaker
    trigger during simulation. This does not change net/gross returns at
    all for base GEM (no breaker) — it is a strictly additive reporting
    improvement there. For the breaker variants, it also directly drives
    new trades (breach exits), so it changes simulation outcomes, not
    just reporting.

SWITCH vs. BREACH vs. RESUME counting: a "resume" (the trade that closes
a BIL breach-holding at the next scheduled evaluation) is now its own
exit_reason, distinct from a "switch" (a normal, non-breach-driven GEM
reallocation) — needed to attribute transaction costs to the breaker
mechanism specifically (breach + resume) versus normal monthly rotation
(switch + eol), per instruction. For the per-fold "position change"
count used for the thin-sample flag, "switch" and "resume" are pooled
together with "circuit_breaker" (all three are real reallocation events
with real transaction costs) — reported as separate switch/breach
columns in the printed table (resume counts folded into "switch" there
for that specific table, since the fold table predates this distinction
and the thin-sample check doesn't need the finer split), and summed for
the thin-sample check. attribute_breaker_costs() gives the finer
breach/resume/normal split used in the cost-attribution report.

Usage:
    python scripts/backtest_gem.py
"""
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alpaca.data.enums import Adjustment
from src.data_ingestion import fetch_historical_stock_candles
from scripts.backtest import summarize, _print_table, DEFAULT_RISK_PER_TRADE_PCT
from scripts.backtest_donchian_ensemble import PAPER_VALIDATION_CAPITAL
from scripts.backtest_etf_donchian import ETF_COMMISSION_PCT, ETF_SLIPPAGE_BPS

UNIVERSE = ["SPY", "EFA", "AGG", "BIL"]
RISKY_PAIR = ["SPY", "EFA"]
DEFENSIVE_ASSET = "AGG"
ABSOLUTE_MOMENTUM_REFERENCE = "BIL"
BREAKER_SAFE_ASSET = "BIL"  # circuit-breaker variants' own defensive holding, per instruction
MOMENTUM_LOOKBACK_MONTHS = 12

GEM_COMMISSION_PCT = ETF_COMMISSION_PCT  # reused from Track B, see module docstring
GEM_SLIPPAGE_BPS = ETF_SLIPPAGE_BPS

NUM_FOLDS = 2  # user instruction — not Track B's 3
SWITCH_COUNT_THIN_THRESHOLD = 3
BREAKER_THRESHOLDS_PCT = [15.0, 20.0]  # spec v24 §10.2's two variants

REQUESTED_START = datetime(2006, 2, 3, tzinfo=timezone.utc)  # requested, not honored — see module docstring, actual floor is 2016-01-04


@dataclass
class GemTrade:
    asset: str
    entry_index: int
    exit_index: int
    entry_timestamp: str
    exit_timestamp: str
    entry_price: float
    exit_price: float
    exit_reason: str  # "switch" | "resume" | "circuit_breaker" | "eol"
    gross_pnl: float
    fees_paid: float
    pnl: float  # net of fees
    r_multiple: float  # nominal only, see module docstring


def build_symbol_series(symbol, start, end):
    """Fetches this symbol's dividend+split-adjusted daily history (Adjustment.ALL — see module docstring) and a date-string -> index map."""
    candles = fetch_historical_stock_candles(symbol, start, end, adjustment=Adjustment.ALL)
    if not candles:
        return None
    date_index = {c.timestamp[:10]: i for i, c in enumerate(candles)}
    return {"symbol": symbol, "candles": candles, "date_index": date_index}


def compute_shared_calendar(symbol_data, universe):
    """Intersection (not union) of all universe symbols' available dates — GEM needs every symbol priced on every day, unlike Track B's rotational ensemble which tolerated partial-history symbols."""
    calendars = [set(symbol_data[sym]["date_index"].keys()) for sym in universe]
    return sorted(set.intersection(*calendars))


def compute_month_end_dates(calendar):
    """
    Dates (strings) that are the last trading day of a FULLY COMPLETED
    calendar month within `calendar` (sorted date strings). A date only
    counts once a LATER date in a different calendar month exists in the
    data — this naturally excludes the current in-progress month.
    """
    return [calendar[i] for i in range(len(calendar) - 1) if calendar[i][:7] != calendar[i + 1][:7]]


def trailing_return_pct(symbol_data, symbol, month_end_dates, t):
    """Trailing MOMENTUM_LOOKBACK_MONTHS total return (%) for `symbol` as of evaluation point t (index into month_end_dates)."""
    date_now = month_end_dates[t]
    date_then = month_end_dates[t - MOMENTUM_LOOKBACK_MONTHS]
    series = symbol_data[symbol]
    close_now = series["candles"][series["date_index"][date_now]].close
    close_then = series["candles"][series["date_index"][date_then]].close
    return (close_now - close_then) / close_then * 100


def select_gem_asset(symbol_data, month_end_dates, t):
    """GEM decision at evaluation point t: relative momentum between the risky pair, then the absolute-momentum filter against BIL. Returns the selected asset symbol."""
    risky_returns = {sym: trailing_return_pct(symbol_data, sym, month_end_dates, t) for sym in RISKY_PAIR}
    risky_winner = max(risky_returns, key=risky_returns.get)
    bil_return = trailing_return_pct(symbol_data, ABSOLUTE_MOMENTUM_REFERENCE, month_end_dates, t)
    return risky_winner if risky_returns[risky_winner] > bil_return else DEFENSIVE_ASSET


def compute_max_drawdown_pct(values):
    """Standard peak-to-trough max drawdown over a value series (equity or price)."""
    if not values:
        return 0.0
    peak = values[0]
    max_dd = 0.0
    for v in values:
        peak = max(peak, v)
        dd = (peak - v) / peak * 100 if peak > 0 else 0.0
        max_dd = max(max_dd, dd)
    return max_dd


def simulate_gem(
    symbol_data,
    calendar,
    month_end_dates,
    capital=PAPER_VALIDATION_CAPITAL,
    fee_pct=GEM_COMMISSION_PCT,
    slippage_bps=GEM_SLIPPAGE_BPS,
    breaker_drawdown_pct=None,
):
    """
    Day-by-day continuous simulation over `calendar` (the full daily
    trading calendar restricted to [first live evaluation date, last
    confirmed month-end] — see main()). See module docstring's
    "CONTINUOUS DAILY SIMULATION" section for the full mechanics,
    same-day ordering judgment call, and resume-rule simplification.

    `breaker_drawdown_pct=None` reproduces base GEM exactly (no circuit
    breaker) — passing e.g. 15.0 enables the breaker at that all-time-peak
    drawdown threshold, checked daily, exiting to BIL on breach and
    resuming at the next scheduled monthly evaluation regardless of
    recovery.

    Returns (trades, trade_close_equity_curve, daily_equity_curve,
    reset_dates). `trades` is in exit-chronological order.
    `daily_equity_curve` is a list of (date, equity) tuples, one per
    trading day in `calendar`. `reset_dates` is a list of dates on which
    the breaker's tracked peak was reset (see FIX below) — starts with
    `calendar[0]` (the implicit initial reset) plus one entry per
    breach-then-resume cycle.

    FIX (this revision): the breaker's tracked peak now RESETS to current
    equity at the moment of RESUMING trading (not at the moment of
    breach, and never before). This is a deliberate change to what the
    guardrail promises: it now bounds drawdown SINCE THE LAST RESUME, not
    cumulative drawdown from the strategy's true all-time peak. The prior
    (unfixed) design's alternative, confirmed against real results, was a
    permanent lockout — once equity fell behind the true all-time peak by
    more than the threshold, every freshly-resumed position read as
    already-breached on day 0 (mark_equity == entry_equity == pre-resume
    equity, already past the threshold relative to the never-reset peak),
    forcing an immediate re-exit with no way to ever close the gap. See
    CLAUDE.md's Track A finding 2 (the original, now-rejected variants)
    for the full diagnosis this fix responds to. The TRUE cumulative
    drawdown from the strategy's actual all-time peak is still fully
    recoverable for reporting from `daily_equity_curve` alone (it doesn't
    depend on what internal peak the trigger used) — see
    slice_continuous_drawdown_by_folds()'s pooled_global_dd.
    """
    cost_frac_per_leg = fee_pct / 100 + slippage_bps / 10000
    live_eval_month_ends = month_end_dates[MOMENTUM_LOOKBACK_MONTHS:]
    eval_date_to_t = {d: MOMENTUM_LOOKBACK_MONTHS + i for i, d in enumerate(live_eval_month_ends)}
    eval_dates = set(live_eval_month_ends)

    trades = []
    trade_close_equity_curve = [capital]
    daily_equity_curve = []
    reset_dates = [calendar[0]] if calendar else []

    equity = capital
    peak_equity = capital
    held_asset = None
    entry_date = None
    entry_price = None
    entry_equity = None
    in_breach = False

    def _price(symbol, date):
        series = symbol_data[symbol]
        return series["candles"][series["date_index"][date]].close

    def _open_position(asset, date, opening_equity):
        nonlocal held_asset, entry_date, entry_price, entry_equity
        held_asset = asset
        entry_date = date
        entry_price = _price(asset, date)
        entry_equity = opening_equity

    def _close_position(date, exit_reason):
        nonlocal equity, held_asset
        series = symbol_data[held_asset]
        exit_idx = series["date_index"][date]
        entry_idx = series["date_index"][entry_date]
        exit_price = series["candles"][exit_idx].close
        position_size = entry_equity / entry_price
        gross_pnl = position_size * (exit_price - entry_price)
        fees_paid = position_size * (entry_price + exit_price) * cost_frac_per_leg
        pnl = gross_pnl - fees_paid
        new_equity = entry_equity + pnl
        trades.append(GemTrade(
            asset=held_asset,
            entry_index=entry_idx,
            exit_index=exit_idx,
            entry_timestamp=series["candles"][entry_idx].timestamp,
            exit_timestamp=series["candles"][exit_idx].timestamp,
            entry_price=entry_price,
            exit_price=exit_price,
            exit_reason=exit_reason,
            gross_pnl=gross_pnl,
            fees_paid=fees_paid,
            pnl=pnl,
            r_multiple=pnl / (capital * DEFAULT_RISK_PER_TRADE_PCT / 100) if capital else 0.0,
        ))
        equity = new_equity
        trade_close_equity_curve.append(equity)
        held_asset = None
        return new_equity

    for date in calendar:
        # 1. Scheduled monthly evaluation (runs first — see module docstring's judgment call)
        if date in eval_dates:
            t = eval_date_to_t[date]
            desired = select_gem_asset(symbol_data, month_end_dates, t)
            if held_asset is None:
                _open_position(desired, date, equity)
            elif in_breach:
                new_equity = _close_position(date, "resume")  # unconditional resume, per instruction
                _open_position(desired, date, new_equity)
                in_breach = False
                peak_equity = new_equity  # FIX: reset tracked peak here, not before -- see docstring
                reset_dates.append(date)
            elif desired != held_asset:
                new_equity = _close_position(date, "switch")
                _open_position(desired, date, new_equity)

        # 2. Mark today's equity to market using whatever is currently held.
        mark_equity = entry_equity * (_price(held_asset, date) / entry_price)
        peak_equity = max(peak_equity, mark_equity)
        daily_equity_curve.append((date, mark_equity))

        # 3. Circuit-breaker check (daily, all-time-peak drawdown), only if enabled and not already breached.
        if breaker_drawdown_pct is not None and not in_breach:
            drawdown_pct = (peak_equity - mark_equity) / peak_equity * 100 if peak_equity > 0 else 0.0
            if drawdown_pct >= breaker_drawdown_pct:
                new_equity = _close_position(date, "circuit_breaker")
                _open_position(BREAKER_SAFE_ASSET, date, new_equity)
                in_breach = True
                daily_equity_curve[-1] = (date, new_equity)  # reflect post-fee equity, not the pre-breach mark
                peak_equity = max(peak_equity, new_equity)

    if held_asset is not None:
        final_date = calendar[-1]
        new_equity = _close_position(final_date, "eol")
        daily_equity_curve[-1] = (final_date, new_equity)

    return trades, trade_close_equity_curve, daily_equity_curve, reset_dates


def compute_gem_fold_boundaries(month_end_dates, num_folds=NUM_FOLDS):
    """
    Splits the USABLE monthly evaluation sequence
    (month_end_dates[MOMENTUM_LOOKBACK_MONTHS:]) into num_folds
    roughly-equal-count, contiguous, non-overlapping folds — no separate
    initial-training span (the 12-month lookback is warm-up, not
    training). Returns a list of {"fold", "test_start", "test_end"}
    dicts with date-string boundaries. Unaffected by the continuous-daily
    rewrite — fold boundaries are still monthly-evaluation-point based.
    """
    live_eval_dates = month_end_dates[MOMENTUM_LOOKBACK_MONTHS:]
    n = len(live_eval_dates)
    fold_size = n // num_folds
    boundary_dates = [live_eval_dates[i * fold_size] for i in range(num_folds)] + [live_eval_dates[-1]]
    return [
        {"fold": i + 1, "test_start": boundary_dates[i], "test_end": boundary_dates[i + 1]}
        for i in range(num_folds)
    ]


def slice_gem_trades_by_folds(trades, equity_curve, folds, capital):
    """
    Mirrors backtest_donchian_ensemble.py's slice_ensemble_trades_by_folds()
    convention (bucket by EXIT timestamp) with ONE DELIBERATE DIFFERENCE:
    the LAST fold's upper boundary always extends through the end of the
    trade list (len(trades)) rather than using a strict "<test_end"
    comparison like every earlier fold — otherwise the final eol trade
    (whose exit date exactly equals the last fold's test_end by
    construction) would be silently dropped from the last fold's count
    while still appearing in the pooled number. Guarantees sum(fold
    trade_counts) == pooled trade_count exactly.

    Position-change counts (switch_counts, breach_counts) are reported
    SEPARATELY per fold — both represent real reallocation events with
    real transaction costs, but keeping them distinct lets the report
    show whether a fold's activity was signal-driven or risk-driven.

    Returns (fold_summaries, fold_switch_counts, fold_breach_counts,
    pooled_summary, pooled_switch_count, pooled_breach_count).
    """
    def _exit_date(t):
        return t.exit_timestamp[:10]

    boundaries = [sum(1 for t in trades if _exit_date(t) < f["test_start"]) for f in folds]
    boundaries.append(len(trades))

    fold_summaries = []
    fold_switch_counts = []
    fold_breach_counts = []
    for i, fold in enumerate(folds):
        start_idx = boundaries[i]
        end_idx = boundaries[i + 1] if i == len(folds) - 1 else sum(1 for t in trades if _exit_date(t) < fold["test_end"])
        fold_trades = trades[start_idx:end_idx]
        fold_curve = equity_curve[start_idx:end_idx + 1]
        starting_equity = fold_curve[0] if fold_curve else capital
        fold_summaries.append(summarize(fold_trades, fold_curve if fold_curve else [starting_equity], starting_equity))
        fold_switch_counts.append(sum(1 for t in fold_trades if t.exit_reason in ("switch", "resume")))
        fold_breach_counts.append(sum(1 for t in fold_trades if t.exit_reason == "circuit_breaker"))

    pooled_start_idx = boundaries[0]
    pooled_trades = trades[pooled_start_idx:]
    pooled_curve = equity_curve[pooled_start_idx:]
    pooled_starting_equity = pooled_curve[0] if pooled_curve else capital
    pooled_summary = summarize(pooled_trades, pooled_curve if pooled_curve else [pooled_starting_equity], pooled_starting_equity)
    pooled_switch_count = sum(1 for t in pooled_trades if t.exit_reason in ("switch", "resume"))
    pooled_breach_count = sum(1 for t in pooled_trades if t.exit_reason == "circuit_breaker")

    return fold_summaries, fold_switch_counts, fold_breach_counts, pooled_summary, pooled_switch_count, pooled_breach_count


def slice_continuous_drawdown_by_folds(daily_equity_curve, folds):
    """
    TRUE (continuous, daily-sampled) max drawdown per fold — fold-relative
    peak, matching summarize()'s existing per-fold convention (peak resets
    to that fold's own starting equity, not the global all-time peak) —
    plus one pooled figure over the full window using a GLOBAL (not
    fold-relative) peak, which is the number most directly comparable
    across the three variants for "did the breaker reduce worst-case
    drawdown" purposes. Returns (fold_dds, pooled_global_dd).
    """
    fold_dds = []
    for fold in folds:
        values = [e for d, e in daily_equity_curve if fold["test_start"] <= d <= fold["test_end"]]
        fold_dds.append(compute_max_drawdown_pct(values))

    pooled_values = [e for d, e in daily_equity_curve if folds[0]["test_start"] <= d <= folds[-1]["test_end"]]
    pooled_global_dd = compute_max_drawdown_pct(pooled_values)
    return fold_dds, pooled_global_dd


def compute_leg_max_drawdowns(daily_equity_curve, reset_dates):
    """
    Splits `daily_equity_curve` into "legs" bounded by `reset_dates` (see
    simulate_gem()'s PEAK-RESET FIX) — each leg starts fresh at a reset
    point and uses ITS OWN local peak (exactly compute_max_drawdown_pct's
    normal behavior when given just that leg's own values). The breaker's
    JOB is to keep every leg's own drawdown bounded near the configured
    threshold; this is the sanity-check metric for that, distinct from
    the pooled GLOBAL (never-resetting) figure
    slice_continuous_drawdown_by_folds() reports, which answers a
    different question (could cumulative loss across many reset cycles
    still add up over time). Returns (leg_dds, worst_leg_dd).
    """
    if not daily_equity_curve:
        return [], 0.0
    boundaries = reset_dates + [daily_equity_curve[-1][0]]
    leg_dds = []
    for i in range(len(boundaries) - 1):
        leg_start, leg_end = boundaries[i], boundaries[i + 1]
        is_last = i == len(boundaries) - 2
        if is_last:
            values = [e for d, e in daily_equity_curve if leg_start <= d <= leg_end]
        else:
            values = [e for d, e in daily_equity_curve if leg_start <= d < leg_end]
        if values:
            leg_dds.append(compute_max_drawdown_pct(values))
    worst_leg_dd = max(leg_dds) if leg_dds else 0.0
    return leg_dds, worst_leg_dd


def attribute_breaker_costs(trades):
    """
    Splits fees_paid across three buckets: breach exits ("circuit_breaker"
    — the forced defensive exit itself), resumes ("resume" — the forced
    reallocation out of BIL back into a risky asset at the next scheduled
    evaluation, itself only happening because a breach occurred), and
    normal monthly rotation ("switch" + "eol" — GEM's own signal-driven
    reallocation, unrelated to the breaker). "Breaker-attributable" cost
    is breach + resume; "normal monthly rotation" cost is everything
    else. Returns (breach_fees, resume_fees, normal_fees).
    """
    breach_fees = sum(t.fees_paid for t in trades if t.exit_reason == "circuit_breaker")
    resume_fees = sum(t.fees_paid for t in trades if t.exit_reason == "resume")
    normal_fees = sum(t.fees_paid for t in trades if t.exit_reason in ("switch", "eol"))
    return breach_fees, resume_fees, normal_fees


def run_variant(symbol_data, calendar, month_end_dates, folds, breaker_drawdown_pct, label):
    """Runs one variant (base GEM if breaker_drawdown_pct is None, else a breaker threshold) net and gross, and assembles its full report data."""
    net_trades, net_trade_curve, net_daily_curve, net_reset_dates = simulate_gem(
        symbol_data, calendar, month_end_dates, fee_pct=GEM_COMMISSION_PCT, slippage_bps=GEM_SLIPPAGE_BPS,
        breaker_drawdown_pct=breaker_drawdown_pct,
    )
    gross_trades, gross_trade_curve, gross_daily_curve, _ = simulate_gem(
        symbol_data, calendar, month_end_dates, fee_pct=0.0, slippage_bps=0.0,
        breaker_drawdown_pct=breaker_drawdown_pct,
    )

    net_folds, net_switches, net_breaches, net_pooled, net_pooled_switches, net_pooled_breaches = slice_gem_trades_by_folds(
        net_trades, net_trade_curve, folds, PAPER_VALIDATION_CAPITAL
    )
    gross_folds, _, _, gross_pooled, _, _ = slice_gem_trades_by_folds(
        gross_trades, gross_trade_curve, folds, PAPER_VALIDATION_CAPITAL
    )

    old_trade_close_dd_folds = [f["max_drawdown_pct"] for f in net_folds]
    old_trade_close_dd_pooled = net_pooled["max_drawdown_pct"]
    continuous_dd_folds, continuous_dd_pooled_global = slice_continuous_drawdown_by_folds(net_daily_curve, folds)

    print(f"\n=== {label} ===")
    rows = []
    for i, fold in enumerate(folds):
        position_changes = net_switches[i] + net_breaches[i]
        rows.append({
            "fold": fold["fold"],
            "test_window": f"{fold['test_start']}..{fold['test_end']}",
            "n": net_folds[i]["trade_count"],
            "switch": net_switches[i],
            "breach": net_breaches[i],
            "flag": "THIN" if position_changes < SWITCH_COUNT_THIN_THRESHOLD else "",
            "net%": f"{net_folds[i]['total_return_pct']:.2f}",
            "gross%": f"{gross_folds[i]['total_return_pct']:.2f}",
            "old_dd%": f"{old_trade_close_dd_folds[i]:.2f}",
            "true_dd%": f"{continuous_dd_folds[i]:.2f}",
        })
    total_position_changes = net_pooled_switches + net_pooled_breaches
    rows.append({
        "fold": "POOLED",
        "test_window": f"{folds[0]['test_start']}..{folds[-1]['test_end']}",
        "n": net_pooled["trade_count"],
        "switch": net_pooled_switches,
        "breach": net_pooled_breaches,
        "flag": "THIN" if total_position_changes < SWITCH_COUNT_THIN_THRESHOLD else "",
        "net%": f"{net_pooled['total_return_pct']:.2f}",
        "gross%": f"{gross_pooled['total_return_pct']:.2f}",
        "old_dd%": f"{old_trade_close_dd_pooled:.2f}",
        "true_dd%": f"{continuous_dd_pooled_global:.2f}",
    })
    _print_table(rows, [
        ("fold", "fold"), ("test_window", "test_window"), ("n", "n"),
        ("switch", "switch"), ("breach", "breach"), ("flag", "flag"),
        ("net%", "net%"), ("gross%", "gross%"), ("old_dd%", "old_dd%"), ("true_dd%", "true_dd%"),
    ])
    print(f"  (old_dd% = trade-close-sampled drawdown, understates risk for long holds; true_dd% = continuous daily mark-to-market, fold-relative peak; POOLED true_dd% uses the GLOBAL all-time peak across the whole window)")

    thin = [r["fold"] for r in rows if r["flag"] == "THIN"]
    if thin:
        print(f"  WARNING: fold(s) {thin} have fewer than {SWITCH_COUNT_THIN_THRESHOLD} total position changes (switches+breaches) — possible sample-starvation risk.")

    print(f"  raw facts vs. the pre-committed bar (pooled net-of-cost positive AND both folds individually positive):")
    for i, fold in enumerate(folds):
        print(f"    fold {fold['fold']} net-of-cost: {'positive' if net_folds[i]['total_return_pct'] > 0 else 'negative/zero'} ({net_folds[i]['total_return_pct']:.2f}%)")
    print(f"    pooled net-of-cost: {'positive' if net_pooled['total_return_pct'] > 0 else 'negative/zero'} ({net_pooled['total_return_pct']:.2f}%)")

    result = {
        "label": label,
        "trades": net_trades,
        "pooled_net_pct": net_pooled["total_return_pct"],
        "pooled_true_dd_pct": continuous_dd_pooled_global,
        "pooled_switches": net_pooled_switches,
        "pooled_breaches": net_pooled_breaches,
    }

    if breaker_drawdown_pct is not None:
        # Extra diagnostics specific to the breaker variants, per instruction:
        # per-leg drawdown sanity check, genuine-vs-whipsaw breach count, cost attribution.
        leg_dds, worst_leg_dd = compute_leg_max_drawdowns(net_daily_curve, net_reset_dates)
        breach_trades = [t for t in net_trades if t.exit_reason == "circuit_breaker"]
        zero_day_breaches = [t for t in breach_trades if t.entry_timestamp[:10] == t.exit_timestamp[:10]]
        genuine_breaches = [t for t in breach_trades if t.entry_timestamp[:10] != t.exit_timestamp[:10]]
        breach_fees, resume_fees, normal_fees = attribute_breaker_costs(net_trades)
        total_fees = breach_fees + resume_fees + normal_fees

        print(f"\n  --- breaker-specific diagnostics ---")
        print(f"  reset cycles: {len(net_reset_dates)}  |  worst single reset-cycle leg drawdown: {worst_leg_dd:.2f}%  (threshold: {breaker_drawdown_pct:.0f}% -- sanity check: should land near the threshold)")
        print(f"  circuit-breaker exits: {len(breach_trades)} total  |  genuine multi-day breaches: {len(genuine_breaches)}  |  zero-day same-day re-breaches: {len(zero_day_breaches)} (should be near zero now)")
        for t in genuine_breaches:
            days_held = (datetime.fromisoformat(t.exit_timestamp) - datetime.fromisoformat(t.entry_timestamp)).days
            print(f"    genuine breach: {t.asset} {t.entry_timestamp[:10]} -> {t.exit_timestamp[:10]} ({days_held}d held), pnl=${t.pnl:.2f}")
        print(f"  transaction costs: breaker-attributable (breach+resume) ${breach_fees + resume_fees:.2f}  |  normal monthly rotation ${normal_fees:.2f}  |  total ${total_fees:.2f}")

        result.update({
            "worst_leg_dd_pct": worst_leg_dd,
            "genuine_breach_count": len(genuine_breaches),
            "zero_day_breach_count": len(zero_day_breaches),
            "breaker_attributable_fees": breach_fees + resume_fees,
            "normal_rotation_fees": normal_fees,
        })

    return result


def main():
    end = datetime.now(timezone.utc) - timedelta(minutes=20)

    print(f"=== Track A: Dual Momentum / GEM — base + circuit-breaker variants ({BREAKER_THRESHOLDS_PCT}) — {MOMENTUM_LOOKBACK_MONTHS}mo lookback, monthly rotation, daily breaker check ===")
    print(f"requested start: {REQUESTED_START.date()} — see module docstring for the confirmed 2016-01-04 account-level data floor")
    symbol_data = {}
    for symbol in UNIVERSE:
        series = build_symbol_series(symbol, REQUESTED_START, end)
        if series is None:
            print(f"{symbol}: no candle data returned")
            return
        symbol_data[symbol] = series
        first, last = series["candles"][0], series["candles"][-1]
        print(f"  {symbol}: {first.timestamp[:10]} -> {last.timestamp[:10]}  ({len(series['candles'])} daily candles, dividend+split adjusted)")

    full_calendar = compute_shared_calendar(symbol_data, UNIVERSE)
    month_end_dates = compute_month_end_dates(full_calendar)
    live_eval_dates = month_end_dates[MOMENTUM_LOOKBACK_MONTHS:]
    # Continuous daily calendar restricted to [first live evaluation date, last confirmed month-end] --
    # matches the trade-based reporting's own window exactly (excludes the still-open current month).
    calendar = [d for d in full_calendar if live_eval_dates[0] <= d <= live_eval_dates[-1]]

    print(f"\nshared calendar: {full_calendar[0]} -> {full_calendar[-1]}  ({len(full_calendar)} trading days)")
    print(f"month-end evaluation points: {len(month_end_dates)} total ({month_end_dates[0]} -> {month_end_dates[-1]})")
    print(f"usable (post-{MOMENTUM_LOOKBACK_MONTHS}mo-warmup) window: {live_eval_dates[0]} -> {live_eval_dates[-1]}  ({len(live_eval_dates)} monthly evaluation points, {len(calendar)} trading days, breaker checked daily on all of them)")
    print(f"(fee model: {GEM_COMMISSION_PCT:.2f}% commission + {GEM_SLIPPAGE_BPS:.0f}bps slippage per leg, reused from Track B)")
    print(
        f"CIRCUIT-BREAKER RESUME RULE (backtest simplification, logged per instruction): on breach, exits fully to "
        f"{BREAKER_SAFE_ASSET}; resumes automatically at the NEXT scheduled monthly evaluation regardless of price "
        f"recovery. Real deployment would require manual review/clearance per spec §7 (halt_state.py's live "
        f"convention) -- a live resume would likely be slower and more conservative than this backtest simulates."
    )
    print(
        f"PEAK-RESET FIX (v2, this revision): the breaker's tracked peak now resets to current equity at the moment "
        f"of RESUMING (not at breach, and not before) -- bounds drawdown SINCE THE LAST RESUME, not cumulative "
        f"drawdown from the strategy's true all-time peak. The original (v1) variants are REJECTED as a "
        f"specification flaw -- see CLAUDE.md Track A finding 2 -- and are not reproduced by this script anymore."
    )

    folds = compute_gem_fold_boundaries(month_end_dates, num_folds=NUM_FOLDS)
    print(f"\nfold boundaries ({NUM_FOLDS} folds, no separate training span):")
    for fold in folds:
        print(f"  fold {fold['fold']}: test {fold['test_start']} -> {fold['test_end']}")

    variants = [("Base GEM (no circuit breaker)", None)] + [
        (f"GEM + {pct:.0f}% circuit breaker (v2, peak-reset-on-resume)", pct) for pct in BREAKER_THRESHOLDS_PCT
    ]
    results = [
        run_variant(symbol_data, calendar, month_end_dates, folds, threshold, label)
        for label, threshold in variants
    ]

    print(f"\n=== Cross-variant summary (pooled, net-of-cost) ===")
    _print_table(
        [{
            "variant": r["label"],
            "pooled_net%": f"{r['pooled_net_pct']:.2f}",
            "true_global_dd%": f"{r['pooled_true_dd_pct']:.2f}",
            "worst_leg_dd%": f"{r['worst_leg_dd_pct']:.2f}" if "worst_leg_dd_pct" in r else "n/a",
            "switches": r["pooled_switches"],
            "breaches": r["pooled_breaches"],
            "genuine_breach": r.get("genuine_breach_count", "n/a"),
            "zeroday_breach": r.get("zero_day_breach_count", "n/a"),
        } for r in results],
        [
            ("variant", "variant"), ("pooled_net%", "pooled_net%"),
            ("true_global_dd%", "true_global_dd%"), ("worst_leg_dd%", "worst_leg_dd%"),
            ("switches", "switches"), ("breaches", "breaches"),
            ("genuine_breach", "genuine_breach"), ("zeroday_breach", "zeroday_breach"),
        ],
    )
    print(f"  (true_global_dd% = continuous drawdown from the strategy's actual all-time peak, never resets; worst_leg_dd% = worst single reset-cycle leg, should sit near each variant's own threshold)")

    for r in results:
        print(f"\n=== {r['label']}: holding-period detail (which asset, how long, net pnl) ===")
        _print_table(
            [{
                "asset": t.asset,
                "entry": t.entry_timestamp[:10],
                "exit": t.exit_timestamp[:10],
                "reason": t.exit_reason,
                "net_pnl": f"${t.pnl:.2f}",
            } for t in r["trades"]],
            [("asset", "asset"), ("entry", "entry"), ("exit", "exit"), ("reason", "reason"), ("net_pnl", "net_pnl")],
        )


if __name__ == "__main__":
    main()
