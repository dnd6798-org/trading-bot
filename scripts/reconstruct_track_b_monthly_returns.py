"""
ONE-OFF diagnostic (NOT meant to be maintained — same convention as
scripts/select_universe.py, scripts/verify_finding12_sizing.py,
scripts/quantify_track_b_notional_concentration.py, scripts/
stress_test_track_b_risk_budget.py, scripts/compute_gem_benchmarks.py).

PURPOSE (CLAUDE.md v51 follow-up): produce Track B's genuine monthly-
return series so a monthly-return correlation against the DMSR (Track C
candidate) backtest can be computed in claude.ai. This script computes
NOTHING about correlation and renders NO adopt/abandon verdict — it only
reports Track B's own monthly returns, raw.

Track B's own scripts/backtest_etf_donchian.py and scripts/
backtest_donchian_ensemble.py are used COMPLETELY UNMODIFIED — no rule,
parameter, or logic change of any kind. This script:
  1. runs Track B's exact net-of-cost simulation — the identical
     simulate_rotational_ensemble() call backtest_etf_donchian.main()
     makes (same universe, 100d channel, 3.0x ATR stop, 8 slots, 8% risk
     budget, 55% notional cap, $10,000, 0% commission + 5bps/leg
     slippage); and
  2. reconstructs a DAILY mark-to-market equity curve from the recorded
     trades + Track B's own daily close series.

WHY THE RECONSTRUCTION IS NEEDED: simulate_rotational_ensemble()'s
returned `equity_curve` is realized-P&L-only — one point appended per
trade close, in exit order, with NO dates attached (it is positionally
parallel to the `trades` list). Equity moves ONLY on a realized close;
between closes, open positions' unrealized moves are invisible, and there
is no daily portfolio valuation anywhere in Track B's code. Over the
2019-07 -> 2026-08 reporting window, 27 of 86 months contain zero trade
closes and 116 of 155 trades span more than one calendar month, so the
raw curve cannot yield a genuine monthly-return series.

RECONSTRUCTION — faithful to Track B's own accounting:
  - position_size for each trade is FULLY DETERMINED by the recorded
    trade (no re-derivation of sizing logic):
        position_size = fees_paid / ((entry_price + exit_price) * cost_frac_per_leg)
    cross-checked against  gross_pnl / (exit_price - entry_price)  when
    the price delta is non-trivial. cost_frac_per_leg for Track B's net
    run = ETF_COMMISSION_PCT/100 + ETF_SLIPPAGE_BPS/10000 = 0 + 0.0005.
  - realized(d)   = capital + sum(t.pnl for trades with exit_date <= d)
  - unrealized(d) = sum, over trades OPEN on d (entry_date <= d < exit_date),
                    of  position_size * (close_of_symbol(d) - entry_price)
  - mtm_equity(d) = realized(d) + unrealized(d)
  - On a trade's EXIT day the trade is counted as REALIZED using the
    sim's recorded pnl (the sim exits at stop_price on a stop hit, or the
    day's close on eol — NOT necessarily that day's close), never marked
    at that day's close. On the ENTRY day the position is open but
    contributes 0 (entry_price == that day's close by construction).

  FLAGGED JUDGMENT CALL (immaterial here, but a real choice): unrealized
  P&L is marked GROSS — Track B books the entire round-trip fee
  (both legs) at the moment of exit, so the fee drag lands in the exit
  month, exactly as the sim recognizes it. An alternative would accrue
  the round-trip fee at entry (smoother, but the sim never reduces equity
  at entry). Track B is commission-free with a 5bps/leg slippage
  placeholder, so the per-trade fee is ~0.1% of notional round-trip and
  the choice moves month-end equity by at most a few $ on $10,000 — but
  it is stated, not hidden.

  FLAGGED, checked at runtime: whether all 8 Track B ETFs share an
  identical daily calendar (they do — NYSE). A missing bar for a symbol
  on a given day is forward-filled from its most recent prior close for
  marking purposes; the runtime output reports how many such fills
  occurred (expected: 0).

MONTH DEFINITION: scripts.backtest_gem.compute_month_end_dates — the last
trading day of each COMPLETED calendar month (the partial current month
is excluded). This is the EXACT function scripts/
backtest_sector_rotation.py (DMSR) used, so the two series share month-
end dates and align row-for-row. Monthly return for month M =
mtm_equity(month_end M) / mtm_equity(month_end M-1) - 1.

WINDOW-INDEPENDENCE: Track B's full 2016 -> present simulation is run
ONCE. The three requested windows (10m: 2019-05-01, 11m: 2019-06-03, 12m:
2019-07-01, all through 2026-08-27) are DMSR execution-date windows;
Track B's strategy does not change with them. They only truncate which
leading month-ends are reported — the per-month numbers are identical
where the columns overlap. Each column is aligned to the exact month-end
dates of the corresponding DMSR column in
backtest_output/dmsr_monthly_returns_split.csv when that file is present;
otherwise it starts at the 2nd month-end on/after the window start (which
reproduces DMSR's own "first full month after deployment, stub excluded"
rule).

Usage:
    python scripts/reconstruct_track_b_monthly_returns.py
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import MAX_SINGLE_POSITION_NOTIONAL_PCT
from scripts.backtest import DEFAULT_RISK_PER_TRADE_PCT
from scripts.backtest_gem import compute_month_end_dates
from scripts.backtest_donchian_ensemble import (
    simulate_rotational_ensemble,
    PAPER_VALIDATION_CAPITAL,
)
from scripts.backtest_etf_donchian import (
    build_symbol_series,
    UNIVERSE,
    ATR_MULTIPLIER,
    MAX_CONCURRENT_POSITIONS,
    ETF_COMMISSION_PCT,
    ETF_SLIPPAGE_BPS,
    REQUESTED_START,
)

WINDOWS = [
    ("10m", "2019-05-01"),
    ("11m", "2019-06-03"),
    ("12m", "2019-07-01"),
]
DMSR_CSV = Path(__file__).resolve().parent.parent / "backtest_output" / "dmsr_monthly_returns_split.csv"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "backtest_output"


def recover_position_size(trade, cost_frac_per_leg):
    """
    position_size is fully determined by the recorded trade. Primary:
    invert the fee formula (always defined when cost_frac_per_leg > 0 and
    prices > 0, i.e. Track B's net run). Cross-check: invert gross_pnl,
    when the price delta is non-trivial. Returns (position_size,
    check_rel_err_or_None).
    """
    denom_fee = (trade.entry_price + trade.exit_price) * cost_frac_per_leg
    ps_fee = trade.fees_paid / denom_fee if denom_fee else None

    price_delta = trade.exit_price - trade.entry_price
    ps_gross = trade.gross_pnl / price_delta if abs(price_delta) > 1e-9 else None

    if ps_fee is not None:
        primary = ps_fee
    elif ps_gross is not None:
        primary = ps_gross
    else:
        primary = 0.0

    rel_err = None
    if ps_fee is not None and ps_gross is not None and primary:
        rel_err = abs(ps_fee - ps_gross) / abs(primary)
    return primary, rel_err


def build_forward_filled_closes(symbol_data, calendar):
    """{symbol: {date: forward-filled close}} + a count of days that needed a fill."""
    ff = {}
    fills = 0
    for sym, series in symbol_data.items():
        di = series["date_index"]
        candles = series["candles"]
        last = None
        col = {}
        for d in calendar:
            idx = di.get(d)
            if idx is not None:
                last = candles[idx].close
            else:
                if last is not None:
                    fills += 1
            col[d] = last
        ff[sym] = col
    return ff, fills


def reconstruct_daily_mtm_equity(trades, symbol_data, calendar, capital, cost_frac_per_leg):
    """
    Daily mark-to-market equity: realized cash + gross unrealized P&L on
    open positions. See module docstring for the exact accounting.
    Returns (list[(date, equity)], sizing_check_max_rel_err, ff_fill_count).
    """
    sized = []
    max_rel_err = 0.0
    for t in trades:
        ps, rel_err = recover_position_size(t, cost_frac_per_leg)
        if rel_err is not None:
            max_rel_err = max(max_rel_err, rel_err)
        sized.append((t, ps, t.entry_timestamp[:10], t.exit_timestamp[:10]))

    ff, fills = build_forward_filled_closes(symbol_data, calendar)

    # cumulative realized pnl by date
    realized_by_exit = {}
    for t in trades:
        realized_by_exit.setdefault(t.exit_timestamp[:10], 0.0)
        realized_by_exit[t.exit_timestamp[:10]] += t.pnl

    curve = []
    realized = capital
    for d in calendar:
        realized += realized_by_exit.get(d, 0.0)
        unrealized = 0.0
        for (t, ps, ed, xd) in sized:
            if ed <= d < xd:
                cur = ff[t.symbol][d]
                if cur is not None:
                    unrealized += ps * (cur - t.entry_price)
        curve.append((d, realized + unrealized))
    return curve, max_rel_err, fills


def monthly_returns(daily_curve, month_end_dates):
    by_date = dict(daily_curve)
    me = [d for d in month_end_dates if d in by_date]
    out = []
    for i in range(1, len(me)):
        prev, cur = by_date[me[i - 1]], by_date[me[i]]
        out.append((me[i], (cur - prev) / prev if prev else 0.0))
    return out


def dmsr_column_start_dates():
    """
    {window_label: first month_end where the matching DMSR column is
    populated}. Prefers the real DMSR CSV; falls back to "2nd month-end
    on/after the window start" if it's absent.
    """
    starts = {}
    if DMSR_CSV.exists():
        lines = DMSR_CSV.read_text().strip().splitlines()
        header = lines[0].split(",")
        col_idx = {lbl: header.index(f"ret_{lbl}") for lbl, _ in WINDOWS}
        for lbl, _ in WINDOWS:
            ci = col_idx[lbl]
            for row in lines[1:]:
                parts = row.split(",")
                if len(parts) > ci and parts[ci].strip() != "":
                    starts[lbl] = parts[0]
                    break
        return starts, "dmsr_csv"
    return starts, "missing_dmsr_csv"


def fallback_start(window_start, month_end_dates):
    ons = [d for d in month_end_dates if d >= window_start]
    return ons[1] if len(ons) >= 2 else (ons[0] if ons else None)


def main():
    end = datetime.now(timezone.utc) - timedelta(minutes=20)  # same convention as backtest_etf_donchian.main()

    print("=== Track B monthly-return reconstruction (CLAUDE.md v51 follow-up — NO correlation, NO verdict) ===")
    print("Track B code (backtest_etf_donchian.py / backtest_donchian_ensemble.py) UNMODIFIED — this script only runs it and post-processes the trades.")
    print(f"requested start: {REQUESTED_START.date()} (2016-01-04 account floor applies) -> {end.date()}")

    symbol_data = {}
    for sym in UNIVERSE:
        series = build_symbol_series(sym, REQUESTED_START, end)
        if series is None:
            print(f"  {sym}: NO DATA — aborting")
            return
        symbol_data[sym] = series
        c = series["candles"]
        print(f"  {sym:4s}: {c[0].timestamp[:10]} -> {c[-1].timestamp[:10]}  ({len(c)} daily candles)")

    universe_order = [s for s in UNIVERSE if s in symbol_data]
    calendar = sorted(set().union(*(s["date_index"].keys() for s in symbol_data.values())))
    cost_frac_per_leg = ETF_COMMISSION_PCT / 100 + ETF_SLIPPAGE_BPS / 10000

    # EXACT replica of backtest_etf_donchian.main()'s net-of-cost simulate call.
    net_trades, net_curve, skipped_log = simulate_rotational_ensemble(
        symbol_data, universe_order,
        max_positions=MAX_CONCURRENT_POSITIONS, atr_multiplier=ATR_MULTIPLIER,
        capital=PAPER_VALIDATION_CAPITAL, fee_pct=ETF_COMMISSION_PCT, slippage_bps=ETF_SLIPPAGE_BPS,
        notional_sanity_cap_pct=MAX_SINGLE_POSITION_NOTIONAL_PCT,
    )
    print(f"\nTrack B net simulation: {len(net_trades)} trades, {len(skipped_log)} signals skipped, "
          f"realized equity_curve has {len(net_curve)} points (one per close + opening capital)")
    print(f"  cost_frac_per_leg (net) = {cost_frac_per_leg:.6f}  ({ETF_COMMISSION_PCT:.2f}% commission + {ETF_SLIPPAGE_BPS:.0f}bps slippage)")
    print(f"  sim's own realized total return (full history, capital ${PAPER_VALIDATION_CAPITAL:,.0f} -> ${net_curve[-1]:,.2f}): "
          f"{(net_curve[-1] - PAPER_VALIDATION_CAPITAL) / PAPER_VALIDATION_CAPITAL * 100:.2f}%")

    daily_curve, max_rel_err, ff_fills = reconstruct_daily_mtm_equity(
        net_trades, symbol_data, calendar, PAPER_VALIDATION_CAPITAL, cost_frac_per_leg
    )
    recon_realized_end = daily_curve[-1][1]
    print(f"\nreconstruction: daily mark-to-market curve over {len(daily_curve)} trading days "
          f"({daily_curve[0][0]} -> {daily_curve[-1][0]})")
    print(f"  position-size cross-check (fee-inversion vs. gross-inversion) max relative error: {max_rel_err:.2e} "
          f"({'OK' if max_rel_err < 1e-6 else 'INVESTIGATE'})")
    print(f"  forward-filled (missing-bar) symbol-days during marking: {ff_fills} ({'all 8 ETFs share one calendar' if ff_fills == 0 else 'gaps present — see docstring'})")
    print(f"  reconstructed end equity (last trading day, should ~= sim realized end since no positions open at eol): "
          f"${recon_realized_end:,.2f}  (sim: ${net_curve[-1]:,.2f}, diff ${recon_realized_end - net_curve[-1]:,.4f})")

    month_end_dates = compute_month_end_dates(calendar)
    full_monthly = monthly_returns(daily_curve, month_end_dates)
    full_by_date = dict(full_monthly)
    print(f"\nfull reconstructed monthly-return series: {len(full_monthly)} months "
          f"({full_monthly[0][0]} -> {full_monthly[-1][0]})")

    starts, start_source = dmsr_column_start_dates()
    for lbl, wstart in WINDOWS:
        if lbl not in starts:
            starts[lbl] = fallback_start(wstart, month_end_dates)
    print(f"per-window column start month-ends (source: {start_source}):")
    for lbl, wstart in WINDOWS:
        print(f"  {lbl} (window {wstart} -> 2026-08-27): first reported month_end = {starts[lbl]}")

    # combined CSV: month_end + one column per window (same underlying series, truncated).
    all_months = [d for d, _ in full_monthly]
    header = ["month_end"] + [f"trackb_ret_{lbl}" for lbl, _ in WINDOWS] + ["trackb_ret_full"]
    rows = [",".join(header)]
    for d in all_months:
        cells = [d]
        for lbl, _ in WINDOWS:
            s = starts.get(lbl)
            cells.append(f"{full_by_date[d]:.8f}" if (s is not None and d >= s) else "")
        cells.append(f"{full_by_date[d]:.8f}")
        rows.append(",".join(cells))
    csv_text = "\n".join(rows) + "\n"

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / "track_b_monthly_returns.csv"
    out_path.write_text(csv_text)

    print(f"\n=== Track B reconstructed monthly returns (net-of-cost, daily mark-to-market) — written to {out_path} ===")
    print("NOTE: trackb_ret_10m / _11m / _12m are the SAME monthly series, differently truncated at the front to match the")
    print("      corresponding DMSR column's start. trackb_ret_full is the untruncated series. All values are net-of-cost.")
    print(csv_text)


if __name__ == "__main__":
    main()
