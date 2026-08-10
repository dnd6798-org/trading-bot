"""
Track C (spec v25 §2, §10.5): SPY put credit spread, premium-selling —
the third and final track of the original three-track pivot (spec v23
§2). Design locked this session, after CLAUDE.md Track C findings 1-2
confirmed the account's real options data floor (2024-01-18) and, more
consequentially, that NO historical bid/ask or IV/greeks exist anywhere
on this account/SDK surface — only historical daily OHLCV bars and trade
prints. That absence drives every mechanical choice below.

TWO DELIBERATE SIMPLIFICATIONS (user instruction, to avoid compounding
estimation error on top of an already-approximate data source):
  1. Strikes are selected by fixed %-OTM off spot, NOT by delta. Delta
     would have to be reconstructed via Black-Scholes from a bar-close
     price standing in for a true mid (no real bid/ask to anchor an IV
     inversion to) — one estimation layer we're simply not building.
  2. Both entry credit AND expiration payoff use REAL historical data
     directly. Entry credit = the real historical daily-bar close price
     of each leg on the entry date (the actual traded price data this
     account has, same convention every other backtest in this repo
     already uses for its own OHLC-close fills — no bid/ask assumption
     is being introduced here that didn't already exist elsewhere).
     Expiration payoff needs NO option data at all: held to expiration,
     a put credit spread's value is fully determined by intrinsic value
     off the UNDERLYING's real closing price alone (max(K-S,0) per leg)
     — no Black-Scholes anywhere in this file.

REDESIGN (this session, two pre-registered changes, reasoned
independently of the first run's zero-trade result, not a reaction to
it — see CLAUDE.md Track C finding 3 for that result and finding 4 for
this one):

  1. STRIKE ZONE narrowed from a fixed 5%/8%-OTM target to a NARROWEST-
     ACHIEVABLE search within a 2-4% OTM zone (NARROW_OTM_LOW/HIGH).
     select_narrow_spread_strikes() checks the REAL listed strike ladder
     for each cycle's own expiry (not assumed) and picks whichever
     in-zone strike has the SMALLEST distance to its own next-lower
     listed strike — the narrowest structurally achievable width at that
     specific expiry, not a fixed number forced onto the chain. Confirmed
     empirically before writing this docstring, not assumed: SPY's real
     chain lists $1 strikes uniformly through the 2-4% OTM zone across
     every expiry sampled (2024-02-20, 2025-07-21, 2026-06-22) — so $1 is
     expected to be the typical achieved width, but the code does NOT
     hardcode $1; it re-derives the achievable width fresh per cycle and
     reports whatever it actually finds, including if some expiry's real
     ladder doesn't support $1 there. If no in-zone strike has usable
     data on any candidate (liquidity fallback exhausted), the cycle is
     skipped and logged ("no_narrow_spread_with_data") rather than
     forcing a wider width the instruction didn't ask for.
  2. SIZING: a defined-risk-specific 2% risk-per-trade override
     (PCS_RISK_PER_TRADE_PCT), replacing spec §4.1's global 1%
     (DEFAULT_RISK_PER_TRADE_PCT) FOR THIS FILE ONLY — justified because
     a credit spread's max loss is contractually fixed at entry (unlike
     an ATR stop, price cannot gap past the protective long strike), so
     the true risk is more precisely known than the 1% rule was
     originally designed around. This does NOT change
     backtest.py's DEFAULT_RISK_PER_TRADE_PCT, risk_filter.py, or any
     .env guardrail value — those stay locked at spec §4.1's 1% for
     every other strategy and for live enforcement. Scoped explicitly to
     defined-risk options structures, per instruction.

SIGNAL:
  - Short leg + long leg (protection): see REDESIGN #1 above —
    select_narrow_spread_strikes() replaces the original fixed-%-OTM
    select_spread_strikes() (removed, not left in as dead code — this is
    a full replacement of the strike-selection design, not an
    alternative kept alongside it).
  - Expiration: nearest (soonest) listed monthly expiry (3rd Friday —
    computed directly, not fetched, since standard equity index options
    settle monthly on the 3rd Friday) with DTE in [30, 45] from the
    entry date. In the ordinary case there is exactly one monthly expiry
    in a 15-day-wide band (consecutive monthlies are ~28-35 days apart),
    so "nearest" and "only" usually coincide; select_expiry() falls back
    to the nearest-outside-band candidate (flagged via a returned note)
    in the rare case none falls inside.
  - Continuous monthly rolling: a new cycle's entry date is the next SPY
    trading day strictly after the prior cycle's expiry, unconditionally
    — the calendar/cycle cadence advances every cycle regardless of
    whether that cycle actually got sized into a trade (see SIZING).
  - Held to expiration always, no early close (user instruction) — there
    is deliberately no monitoring/exit logic in this file at all.

CHAIN QUERYING: per CLAUDE.md Track C finding 2 (far-dated series list
progressively — today's active-contract list can silently omit contracts
that existed as of an earlier date), the strike ladder for each cycle is
fetched by querying that cycle's OWN target expiration_date directly
(fetch_option_contracts(), src/data_ingestion.py) — never from "today's"
chain. A contract's own metadata (strike, expiration) is static
regardless of when it's queried, so this sidesteps the progressive-
listing problem entirely rather than needing an explicit "as of" filter.

DATA-GAP FALLBACK (user instruction: log and use the nearest valid
date/strike rather than skip silently) — two independent fallback axes,
both logged per cycle:
  1. DATE: if a chosen contract has no bar on the exact entry date, the
     nearest available bar within OPTION_DATA_FALLBACK_MAX_DAYS is used
     instead (see nearest_bar_close()).
  2. STRIKE: since REDESIGN #1 selects strikes by narrowest-achievable-
     width rather than a fixed target, the "strike fallback" axis is now
     candidate iteration through select_narrow_spread_strikes()'s
     narrowest-first list — if the truly-narrowest candidate's legs lack
     usable data, the next-narrowest candidate is tried, and so on. Each
     cycle records candidate_rank (0 = narrowest available candidate had
     usable data; 1+ = that many narrower candidates were skipped for
     lack of data). Only if every candidate in the zone fails is the
     cycle skipped, logged "no_narrow_spread_with_data".

SIZING (user instruction: use spec §4.1's real formula, but at a
defined-risk-specific 2% rather than the global 1% — see REDESIGN #2
above). risk_amount = equity * PCS_RISK_PER_TRADE_PCT (2%);
max_loss_per_contract = (spread width - credit received) * 100;
contracts = floor(risk_amount / max_loss_per_contract) — the position's
TOTAL max loss across however many contracts, not a per-contract cap,
matching spec §4.1's position-level convention (identical in spirit to
every other backtest's risk_amount / stop_distance formula). If
contracts < 1, the cycle is SKIPPED (no trade, equity unchanged, reason
"sizing_floor_zero") but the cycle CLOCK still advances (next entry =
day after this cycle's own expiry) — the cadence is calendar-anchored,
not trade-count-anchored, so a string of unsizable cycles doesn't stall
the simulation. Per instruction: if most cycles are STILL zero-sized
even after both redesign changes, that is reported plainly, not forced
to a non-zero number.

FLAGGED, NOT SILENTLY RESOLVED: unlike every other backtest in this
repo, sizing here is NOT fee/slippage-independent. Because slippage is
modeled as a reduction to entry credit (see FEES below), and credit
feeds directly into max_loss_per_contract, the net-of-cost and
gross-of-cost simulations can select a DIFFERENT contract count for the
same cycle (gross credit is higher, so gross max loss is lower, so more
contracts can fit the same risk budget) — occasionally even different
cycle PARTICIPATION (a cycle viable gross-of-cost but floored to zero
net-of-cost). main() reports this divergence explicitly rather than
letting the two "pooled trade count" numbers look independently clean
without explaining why they can differ.

FEES: commission-free (user instruction, $0/contract — Alpaca's
options product, same framing Track B used for ETFs) plus a slippage
JUDGMENT CALL, not a measured number (same epistemic status as every
other slippage placeholder in this repo — see backtest.py's
DEFAULT_SLIPPAGE_BPS docstring): PCS_SLIPPAGE_PER_LEG_DOLLARS ($0.10/
share = $10/contract per leg, applied only at ENTRY — both legs, credit
reduced by 2x this amount). No slippage is modeled at expiration:
expiring ITM legs settle/exercise automatically, there is no execution
crossing a spread the way a discretionary close would.

FOLDS: 2 anchored folds (user instruction) over
[2024-01-18, last available data date] — no separate initial-training
span (unlike GEM's 12-month lookback, nothing here needs indicator
warm-up: strike selection only needs that day's own spot price).
Reuses compute_fold_boundaries() (backtest_walkforward.py, called with
initial_train_days=0) and slice_trades_by_folds() (backtest_donchian.py)
completely unchanged — this strategy is single-position, strictly
sequential (never more than one spread open at a time), so entry order
and exit/equity-realization order are always identical, exactly the
assumption backtest_donchian.py's slicer (not the rotational ensemble's
exit-timestamp variant) already makes.

ADOPT BAR (user instruction, same shape as GEM's): pooled net-of-cost
positive AND both folds individually positive. Reported as raw facts,
no verdict self-rendered, same convention as every prior finding.

Buy-and-hold SPY over the same window is reported for context (CLAUDE.md
permanent requirement) via compute_buy_and_hold_symbol_return()
(backtest_donchian_ensemble.py), reused unchanged — it's already generic
over any series dict shaped {candles, date_index}.

Does NOT include the stress-test scenario overlay — see
scripts/stress_test_pcs.py, a deliberately separate script/report per
instruction ("don't blend it into the pooled backtest numbers").

Usage:
    python scripts/backtest_put_credit_spread.py
"""
import sys
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data_ingestion import fetch_historical_stock_candles, fetch_option_contracts, fetch_option_bars
from scripts.backtest import summarize, _print_table, DEFAULT_RISK_PER_TRADE_PCT
from scripts.backtest_donchian import slice_trades_by_folds
from scripts.backtest_walkforward import compute_fold_boundaries
from scripts.backtest_donchian_ensemble import PAPER_VALIDATION_CAPITAL, compute_buy_and_hold_symbol_return

UNDERLYING = "SPY"
# REDESIGN #1 (this session): narrowest-achievable width within a 2-4%
# OTM zone, replacing the original fixed 5%/8%-OTM target — see module
# docstring. NARROW_OTM_LOW/HIGH bound the zone the SHORT leg is drawn
# from; the long leg is whatever real strike is immediately below it.
NARROW_OTM_LOW = 0.02
NARROW_OTM_HIGH = 0.04
DTE_LOW = 30
DTE_HIGH = 45

# Confirmed real usable floor for SPY options bar data on this account
# (CLAUDE.md Track C finding 1) — NOT the ~2024-01-03 the contract-
# metadata search implies, that number is wrong for backtesting.
OPTIONS_DATA_FLOOR = date(2024, 1, 18)

# Judgment calls, both flagged in the module docstring — not measured facts.
PCS_SLIPPAGE_PER_LEG_DOLLARS = 0.10  # $/share = $10/contract per leg, entry only
PCS_COMMISSION_PER_CONTRACT = 0.0    # commission-free, per instruction

# REDESIGN #2 (this session): defined-risk-specific override of spec
# §4.1's global 1% — see module docstring's REDESIGN section for the
# justification and scope. Does NOT touch DEFAULT_RISK_PER_TRADE_PCT
# (backtest.py, spec §4.1's locked global figure) — imported here only
# for reference/comparison in diagnostics, not used for sizing.
PCS_RISK_PER_TRADE_PCT = 2.0

OPTION_DATA_FALLBACK_MAX_DAYS = 5

NUM_FOLDS = 2  # user instruction, same as GEM's Track A
THIN_CYCLE_THRESHOLD = 5


@dataclass
class PutCreditSpreadTrade:
    entry_index: int
    exit_index: int
    entry_timestamp: str
    exit_timestamp: str
    entry_price: float   # net credit received per share (this run's cost basis)
    exit_price: float    # spread value owed at expiration, per share (intrinsic, 0..width)
    exit_reason: str     # "expired_otm" | "expired_itm_partial" | "expired_itm_max_loss"
    gross_pnl: float
    fees_paid: float
    pnl: float            # net of slippage
    r_multiple: float
    short_strike: float
    long_strike: float
    contracts: int
    credit_per_share: float
    dte: int


def third_friday(year: int, month: int) -> date:
    """Standard equity-index monthly options expiry: the 3rd Friday of the month."""
    d = date(year, month, 1)
    days_to_friday = (4 - d.weekday()) % 7  # Monday=0 .. Friday=4
    first_friday = d + timedelta(days=days_to_friday)
    return first_friday + timedelta(days=14)


def _add_months(year: int, month: int, delta: int) -> tuple[int, int]:
    idx = (year * 12 + (month - 1)) + delta
    return idx // 12, idx % 12 + 1


def select_expiry(entry_date: date, dte_low: int = DTE_LOW, dte_high: int = DTE_HIGH):
    """
    Nearest (soonest) listed monthly expiry with DTE in [dte_low, dte_high]
    from entry_date. Searches 4 months of 3rd-Fridays ahead of entry_date
    — always enough headroom for a 45-day band. Returns (expiry_date, dte,
    note) — note is None in the ordinary case, or a flagged string if the
    band search found nothing inside the band (falls back to whichever
    candidate's DTE is closest to the band, still returned rather than
    raising, so a single unusual cycle doesn't halt the whole run).
    """
    candidates = [third_friday(*_add_months(entry_date.year, entry_date.month, delta)) for delta in range(4)]
    in_band = [(e, (e - entry_date).days) for e in candidates if dte_low <= (e - entry_date).days <= dte_high]
    if in_band:
        expiry, dte = min(in_band, key=lambda pair: pair[1])
        return expiry, dte, None

    positive = [(e, (e - entry_date).days) for e in candidates if (e - entry_date).days > 0]
    expiry, dte = min(positive, key=lambda pair: min(abs(pair[1] - dte_low), abs(pair[1] - dte_high)))
    return expiry, dte, f"dte_band_widened(actual_dte={dte})"


def select_narrow_spread_strikes(contracts, spot: float, otm_low: float = NARROW_OTM_LOW, otm_high: float = NARROW_OTM_HIGH):
    """
    REDESIGN #1 (this session, see module docstring): checks the REAL
    listed strike ladder for whichever short-leg location in the
    [otm_low, otm_high] OTM zone yields the SMALLEST achievable width to
    its own next-lower listed strike (the long leg) — not a fixed target
    width forced onto the chain. Every strike within the zone is a
    candidate; each candidate's width is its distance to its own
    immediate lower neighbor in the FULL chain (that neighbor need not
    itself be inside the zone). Returns a list of (short_contract,
    long_contract, width) tuples sorted narrowest-width-first, ties
    broken by proximity to the zone's own center — so the caller (see
    build_cycles()) can walk the list for a liquidity fallback without
    re-deriving strikes. Returns [] if no strike falls in the zone, or if
    every in-zone strike sits at the very bottom of the chain with
    nothing listed below it (both real, flagged possibilities, not
    silently defaulted).
    """
    sorted_contracts = sorted(contracts, key=lambda c: c.strike_price)
    zone_low = spot * (1 - otm_high)
    zone_high = spot * (1 - otm_low)
    zone_center = spot * (1 - (otm_low + otm_high) / 2)

    scored = []
    for i, c in enumerate(sorted_contracts):
        if not (zone_low <= c.strike_price <= zone_high):
            continue
        if i == 0:
            continue  # nothing listed below this strike -- can't form a spread here
        lower = sorted_contracts[i - 1]
        width = c.strike_price - lower.strike_price
        scored.append((width, abs(c.strike_price - zone_center), c, lower))

    scored.sort(key=lambda t: (t[0], t[1]))
    return [(short, long, width) for width, _, short, long in scored]


def nearest_bar_close(bars, target_date: date, max_days: int = OPTION_DATA_FALLBACK_MAX_DAYS):
    """
    Close price on target_date if a bar exists there; otherwise the
    nearest available bar within max_days (either direction). Returns
    (close, used_date, distance_days) or (None, None, None) if nothing
    usable exists within the window. See module docstring's DATA-GAP
    FALLBACK section.
    """
    if not bars:
        return None, None, None
    by_date = {b.timestamp[:10]: b for b in bars}
    target_str = target_date.isoformat()
    if target_str in by_date:
        return by_date[target_str].close, target_date, 0
    nearest_str = min(by_date.keys(), key=lambda d: abs((date.fromisoformat(d) - target_date).days))
    distance = abs((date.fromisoformat(nearest_str) - target_date).days)
    if distance > max_days:
        return None, None, None
    return by_date[nearest_str].close, date.fromisoformat(nearest_str), distance


def _leg_bar_close(contract, entry_date, option_bar_cache):
    """
    Fetches/caches one specific contract's bars around entry_date and
    returns its nearest usable close (see nearest_bar_close()) — used by
    build_cycles() to test ONE candidate spread (short, long) from
    select_narrow_spread_strikes()'s narrowest-first list; the STRIKE
    fallback axis is candidate iteration in the caller, not a search
    inside this function (unlike the original design's
    _select_leg_with_data(), removed — see module docstring's REDESIGN).
    """
    if contract.symbol not in option_bar_cache:
        window_start = datetime.combine(entry_date - timedelta(days=OPTION_DATA_FALLBACK_MAX_DAYS), datetime.min.time(), tzinfo=timezone.utc)
        window_end = datetime.combine(entry_date + timedelta(days=OPTION_DATA_FALLBACK_MAX_DAYS), datetime.min.time(), tzinfo=timezone.utc)
        option_bar_cache[contract.symbol] = fetch_option_bars(contract.symbol, window_start, window_end)
    return nearest_bar_close(option_bar_cache[contract.symbol], entry_date)


def build_symbol_series(symbol, start, end):
    """SPY's own daily history (RAW — nominal traded price, matching real strike levels, same reasoning Track B used) and a date-string -> index map."""
    candles = fetch_historical_stock_candles(symbol, start, end)
    if not candles:
        return None
    date_index = {c.timestamp[:10]: i for i, c in enumerate(candles)}
    return {"symbol": symbol, "candles": candles, "date_index": date_index}


def build_cycles(spy_series, window_start: date, window_end: date):
    """
    Walks the continuous monthly-rolling cycle sequence from window_start
    through window_end, fetching real chain/bar data for each cycle. A
    cycle is only added once BOTH its entry-side option data resolves
    (with fallback — see module docstring) AND its own expiry date is
    <= the last available SPY trading date (so the payoff is always
    computable from real data, never estimated) — a cycle whose expiry
    would fall beyond available data is not started at all, not
    half-simulated.

    Returns (cycles, skip_log). Each cycle dict carries every raw input
    simulate_from_cycles() needs (spot, strikes, symbols, entry credit,
    expiry-date underlying close) plus fallback/note fields for the
    report — no P&L or sizing decision is made here, that's
    simulate_from_cycles()'s job (separating data-fetch from arithmetic,
    same pattern build_symbol_series()/simulate() split use elsewhere).
    """
    spy_dates = sorted(spy_series["date_index"].keys())
    last_available = spy_dates[-1]

    cycles = []
    skip_log = []
    option_bar_cache = {}
    contracts_cache = {}

    entry_idx = bisect_left(spy_dates, window_start.isoformat())
    cycle_num = 0

    while entry_idx < len(spy_dates):
        entry_date_str = spy_dates[entry_idx]
        entry_date = date.fromisoformat(entry_date_str)
        if entry_date > window_end:
            break

        expiry_date, dte, band_note = select_expiry(entry_date)
        if expiry_date.isoformat() > last_available:
            break  # can't resolve this cycle from real data — stop here, don't half-simulate

        spot = spy_series["candles"][spy_series["date_index"][entry_date_str]].close

        if expiry_date not in contracts_cache:
            contracts_cache[expiry_date] = fetch_option_contracts(UNDERLYING, expiry_date.isoformat(), option_type="put")
        contracts = contracts_cache[expiry_date]
        if not contracts:
            skip_log.append({"cycle": cycle_num, "entry_date": entry_date_str, "expiry": expiry_date.isoformat(), "reason": "no_contracts_for_expiry"})
            entry_idx = bisect_right(spy_dates, expiry_date.isoformat())
            cycle_num += 1
            continue

        # REDESIGN #1: narrowest-achievable-width candidates within the
        # 2-4% OTM zone, real chain, sorted narrowest-first. See module
        # docstring — the strike FALLBACK axis is now walking this list,
        # not a target-based nearest search.
        candidates = select_narrow_spread_strikes(contracts, spot)
        if not candidates:
            skip_log.append({"cycle": cycle_num, "entry_date": entry_date_str, "expiry": expiry_date.isoformat(), "reason": "no_strikes_in_otm_zone"})
            entry_idx = bisect_right(spy_dates, expiry_date.isoformat())
            cycle_num += 1
            continue

        chosen = None
        for candidate_rank, (short_c, long_c, width) in enumerate(candidates):
            short_close, short_used_date, short_dist = _leg_bar_close(short_c, entry_date, option_bar_cache)
            if short_close is None:
                continue
            long_close, long_used_date, long_dist = _leg_bar_close(long_c, entry_date, option_bar_cache)
            if long_close is None:
                continue
            chosen = (short_c, long_c, width, candidate_rank, short_close, short_used_date, short_dist, long_close, long_used_date, long_dist)
            break

        if chosen is None:
            skip_log.append({"cycle": cycle_num, "entry_date": entry_date_str, "expiry": expiry_date.isoformat(), "reason": "no_narrow_spread_with_data", "candidates_checked": len(candidates)})
            entry_idx = bisect_right(spy_dates, expiry_date.isoformat())
            cycle_num += 1
            continue

        short_contract, long_contract, width, candidate_rank, short_close, short_used_date, short_dist, long_close, long_used_date, long_dist = chosen

        # Expiration payoff needs ONLY the underlying's real close — no option data (see module docstring).
        expiry_idx = spy_series["date_index"].get(expiry_date.isoformat())
        if expiry_idx is None:
            nearby = [d for d in spy_dates if abs((date.fromisoformat(d) - expiry_date).days) <= OPTION_DATA_FALLBACK_MAX_DAYS]
            if not nearby:
                skip_log.append({"cycle": cycle_num, "entry_date": entry_date_str, "expiry": expiry_date.isoformat(), "reason": "no_spy_data_at_expiry"})
                entry_idx = bisect_right(spy_dates, expiry_date.isoformat())
                cycle_num += 1
                continue
            expiry_used_date = min(nearby, key=lambda d: abs((date.fromisoformat(d) - expiry_date).days))
        else:
            expiry_used_date = expiry_date.isoformat()
        spy_close_at_expiry = spy_series["candles"][spy_series["date_index"][expiry_used_date]].close

        cycles.append({
            "cycle_index": cycle_num,
            "entry_date": entry_date_str,
            "expiry_date": expiry_date.isoformat(),
            "expiry_used_date": expiry_used_date,
            "dte": dte,
            "dte_band_note": band_note,
            "spot_at_entry": spot,
            "short_strike": short_contract.strike_price,
            "long_strike": long_contract.strike_price,
            "width": width,
            "candidate_rank": candidate_rank,  # 0 = narrowest in-zone candidate had usable data; N = N narrower candidates were skipped for lack of data
            "short_symbol": short_contract.symbol,
            "long_symbol": long_contract.symbol,
            "credit_gross_per_share": short_close - long_close,
            "short_date_distance": short_dist,
            "long_date_distance": long_dist,
            "spy_close_at_expiry": spy_close_at_expiry,
        })
        cycle_num += 1
        entry_idx = bisect_right(spy_dates, expiry_date.isoformat())

    return cycles, skip_log


def simulate_from_cycles(
    cycles, spy_series, capital=PAPER_VALIDATION_CAPITAL, risk_pct=PCS_RISK_PER_TRADE_PCT,
    slippage_per_leg_dollars=PCS_SLIPPAGE_PER_LEG_DOLLARS,
):
    """
    Pure arithmetic over already-fetched `cycles` (see build_cycles()) —
    no I/O. Sizes each cycle independently off the CURRENT compounding
    equity (same convention as every other backtest here), skipping and
    logging any cycle that can't clear a >=1-contract size under the
    risk budget (PCS_RISK_PER_TRADE_PCT, 2% — REDESIGN #2, see module
    docstring) or that has non-positive/nonsensical credit. See module
    docstring's SIZING and FLAGGED sections for why sizing (and therefore
    which cycles even become trades) can differ between a net-of-cost and
    gross-of-cost call.

    Returns (trades, equity_curve, skipped_log).
    """
    trades = []
    equity = capital
    equity_curve = [equity]
    skipped_log = []

    for cycle in cycles:
        credit_per_share = cycle["credit_gross_per_share"] - 2 * slippage_per_leg_dollars
        width = cycle["short_strike"] - cycle["long_strike"]

        if credit_per_share <= 0:
            skipped_log.append({"cycle": cycle["cycle_index"], "entry_date": cycle["entry_date"], "reason": "non_positive_credit"})
            continue

        max_loss_per_contract = (width - credit_per_share) * 100
        if max_loss_per_contract <= 0:
            skipped_log.append({"cycle": cycle["cycle_index"], "entry_date": cycle["entry_date"], "reason": "non_positive_max_loss"})
            continue

        risk_amount = equity * (risk_pct / 100)
        contracts = int(risk_amount // max_loss_per_contract)
        if contracts < 1:
            skipped_log.append({
                "cycle": cycle["cycle_index"], "entry_date": cycle["entry_date"], "reason": "sizing_floor_zero",
                "risk_amount": risk_amount, "max_loss_per_contract": max_loss_per_contract,
            })
            continue

        spy_exit = cycle["spy_close_at_expiry"]
        short_intrinsic = max(cycle["short_strike"] - spy_exit, 0.0)
        long_intrinsic = max(cycle["long_strike"] - spy_exit, 0.0)
        spread_value_at_exp = short_intrinsic - long_intrinsic  # per share, bounded [0, width]

        if short_intrinsic == 0:
            exit_reason = "expired_otm"
        elif spread_value_at_exp >= width:
            exit_reason = "expired_itm_max_loss"
        else:
            exit_reason = "expired_itm_partial"

        net_pnl_per_share = credit_per_share - spread_value_at_exp
        pnl = net_pnl_per_share * 100 * contracts
        fees_paid = 2 * slippage_per_leg_dollars * 100 * contracts + PCS_COMMISSION_PER_CONTRACT * contracts
        gross_pnl = pnl + fees_paid  # what this SAME contract count earns absent slippage/commission

        equity += pnl
        equity_curve.append(equity)

        entry_idx = spy_series["date_index"][cycle["entry_date"]]
        exit_idx = spy_series["date_index"][cycle["expiry_used_date"]]

        trades.append(PutCreditSpreadTrade(
            entry_index=entry_idx,
            exit_index=exit_idx,
            entry_timestamp=spy_series["candles"][entry_idx].timestamp,
            exit_timestamp=spy_series["candles"][exit_idx].timestamp,
            entry_price=credit_per_share,
            exit_price=spread_value_at_exp,
            exit_reason=exit_reason,
            gross_pnl=gross_pnl,
            fees_paid=fees_paid,
            pnl=pnl,
            r_multiple=pnl / risk_amount if risk_amount else 0.0,
            short_strike=cycle["short_strike"],
            long_strike=cycle["long_strike"],
            contracts=contracts,
            credit_per_share=credit_per_share,
            dte=cycle["dte"],
        ))

    return trades, equity_curve, skipped_log


def main():
    end = datetime.now(timezone.utc) - timedelta(minutes=20)
    start = datetime(2016, 1, 4, tzinfo=timezone.utc)  # equity-data floor — see Track B/A, fetched wide so buy-and-hold context isn't clipped

    print(f"=== Track C: SPY put credit spread (narrowest-achievable width in {NARROW_OTM_LOW*100:.0f}-{NARROW_OTM_HIGH*100:.0f}% OTM zone, 30-45 DTE monthly rolling, real-data-only entry+expiration, {PCS_RISK_PER_TRADE_PCT:.0f}% defined-risk sizing) ===")
    print(f"(REDESIGN this session vs. the first run: strike zone 5%/8% OTM -> narrowest-achievable in {NARROW_OTM_LOW*100:.0f}-{NARROW_OTM_HIGH*100:.0f}% OTM; sizing spec §4.1's global {DEFAULT_RISK_PER_TRADE_PCT:.0f}% -> a defined-risk-specific {PCS_RISK_PER_TRADE_PCT:.0f}% override, THIS FILE ONLY — see module docstring)")
    spy_series = build_symbol_series(UNDERLYING, start, end)
    if spy_series is None:
        print("SPY: no candle data returned")
        return
    print(f"SPY daily history: {spy_series['candles'][0].timestamp[:10]} -> {spy_series['candles'][-1].timestamp[:10]} ({len(spy_series['candles'])} candles, RAW/unadjusted)")

    window_end = date.fromisoformat(spy_series["candles"][-1].timestamp[:10])
    print(f"options backtest window (requested): {OPTIONS_DATA_FLOOR} -> {window_end}  (floor per CLAUDE.md Track C finding 1)")
    print(f"(fee model: ${PCS_COMMISSION_PER_CONTRACT:.2f}/contract commission + ${PCS_SLIPPAGE_PER_LEG_DOLLARS:.2f}/share slippage per leg, entry only — judgment call, see module docstring)")

    cycles, cycle_skip_log = build_cycles(spy_series, OPTIONS_DATA_FLOOR, window_end)
    print(f"\n{len(cycles)} cycles built, {len(cycle_skip_log)} cycles skipped at data-fetch stage")
    if cycle_skip_log:
        by_reason = {}
        for s in cycle_skip_log:
            by_reason[s["reason"]] = by_reason.get(s["reason"], 0) + 1
        print("  data-fetch skip reasons:", ", ".join(f"{r}={c}" for r, c in sorted(by_reason.items(), key=lambda kv: -kv[1])))

    if not cycles:
        print("No cycles were built — cannot run the backtest.")
        return

    widths = [c["width"] for c in cycles]
    print(f"\nachievable spread width (real chain, narrowest candidate with usable data — NOT a forced target): min=${min(widths):.2f}, mean=${sum(widths) / len(widths):.2f}, max=${max(widths):.2f}")
    not_narrowest = [c for c in cycles if c["candidate_rank"] > 0]
    if not_narrowest:
        print(f"cycles where the truly-narrowest in-zone candidate lacked usable data, forcing a wider fallback candidate: {len(not_narrowest)}/{len(cycles)} (mean candidate_rank skipped: {sum(c['candidate_rank'] for c in not_narrowest) / len(not_narrowest):.1f})")
    fallback_date = [c for c in cycles if c["short_date_distance"] or c["long_date_distance"]]
    print(f"cycles using a date-fallback (nearest available bar, not the exact entry date) on either leg: {len(fallback_date)}/{len(cycles)}")
    widened = [c for c in cycles if c["dte_band_note"]]
    if widened:
        print(f"cycles where the 30-45 DTE band search found nothing inside and was widened: {len(widened)}/{len(cycles)}")

    actual_start = datetime.fromisoformat(cycles[0]["entry_date"]).replace(tzinfo=timezone.utc)
    actual_end = datetime.fromisoformat(cycles[-1]["expiry_used_date"]).replace(tzinfo=timezone.utc)
    folds = compute_fold_boundaries(actual_start, actual_end, num_folds=NUM_FOLDS, initial_train_days=0)
    print(f"\nfold boundaries ({NUM_FOLDS} folds, no separate training span):")
    for fold in folds:
        print(f"  fold {fold['fold']}: test {fold['test_start'].date()} -> {fold['test_end'].date()}")

    net_trades, net_curve, net_skipped = simulate_from_cycles(cycles, spy_series, slippage_per_leg_dollars=PCS_SLIPPAGE_PER_LEG_DOLLARS)
    gross_trades, gross_curve, gross_skipped = simulate_from_cycles(cycles, spy_series, slippage_per_leg_dollars=0.0)

    net_folds, net_pooled = slice_trades_by_folds(net_trades, net_curve, folds, PAPER_VALIDATION_CAPITAL)
    gross_folds, gross_pooled = slice_trades_by_folds(gross_trades, gross_curve, folds, PAPER_VALIDATION_CAPITAL)

    # Sizing/participation diagnostics — see module docstring's FLAGGED section:
    # net and gross runs can size (and therefore trade-or-skip) the same cycle differently.
    net_sized_cycles = {t.entry_index for t in net_trades}
    gross_sized_cycles = {t.entry_index for t in gross_trades}
    only_gross = gross_sized_cycles - net_sized_cycles
    net_zero_sizing = [s for s in net_skipped if s["reason"] == "sizing_floor_zero"]
    gross_zero_sizing = [s for s in gross_skipped if s["reason"] == "sizing_floor_zero"]
    print(f"\n=== Sizing diagnostics ({PCS_RISK_PER_TRADE_PCT:.0f}% of equity, defined-risk override — see module docstring; NOT spec §4.1's global {DEFAULT_RISK_PER_TRADE_PCT:.0f}%) ===")
    print(f"cycles sized into a real trade: net-of-cost {len(net_trades)}/{len(cycles)}, gross-of-cost {len(gross_trades)}/{len(cycles)}")
    print(f"cycles skipped for zero-sizing (risk budget < 1 contract's max loss): net-of-cost {len(net_zero_sizing)}, gross-of-cost {len(gross_zero_sizing)}")
    if len(only_gross) > 0:
        print(f"NOTE: {len(only_gross)} cycle(s) were sized gross-of-cost but floored to zero net-of-cost — sizing itself, not just P&L, differs between the two runs (see module docstring).")
    if net_trades:
        contract_counts = [t.contracts for t in net_trades]
        print(f"net-of-cost contracts per trade: min={min(contract_counts)}, mean={sum(contract_counts) / len(contract_counts):.2f}, max={max(contract_counts)}")
    else:
        print("net-of-cost contracts per trade: n/a — 0 trades sized (reported plainly, not forced to a non-zero number, per instruction).")

    print(f"\n=== Portfolio-level results ({len(net_trades)} net trades / {len(cycles)} cycles) ===")
    rows = []
    for fold, net, gross in zip(folds, net_folds, gross_folds):
        rows.append({
            "fold": fold["fold"],
            "test_window": f"{fold['test_start'].date()}..{fold['test_end'].date()}",
            "n": net["trade_count"],
            "flag": "THIN" if net["trade_count"] < THIN_CYCLE_THRESHOLD else "",
            "win%": f"{net['win_rate_pct']:.1f}",
            "net%": f"{net['total_return_pct']:.2f}",
            "gross%": f"{gross['total_return_pct']:.2f}",
            "max_dd%": f"{net['max_drawdown_pct']:.2f}",
        })
    rows.append({
        "fold": "POOLED",
        "test_window": f"{folds[0]['test_start'].date()}..{folds[-1]['test_end'].date()}",
        "n": net_pooled["trade_count"],
        "flag": "THIN" if net_pooled["trade_count"] < THIN_CYCLE_THRESHOLD else "",
        "win%": f"{net_pooled['win_rate_pct']:.1f}",
        "net%": f"{net_pooled['total_return_pct']:.2f}",
        "gross%": f"{gross_pooled['total_return_pct']:.2f}",
        "max_dd%": f"{net_pooled['max_drawdown_pct']:.2f}",
    })
    _print_table(rows, [
        ("fold", "fold"), ("test_window", "test_window"),
        ("n", "n"), ("flag", "flag"), ("win%", "win%"), ("net%", "net%"), ("gross%", "gross%"), ("max_dd%", "max_dd%"),
    ])
    thin_folds = [r["fold"] for r in rows if r["flag"] == "THIN"]
    if thin_folds:
        print(f"WARNING: fold(s) {thin_folds} have fewer than {THIN_CYCLE_THRESHOLD} trades — read as thin/inconclusive, not clean pass/fail evidence.")

    print(f"\nraw facts vs. the pre-committed bar (pooled net-of-cost positive AND both folds individually positive):")
    for i, fold in enumerate(folds):
        print(f"  fold {fold['fold']} net-of-cost: {'positive' if net_folds[i]['total_return_pct'] > 0 else 'negative/zero'} ({net_folds[i]['total_return_pct']:.2f}%)")
    print(f"  pooled net-of-cost: {'positive' if net_pooled['total_return_pct'] > 0 else 'negative/zero'} ({net_pooled['total_return_pct']:.2f}%)")

    # Mandatory buy-and-hold comparison (CLAUDE.md permanent requirement).
    print(f"\n=== Buy-and-hold SPY benchmark (same window) ===")
    bh_rows = []
    for fold in folds:
        test_start_date = fold["test_start"].date().isoformat()
        test_end_date = fold["test_end"].date().isoformat()
        bh = compute_buy_and_hold_symbol_return(spy_series, test_start_date, test_end_date)
        bh_rows.append({"fold": fold["fold"], "test_window": f"{test_start_date}..{test_end_date}", "bh_spy%": f"{bh:.2f}" if bh is not None else "n/a"})
    pooled_start = folds[0]["test_start"].date().isoformat()
    pooled_end = folds[-1]["test_end"].date().isoformat()
    bh_pooled = compute_buy_and_hold_symbol_return(spy_series, pooled_start, pooled_end)
    bh_rows.append({"fold": "POOLED", "test_window": f"{pooled_start}..{pooled_end}", "bh_spy%": f"{bh_pooled:.2f}" if bh_pooled is not None else "n/a"})
    _print_table(bh_rows, [("fold", "fold"), ("test_window", "test_window"), ("bh_spy%", "bh_spy%")])
    print(f"\nstrategy pooled net-of-cost {net_pooled['total_return_pct']:.2f}%  vs.  buy-and-hold SPY {bh_pooled:.2f}%" if bh_pooled is not None else "\nbuy-and-hold SPY: n/a")

    print(f"\n=== Cycle detail (entry, expiry, strikes, credit, contracts, exit, net pnl) ===")
    _print_table(
        [{
            "entry": t.entry_timestamp[:10],
            "expiry": t.exit_timestamp[:10],
            "dte": t.dte,
            "short_K": f"{t.short_strike:.0f}",
            "long_K": f"{t.long_strike:.0f}",
            "credit": f"${t.credit_per_share:.2f}",
            "contracts": t.contracts,
            "exit": t.exit_reason,
            "net_pnl": f"${t.pnl:.2f}",
        } for t in net_trades],
        [
            ("entry", "entry"), ("expiry", "expiry"), ("dte", "dte"), ("short_K", "short_K"), ("long_K", "long_K"),
            ("credit", "credit"), ("contracts", "contracts"), ("exit", "exit"), ("net_pnl", "net_pnl"),
        ],
    )

    if net_skipped:
        print(f"\nskipped cycles at simulation stage (net-of-cost run), {len(net_skipped)} total:")
        by_reason = {}
        for s in net_skipped:
            by_reason[s["reason"]] = by_reason.get(s["reason"], 0) + 1
        print("  by reason:", ", ".join(f"{r}={c}" for r, c in sorted(by_reason.items(), key=lambda kv: -kv[1])))


if __name__ == "__main__":
    main()
