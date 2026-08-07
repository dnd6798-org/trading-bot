"""
EXPERIMENT — 10-asset rotational Donchian ensemble (CLAUDE.md finding 10
milestone). Pivots off the closed/inconclusive single-/dual-asset findings
(5, 7, 8, 9) after finding 10 identified a fixed 1-2 asset universe as the
common structural gap: crypto trend-following research (Zarattini/Pagani/
Barbon SFI paper; Man Group) points at portfolio breadth as the mechanism
that clears the transaction-cost hurdle findings 1/3/5/7/8 kept hitting.

Universe (locked this session via scripts/select_universe.py — BTC/USD +
ETH/USD by default, plus the 8 most liquid non-stablecoin USD pairs on
Alpaca's own crypto venue by trailing-30-day dollar volume, with PAXG/USD
hand-excluded as a gold-tracking token rather than a crypto-beta asset,
per explicit instruction):
    BTC/USD, ETH/USD, XRP/USD, SOL/USD, UNI/USD, AVAX/USD, AAVE/USD,
    LINK/USD, ADA/USD, PEPE/USD

Signal — fixed rule, NOT a parameter grid this round:
  - Long entry: daily close breaks above the 20-day OR the 55-day causal
    Donchian channel high (compute_donchian_levels(), reused unchanged
    from backtest_donchian.py/finding 6-7 — window [i-N, i), current day
    excluded).
  - Exit: ATR trailing stop fixed at 2.5x ATR(14) — finding 7's middle
    grid value, Chandelier-style, same formula as
    backtest_donchian.py's simulate_donchian() (ratchets in the trade's
    favor only, using the PRIOR day's extreme-close/ATR so today's
    trigger check has no lookahead).
  - Long-only (Alpaca doesn't support crypto shorting — same reasoning as
    finding 7's --long-only flag).

MATH NOTE, flagged rather than silently resolved: because a 55-day causal
window always contains the most recent 20 days as a subset, upper_55[i]
>= upper_20[i] at every index once both are defined (and upper_55[i] is
None, i.e. the leg contributes nothing, while i < 55). This means "close
> upper_20 OR close > upper_55" is mathematically IDENTICAL to "close >
upper_20" for every index, over the whole dataset — the 55-day leg of the
spec as given never fires an entry the 20-day leg wouldn't have already
fired. Implemented literally (both bands computed, OR'd) rather than
silently simplified to a 20-day-only signal, since the task specified
both explicitly and the redundancy may not have been the intent — flagged
here and in the run's printed output, not decided unilaterally.

Portfolio construction (the two new infrastructure pieces this milestone
needed, per finding 10 — NOT the live risk-budget guardrail, which is
explicitly out of scope):
  - Rotational, capped at MAX_CONCURRENT_POSITIONS (4) concurrent open
    positions across the whole 10-symbol universe, shared capital pool
    (DEFAULT_CAPITAL, same $100 as the account this bot actually runs —
    a deliberate difference from findings 6-9, which backtested each
    symbol independently against its own full $100; here the 4-slot cap
    IS the cross-symbol risk control, replacing the correlation/open-risk
    guardrail that's explicitly deferred).
  - New signals that fire while all 4 slots are occupied are SKIPPED and
    logged, not queued — a skipped signal is gone, it does not enter
    later when a slot frees up, per instruction.
  - Position sizing: finding 7's existing per-trade risk-based formula
    (risk_amount = current portfolio equity * 1%, position_size =
    risk_amount / (2.5 * entry ATR), capped at 25% of current portfolio
    equity notional), applied per-asset off the SHARED equity value at
    the moment each position opens. No portfolio-level vol-targeted
    sizing this round, per instruction. Judgment call, flagged: this
    does NOT enforce a hard "total deployed notional <= 100% of equity"
    check across concurrently open positions — each position is sized
    and capped independently off current equity, same simplification
    findings 1-9 already made (spec §4.3's real cross-symbol risk budget
    isn't implemented yet regardless). With a 25% per-position cap and a
    4-slot maximum, worst-case simultaneous exposure is bounded at ~100%
    of equity, which is a reasonable backtest placeholder, not a load-
    bearing guarantee.
  - Slot-filling priority when more signals fire on the same day than
    slots are available: universe list order (BTC, ETH, then the 8
    ranked-liquidity symbols in that order) — an arbitrary but
    deterministic tie-break, flagged as a judgment call, not derived
    from signal strength or any other ranking.
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
    python scripts/backtest_donchian_ensemble.py --max-positions 4 --atr-multiplier 2.5
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
    DEFAULT_MAX_POSITION_PCT,
)
from scripts.backtest_donchian import compute_donchian_levels
from scripts.backtest_walkforward import compute_fold_boundaries, DEFAULT_NUM_FOLDS, DEFAULT_INITIAL_TRAIN_DAYS

# Locked this session (scripts/select_universe.py) — BTC/ETH by default +
# 8 most-liquid non-stablecoin USD pairs on Alpaca's own crypto venue,
# PAXG/USD hand-excluded (gold-tracking, not crypto-beta) per instruction.
UNIVERSE = [
    "BTC/USD", "ETH/USD", "XRP/USD", "SOL/USD", "UNI/USD",
    "AVAX/USD", "AAVE/USD", "LINK/USD", "ADA/USD", "PEPE/USD",
]
CHANNEL_LENGTHS = (20, 55)   # fixed dual-channel entry, not swept
ATR_MULTIPLIER = 2.5         # fixed — finding 7's middle grid value, not swept
MAX_CONCURRENT_POSITIONS = 4


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


def compute_dual_channel_long_entry_indices(candles):
    """
    Long entry indices where close breaks above the 20-day OR 55-day
    causal Donchian high. See module docstring's MATH NOTE — this is
    provably identical to "close > upper_20" alone, implemented literally
    anyway per the specified rule.
    """
    upper_20, _ = compute_donchian_levels(candles, CHANNEL_LENGTHS[0])
    upper_55, _ = compute_donchian_levels(candles, CHANNEL_LENGTHS[1])
    atr = compute_atr(candles, period=ATR_PERIOD)

    entry_indices = set()
    for i in range(len(candles)):
        if atr[i] is None:
            continue
        broke_20 = upper_20[i] is not None and candles[i].close > upper_20[i]
        broke_55 = upper_55[i] is not None and candles[i].close > upper_55[i]
        if broke_20 or broke_55:
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
    entry_indices, atr = compute_dual_channel_long_entry_indices(candles)
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
    max_position_pct=DEFAULT_MAX_POSITION_PCT,
    fee_pct=DEFAULT_TAKER_FEE_PCT,
    slippage_bps=DEFAULT_SLIPPAGE_BPS,
):
    """
    Day-by-day portfolio walk-forward across the shared daily calendar
    (union of every symbol's available dates). See module docstring for
    the exits-before-entries ordering, slot-priority tie-break, and
    sizing-off-shared-equity judgment calls.

    Returns (trades, equity_curve, skipped_log) — trades/equity_curve in
    EXIT-chronological order (equity only moves on a realized close, same
    convention as every other backtest in this repo).
    """
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

            risk_amount = equity * (risk_pct / 100)
            stop_distance = atr_multiplier * entry_atr
            if stop_distance <= 0:
                continue
            position_size = risk_amount / stop_distance
            max_notional = equity * (max_position_pct / 100)
            notional = position_size * candle.close
            if notional > max_notional:
                position_size = max_notional / candle.close

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

    print(f"=== 10-asset rotational Donchian ensemble: fetching {len(args.symbols)} symbols ===")
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

    print(f"\nshared calendar: {calendar[0]} -> {calendar[-1]}  ({len(calendar)} days)")
    print(f"max concurrent positions: {args.max_positions}  |  ATR trailing-stop multiplier: {args.atr_multiplier}")
    print(f"fold boundaries (initial train {args.initial_train_days}d, then {args.folds} contiguous test windows):")
    for fold in folds:
        print(
            f"  fold {fold['fold']}: train {fold['train_start'].date()} -> {fold['train_end'].date()}"
            f"  |  test {fold['test_start'].date()} -> {fold['test_end'].date()}"
        )
    print(f"(fee model: {DEFAULT_TAKER_FEE_PCT:.2f}% taker + {DEFAULT_SLIPPAGE_BPS:.0f}bps slippage per leg)")

    net_trades, net_curve, skipped_log = simulate_rotational_ensemble(
        symbol_data, universe_order, max_positions=args.max_positions, atr_multiplier=args.atr_multiplier,
        capital=DEFAULT_CAPITAL, fee_pct=DEFAULT_TAKER_FEE_PCT, slippage_bps=DEFAULT_SLIPPAGE_BPS,
    )
    gross_trades, gross_curve, _ = simulate_rotational_ensemble(
        symbol_data, universe_order, max_positions=args.max_positions, atr_multiplier=args.atr_multiplier,
        capital=DEFAULT_CAPITAL, fee_pct=0.0, slippage_bps=0.0,
    )

    net_folds, net_pooled = slice_ensemble_trades_by_folds(net_trades, net_curve, folds, DEFAULT_CAPITAL)
    gross_folds, gross_pooled = slice_ensemble_trades_by_folds(gross_trades, gross_curve, folds, DEFAULT_CAPITAL)

    print(f"\n=== Portfolio-level results ({len(net_trades)} total trades, {len(skipped_log)} signals skipped for no free slot) ===")
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
    print(f"\nskipped signals (no free slot), pooled test period: {len(skipped_pooled)} of {len(skipped_log)} total")
    if skipped_pooled:
        by_symbol_skips = {}
        for s in skipped_pooled:
            by_symbol_skips[s["symbol"]] = by_symbol_skips.get(s["symbol"], 0) + 1
        print("  by symbol:", ", ".join(f"{sym}={count}" for sym, count in sorted(by_symbol_skips.items(), key=lambda kv: -kv[1])))


if __name__ == "__main__":
    main()
