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

Universe, channel, ATR multiplier, long-only, fee model — all unchanged
from finding 12 (see below). Notional: this run uses $10,000 (the
locked paper-validation notional, CLAUDE.md 2026-08 capital reframing),
not finding 12's $100 — percentage results are unaffected by that switch,
it only makes position-size dollar reporting realistic; see
PAPER_VALIDATION_CAPITAL below (a local override, NOT a change to
backtest.py's shared DEFAULT_CAPITAL, which other findings' $100 numbers
still depend on).

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
  - Long entry: daily close breaks above the single 55-day causal Donchian
    channel high (compute_donchian_levels(), reused unchanged from
    backtest_donchian.py/finding 6-7 — window [i-N, i), current day
    excluded). Finding 11's 20-day leg is removed entirely, not just
    unused — finding 11's MATH NOTE proved "close > upper_20 OR close >
    upper_55" is mathematically IDENTICAL to "close > upper_20" at every
    index (a causal 55-day window always contains the most recent 20 days,
    so upper_55[i] >= upper_20[i] once both are defined), meaning the
    20-day leg was the one silently doing all the work the whole time,
    not the 55-day leg as the fixed-rule spec intended. Finding 12 keeps
    the 55-day channel (the one the design was supposed to test) and
    drops the 20-day leg, rather than the reverse.
  - Exit: ATR trailing stop fixed at 2.5x ATR(14) — unchanged from finding
    11/finding 7's middle grid value, Chandelier-style, same formula as
    backtest_donchian.py's simulate_donchian() (ratchets in the trade's
    favor only, using the PRIOR day's extreme-close/ATR so today's
    trigger check has no lookahead).
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
  - Entry cadence (FINDING 13): entries evaluated weekly (fixed Monday
    evaluation day) instead of daily — see module docstring update.
    Exits/trailing-stop still evaluated daily, unchanged.
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
CHANNEL_LENGTH = 55           # finding 12: single channel, 20d leg removed (see docstring)
ATR_MULTIPLIER = 2.5          # fixed — finding 7's middle grid value, not swept
MAX_CONCURRENT_POSITIONS = 8  # finding 12: widened from finding 11's 4
# Finding 13: replaces finding 12's flat SLOT_MAX_POSITION_PCT (12.5%) —
# verification showed that cap bound almost exclusively on BTC/USD (see
# module docstring). TOTAL_PORTFOLIO_RISK_BUDGET_PCT caps aggregate RISK
# across open positions instead of NOTIONAL per slot; derived as
# MAX_CONCURRENT_POSITIONS x DEFAULT_RISK_PER_TRADE_PCT (8 x 1% = 8%),
# same worst-case aggregate risk envelope finding 12's design implied.
TOTAL_PORTFOLIO_RISK_BUDGET_PCT = MAX_CONCURRENT_POSITIONS * DEFAULT_RISK_PER_TRADE_PCT
# Loose leverage/numerical sanity backstop only (near-zero-ATR edge case)
# — NOT a per-slot design choice, see module docstring's finding 13 note.
NOTIONAL_SANITY_CAP_PCT = 100.0
# Finding 13: weekly entry evaluation (fixed Monday, weekday()==0) —
# arbitrary but deterministic, flagged per module docstring.
WEEKLY_ENTRY_WEEKDAY = 0
# Finding 13: $10,000 locked paper-validation notional (CLAUDE.md 2026-08
# capital reframing), NOT backtest.py's shared $100 DEFAULT_CAPITAL —
# other findings' $100 numbers are untouched by this local override.
PAPER_VALIDATION_CAPITAL = 10_000.0


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
    Long entry indices where close breaks above the single 55-day causal
    Donchian high. Finding 12: replaces finding 11's 20d/55d OR-combination
    (proven redundant — see module docstring) with this single channel.
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
            stop_distance = atr_multiplier * entry_atr
            if stop_distance <= 0:
                continue
            position_size = risk_amount / stop_distance

            # Loose leverage/numerical sanity backstop only (near-zero-ATR
            # edge case) — not a per-slot design choice, see docstring.
            max_notional = equity * (notional_sanity_cap_pct / 100)
            notional = position_size * candle.close
            if notional > max_notional:
                position_size = max_notional / candle.close
                risk_amount = position_size * stop_distance

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

    print(f"=== 10-asset rotational Donchian ensemble (finding 13: risk-budget sizing + weekly entries): fetching {len(args.symbols)} symbols ===")
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
    entry_eval_dates = compute_weekly_entry_evaluation_dates(calendar)
    total_risk_budget_pct = args.max_positions * DEFAULT_RISK_PER_TRADE_PCT

    print(f"\nshared calendar: {calendar[0]} -> {calendar[-1]}  ({len(calendar)} days, {len(entry_eval_dates)} weekly entry-evaluation days)")
    print(f"max concurrent positions: {args.max_positions}  |  ATR trailing-stop multiplier: {args.atr_multiplier}")
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
        entry_eval_dates=entry_eval_dates,
    )
    gross_trades, gross_curve, _ = simulate_rotational_ensemble(
        symbol_data, universe_order, max_positions=args.max_positions, atr_multiplier=args.atr_multiplier,
        capital=PAPER_VALIDATION_CAPITAL, fee_pct=0.0, slippage_bps=0.0,
        entry_eval_dates=entry_eval_dates,
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
            "win%": f"{net['win_rate_pct']:.1f}",
            "net%": f"{net['total_return_pct']:.2f}",
            "gross%": f"{gross['total_return_pct']:.2f}",
            "max_dd%": f"{net['max_drawdown_pct']:.2f}",
        })
    rows.append({
        "fold": "POOLED",
        "test_window": f"{folds[0]['test_start'].date()}..{folds[-1]['test_end'].date()}",
        "n": net_pooled["trade_count"],
        "win%": f"{net_pooled['win_rate_pct']:.1f}",
        "net%": f"{net_pooled['total_return_pct']:.2f}",
        "gross%": f"{gross_pooled['total_return_pct']:.2f}",
        "max_dd%": f"{net_pooled['max_drawdown_pct']:.2f}",
    })
    _print_table(rows, [
        ("fold", "fold"), ("test_window", "test_window"),
        ("n", "n"), ("win%", "win%"), ("net%", "net%"), ("gross%", "gross%"), ("max_dd%", "max_dd%"),
    ])

    positive = sum(1 for net in net_folds if net["trade_count"] > 0 and net["total_return_pct"] > 0)
    negative = sum(1 for net in net_folds if net["trade_count"] > 0 and net["total_return_pct"] < 0)
    flat_or_no_trades = len(net_folds) - positive - negative
    print(
        f"folds net-positive: {positive}/{len(net_folds)}  |  "
        f"net-negative: {negative}/{len(net_folds)}  |  "
        f"flat/no-trades: {flat_or_no_trades}/{len(net_folds)}"
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
