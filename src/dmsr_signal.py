"""
Pure DMSR (Dual Momentum Sector Rotation) signal computation for Track C
(spec v59 §10.29, Milestone 4).

Re-implemented from scripts/backtest_sector_rotation.py — the backtest
that earned Track C its ADOPT verdict (spec v52 §10.22) — with the same
exact rules, hardcoded to the one adopted lookback (12 months) rather
than the backtest's 10/11/12/13-month robustness sweep. src/ must not
import scripts/ for its live path, so the shared helpers
(compute_month_end_dates, trailing_return, rank_sectors,
select_target_holdings) are COPIED here, not imported. A regression test
(tests/test_dmsr_signal.py) pins compute_month_end_dates() byte-for-byte
against scripts/backtest_gem.py's so the copy can't silently drift.

NO I/O in this module. Callers (src/track_c_execution.py) supply
already-fetched price series as {"symbol", "candles", "date_index"}
dicts (same shape as the backtests use).

=====================================================================
LOCKED STRATEGY RULES (spec v59 §10.29 brief — no substitutions)
=====================================================================
- Universe: 11 SPDR Select Sector ETFs (SECTOR_UNIVERSE).
- Defensive / risk-off asset: AGG, held 100% when the market filter is off.
- Market filter symbol: SPY.
- Ranking signal: trailing 12-month price return (month-end close vs. the
  close 12 month-ends earlier). Split-adjusted, NOT dividend-adjusted
  (Adjustment.SPLIT) — matches the backtest's validated basis; the caller
  is responsible for fetching the series that way.
- Market absolute-momentum filter: if SPY's own trailing 12-month return
  is negative -> 100% AGG, sector rankings ignored entirely.
- Risk-on holdings: top 3 of the 11 ranked sectors, equal-weighted.
- Hysteresis / whipsaw guard: a currently-held sector is sold ONLY if its
  rank falls out of the top 5 (not merely out of the top 3) — a genuine
  2-rank buffer.
- Rebalance frequency: monthly, on the first trading day after each
  month-end close.
- NO trim trades for names that stay held — weights drift between
  rebalances.
- NO stop-loss / intra-month risk exit of any kind. The monthly
  absolute-momentum filter IS Track C's entire risk control, by design.

=====================================================================
DEVIATION FROM THE BRIEF'S PASTED HELPER CODE — FLAGGED, NOT SILENT
(per RULES.md "stop and report, don't guess")
=====================================================================
The Milestone 4 brief pasted a `compute_month_end_dates()` that appends
`calendar[-1]` unconditionally (NOT what scripts/backtest_gem.py does),
and an `is_rebalance_day()` that calls `compute_month_end_dates(calendar
[:-1])`. Taken literally, those two together make is_rebalance_day()
return True on EVERY call (the unconditional append always puts
`calendar[:-1][-1]` == `calendar[-2]` into the set), which defeats the
whole self-gate. With a truly-verbatim gem port (no append) plus the
`[:-1]` slice, is_rebalance_day() would instead return False on every
call (the loop never evaluates its own last element, so `calendar[-2]`
is never flagged). Neither is usable.

The brief's INTENT is unambiguous and stated consistently three ways:
the is_rebalance_day docstring ("iff calendar[-2] ... is a month-end
date"), the required test ("true when calendar[-2] is a month-end;
false otherwise"), and step 4 ("t = index of the most recent
month-end"). Implemented to that intent:
  - compute_month_end_dates() is a TRULY verbatim copy of
    scripts/backtest_gem.py's (no appended last element).
  - is_rebalance_day() calls it on the FULL `calendar` (not
    `calendar[:-1]`), so `calendar[-2] in month_ends` is exactly "was
    yesterday the last trading day of its calendar month" — because
    compute_month_end_dates()'s loop flags `calendar[i]` iff
    `calendar[i][:7] != calendar[i+1][:7]`, and for i == len-2 that is
    precisely the month-boundary test between yesterday and today.
Recommend a chat-interface confirmation of this resolution.
"""

SECTOR_UNIVERSE = ["XLK", "XLV", "XLE", "XLF", "XLY", "XLP", "XLU", "XLI", "XLB", "XLRE", "XLC"]
DEFENSIVE_ASSET = "AGG"
MARKET_FILTER_SYMBOL = "SPY"
TOP_N_HOLD = 3
HYSTERESIS_RANK = 5
LOOKBACK_MONTHS = 12


def compute_month_end_dates(calendar):
    """
    Dates (strings) that are the last trading day of a FULLY COMPLETED
    calendar month within `calendar` (a sorted list of "YYYY-MM-DD"
    strings). A date counts only once a LATER date in a different
    calendar month exists in the data — this naturally excludes the
    current in-progress month.

    VERBATIM copy of scripts/backtest_gem.py's compute_month_end_dates()
    (see this module's docstring for why it is copied, not imported, and
    for the flagged deviation from the Milestone 4 brief's pasted
    version — the brief's extra unconditional `append(calendar[-1])` is
    deliberately NOT reproduced here).
    """
    return [calendar[i] for i in range(len(calendar) - 1) if calendar[i][:7] != calendar[i + 1][:7]]


def is_rebalance_day(calendar) -> bool:
    """
    True iff TODAY (calendar[-1], the most recent trading day, assumed to
    be the day this is called) is the first trading day after a
    month-end — i.e. iff calendar[-2] (yesterday's trading day) was the
    last trading day of its calendar month.

    Self-gating check for the live job (src/track_c_execution.py): on
    almost every day this is False and the job is a no-op, mirroring how
    Track B's own daily job is a no-op on days with no breakout signal.

    Calls compute_month_end_dates() on the FULL `calendar` — see this
    module's docstring for why NOT `calendar[:-1]` (the brief's pasted
    version, which would break the gate).
    """
    if len(calendar) < 2:
        return False
    month_ends = set(compute_month_end_dates(calendar))
    return calendar[-2] in month_ends


def trailing_return(series, month_end_dates, t, lookback=LOOKBACK_MONTHS):
    """
    Month-end-to-month-end price return over `lookback` months, as of
    evaluation point t (an index into month_end_dates). Ported verbatim
    from scripts/backtest_sector_rotation.py.
    """
    d_now = month_end_dates[t]
    d_then = month_end_dates[t - lookback]
    di = series["date_index"]
    c_now = series["candles"][di[d_now]].close
    c_then = series["candles"][di[d_then]].close
    return (c_now - c_then) / c_then


def rank_sectors(symbol_data, month_end_dates, t, lookback=LOOKBACK_MONTHS):
    """
    (symbol, trailing_return) for all 11 sectors, best-first, with a
    deterministic tie-break by ticker. Ported verbatim from
    scripts/backtest_sector_rotation.py.
    """
    rets = [(s, trailing_return(symbol_data[s], month_end_dates, t, lookback)) for s in SECTOR_UNIVERSE]
    rets.sort(key=lambda kv: (-kv[1], kv[0]))
    return rets


def select_target_holdings(current_holdings, ranked, spy_return):
    """
    Decide the target holding set for a rebalance. Ported verbatim from
    scripts/backtest_sector_rotation.py. Returns (target_holdings,
    is_risk_off).

    current_holdings : symbols currently held — either up to 3 sector
                       names, or ["AGG"] (a prior risk-off month), or []
                       (first-ever deployment).
    ranked           : rank_sectors() output (list of (symbol, ret), best first).
    spy_return       : SPY's own trailing return over the same lookback.

    Risk-off (spy_return < 0): 100% AGG, all rankings ignored.
    Risk-on: keep every currently-held sector still inside the top
    HYSTERESIS_RANK (5), then fill the remaining slots up to TOP_N_HOLD
    (3) with the highest-ranked sectors not already kept.
    """
    if spy_return < 0:
        return [DEFENSIVE_ASSET], True

    order = [s for s, _ in ranked]
    top_hysteresis = set(order[:HYSTERESIS_RANK])
    kept = [s for s in current_holdings if s in top_hysteresis][:TOP_N_HOLD]

    target = list(kept)
    for s in order:
        if len(target) >= TOP_N_HOLD:
            break
        if s not in target:
            target.append(s)
    return target, False
