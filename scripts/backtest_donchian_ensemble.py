"""
EXPERIMENT — redesigned 10-asset rotational Donchian ensemble (CLAUDE.md
finding 12, a bounded one-time retry of finding 11 after its formal
rejection). Pivots off the closed/inconclusive single-/dual-asset findings
(5, 7, 8, 9) after finding 10 identified a fixed 1-2 asset universe as the
common structural gap: crypto trend-following research (Zarattini/Pagani/
Barbon SFI paper; Man Group) points at portfolio breadth as the mechanism
that clears the transaction-cost hurdle findings 1/3/5/7/8 kept hitting.
Finding 11 executed that pivot but was rejected on three diagnosed
construction flaws (redundant 20d/55d OR-entry, over-tight 4-slot cap,
thin-history ADA/PEPE) — finding 12 fixes those three directly, same
strategy family and same portfolio-breadth thesis, not a new signal idea.

FINDING 13 UPDATE (final planned iteration on this family, executed in
place per the same "repair, not rebuild" convention finding 12 used on
finding 11's file): finding 12 was formally REJECTED (pooled net-of-fees
-6.72%, 2/5 folds positive) and diagnosed as a signal-quality problem, not
fee drag. Finding 13 tests the two remaining untested pieces of the
original reference research — required verification step first, run via
the separate one-off scripts/verify_finding12_sizing.py (not this file):
re-derived finding 12's actual per-trade position sizes from its own
unchanged formula. Result: sizing was NOT flat (informal "flat sizing"
assumption was wrong) — 154 entries ranged 2.91%-12.50% of equity
(mean 6.99%, stdev 2.11%), and the 12.5% notional cap bound only 7/154
times (4.5%), concentrated almost entirely on BTC/USD (6/20 = 30% of its
trades; every other symbol capped 0-1 times, XRP/USD never). The
risk-based formula (position_size = 1%-equity-risk / ATR-stop-distance)
was already close to equal-dollar-risk-per-trade whenever uncapped — the
cap's failure mode was narrow and BTC-specific, not the broad "flat
notional sizing" the milestone kickoff assumed.

Two changes made this round, both fixed-rule (not swept):
  (a) Position sizing: the flat per-slot NOTIONAL cap
      (SLOT_MAX_POSITION_PCT, 12.5% of equity, finding 12's mechanism —
      the thing verification showed was distorting BTC's risk
      contribution specifically) is replaced with a portfolio-level TOTAL
      RISK BUDGET cap. Same 1%-of-equity risk target per trade as before
      (DEFAULT_RISK_PER_TRADE_PCT, unchanged, still spec §4.1's locked
      number) — but when the sum of currently-open positions' committed
      risk plus this new trade's target risk would exceed
      TOTAL_PORTFOLIO_RISK_BUDGET_PCT (8% = MAX_CONCURRENT_POSITIONS(8) x
      1%, the same worst-case aggregate risk envelope finding 12's flat
      12.5% x 8 slots design implied), the new trade's risk — not anyone
      else's, positions already open are never resized — is shrunk to
      whatever budget remains, rather than hitting an arbitrary per-slot
      % ceiling unrelated to how much risk the portfolio has already
      committed elsewhere. A loose 100%-of-equity notional backstop stays
      underneath this purely as a leverage/numerical sanity check (guards
      the pathological near-zero-ATR case only — essentially never binds
      for these liquid symbols) — NOT a reintroduction of finding 12's
      per-slot design, flagged as a separate, distinct judgment call. The
      MAX_CONCURRENT_POSITIONS=8 count-based structural cap is untouched,
      per instruction.
  (b) Entry cadence: entry signals are evaluated once per week (fixed
      calendar weekday, Monday — arbitrary but deterministic, same
      judgment-call convention as findings 11-12's slot-priority
      tie-break) instead of every day. Exit/trailing-stop monitoring is
      unchanged — still evaluated daily for every open position. Fold
      boundaries and compute_fold_boundaries() are untouched.
Backward-compatible: simulate_rotational_ensemble()'s new
`total_risk_budget_pct` and `entry_eval_dates` parameters both default to
finding-12-equivalent behavior (None -> derived 8%-budget cap; None ->
every day is an entry-evaluation day) so finding 12's existing tests
needed only the one sizing-cap test rewritten, not a rebuild.

FINDING 14 UPDATE (the TRUE final planned iteration on this strategy
family, in both directions — see CLAUDE.md "Current status"/finding 14
for the full binding constraint, executed in place per the same
"repair, not rebuild" convention). Finding 13 was formally REJECTED
(pooled net-of-fees -15.22% vs. finding 12's -6.72%, gross -13.51% vs.
-1.65%, 1/5 folds positive vs. 2/5, trade count collapsed 154->54).
Planning-chat root-cause diagnosis: the gross-return degradation ruled
out fee drag — the actual cause was the weekly Monday-only entry gate
decoupling signal-*checking* from signal-*timing* on a fast 55-day
breakout rule (a breakout firing mid-week was simply missed or picked up
late, not deferred). This was diagnosed as an implementation flaw in HOW
"lower entry frequency" was tested, not evidence against the underlying
"trade less often" idea, and separately, finding 13's risk-budget sizing
was never meaningfully exercised (0 skips of any kind at only 44-54 total
trades) so finding 13 provides no evidence against it either.

Finding 14 makes three changes, addressing findings 13's actual flaw
structurally instead of reverting the goal it was chasing:
  (a) Channel lengthened 55d -> 100d (CHANNEL_LENGTH): a longer, slower
      breakout window expresses "trade less often" as a property of the
      signal itself, not a calendar gate bolted on top of a fast signal.
  (b) Entries evaluated DAILY again, not weekly-gated: directly reverses
      finding 13's Part 3 mechanism (the diagnosed cause of its failure).
      compute_weekly_entry_evaluation_dates() and
      simulate_rotational_ensemble()'s entry_eval_dates parameter are
      BOTH KEPT in this file (general infrastructure, still exercised by
      their own unit tests) but main() no longer calls the weekly-cadence
      helper or passes entry_eval_dates — omitting it defaults to None,
      i.e. every day is an entry-evaluation day, finding-12-equivalent
      cadence behavior.
  (c) ATR trailing-stop multiplier widened 2.5x -> 3.0x (ATR_MULTIPLIER):
      more room for a longer-horizon trend before getting stopped out,
      consistent with trading a slower channel.
Finding 13's Part 2 (equal-risk-contribution / portfolio-level
TOTAL_PORTFOLIO_RISK_BUDGET_PCT sizing) is KEPT UNCHANGED — no code
touched sizing this round, per instruction (no evidence against it, so
it isn't reverted alongside Part 3).

NEW, PERMANENT REQUIREMENT (CLAUDE.md, established this session): every
finding from here forward must report a buy-and-hold comparison for the
same universe/period alongside net/gross/folds-positive, since none of
findings 1-13 beat buy-and-hold on BTC/ETH (~+100% each over the 5.6yr
window) while every active strategy tested was net-negative — "clears
the internal adopt bar" was never sufficient on its own. New functions
`compute_buy_and_hold_symbol_return()` /
`compute_buy_and_hold_portfolio_return()` compute an equal-weighted,
buy-at-fold-test-window-start/hold-to-window-end, NEVER-rebalanced
return (portfolio return = simple average of per-symbol % returns,
which is exactly what "split capital equally at t0, never touch it
again" produces) for both the full 10-asset universe and a BTC/ETH-only
subset, using the SAME fold boundaries as the strategy's own per-fold
breakdown, computed independently per fold (not compounded fold-to-fold)
plus once for the full pooled window (fold 1 test_start -> fold 5
test_end) — mirrors exactly how the strategy's own pooled number is
defined. Judgment call, flagged: for a symbol whose own history doesn't
yet cover a fold's test_start (XRP/USD from 2024-01-01, AVAX/USD from
2021-11-18, AAVE/USD from 2021-07-15 per finding 11), that symbol's
entry is its first available close ON OR AFTER the window start rather
than being excluded from the fold entirely — a partial-window return,
included with an equal weight alongside full-window symbols. This
slightly favors symbols that entered late during a favorable stretch,
but excluding them would understate 10-asset breadth in early folds even
more; flagged rather than silently resolved either way. BTC/USD and
ETH/USD have full history for every fold, so the BTC/ETH-only comparison
carries no such caveat.

Known risk, reported honestly per instruction, not folded into a clean
pass/fail number: a 100-day lookback is expected to produce a materially
lower trade count per fold than finding 12/13's 55-day channel — each
fold's own trade count is printed and any fold under
THIN_FOLD_TRADE_THRESHOLD trades is explicitly flagged "THIN" in the
results table rather than silently averaged into the headline number.

Universe, long-only, fee model, fold-slicing convention — all otherwise
unchanged from findings 11-13 (see below). Notional: $10,000
(PAPER_VALIDATION_CAPITAL, the locked paper-validation notional,
CLAUDE.md 2026-08 capital reframing), same as finding 13, not
backtest.py's shared $100 DEFAULT_CAPITAL which earlier findings' $100
numbers still depend on.

Universe (finding 11's list, ADA/USD and PEPE/USD dropped for
insufficient history and backfilled with the next-most-liquid full-history
candidates from scripts/select_universe.py's ranked output — see finding
12's backfill selection: SHIB/USD, CRV/USD, BONK/USD, and WIF/USD all
ranked above DOGE/USD and BCH/USD by trailing-30-day dollar volume but
only have 2023-2026 or 2026-only history (1084-1241 and 169-172 daily
candles respectively) against BTC/ETH's ~2040-candle full 2021-2026 depth
— DOGE/USD and BCH/USD are the highest-ranked candidates that also clear
full-history depth (2041 and 2037 daily candles, both from 2021-01-03),
confirmed by direct fetch before locking in, not assumed from the
liquidity ranking alone):
    BTC/USD, ETH/USD, XRP/USD, SOL/USD, UNI/USD, AVAX/USD, AAVE/USD,
    LINK/USD, DOGE/USD, BCH/USD

Signal — fixed rule, NOT a parameter grid this round:
  - Long entry: daily close breaks above the single causal Donchian
    channel high (compute_donchian_levels(), reused unchanged from
    backtest_donchian.py/finding 6-7 — window [i-N, i), current day
    excluded). N = CHANNEL_LENGTH = 100d as of finding 14 (was 55d in
    findings 12-13; finding 11's 20-day leg was removed entirely in
    finding 12 — see finding 11's MATH NOTE proving the OR-combination
    was redundant — and has stayed removed since).
  - Exit: ATR trailing stop, ATR_MULTIPLIER = 3.0x ATR(14) as of finding
    14 (was 2.5x in findings 11-13, finding 7's middle grid value) —
    Chandelier-style, same formula as backtest_donchian.py's
    simulate_donchian() (ratchets in the trade's favor only, using the
    PRIOR day's extreme-close/ATR so today's trigger check has no
    lookahead).
  - Long-only (Alpaca doesn't support crypto shorting — same reasoning as
    finding 7's --long-only flag).

Portfolio construction (finding 11's infrastructure, two of its three
diagnosed parameters changed this round — NOT the live risk-budget
guardrail, which remains explicitly out of scope):
  - Rotational, capped at MAX_CONCURRENT_POSITIONS (8, widened from
    finding 11's 4 — diagnosed as binding too hard: 169 of 337 signals
    were skipped for lack of a slot) concurrent open positions across the
    whole 10-symbol universe, shared capital pool (DEFAULT_CAPITAL, same
    $100 as the account this bot actually runs — a deliberate difference
    from findings 6-9, which backtested each symbol independently against
    its own full $100; here the slot cap IS the cross-symbol risk
    control, replacing the correlation/open-risk guardrail that's
    explicitly deferred).
  - New signals that fire while all 8 slots are occupied are SKIPPED and
    logged, not queued — a skipped signal is gone, it does not enter
    later when a slot frees up, per instruction, unchanged from finding 11.
  - Position sizing (FINDING 13: see module docstring update above for
    the full rationale): finding 7's per-trade risk-based formula
    (risk_amount = current portfolio equity * 1%, position_size =
    risk_amount / (2.5 * entry ATR)) is unchanged, but the ceiling that
    shrinks a trade when necessary switched from finding 12's flat
    per-slot NOTIONAL cap (SLOT_MAX_POSITION_PCT, 12.5%) to a
    portfolio-level TOTAL RISK BUDGET cap (TOTAL_PORTFOLIO_RISK_BUDGET_PCT,
    8% = 8 slots x 1%): a new trade's risk is shrunk to whatever budget
    remains after subtracting all currently-open positions' already-
    committed risk, not to an arbitrary fixed % of equity unrelated to
    portfolio occupancy. Applied per-asset off the SHARED equity value at
    the moment each position opens, same as finding 12. A loose
    100%-of-equity notional backstop remains underneath as a leverage/
    numerical sanity check only (near-zero-ATR edge case) — with an 8%
    total risk budget and an 8-slot maximum, worst-case simultaneous risk
    exposure is bounded at ~8% of equity (not ~100% notional exposure the
    way finding 11/12's notional-cap framing was) — a materially tighter,
    risk-denominated bound than finding 12's notional-denominated one.
    **CORRECTION (Track B risk-budget stress-test milestone, spec v29
    §10.1): the "near-zero-ATR edge case" characterization above is WRONG
    for at least one real, non-degenerate symbol — see
    scripts/backtest_etf_donchian.py's module docstring for the full
    finding. AGG (a Track B universe symbol, low-ATR-relative-to-price
    bonds) hit this exact NOTIONAL_SANITY_CAP_PCT backstop on 13 of its
    15 trades in the real Track B backtest, each one sized to exactly
    100% of account equity — this was silently true in Track B's
    already-passed run too (confirmed by rerunning that exact 8-slot/8%
    configuration with the new instrumentation below), just never visible
    before this milestone added `entry_sizing_log`. The "worst-case ~8%
    risk exposure" framing above only bounds the RISK-budget path; the
    notional backstop is a structurally separate, unbounded-by-that-8%-
    number path, and for low-volatility instruments it is the one that
    actually governs sizing. Not fixed here — flagged for whatever design
    picks this strategy back up (execution.py, guardrail rescaling).
  - Entry cadence (FINDING 14: reverted): entries evaluated DAILY again
    (finding 13's weekly Monday-only gate is diagnosed as the cause of
    finding 13's failure, not the sizing change — see module docstring's
    FINDING 14 UPDATE). compute_weekly_entry_evaluation_dates() and the
    entry_eval_dates parameter both still exist and are still unit-tested,
    just no longer invoked from main(). Exits/trailing-stop are and always
    were evaluated daily, unaffected either way.
  - Slot-filling priority when more signals fire on the same day than
    slots are available: universe list order (BTC, ETH, then the 8
    ranked-liquidity/backfill symbols in that order) — an arbitrary but
    deterministic tie-break, flagged as a judgment call, not derived
    from signal strength or any other ranking, unchanged from finding 11.
  - Exits are processed before entries within each simulated day, so a
    slot vacated by an exit can be reused by a new entry the same day.

Fold-slicing judgment call, flagged (methodology, not fold BOUNDARY
dates — compute_fold_boundaries() itself is reused completely
unchanged): because multiple positions can be open concurrently, trade
EXIT order and trade ENTRY order can diverge (trade A can enter before
trade B but exit after it) — unlike every single-position-at-a-time
script in this repo (findings 1-9), where entry order, exit order, and
equity-curve order are always identical. The existing slice_trades_by_
folds() pattern (count trades with entry_timestamp < boundary, use that
count as a list-slice index) silently assumes trades are list-ordered by
entry_timestamp, matching their equity-curve position — true everywhere
else, false here. This script's simulation loop builds `trades` and
`equity_curve` in EXIT order (equity only changes when a trade closes,
same convention as every other backtest here), so fold-slicing here
buckets by EXIT_timestamp instead of entry_timestamp, which is exactly
the trades/equity_curve list's actual order and correctly attributes
each trade's realized P&L to the fold its equity impact actually landed
in. Pooling (everything from fold 1's test start onward) is otherwise
identical to every prior finding's approach.

Does NOT reuse simulate_donchian() (single-symbol, one-position-at-a-time)
or run_multi_fold_walk_forward()/backtest_donchian.py's slice_trades_by_
folds() (both assume entry-ordered = equity-ordered trades, see above) —
new EnsembleTrade dataclass and simulate_rotational_ensemble() /
slice_ensemble_trades_by_folds() written for this script. Reuses
unchanged: compute_donchian_levels() (backtest_donchian.py), compute_atr()
(signal_generation.py), resample_candles()/summarize()/_print_table()/
fee constants/position-sizing constants/ATR_PERIOD (backtest.py),
compute_fold_boundaries() (backtest_walkforward.py).

Usage:
    python scripts/backtest_donchian_ensemble.py
    python scripts/backtest_donchian_ensemble.py --max-positions 8 --atr-multiplier 2.5
"""
import argparse
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data_ingestion import fetch_historical_candles
from src.signal_generation import compute_atr
from scripts.backtest import (
    resample_candles,
    summarize,
    _print_table,
    ATR_PERIOD,
    DEFAULT_CAPITAL,
    DEFAULT_TAKER_FEE_PCT,
    DEFAULT_SLIPPAGE_BPS,
    DEFAULT_RISK_PER_TRADE_PCT,
)
from scripts.backtest_donchian import compute_donchian_levels
from scripts.backtest_walkforward import compute_fold_boundaries, DEFAULT_NUM_FOLDS, DEFAULT_INITIAL_TRAIN_DAYS

# Finding 12: finding 11's universe with ADA/USD and PEPE/USD (insufficient
# history — 175 and 554 daily candles) dropped and backfilled with the
# next-most-liquid full-history candidates from scripts/select_universe.py's
# ranked output — see module docstring for the SHIB/CRV/BONK/WIF candidates
# that ranked higher but failed the history-depth check.
UNIVERSE = [
    "BTC/USD", "ETH/USD", "XRP/USD", "SOL/USD", "UNI/USD",
    "AVAX/USD", "AAVE/USD", "LINK/USD", "DOGE/USD", "BCH/USD",
]
CHANNEL_LENGTH = 100          # finding 14: lengthened from 55d (findings 12-13) — see docstring
ATR_MULTIPLIER = 3.0          # finding 14: widened from 2.5x (findings 11-13) — see docstring
MAX_CONCURRENT_POSITIONS = 8  # finding 12: widened from finding 11's 4
# Finding 13: replaces finding 12's flat SLOT_MAX_POSITION_PCT (12.5%) —
# verification showed that cap bound almost exclusively on BTC/USD (see
# module docstring). TOTAL_PORTFOLIO_RISK_BUDGET_PCT caps aggregate RISK
# across open positions instead of NOTIONAL per slot; derived as
# MAX_CONCURRENT_POSITIONS x DEFAULT_RISK_PER_TRADE_PCT (8 x 1% = 8%),
# same worst-case aggregate risk envelope finding 12's design implied.
# Finding 14 keeps this sizing mechanism unchanged, per instruction.
TOTAL_PORTFOLIO_RISK_BUDGET_PCT = MAX_CONCURRENT_POSITIONS * DEFAULT_RISK_PER_TRADE_PCT
# Loose leverage/numerical sanity backstop only (near-zero-ATR edge case)
# — NOT a per-slot design choice, see module docstring's finding 13 note.
NOTIONAL_SANITY_CAP_PCT = 100.0
# Finding 13 infrastructure, kept but NOT invoked from main() as of finding
# 14 (weekly gating was diagnosed as finding 13's failure cause) — still
# unit-tested, available for any future caller that wants it.
WEEKLY_ENTRY_WEEKDAY = 0
# Finding 13: $10,000 locked paper-validation notional (CLAUDE.md 2026-08
# capital reframing), NOT backtest.py's shared $100 DEFAULT_CAPITAL —
# other findings' $100 numbers are untouched by this local override.
PAPER_VALIDATION_CAPITAL = 10_000.0
# Finding 14: per-fold trade counts below this are flagged "THIN" in the
# results table rather than folded silently into a clean pass/fail read —
# a 100-day channel is expected to produce materially fewer signals than
# the 55-day channel findings 11-13 used. Arbitrary but stated threshold.
THIN_FOLD_TRADE_THRESHOLD = 5
# Finding 14: BTC/ETH-only subset for the buy-and-hold benchmark's second,
# caveat-free comparison (both have full history for every fold, unlike
# XRP/AVAX/AAVE — see module docstring's buy-and-hold judgment call).
BUY_AND_HOLD_BTC_ETH_ONLY = ["BTC/USD", "ETH/USD"]


@dataclass
class EnsembleTrade:
    symbol: str
    entry_index: int
    exit_index: int
    entry_timestamp: str
    exit_timestamp: str
    entry_price: float
    exit_price: float
    exit_reason: str  # "trailing_stop" | "eol"
    gross_pnl: float
    fees_paid: float
    pnl: float  # net of fees
    r_multiple: float


def compute_channel_long_entry_indices(candles):
    """
    Long entry indices where close breaks above the single CHANNEL_LENGTH-day
    causal Donchian high (100d as of finding 14, was 55d in findings 12-13).
    Finding 12: replaces finding 11's 20d/55d OR-combination (proven
    redundant — see module docstring) with this single channel.
    """
    upper, _ = compute_donchian_levels(candles, CHANNEL_LENGTH)
    atr = compute_atr(candles, period=ATR_PERIOD)

    entry_indices = set()
    for i in range(len(candles)):
        if atr[i] is None:
            continue
        if upper[i] is not None and candles[i].close > upper[i]:
            entry_indices.add(i)
    return entry_indices, atr


def build_symbol_series(symbol, start, end):
    """
    Fetches this symbol's full hourly history, resamples to daily, and
    precomputes everything the portfolio loop needs: entry signal
    indices, ATR(14), and a date-string -> index map (dates rather than
    full timestamps, so symbols with different actual data-start dates
    still align on the shared daily calendar without assuming identical
    hourly fetch offsets).
    """
    hourly = fetch_historical_candles(symbol, start, end)
    if not hourly:
        return None
    candles = resample_candles(hourly, 24)
    entry_indices, atr = compute_channel_long_entry_indices(candles)
    date_index = {c.timestamp[:10]: i for i, c in enumerate(candles)}
    return {
        "symbol": symbol,
        "candles": candles,
        "atr": atr,
        "entry_indices": entry_indices,
        "date_index": date_index,
    }


def simulate_rotational_ensemble(
    symbol_data,
    universe_order,
    max_positions=MAX_CONCURRENT_POSITIONS,
    atr_multiplier=ATR_MULTIPLIER,
    capital=DEFAULT_CAPITAL,
    risk_pct=DEFAULT_RISK_PER_TRADE_PCT,
    total_risk_budget_pct=None,
    notional_sanity_cap_pct=NOTIONAL_SANITY_CAP_PCT,
    fee_pct=DEFAULT_TAKER_FEE_PCT,
    slippage_bps=DEFAULT_SLIPPAGE_BPS,
    entry_eval_dates=None,
    entry_sizing_log=None,
):
    """
    Day-by-day portfolio walk-forward across the shared daily calendar
    (union of every symbol's available dates). See module docstring for
    the exits-before-entries ordering, slot-priority tie-break, and
    sizing-off-shared-equity judgment calls.

    Finding 13: `total_risk_budget_pct` (defaults to
    max_positions * risk_pct if not given, e.g. 8 * 1% = 8%) replaces
    finding 12's flat max_position_pct notional cap — a new trade's risk
    is shrunk to whatever's left of the shared risk budget after
    currently-open positions' committed risk, not to a fixed per-slot %.
    `notional_sanity_cap_pct` is a separate, loose leverage backstop only.
    `entry_eval_dates`, if given, restricts entry evaluation (NOT exit/
    stop monitoring, which always runs daily) to that date set — None
    (default) preserves finding 12's every-day behavior.

    Track B risk-budget stress-test milestone (spec v29 §10.1): `entry_
    sizing_log`, if given a list, gets one dict appended per accepted
    entry (target vs. granted risk_amount, and whether the risk budget
    shrunk it) — purely additive, read-only instrumentation for that
    milestone's diagnostic script. Default None appends nothing and
    changes no other behavior; sizing math itself is untouched, and the
    return signature is unchanged regardless of this argument, so every
    existing caller (Track A/B, the crypto ensemble, every test in this
    file) is unaffected.

    Returns (trades, equity_curve, skipped_log) — trades/equity_curve in
    EXIT-chronological order (equity only moves on a realized close, same
    convention as every other backtest in this repo).
    """
    if total_risk_budget_pct is None:
        total_risk_budget_pct = max_positions * risk_pct
    cost_frac_per_leg = fee_pct / 100 + slippage_bps / 10000
    calendar = sorted(set().union(*(s["date_index"].keys() for s in symbol_data.values())))

    open_positions = {}  # symbol -> position dict
    trades = []
    equity = capital
    equity_curve = [equity]
    skipped_log = []

    for date in calendar:
        # 1. Exits first, so a slot freed today can be reused today.
        for symbol in list(open_positions.keys()):
            series = symbol_data[symbol]
            idx = series["date_index"].get(date)
            if idx is None:
                continue
            pos = open_positions[symbol]
            candle = series["candles"][idx]
            prior_atr = series["atr"][idx - 1] if idx > 0 and series["atr"][idx - 1] is not None else pos["entry_atr"]
            stop_price = pos["extreme_close"] - atr_multiplier * prior_atr
            hit_stop = candle.low <= stop_price
            is_last_candle = idx == len(series["candles"]) - 1

            if hit_stop or is_last_candle:
                exit_price = stop_price if hit_stop else candle.close
                exit_reason = "trailing_stop" if hit_stop else "eol"
                gross_pnl = pos["position_size"] * (exit_price - pos["entry_price"])
                fees_paid = pos["position_size"] * (pos["entry_price"] + exit_price) * cost_frac_per_leg
                pnl = gross_pnl - fees_paid
                equity += pnl
                trades.append(EnsembleTrade(
                    symbol=symbol,
                    entry_index=pos["entry_index"],
                    exit_index=idx,
                    entry_timestamp=pos["entry_timestamp"],
                    exit_timestamp=candle.timestamp,
                    entry_price=pos["entry_price"],
                    exit_price=exit_price,
                    exit_reason=exit_reason,
                    gross_pnl=gross_pnl,
                    fees_paid=fees_paid,
                    pnl=pnl,
                    r_multiple=pnl / pos["risk_amount"] if pos["risk_amount"] else 0.0,
                ))
                equity_curve.append(equity)
                del open_positions[symbol]
            else:
                pos["extreme_close"] = max(pos["extreme_close"], candle.close)

        # 2. Entries, in fixed universe-order priority when slots are scarce.
        #    Finding 13: entry evaluation is gated to entry_eval_dates when
        #    given (weekly cadence) — exits above are unaffected, still daily.
        if entry_eval_dates is not None and date not in entry_eval_dates:
            continue
        for symbol in universe_order:
            if symbol in open_positions:
                continue
            series = symbol_data[symbol]
            idx = series["date_index"].get(date)
            if idx is None or idx not in series["entry_indices"]:
                continue

            if len(open_positions) >= max_positions:
                skipped_log.append({"date": date, "symbol": symbol, "reason": "no_slot_available"})
                continue

            candle = series["candles"][idx]
            entry_atr = series["atr"][idx]
            if entry_atr is None or entry_atr <= 0:
                continue

            # Finding 13: equal-risk-contribution sizing — target risk_pct
            # of equity per trade (unchanged), shrunk to whatever's left of
            # the shared portfolio risk budget rather than a flat per-slot
            # notional %. See module docstring.
            committed_risk = sum(p["risk_amount"] for p in open_positions.values())
            available_risk_budget = equity * (total_risk_budget_pct / 100) - committed_risk
            if available_risk_budget <= 0:
                skipped_log.append({"date": date, "symbol": symbol, "reason": "no_risk_budget_available"})
                continue

            target_risk_amount = equity * (risk_pct / 100)
            risk_amount = min(target_risk_amount, available_risk_budget)
            shrunk_by_risk_budget = risk_amount < target_risk_amount - 1e-9
            stop_distance = atr_multiplier * entry_atr
            if stop_distance <= 0:
                continue
            position_size = risk_amount / stop_distance

            # Loose leverage/numerical sanity backstop only (near-zero-ATR
            # edge case) — not a per-slot design choice, see docstring.
            max_notional = equity * (notional_sanity_cap_pct / 100)
            notional = position_size * candle.close
            shrunk_by_notional_cap = notional > max_notional
            if shrunk_by_notional_cap:
                position_size = max_notional / candle.close
                risk_amount = position_size * stop_distance

            if entry_sizing_log is not None:
                entry_sizing_log.append({
                    "date": date,
                    "symbol": symbol,
                    "equity": equity,
                    "committed_risk_before": committed_risk,
                    "available_risk_budget": available_risk_budget,
                    "target_risk_amount": target_risk_amount,
                    "granted_risk_amount": risk_amount,
                    # Attributed separately so a rare notional-backstop shrink
                    # (near-zero-ATR edge case) is never mistaken for the
                    # risk-budget mechanism this milestone is diagnosing.
                    "shrunk_by_risk_budget": shrunk_by_risk_budget,
                    "shrunk_by_notional_cap": shrunk_by_notional_cap,
                })

            open_positions[symbol] = {
                "entry_index": idx,
                "entry_timestamp": candle.timestamp,
                "entry_price": candle.close,
                "entry_atr": entry_atr,
                "extreme_close": candle.close,
                "position_size": position_size,
                "risk_amount": risk_amount,
            }

    return trades, equity_curve, skipped_log


def compute_weekly_entry_evaluation_dates(calendar, weekday=WEEKLY_ENTRY_WEEKDAY):
    """
    Finding 13: entry signals evaluated once per week — picks the subset
    of `calendar` (date strings) falling on a single fixed real calendar
    weekday (default Monday, weekday()==0). Arbitrary but deterministic,
    same judgment-call convention as findings 11-12's slot-priority
    tie-break. Exit/stop monitoring is unaffected — always daily, see
    simulate_rotational_ensemble()'s entry_eval_dates parameter.
    """
    return {d for d in calendar if datetime.fromisoformat(d).weekday() == weekday}


def slice_ensemble_trades_by_folds(trades, equity_curve, folds, capital):
    """
    Mirrors backtest_donchian.py's slice_trades_by_folds() approach
    exactly, EXCEPT buckets by exit_timestamp instead of entry_timestamp
    — see module docstring's fold-slicing judgment call for why that
    substitution is necessary (and correct) for a portfolio where trade
    entry order and exit/equity-realization order can diverge.
    """
    fold_summaries = []
    for fold in folds:
        test_start_iso = fold["test_start"].isoformat()
        test_end_iso = fold["test_end"].isoformat()
        start_idx = sum(1 for t in trades if t.exit_timestamp < test_start_iso)
        end_idx = sum(1 for t in trades if t.exit_timestamp < test_end_iso)
        fold_trades = trades[start_idx:end_idx]
        fold_curve = equity_curve[start_idx:end_idx + 1]
        starting_equity = fold_curve[0] if fold_curve else capital
        fold_summaries.append(
            summarize(fold_trades, fold_curve if fold_curve else [starting_equity], starting_equity)
        )

    pooled_start_idx = sum(1 for t in trades if t.exit_timestamp < folds[0]["test_start"].isoformat())
    pooled_trades = trades[pooled_start_idx:]
    pooled_curve = equity_curve[pooled_start_idx:]
    pooled_starting_equity = pooled_curve[0] if pooled_curve else capital
    pooled_summary = summarize(
        pooled_trades, pooled_curve if pooled_curve else [pooled_starting_equity], pooled_starting_equity
    )
    return fold_summaries, pooled_summary


def per_symbol_diagnostics(trades, fold_test_start_iso):
    """Trade count/contribution per symbol, pooled from fold 1's test start onward — diagnostic only, not part of the adopt/reject bar."""
    pooled = [t for t in trades if t.exit_timestamp >= fold_test_start_iso]
    by_symbol = {}
    for t in pooled:
        row = by_symbol.setdefault(t.symbol, {"symbol": t.symbol, "trade_count": 0, "net_pnl": 0.0, "gross_pnl": 0.0})
        row["trade_count"] += 1
        row["net_pnl"] += t.pnl
        row["gross_pnl"] += t.gross_pnl
    return sorted(by_symbol.values(), key=lambda r: r["net_pnl"], reverse=True)


def compute_buy_and_hold_symbol_return(series, test_start_date, test_end_date):
    """
    Finding 14: single-symbol buy-and-hold % return over [test_start_date,
    test_end_date] (inclusive date strings, "YYYY-MM-DD"). Entry is the
    first available close ON OR AFTER test_start_date (not necessarily
    test_start_date itself — a symbol whose own history starts later in
    the window still gets a partial-window return rather than being
    silently assumed to start at test_start_date, see module docstring's
    judgment call), exit is the last available close ON OR BEFORE
    test_end_date. Returns None if the symbol has no candles anywhere in
    the window (fully outside its available history).
    """
    dates_in_window = sorted(d for d in series["date_index"] if test_start_date <= d <= test_end_date)
    if not dates_in_window:
        return None
    entry_idx = series["date_index"][dates_in_window[0]]
    exit_idx = series["date_index"][dates_in_window[-1]]
    entry_price = series["candles"][entry_idx].close
    exit_price = series["candles"][exit_idx].close
    return (exit_price - entry_price) / entry_price * 100


def compute_buy_and_hold_portfolio_return(symbol_data, symbols, test_start_date, test_end_date):
    """
    Finding 14: equal-weighted buy-and-hold portfolio return — split
    capital equally across `symbols` at window start, hold each
    independently to window end, never rebalance. Under that convention
    the portfolio % return is exactly the simple average of each
    included symbol's own % return (each got an equal dollar amount, so
    each dollar's pct gain contributes equally regardless of price level).
    Symbols with no candle data anywhere in the window are excluded from
    both the average and the returned per-symbol dict, not counted as 0%.
    Returns (portfolio_return_pct_or_None, {symbol: return_pct}).
    """
    symbol_returns = {}
    for symbol in symbols:
        series = symbol_data.get(symbol)
        if series is None:
            continue
        r = compute_buy_and_hold_symbol_return(series, test_start_date, test_end_date)
        if r is not None:
            symbol_returns[symbol] = r
    if not symbol_returns:
        return None, symbol_returns
    portfolio_return = sum(symbol_returns.values()) / len(symbol_returns)
    return portfolio_return, symbol_returns


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--symbols", nargs="+", default=UNIVERSE)
    parser.add_argument("--max-positions", type=int, default=MAX_CONCURRENT_POSITIONS)
    parser.add_argument("--atr-multiplier", type=float, default=ATR_MULTIPLIER)
    parser.add_argument("--folds", type=int, default=DEFAULT_NUM_FOLDS)
    parser.add_argument("--initial-train-days", type=int, default=DEFAULT_INITIAL_TRAIN_DAYS)
    return parser.parse_args()


def main():
    args = parse_args()
    end = datetime.now(timezone.utc) - timedelta(minutes=20)  # crypto bars need a short settle delay
    start = datetime(2021, 1, 3, tzinfo=timezone.utc)  # same earliest-history anchor as findings 5-9

    print(f"=== 10-asset rotational Donchian ensemble (finding 14: 100d channel + 3.0x ATR stop, daily entries, risk-budget sizing kept from finding 13): fetching {len(args.symbols)} symbols ===")
    symbol_data = {}
    for symbol in args.symbols:
        series = build_symbol_series(symbol, start, end)
        if series is None:
            print(f"{symbol}: no candle data returned, excluding from this run")
            continue
        symbol_data[symbol] = series
        first, last = series["candles"][0], series["candles"][-1]
        print(f"  {symbol}: {first.timestamp[:10]} -> {last.timestamp[:10]}  ({len(series['candles'])} daily candles, {len(series['entry_indices'])} raw long-entry signals)")

    universe_order = [s for s in args.symbols if s in symbol_data]
    calendar = sorted(set().union(*(s["date_index"].keys() for s in symbol_data.values())))
    actual_start = datetime.fromisoformat(calendar[0]).replace(tzinfo=timezone.utc)
    actual_end = datetime.fromisoformat(calendar[-1]).replace(tzinfo=timezone.utc)
    folds = compute_fold_boundaries(
        actual_start, actual_end, num_folds=args.folds, initial_train_days=args.initial_train_days
    )
    # Finding 14: entries evaluated daily again — no entry_eval_dates
    # passed below (None default), reverting finding 13's weekly gate.
    total_risk_budget_pct = args.max_positions * DEFAULT_RISK_PER_TRADE_PCT

    print(f"\nshared calendar: {calendar[0]} -> {calendar[-1]}  ({len(calendar)} days, entries evaluated daily)")
    print(f"channel length: {CHANNEL_LENGTH}d  |  max concurrent positions: {args.max_positions}  |  ATR trailing-stop multiplier: {args.atr_multiplier}")
    print(f"total portfolio risk budget: {total_risk_budget_pct:.1f}%  |  per-trade risk target: {DEFAULT_RISK_PER_TRADE_PCT:.1f}%  |  capital: ${PAPER_VALIDATION_CAPITAL:,.0f}")
    print(f"fold boundaries (initial train {args.initial_train_days}d, then {args.folds} contiguous test windows):")
    for fold in folds:
        print(
            f"  fold {fold['fold']}: train {fold['train_start'].date()} -> {fold['train_end'].date()}"
            f"  |  test {fold['test_start'].date()} -> {fold['test_end'].date()}"
        )
    print(f"(fee model: {DEFAULT_TAKER_FEE_PCT:.2f}% taker + {DEFAULT_SLIPPAGE_BPS:.0f}bps slippage per leg)")

    net_trades, net_curve, skipped_log = simulate_rotational_ensemble(
        symbol_data, universe_order, max_positions=args.max_positions, atr_multiplier=args.atr_multiplier,
        capital=PAPER_VALIDATION_CAPITAL, fee_pct=DEFAULT_TAKER_FEE_PCT, slippage_bps=DEFAULT_SLIPPAGE_BPS,
    )
    gross_trades, gross_curve, _ = simulate_rotational_ensemble(
        symbol_data, universe_order, max_positions=args.max_positions, atr_multiplier=args.atr_multiplier,
        capital=PAPER_VALIDATION_CAPITAL, fee_pct=0.0, slippage_bps=0.0,
    )

    net_folds, net_pooled = slice_ensemble_trades_by_folds(net_trades, net_curve, folds, PAPER_VALIDATION_CAPITAL)
    gross_folds, gross_pooled = slice_ensemble_trades_by_folds(gross_trades, gross_curve, folds, PAPER_VALIDATION_CAPITAL)

    print(f"\n=== Portfolio-level results ({len(net_trades)} total trades, {len(skipped_log)} signals skipped) ===")
    rows = []
    for fold, net, gross in zip(folds, net_folds, gross_folds):
        rows.append({
            "fold": fold["fold"],
            "test_window": f"{fold['test_start'].date()}..{fold['test_end'].date()}",
            "n": net["trade_count"],
            "flag": "THIN" if net["trade_count"] < THIN_FOLD_TRADE_THRESHOLD else "",
            "win%": f"{net['win_rate_pct']:.1f}",
            "net%": f"{net['total_return_pct']:.2f}",
            "gross%": f"{gross['total_return_pct']:.2f}",
            "max_dd%": f"{net['max_drawdown_pct']:.2f}",
        })
    rows.append({
        "fold": "POOLED",
        "test_window": f"{folds[0]['test_start'].date()}..{folds[-1]['test_end'].date()}",
        "n": net_pooled["trade_count"],
        "flag": "THIN" if net_pooled["trade_count"] < THIN_FOLD_TRADE_THRESHOLD else "",
        "win%": f"{net_pooled['win_rate_pct']:.1f}",
        "net%": f"{net_pooled['total_return_pct']:.2f}",
        "gross%": f"{gross_pooled['total_return_pct']:.2f}",
        "max_dd%": f"{net_pooled['max_drawdown_pct']:.2f}",
    })
    _print_table(rows, [
        ("fold", "fold"), ("test_window", "test_window"),
        ("n", "n"), ("flag", "flag"), ("win%", "win%"), ("net%", "net%"), ("gross%", "gross%"), ("max_dd%", "max_dd%"),
    ])
    thin_folds = [r["fold"] for r in rows if r["flag"] == "THIN"]
    if thin_folds:
        print(
            f"WARNING: fold(s) {thin_folds} have fewer than {THIN_FOLD_TRADE_THRESHOLD} trades — "
            f"read these as thin/inconclusive samples, not as clean pass/fail evidence."
        )

    positive = sum(1 for net in net_folds if net["trade_count"] > 0 and net["total_return_pct"] > 0)
    negative = sum(1 for net in net_folds if net["trade_count"] > 0 and net["total_return_pct"] < 0)
    flat_or_no_trades = len(net_folds) - positive - negative
    print(
        f"folds net-positive: {positive}/{len(net_folds)}  |  "
        f"net-negative: {negative}/{len(net_folds)}  |  "
        f"flat/no-trades: {flat_or_no_trades}/{len(net_folds)}"
    )

    # Finding 14: mandatory buy-and-hold comparison (CLAUDE.md, permanent
    # requirement from this finding forward) — same fold boundaries as the
    # strategy's own per-fold breakdown, plus the full pooled window.
    print(f"\n=== Buy-and-hold benchmark (equal-weighted, buy-at-window-start/hold-to-window-end, no rebalancing) ===")
    bh_rows = []
    for fold in folds:
        test_start_date = fold["test_start"].date().isoformat()
        test_end_date = fold["test_end"].date().isoformat()
        bh_10, _ = compute_buy_and_hold_portfolio_return(symbol_data, universe_order, test_start_date, test_end_date)
        bh_btc_eth, _ = compute_buy_and_hold_portfolio_return(symbol_data, BUY_AND_HOLD_BTC_ETH_ONLY, test_start_date, test_end_date)
        bh_rows.append({
            "fold": fold["fold"],
            "test_window": f"{test_start_date}..{test_end_date}",
            "bh_10asset%": f"{bh_10:.2f}" if bh_10 is not None else "n/a",
            "bh_btc_eth%": f"{bh_btc_eth:.2f}" if bh_btc_eth is not None else "n/a",
        })
    pooled_test_start_date = folds[0]["test_start"].date().isoformat()
    pooled_test_end_date = folds[-1]["test_end"].date().isoformat()
    bh_10_pooled, bh_10_by_symbol = compute_buy_and_hold_portfolio_return(symbol_data, universe_order, pooled_test_start_date, pooled_test_end_date)
    bh_btc_eth_pooled, _ = compute_buy_and_hold_portfolio_return(symbol_data, BUY_AND_HOLD_BTC_ETH_ONLY, pooled_test_start_date, pooled_test_end_date)
    bh_rows.append({
        "fold": "POOLED",
        "test_window": f"{pooled_test_start_date}..{pooled_test_end_date}",
        "bh_10asset%": f"{bh_10_pooled:.2f}" if bh_10_pooled is not None else "n/a",
        "bh_btc_eth%": f"{bh_btc_eth_pooled:.2f}" if bh_btc_eth_pooled is not None else "n/a",
    })
    _print_table(bh_rows, [
        ("fold", "fold"), ("test_window", "test_window"),
        ("bh_10asset%", "bh_10asset%"), ("bh_btc_eth%", "bh_btc_eth%"),
    ])
    print("  per-symbol pooled buy-and-hold % (10-asset universe):")
    print("   ", ", ".join(f"{sym}={ret:.1f}%" for sym, ret in sorted(bh_10_by_symbol.items(), key=lambda kv: -kv[1])))
    print(
        f"\nstrategy pooled net-of-fees {net_pooled['total_return_pct']:.2f}%  vs.  "
        f"buy-and-hold 10-asset {bh_10_pooled:.2f}%  vs.  buy-and-hold BTC/ETH-only {bh_btc_eth_pooled:.2f}%"
    )

    print(f"\n=== Per-symbol diagnostics (pooled from fold 1 test start onward, informational only) ===")
    diag_rows = per_symbol_diagnostics(net_trades, folds[0]["test_start"].isoformat())
    _print_table(
        [{"symbol": r["symbol"], "n": r["trade_count"], "net_pnl": f"${r['net_pnl']:.2f}", "gross_pnl": f"${r['gross_pnl']:.2f}"} for r in diag_rows],
        [("symbol", "symbol"), ("n", "n"), ("net_pnl", "net_pnl"), ("gross_pnl", "gross_pnl")],
    )

    skipped_pooled = [s for s in skipped_log if s["date"] >= folds[0]["test_start"].isoformat()[:10]]
    print(f"\nskipped signals, pooled test period: {len(skipped_pooled)} of {len(skipped_log)} total")
    if skipped_pooled:
        by_reason = {}
        for s in skipped_pooled:
            by_reason[s["reason"]] = by_reason.get(s["reason"], 0) + 1
        print("  by reason:", ", ".join(f"{reason}={count}" for reason, count in sorted(by_reason.items(), key=lambda kv: -kv[1])))
        by_symbol_skips = {}
        for s in skipped_pooled:
            by_symbol_skips[s["symbol"]] = by_symbol_skips.get(s["symbol"], 0) + 1
        print("  by symbol:", ", ".join(f"{sym}={count}" for sym, count in sorted(by_symbol_skips.items(), key=lambda kv: -kv[1])))


if __name__ == "__main__":
    main()
