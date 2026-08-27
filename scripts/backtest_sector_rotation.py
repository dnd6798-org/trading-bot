"""
Track C candidate (spec v50 §10.20): DMSR — Dual Momentum Sector Rotation.

BACKTEST-ONLY. This script does not touch src/execution.py, the daily
job, src/fill_listener.py, src/risk_filter.py, or any other live code
path. It is a new standalone script, using the same data source and
conventions as scripts/backtest_etf_donchian.py (Alpaca
StockHistoricalDataClient daily bars, alpaca-py 0.43.5).

NO ADOPT/ABANDON VERDICT is computed or implied here — raw numbers only,
per standing project rules (RULES.md; CLAUDE.md "Coding conventions").
The adoption decision is made in claude.ai against pre-committed bars and
must not be decided in this session.

=====================================================================
STRATEGY RULES (exactly as briefed — no substitutions)
=====================================================================
Universe (11 SPDR Select Sector ETFs):
    XLK XLV XLE XLF XLY XLP XLU XLI XLB XLRE XLC
Defensive / risk-off asset: AGG (held 100% when the market filter is off).

Ranking signal: trailing LOOKBACK-month total return, measured as the
price return of the daily *close* series (month-end close vs. the close
LOOKBACK month-ends earlier). See "DIVIDEND-ADJUSTMENT LIMITATION" below.

Market absolute-momentum filter: at each monthly rebalance, if SPY's own
trailing LOOKBACK-month return is negative, allocate 100% to AGG and
ignore all sector rankings for that month.

Risk-on holdings: the top 3 of the 11 ranked sectors, equal-weighted
(1/3 each) at the moment a name is *bought*.

Whipsaw / hysteresis guard: a sector currently held is only sold if its
rank falls out of the top 5 (not merely out of the top 3). A held sector
sitting at rank 4 or 5 is kept, and the top-ranked non-held sector that
would otherwise displace it is NOT bought.

Rebalance cadence: monthly. The ranking/filter is computed from the last
trading day of month M (month-end close); the resulting trades execute at
the *close of the first trading day of month M+1* ("the first trading day
after each month-end close", per the brief) — a deliberate 1-trading-day
signal-to-execution gap, no lookahead.

Transaction cost: 0.10% of traded notional on every leg (each individual
ETF buy or sell) at each rebalance.

=====================================================================
IMPLEMENTATION JUDGMENT CALLS (confirmed with the user before coding, or
flagged here — per RULES.md "stop and report, don't guess")
=====================================================================
1. WEIGHT DRIFT (confirmed with the user): trade ONLY on composition
   change. When the held set is unchanged month-to-month, NO trades are
   made and the three names' weights are allowed to drift — kept names
   are never "trimmed" back to 1/3. Consequences: (a) far fewer legs/year
   than a full monthly equal-weight rebalance would produce; (b) a swap
   is self-funding — the proceeds of the sold name(s) fund the bought
   name(s), split equally when the counts differ — so a newly-bought name
   inherits roughly the drifted weight of the name it replaced, not a
   fresh 1/3 of total equity.

2. SHARPE RISK-FREE RATE (confirmed with the user): BIL's own monthly
   total return (dividend-adjusted, Adjustment.ALL) is the risk-free
   proxy, subtracted from each monthly strategy return before
   annualizing. Sharpe = mean(excess monthly) / stdev(excess monthly,
   sample/ddof=1) * sqrt(12). A secondary RF=0 Sharpe is also printed for
   context.

3. PRICE BASIS — SPLIT-ADJUSTED, NOT DIVIDEND-ADJUSTED, and a FORCED
   DEVIATION from the brief's "same basis as the Donchian backtest"
   (flag, not silently resolved — per RULES.md):

   The brief specified "price return from daily close bars — dividend-
   adjustment is a known limitation, same basis as the existing Donchian
   backtest" (which uses Adjustment.RAW). Adjustment.RAW is
   fully unadjusted — it does NOT adjust for share splits either. On
   2025-12-05 State Street ran a 2:1 forward split on several Select
   Sector SPDR ETFs (XLK, XLE, XLY, XLU, XLB all halve in price that day
   in the RAW series). RAW would inject a phantom ~50% one-day loss into
   the backtest for every one of those names — confirmed empirically
   before this decision, not assumed. Track B's RAW choice was safe only
   because its universe (SPY/QQQ/IWM/EFA/AGG/GLD/DBC/VNQ) had no in-window
   splits.

   RESOLUTION: this script uses Adjustment.SPLIT as the default price
   basis — split-adjusted (the 2025-12-05 corporate action is handled
   correctly) but NOT dividend-adjusted, so the brief's intended "price
   return, dividends are a known limitation" basis is preserved. A split
   is a pure share-count artifact, not a return; adjusting for it is a
   correctness requirement, not a modelling choice.

   DIVIDEND LIMITATION still in effect (as the brief intended): sector/AGG
   returns are price-only, understating absolute strategy return by
   roughly the universe's dividend yield (~1.5-2%/yr for the sector ETFs;
   materially more for any month spent risk-off in AGG, whose total
   return is mostly coupons — ~3-4%/yr annualized). Because the Sharpe RF
   proxy (BIL) IS dividend-adjusted while strategy returns are not, the
   reported Sharpe is biased DOWNWARD from both sides. Rerun with
   `--adjustment all` for the dividend-inclusive version, or
   `--adjustment raw` to see the (broken, split-corrupted) literal-brief
   version for transparency.

4. LOOKBACK ANCHORING: trailing returns are month-end-to-month-end (close
   at month_end[t] vs close at month_end[t - lookback]), NOT "N trading
   days back". The market filter uses the SAME lookback value as the
   sector ranking — the robustness reruns change that one shared value
   (10 / 11 / 13 months), nothing else.

5. WINDOW: the common daily-bar history across all 11 sectors is bounded
   by XLC (inception 2018-06-19). Every other symbol (10 sectors + AGG +
   SPY + BIL) starts at this account's 2016-01-04 Alpaca data floor —
   confirmed empirically, same floor Track B / Track A found. Each
   lookback run reports over its OWN maximum window (a longer lookback
   burns one or two more months of warm-up), so the 4 runs' start dates
   differ slightly by construction. The combined monthly-return CSV is
   NaN-padded at the front so all 4 columns align by month-end date.

6. TIE-BREAK: sectors are ranked by (-trailing_return, symbol), so a
   floating-point tie (vanishingly unlikely) resolves deterministically
   by ticker.

7. METRIC BASES: max drawdown is from the DAILY mark-to-market equity
   curve (peak-to-trough %). CAGR uses calendar days / 365.25 and the
   deployed window (first execution day -> last data day). "Rebalance
   trades per year" counts individual legs (buys + sells), total / years.
   The monthly-return series begins with the first FULL calendar month
   after initial deployment; the partial stub month between the first
   execution day and the first month-end is excluded from the series
   (but is included in the daily equity curve, CAGR, and max drawdown).

Usage:
    python scripts/backtest_sector_rotation.py
    python scripts/backtest_sector_rotation.py --adjustment all
    python scripts/backtest_sector_rotation.py --lookbacks 12
"""
import argparse
import math
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alpaca.data.enums import Adjustment

from src.data_ingestion import fetch_historical_stock_candles
from scripts.backtest import _print_table
from scripts.backtest_donchian_ensemble import PAPER_VALIDATION_CAPITAL
from scripts.backtest_gem import (
    compute_shared_calendar,
    compute_month_end_dates,
    compute_max_drawdown_pct,
)

SECTOR_UNIVERSE = ["XLK", "XLV", "XLE", "XLF", "XLY", "XLP", "XLU", "XLI", "XLB", "XLRE", "XLC"]
DEFENSIVE_ASSET = "AGG"
MARKET_FILTER_SYMBOL = "SPY"
RISK_FREE_SYMBOL = "BIL"

TOP_N_HOLD = 3
HYSTERESIS_RANK = 5
TRANSACTION_COST_PCT = 0.10  # per leg, % of traded notional

PRIMARY_LOOKBACK = 12
ROBUSTNESS_LOOKBACKS = [10, 11, 13]
DEFAULT_LOOKBACKS = [PRIMARY_LOOKBACK] + ROBUSTNESS_LOOKBACKS

REQUESTED_START = datetime(2006, 2, 3, tzinfo=timezone.utc)  # requested, not honored — 2016-01-04 account floor, see docstring
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "backtest_output"


# --------------------------------------------------------------------------
# data
# --------------------------------------------------------------------------
def build_symbol_series(symbol, start, end, adjustment):
    candles = fetch_historical_stock_candles(symbol, start, end, adjustment=adjustment)
    if not candles:
        return None
    date_index = {c.timestamp[:10]: i for i, c in enumerate(candles)}
    return {"symbol": symbol, "candles": candles, "date_index": date_index}


# --------------------------------------------------------------------------
# signal
# --------------------------------------------------------------------------
def trailing_return(series, month_end_dates, t, lookback):
    """
    Month-end-to-month-end price return over `lookback` months, as of
    evaluation point t (index into month_end_dates). Price return of the
    RAW close series unless the caller fetched an adjusted series.
    """
    d_now = month_end_dates[t]
    d_then = month_end_dates[t - lookback]
    di = series["date_index"]
    c_now = series["candles"][di[d_now]].close
    c_then = series["candles"][di[d_then]].close
    return (c_now - c_then) / c_then


def rank_sectors(symbol_data, month_end_dates, t, lookback):
    """(symbol, trailing_return) for all 11 sectors, best-first, deterministic tie-break by ticker."""
    rets = [(s, trailing_return(symbol_data[s], month_end_dates, t, lookback)) for s in SECTOR_UNIVERSE]
    rets.sort(key=lambda kv: (-kv[1], kv[0]))
    return rets


def select_target_holdings(current_holdings, ranked, spy_return):
    """
    Decide the target holding set for a rebalance.

    current_holdings : symbols currently held — either up to 3 sector
                       names, or ["AGG"] (a prior risk-off month), or []
                       (first-ever deployment).
    ranked           : rank_sectors() output (list of (symbol, ret), best first).
    spy_return       : SPY's own trailing return over the same lookback.

    Returns (target_holdings, is_risk_off).

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


# --------------------------------------------------------------------------
# simulation
# --------------------------------------------------------------------------
@dataclass
class RebalanceEvent:
    signal_date: str
    exec_date: str
    risk_off: bool
    target: list
    sold: list
    bought: list
    legs: int
    cost: float
    equity_before: float
    equity_after: float


@dataclass
class RunResult:
    lookback: int
    daily_curve: list  # (date, equity)
    events: list  # RebalanceEvent
    monthly_returns: list  # (month_end_date, return_fraction)
    first_exec: str
    last_date: str
    capital: float
    final_equity: float


def simulate(symbol_data, calendar, month_end_dates, lookback, capital, cost_pct):
    """
    Day-by-day mark-to-market simulation. Trades happen only on the first
    trading day after a month-end, and only when the target holding set
    differs from what is currently held (judgment call #1). Self-funding
    swaps: sell proceeds fund the buys, split equally across new names.
    """
    cost_frac = cost_pct / 100.0
    cal_index = {d: i for i, d in enumerate(calendar)}

    def price(sym, date):
        s = symbol_data[sym]
        return s["candles"][s["date_index"][date]].close

    # Rebalance schedule: eval at month_end_dates[t] for t in [lookback, ...],
    # execute on the next trading day within `calendar`.
    schedule = []
    for t in range(lookback, len(month_end_dates)):
        me = month_end_dates[t]
        if me not in cal_index:
            continue
        j = cal_index[me] + 1
        if j >= len(calendar):
            continue
        schedule.append((me, calendar[j], t))
    if not schedule:
        return None

    sched_by_exec = {ex: (sig, t) for sig, ex, t in schedule}
    first_exec = schedule[0][1]

    positions = {}  # symbol -> shares
    cash = 0.0
    deployed = False
    events = []
    daily_curve = []

    for date in calendar:
        if date < first_exec:
            continue

        if date in sched_by_exec:
            sig_date, t = sched_by_exec[date]
            spy_ret = trailing_return(symbol_data[MARKET_FILTER_SYMBOL], month_end_dates, t, lookback)
            ranked = rank_sectors(symbol_data, month_end_dates, t, lookback)
            current = list(positions.keys())
            target, risk_off = select_target_holdings(current, ranked, spy_ret)

            if not deployed:
                cash = capital
                equity_before = capital
            else:
                equity_before = cash + sum(sh * price(s, date) for s, sh in positions.items())

            sold, bought = [], []
            total_cost = 0.0

            for s in list(positions.keys()):
                if s not in target:
                    proceeds = positions[s] * price(s, date)
                    c = proceeds * cost_frac
                    cash += proceeds - c
                    total_cost += c
                    sold.append(s)
                    del positions[s]

            to_buy = [s for s in target if s not in positions]
            if to_buy:
                budget_each = cash / len(to_buy)
                for s in to_buy:
                    c = budget_each * cost_frac
                    positions[s] = (budget_each - c) / price(s, date)
                    cash -= budget_each
                    total_cost += c
                    bought.append(s)

            deployed = True
            equity_after = cash + sum(sh * price(s, date) for s, sh in positions.items())
            events.append(RebalanceEvent(
                signal_date=sig_date, exec_date=date, risk_off=risk_off,
                target=list(target), sold=sold, bought=bought,
                legs=len(sold) + len(bought), cost=total_cost,
                equity_before=equity_before, equity_after=equity_after,
            ))

        equity = cash + sum(sh * price(s, date) for s, sh in positions.items())
        daily_curve.append((date, equity))

    curve_by_date = dict(daily_curve)
    me_in_curve = [d for d in month_end_dates if d in curve_by_date]
    monthly = []
    for i in range(1, len(me_in_curve)):
        prev = curve_by_date[me_in_curve[i - 1]]
        cur = curve_by_date[me_in_curve[i]]
        monthly.append((me_in_curve[i], (cur - prev) / prev if prev else 0.0))

    return RunResult(
        lookback=lookback,
        daily_curve=daily_curve,
        events=events,
        monthly_returns=monthly,
        first_exec=first_exec,
        last_date=daily_curve[-1][0],
        capital=capital,
        final_equity=daily_curve[-1][1],
    )


# --------------------------------------------------------------------------
# metrics
# --------------------------------------------------------------------------
def bil_monthly_returns(bil_series, month_end_dates):
    """BIL month-end-to-month-end total return (the series is fetched dividend-adjusted) keyed by month-end date."""
    di = bil_series["date_index"]
    c = bil_series["candles"]
    me = [d for d in month_end_dates if d in di]
    out = {}
    for i in range(1, len(me)):
        p = c[di[me[i - 1]]].close
        q = c[di[me[i]]].close
        out[me[i]] = (q - p) / p if p else 0.0
    return out


def _sample_std(xs):
    if len(xs) < 2:
        return 0.0
    mean = sum(xs) / len(xs)
    return math.sqrt(sum((x - mean) ** 2 for x in xs) / (len(xs) - 1))


def annualized_sharpe(monthly_returns, rf_by_month=None):
    """mean(excess) / stdev(excess, ddof=1) * sqrt(12). rf_by_month=None => RF of 0."""
    if len(monthly_returns) < 2:
        return 0.0
    excess = [r - (rf_by_month.get(d, 0.0) if rf_by_month else 0.0) for d, r in monthly_returns]
    sd = _sample_std(excess)
    if sd == 0:
        return 0.0
    return (sum(excess) / len(excess)) / sd * math.sqrt(12)


def cagr(first_equity, final_equity, first_date, last_date):
    days = (datetime.fromisoformat(last_date) - datetime.fromisoformat(first_date)).days
    if days <= 0 or first_equity <= 0:
        return 0.0
    years = days / 365.25
    return (final_equity / first_equity) ** (1 / years) - 1


def summarize_run(run: RunResult, rf_by_month):
    equities = [e for _, e in run.daily_curve]
    days = (datetime.fromisoformat(run.last_date) - datetime.fromisoformat(run.first_exec)).days
    years = days / 365.25 if days > 0 else 0.0
    total_legs = sum(e.legs for e in run.events)
    trades_with_action = sum(1 for e in run.events if e.legs > 0)
    risk_off_rebalances = sum(1 for e in run.events if e.risk_off)
    return {
        "lookback": run.lookback,
        "window": f"{run.first_exec}..{run.last_date}",
        "years": years,
        "months": len(run.monthly_returns),
        "total_return_pct": (run.final_equity - run.capital) / run.capital * 100,
        "cagr_pct": cagr(run.capital, run.final_equity, run.first_exec, run.last_date) * 100,
        "sharpe_bil_rf": annualized_sharpe(run.monthly_returns, rf_by_month),
        "sharpe_zero_rf": annualized_sharpe(run.monthly_returns, None),
        "max_drawdown_pct": compute_max_drawdown_pct(equities),
        "rebalance_opportunities": len(run.events),
        "rebalances_with_trades": trades_with_action,
        "risk_off_rebalances": risk_off_rebalances,
        "total_legs": total_legs,
        "legs_per_year": total_legs / years if years > 0 else 0.0,
    }


# --------------------------------------------------------------------------
# reporting
# --------------------------------------------------------------------------
def write_monthly_returns_csv(runs, rf_by_month, path):
    all_dates = sorted({d for run in runs for d, _ in run.monthly_returns})
    by_lookback = {run.lookback: dict(run.monthly_returns) for run in runs}
    lookbacks = sorted(by_lookback)

    header = ["month_end"] + [f"ret_{lb}m" for lb in lookbacks] + ["bil_rf_monthly"]
    lines = [",".join(header)]
    for d in all_dates:
        row = [d]
        for lb in lookbacks:
            v = by_lookback[lb].get(d)
            row.append(f"{v:.8f}" if v is not None else "")
        rf = rf_by_month.get(d)
        row.append(f"{rf:.8f}" if rf is not None else "")
        lines.append(",".join(row))

    text = "\n".join(lines) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return text


def print_rebalance_log(run: RunResult):
    action_events = [e for e in run.events if e.legs > 0]
    print(
        f"\n  rebalance log — lookback {run.lookback}m "
        f"({len(run.events)} monthly rebalance opportunities, {len(action_events)} produced trades; "
        f"opportunities with no composition change are omitted below but counted in the totals)"
    )
    _print_table(
        [{
            "signal_date": e.signal_date,
            "exec_date": e.exec_date,
            "risk_off": "yes" if e.risk_off else "",
            "sold": ",".join(e.sold) or "-",
            "bought": ",".join(e.bought) or "-",
            "legs": e.legs,
            "cost$": f"{e.cost:.2f}",
            "equity_after$": f"{e.equity_after:,.2f}",
        } for e in action_events],
        [
            ("signal_date", "signal_date"), ("exec_date", "exec_date"), ("risk_off", "risk_off"),
            ("sold", "sold"), ("bought", "bought"), ("legs", "legs"),
            ("cost$", "cost$"), ("equity_after$", "equity_after$"),
        ],
    )


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--lookbacks", nargs="+", type=int, default=DEFAULT_LOOKBACKS,
                   help="lookback windows in months (default: 12 10 11 13 — primary first)")
    p.add_argument("--adjustment", choices=["split", "all", "raw"], default="split",
                   help="price series for sectors/AGG/SPY: split (default — split-adjusted, NOT dividend-adjusted; see docstring judgment call #3), "
                        "all (dividend+split adjusted / total return), or raw (fully unadjusted — BROKEN for this universe, 2025-12-05 SPDR split; kept for transparency only)")
    p.add_argument("--capital", type=float, default=PAPER_VALIDATION_CAPITAL)
    p.add_argument("--cost-pct", type=float, default=TRANSACTION_COST_PCT, help="per-leg transaction cost, percent of traded notional")
    p.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    return p.parse_args()


def main():
    args = parse_args()
    end = datetime.now(timezone.utc) - timedelta(minutes=20)
    adjustment = {"raw": Adjustment.RAW, "split": Adjustment.SPLIT, "all": Adjustment.ALL}[args.adjustment]

    print("=== Track C candidate: DMSR (Dual Momentum Sector Rotation) — backtest only, NO verdict rendered ===")
    print(f"sector price basis: {adjustment}  |  BIL (Sharpe RF proxy): ALWAYS dividend-adjusted (Adjustment.ALL)")
    print(f"transaction cost: {args.cost_pct:.2f}% per leg  |  capital: ${args.capital:,.0f}  |  lookbacks: {args.lookbacks} months")
    if args.adjustment == "split":
        print("PRICE BASIS = SPLIT-ADJUSTED, NOT dividend-adjusted (forced deviation from the brief's literal 'RAW, same as "
              "Donchian' — Adjustment.RAW injects a phantom ~50% loss from the 2025-12-05 SPDR 2:1 split on XLK/XLE/XLY/XLU/XLB; "
              "see docstring judgment call #3). DIVIDEND limitation still in effect per the brief: sector/AGG returns price-only, "
              "absolute return understated ~1.5-2%/yr (sectors), ~3-4%/yr for risk-off months in AGG; Sharpe biased downward "
              "(strategy price-only vs. dividend-adjusted BIL RF). Rerun --adjustment all for the total-return version.")
    elif args.adjustment == "raw":
        print("WARNING: --adjustment raw is BROKEN for this universe — the 2025-12-05 SPDR 2:1 split (XLK/XLE/XLY/XLU/XLB) is "
              "NOT adjusted out, injecting a phantom ~50% one-day loss. Shown only for transparency against the brief's literal wording.")

    all_symbols = SECTOR_UNIVERSE + [DEFENSIVE_ASSET, MARKET_FILTER_SYMBOL, RISK_FREE_SYMBOL]
    symbol_data = {}
    for symbol in all_symbols:
        adj = Adjustment.ALL if symbol == RISK_FREE_SYMBOL else adjustment
        series = build_symbol_series(symbol, REQUESTED_START, end, adj)
        if series is None:
            print(f"  {symbol}: NO DATA — aborting")
            return
        symbol_data[symbol] = series
        first, last = series["candles"][0], series["candles"][-1]
        print(f"  {symbol:5s}: {first.timestamp[:10]} -> {last.timestamp[:10]}  ({len(series['candles'])} daily candles)")

    # Common daily-bar calendar across ALL symbols (intersection). XLC (2018-06-19) is the binding constraint.
    calendar = compute_shared_calendar(symbol_data, all_symbols)
    month_end_dates = compute_month_end_dates(calendar)
    print(f"\ncommon daily-bar window (intersection of all {len(all_symbols)} symbols): {calendar[0]} -> {calendar[-1]}  ({len(calendar)} trading days)")
    print(f"month-end evaluation points available: {len(month_end_dates)}  ({month_end_dates[0]} -> {month_end_dates[-1]})")
    xlc_first = symbol_data["XLC"]["candles"][0].timestamp[:10]
    print(f"binding data-start constraint: XLC first bar = {xlc_first} (all other symbols start 2016-01-04, this account's Alpaca floor)")

    rf_by_month = bil_monthly_returns(symbol_data[RISK_FREE_SYMBOL], month_end_dates)

    runs = []
    for lookback in args.lookbacks:
        run = simulate(symbol_data, calendar, month_end_dates, lookback, args.capital, args.cost_pct)
        if run is None:
            print(f"\nlookback {lookback}m: not enough month-end history to run — skipped")
            continue
        runs.append(run)

    if not runs:
        print("\nno runs produced — aborting")
        return

    # --- summary table (all 4 runs) ---
    print("\n=== Summary — all runs, raw, net-of-cost (NO verdict) ===")
    summaries = [summarize_run(run, rf_by_month) for run in runs]
    _print_table(
        [{
            "lookback": f"{s['lookback']}m" + (" (primary)" if s["lookback"] == PRIMARY_LOOKBACK else ""),
            "window": s["window"],
            "yrs": f"{s['years']:.2f}",
            "mo": s["months"],
            "tot_ret%": f"{s['total_return_pct']:.2f}",
            "CAGR%": f"{s['cagr_pct']:.2f}",
            "Sharpe(BIL)": f"{s['sharpe_bil_rf']:.3f}",
            "Sharpe(0)": f"{s['sharpe_zero_rf']:.3f}",
            "maxDD%": f"{s['max_drawdown_pct']:.2f}",
            "legs/yr": f"{s['legs_per_year']:.2f}",
        } for s in summaries],
        [
            ("lookback", "lookback"), ("window", "window"), ("yrs", "yrs"), ("mo", "mo"),
            ("tot_ret%", "tot_ret%"), ("CAGR%", "CAGR%"),
            ("Sharpe(BIL)", "Sharpe(BIL)"), ("Sharpe(0)", "Sharpe(0)"),
            ("maxDD%", "maxDD%"), ("legs/yr", "legs/yr"),
        ],
    )
    print("  Sharpe(BIL) = risk-free = BIL monthly total return; Sharpe(0) = risk-free = 0. Both annualized (x sqrt 12), sample stdev (ddof=1).")
    print("  maxDD% from the daily mark-to-market equity curve. legs/yr = total individual buy+sell legs / deployed years.")

    print("\n=== Per-run rebalance detail (raw) ===")
    for run, s in zip(runs, summaries):
        print(f"\n--- lookback {run.lookback}m ---")
        print(f"  deployed window: {s['window']}  ({s['years']:.2f} yrs, {s['months']} full months in the monthly-return series)")
        print(f"  rebalance opportunities: {s['rebalance_opportunities']}  |  with trades: {s['rebalances_with_trades']}  |  risk-off (100% AGG) months: {s['risk_off_rebalances']}")
        print(f"  total legs: {s['total_legs']}  |  legs/yr: {s['legs_per_year']:.2f}  |  total transaction cost: ${sum(e.cost for e in run.events):,.2f}")
        print(f"  total return: {s['total_return_pct']:.2f}%  |  CAGR: {s['cagr_pct']:.2f}%  |  Sharpe(BIL): {s['sharpe_bil_rf']:.3f}  |  Sharpe(0): {s['sharpe_zero_rf']:.3f}  |  maxDD: {s['max_drawdown_pct']:.2f}%")
        print_rebalance_log(run)

    # --- monthly returns CSV ---
    csv_path = args.output_dir / f"dmsr_monthly_returns_{args.adjustment}.csv"
    csv_text = write_monthly_returns_csv(runs, rf_by_month, csv_path)
    print(f"\n=== Monthly-return time series (net-of-cost) — written to {csv_path} ===")
    print("(also printed in full below for the follow-up Track B correlation step; empty cell = that lookback run had not started yet)")
    print(csv_text)


if __name__ == "__main__":
    main()
