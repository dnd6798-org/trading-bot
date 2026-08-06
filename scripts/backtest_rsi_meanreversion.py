"""
EXPERIMENT — RSI(14) regime-filtered mean-reversion, daily candles, long-
only. New strategy family, replacing MACD D1H1 (CLAUDE.md finding 8 /
commit b4ef340 on `paper`: pooled net-of-fees sharply negative on both
symbols, 0/5 folds positive on either, severe fee drag from a high-
turnover price-action exit — formally rejected). First mean-reversion
strategy tried in this repo; findings 1-8 were all trend-following.

Signal:
  - Entry: RSI(14) on daily candles drops below 30 (oversold). Implemented
    as a downward CROSS (RSI[i-1] >= 30, RSI[i] < 30), not a bare level
    check — same crossing convention every entry signal in this repo
    already uses (EMA crossover, MACD crossover, Donchian breakout). A
    level check would keep re-firing every day RSI stays under 30; since
    this repo's simulate loops already skip a signal while a position is
    open (see simulate_rsi_meanreversion), a level check and a cross check
    only differ in the (rare) case where a prior trade closes via
    time-stop while RSI is still under 30 — cross avoids re-entering
    on stale oversold-ness that hasn't produced a fresh dip. Flagged as a
    judgment call, not explicitly specified in the brief.
  - Regime filter: entry only valid if daily close is above the daily
    200-SMA at that point — restricts entries to dips within an uptrend,
    not against one (per-brief: this is a from-the-start design choice,
    not something added after seeing results, addressing the "buying dips
    in a downtrend" failure mode from external research).
  - Long-only (Alpaca doesn't support crypto shorting — same constraint as
    every prior finding since 6).

Exit: whichever comes first —
  - RSI(14) reverts back above 50 ("rsi_revert"), OR
  - 10 daily candles have elapsed since entry with no reversion
    ("time_stop"). "10 trading days" is read as 10 daily candles, since
    crypto trades 24/7 and every prior daily-timeframe finding in this
    repo (4, 8) already treats one daily candle as one trading day.
  A THIRD, distinct exit philosophy from the ATR fixed stop/TP (findings
  1-7's simulate()/simulate_donchian()) and the price-action trailing exit
  (finding 8's simulate_macd_d1h1()) — implemented as its own function,
  resolve_exit(), kept separate from the trade-simulation loop so all
  three exit styles stay independently readable/comparable, same
  separation-of-concerns the brief asked for.

No additional filters this round (brief: keep the base variant clean,
same discipline as prior milestones). Fixed-rule strategy, not a
parameter grid — RSI(14)/30/50/200-SMA/10-day are the specified
parameters, not tuned this round.

Reuses UNCHANGED, per instruction — nothing about fees or fold boundaries
was touched:
  - backtest.py's fee constants (DEFAULT_TAKER_FEE_PCT 0.25%/leg taker,
    DEFAULT_SLIPPAGE_BPS 5bps/leg slippage), compute_sma() (for the daily
    200-SMA regime filter), summarize() (its stop_rate_pct/
    take_profit_rate_pct columns don't apply to this strategy's exit_reason
    values and report 0%; trade_count/win_rate/total_return_pct/
    max_drawdown_pct are what this report needs and don't depend on those
    labels), resample_candles() (daily series from the same hourly fetch,
    same trick findings 4-8 already use — no second network call needed).
  - backtest_walkforward.py's compute_fold_boundaries() (same 5-fold,
    365-day-initial-train logic) over the same 2021-01-03 -> present
    dataset.

JUDGMENT CALLS (flagged per instruction, not self-adjudicated):
  1. Entry as a downward RSI cross rather than a bare "RSI < 30" level —
     see the Signal section above.
  2. Position sizing: same open gap as finding 8 — this signal has no
     natural stop-distance for the spec §4.1 1%-risk formula (a
     time-stop exit, like finding 8's price-action exit, isn't priced off
     a fixed initial stop). Sized flat at max_position_pct (25% of
     equity), identical to finding 8's resolution of the same gap.
     r_multiple is a nominal scorecard against DEFAULT_RISK_PER_TRADE_PCT
     (1% of equity), NOT tied to actual sizing — same caveat as finding 8.
  3. Fold boundaries anchored off the DAILY candle series' actual
     start/end. Unlike finding 8 (which traded hourly with a daily
     filter, and had to pick one), this strategy trades daily bars only —
     there's no dual-timeframe ambiguity, so the daily series is the only
     sensible anchor.
  4. Does NOT reuse backtest.py's simulate(), backtest_donchian.py's
     simulate_donchian(), or backtest_macd_d1h1.py's simulate_macd_d1h1():
     none can express an RSI-level entry gated by a separate SMA regime
     filter, nor a dual-exit-condition (RSI-revert OR time-stop) rule.
     Re-implements the trade loop as simulate_rsi_meanreversion() and
     duplicates the fold-slicing/pooling logic as slice_trades_by_folds()
     — same duplication-over-modification approach findings 7 and 8
     already used and documented for the same reason.

Usage:
    python scripts/backtest_rsi_meanreversion.py
    python scripts/backtest_rsi_meanreversion.py --symbols BTC/USD
"""
import argparse
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data_ingestion import fetch_historical_candles, TRADING_PAIRS
from src.signal_generation import compute_rsi
from scripts.backtest import (
    resample_candles,
    compute_sma,
    summarize,
    _print_table,
    DEFAULT_CAPITAL,
    DEFAULT_TAKER_FEE_PCT,
    DEFAULT_SLIPPAGE_BPS,
    DEFAULT_RISK_PER_TRADE_PCT,
    DEFAULT_MAX_POSITION_PCT,
)
from scripts.backtest_walkforward import compute_fold_boundaries, DEFAULT_NUM_FOLDS, DEFAULT_INITIAL_TRAIN_DAYS

RSI_PERIOD = 14          # standard convention, not tuned this round — see module docstring
RSI_OVERSOLD = 30
RSI_EXIT = 50
SMA_PERIOD = 200
TIME_STOP_DAYS = 10


@dataclass
class RsiMeanReversionTrade:
    entry_index: int
    exit_index: int
    entry_timestamp: str
    exit_timestamp: str
    entry_price: float
    exit_price: float
    exit_reason: str  # "rsi_revert" | "time_stop" | "eol"
    gross_pnl: float
    fees_paid: float
    pnl: float  # net of fees
    r_multiple: float  # nominal scorecard only — see module docstring judgment call 2


def compute_entry_indices(daily_candles, rsi_period=RSI_PERIOD, sma_period=SMA_PERIOD, oversold=RSI_OVERSOLD):
    """
    Indices where a long entry fires: RSI(rsi_period) crosses down below
    `oversold` AND that day's close is above the SMA(sma_period) regime
    filter. Both series are causal (index i only depends on
    daily_candles[0..i]), so this is walk-forward correct without needing
    to re-run per-slice.
    """
    closes = [c.close for c in daily_candles]
    rsi = compute_rsi(closes, rsi_period)
    sma = compute_sma(closes, sma_period)

    indices = []
    for i in range(1, len(daily_candles)):
        if None in (rsi[i], rsi[i - 1], sma[i]):
            continue
        crossed_down = rsi[i - 1] >= oversold and rsi[i] < oversold
        if crossed_down and closes[i] > sma[i]:
            indices.append(i)
    return indices, rsi, sma


def resolve_exit(daily_candles, rsi, entry_index, exit_threshold=RSI_EXIT, time_stop_days=TIME_STOP_DAYS):
    """
    Third, distinct exit philosophy (see module docstring) — kept as its
    own function, separate from the trade-simulation loop, so it stays
    independently readable/comparable against the ATR-based exit
    (backtest.py's simulate(), backtest_donchian.py's simulate_donchian())
    and the price-action trailing exit (backtest_macd_d1h1.py's
    simulate_macd_d1h1()).

    Scans forward from the candle after entry: exits at the close of the
    first candle where RSI reverts above `exit_threshold` ("rsi_revert"),
    or at the close of the candle `time_stop_days` after entry if RSI
    hasn't reverted by then ("time_stop") — checked in that order per
    candle, so a candle that satisfies both on the same day counts as a
    reversion, consistent with "whichever comes first." If neither
    condition is ever met before the end of the data, marks to the last
    close ("eol"), matching every other backtest's convention.
    """
    for j in range(entry_index + 1, len(daily_candles)):
        if rsi[j] is not None and rsi[j] > exit_threshold:
            return j, daily_candles[j].close, "rsi_revert"
        if j - entry_index >= time_stop_days:
            return j, daily_candles[j].close, "time_stop"

    last = len(daily_candles) - 1
    return last, daily_candles[last].close, "eol"


def simulate_rsi_meanreversion(
    daily_candles,
    entry_indices,
    rsi,
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
    every other backtest here). Sized flat at max_position_pct — see
    module docstring judgment call 2 for why there's no risk_pct/
    stop-distance sizing here.
    """
    cost_frac_per_leg = fee_pct / 100 + slippage_bps / 10000

    trades = []
    equity = capital
    equity_curve = [equity]
    position_open_until = -1

    for i in entry_indices:
        if i <= position_open_until:
            continue  # already in a position

        entry_price = daily_candles[i].close
        entry_equity = equity
        nominal_risk_amount = entry_equity * (risk_pct / 100)  # scorecard only, see judgment call 2
        position_size = (entry_equity * (max_position_pct / 100)) / entry_price

        exit_index, exit_price, exit_reason = resolve_exit(daily_candles, rsi, i)

        gross_pnl = position_size * (exit_price - entry_price)
        fees_paid = position_size * (entry_price + exit_price) * cost_frac_per_leg
        pnl = gross_pnl - fees_paid

        equity += pnl
        equity_curve.append(equity)
        trades.append(RsiMeanReversionTrade(
            entry_index=i,
            exit_index=exit_index,
            entry_timestamp=daily_candles[i].timestamp,
            exit_timestamp=daily_candles[exit_index].timestamp,
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
    Same fold-slicing/pooling approach as backtest_donchian.py's and
    backtest_macd_d1h1.py's slice_trades_by_folds() (duplicated rather
    than imported — see module docstring judgment call 4): slice trades by
    entry_timestamp against each fold's test window, summarize relative to
    that fold's own starting equity, and pool everything from fold 1's
    test start onward.
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


def _exit_reason_counts(trades):
    counts = {"rsi_revert": 0, "time_stop": 0, "eol": 0}
    for t in trades:
        counts[t.exit_reason] = counts.get(t.exit_reason, 0) + 1
    return counts


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

        # Fold boundaries anchored off the daily series — this strategy's
        # only traded timeframe, see module docstring judgment call 3.
        actual_start = datetime.fromisoformat(daily[0].timestamp)
        actual_end = datetime.fromisoformat(daily[-1].timestamp)
        folds = compute_fold_boundaries(
            actual_start, actual_end, num_folds=args.folds, initial_train_days=args.initial_train_days
        )

        entry_indices, rsi, sma = compute_entry_indices(daily)

        print(f"\n=== {symbol}: RSI(14) regime-filtered mean-reversion, {args.folds}-fold anchored walk-forward ===")
        print(f"history: {actual_start.date()} to {actual_end.date()}  ({len(hourly)} hourly candles, {len(daily)} daily candles)")
        print(f"fold boundaries (initial train {args.initial_train_days}d, then {args.folds} contiguous test windows):")
        for fold in folds:
            print(
                f"  fold {fold['fold']}: train {fold['train_start'].date()} -> {fold['train_end'].date()}"
                f"  |  test {fold['test_start'].date()} -> {fold['test_end'].date()}"
            )
        print(f"(fee model: {DEFAULT_TAKER_FEE_PCT:.2f}% taker + {DEFAULT_SLIPPAGE_BPS:.0f}bps slippage per leg)")
        print(f"raw daily entry signals (RSI<{RSI_OVERSOLD} cross, above daily-{SMA_PERIOD} SMA): {len(entry_indices)}")

        net_trades, net_curve = simulate_rsi_meanreversion(
            daily, entry_indices, rsi,
            capital=DEFAULT_CAPITAL, fee_pct=DEFAULT_TAKER_FEE_PCT, slippage_bps=DEFAULT_SLIPPAGE_BPS,
        )
        gross_trades, gross_curve = simulate_rsi_meanreversion(
            daily, entry_indices, rsi,
            capital=DEFAULT_CAPITAL, fee_pct=0.0, slippage_bps=0.0,
        )
        net_folds, net_pooled = slice_trades_by_folds(net_trades, net_curve, folds, DEFAULT_CAPITAL)
        gross_folds, gross_pooled = slice_trades_by_folds(gross_trades, gross_curve, folds, DEFAULT_CAPITAL)

        # Per-fold exit-reason breakdown (rsi_revert vs. time_stop vs. eol)
        # to see which exit mechanism is doing the work — net_trades sliced
        # the same way slice_trades_by_folds() slices for summarize().
        rows = []
        for fold, net, gross in zip(folds, net_folds, gross_folds):
            test_start_iso = fold["test_start"].isoformat()
            test_end_iso = fold["test_end"].isoformat()
            fold_trades = [t for t in net_trades if test_start_iso <= t.entry_timestamp < test_end_iso]
            reasons = _exit_reason_counts(fold_trades)
            rows.append({
                "fold": fold["fold"],
                "test_window": f"{fold['test_start'].date()}..{fold['test_end'].date()}",
                "n": net["trade_count"],
                "win%": f"{net['win_rate_pct']:.1f}",
                "net%": f"{net['total_return_pct']:.2f}",
                "gross%": f"{gross['total_return_pct']:.2f}",
                "max_dd%": f"{net['max_drawdown_pct']:.2f}",
                "rsi_revert": reasons["rsi_revert"],
                "time_stop": reasons["time_stop"],
                "eol": reasons["eol"],
            })
        pooled_reasons = _exit_reason_counts(net_trades)
        rows.append({
            "fold": "POOLED",
            "test_window": f"{folds[0]['test_start'].date()}..{folds[-1]['test_end'].date()}",
            "n": net_pooled["trade_count"],
            "win%": f"{net_pooled['win_rate_pct']:.1f}",
            "net%": f"{net_pooled['total_return_pct']:.2f}",
            "gross%": f"{gross_pooled['total_return_pct']:.2f}",
            "max_dd%": f"{net_pooled['max_drawdown_pct']:.2f}",
            "rsi_revert": pooled_reasons["rsi_revert"],
            "time_stop": pooled_reasons["time_stop"],
            "eol": pooled_reasons["eol"],
        })
        _print_table(rows, [
            ("fold", "fold"), ("test_window", "test_window"),
            ("n", "n"), ("win%", "win%"), ("net%", "net%"), ("gross%", "gross%"), ("max_dd%", "max_dd%"),
            ("rsi_revert", "rsi_revert"), ("time_stop", "time_stop"), ("eol", "eol"),
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
