"""
src/dmsr_signal.py (spec v59 §10.29, Milestone 4) — pure DMSR signal
logic for Track C. All tests against hand-built synthetic calendars /
symbol_data dicts, no network.

Covers: compute_month_end_dates (incl. a verbatim-port regression guard
against scripts/backtest_gem.py), is_rebalance_day (the self-gate —
including the flagged deviation from the brief's pasted helpers),
trailing_return / rank_sectors (values + ticker tie-break), and
select_target_holdings (risk-off filter, top-5 hysteresis keep, clean
top-3 swap).
"""
import pytest

from src import dmsr_signal
from src.data_ingestion import Candle
from scripts.backtest_gem import compute_month_end_dates as _gem_compute_month_end_dates


def _series(symbol, dated_closes):
    candles = [
        Candle(symbol, f"{d}T00:00:00+00:00", open=c, high=c, low=c, close=c, volume=1000)
        for d, c in dated_closes
    ]
    return {"symbol": symbol, "candles": candles, "date_index": {c.timestamp[:10]: i for i, c in enumerate(candles)}}


# 13 month-end dates — enough for one 12-month trailing return (t=12, t-12=0).
MONTH_ENDS_13 = [
    "2025-01-31", "2025-02-28", "2025-03-31", "2025-04-30", "2025-05-30", "2025-06-30",
    "2025-07-31", "2025-08-29", "2025-09-30", "2025-10-31", "2025-11-28", "2025-12-31", "2026-01-30",
]


# --- compute_month_end_dates -------------------------------------------

def test_compute_month_end_dates_identifies_last_trading_day_of_each_completed_month():
    cal = ["2026-01-29", "2026-01-30", "2026-02-02", "2026-02-27", "2026-03-02", "2026-03-31", "2026-04-01"]
    # 2026-01-30 (next day is Feb), 2026-02-27 (next is Mar), 2026-03-31 (next is Apr).
    # 2026-04-01 is the current in-progress month's only day -> excluded (no later date).
    assert dmsr_signal.compute_month_end_dates(cal) == ["2026-01-30", "2026-02-27", "2026-03-31"]


def test_compute_month_end_dates_is_verbatim_port_of_backtest_gem():
    for cal in (
        ["2026-01-29", "2026-01-30", "2026-02-02", "2026-03-31", "2026-04-01", "2026-04-30", "2026-05-01"],
        MONTH_ENDS_13 + ["2026-02-02"],
        [],
        ["2026-07-01"],
    ):
        assert dmsr_signal.compute_month_end_dates(cal) == _gem_compute_month_end_dates(cal)


# --- is_rebalance_day -------------------------------------------------

def test_is_rebalance_day_true_when_yesterday_was_a_month_end():
    cal = ["2026-06-26", "2026-06-29", "2026-06-30", "2026-07-01"]  # 06-30 month-end, 07-01 today
    assert dmsr_signal.is_rebalance_day(cal) is True


def test_is_rebalance_day_false_mid_month():
    cal = ["2026-07-01", "2026-07-02", "2026-07-03"]
    assert dmsr_signal.is_rebalance_day(cal) is False


def test_is_rebalance_day_checks_yesterday_specifically_not_just_any_month_end_in_the_window():
    # 2026-06-30 IS a month-end but it is calendar[-3], not calendar[-2].
    cal = ["2026-06-30", "2026-07-01", "2026-07-02"]
    assert dmsr_signal.is_rebalance_day(cal) is False


def test_is_rebalance_day_false_on_too_short_calendar():
    assert dmsr_signal.is_rebalance_day([]) is False
    assert dmsr_signal.is_rebalance_day(["2026-07-01"]) is False


# --- trailing_return / rank_sectors ----------------------------------

def test_trailing_return_is_12_month_month_end_to_month_end():
    closes = [(d, 100.0) for d in MONTH_ENDS_13[:-1]] + [(MONTH_ENDS_13[-1], 120.0)]
    s = _series("XLK", closes)
    assert dmsr_signal.trailing_return(s, MONTH_ENDS_13, 12) == pytest.approx(0.20)
    # explicit lookback arg
    assert dmsr_signal.trailing_return(s, MONTH_ENDS_13, 12, lookback=12) == pytest.approx(0.20)


def _sector_data(returns_by_symbol):
    data = {}
    for sym in dmsr_signal.SECTOR_UNIVERSE:
        r = returns_by_symbol[sym]
        closes = [(d, 100.0) for d in MONTH_ENDS_13[:-1]] + [(MONTH_ENDS_13[-1], 100.0 * (1 + r))]
        data[sym] = _series(sym, closes)
    return data


def test_rank_sectors_best_first_with_deterministic_ticker_tie_break():
    returns = {s: 0.0 for s in dmsr_signal.SECTOR_UNIVERSE}
    returns["XLE"] = 0.30
    returns["XLV"] = 0.10  # deliberate tie with XLK
    returns["XLK"] = 0.10
    ranked = dmsr_signal.rank_sectors(_sector_data(returns), MONTH_ENDS_13, 12)
    syms = [s for s, _ in ranked]
    assert syms[0] == "XLE"
    assert syms[1:3] == ["XLK", "XLV"]  # 0.10 tie -> alphabetical
    assert ranked[0][1] == pytest.approx(0.30)


# --- select_target_holdings ----------------------------------------

_RANK_ORDER = ["XLK", "XLV", "XLE", "XLF", "XLY", "XLP", "XLU", "XLI", "XLB", "XLRE", "XLC"]
_RANKED = [(s, 1.0 - i * 0.01) for i, s in enumerate(_RANK_ORDER)]


def test_select_target_holdings_risk_off_when_spy_negative_ignores_rankings():
    target, risk_off = dmsr_signal.select_target_holdings(["XLK", "XLV", "XLE"], _RANKED, -0.001)
    assert risk_off is True
    assert target == ["AGG"]


def test_select_target_holdings_keeps_a_held_name_at_rank_5_via_hysteresis():
    # XLY is held and sits at rank 5 (index 4) — inside the top-5 buffer,
    # so it is KEPT and NOT displaced by XLE (rank 3), which would take
    # its slot under a pure top-3 rule.
    target, risk_off = dmsr_signal.select_target_holdings(["XLY"], _RANKED, 0.05)
    assert risk_off is False
    assert target[0] == "XLY"                 # kept names first
    assert target[1:] == ["XLK", "XLV"]       # remaining slots filled by rank
    assert "XLE" not in target               # displaced by the hysteresis keep
    assert len(target) == dmsr_signal.TOP_N_HOLD


def test_select_target_holdings_drops_a_held_name_outside_the_top_5_clean_top_3_swap():
    # XLP is held but ranks 6th (outside top 5) -> sold. XLK is held and
    # ranks 1st -> kept. Result is the clean top 3.
    target, risk_off = dmsr_signal.select_target_holdings(["XLP", "XLK"], _RANKED, 0.05)
    assert risk_off is False
    assert "XLP" not in target
    assert target[0] == "XLK"
    assert set(target) == {"XLK", "XLV", "XLE"}
