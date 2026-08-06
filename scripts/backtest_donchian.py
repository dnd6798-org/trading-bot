"""
EXPERIMENT — Donchian channel breakout (long AND short) with an ATR
trailing-stop exit. New strategy family, replacing the rejected 9/21 EMA
crossover (CLAUDE.md finding 5 / commit 82d1bb0 on `paper`: that signal,
even with a daily-50 SMA trend filter, failed the walk-forward adopt bar
on every symbol/ATR combo tested).

Signal (daily candles; channel length N in {20, 55} days):
  - Long entry:  today's close breaks above the highest HIGH of the prior
    N days (window [i-N, i), current day excluded — causal, no lookahead).
  - Short entry: today's close breaks below the lowest LOW of the same
    prior-N-day window.
  - No volume filter this round (explicit instruction — keep the base
    signal clean; a filter can be layered on later if it shows promise).

Exit: ATR trailing stop (NOT a fixed opposite-band exit, NOT a fixed
stop/take-profit pair like backtest.py's EMA-crossover simulate()). See
simulate_donchian()'s docstring for the exact trail rule — the task
specified "ATR-based trailing stop" without pinning the formula, so the
rule used here (Chandelier-style, ATR-scaled trail off the highest/lowest
CLOSE since entry, recomputed daily) is a judgment call, flagged there.

Reuses UNCHANGED, per instruction — nothing about fees or fold boundaries
was touched:
  - backtest.py's fee constants (DEFAULT_TAKER_FEE_PCT 0.25%/leg taker,
    DEFAULT_SLIPPAGE_BPS 5bps/leg slippage), ATR_PERIOD (14), and
    position-sizing constants (DEFAULT_RISK_PER_TRADE_PCT 1%,
    DEFAULT_MAX_POSITION_PCT 25% — spec §4.1).
  - backtest_walkforward.py's compute_fold_boundaries() — same fold
    boundary dates over the same 2021-01-03 -> present dataset (5 folds,
    365-day initial anchor).

Does NOT reuse backtest.py's simulate() or backtest_walkforward.py's
run_multi_fold_walk_forward(): both are hardwired to the EMA crossover's
long-only, fixed-stop/take-profit trade mechanics, which can't express a
long+short position with a trailing-stop exit. Rather than modify either
of those (both are shared by other backtests, and the instruction was to
flag a needed change rather than make it silently), this script
re-implements just the trade-simulation loop (simulate_donchian) and the
fold-slicing/pooling logic (slice_trades_by_folds) as parallel code.
slice_trades_by_folds() duplicates run_multi_fold_walk_forward()'s
slicing approach exactly (slice trades by entry_timestamp against each
fold's test window, summarize relative to that fold's own starting
equity, pool everything from fold 1's test start onward) — it isn't
imported only because that function couples the slicing to a simulate()
call this strategy can't use.

--long-only gates out short entries entirely (skip/ignore, not simulate-
and-discard) while leaving simulate_donchian()/slice_trades_by_folds()
untouched — Alpaca does not support short-selling crypto, so the
both-directions numbers in CLAUDE.md finding 6 aren't directly tradeable
as-is; this flag reruns the same grid with only the long side active, for
a number that could actually be executed. Default (flag omitted) still
runs both directions, so `python scripts/backtest_donchian.py` with no
arguments continues to reproduce finding 6 exactly.

Usage:
    python scripts/backtest_donchian.py
    python scripts/backtest_donchian.py --channel-lengths 20 55 --atr-multipliers 2.0 2.5 3.0
    python scripts/backtest_donchian.py --long-only
"""
import argparse
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data_ingestion import fetch_historical_candles, TRADING_PAIRS
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
from scripts.backtest_walkforward import compute_fold_boundaries, DEFAULT_NUM_FOLDS, DEFAULT_INITIAL_TRAIN_DAYS

CHANNEL_LENGTHS = [20, 55]       # pre-registered grid — do not expand mid-test
ATR_MULTIPLIERS = [2.0, 2.5, 3.0]  # pre-registered grid — do not expand mid-test


@dataclass
class DonchianTrade:
    entry_index: int
    exit_index: int
    entry_timestamp: str
    exit_timestamp: str
    direction: str  # "long" | "short"
    entry_price: float
    exit_price: float
    exit_reason: str  # "trailing_stop" | "eol"
    gross_pnl: float
    fees_paid: float
    pnl: float  # net of fees
    r_multiple: float


def compute_donchian_levels(candles, channel_length):
    """
    Causal Donchian channel: at index i, the upper/lower band is the
    highest high / lowest low over candles[i-channel_length:i] — the
    PRIOR channel_length days, current day excluded, so there's no
    lookahead into the same day's own high/low when checking its close
    against the band.
    """
    n = len(candles)
    upper = [None] * n
    lower = [None] * n
    for i in range(channel_length, n):
        window = candles[i - channel_length:i]
        upper[i] = max(c.high for c in window)
        lower[i] = min(c.low for c in window)
    return upper, lower


def compute_donchian_signal_indices(candles, channel_length):
    """
    Returns (long_indices, short_indices, atr). A close above the prior-N
    highest high fires a long entry; a close below the prior-N lowest low
    fires a short entry. The two are mutually exclusive per day (the
    upper band can never sit below the lower band), so no index appears
    in both lists.
    """
    upper, lower = compute_donchian_levels(candles, channel_length)
    atr = compute_atr(candles, period=ATR_PERIOD)

    long_indices, short_indices = [], []
    for i in range(len(candles)):
        if upper[i] is None or atr[i] is None:
            continue
        if candles[i].close > upper[i]:
            long_indices.append(i)
        elif candles[i].close < lower[i]:
            short_indices.append(i)
    return long_indices, short_indices, atr


def simulate_donchian(
    candles,
    channel_length,
    atr_multiplier,
    capital=DEFAULT_CAPITAL,
    risk_pct=DEFAULT_RISK_PER_TRADE_PCT,
    max_position_pct=DEFAULT_MAX_POSITION_PCT,
    fee_pct=DEFAULT_TAKER_FEE_PCT,
    slippage_bps=DEFAULT_SLIPPAGE_BPS,
    precomputed_signals=None,
):
    """
    Walk-forward simulation of the Donchian breakout with an ATR
    trailing-stop exit — long and short, one open position at a time (a
    signal firing while a position is already open, in either direction,
    is skipped rather than pyramiding OR reversing; same one-position
    simplification backtest.py's simulate() uses, applied here as a
    judgment call since a "pure" turtle-style system would reverse
    immediately on an opposite breakout).

    Trailing-stop rule (judgment call — the task specified "ATR-based
    trailing stop" without pinning the formula): Chandelier-style. Track
    the highest close since entry (long) / lowest close since entry
    (short). Each day's stop level is that running extreme, scaled by
    atr_multiplier * ATR — using the extreme and ATR as of the PRIOR
    day's close, so the stop checked against today's high/low is fully
    determined before today's own bar forms (no lookahead). The stop only
    ever ratchets in the trade's favor (up for longs, down for shorts),
    never loosens. Exit fires the first day price touches it; if no exit
    by the end of the data, marks to the last close ("eol"), matching
    backtest.py's convention.
    """
    if precomputed_signals is not None:
        long_indices, short_indices, atr = precomputed_signals
    else:
        long_indices, short_indices, atr = compute_donchian_signal_indices(candles, channel_length)
    signals = sorted([(i, "long") for i in long_indices] + [(i, "short") for i in short_indices])
    cost_frac_per_leg = fee_pct / 100 + slippage_bps / 10000

    trades = []
    equity = capital
    equity_curve = [equity]
    position_open_until = -1

    for i, direction in signals:
        if i <= position_open_until:
            continue  # one open position at a time — see docstring

        entry_price = candles[i].close
        entry_atr = atr[i]
        if entry_atr is None or entry_atr <= 0:
            continue

        risk_amount = equity * (risk_pct / 100)
        stop_distance = atr_multiplier * entry_atr
        if stop_distance <= 0:
            continue
        position_size = risk_amount / stop_distance
        max_notional = equity * (max_position_pct / 100)
        notional = position_size * entry_price
        if notional > max_notional:
            position_size = max_notional / entry_price

        exit_price = None
        exit_index = len(candles) - 1
        extreme_close = entry_price  # highest (long) / lowest (short) close since entry, updated at end of each bar

        for j in range(i + 1, len(candles)):
            prior_atr = atr[j - 1] if atr[j - 1] is not None else entry_atr
            if direction == "long":
                stop_price = extreme_close - atr_multiplier * prior_atr
                hit = candles[j].low <= stop_price
            else:
                stop_price = extreme_close + atr_multiplier * prior_atr
                hit = candles[j].high >= stop_price

            if hit:
                exit_price = stop_price
                exit_index = j
                break

            extreme_close = max(extreme_close, candles[j].close) if direction == "long" else min(extreme_close, candles[j].close)

        if exit_price is None:
            exit_price = candles[-1].close
            exit_reason = "eol"
        else:
            exit_reason = "trailing_stop"

        if direction == "long":
            gross_pnl = position_size * (exit_price - entry_price)
        else:
            gross_pnl = position_size * (entry_price - exit_price)
        fees_paid = position_size * (entry_price + exit_price) * cost_frac_per_leg
        pnl = gross_pnl - fees_paid

        equity += pnl
        equity_curve.append(equity)
        trades.append(DonchianTrade(
            entry_index=i,
            exit_index=exit_index,
            entry_timestamp=candles[i].timestamp,
            exit_timestamp=candles[exit_index].timestamp,
            direction=direction,
            entry_price=entry_price,
            exit_price=exit_price,
            exit_reason=exit_reason,
            gross_pnl=gross_pnl,
            fees_paid=fees_paid,
            pnl=pnl,
            r_multiple=pnl / risk_amount if risk_amount else 0.0,
        ))
        position_open_until = exit_index

    return trades, equity_curve


def slice_trades_by_folds(trades, equity_curve, folds, capital):
    """
    Mirrors backtest_walkforward.py's run_multi_fold_walk_forward() fold-
    slicing logic exactly (see module docstring for why it's duplicated
    rather than imported): slice trades by entry_timestamp against each
    fold's test window, summarize each fold relative to its own starting
    equity, and pool everything from fold 1's test start onward (fold
    test windows are contiguous and non-overlapping, so pooling them is
    just one continuous run skipping the initial training-only period).
    """
    fold_summaries = []
    for fold in folds:
        test_start_iso = fold["test_start"].isoformat()
        test_end_iso = fold["test_end"].isoformat()
        start_idx = sum(1 for t in trades if t.entry_timestamp < test_start_iso)
        end_idx = sum(1 for t in trades if t.entry_timestamp < test_end_iso)
        fold_trades = trades[start_idx:end_idx]
        fold_curve = equity_curve[start_idx:end_idx + 1]
        starting_equity = fold_curve[0] if fold_curve else capital
        fold_summaries.append(
            summarize(fold_trades, fold_curve if fold_curve else [starting_equity], starting_equity)
        )

    pooled_start_idx = sum(1 for t in trades if t.entry_timestamp < folds[0]["test_start"].isoformat())
    pooled_trades = trades[pooled_start_idx:]
    pooled_curve = equity_curve[pooled_start_idx:]
    pooled_starting_equity = pooled_curve[0] if pooled_curve else capital
    pooled_summary = summarize(
        pooled_trades, pooled_curve if pooled_curve else [pooled_starting_equity], pooled_starting_equity
    )
    return fold_summaries, pooled_summary


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--symbols", nargs="+", default=TRADING_PAIRS)
    parser.add_argument("--channel-lengths", nargs="+", type=int, default=CHANNEL_LENGTHS)
    parser.add_argument("--atr-multipliers", nargs="+", type=float, default=ATR_MULTIPLIERS)
    parser.add_argument("--folds", type=int, default=DEFAULT_NUM_FOLDS)
    parser.add_argument("--initial-train-days", type=int, default=DEFAULT_INITIAL_TRAIN_DAYS)
    parser.add_argument(
        "--long-only", action="store_true",
        help="gate out short entries (Alpaca doesn't support crypto shorting) — see module docstring",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    end = datetime.now(timezone.utc) - timedelta(minutes=20)  # crypto bars need a short settle delay
    start = datetime(2021, 1, 3, tzinfo=timezone.utc)  # earliest history available (CLAUDE.md) — same as backtest_walkforward.py

    for symbol in args.symbols:
        hourly = fetch_historical_candles(symbol, start, end)
        if not hourly:
            print(f"{symbol}: no candle data returned, skipping")
            continue

        candles_daily = resample_candles(hourly, 24)
        actual_start = datetime.fromisoformat(candles_daily[0].timestamp)
        actual_end = datetime.fromisoformat(candles_daily[-1].timestamp)
        folds = compute_fold_boundaries(
            actual_start, actual_end, num_folds=args.folds, initial_train_days=args.initial_train_days
        )

        mode_label = "long-only" if args.long_only else "long+short"
        print(f"\n=== {symbol}: Donchian breakout ({mode_label}) + ATR trailing stop, {args.folds}-fold anchored walk-forward ===")
        print(f"history: {actual_start.date()} to {actual_end.date()}  ({len(candles_daily)} daily candles)")
        print(f"fold boundaries (initial train {args.initial_train_days}d, then {args.folds} contiguous test windows):")
        for fold in folds:
            print(
                f"  fold {fold['fold']}: train {fold['train_start'].date()} -> {fold['train_end'].date()}"
                f"  |  test {fold['test_start'].date()} -> {fold['test_end'].date()}"
            )
        print(f"(fee model: {DEFAULT_TAKER_FEE_PCT:.2f}% taker + {DEFAULT_SLIPPAGE_BPS:.0f}bps slippage per leg)")

        for channel_length in args.channel_lengths:
            long_indices, short_indices, atr = compute_donchian_signal_indices(candles_daily, channel_length)
            if args.long_only:
                short_indices = []  # gate out shorts only — simulate_donchian()/slice_trades_by_folds() untouched
            for atr_multiplier in args.atr_multipliers:
                net_trades, net_curve = simulate_donchian(
                    candles_daily, channel_length, atr_multiplier,
                    capital=DEFAULT_CAPITAL, fee_pct=DEFAULT_TAKER_FEE_PCT, slippage_bps=DEFAULT_SLIPPAGE_BPS,
                    precomputed_signals=(long_indices, short_indices, atr),
                )
                gross_trades, gross_curve = simulate_donchian(
                    candles_daily, channel_length, atr_multiplier,
                    capital=DEFAULT_CAPITAL, fee_pct=0.0, slippage_bps=0.0,
                    precomputed_signals=(long_indices, short_indices, atr),
                )
                net_folds, net_pooled = slice_trades_by_folds(net_trades, net_curve, folds, DEFAULT_CAPITAL)
                gross_folds, gross_pooled = slice_trades_by_folds(gross_trades, gross_curve, folds, DEFAULT_CAPITAL)

                print(f"\n--- channel_length={channel_length}d, ATR multiplier {atr_multiplier} ---")
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


if __name__ == "__main__":
    main()
