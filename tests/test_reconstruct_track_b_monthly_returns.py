"""
Verifies the reconstruction logic in
scripts/reconstruct_track_b_monthly_returns.py (a one-off diagnostic —
CLAUDE.md v51 follow-up). Track B's own code is NOT exercised here (it is
used unmodified by the script); these tests only pin the post-processing:
position-size recovery from a recorded trade, forward-filled close
construction, the daily mark-to-market walk, and month-end sampling.
Synthetic data only, no network.
"""
from src.data_ingestion import Candle
from scripts.backtest_donchian_ensemble import EnsembleTrade
from scripts.reconstruct_track_b_monthly_returns import (
    recover_position_size,
    build_forward_filled_closes,
    reconstruct_daily_mtm_equity,
    monthly_returns,
)

COST_FRAC = 0.0005  # Track B net run: 0% commission + 5bps/leg slippage


def _trade(symbol, entry_d, exit_d, entry_px, exit_px, position_size, cost_frac=COST_FRAC):
    gross = position_size * (exit_px - entry_px)
    fees = position_size * (entry_px + exit_px) * cost_frac
    return EnsembleTrade(
        symbol=symbol, entry_index=0, exit_index=0,
        entry_timestamp=f"{entry_d}T00:00:00+00:00", exit_timestamp=f"{exit_d}T00:00:00+00:00",
        entry_price=entry_px, exit_price=exit_px, exit_reason="trailing_stop",
        gross_pnl=gross, fees_paid=fees, pnl=gross - fees,
        r_multiple=0.0,
    )


def _series(symbol, dated_closes):
    candles = [Candle(symbol, f"{d}T00:00:00+00:00", open=c, high=c, low=c, close=c, volume=1000)
               for d, c in dated_closes]
    return {"symbol": symbol, "candles": candles, "date_index": {c.timestamp[:10]: i for i, c in enumerate(candles)}}


def test_recover_position_size_fee_and_gross_agree():
    t = _trade("SPY", "2020-01-06", "2020-02-10", 100.0, 110.0, position_size=10.0)
    ps, rel_err = recover_position_size(t, COST_FRAC)
    assert abs(ps - 10.0) < 1e-9
    assert rel_err is not None and rel_err < 1e-9


def test_recover_position_size_falls_back_to_fee_when_price_delta_zero():
    # exit_price == entry_price -> gross-inversion undefined; fee-inversion still works.
    t = _trade("AGG", "2020-01-06", "2020-01-20", 100.0, 100.0, position_size=7.5)
    ps, rel_err = recover_position_size(t, COST_FRAC)
    assert abs(ps - 7.5) < 1e-9
    assert rel_err is None  # only one method available, no cross-check


def test_build_forward_filled_closes_fills_gaps_and_counts_them():
    cal = ["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07"]
    sd = {"SPY": _series("SPY", [("2020-01-02", 100.0), ("2020-01-03", 101.0), ("2020-01-07", 103.0)])}  # 01-06 missing
    ff, fills = build_forward_filled_closes(sd, cal)
    assert ff["SPY"]["2020-01-06"] == 101.0  # forward-filled from 01-03
    assert ff["SPY"]["2020-01-07"] == 103.0
    assert fills == 1


def test_reconstruct_daily_mtm_marks_open_position_and_realizes_on_exit_day():
    cal = ["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07", "2020-01-08"]
    # Entry at 2020-01-03 close (100), exit at 2020-01-07 (recorded exit_price 106).
    sd = {"SPY": _series("SPY", [
        ("2020-01-02", 99.0), ("2020-01-03", 100.0), ("2020-01-06", 104.0),
        ("2020-01-07", 108.0), ("2020-01-08", 110.0),
    ])}
    t = _trade("SPY", "2020-01-03", "2020-01-07", 100.0, 106.0, position_size=10.0)
    curve, max_rel_err, fills = reconstruct_daily_mtm_equity([t], sd, cal, capital=1000.0, cost_frac_per_leg=COST_FRAC)
    by_date = dict(curve)

    assert by_date["2020-01-02"] == 1000.0                 # before entry: just cash
    assert abs(by_date["2020-01-03"] - 1000.0) < 1e-9      # entry day: open but 0 P&L (close == entry_price)
    assert abs(by_date["2020-01-06"] - (1000.0 + 10.0 * (104.0 - 100.0))) < 1e-9  # marked at that day's close
    # exit day: realized at the RECORDED exit_price (106), not the day's close (108)
    assert abs(by_date["2020-01-07"] - (1000.0 + t.pnl)) < 1e-9
    assert abs(by_date["2020-01-08"] - (1000.0 + t.pnl)) < 1e-9  # flat cash after exit
    assert fills == 0
    assert max_rel_err < 1e-9


def test_reconstruct_converges_to_capital_plus_realized_when_flat_at_end():
    cal = ["2021-03-01", "2021-03-02", "2021-03-03", "2021-03-04"]
    sd = {
        "SPY": _series("SPY", [("2021-03-01", 50.0), ("2021-03-02", 55.0), ("2021-03-03", 60.0), ("2021-03-04", 62.0)]),
        "QQQ": _series("QQQ", [("2021-03-01", 80.0), ("2021-03-02", 78.0), ("2021-03-03", 70.0), ("2021-03-04", 72.0)]),
    }
    t1 = _trade("SPY", "2021-03-01", "2021-03-03", 50.0, 58.0, position_size=4.0)
    t2 = _trade("QQQ", "2021-03-02", "2021-03-04", 78.0, 71.0, position_size=3.0)
    curve, _, _ = reconstruct_daily_mtm_equity([t1, t2], sd, cal, capital=500.0, cost_frac_per_leg=COST_FRAC)
    assert abs(curve[-1][1] - (500.0 + t1.pnl + t2.pnl)) < 1e-9


def test_monthly_returns_month_over_month_from_daily_curve():
    daily = [
        ("2020-01-31", 1000.0), ("2020-02-14", 1100.0), ("2020-02-28", 1050.0),
        ("2020-03-31", 1260.0),
    ]
    me = ["2020-01-31", "2020-02-28", "2020-03-31"]
    out = monthly_returns(daily, me)
    assert out[0] == ("2020-02-28", (1050.0 - 1000.0) / 1000.0)
    assert out[1] == ("2020-03-31", (1260.0 - 1050.0) / 1050.0)
