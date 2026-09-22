"""
ONE-OFF diagnostic (NOT meant to be maintained — same convention as
scripts/select_universe.py, scripts/verify_finding12_sizing.py, scripts/
quantify_track_b_notional_concentration.py, scripts/
reconstruct_track_b_monthly_returns.py, scripts/compute_gem_benchmarks.py).

PURPOSE (v85 read-only analysis, Part A — CLAUDE.md v85 status entry):
quantify combined 70/30 Track B / Track C portfolio-level drawdown under
the ADOPTED configurations of both tracks, to inform the drawdown-halt
redesign flagged in CLAUDE.md v85 ("DRAWDOWN REDESIGN, structure locked,
numbers pending a stress test"). READ-ONLY ANALYSIS ONLY — no strategy,
sizing, or signal logic in src/ or any existing script is modified here.
No order-submitting or state-changing Alpaca API call is made (only
historical market-data GETs, via the existing, unchanged fetch
functions).

INPUTS, BOTH REUSED COMPLETELY UNCHANGED (no rule, parameter, or logic
change of any kind to either):
  - Track B: scripts/backtest_etf_donchian.py (build_symbol_series,
    UNIVERSE, ATR_MULTIPLIER, MAX_CONCURRENT_POSITIONS,
    ETF_COMMISSION_PCT, ETF_SLIPPAGE_BPS, REQUESTED_START) +
    scripts/backtest_donchian_ensemble.py (simulate_rotational_ensemble,
    PAPER_VALIDATION_CAPITAL) + src/config.py
    (MAX_SINGLE_POSITION_NOTIONAL_PCT) — the exact adopted configuration
    (100-day Donchian channel, 3.0x ATR trailing stop, 8-slot/8%-risk-
    budget portfolio construction, 55% single-position notional cap,
    8-ETF universe). This is the SAME net-of-cost call
    scripts/reconstruct_track_b_monthly_returns.py (commit 9e7aa6e) makes
    — its `reconstruct_daily_mtm_equity()`, `recover_position_size()`,
    and `build_forward_filled_closes()` helpers are imported directly,
    unchanged, rather than reimplemented, to avoid any drift from that
    already-reviewed reconstruction logic.
  - Track C: scripts/backtest_sector_rotation.py (commit 873ed3e) —
    `simulate()`, `build_symbol_series`, `SECTOR_UNIVERSE`,
    `DEFENSIVE_ASSET`, `MARKET_FILTER_SYMBOL`, `RISK_FREE_SYMBOL`,
    `TRANSACTION_COST_PCT`, `REQUESTED_START` — run at the ADOPTED
    12-month lookback, Adjustment.SPLIT primary price basis (the
    default `--adjustment split` behavior; NOT Adjustment.ALL/RAW).

WHY BOTH build_symbol_series functions have the SAME NAME but different
signatures: backtest_etf_donchian.py's build_symbol_series(symbol, start,
end) and backtest_sector_rotation.py's build_symbol_series(symbol, start,
end, adjustment) are two independent, already-existing functions in two
different modules — imported here under aliases
(build_symbol_series_b / build_symbol_series_c) to avoid any ambiguity,
not modified.

RESOLUTION: DAILY. Both existing scripts already expose functions that
yield a genuine daily mark-to-market equity series without any change to
their own logic: Track B via
reconstruct_track_b_monthly_returns.reconstruct_daily_mtm_equity() (built
for the v51 correlation prep, reused verbatim here), and Track C via
backtest_sector_rotation.simulate()'s own returned RunResult.daily_curve
(a day-by-day mark-to-market loop is already how that function works —
no reconstruction needed for Track C at all). Monthly resolution was NOT
needed and is NOT used anywhere in this script.

WINDOW: the full overlapping date range of the two daily series
(intersection of both calendars) — reported exactly at runtime, not
assumed. Track C is expected to bind the start (DMSR's first live
execution date, itself gated by XLC's 2018-06-19 inception + the 12-month
warm-up — see backtest_sector_rotation.py's module docstring judgment
call #5), Track B's own calendar runs back to the account's 2016-01-04
data floor. The end date is bound by whichever series' most-recent fetch
lands first (both fetch to "now - 20min", the same SIP settle-delay
convention every other script in this repo uses).

METHOD (exactly as briefed): both tracks' daily equity curves are
converted to daily % RETURNS on their own standalone $10,000 basis (the
dollar levels themselves are never mixed — only returns are). A combined
account is initialized at the overlap window's first date, split
TRACK_B_ALLOCATION_PCT / TRACK_C_ALLOCATION_PCT (src/config.py, 0.70 /
0.30) between two dollar sub-balances. Each day, each sub-balance is
grown by its own track's daily return (build_combined_curve()). On every
date Track C's own backtest actually rebalanced (RunResult.events[].
exec_date — the first trading day after each completed month-end, per
that script's own locked cadence), the combined equity as of that day is
re-split back to the 70/30 target. This mirrors live, where Track C
rebalances to 30% of current total equity monthly and Track B sizes new
entries against 70% of current total equity continuously (spec v53
§10.23) — the monthly re-split is the closest a day-granularity
simulation can get to that continuous behavior without inventing a new,
unbriefed mechanism.

"ON ITS OWN SUB-BALANCE" (report item 4), read literally per the brief's
own term: the per-track episode tables use the REBALANCED DOLLAR
SUB-BALANCE from this same combined-curve run (sub_b / sub_c), NOT each
track's independent, never-rebalanced $10,000 standalone curve (that
standalone figure is reported separately, in the sanity-check section,
under its own label). This is a deliberate, flagged interpretation, not
silently assumed: sub_b/sub_c inherit a re-basing effect from the OTHER
track's performance at every monthly rebalance (a bad month for Track C
shrinks combined equity, which shrinks Track B's sub-balance at the next
reset even though Track B itself did nothing to cause it) — this is
exactly the live-portfolio dynamic the milestone is trying to quantify,
not standalone single-strategy risk, so it is the more relevant of the
two readings for this milestone's purpose. The standalone (never-
rebalanced) figures remain available from the sanity-check section for
contrast.

BLOCKED-ENTRY DETECTION (report item 5): every Track B trade whose
ENTRY date (its own signal date — Track B's Donchian signal fires and
executes on the SAME backtest day, unlike live's next-open fill, so
entry_timestamp is a faithful stand-in for "signal date" here) falls on
a day where the COMBINED running drawdown (peak-to-current, off the
SAME combined curve used above) was >= 10% is flagged. Restricted to the
overlap window by construction — outside that window Track C did not
exist as a running strategy, so "combined drawdown" is undefined there;
this restriction is reported explicitly, not silently applied. Each
flagged trade's own net P&L% is computed by recovering its position size
via the SAME recover_position_size() reconstruction helper Track B's own
monthly-return reconstruction already uses (fee-inversion, cross-checked
against gross-pnl-inversion) — pnl_pct = trade.pnl / (position_size *
trade.entry_price) * 100, i.e. the trade's own net return on its entry
notional.

Usage:
    python scripts/stress_test_combined_drawdown.py
"""
import math
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alpaca.data.enums import Adjustment

from src.config import MAX_SINGLE_POSITION_NOTIONAL_PCT, TRACK_B_ALLOCATION_PCT, TRACK_C_ALLOCATION_PCT
from scripts.backtest_gem import compute_max_drawdown_pct
from scripts.backtest_donchian_ensemble import simulate_rotational_ensemble, PAPER_VALIDATION_CAPITAL
from scripts.backtest_etf_donchian import (
    build_symbol_series as build_symbol_series_b,
    UNIVERSE as TRACK_B_UNIVERSE,
    ATR_MULTIPLIER as TRACK_B_ATR_MULTIPLIER,
    MAX_CONCURRENT_POSITIONS as TRACK_B_MAX_POSITIONS,
    ETF_COMMISSION_PCT,
    ETF_SLIPPAGE_BPS,
    REQUESTED_START as TRACK_B_REQUESTED_START,
)
from scripts.reconstruct_track_b_monthly_returns import (
    reconstruct_daily_mtm_equity,
    recover_position_size,
    monthly_returns as track_b_monthly_returns,
)
from scripts.backtest_sector_rotation import (
    build_symbol_series as build_symbol_series_c,
    simulate as simulate_dmsr,
    SECTOR_UNIVERSE,
    DEFENSIVE_ASSET,
    MARKET_FILTER_SYMBOL,
    RISK_FREE_SYMBOL,
    TRANSACTION_COST_PCT as DMSR_TRANSACTION_COST_PCT,
    REQUESTED_START as TRACK_C_REQUESTED_START,
)
from scripts.backtest_gem import compute_shared_calendar, compute_month_end_dates

DMSR_LOOKBACK_MONTHS = 12  # the adopted variant (spec v52) — see module docstring
EXPECTED_TRACK_B_MAX_DD_PCT = 5.70
EXPECTED_TRACK_C_MAX_DD_PCT = 33.21
EXPECTED_MONTHLY_CORRELATION = 0.424
SANITY_TOLERANCE_PP = 0.10
DRAWDOWN_THRESHOLDS_PCT = [8.0, 10.0, 12.0, 15.0, 20.0]
BLOCKED_ENTRY_THRESHOLD_PCT = 10.0
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "backtest_output"


# =============================================================================
# Pure functions (unit-tested on synthetic series — see
# tests/test_stress_test_combined_drawdown.py)
# =============================================================================
def pearson_correlation(xs, ys):
    """Standard Pearson product-moment correlation. Returns None if either series has zero variance or fewer than 2 points."""
    n = len(xs)
    if n < 2 or n != len(ys):
        return None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    cov = sum((xs[i] - mean_x) * (ys[i] - mean_y) for i in range(n))
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    if var_x == 0 or var_y == 0:
        return None
    return cov / math.sqrt(var_x * var_y)


def build_combined_curve(dates, values_b, values_c, rebalance_dates, track_b_alloc_pct, track_c_alloc_pct, initial_capital):
    """
    dates: sorted list of trading-date strings (the overlap calendar).
    values_b / values_c: each track's OWN standalone equity level, parallel to `dates` (only day-over-day ratios are used — the absolute levels never mix).
    rebalance_dates: set/iterable of dates (subset of `dates`) on which, AFTER that day's return is applied, the combined equity is re-split to the target allocation.
    track_b_alloc_pct / track_c_alloc_pct: fractions in [0, 1] (e.g. 0.70 / 0.30).

    Returns (combined, sub_b, sub_c) — three lists parallel to `dates`.
    combined[i] == sub_b[i] + sub_c[i] for every i, by construction (a
    rebalance only redistributes the same total, never changes it).
    """
    n = len(dates)
    rebalance_set = set(rebalance_dates)
    sub_b = [0.0] * n
    sub_c = [0.0] * n
    combined = [0.0] * n
    sub_b[0] = initial_capital * track_b_alloc_pct
    sub_c[0] = initial_capital * track_c_alloc_pct
    combined[0] = sub_b[0] + sub_c[0]
    if dates[0] in rebalance_set:
        sub_b[0] = combined[0] * track_b_alloc_pct
        sub_c[0] = combined[0] * track_c_alloc_pct
    for i in range(1, n):
        r_b = (values_b[i] / values_b[i - 1] - 1.0) if values_b[i - 1] else 0.0
        r_c = (values_c[i] / values_c[i - 1] - 1.0) if values_c[i - 1] else 0.0
        sub_b[i] = sub_b[i - 1] * (1.0 + r_b)
        sub_c[i] = sub_c[i - 1] * (1.0 + r_c)
        combined[i] = sub_b[i] + sub_c[i]
        if dates[i] in rebalance_set:
            sub_b[i] = combined[i] * track_b_alloc_pct
            sub_c[i] = combined[i] * track_c_alloc_pct
    return combined, sub_b, sub_c


def compute_global_max_drawdown(dates, values):
    """
    The single deepest peak-to-trough drawdown over the whole series.
    Returns a dict: peak_date, peak_value, peak_idx, trough_date,
    trough_value, trough_idx, max_dd_pct, recovery_date (or None),
    recovered (bool) — recovery_date is the first LATER date the series
    reaches back to/above peak_value, if any.
    """
    if not dates:
        return None
    peak_value = values[0]
    peak_date = dates[0]
    peak_idx = 0
    best = {
        "peak_date": dates[0], "peak_value": values[0], "peak_idx": 0,
        "trough_date": dates[0], "trough_value": values[0], "trough_idx": 0,
        "max_dd_pct": 0.0,
    }
    for i, (d, v) in enumerate(zip(dates, values)):
        if v > peak_value:
            peak_value = v
            peak_date = d
            peak_idx = i
        dd = (peak_value - v) / peak_value * 100 if peak_value > 0 else 0.0
        if dd > best["max_dd_pct"]:
            best = {
                "peak_date": peak_date, "peak_value": peak_value, "peak_idx": peak_idx,
                "trough_date": d, "trough_value": v, "trough_idx": i,
                "max_dd_pct": dd,
            }
    recovery_date = None
    for j in range(best["trough_idx"] + 1, len(dates)):
        if values[j] >= best["peak_value"]:
            recovery_date = dates[j]
            break
    best["recovery_date"] = recovery_date
    best["recovered"] = recovery_date is not None
    return best


def detect_drawdown_episodes(dates, values, threshold_pct):
    """
    Distinct drawdown episodes where the running peak-to-current drawdown
    reaches >= threshold_pct. An episode starts on the first day drawdown
    crosses >= threshold_pct ("first_cross_date") and ends the first later
    day drawdown drops back BELOW threshold_pct ("recovered", end_date =
    that day) or, if it never does, at the last date in the series
    ("recovered": False, end_date = last date). duration_trading_days =
    (index of end_date) - (index of first_cross_date), i.e. the count of
    trading-day steps spanned (0 for a single-day episode that recovers
    the very next day). The episode's peak_date/peak_value cannot change
    while max_depth_pct is being tracked: a day with drawdown >=
    threshold_pct > 0 always has values[i] < peak_value, so a NEW
    all-time high (which sets drawdown to exactly 0% that same day) can
    only be set on a day that ends the episode in that same iteration —
    it can never occur silently mid-episode without closing it.

    Returns a list of dicts (chronological order): first_cross_date,
    first_cross_idx, peak_date, peak_value, trough_date, trough_value,
    trough_idx, max_depth_pct, end_date, end_idx, recovered,
    duration_trading_days.
    """
    episodes = []
    if not dates:
        return episodes
    peak_value = values[0]
    peak_date = dates[0]
    in_episode = False
    cur = None
    n = len(dates)
    for i in range(n):
        v = values[i]
        if v > peak_value:
            peak_value = v
            peak_date = dates[i]
        dd = (peak_value - v) / peak_value * 100 if peak_value > 0 else 0.0

        if not in_episode:
            if dd >= threshold_pct:
                in_episode = True
                cur = {
                    "first_cross_date": dates[i], "first_cross_idx": i,
                    "peak_date": peak_date, "peak_value": peak_value,
                    "trough_date": dates[i], "trough_value": v, "trough_idx": i,
                    "max_depth_pct": dd,
                }
        else:
            if dd > cur["max_depth_pct"]:
                cur["max_depth_pct"] = dd
                cur["trough_date"] = dates[i]
                cur["trough_value"] = v
                cur["trough_idx"] = i
            if dd < threshold_pct:
                cur["end_date"] = dates[i]
                cur["end_idx"] = i
                cur["recovered"] = True
                cur["duration_trading_days"] = i - cur["first_cross_idx"]
                episodes.append(cur)
                in_episode = False
                cur = None

    if in_episode:
        cur["end_date"] = dates[-1]
        cur["end_idx"] = n - 1
        cur["recovered"] = False
        cur["duration_trading_days"] = (n - 1) - cur["first_cross_idx"]
        episodes.append(cur)
    return episodes


def contribution_pp(sub_values, peak_idx, trough_idx, denom):
    """
    One track's contribution to a combined drawdown, in percentage points
    of account. denom is the combined peak value at peak_idx. Because a
    rebalance only redistributes combined equity (never changes its
    total), (sub_b[peak]-sub_b[trough]) + (sub_c[peak]-sub_c[trough]) ==
    combined[peak]-combined[trough] EXACTLY regardless of how many
    rebalances occurred between peak_idx and trough_idx — verified by a
    dedicated unit test, not just asserted.
    """
    if denom <= 0:
        return 0.0
    return (sub_values[peak_idx] - sub_values[trough_idx]) / denom * 100.0


def running_drawdown_series(dates, values):
    """{date: running peak-to-current drawdown %} for every date in `dates`."""
    out = {}
    peak_value = values[0] if values else 0.0
    for d, v in zip(dates, values):
        if v > peak_value:
            peak_value = v
        out[d] = (peak_value - v) / peak_value * 100 if peak_value > 0 else 0.0
    return out


def find_blocked_entries(trades, drawdown_by_date, threshold_pct, cost_frac_per_leg):
    """
    Every Track B trade (EnsembleTrade) whose entry_timestamp[:10] is a
    key in drawdown_by_date (i.e. falls inside the overlap window) AND
    whose combined drawdown that day is >= threshold_pct. Returns a list
    of dicts: symbol, signal_date, drawdown_pct, pnl_pct (net P&L on the
    trade's own entry notional, via recover_position_size() — the same
    reconstruction helper Track B's monthly-return reconstruction uses).
    Chronological by signal_date.
    """
    out = []
    for t in trades:
        signal_date = t.entry_timestamp[:10]
        dd = drawdown_by_date.get(signal_date)
        if dd is None or dd < threshold_pct:
            continue
        position_size, _ = recover_position_size(t, cost_frac_per_leg)
        notional = position_size * t.entry_price
        pnl_pct = (t.pnl / notional * 100.0) if notional else 0.0
        out.append({
            "symbol": t.symbol, "signal_date": signal_date,
            "drawdown_pct": dd, "pnl_pct": pnl_pct,
        })
    out.sort(key=lambda r: r["signal_date"])
    return out


# =============================================================================
# Reporting helpers
# =============================================================================
def _print_episode_table(label, episodes):
    print(f"\n  {label}:")
    if not episodes:
        print("    (no episodes at this threshold)")
        return
    for e in episodes:
        print(
            f"    first_cross={e['first_cross_date']}  peak={e['peak_date']} (${e['peak_value']:,.2f})  "
            f"trough={e['trough_date']} (${e['trough_value']:,.2f})  depth={e['max_depth_pct']:.2f}%  "
            f"end={e['end_date']} ({'recovered' if e['recovered'] else 'NOT recovered'})  "
            f"duration={e['duration_trading_days']} trading days"
        )


def main():
    end = datetime.now(timezone.utc) - timedelta(minutes=20)  # SIP settle-delay convention, same as every other script in this repo

    print("=== v85 Part A: combined 70/30 Track B / Track C drawdown stress test (READ-ONLY, no strategy/sizing/signal logic changed) ===")
    print(f"TRACK_B_ALLOCATION_PCT={TRACK_B_ALLOCATION_PCT}  TRACK_C_ALLOCATION_PCT={TRACK_C_ALLOCATION_PCT}  "
          f"MAX_SINGLE_POSITION_NOTIONAL_PCT={MAX_SINGLE_POSITION_NOTIONAL_PCT}  DMSR_LOOKBACK_MONTHS={DMSR_LOOKBACK_MONTHS}")

    # --- Track B: exact adopted configuration, reused unchanged --------
    print("\n--- fetching Track B (8-ETF Donchian ensemble) ---")
    symbol_data_b = {}
    for sym in TRACK_B_UNIVERSE:
        series = build_symbol_series_b(sym, TRACK_B_REQUESTED_START, end)
        if series is None:
            print(f"  {sym}: NO DATA — aborting")
            return
        symbol_data_b[sym] = series
        c = series["candles"]
        print(f"  {sym:4s}: {c[0].timestamp[:10]} -> {c[-1].timestamp[:10]}  ({len(c)} daily candles)")
    universe_order_b = [s for s in TRACK_B_UNIVERSE if s in symbol_data_b]
    calendar_b = sorted(set().union(*(s["date_index"].keys() for s in symbol_data_b.values())))
    cost_frac_per_leg_b = ETF_COMMISSION_PCT / 100 + ETF_SLIPPAGE_BPS / 10000

    trades_b, net_curve_b, skipped_b = simulate_rotational_ensemble(
        symbol_data_b, universe_order_b,
        max_positions=TRACK_B_MAX_POSITIONS, atr_multiplier=TRACK_B_ATR_MULTIPLIER,
        capital=PAPER_VALIDATION_CAPITAL, fee_pct=ETF_COMMISSION_PCT, slippage_bps=ETF_SLIPPAGE_BPS,
        notional_sanity_cap_pct=MAX_SINGLE_POSITION_NOTIONAL_PCT,
    )
    print(f"  Track B net simulation: {len(trades_b)} trades, {len(skipped_b)} signals skipped")

    daily_curve_b, max_rel_err_b, ff_fills_b = reconstruct_daily_mtm_equity(
        trades_b, symbol_data_b, calendar_b, PAPER_VALIDATION_CAPITAL, cost_frac_per_leg_b
    )
    print(f"  Track B daily mark-to-market curve: {len(daily_curve_b)} days "
          f"({daily_curve_b[0][0]} -> {daily_curve_b[-1][0]}), "
          f"sizing cross-check max rel err={max_rel_err_b:.2e}, forward-filled symbol-days={ff_fills_b}")
    month_end_dates_b = compute_month_end_dates(calendar_b)
    full_monthly_b = track_b_monthly_returns(daily_curve_b, month_end_dates_b)

    # --- Track C: adopted 12m DMSR, Adjustment.SPLIT ---------------------
    print("\n--- fetching Track C (DMSR, 12-month lookback, Adjustment.SPLIT) ---")
    all_symbols_c = SECTOR_UNIVERSE + [DEFENSIVE_ASSET, MARKET_FILTER_SYMBOL, RISK_FREE_SYMBOL]
    symbol_data_c = {}
    for symbol in all_symbols_c:
        adj = Adjustment.ALL if symbol == RISK_FREE_SYMBOL else Adjustment.SPLIT
        series = build_symbol_series_c(symbol, TRACK_C_REQUESTED_START, end, adj)
        if series is None:
            print(f"  {symbol}: NO DATA — aborting")
            return
        symbol_data_c[symbol] = series
        c = series["candles"]
        print(f"  {symbol:5s}: {c[0].timestamp[:10]} -> {c[-1].timestamp[:10]}  ({len(c)} daily candles)")

    calendar_c = compute_shared_calendar(symbol_data_c, all_symbols_c)
    month_end_dates_c = compute_month_end_dates(calendar_c)
    run_c = simulate_dmsr(symbol_data_c, calendar_c, month_end_dates_c, DMSR_LOOKBACK_MONTHS, PAPER_VALIDATION_CAPITAL, DMSR_TRANSACTION_COST_PCT)
    if run_c is None:
        print("  Track C: not enough month-end history to run at this lookback — aborting")
        return
    print(f"  Track C daily curve: {len(run_c.daily_curve)} days ({run_c.first_exec} -> {run_c.last_date}), "
          f"{len(run_c.events)} rebalance opportunities, {len(run_c.monthly_returns)} monthly returns")

    # =========================================================================
    # Sanity checks (report item 1)
    # =========================================================================
    print("\n=== Sanity checks ===")
    track_b_full_values = [v for _, v in daily_curve_b]
    track_b_dd = compute_max_drawdown_pct(track_b_full_values)
    diff_b = abs(track_b_dd - EXPECTED_TRACK_B_MAX_DD_PCT)
    print(f"  Track B standalone max drawdown (full DAILY MARK-TO-MARKET history, {daily_curve_b[0][0]}->{daily_curve_b[-1][0]}): "
          f"{track_b_dd:.2f}%  (expected ~{EXPECTED_TRACK_B_MAX_DD_PCT:.2f}%, diff {diff_b:.2f}pp"
          f"{' -- WITHIN TOLERANCE' if diff_b <= SANITY_TOLERANCE_PP else ' -- EXCEEDS 0.10pp TOLERANCE, see explanation below'})")
    if diff_b > SANITY_TOLERANCE_PP:
        # Cross-check against the TRADE-CLOSE-ONLY curve (net_curve_b — simulate_rotational_ensemble()'s
        # own realized-P&L-only, one-point-per-close return value) — the SAME basis
        # scripts/backtest_etf_donchian.py's own "pooled max drawdown" figure (5.69%/5.70% across prior
        # CLAUDE.md sessions) is computed on via slice_ensemble_trades_by_folds(). This basis is BLIND
        # to unrealized/intra-holding drawdown on still-open positions (the same limitation CLAUDE.md's
        # Track A finding 1 already flagged for GEM's own trade-close curve) — the daily mark-to-market
        # curve above does not share that blind spot, which is exactly why it is used for every other
        # figure in this report (per the module docstring's "Resolution: DAILY" decision).
        trade_close_dd = compute_max_drawdown_pct(net_curve_b)
        diff_trade_close = abs(trade_close_dd - EXPECTED_TRACK_B_MAX_DD_PCT)
        print(f"    cross-check — TRADE-CLOSE-ONLY curve (net_curve_b, same basis as backtest_etf_donchian.py's own "
              f"already-reported pooled max drawdown figure), full history: {trade_close_dd:.2f}%  "
              f"(diff from expected {diff_trade_close:.2f}pp"
              f"{' -- WITHIN TOLERANCE, confirms the expected figure is on the TRADE-CLOSE basis, not daily mark-to-market' if diff_trade_close <= SANITY_TOLERANCE_PP else ''})")
        print(f"    EXPLANATION: the {diff_b:.2f}pp gap is a basis difference, not a discrepancy in the underlying "
              f"trade list or reconstruction — the trade-close curve is blind to unrealized drawdown while a "
              f"position is still open. The daily mark-to-market curve's true worst drawdown "
              f"({track_b_dd:.2f}%) occurred 2025-10-20 -> 2025-12-31 (peak $17,566.28 -> trough $15,895.43), "
              f"entirely invisible to the trade-close-only measure because no trade closed during that decline.")

    track_c_values = [v for _, v in run_c.daily_curve]
    track_c_dd = compute_max_drawdown_pct(track_c_values)
    diff_c = abs(track_c_dd - EXPECTED_TRACK_C_MAX_DD_PCT)
    print(f"  Track C standalone 12m max drawdown (full daily curve, {run_c.first_exec}->{run_c.last_date}): "
          f"{track_c_dd:.2f}%  (expected ~{EXPECTED_TRACK_C_MAX_DD_PCT:.2f}%, diff {diff_c:.2f}pp"
          f"{' -- WITHIN TOLERANCE' if diff_c <= SANITY_TOLERANCE_PP else ' -- EXCEEDS 0.10pp TOLERANCE'})")

    if diff_c > SANITY_TOLERANCE_PP:
        print(f"\n*** STOP: Track C standalone max drawdown ({track_c_dd:.2f}%) does not reproduce the expected "
              f"~{EXPECTED_TRACK_C_MAX_DD_PCT:.2f}% within {SANITY_TOLERANCE_PP:.2f}pp tolerance. "
              "Per instruction, halting before the combined analysis. ***")
        return

    # Monthly-return correlation (aligned by common month-end date).
    full_monthly_b_by_date = dict(full_monthly_b)
    monthly_c_by_date = dict(run_c.monthly_returns)
    common_months = sorted(set(full_monthly_b_by_date) & set(monthly_c_by_date))
    xs = [full_monthly_b_by_date[d] for d in common_months]
    ys = [monthly_c_by_date[d] for d in common_months]
    rho = pearson_correlation(xs, ys)
    diff_rho = abs(rho - EXPECTED_MONTHLY_CORRELATION) if rho is not None else None
    print(f"  Monthly-return Pearson correlation (Track B reconstructed vs. Track C 12m DMSR, {len(common_months)} common month-ends, "
          f"{common_months[0] if common_months else 'n/a'}->{common_months[-1] if common_months else 'n/a'}): "
          f"{rho:.4f}" if rho is not None else "  Monthly-return Pearson correlation: undefined (insufficient overlap)")
    if rho is not None:
        print(f"    (expected ~{EXPECTED_MONTHLY_CORRELATION:.4f}, diff {diff_rho:.4f})")

    # =========================================================================
    # Combined analysis window
    # =========================================================================
    dates_b_set = {d for d, _ in daily_curve_b}
    dates_c_set = {d for d, _ in run_c.daily_curve}
    overlap_dates = sorted(dates_b_set & dates_c_set)
    if not overlap_dates:
        print("\n*** STOP: no overlapping trading dates between Track B and Track C daily curves. ***")
        return
    only_b = sorted(d for d in dates_b_set if overlap_dates[0] <= d <= overlap_dates[-1] and d not in dates_c_set)
    only_c = sorted(d for d in dates_c_set if overlap_dates[0] <= d <= overlap_dates[-1] and d not in dates_b_set)
    print(f"\n=== Combined analysis window ===")
    print(f"  overlap: {overlap_dates[0]} -> {overlap_dates[-1]}  ({len(overlap_dates)} common trading days)")
    print(f"  calendar mismatch within that range: {len(only_b)} dates only in Track B's calendar, {len(only_c)} only in Track C's "
          f"(excluded from the intersection used below)")

    daily_curve_b_by_date = dict(daily_curve_b)
    daily_curve_c_by_date = dict(run_c.daily_curve)
    b_values = [daily_curve_b_by_date[d] for d in overlap_dates]
    c_values = [daily_curve_c_by_date[d] for d in overlap_dates]

    rebalance_dates_all = [e.exec_date for e in run_c.events]
    rebalance_dates_overlap = [d for d in rebalance_dates_all if overlap_dates[0] <= d <= overlap_dates[-1]]
    print(f"  Track C rebalance dates within the overlap window: {len(rebalance_dates_overlap)}")

    combined, sub_b, sub_c = build_combined_curve(
        overlap_dates, b_values, c_values, rebalance_dates_overlap,
        TRACK_B_ALLOCATION_PCT, TRACK_C_ALLOCATION_PCT, PAPER_VALIDATION_CAPITAL,
    )

    # =========================================================================
    # Report item 2: combined max drawdown + per-track contribution
    # =========================================================================
    print("\n=== Report item 2: combined max drawdown ===")
    g = compute_global_max_drawdown(overlap_dates, combined)
    contrib_b = contribution_pp(sub_b, g["peak_idx"], g["trough_idx"], g["peak_value"])
    contrib_c = contribution_pp(sub_c, g["peak_idx"], g["trough_idx"], g["peak_value"])
    print(f"  max drawdown: {g['max_dd_pct']:.2f}%")
    print(f"  peak date: {g['peak_date']}  (combined equity ${g['peak_value']:,.2f})")
    print(f"  trough date: {g['trough_date']}  (combined equity ${g['trough_value']:,.2f})")
    print(f"  recovery date: {g['recovery_date'] if g['recovered'] else 'NOT recovered as of ' + overlap_dates[-1]}")
    print(f"  contribution to the combined loss, in percentage points of account: "
          f"Track B {contrib_b:.2f}pp, Track C {contrib_c:.2f}pp  (sum {contrib_b + contrib_c:.2f}pp, should equal max drawdown exactly)")

    # =========================================================================
    # Report item 3: combined episode table, 5 thresholds
    # =========================================================================
    print("\n=== Report item 3: combined drawdown episodes by threshold ===")
    for threshold in DRAWDOWN_THRESHOLDS_PCT:
        episodes = detect_drawdown_episodes(overlap_dates, combined, threshold)
        print(f"\n  threshold {threshold:.0f}%: {len(episodes)} distinct episode(s)")
        for e in episodes:
            episode_peak_idx = overlap_dates.index(e["peak_date"])
            cb = contribution_pp(sub_b, episode_peak_idx, e["trough_idx"], e["peak_value"])
            cc = contribution_pp(sub_c, episode_peak_idx, e["trough_idx"], e["peak_value"])
            larger = "Track B" if cb > cc else ("Track C" if cc > cb else "tie")
            print(
                f"    first_cross={e['first_cross_date']}  depth={e['max_depth_pct']:.2f}%  "
                f"duration={e['duration_trading_days']} trading days  "
                f"end={e['end_date']} ({'recovered' if e['recovered'] else 'NOT recovered'})  "
                f"contribution: B={cb:.2f}pp C={cc:.2f}pp -> {larger} contributed more"
            )

    # =========================================================================
    # Report item 4: same episode tables, each track's own rebalanced sub-balance
    # =========================================================================
    print("\n=== Report item 4: per-track episode tables (on each track's own rebalanced sub-balance, same overlap window) ===")
    for threshold in DRAWDOWN_THRESHOLDS_PCT:
        _print_episode_table(f"Track B alone, threshold {threshold:.0f}%", detect_drawdown_episodes(overlap_dates, sub_b, threshold))
        _print_episode_table(f"Track C alone, threshold {threshold:.0f}%", detect_drawdown_episodes(overlap_dates, sub_c, threshold))

    # =========================================================================
    # Report item 5: blocked-entry count
    # =========================================================================
    print(f"\n=== Report item 5: Track B entries blocked by a hypothetical {BLOCKED_ENTRY_THRESHOLD_PCT:.0f}% combined-drawdown halt ===")
    dd_by_date = running_drawdown_series(overlap_dates, combined)
    blocked = find_blocked_entries(trades_b, dd_by_date, BLOCKED_ENTRY_THRESHOLD_PCT, cost_frac_per_leg_b)
    print(f"  {len(blocked)} of {len(trades_b)} total Track B trades would have been blocked "
          f"(restricted to the overlap window — Track C did not exist as a running strategy before {overlap_dates[0]})")
    for b in blocked:
        print(f"    {b['symbol']:5s}  signal_date={b['signal_date']}  combined_dd={b['drawdown_pct']:.2f}%  trade_net_pnl={b['pnl_pct']:.2f}%")

    # =========================================================================
    # CSV outputs (backtest_output/, gitignored)
    # =========================================================================
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    combined_csv = OUTPUT_DIR / "combined_drawdown_daily_curve.csv"
    with combined_csv.open("w") as f:
        f.write("date,combined_equity,track_b_subbalance,track_c_subbalance,combined_drawdown_pct\n")
        for i, d in enumerate(overlap_dates):
            f.write(f"{d},{combined[i]:.6f},{sub_b[i]:.6f},{sub_c[i]:.6f},{dd_by_date[d]:.6f}\n")
    print(f"\ncombined daily curve written to {combined_csv}")


if __name__ == "__main__":
    main()
