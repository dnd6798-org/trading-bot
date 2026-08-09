"""
ONE-OFF DIAGNOSTIC (not meant to be maintained, same convention as
scripts/compute_buy_and_hold_drawdown.py) — Track A's mandatory
buy-and-hold context, requested but not yet delivered before Track A's
final evaluation: buy-and-hold SPY, and a static 60/40 SPY/AGG portfolio,
both return AND max drawdown, over the IDENTICAL pooled test window
Track A's own findings use (2017-01-31 -> 2026-07-31, derived from real
fetched data via the same month_end_dates/MOMENTUM_LOOKBACK_MONTHS logic
backtest_gem.py's main() uses, not hardcoded — reproduces that window
automatically if the underlying data ever shifts).

Reuses build_symbol_series()/compute_shared_calendar()/compute_month_end_
dates()/compute_max_drawdown_pct()/REQUESTED_START/MOMENTUM_LOOKBACK_
MONTHS from backtest_gem.py unchanged — same Adjustment.ALL (dividend+
split-adjusted) data, since both benchmarks are total-return comparisons
and AGG's return is mostly distributions, same correctness reasoning
that applied to GEM's own signal (see backtest_gem.py's module docstring
and src/data_ingestion.py's fetch_historical_stock_candles() docstring).

Two benchmarks, both buy-at-window-start/hold-to-window-end with NO
rebalancing — same convention as Track B's compute_buy_and_hold_
portfolio_return() (backtest_donchian_ensemble.py), a judgment call
flagged here: "static 60/40" could also mean monthly- or annually-
REBALANCED to maintain the 60/40 target weight, which is at least as
common a convention for this specific benchmark in the literature. This
script implements the no-rebalance reading (weights drift with relative
performance from the initial 60/40 split) for consistency with every
other buy-and-hold figure already reported in this repo; a rebalanced
variant would need separate code and is not built here.

Usage:
    python scripts/compute_gem_benchmarks.py
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.backtest_gem import (
    build_symbol_series,
    compute_shared_calendar,
    compute_month_end_dates,
    compute_max_drawdown_pct,
    REQUESTED_START,
    MOMENTUM_LOOKBACK_MONTHS,
)

# Track A's already-reported pooled figures (backtest_gem.py's own output,
# not recomputed here) -- included only for a direct side-by-side table.
GEM_RESULTS = [
    ("Base GEM (no circuit breaker)", 138.90, 33.79),
    ("GEM + 15% circuit breaker (v2)", 120.09, 24.58),
    ("GEM + 20% circuit breaker (v2)", 133.38, 24.94),
]


def main():
    end = datetime.now(timezone.utc) - timedelta(minutes=20)

    print("=== Track A benchmark context: buy-and-hold SPY + static 60/40 SPY/AGG ===")
    symbol_data = {}
    for symbol in ["SPY", "AGG"]:
        series = build_symbol_series(symbol, REQUESTED_START, end)
        symbol_data[symbol] = series
        first, last = series["candles"][0], series["candles"][-1]
        print(f"  {symbol}: {first.timestamp[:10]} -> {last.timestamp[:10]}  ({len(series['candles'])} daily candles, dividend+split adjusted)")

    full_calendar = compute_shared_calendar(symbol_data, ["SPY", "AGG"])
    month_end_dates = compute_month_end_dates(full_calendar)
    live_eval_dates = month_end_dates[MOMENTUM_LOOKBACK_MONTHS:]
    calendar = [d for d in full_calendar if live_eval_dates[0] <= d <= live_eval_dates[-1]]
    print(f"\nwindow (reproduced from real data, matching Track A's own pooled test window): {calendar[0]} -> {calendar[-1]}  ({len(calendar)} trading days)")

    def _price_series(symbol):
        series = symbol_data[symbol]
        return [series["candles"][series["date_index"][d]].close for d in calendar]

    spy_prices = _price_series("SPY")
    agg_prices = _price_series("AGG")

    spy_entry, spy_exit = spy_prices[0], spy_prices[-1]
    spy_return_pct = (spy_exit - spy_entry) / spy_entry * 100
    spy_dd = compute_max_drawdown_pct(spy_prices)

    agg_entry = agg_prices[0]
    blend_curve = [0.6 * (sp / spy_entry) + 0.4 * (ap / agg_entry) for sp, ap in zip(spy_prices, agg_prices)]
    blend_return_pct = (blend_curve[-1] - 1.0) * 100
    blend_dd = compute_max_drawdown_pct(blend_curve)

    print(f"\n=== Buy-and-hold SPY (100%, no rebalancing) ===")
    print(f"  return: {spy_return_pct:.2f}%   max drawdown: {spy_dd:.2f}%")

    print(f"\n=== Static 60/40 SPY/AGG (buy-at-window-start, NO rebalancing -- see module docstring's judgment call) ===")
    print(f"  return: {blend_return_pct:.2f}%   max drawdown: {blend_dd:.2f}%")

    print(f"\n=== Side-by-side comparison (pooled, net-of-cost for GEM variants) ===")
    print(f"{'label':<38}{'return%':<12}{'max_dd%':<12}")
    print(f"{'Buy-and-hold SPY':<38}{spy_return_pct:<12.2f}{spy_dd:<12.2f}")
    print(f"{'Static 60/40 SPY/AGG (no rebalance)':<38}{blend_return_pct:<12.2f}{blend_dd:<12.2f}")
    for label, ret, dd in GEM_RESULTS:
        print(f"{label:<38}{ret:<12.2f}{dd:<12.2f}")


if __name__ == "__main__":
    main()
