"""
EXPERIMENT — multi-fold anchored walk-forward validation harness for the
daily-50-SMA-filtered 9/21 signal (scripts/backtest_trend_filter.py).

VALIDATION-METHODOLOGY change only, not a strategy change. The prior
single-split test (270d calibration / 90d validation, backtest_trend_
filter.py) showed thin, partial improvement over the raw signal but with
too few validation trades (5-8) to trust as a real result. This script
reuses compute_trend_filtered_signal_indices() and simulate() from
backtest.py completely unchanged — same fee model (0.25%/leg taker + 5bps/
leg slippage), same daily-50 SMA filter logic, same ATR multiplier sweep
(1.5x-3.0x) — and only replaces the single split with N anchored,
non-overlapping folds across the full available history, to get more
validation trades to judge the filter against.

Fold structure: anchored walk-forward. The first ~INITIAL_TRAIN_DAYS of
history is reserved as fold 1's training-only period (no fold tests
against it). The remaining history is divided into NUM_FOLDS roughly-even,
contiguous, non-overlapping test windows. Fold i's training window is
always [history_start, fold_i_test_start) — i.e. anchored at the start of
history and growing with each fold, per the session's requirement ("train
on everything prior"). Because this strategy has no calibration-fit step
(the ATR multiplier and SMA period are fixed inputs swept for reporting,
not chosen from calibration data), a fold's training window doesn't get
its own separate simulation — it just defines where that fold's test
window begins. Exact boundary dates are computed from the actual fetched
candle range and printed at runtime, not hardcoded.

Only the daily-50 SMA filter is run here (per session instructions — no
daily-200 test in this harness). If a fold's test window happens to sit
mostly below the daily-200 SMA, that's noted as an observation only — it
does not gate or change the fold's daily-50 result.

Usage:
    python scripts/backtest_walkforward.py
    python scripts/backtest_walkforward.py --folds 5 --initial-train-days 365
"""
import argparse
import sys
from datetime import datetime, timedelta, timezone

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data_ingestion import fetch_historical_candles, TRADING_PAIRS
from scripts.backtest import (
    resample_candles,
    compute_trend_filtered_signal_indices,
    compute_sma,
    simulate,
    summarize,
    _print_table,
    DEFAULT_CAPITAL,
    DEFAULT_TAKER_FEE_PCT,
    DEFAULT_SLIPPAGE_BPS,
)

EMA_FAST, EMA_SLOW = 9, 21
ATR_MULTIPLIERS = [1.5, 2.0, 2.5, 3.0]
SMA_PERIOD = 50            # daily-50 filter only — see module docstring
SMA_PERIOD_OBSERVE = 200   # observational note only, not a separate test
CANDLE_HOURS = 4
BARS_PER_DAY = 24 // CANDLE_HOURS  # 6 four-hour bars per daily bar
DEFAULT_NUM_FOLDS = 5
DEFAULT_INITIAL_TRAIN_DAYS = 365


def compute_fold_boundaries(start, end, num_folds=DEFAULT_NUM_FOLDS, initial_train_days=DEFAULT_INITIAL_TRAIN_DAYS):
    """
    Anchored walk-forward fold boundaries. Reserves the first
    initial_train_days as fold 1's training-only period, then splits the
    remaining [start + initial_train_days, end) span into num_folds
    roughly-even, contiguous, non-overlapping test windows. Each fold's
    train window is [start, fold's own test_start) — anchored, growing.
    """
    total_days = (end - start).days
    remaining_days = total_days - initial_train_days
    if remaining_days <= 0:
        raise ValueError(
            f"initial_train_days ({initial_train_days}) leaves no history "
            f"for test folds (total history is only {total_days} days)"
        )
    test_window_days = remaining_days / num_folds

    folds = []
    for i in range(num_folds):
        test_start = start + timedelta(days=initial_train_days + i * test_window_days)
        test_end = end if i == num_folds - 1 else start + timedelta(days=initial_train_days + (i + 1) * test_window_days)
        folds.append({
            "fold": i + 1,
            "train_start": start,
            "train_end": test_start,
            "test_start": test_start,
            "test_end": test_end,
        })
    return folds


def run_multi_fold_walk_forward(
    candles,
    folds,
    ema_fast_period,
    ema_slow_period,
    atr_multiplier,
    capital=DEFAULT_CAPITAL,
    fee_pct=DEFAULT_TAKER_FEE_PCT,
    slippage_bps=DEFAULT_SLIPPAGE_BPS,
    precomputed_signals=None,
):
    """
    One continuous simulate() pass over the full candle range (equity
    compounds across the whole history, same continuity assumption as
    backtest.py's run_walk_forward), then sliced per fold's TEST window
    only, each summarized relative to that fold's own starting equity —
    exactly run_walk_forward's calibration/validation approach, generalized
    from one cutoff to N.

    Also returns a pooled summary: fold test windows are contiguous and
    non-overlapping, so "pooled" is just one continuous run from fold 1's
    test start through the end of history, i.e. everything except the
    initial training-only period.
    """
    trades, equity_curve = simulate(
        candles, ema_fast_period, ema_slow_period, atr_multiplier,
        capital=capital, fee_pct=fee_pct, slippage_bps=slippage_bps,
        precomputed_signals=precomputed_signals,
    )

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


def _pct_below_sma(daily_candles, sma_values, window_start, window_end):
    """Observational only: fraction of daily closes below the (same-day, unlagged) SMA within [window_start, window_end)."""
    in_window = [
        (c, sma) for c, sma in zip(daily_candles, sma_values)
        if sma is not None and window_start.isoformat() <= c.timestamp < window_end.isoformat()
    ]
    if not in_window:
        return None
    below = sum(1 for c, sma in in_window if c.close < sma)
    return below / len(in_window) * 100


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--symbols", nargs="+", default=TRADING_PAIRS)
    parser.add_argument("--folds", type=int, default=DEFAULT_NUM_FOLDS)
    parser.add_argument("--initial-train-days", type=int, default=DEFAULT_INITIAL_TRAIN_DAYS)
    parser.add_argument("--atr-multipliers", nargs="+", type=float, default=ATR_MULTIPLIERS)
    return parser.parse_args()


def main():
    args = parse_args()
    end = datetime.now(timezone.utc) - timedelta(minutes=20)  # crypto bars need a short settle delay
    start = datetime(2021, 1, 3, tzinfo=timezone.utc)  # earliest history available (CLAUDE.md)

    for symbol in args.symbols:
        hourly = fetch_historical_candles(symbol, start, end)
        if not hourly:
            print(f"{symbol}: no candle data returned, skipping")
            continue

        candles_4h = resample_candles(hourly, CANDLE_HOURS)
        candles_daily = resample_candles(hourly, 24)

        actual_start = datetime.fromisoformat(candles_4h[0].timestamp)
        actual_end = datetime.fromisoformat(candles_4h[-1].timestamp)
        folds = compute_fold_boundaries(
            actual_start, actual_end, num_folds=args.folds, initial_train_days=args.initial_train_days
        )
        daily_200_sma = compute_sma([c.close for c in candles_daily], SMA_PERIOD_OBSERVE)

        print(f"\n=== {symbol}: daily-{SMA_PERIOD} SMA filter, {args.folds}-fold anchored walk-forward ===")
        print(f"history: {actual_start.date()} to {actual_end.date()}  ({len(candles_4h)} 4h candles, {len(candles_daily)} daily candles)")
        print(f"fold boundaries (initial train {args.initial_train_days}d, then {args.folds} contiguous test windows):")
        for fold in folds:
            pct_below_200 = _pct_below_sma(candles_daily, daily_200_sma, fold["test_start"], fold["test_end"])
            note = f", {pct_below_200:.0f}% of days below daily-200 SMA" if pct_below_200 is not None else ""
            print(
                f"  fold {fold['fold']}: train {fold['train_start'].date()} -> {fold['train_end'].date()}"
                f"  |  test {fold['test_start'].date()} -> {fold['test_end'].date()}{note}"
            )
        print(f"(fee model: {DEFAULT_TAKER_FEE_PCT:.2f}% taker + {DEFAULT_SLIPPAGE_BPS:.0f}bps slippage per leg)")

        for atr_multiplier in args.atr_multipliers:
            filtered_indices, atr = compute_trend_filtered_signal_indices(
                candles_4h, EMA_FAST, EMA_SLOW,
                higher_tf_candles=candles_daily, higher_tf_sma_period=SMA_PERIOD,
                bars_per_higher_tf_unit=BARS_PER_DAY,
            )
            net_folds, net_pooled = run_multi_fold_walk_forward(
                candles_4h, folds, EMA_FAST, EMA_SLOW, atr_multiplier,
                capital=DEFAULT_CAPITAL, fee_pct=DEFAULT_TAKER_FEE_PCT, slippage_bps=DEFAULT_SLIPPAGE_BPS,
                precomputed_signals=(filtered_indices, atr),
            )
            gross_folds, gross_pooled = run_multi_fold_walk_forward(
                candles_4h, folds, EMA_FAST, EMA_SLOW, atr_multiplier,
                capital=DEFAULT_CAPITAL, fee_pct=0.0, slippage_bps=0.0,
                precomputed_signals=(filtered_indices, atr),
            )

            print(f"\n--- ATR multiplier {atr_multiplier} ---")
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
