"""
ONE-OFF DIAGNOSTIC, not a new finding and not meant to be maintained (same
convention as scripts/verify_finding12_sizing.py / sanity_check_daily_
signal.py). Track B follow-up: the user confirmed the pre-committed bar
(pooled net-positive, 3/3 folds) is cleared and wants one more number
before any adopt/abandon call — max drawdown (peak-to-trough) of the
8-ETF equal-weight buy-and-hold blend, and each individual ETF's own max
drawdown, over the SAME 2016-01-04 -> 2026-08-07 window as Track B's
backtest (backtest_etf_donchian.py). This is the risk-adjusted comparison
the raw-return-only report couldn't answer — Track B's own pooled max
drawdown (5.69%) was already reported; this script computes the
buy-and-hold side of that comparison, not previously computed.

Reuses build_symbol_series()/UNIVERSE/REQUESTED_START from
backtest_etf_donchian.py unchanged (same fetch, same 8 tickers, same
2016-01-04 account-level truncation already documented there) — no
strategy logic touched, this is read-only diagnostics on the raw price
series.

Blend construction: equal-weight, buy-at-window-start, never rebalanced —
same convention backtest_donchian_ensemble.py's compute_buy_and_hold_
portfolio_return() already uses for the pooled RETURN number (portfolio
return = simple average of per-symbol % returns, since each symbol got
an equal dollar allocation at t0). Extended here to a full daily EQUITY
CURVE (needed for drawdown, which return alone can't give): each day's
blend relative value = average across the 8 symbols of (that day's close
/ that symbol's entry close). The final value of this curve should
reproduce Track B's already-reported blend total return (+164.01%) as a
sanity check that this is the same portfolio, just with drawdown added.

Usage:
    python scripts/compute_buy_and_hold_drawdown.py
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.backtest_etf_donchian import (
    UNIVERSE, build_symbol_series, REQUESTED_START, NUM_FOLDS, INITIAL_TRAIN_DAYS,
)
from scripts.backtest_walkforward import compute_fold_boundaries


def compute_max_drawdown_pct(values):
    """Standard peak-to-trough max drawdown over a value series (price or equity)."""
    peak = values[0]
    max_dd = 0.0
    for v in values:
        peak = max(peak, v)
        dd = (peak - v) / peak * 100 if peak > 0 else 0.0
        max_dd = max(max_dd, dd)
    return max_dd


def blend_curve_over_window(symbol_data, calendar, window_start_date, window_end_date):
    """
    Equal-weight, buy-at-window-start/hold-to-window-end, never-rebalanced
    blend equity curve restricted to [window_start_date, window_end_date]
    (inclusive date strings) — same convention as backtest_donchian_
    ensemble.py's compute_buy_and_hold_portfolio_return(), extended to a
    full daily curve (needed for drawdown) instead of just a start/end
    return. Entry price is each symbol's first close ON OR AFTER
    window_start_date, matching that function's judgment call.
    """
    window_dates = [d for d in calendar if window_start_date <= d <= window_end_date]
    entry_price = {}
    for sym in UNIVERSE:
        idx = symbol_data[sym]["date_index"].get(window_dates[0])
        if idx is None:
            # first available close on/after window_start_date
            later = [d for d in symbol_data[sym]["date_index"] if d >= window_start_date]
            idx = symbol_data[sym]["date_index"][sorted(later)[0]] if later else None
        if idx is not None:
            entry_price[sym] = symbol_data[sym]["candles"][idx].close

    curve = []
    for date in window_dates:
        relatives = []
        for sym in UNIVERSE:
            if sym not in entry_price:
                continue
            idx = symbol_data[sym]["date_index"].get(date)
            if idx is None:
                continue
            relatives.append(symbol_data[sym]["candles"][idx].close / entry_price[sym])
        if relatives:
            curve.append(sum(relatives) / len(relatives))
    return curve


def main():
    end = datetime.now(timezone.utc) - timedelta(minutes=20)

    print(f"=== Track B follow-up: buy-and-hold max drawdown, {REQUESTED_START.date()} (requested) -> present ===")
    symbol_data = {}
    for symbol in UNIVERSE:
        series = build_symbol_series(symbol, REQUESTED_START, end)
        if series is None:
            print(f"{symbol}: no candle data returned, excluding")
            continue
        symbol_data[symbol] = series

    calendar = sorted(set().union(*(s["date_index"].keys() for s in symbol_data.values())))
    starts = {sym: symbol_data[sym]["candles"][0].timestamp[:10] for sym in symbol_data}
    ends = {sym: symbol_data[sym]["candles"][-1].timestamp[:10] for sym in symbol_data}
    uniform = len(set(starts.values())) == 1 and len(set(ends.values())) == 1
    print(f"full fetched window: {calendar[0]} -> {calendar[-1]}  ({len(calendar)} trading days)")
    print(f"per-symbol history uniform across all 8 tickers: {uniform}" + ("" if uniform else f"  starts={starts}  ends={ends}"))

    # Recover the exact pooled TEST window Track B's own backtest used
    # (fold 1 test_start -> fold N test_end) so the comparison is
    # apples-to-apples with the strategy's own reported net%/max_dd%,
    # which excludes the initial training-only period.
    actual_start = datetime.fromisoformat(calendar[0]).replace(tzinfo=timezone.utc)
    actual_end = datetime.fromisoformat(calendar[-1]).replace(tzinfo=timezone.utc)
    folds = compute_fold_boundaries(actual_start, actual_end, num_folds=NUM_FOLDS, initial_train_days=INITIAL_TRAIN_DAYS)
    pooled_test_start = folds[0]["test_start"].date().isoformat()
    pooled_test_end = folds[-1]["test_end"].date().isoformat()
    print(f"pooled TEST window (excludes initial {INITIAL_TRAIN_DAYS}d training-only period, matches Track B's reported net%/max_dd%): {pooled_test_start} -> {pooled_test_end}")

    print(f"\n=== Individual ETF buy-and-hold max drawdown (own price series) ===")
    print(f"{'symbol':<8}{'full_window_dd%':<18}{'pooled_test_window_dd%':<24}")
    for symbol in UNIVERSE:
        full_closes = [c.close for c in symbol_data[symbol]["candles"]]
        full_dd = compute_max_drawdown_pct(full_closes)
        pooled_dates = [d for d in symbol_data[symbol]["date_index"] if pooled_test_start <= d <= pooled_test_end]
        pooled_closes = [symbol_data[symbol]["candles"][symbol_data[symbol]["date_index"][d]].close for d in pooled_dates]
        pooled_dd = compute_max_drawdown_pct(pooled_closes) if pooled_closes else None
        print(f"{symbol:<8}{full_dd:<18.2f}{(f'{pooled_dd:.2f}' if pooled_dd is not None else 'n/a'):<24}")

    print(f"\n=== 8-ETF equal-weight blend buy-and-hold max drawdown ===")
    full_curve = blend_curve_over_window(symbol_data, calendar, calendar[0], calendar[-1])
    full_dd = compute_max_drawdown_pct(full_curve)
    full_return_pct = (full_curve[-1] - 1.0) * 100
    print(f"  FULL fetched window ({calendar[0]} -> {calendar[-1]}): max drawdown {full_dd:.2f}%, total return {full_return_pct:.2f}%")

    pooled_curve = blend_curve_over_window(symbol_data, calendar, pooled_test_start, pooled_test_end)
    pooled_dd = compute_max_drawdown_pct(pooled_curve)
    pooled_return_pct = (pooled_curve[-1] - 1.0) * 100
    print(f"  POOLED TEST window ({pooled_test_start} -> {pooled_test_end}): max drawdown {pooled_dd:.2f}%, total return {pooled_return_pct:.2f}%")
    print(f"  (sanity check: pooled-window total return should reproduce Track B's already-reported +164.01% -- got {pooled_return_pct:.2f}%)")

    print(f"\n=== Risk-adjusted comparison (apples-to-apples: pooled TEST window, matching Track B's reported figures) ===")
    print(f"  Track B strategy pooled net-of-costs max drawdown: 5.69%  (already reported, over the pooled test window)")
    print(f"  8-ETF buy-and-hold blend max drawdown, same window: {pooled_dd:.2f}%")
    print(f"\n=== For reference: full fetched window (includes the 2016-01-04->{pooled_test_start} training-only period Track B's own numbers exclude) ===")
    print(f"  8-ETF buy-and-hold blend max drawdown, full window:  {full_dd:.2f}%")


if __name__ == "__main__":
    main()
