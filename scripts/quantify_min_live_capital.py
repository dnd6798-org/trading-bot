"""
ONE-OFF diagnostic (NOT meant to be maintained — same convention as
scripts/select_universe.py, scripts/verify_finding12_sizing.py, scripts/
quantify_track_b_notional_concentration.py).

PURPOSE (v85 read-only analysis, Part B — CLAUDE.md v85 status entry):
quantify the minimum live Stage-1 account equity needed for Track B's
real, ATR-risk-based position sizing to floor to a viable whole-share
count, given Alpaca's confirmed structural limitation that fractional-
quantity GTC stop orders are rejected outright (spec — see CLAUDE.md's
"CRITICAL FINDING (2026-08-28)" — `submit_stop_order_with_retry()`
already floors qty to whole shares before every submission attempt,
`src/execution.py`, FIX 1). This answers the "$100 REAL-MONEY GO-LIVE
FIGURE RETIRED... Stage 1 capital must be set from a whole-share-
viability quantification" open item in CLAUDE.md's v85 status entry.
READ-ONLY ANALYSIS ONLY — no strategy, sizing, or signal logic in src/ or
any existing script is modified here; no order-submitting or state-
changing Alpaca API call is made.

INPUTS, REUSED COMPLETELY UNCHANGED:
  - The per-trade entry-sizing detail (all 219 real Track B trades,
    2016-01-04 -> present, symbol + uncapped_notional_pct_of_equity) is
    reproduced by reusing scripts/quantify_track_b_notional_
    concentration.py's own module-level constants
    (TRACK_B_MAX_POSITIONS, TRACK_B_RISK_BUDGET_PCT,
    TRACK_B_NOTIONAL_CAP_PCT — that script's ORIGINAL, already-passed
    Track B configuration: notional_sanity_cap_pct=100%, so the logged
    uncapped_notional_pct_of_equity is genuinely uncapped) plus
    backtest_etf_donchian.py's UNIVERSE/ATR_MULTIPLIER/
    ETF_COMMISSION_PCT/ETF_SLIPPAGE_BPS/REQUESTED_START/
    build_symbol_series and backtest_donchian_ensemble.py's
    simulate_rotational_ensemble()/PAPER_VALIDATION_CAPITAL — the exact
    same simulate_rotational_ensemble() call that script makes, not a
    new one. The LIVE cap (config.MAX_SINGLE_POSITION_NOTIONAL_PCT, 55%)
    is then applied HERE, in this script only, to each entry's
    uncapped_notional_pct_of_equity — reproducing what the live
    guardrail (get_track_b_guardrail_config()'s max_position_size_pct,
    src/config.py) actually does, without re-running the simulation with
    a different notional_sanity_cap_pct argument (which would change
    which trades the equal-risk-contribution budget accepts/shrinks
    downstream, per simulate_rotational_ensemble()'s own mechanics —
    applying min(uncapped, 55%) as a pure post-hoc function on the
    ALREADY-taken 219 trades' uncapped figures is the correct way to ask
    "what would the live 55% cap have done to each of these entries",
    without conflating it with a different backtest run's own trade
    selection).
  - Current price per symbol: the most recent completed daily close for
    each of the 8 Track B UNIVERSE symbols, fetched via
    backtest_etf_donchian.build_symbol_series() (unchanged — the same
    RAW-adjustment daily-bar fetch every Track B script already uses),
    over a short recent window ending "now - 20min" (the same SIP
    settle-delay convention every script in this repo already uses).
  - config.TRACK_B_ALLOCATION_PCT (0.70) — the fraction of current total
    account equity Track B sizes against (spec v53 §10.23).

SNAPSHOT CAVEAT (stated explicitly, not just implied): this is a
snapshot at the reported current-price date. A trade's
notional_pct_of_equity depends only on its entry ATR-to-price ratio and
the sizing formula (see CLAUDE.md's Track B notional-concentration
milestone, spec v30 §10.2) — it does NOT depend on price level — so
applying a HISTORICAL notional_pct_of_equity against TODAY's price to
get a dollar/share-count answer is valid. The dollar-equity results
(E, share counts) themselves are a function of today's prices and will
move as prices move; the underlying notional_pct distributions will not
(short of a genuine ATR-regime shift).

Usage:
    python scripts/quantify_min_live_capital.py
"""
import math
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import MAX_SINGLE_POSITION_NOTIONAL_PCT, TRACK_B_ALLOCATION_PCT
from scripts.backtest_donchian_ensemble import simulate_rotational_ensemble, PAPER_VALIDATION_CAPITAL
from scripts.backtest_etf_donchian import (
    build_symbol_series,
    UNIVERSE,
    ATR_MULTIPLIER,
    ETF_COMMISSION_PCT,
    ETF_SLIPPAGE_BPS,
    REQUESTED_START,
)
from scripts.quantify_track_b_notional_concentration import (
    TRACK_B_MAX_POSITIONS,
    TRACK_B_RISK_BUDGET_PCT,
    TRACK_B_NOTIONAL_CAP_PCT,
)

N_VALUES = [1, 5, 10]
EQUITY_SCENARIOS = [10_000.0, 100.0]
CURRENT_PRICE_LOOKBACK_DAYS = 30  # comfortably covers weekends/holidays to guarantee at least one recent daily bar


# =============================================================================
# Pure functions (unit-tested on hand-computed values — see
# tests/test_quantify_min_live_capital.py)
# =============================================================================
def percentile(values, p):
    """
    Linear-interpolation percentile (numpy's default "linear" method),
    p in [0, 1]. Returns None for an empty input.
    """
    if not values:
        return None
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * p
    f = math.floor(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def apply_live_cap(uncapped_pct, cap_pct):
    """The live guardrail's own rule: notional_pct = min(uncapped, cap)."""
    return min(uncapped_pct, cap_pct)


def min_equity_for_n_shares(n, price, alloc_pct, notional_pct):
    """
    The minimum total account equity E such that a trade sized at
    `notional_pct`% of the track's own (alloc_pct-fraction) sub-balance,
    at `price`, has an UNFLOORED share count of exactly n (the smallest E
    for which floor(shares) >= n, since unfloored_shares(E) is
    continuous and strictly increasing in E).

    alloc_pct: fraction in [0, 1] (e.g. TRACK_B_ALLOCATION_PCT, 0.70).
    notional_pct: percent, 0-100.
    """
    return n * price / (alloc_pct * (notional_pct / 100.0))


def unfloored_shares(equity, alloc_pct, notional_pct, price):
    """The exact (pre-floor) share count a trade at this equity/notional_pct/price would size to."""
    return equity * alloc_pct * (notional_pct / 100.0) / price


def floor_shares(shares):
    return math.floor(shares)


def undersizing_pct(unfloored, floored):
    """% reduction in position size caused by flooring to a whole share. 0.0 when unfloored <= 0 (no position)."""
    if unfloored <= 0:
        return 0.0
    return (unfloored - floored) / unfloored * 100.0


# =============================================================================
# Reporting
# =============================================================================
def main():
    end = datetime.now(timezone.utc) - timedelta(minutes=20)  # SIP settle-delay convention, same as every other script in this repo

    print("=== v85 Part B: minimum live Stage-1 capital for whole-share Track B sizing (READ-ONLY, no strategy/sizing/signal logic changed) ===")
    print(f"MAX_SINGLE_POSITION_NOTIONAL_PCT (live cap) = {MAX_SINGLE_POSITION_NOTIONAL_PCT}%   TRACK_B_ALLOCATION_PCT = {TRACK_B_ALLOCATION_PCT}")

    # --- reproduce the 219-trade entry_sizing_log, Track B's ORIGINAL uncapped configuration ---
    print("\n--- reproducing Track B's original (100%-cap) backtest for uncapped per-trade sizing detail ---")
    symbol_data = {}
    for symbol in UNIVERSE:
        series = build_symbol_series(symbol, REQUESTED_START, end)
        if series is None:
            print(f"  {symbol}: NO DATA — aborting")
            return
        symbol_data[symbol] = series
    universe_order = [s for s in UNIVERSE if s in symbol_data]

    entry_sizing_log = []
    trades, _equity_curve, _skipped_log = simulate_rotational_ensemble(
        symbol_data, universe_order,
        max_positions=TRACK_B_MAX_POSITIONS, atr_multiplier=ATR_MULTIPLIER,
        capital=PAPER_VALIDATION_CAPITAL, total_risk_budget_pct=TRACK_B_RISK_BUDGET_PCT,
        notional_sanity_cap_pct=TRACK_B_NOTIONAL_CAP_PCT,
        fee_pct=ETF_COMMISSION_PCT, slippage_bps=ETF_SLIPPAGE_BPS,
        entry_sizing_log=entry_sizing_log,
    )
    print(f"  {len(trades)} trades, {len(entry_sizing_log)} entries logged "
          f"(sanity check: should reproduce Track B's known 219-trade total — CLAUDE.md 'Track B findings' 1 / quantify_track_b_notional_concentration.py)")

    by_symbol_uncapped = {}
    for e in entry_sizing_log:
        by_symbol_uncapped.setdefault(e["symbol"], []).append(e["uncapped_notional_pct_of_equity"])

    # --- current price per symbol -------------------------------------------
    print("\n--- fetching current price per symbol ---")
    current_price = {}
    current_price_date = {}
    price_start = end - timedelta(days=CURRENT_PRICE_LOOKBACK_DAYS)
    for symbol in UNIVERSE:
        series = build_symbol_series(symbol, price_start, end)
        if series is None:
            print(f"  {symbol}: NO DATA — aborting")
            return
        last_candle = series["candles"][-1]
        current_price[symbol] = last_candle.close
        current_price_date[symbol] = last_candle.timestamp[:10]
        print(f"  {symbol:4s}: ${last_candle.close:.2f}  ({last_candle.timestamp[:10]})")

    # =========================================================================
    # Report item 1: per-symbol median / p10 capped notional %
    # =========================================================================
    print("\n=== Report item 1: per-symbol median / 10th-percentile CAPPED notional % of equity ===")
    capped_by_symbol = {}
    median_capped = {}
    p10_capped = {}
    for symbol in universe_order:
        uncapped = by_symbol_uncapped.get(symbol, [])
        capped = [apply_live_cap(u, MAX_SINGLE_POSITION_NOTIONAL_PCT) for u in uncapped]
        capped_by_symbol[symbol] = capped
        median_capped[symbol] = statistics.median(capped) if capped else None
        p10_capped[symbol] = percentile(capped, 0.10)
        print(f"  {symbol:4s}: n={len(capped):3d}  median={median_capped[symbol]:.2f}%  p10={p10_capped[symbol]:.2f}%")

    # =========================================================================
    # Report item 2: minimum equity for N whole shares, per symbol + binding
    # =========================================================================
    print("\n=== Report item 2: minimum total account equity E for the median/p10 trade to floor to >= N whole shares ===")
    for n in N_VALUES:
        print(f"\n  N={n}:")
        binding_symbol = None
        binding_e = -1.0
        rows = []
        for symbol in universe_order:
            price = current_price[symbol]
            e_median = min_equity_for_n_shares(n, price, TRACK_B_ALLOCATION_PCT, median_capped[symbol])
            e_p10 = min_equity_for_n_shares(n, price, TRACK_B_ALLOCATION_PCT, p10_capped[symbol])
            e_symbol = max(e_median, e_p10)
            binder = "median" if e_median >= e_p10 else "p10"
            rows.append((symbol, e_median, e_p10, e_symbol, binder))
            if e_symbol > binding_e:
                binding_e = e_symbol
                binding_symbol = symbol
        for symbol, e_median, e_p10, e_symbol, binder in rows:
            print(f"    {symbol:4s}: E(median)=${e_median:,.2f}  E(p10)=${e_p10:,.2f}  -> E(symbol)=${e_symbol:,.2f}  (binding: {binder})")
        print(f"  -> binding (highest) E across all 8 symbols for N={n}: ${binding_e:,.2f}  (symbol: {binding_symbol})")

    # =========================================================================
    # Report item 3: at E=$10,000 and E=$100, per symbol, median trade detail
    # =========================================================================
    print("\n=== Report item 3: at E=$10,000 / $100, the median trade's unfloored/floored share count and %-unprotected ===")
    for equity in EQUITY_SCENARIOS:
        print(f"\n  E=${equity:,.0f}:")
        for symbol in universe_order:
            price = current_price[symbol]
            unf = unfloored_shares(equity, TRACK_B_ALLOCATION_PCT, median_capped[symbol], price)
            flo = floor_shares(unf)
            pct_unprotected = undersizing_pct(unf, flo)
            print(f"    {symbol:4s}: unfloored={unf:.4f} shares  floored={flo} shares  %-of-position-with-no-GTC-stop={pct_unprotected:.2f}%")

    # =========================================================================
    # Report item 4: at E=$10,000 and E=$100, across all 219 trades, floored-to-zero count
    # =========================================================================
    print("\n=== Report item 4: at E=$10,000 / $100, across all 219 trades at CURRENT prices, count/% whose floored qty would be 0 ===")
    for equity in EQUITY_SCENARIOS:
        zero_count = 0
        total = 0
        for e in entry_sizing_log:
            symbol = e["symbol"]
            price = current_price[symbol]
            capped_pct = apply_live_cap(e["uncapped_notional_pct_of_equity"], MAX_SINGLE_POSITION_NOTIONAL_PCT)
            unf = unfloored_shares(equity, TRACK_B_ALLOCATION_PCT, capped_pct, price)
            flo = floor_shares(unf)
            total += 1
            if flo == 0:
                zero_count += 1
        print(f"  E=${equity:,.0f}: {zero_count} of {total} trades ({zero_count / total * 100:.2f}%) would floor to 0 shares")

    # =========================================================================
    # Report item 5: median % reduction in position size per symbol at E=$10,000
    # =========================================================================
    print("\n=== Report item 5: median %-reduction in position size (whole-share flooring) per symbol, at E=$10,000, across each symbol's own real trades ===")
    equity = 10_000.0
    for symbol in universe_order:
        price = current_price[symbol]
        reductions = []
        for e in entry_sizing_log:
            if e["symbol"] != symbol:
                continue
            capped_pct = apply_live_cap(e["uncapped_notional_pct_of_equity"], MAX_SINGLE_POSITION_NOTIONAL_PCT)
            unf = unfloored_shares(equity, TRACK_B_ALLOCATION_PCT, capped_pct, price)
            flo = floor_shares(unf)
            reductions.append(undersizing_pct(unf, flo))
        median_reduction = statistics.median(reductions) if reductions else None
        print(f"  {symbol:4s}: n={len(reductions):3d}  median %-reduction={median_reduction:.2f}%" if median_reduction is not None else f"  {symbol:4s}: no trades")

    print(f"\nNOTE: all dollar/share-count results above are a SNAPSHOT at the current-price date(s) reported above "
          f"({sorted(set(current_price_date.values()))}). notional_pct_of_equity itself depends only on ATR/price at "
          f"ENTRY time, not on today's price level, so historical notional_pct x current price is a valid combination "
          f"— but the dollar results will move as prices move.")


if __name__ == "__main__":
    main()
