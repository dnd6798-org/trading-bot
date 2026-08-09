"""
Track A (spec v24 §10.2): Dual Momentum / GEM (Gary Antonacci's classic
design) — locked as a candidate in a prior planning-chat session (spec
v22 §10.1) but never actually backtested (superseded by the three-track
pivot before its first run). First non-crypto, non-Track-B strategy in
this repo, and the first whose signal is a TOTAL-RETURN comparison rather
than a price-channel/indicator-crossover rule.

Universe (4 ETFs): SPY (US equities), EFA (developed ex-US equities), AGG
(aggregate bonds — the defensive holding), BIL (1-3mo T-bill proxy — an
absolute-momentum REFERENCE rate only, never itself held as a position).

Signal, evaluated once per fully-completed calendar month (month-end
close), fixed rule per spec v22 §10.1 — externally-evidenced parameters
(Antonacci's original design), not swept or tuned this round:
  1. Relative momentum: whichever of SPY/EFA has the higher trailing
     12-month total return is this month's "risky pick".
  2. Absolute momentum filter: if the risky pick's trailing 12-month
     total return exceeds BIL's trailing 12-month total return, hold the
     risky pick for the following month. Otherwise hold AGG instead.
  3. Full notional, single position at a time. GEM's actual specified
     design IS 100%-of-equity rotation — unlike MACD D1H1/RSI-mean-
     reversion's flat-25%-cap fallback (a workaround for lacking a
     natural risk-based sizing anchor, crypto findings 8/9), full
     notional isn't a fallback here, it's the strategy.

CORRECTNESS FIX, not a style choice (see src/data_ingestion.py's
fetch_historical_stock_candles() docstring for the empirical evidence
gathered before writing this file): momentum is computed on Alpaca's
split+dividend-ADJUSTED close series (Adjustment.ALL), not the RAW prices
Track B used. GEM's signal IS a total-return comparison — RAW prices
would badly distort or outright invalidate the absolute-momentum filter
(BIL's raw series has an uncorrected ~2x split discontinuity; AGG's raw
price-only return is negative over a window where its true
dividend-inclusive return is positive).

12-MONTH LOOKBACK = INDICATOR WARM-UP, NOT A TRAINING/TUNING PERIOD (user
instruction, this session) — GEM's parameters are fixed, externally-
evidenced values, the same epistemic status as Track B's carried-over
100d/3.0x parameters, so nothing is actually fit/selected across folds.
The first evaluation point with a full 12-month lookback (computed from
real fetched data, not hardcoded) is where the 2-fold walk-forward's
USABLE window begins — there is no separate "initial training" span the
way Track B's day-based design used one.

DATA WINDOW: the same account-level 2016-01-04 truncation Track B
discovered applies identically here — confirmed for all 4 tickers before
writing any Track A code, per explicit instruction (see the chat record;
not re-derived in code, since it's the same account/data-plan limit
already documented in fetch_historical_stock_candles()'s docstring).
~10.6yr raw window, but GEM's own 12-month warm-up consumes the first
year of it regardless, so the USABLE (tradeable) window is ~9.6yr
starting ~2017-01.

WALK-FORWARD: 2 anchored, contiguous, non-overlapping folds (not 3, per
user instruction) — GEM's monthly cadence and low turnover risk the same
sample-starvation failure mode as the crypto RSI mean-reversion finding
(finding 9) if split any finer. Folds are built by splitting the usable
monthly-evaluation-point sequence into two roughly-equal-count halves;
fold boundary DATES (not the evaluation-point split itself) are what
trades get bucketed against, by EXIT timestamp — same convention as
backtest_donchian_ensemble.py's slice_ensemble_trades_by_folds() (a
holding period that starts in fold 1 but ends in fold 2, if one occurs,
is attributed to fold 2, matching how equity is actually realized). ONE
DELIBERATE DEVIATION from that file's exact slicing code, not a
copy-paste: see slice_gem_trades_by_folds()'s docstring — the last
fold's upper boundary is forced to extend through the end of the trade
list rather than using a strict "<test_end" comparison, otherwise the
final eol trade (whose exit timestamp exactly equals the last fold's
test_end by construction) would be silently dropped from the per-fold
count while still appearing in the pooled number — invisible in Track
B's 200+-trade context, but immediately visible and misleading with
GEM's low trade count and only 2 folds.

ADOPT BAR (user instruction, this session — reported as raw numbers
below, not self-rendered as a verdict, same convention as every prior
finding): pooled net-of-cost positive AND BOTH folds individually
positive (not a relaxed >=N/2 fraction). Per-fold POSITION-CHANGE (asset
switch) counts are reported explicitly; any fold with fewer than
SWITCH_COUNT_THIN_THRESHOLD (3) switches is flagged in the printed report
as a possible sample-starvation risk, not silently treated as fully
conclusive just because it's numerically positive.

TRADE MODEL: unlike every prior finding's trade-per-signal model, GEM
holds continuously across months with no per-trade stop/target — a
"trade" here is a continuous HOLDING PERIOD in one asset, opened when GEM
selects a different asset than currently held (or the very first pick)
and closed when GEM later selects a different asset again ("switch") or
at the end of the data ("eol", mark-to-market, same convention as every
other finding). This maps onto the existing Trade-shaped dataclass/
summarize() pattern (entry/exit price, one fee event per full round
trip) even though the triggering mechanism (monthly re-evaluation, not a
stop/take-profit) differs from every earlier strategy family. `r_multiple`
is a NOMINAL scorecard only (against spec §4.1's 1%-of-equity figure),
not tied to actual sizing — GEM has no per-trade stop-distance to size
off, same documented caveat as MACD D1H1/RSI mean-reversion (findings
8/9), though unlike those, GEM's 100%-notional sizing is not itself a
fallback (see above).

Fee model: reused directly from Track B (0% commission + 5bps/leg
slippage, backtest_etf_donchian.py's ETF_COMMISSION_PCT/
ETF_SLIPPAGE_BPS) — GEM's universe (SPY/EFA/AGG/BIL) is at least as
liquid as Track B's DBC/VNQ, so this is a conservative, not aggressive,
reuse; flagged as a judgment call since Track A wasn't given its own fee
instruction, not a newly-derived number.

Circuit-breaker variants (15%/20% drawdown thresholds, spec v24 §10.2)
are NOT implemented in this file yet — their exact trigger/action/reset
mechanics haven't been confirmed this session. This file currently
implements BASE GEM only; the two variants are a follow-up once that
design is confirmed.

Usage:
    python scripts/backtest_gem.py
"""
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alpaca.data.enums import Adjustment
from src.data_ingestion import fetch_historical_stock_candles
from scripts.backtest import summarize, _print_table, DEFAULT_RISK_PER_TRADE_PCT
from scripts.backtest_donchian_ensemble import PAPER_VALIDATION_CAPITAL
from scripts.backtest_etf_donchian import ETF_COMMISSION_PCT, ETF_SLIPPAGE_BPS

UNIVERSE = ["SPY", "EFA", "AGG", "BIL"]
RISKY_PAIR = ["SPY", "EFA"]
DEFENSIVE_ASSET = "AGG"
ABSOLUTE_MOMENTUM_REFERENCE = "BIL"
MOMENTUM_LOOKBACK_MONTHS = 12

GEM_COMMISSION_PCT = ETF_COMMISSION_PCT  # reused from Track B, see module docstring
GEM_SLIPPAGE_BPS = ETF_SLIPPAGE_BPS

NUM_FOLDS = 2  # user instruction, this session — not Track B's 3
SWITCH_COUNT_THIN_THRESHOLD = 3

REQUESTED_START = datetime(2006, 2, 3, tzinfo=timezone.utc)  # requested, not honored — see module docstring, actual floor is 2016-01-04


@dataclass
class GemTrade:
    asset: str
    entry_index: int
    exit_index: int
    entry_timestamp: str
    exit_timestamp: str
    entry_price: float
    exit_price: float
    exit_reason: str  # "switch" | "eol"
    gross_pnl: float
    fees_paid: float
    pnl: float  # net of fees
    r_multiple: float  # nominal only, see module docstring


def build_symbol_series(symbol, start, end):
    """Fetches this symbol's dividend+split-adjusted daily history (Adjustment.ALL — see module docstring) and a date-string -> index map."""
    candles = fetch_historical_stock_candles(symbol, start, end, adjustment=Adjustment.ALL)
    if not candles:
        return None
    date_index = {c.timestamp[:10]: i for i, c in enumerate(candles)}
    return {"symbol": symbol, "candles": candles, "date_index": date_index}


def compute_shared_calendar(symbol_data, universe):
    """Intersection (not union) of all universe symbols' available dates — GEM needs every symbol priced on every evaluation date, unlike Track B's rotational ensemble which tolerated partial-history symbols."""
    calendars = [set(symbol_data[sym]["date_index"].keys()) for sym in universe]
    return sorted(set.intersection(*calendars))


def compute_month_end_dates(calendar):
    """
    Dates (strings) that are the last trading day of a FULLY COMPLETED
    calendar month within `calendar` (sorted date strings). A date only
    counts once a LATER date in a different calendar month exists in the
    data — this naturally excludes the current in-progress month rather
    than treating "the last date we happen to have fetched" as a valid
    month-end.
    """
    return [calendar[i] for i in range(len(calendar) - 1) if calendar[i][:7] != calendar[i + 1][:7]]


def trailing_return_pct(symbol_data, symbol, month_end_dates, t):
    """Trailing MOMENTUM_LOOKBACK_MONTHS total return (%) for `symbol` as of evaluation point t (index into month_end_dates)."""
    date_now = month_end_dates[t]
    date_then = month_end_dates[t - MOMENTUM_LOOKBACK_MONTHS]
    series = symbol_data[symbol]
    close_now = series["candles"][series["date_index"][date_now]].close
    close_then = series["candles"][series["date_index"][date_then]].close
    return (close_now - close_then) / close_then * 100


def select_gem_asset(symbol_data, month_end_dates, t):
    """GEM decision at evaluation point t: relative momentum between the risky pair, then the absolute-momentum filter against BIL. Returns the selected asset symbol."""
    risky_returns = {sym: trailing_return_pct(symbol_data, sym, month_end_dates, t) for sym in RISKY_PAIR}
    risky_winner = max(risky_returns, key=risky_returns.get)
    bil_return = trailing_return_pct(symbol_data, ABSOLUTE_MOMENTUM_REFERENCE, month_end_dates, t)
    return risky_winner if risky_returns[risky_winner] > bil_return else DEFENSIVE_ASSET


def simulate_gem(
    symbol_data,
    month_end_dates,
    capital=PAPER_VALIDATION_CAPITAL,
    fee_pct=GEM_COMMISSION_PCT,
    slippage_bps=GEM_SLIPPAGE_BPS,
):
    """
    Walk-forward simulation over the USABLE monthly evaluation range
    (month_end_dates[MOMENTUM_LOOKBACK_MONTHS:]) — see module docstring
    for the holding-period trade model. Returns (trades, equity_curve),
    trades in exit-chronological order (equity only moves when a holding
    period closes, same convention as every other backtest here).
    """
    cost_frac_per_leg = fee_pct / 100 + slippage_bps / 10000
    live_eval = list(range(MOMENTUM_LOOKBACK_MONTHS, len(month_end_dates)))

    trades = []
    equity = capital
    equity_curve = [equity]
    held_asset = None
    entry_date = None
    entry_price = None

    def _close_position(exit_date, exit_reason):
        nonlocal equity, held_asset, entry_date, entry_price
        series = symbol_data[held_asset]
        exit_idx = series["date_index"][exit_date]
        entry_idx = series["date_index"][entry_date]
        exit_price = series["candles"][exit_idx].close
        position_size = equity / entry_price
        gross_pnl = position_size * (exit_price - entry_price)
        fees_paid = position_size * (entry_price + exit_price) * cost_frac_per_leg
        pnl = gross_pnl - fees_paid
        equity += pnl
        trades.append(GemTrade(
            asset=held_asset,
            entry_index=entry_idx,
            exit_index=exit_idx,
            entry_timestamp=series["candles"][entry_idx].timestamp,
            exit_timestamp=series["candles"][exit_idx].timestamp,
            entry_price=entry_price,
            exit_price=exit_price,
            exit_reason=exit_reason,
            gross_pnl=gross_pnl,
            fees_paid=fees_paid,
            pnl=pnl,
            r_multiple=pnl / (capital * DEFAULT_RISK_PER_TRADE_PCT / 100) if capital else 0.0,
        ))
        equity_curve.append(equity)

    for t in live_eval:
        date = month_end_dates[t]
        desired = select_gem_asset(symbol_data, month_end_dates, t)

        if held_asset is not None and desired != held_asset:
            _close_position(date, "switch")
            held_asset = None

        if held_asset is None:
            held_asset = desired
            entry_date = date
            entry_price = symbol_data[held_asset]["candles"][symbol_data[held_asset]["date_index"][date]].close

    if held_asset is not None:
        _close_position(month_end_dates[live_eval[-1]], "eol")

    return trades, equity_curve


def compute_gem_fold_boundaries(month_end_dates, num_folds=NUM_FOLDS):
    """
    Splits the USABLE monthly evaluation sequence
    (month_end_dates[MOMENTUM_LOOKBACK_MONTHS:]) into num_folds
    roughly-equal-count, contiguous, non-overlapping folds — no separate
    initial-training span (see module docstring: the 12-month lookback is
    warm-up, not training). Returns a list of {"fold", "test_start",
    "test_end"} dicts with date-string boundaries.
    """
    live_eval_dates = month_end_dates[MOMENTUM_LOOKBACK_MONTHS:]
    n = len(live_eval_dates)
    fold_size = n // num_folds
    boundary_dates = [live_eval_dates[i * fold_size] for i in range(num_folds)] + [live_eval_dates[-1]]
    return [
        {"fold": i + 1, "test_start": boundary_dates[i], "test_end": boundary_dates[i + 1]}
        for i in range(num_folds)
    ]


def slice_gem_trades_by_folds(trades, equity_curve, folds, capital):
    """
    Mirrors backtest_donchian_ensemble.py's slice_ensemble_trades_by_folds()
    convention (bucket by EXIT timestamp, since equity only moves when a
    holding period closes) with ONE DELIBERATE DIFFERENCE: the LAST
    fold's upper boundary always extends through the end of the trade
    list (len(trades)) rather than using a strict "<test_end" comparison
    like every earlier fold. Reason: the last fold's test_end is defined
    as the final live evaluation point's own date, which is also exactly
    the exit date of the final "eol" trade — a strict "<" comparison
    would silently drop that trade from the last fold's count (while
    POOLED, which has no upper bound, would still include it), producing
    a fold-sum that doesn't match the pooled number. Invisible in Track
    B's 200+-trade context; immediately visible and misleading with
    GEM's low trade count and only 2 folds. This guarantees sum(fold
    trade_counts) == pooled trade_count exactly (see the test suite).

    Returns (fold_summaries, fold_switch_counts, pooled_summary, pooled_switch_count).

    NOTE, checked not assumed: fold boundaries are 10-char YYYY-MM-DD date
    strings (from month_end_dates), but trade exit_timestamp values are
    full candle timestamps (e.g. "2022-01-03T05:00:00+00:00"). Comparing
    those directly LOOKED like a length-mismatch risk, but is provably
    NOT one for the "<" comparisons this function actually uses: for any
    ISO date-then-time string sharing a bare date string's first 10
    characters, the full string always sorts after the bare date (since
    'T' sorts after every digit), so "full < bare_date" and
    "truncated < bare_date" always agree — verified exhaustively across
    date/boundary/time-of-day combinations, not just spot-checked, before
    trusting this. Truncated to [:10] anyway purely for clarity/
    robustness (e.g. if a future caller ever compared with "<=" instead
    of "<", the two WOULD diverge) — not because the untruncated version
    was observed to misbucket anything.
    """
    def _exit_date(t):
        return t.exit_timestamp[:10]

    boundaries = [sum(1 for t in trades if _exit_date(t) < f["test_start"]) for f in folds]
    boundaries.append(len(trades))

    fold_summaries = []
    fold_switch_counts = []
    for i, fold in enumerate(folds):
        start_idx = boundaries[i]
        end_idx = boundaries[i + 1] if i == len(folds) - 1 else sum(1 for t in trades if _exit_date(t) < fold["test_end"])
        fold_trades = trades[start_idx:end_idx]
        fold_curve = equity_curve[start_idx:end_idx + 1]
        starting_equity = fold_curve[0] if fold_curve else capital
        fold_summaries.append(summarize(fold_trades, fold_curve if fold_curve else [starting_equity], starting_equity))
        fold_switch_counts.append(sum(1 for t in fold_trades if t.exit_reason == "switch"))

    pooled_start_idx = boundaries[0]
    pooled_trades = trades[pooled_start_idx:]
    pooled_curve = equity_curve[pooled_start_idx:]
    pooled_starting_equity = pooled_curve[0] if pooled_curve else capital
    pooled_summary = summarize(pooled_trades, pooled_curve if pooled_curve else [pooled_starting_equity], pooled_starting_equity)
    pooled_switch_count = sum(1 for t in pooled_trades if t.exit_reason == "switch")

    return fold_summaries, fold_switch_counts, pooled_summary, pooled_switch_count


def main():
    end = datetime.now(timezone.utc) - timedelta(minutes=20)

    print(f"=== Track A: Dual Momentum / GEM (base, no circuit breaker) — {MOMENTUM_LOOKBACK_MONTHS}mo lookback, monthly rotation ===")
    print(f"requested start: {REQUESTED_START.date()} — see module docstring for the confirmed 2016-01-04 account-level data floor")
    symbol_data = {}
    for symbol in UNIVERSE:
        series = build_symbol_series(symbol, REQUESTED_START, end)
        if series is None:
            print(f"{symbol}: no candle data returned")
            return
        symbol_data[symbol] = series
        first, last = series["candles"][0], series["candles"][-1]
        print(f"  {symbol}: {first.timestamp[:10]} -> {last.timestamp[:10]}  ({len(series['candles'])} daily candles, dividend+split adjusted)")

    calendar = compute_shared_calendar(symbol_data, UNIVERSE)
    month_end_dates = compute_month_end_dates(calendar)
    live_eval_dates = month_end_dates[MOMENTUM_LOOKBACK_MONTHS:]
    print(f"\nshared calendar: {calendar[0]} -> {calendar[-1]}  ({len(calendar)} trading days)")
    print(f"month-end evaluation points: {len(month_end_dates)} total ({month_end_dates[0]} -> {month_end_dates[-1]})")
    print(f"usable (post-{MOMENTUM_LOOKBACK_MONTHS}mo-warmup) evaluation window: {live_eval_dates[0]} -> {live_eval_dates[-1]}  ({len(live_eval_dates)} live evaluation points)")
    print(f"(fee model: {GEM_COMMISSION_PCT:.2f}% commission + {GEM_SLIPPAGE_BPS:.0f}bps slippage per leg, reused from Track B)")

    folds = compute_gem_fold_boundaries(month_end_dates, num_folds=NUM_FOLDS)
    print(f"\nfold boundaries ({NUM_FOLDS} folds, no separate training span — 12mo lookback is warm-up only):")
    for fold in folds:
        print(f"  fold {fold['fold']}: test {fold['test_start']} -> {fold['test_end']}")

    net_trades, net_curve = simulate_gem(symbol_data, month_end_dates, fee_pct=GEM_COMMISSION_PCT, slippage_bps=GEM_SLIPPAGE_BPS)
    gross_trades, gross_curve = simulate_gem(symbol_data, month_end_dates, fee_pct=0.0, slippage_bps=0.0)

    net_folds, net_switch_counts, net_pooled, net_pooled_switches = slice_gem_trades_by_folds(net_trades, net_curve, folds, PAPER_VALIDATION_CAPITAL)
    gross_folds, _, gross_pooled, _ = slice_gem_trades_by_folds(gross_trades, gross_curve, folds, PAPER_VALIDATION_CAPITAL)

    print(f"\n=== Results ({len(net_trades)} total holding periods, {net_pooled['trade_count']} pooled) ===")
    rows = []
    for fold, net, gross, switches in zip(folds, net_folds, gross_folds, net_switch_counts):
        rows.append({
            "fold": fold["fold"],
            "test_window": f"{fold['test_start']}..{fold['test_end']}",
            "n": net["trade_count"],
            "switches": switches,
            "flag": "THIN-SWITCHES" if switches < SWITCH_COUNT_THIN_THRESHOLD else "",
            "net%": f"{net['total_return_pct']:.2f}",
            "gross%": f"{gross['total_return_pct']:.2f}",
            "max_dd%": f"{net['max_drawdown_pct']:.2f}",
        })
    rows.append({
        "fold": "POOLED",
        "test_window": f"{folds[0]['test_start']}..{folds[-1]['test_end']}",
        "n": net_pooled["trade_count"],
        "switches": net_pooled_switches,
        "flag": "",
        "net%": f"{net_pooled['total_return_pct']:.2f}",
        "gross%": f"{gross_pooled['total_return_pct']:.2f}",
        "max_dd%": f"{net_pooled['max_drawdown_pct']:.2f}",
    })
    _print_table(rows, [
        ("fold", "fold"), ("test_window", "test_window"), ("n", "n"),
        ("switches", "switches"), ("flag", "flag"), ("net%", "net%"), ("gross%", "gross%"), ("max_dd%", "max_dd%"),
    ])

    thin = [r["fold"] for r in rows if r["flag"] == "THIN-SWITCHES"]
    if thin:
        print(
            f"WARNING: fold(s) {thin} have fewer than {SWITCH_COUNT_THIN_THRESHOLD} asset switches — "
            f"read as a possible sample-starvation risk, not fully conclusive even if numerically positive."
        )

    print(f"\nraw facts against the pre-committed bar (pooled net-of-cost positive AND both folds individually positive) — reported, not self-judged:")
    for fold, net in zip(folds, net_folds):
        print(f"  fold {fold['fold']} net-of-cost: {'positive' if net['total_return_pct'] > 0 else 'negative/zero'} ({net['total_return_pct']:.2f}%)")
    print(f"  pooled net-of-cost: {'positive' if net_pooled['total_return_pct'] > 0 else 'negative/zero'} ({net_pooled['total_return_pct']:.2f}%)")

    print(f"\n=== Holding-period detail (which asset, how long, net pnl) ===")
    _print_table(
        [{
            "asset": t.asset,
            "entry": t.entry_timestamp[:10],
            "exit": t.exit_timestamp[:10],
            "reason": t.exit_reason,
            "net_pnl": f"${t.pnl:.2f}",
        } for t in net_trades],
        [("asset", "asset"), ("entry", "entry"), ("exit", "exit"), ("reason", "reason"), ("net_pnl", "net_pnl")],
    )


if __name__ == "__main__":
    main()
