"""
EXPERIMENT — MACD(12,26,9) daily-regime + hourly-entry ("D1H1") trend-
following strategy, with a price-action trailing-stop exit. New strategy
family, replacing Donchian channel breakout long-only (CLAUDE.md finding 7
/ commit fda5a86 on `paper`: pooled net returns were positive but the
folds-consistency leg of the adopt bar never cleared on any of the 12
combos tested — formally rejected).

Signal:
  - Daily regime filter: MACD(12,26,9) on daily candles. Regime is
    "bullish" when the daily MACD line is above its signal line. Per the
    task's explicit correctness requirement, this is evaluated only once
    per day, off the most recently FULLY CLOSED daily candle — never
    recomputed intraday. Implemented with the exact same causal-lag
    pattern backtest.py's compute_trend_filtered_signal_indices() already
    uses for its daily-50-SMA filter (`i // bars_per_higher_tf_unit - 1`,
    bars_per_higher_tf_unit=24 for hourly-under-daily): every hourly index
    i within calendar day D maps to daily index D-1, which is constant
    across all 24 hourly bars of day D. See
    test_hourly_index_maps_to_prior_daily_index_and_is_constant_within_a_day
    in the test file for the explicit proof of this property.
  - Hourly entry: MACD(12,26,9) on hourly candles. Long entry fires when
    the hourly MACD line crosses above its hourly signal line AND the
    aligned daily regime (per above) is bullish. No entries while the
    daily regime is bearish or not yet seeded. Long-only (Alpaca doesn't
    support crypto shorting — same constraint as Donchian finding 7).

Exit: price-action trailing stop, NOT ATR-based — genuinely different exit
philosophy from every prior backtest in this repo (backtest.py's fixed
ATR stop/take-profit, backtest_donchian.py's ATR-scaled Chandelier trail).
While in a position, hold as long as each new hourly candle closes green
(close > open); exit at the close of the first hourly candle that closes
red (close < open). Implemented as its own function
(exit at first red close) rather than folded into the ATR-multiple
parameter, so the two exit philosophies stay separated in the codebase —
see simulate_macd_d1h1().

No volume filter this round (explicit instruction — keep the base signal
clean, consistent with how Donchian was kept clean before any filter was
considered).

Reuses UNCHANGED, per instruction — nothing about fees or fold boundaries
was touched:
  - backtest.py's fee constants (DEFAULT_TAKER_FEE_PCT 0.25%/leg taker,
    DEFAULT_SLIPPAGE_BPS 5bps/leg slippage) and summarize() (its exit-
    reason rate breakdown reports 0% for "stop"/"take_profit" here since
    those labels don't apply to this strategy — trade_count, win_rate,
    total_return_pct, and max_drawdown_pct, the figures this report
    needs, don't depend on those labels).
  - backtest_walkforward.py's compute_fold_boundaries() (same 5-fold,
    365-day-initial-train logic) over the same 2021-01-03 -> present
    dataset.
  - backtest.py's resample_candles() to derive the daily series from the
    SAME hourly fetch — no second network call needed. The task flagged
    dual-timeframe ingestion as new infrastructure to watch for, but it
    turned out already solved: resample_candles(hourly, 24) is exactly
    what backtest_walkforward.py (daily-50 filter) and backtest_donchian.py
    already use to get a daily series for free from one hourly fetch.

JUDGMENT CALLS (flagged per instruction, not self-adjudicated):
  1. Position sizing has no natural stop-distance to size a 1%-risk
     position off (spec §4.1's risk-per-trade sizing assumes a known stop
     distance; this exit is price-action based with no fixed initial
     stop). Rather than invent an unspec'd ATR-based sizing distance for a
     strategy whose exit isn't ATR-based, every trade is sized flat at
     max_position_pct (25% of equity) — the same cap backtest.py and
     backtest_donchian.py both already enforce as an upper bound, used
     here as the sizing rule itself. r_multiple on each trade uses the
     nominal 1%-of-equity risk amount (DEFAULT_RISK_PER_TRADE_PCT) purely
     as a stable scorecard denominator — it is NOT tied to actual
     position sizing here and shouldn't be over-interpreted as a real
     risk multiple the way it is in backtest.py/backtest_donchian.py.
  2. Fold boundaries are computed via the same compute_fold_boundaries()
     call, same params, same dataset — but anchored off the HOURLY
     candle series' actual start/end (the primary traded timeframe here),
     not a resampled daily/4h series like the prior two scripts used.
     Since resample_candles() only drops a trailing partial group and
     hourly has none to drop (hours_per_candle=1 is a no-op), this can
     only shift boundaries by a sub-day amount out of a 5.6-year dataset
     — flagged, not silently changed.
  3. Does NOT reuse backtest.py's simulate() or backtest_donchian.py's
     simulate_donchian(): both are hardwired to different entry/exit
     mechanics than a dual-timeframe entry gate + price-action exit can
     express. Re-implements the trade loop as simulate_macd_d1h1() and
     duplicates the fold-slicing/pooling logic as slice_trades_by_folds()
     — same duplication-over-modification approach backtest_donchian.py
     already used and documented for the same reason.

Usage:
    python scripts/backtest_macd_d1h1.py
    python scripts/backtest_macd_d1h1.py --symbols BTC/USD
"""
import argparse
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data_ingestion import fetch_historical_candles, TRADING_PAIRS
from src.signal_generation import compute_macd
from scripts.backtest import (
    resample_candles,
    summarize,
    _print_table,
    DEFAULT_CAPITAL,
    DEFAULT_TAKER_FEE_PCT,
    DEFAULT_SLIPPAGE_BPS,
    DEFAULT_RISK_PER_TRADE_PCT,
    DEFAULT_MAX_POSITION_PCT,
)
from scripts.backtest_walkforward import compute_fold_boundaries, DEFAULT_NUM_FOLDS, DEFAULT_INITIAL_TRAIN_DAYS

MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9  # standard convention, not tuned this round — see module docstring
BARS_PER_DAY = 24  # 1h candles per daily candle


@dataclass
class MacdD1H1Trade:
    entry_index: int
    exit_index: int
    entry_timestamp: str
    exit_timestamp: str
    entry_price: float
    exit_price: float
    exit_reason: str  # "trend_break" | "eol"
    gross_pnl: float
    fees_paid: float
    pnl: float  # net of fees
    r_multiple: float  # nominal scorecard only — see module docstring judgment call 1


def compute_daily_regime_series(daily_candles):
    """
    Bullish/bearish/unknown per daily candle: True if that day's MACD line
    closed above its signal line, False if below, None if not yet seeded
    (early history). One value per daily candle — the once-per-day part of
    "once per day, not intraday" comes from how this is consumed (see
    compute_hourly_entry_indices), not from anything in this function.
    """
    closes = [c.close for c in daily_candles]
    macd_line, signal_line, _ = compute_macd(closes, MACD_FAST, MACD_SLOW, MACD_SIGNAL)
    regime = [None] * len(daily_candles)
    for d in range(len(daily_candles)):
        if macd_line[d] is not None and signal_line[d] is not None:
            regime[d] = macd_line[d] > signal_line[d]
    return regime


def compute_hourly_entry_indices(hourly_candles, daily_regime_series, bars_per_day=BARS_PER_DAY):
    """
    Indices where a long entry fires: hourly MACD line crosses above its
    hourly signal line, AND the aligned daily regime is bullish.

    Alignment is causal by construction: hourly index i falls in calendar
    day (i // bars_per_day); the most recently FULLY CLOSED daily candle
    at that point is the PRIOR day, so `i // bars_per_day - 1` is used —
    identical to backtest.py's compute_trend_filtered_signal_indices()
    lag pattern. This value is constant for every i within the same
    calendar day, which is exactly what "regime updates once per day, not
    intraday" requires.
    """
    closes = [c.close for c in hourly_candles]
    macd_line, signal_line, _ = compute_macd(closes, MACD_FAST, MACD_SLOW, MACD_SIGNAL)

    indices = []
    for i in range(1, len(hourly_candles)):
        if None in (macd_line[i], signal_line[i], macd_line[i - 1], signal_line[i - 1]):
            continue
        crossed_up = macd_line[i - 1] <= signal_line[i - 1] and macd_line[i] > signal_line[i]
        if not crossed_up:
            continue

        daily_index = i // bars_per_day - 1
        if daily_index < 0 or daily_index >= len(daily_regime_series):
            continue
        if daily_regime_series[daily_index] is True:
            indices.append(i)
    return indices, macd_line, signal_line


def simulate_macd_d1h1(
    hourly_candles,
    entry_indices,
    capital=DEFAULT_CAPITAL,
    risk_pct=DEFAULT_RISK_PER_TRADE_PCT,
    max_position_pct=DEFAULT_MAX_POSITION_PCT,
    fee_pct=DEFAULT_TAKER_FEE_PCT,
    slippage_bps=DEFAULT_SLIPPAGE_BPS,
):
    """
    Walk-forward simulation: long-only, one open position at a time (a
    signal firing while a position is already open is skipped, same
    simplification every other backtest in this repo uses).

    Entry: enters at the signal candle's own close (same convention as
    backtest.py/backtest_donchian.py). Sized flat at max_position_pct —
    see module docstring judgment call 1 for why there's no risk_pct/
    stop-distance sizing here.

    Exit: price-action trailing stop. Starting from the candle AFTER
    entry, hold through every candle that closes green (close > open);
    exit at the close of the first candle that closes red (close < open).
    If no red candle ever closes before the end of the data, marks to the
    last close ("eol"), matching every other backtest's convention.
    """
    cost_frac_per_leg = fee_pct / 100 + slippage_bps / 10000

    trades = []
    equity = capital
    equity_curve = [equity]
    position_open_until = -1

    for i in entry_indices:
        if i <= position_open_until:
            continue  # already in a position

        entry_price = hourly_candles[i].close
        entry_equity = equity
        nominal_risk_amount = entry_equity * (risk_pct / 100)  # scorecard only, see judgment call 1
        position_size = (entry_equity * (max_position_pct / 100)) / entry_price

        exit_price = None
        exit_reason = None
        exit_index = len(hourly_candles) - 1
        for j in range(i + 1, len(hourly_candles)):
            c = hourly_candles[j]
            if c.close < c.open:
                exit_price = c.close
                exit_reason = "trend_break"
                exit_index = j
                break

        if exit_price is None:
            exit_price = hourly_candles[-1].close
            exit_reason = "eol"

        gross_pnl = position_size * (exit_price - entry_price)
        fees_paid = position_size * (entry_price + exit_price) * cost_frac_per_leg
        pnl = gross_pnl - fees_paid

        equity += pnl
        equity_curve.append(equity)
        trades.append(MacdD1H1Trade(
            entry_index=i,
            exit_index=exit_index,
            entry_timestamp=hourly_candles[i].timestamp,
            exit_timestamp=hourly_candles[exit_index].timestamp,
            entry_price=entry_price,
            exit_price=exit_price,
            exit_reason=exit_reason,
            gross_pnl=gross_pnl,
            fees_paid=fees_paid,
            pnl=pnl,
            r_multiple=pnl / nominal_risk_amount if nominal_risk_amount else 0.0,
        ))
        position_open_until = exit_index

    return trades, equity_curve


def slice_trades_by_folds(trades, equity_curve, folds, capital):
    """
    Same fold-slicing/pooling approach as backtest_donchian.py's
    slice_trades_by_folds() (duplicated rather than imported — see module
    docstring judgment call 3): slice trades by entry_timestamp against
    each fold's test window, summarize relative to that fold's own
    starting equity, and pool everything from fold 1's test start onward.
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
    parser.add_argument("--folds", type=int, default=DEFAULT_NUM_FOLDS)
    parser.add_argument("--initial-train-days", type=int, default=DEFAULT_INITIAL_TRAIN_DAYS)
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

        daily = resample_candles(hourly, 24)

        # Fold boundaries anchored off the hourly series (primary traded
        # timeframe here) — see module docstring judgment call 2.
        actual_start = datetime.fromisoformat(hourly[0].timestamp)
        actual_end = datetime.fromisoformat(hourly[-1].timestamp)
        folds = compute_fold_boundaries(
            actual_start, actual_end, num_folds=args.folds, initial_train_days=args.initial_train_days
        )

        daily_regime = compute_daily_regime_series(daily)
        entry_indices, _, _ = compute_hourly_entry_indices(hourly, daily_regime)

        print(f"\n=== {symbol}: MACD D1H1 (daily-regime + hourly-entry, price-action trail), {args.folds}-fold anchored walk-forward ===")
        print(f"history: {actual_start.date()} to {actual_end.date()}  ({len(hourly)} hourly candles, {len(daily)} daily candles)")
        print(f"fold boundaries (initial train {args.initial_train_days}d, then {args.folds} contiguous test windows):")
        for fold in folds:
            print(
                f"  fold {fold['fold']}: train {fold['train_start'].date()} -> {fold['train_end'].date()}"
                f"  |  test {fold['test_start'].date()} -> {fold['test_end'].date()}"
            )
        print(f"(fee model: {DEFAULT_TAKER_FEE_PCT:.2f}% taker + {DEFAULT_SLIPPAGE_BPS:.0f}bps slippage per leg)")
        print(f"raw hourly entry signals (daily-regime-gated): {len(entry_indices)}")

        net_trades, net_curve = simulate_macd_d1h1(
            hourly, entry_indices,
            capital=DEFAULT_CAPITAL, fee_pct=DEFAULT_TAKER_FEE_PCT, slippage_bps=DEFAULT_SLIPPAGE_BPS,
        )
        gross_trades, gross_curve = simulate_macd_d1h1(
            hourly, entry_indices,
            capital=DEFAULT_CAPITAL, fee_pct=0.0, slippage_bps=0.0,
        )
        net_folds, net_pooled = slice_trades_by_folds(net_trades, net_curve, folds, DEFAULT_CAPITAL)
        gross_folds, gross_pooled = slice_trades_by_folds(gross_trades, gross_curve, folds, DEFAULT_CAPITAL)

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
