"""
Verifies scripts/backtest_sector_rotation.py (DMSR — Dual Momentum Sector
Rotation, Track C candidate, spec v50 §10.20). All pure-logic tests
against hand-built synthetic daily candles / symbol_data dicts — no
network calls.

Covered: month-end-to-month-end trailing return, rank ordering + tie
break, the market absolute-momentum filter (SPY<0 -> 100% AGG), the
top-5 hysteresis guard (keep held names at rank 4/5, drop at rank 6),
the "trade only on composition change" rule (no legs / no cost when the
held set is unchanged), per-leg transaction cost application, risk-off
transition, the monthly-return series (partial stub month excluded), and
the Sharpe / CAGR / max-drawdown helpers.
"""
import math

from src.data_ingestion import Candle
from scripts.backtest_sector_rotation import (
    SECTOR_UNIVERSE,
    trailing_return,
    rank_sectors,
    select_target_holdings,
    simulate,
    bil_monthly_returns,
    annualized_sharpe,
    cagr,
    summarize_run,
)
from scripts.backtest_gem import compute_month_end_dates, compute_shared_calendar, compute_max_drawdown_pct


def _series(symbol, dated_closes):
    """dated_closes: list of (date_str, close). Builds a symbol_data-style dict."""
    candles = [
        Candle(symbol, f"{d}T00:00:00+00:00", open=c, high=c, low=c, close=c, volume=1000)
        for d, c in dated_closes
    ]
    return {"symbol": symbol, "candles": candles, "date_index": {c.timestamp[:10]: i for i, c in enumerate(candles)}}


# --- trailing_return ------------------------------------------------------

def test_trailing_return_is_month_end_to_month_end():
    me = ["2020-01-31", "2020-02-28", "2020-03-31", "2020-04-30"]
    s = _series("XLK", [("2020-01-31", 100.0), ("2020-02-28", 110.0), ("2020-03-31", 90.0), ("2020-04-30", 120.0)])
    # lookback 2, t=2 -> compares 2020-03-31 (90) vs 2020-01-31 (100)
    assert trailing_return(s, me, 2, 2) == (90.0 - 100.0) / 100.0
    # lookback 3, t=3 -> 2020-04-30 (120) vs 2020-01-31 (100)
    assert trailing_return(s, me, 3, 3) == 0.20


# --- rank_sectors --------------------------------------------------------

def _flat_month_ends():
    return ["2019-11-29", "2019-12-31", "2020-01-31", "2020-02-28", "2020-03-31"]


def _sector_data(returns_at_t2):
    """
    Build 11 sector series so that trailing_return(., me, t=2, lookback=2)
    equals the given per-symbol fraction. me[0] close = 100 for all;
    me[2] close = 100*(1+r).
    """
    me = _flat_month_ends()
    data = {}
    for sym in SECTOR_UNIVERSE:
        r = returns_at_t2[sym]
        closes = [
            (me[0], 100.0), (me[1], 100.0),
            (me[2], 100.0 * (1 + r)),
            (me[3], 100.0 * (1 + r)), (me[4], 100.0 * (1 + r)),
        ]
        data[sym] = _series(sym, closes)
    return data, me


def test_rank_sectors_orders_by_trailing_return_desc_with_ticker_tiebreak():
    rets = {s: 0.0 for s in SECTOR_UNIVERSE}
    rets["XLE"] = 0.30
    rets["XLK"] = 0.20
    rets["XLV"] = 0.20  # tie with XLK -> XLK first alphabetically
    data, me = _sector_data(rets)
    ranked = rank_sectors(data, me, 2, 2)
    order = [s for s, _ in ranked]
    assert order[0] == "XLE"
    assert order[1] == "XLK" and order[2] == "XLV"  # deterministic tie-break by ticker


# --- select_target_holdings -------------------------------------------------

def _ranked(order):
    """Fake rank_sectors output from a bare symbol order (returns unused by select_target_holdings except for ordering)."""
    return [(s, float(len(order) - i)) for i, s in enumerate(order)]


def test_market_filter_forces_100pct_agg_when_spy_negative():
    order = ["XLK", "XLV", "XLE", "XLF", "XLY", "XLP", "XLU", "XLI", "XLB", "XLRE", "XLC"]
    target, risk_off = select_target_holdings(["XLK", "XLV", "XLE"], _ranked(order), spy_return=-0.01)
    assert risk_off is True
    assert target == ["AGG"]


def test_first_deployment_takes_top_3():
    order = ["XLK", "XLV", "XLE", "XLF", "XLY", "XLP", "XLU", "XLI", "XLB", "XLRE", "XLC"]
    target, risk_off = select_target_holdings([], _ranked(order), spy_return=0.05)
    assert risk_off is False
    assert target == ["XLK", "XLV", "XLE"]


def test_hysteresis_keeps_held_name_sitting_at_rank_4_or_5():
    # Held: XLK, XLV, XLE. New ranking: XLE slipped to rank 5 (still top-5) -> kept.
    order = ["XLF", "XLK", "XLV", "XLY", "XLE", "XLP", "XLU", "XLI", "XLB", "XLRE", "XLC"]
    target, _ = select_target_holdings(["XLK", "XLV", "XLE"], _ranked(order), spy_return=0.05)
    assert set(target) == {"XLK", "XLV", "XLE"}  # XLF (rank 1) NOT bought — XLE kept at rank 5


def test_hysteresis_sells_held_name_that_falls_out_of_top_5():
    # XLE slipped to rank 6 -> sold; highest-ranked non-held (XLF) takes the slot.
    order = ["XLF", "XLK", "XLV", "XLY", "XLP", "XLE", "XLU", "XLI", "XLB", "XLRE", "XLC"]
    target, _ = select_target_holdings(["XLK", "XLV", "XLE"], _ranked(order), spy_return=0.05)
    assert "XLE" not in target
    assert set(target) == {"XLK", "XLV", "XLF"}


def test_risk_off_to_risk_on_takes_fresh_top_3_no_hysteresis_carry():
    order = ["XLE", "XLB", "XLI", "XLK", "XLV", "XLF", "XLY", "XLP", "XLU", "XLRE", "XLC"]
    target, risk_off = select_target_holdings(["AGG"], _ranked(order), spy_return=0.05)
    assert risk_off is False
    assert target == ["XLE", "XLB", "XLI"]


# --- simulate: composition-change-only trading + cost ---------------------

def _daily_calendar(month_ends):
    """2 trading days per month: the month-end, plus the 1st-of-next-month exec day."""
    cal = []
    for me in month_ends:
        cal.append(me)
        y, m, _ = me.split("-")
        nm = f"{y}-{m}-15"  # a mid-next-ish placeholder is wrong; use first-of-next-month
        cal.append(nm)
    return cal


def _build_two_day_month_calendar(pairs):
    """pairs: list of (month_end_date, next_trading_day). Returns a flat sorted calendar."""
    cal = []
    for me, nx in pairs:
        cal += [me, nx]
    return sorted(cal)


def _const_series(symbol, calendar, close):
    return _series(symbol, [(d, close) for d in calendar])


def test_simulate_no_trades_when_composition_unchanged():
    pairs = [
        ("2019-11-29", "2019-12-02"), ("2019-12-31", "2020-01-02"),
        ("2020-01-31", "2020-02-03"), ("2020-02-28", "2020-03-02"),
        ("2020-03-31", "2020-04-01"), ("2020-04-30", "2020-05-01"),
        ("2020-05-29", "2020-06-01"), ("2020-06-30", "2020-07-01"),
    ]
    cal = _build_two_day_month_calendar(pairs)
    me = compute_month_end_dates(cal)

    # SPY always up; XLK/XLV/XLE always the top 3, everyone else flat.
    symbol_data = {}
    for s in SECTOR_UNIVERSE:
        symbol_data[s] = _const_series(s, cal, 100.0)
    for s in ["XLK", "XLV", "XLE"]:
        symbol_data[s] = _series(s, [(d, 100.0 + 50.0 * i) for i, d in enumerate(cal)])  # steadily rising -> always top 3
    symbol_data["SPY"] = _series("SPY", [(d, 100.0 + i) for i, d in enumerate(cal)])
    symbol_data["AGG"] = _const_series("AGG", cal, 100.0)
    symbol_data["BIL"] = _const_series("BIL", cal, 100.0)

    run = simulate(symbol_data, cal, me, lookback=2, capital=10000.0, cost_pct=0.10)

    action_events = [e for e in run.events if e.legs > 0]
    assert len(action_events) == 1  # only the very first deployment trades
    assert set(action_events[0].bought) == {"XLK", "XLV", "XLE"}
    assert sum(e.cost for e in run.events[1:]) == 0.0  # nothing after deployment


def test_simulate_applies_per_leg_transaction_cost_on_first_deployment():
    pairs = [
        ("2019-11-29", "2019-12-02"), ("2019-12-31", "2020-01-02"),
        ("2020-01-31", "2020-02-03"), ("2020-02-28", "2020-03-02"),
    ]
    cal = _build_two_day_month_calendar(pairs)
    me = compute_month_end_dates(cal)
    symbol_data = {s: _const_series(s, cal, 100.0) for s in SECTOR_UNIVERSE}
    for s in ["XLK", "XLV", "XLE"]:
        symbol_data[s] = _series(s, [(d, 100.0 + 10.0 * i) for i, d in enumerate(cal)])
    symbol_data["SPY"] = _series("SPY", [(d, 100.0 + i) for i, d in enumerate(cal)])
    symbol_data["AGG"] = _const_series("AGG", cal, 100.0)
    symbol_data["BIL"] = _const_series("BIL", cal, 100.0)

    run = simulate(symbol_data, cal, me, lookback=2, capital=9000.0, cost_pct=0.10)
    first = run.events[0]
    # 3 legs, each buying $3000 notional, 0.10% each => $3.00 per leg, $9.00 total.
    assert first.legs == 3
    assert abs(first.cost - 9.0) < 1e-9
    assert abs(first.equity_after - (9000.0 - 9.0)) < 1e-6


def test_simulate_risk_off_moves_fully_to_agg_and_costs_four_legs():
    pairs = [
        ("2019-11-29", "2019-12-02"), ("2019-12-31", "2020-01-02"),
        ("2020-01-31", "2020-02-03"), ("2020-02-28", "2020-03-02"),
        ("2020-03-31", "2020-04-01"),
    ]
    cal = _build_two_day_month_calendar(pairs)
    me = compute_month_end_dates(cal)

    symbol_data = {s: _const_series(s, cal, 100.0) for s in SECTOR_UNIVERSE}
    for s in ["XLK", "XLV", "XLE"]:
        symbol_data[s] = _series(s, [(d, 100.0 + 5.0 * i) for i, d in enumerate(cal)])
    # SPY: rising until the last eval, then a 12-mo (== 2 month-end) drop below zero.
    spy_closes = {
        "2019-11-29": 100.0, "2019-12-02": 100.0,
        "2019-12-31": 110.0, "2020-01-02": 110.0,
        "2020-01-31": 120.0, "2020-02-03": 120.0,
        "2020-02-28": 130.0, "2020-03-02": 130.0,
        "2020-03-31": 90.0,  "2020-04-01": 90.0,  # vs 2020-01-31 (120) -> -25% -> risk off
    }
    symbol_data["SPY"] = _series("SPY", [(d, spy_closes[d]) for d in cal])
    symbol_data["AGG"] = _const_series("AGG", cal, 100.0)
    symbol_data["BIL"] = _const_series("BIL", cal, 100.0)

    run = simulate(symbol_data, cal, me, lookback=2, capital=10000.0, cost_pct=0.10)
    risk_off_events = [e for e in run.events if e.risk_off]
    assert len(risk_off_events) == 1
    ro = risk_off_events[0]
    assert ro.target == ["AGG"]
    assert set(ro.sold) == {"XLK", "XLV", "XLE"} and ro.bought == ["AGG"]
    assert ro.legs == 4


def test_monthly_returns_exclude_partial_stub_and_are_month_over_month():
    pairs = [
        ("2019-11-29", "2019-12-02"), ("2019-12-31", "2020-01-02"),
        ("2020-01-31", "2020-02-03"), ("2020-02-28", "2020-03-02"),
        ("2020-03-31", "2020-04-01"),
    ]
    cal = _build_two_day_month_calendar(pairs)
    me = compute_month_end_dates(cal)

    # Per-"period" prices (a period = a month-end + the next exec day share one price,
    # so signal and execution see the same value). P0..P4 map to the 5 pairs above.
    def period_series(symbol, p_values):
        vals = {}
        for (m_end, nxt), v in zip(pairs, p_values):
            vals[m_end] = v
            vals[nxt] = v
        return _series(symbol, [(d, vals[d]) for d in cal])

    symbol_data = {s: _const_series(s, cal, 100.0) for s in SECTOR_UNIVERSE}
    # XLV, XLE: rise into deployment, then flat. XLK: same, then doubles at the final month-end.
    symbol_data["XLV"] = period_series("XLV", [100, 100, 110, 110, 110])
    symbol_data["XLE"] = period_series("XLE", [100, 100, 110, 110, 110])
    symbol_data["XLK"] = period_series("XLK", [100, 100, 110, 110, 220])
    symbol_data["SPY"] = period_series("SPY", [100, 100, 105, 110, 110])  # positive trailing at every eval
    symbol_data["AGG"] = _const_series("AGG", cal, 100.0)
    symbol_data["BIL"] = _const_series("BIL", cal, 100.0)

    run = simulate(symbol_data, cal, me, lookback=2, capital=30000.0, cost_pct=0.0)
    # first_exec = 2020-02-03. month-ends in the curve: 2020-02-28, 2020-03-31.
    # The monthly series starts at the SECOND (2020-03-31) — the partial stub
    # 2020-02-03..2020-02-28 is excluded.
    assert [d for d, _ in run.monthly_returns] == ["2020-03-31"]
    # Held XLK/XLV/XLE equal-weight ($10k each at price 110). Over 2020-02-28 -> 2020-03-31
    # XLK 110 -> 220 (one third of the book doubles), XLV/XLE flat -> portfolio +1/3.
    assert abs(run.monthly_returns[0][1] - (1 / 3)) < 1e-9


# --- metric helpers ------------------------------------------------------

def test_annualized_sharpe_matches_hand_computation():
    monthly = [("2020-01-31", 0.02), ("2020-02-29", -0.01), ("2020-03-31", 0.03), ("2020-04-30", 0.01)]
    xs = [0.02, -0.01, 0.03, 0.01]
    mean = sum(xs) / len(xs)
    sd = math.sqrt(sum((x - mean) ** 2 for x in xs) / (len(xs) - 1))
    expected = mean / sd * math.sqrt(12)
    assert abs(annualized_sharpe(monthly, None) - expected) < 1e-12


def test_annualized_sharpe_subtracts_risk_free():
    monthly = [("2020-01-31", 0.02), ("2020-02-29", 0.02), ("2020-03-31", 0.02), ("2020-04-30", 0.02)]
    rf = {"2020-01-31": 0.01, "2020-02-29": 0.01, "2020-03-31": 0.01, "2020-04-30": 0.01}
    # constant excess return -> zero stdev -> defined as 0.0
    assert annualized_sharpe(monthly, rf) == 0.0


def test_cagr_and_max_drawdown():
    assert abs(cagr(100.0, 121.0, "2020-01-01", "2022-01-01") - 0.1) < 2e-3  # ~2 yrs, 21% total -> ~10%/yr
    assert abs(compute_max_drawdown_pct([100, 120, 90, 130]) - 25.0) < 1e-9  # 120 -> 90


def test_default_price_basis_is_split_adjusted(monkeypatch):
    # Forced deviation from the brief's literal "RAW, same as the Donchian
    # backtest": Adjustment.RAW injects a phantom ~50% one-day loss from
    # the 2025-12-05 SPDR 2:1 split on XLK/XLE/XLY/XLU/XLB. SPLIT-adjusted
    # keeps the dividend limitation the brief wants while fixing that.
    import sys as _sys
    from scripts.backtest_sector_rotation import parse_args
    monkeypatch.setattr(_sys, "argv", ["backtest_sector_rotation.py"])
    assert parse_args().adjustment == "split"


def test_bil_monthly_returns_keyed_by_month_end():
    me = ["2020-01-31", "2020-02-28", "2020-03-31"]
    bil = _series("BIL", [("2020-01-31", 100.0), ("2020-02-28", 100.1), ("2020-03-31", 100.2)])
    out = bil_monthly_returns(bil, me)
    assert set(out) == {"2020-02-28", "2020-03-31"}
    assert abs(out["2020-02-28"] - 0.001) < 1e-9
