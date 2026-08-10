"""
Track C (spec v25 §10.5): SPY put credit spread — STRESS-TEST SCENARIO
ANALYSIS, required separately from and NOT blended into
scripts/backtest_put_credit_spread.py's pooled backtest numbers (user
instruction — this is its own clearly-labeled report).

PURPOSE: the pooled backtest only covers 2024-01-18 -> present (the
account's real options-data floor, CLAUDE.md Track C finding 1) — a
window that does not contain a genuine sharp equity crash. This checks
the strategy's strike-selection rule against three real historical crash
windows using ONLY SPY's own underlying price history (available back to
2016, RAW/unadjusted — matches the main backtest's convention for
strike-level context) — NO options data is needed or used for this
script, since the question here is purely "how far did the underlying
fall relative to where the strikes would have been," not "what would
this specific spread's premium have been."

WINDOWS (user-specified, taken as calendar-month ranges rather than
hand-picked peak/trough dates from memory — deliberately, so the exact
extrema are found from real fetched data, not assumed from recollection):
  - Feb 2018 ("Volmageddon" vol-spike selloff)
  - Feb-Mar 2020 (COVID crash)
  - Sept-Oct 2022 (2022 bear-market low)

REDESIGN (this session, matching backtest_put_credit_spread.py's two
pre-registered changes, reasoned independently of the first run's
zero-trade result):
  1. Strike zone narrowed to 2-4% OTM (NARROW_OTM_LOW/HIGH, imported from
     the main backtest file, not redefined here) — same zone, same
     rationale.
  2. Sizing uses PCS_RISK_PER_TRADE_PCT (2%, imported from the main
     backtest file) instead of spec §4.1's global 1%.

METHODOLOGY, each judgment call flagged, not silently resolved:
  - "A hypothetically-open position going into the window" is modeled as
    ENTERED THE LAST SPY TRADING DAY BEFORE THE WINDOW STARTS — the
    zero-cushion, worst-case timing (a position established right as the
    selloff begins, with no prior favorable drift already banked). An
    entry weeks earlier (the main backtest's real monthly cadence) could
    look safer purely because of where in the cycle it happened to sit;
    this scenario deliberately does not give the strategy that benefit
    of the doubt.
  - Strikes: short leg = spot * (1 - zone_center), where zone_center is
    the midpoint of the 2-4% OTM zone, rounded to the nearest $1. Long
    leg = short leg minus $1 (the narrowest achievable increment CONFIRMED
    REAL in this same zone by the main backtest against the live 2024-2026
    chain — see backtest_put_credit_spread.py's module docstring; every
    cycle checked there found $1 spacing throughout the zone). This
    account has NO options chain data before 2024-01-18 (CLAUDE.md Track C
    finding 1), so the $1 increment is a CARRIED-OVER assumption from
    confirmed recent real data, not an independent guess for 2018/2020/
    2022 specifically — flagged, not resolved by pretending a chain exists
    for these older dates.
  - Breach severity = how far the window's TROUGH close fell below the
    short strike, capped at the spread's own structural width (a credit
    spread's max loss can never exceed strike width regardless of credit
    collected) — the "known max loss per spread" the instruction referred
    to. This is a STRUCTURAL cap, not the ACTUAL max loss (which would be
    width minus whatever credit was actually collected) — real credit
    isn't knowable for these pre-2024 dates, so using the full width
    overstates per-contract loss (ignores the credit cushion) while
    simultaneously understating contract count in the sizing calc below
    (same missing-credit assumption makes each contract look larger-risk
    than it likely really was, so fewer contracts fit the risk budget) —
    these two effects pull in OPPOSITE directions on the final
    dollar-loss-to-equity figure and are NOT claimed to cancel out; both
    are reported so the reader can judge each independently.
  - Sizing uses the SAME formula as the main backtest (contracts =
    floor(risk budget / max_loss_per_contract), risk budget =
    PCS_RISK_PER_TRADE_PCT of equity), with PAPER_VALIDATION_CAPITAL as a
    fixed snapshot equity basis (there is no rolled-forward equity curve
    prior to 2024) — not a claim the account actually had this exact
    equity in 2018/2020/2022.
  - "Concurrent spreads" in the instruction maps to CONTRACT COUNT within
    the single position sized above, not multiple distinct simultaneous
    positions — the main strategy design (backtest_put_credit_spread.py)
    is explicitly single-position, sequential, continuous monthly
    rolling; it is never structurally possible for more than one spread
    to be open at a time. This script reports contract count under that
    same constraint, not a different concurrency model.

Usage:
    python scripts/stress_test_pcs.py
"""
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.backtest import _print_table, DEFAULT_RISK_PER_TRADE_PCT
from scripts.backtest_donchian_ensemble import PAPER_VALIDATION_CAPITAL
from scripts.backtest_put_credit_spread import (
    UNDERLYING,
    NARROW_OTM_LOW,
    NARROW_OTM_HIGH,
    PCS_RISK_PER_TRADE_PCT,
    select_expiry,
    build_symbol_series,
)

# Carried over from the main backtest's confirmed-real $1 increment
# throughout the 2-4% OTM zone (2024-2026 chain) — see module docstring.
ASSUMED_NARROWEST_INCREMENT_DOLLARS = 1.0

STRESS_WINDOWS = [
    {"label": "Feb 2018 (Volmageddon)", "start": "2018-02-01", "end": "2018-02-28"},
    {"label": "Feb-Mar 2020 (COVID crash)", "start": "2020-02-01", "end": "2020-03-31"},
    {"label": "Sept-Oct 2022 (2022 bear-market low)", "start": "2022-09-01", "end": "2022-10-31"},
]


def find_entry_date(spy_dates_sorted, window_start: str):
    """Last available SPY trading date strictly before window_start — see module docstring's entry-timing judgment call."""
    before = [d for d in spy_dates_sorted if d < window_start]
    return before[-1] if before else None


def find_trough(spy_series, window_start: str, window_end: str):
    """(trough_date, trough_close) — the minimum close within [window_start, window_end], from real fetched data."""
    in_window = [(d, spy_series["candles"][i].close) for d, i in spy_series["date_index"].items() if window_start <= d <= window_end]
    if not in_window:
        return None, None
    return min(in_window, key=lambda pair: pair[1])


def run_scenario(spy_series, window):
    spy_dates = sorted(spy_series["date_index"].keys())
    entry_date_str = find_entry_date(spy_dates, window["start"])
    if entry_date_str is None:
        return {"label": window["label"], "error": "no SPY data available before this window"}

    entry_idx = spy_series["date_index"][entry_date_str]
    spot = spy_series["candles"][entry_idx].close
    entry_date = date.fromisoformat(entry_date_str)

    zone_center_otm = (NARROW_OTM_LOW + NARROW_OTM_HIGH) / 2
    short_strike = round(spot * (1 - zone_center_otm))
    long_strike = short_strike - ASSUMED_NARROWEST_INCREMENT_DOLLARS
    width = short_strike - long_strike

    illustrative_expiry, illustrative_dte, _ = select_expiry(entry_date)

    trough_date, trough_close = find_trough(spy_series, window["start"], window["end"])

    breach_amount = max(0.0, short_strike - trough_close)
    capped_loss_per_contract_dollars = min(breach_amount, width) * 100
    loss_pct_of_max = capped_loss_per_contract_dollars / (width * 100) * 100 if width > 0 else 0.0

    risk_amount = PAPER_VALIDATION_CAPITAL * (PCS_RISK_PER_TRADE_PCT / 100)
    structural_max_loss_per_contract = width * 100  # see module docstring — ignores unknown credit, conservative for contract count
    contracts = int(risk_amount // structural_max_loss_per_contract) if structural_max_loss_per_contract > 0 else 0

    total_position_loss = contracts * capped_loss_per_contract_dollars
    pct_of_equity = total_position_loss / PAPER_VALIDATION_CAPITAL * 100
    underlying_decline_pct = (trough_close - spot) / spot * 100

    return {
        "label": window["label"],
        "entry_date": entry_date_str,
        "spot_at_entry": spot,
        "short_strike": short_strike,
        "long_strike": long_strike,
        "width": width,
        "illustrative_expiry": illustrative_expiry.isoformat(),
        "illustrative_dte": illustrative_dte,
        "trough_date": trough_date,
        "trough_close": trough_close,
        "underlying_decline_pct": underlying_decline_pct,
        "breach_amount": breach_amount,
        "capped_loss_per_contract_dollars": capped_loss_per_contract_dollars,
        "loss_pct_of_max": loss_pct_of_max,
        "contracts": contracts,
        "total_position_loss": total_position_loss,
        "pct_of_equity": pct_of_equity,
    }


def main():
    end = datetime.now(timezone.utc) - timedelta(minutes=20)
    start = datetime(2016, 1, 4, tzinfo=timezone.utc)  # equity-data floor (Track A/B) -- covers all 3 stress windows

    print("=== Track C STRESS TEST — separate scenario analysis, NOT part of the pooled backtest numbers ===")
    print(f"(REDESIGN this session: strike zone -> narrowest-achievable in {NARROW_OTM_LOW*100:.0f}-{NARROW_OTM_HIGH*100:.0f}% OTM (assumed ${ASSUMED_NARROWEST_INCREMENT_DOLLARS:.0f} increment, carried over from the main backtest's confirmed-real chain check); sizing -> {PCS_RISK_PER_TRADE_PCT:.0f}% defined-risk override, not spec §4.1's global {DEFAULT_RISK_PER_TRADE_PCT:.0f}%)")
    print("Uses SPY underlying price history only (no options data, none needed) — see module docstring for every judgment call made.\n")

    spy_series = build_symbol_series(UNDERLYING, start, end)
    if spy_series is None:
        print("SPY: no candle data returned")
        return
    print(f"SPY daily history: {spy_series['candles'][0].timestamp[:10]} -> {spy_series['candles'][-1].timestamp[:10]}\n")

    results = [run_scenario(spy_series, w) for w in STRESS_WINDOWS]

    rows = []
    for r in results:
        if "error" in r:
            rows.append({"window": r["label"], "note": r["error"]})
            continue
        rows.append({
            "window": r["label"],
            "entry": r["entry_date"],
            "spot": f"{r['spot_at_entry']:.2f}",
            "short_K/long_K": f"{r['short_strike']}/{r['long_strike']}",
            "width": f"{r['width']:.0f}",
            "trough": f"{r['trough_close']:.2f} ({r['trough_date']})",
            "underlying_decline%": f"{r['underlying_decline_pct']:.1f}",
            "breach$": f"{r['breach_amount']:.2f}",
            "loss/contract($)": f"{r['capped_loss_per_contract_dollars']:.0f}",
            "%_of_max_loss": f"{r['loss_pct_of_max']:.1f}",
        })
    _print_table(rows, [
        ("window", "window"), ("entry", "entry"), ("spot", "spot"), ("short_K/long_K", "short_K/long_K"), ("width", "width"),
        ("trough", "trough"), ("underlying_decline%", "underlying_decline%"),
        ("breach$", "breach$"), ("loss/contract($)", "loss/contract($)"), ("%_of_max_loss", "%_of_max_loss"),
    ])

    print(f"\n=== Sizing + account-level impact ({PCS_RISK_PER_TRADE_PCT:.0f}% of ${PAPER_VALIDATION_CAPITAL:,.0f} equity, defined-risk override, structural width as max loss — see module docstring) ===")
    sizing_rows = []
    for r in results:
        if "error" in r:
            continue
        sizing_rows.append({
            "window": r["label"],
            "contracts": r["contracts"],
            "total_position_loss($)": f"{r['total_position_loss']:.0f}",
            "%_of_equity": f"{r['pct_of_equity']:.2f}",
        })
    _print_table(sizing_rows, [
        ("window", "window"), ("contracts", "contracts"),
        ("total_position_loss($)", "total_position_loss($)"), ("%_of_equity", "%_of_equity"),
    ])
    if any(r.get("contracts", 1) == 0 for r in results if "error" not in r):
        zero = [r["label"] for r in results if "error" not in r and r["contracts"] == 0]
        print(f"\nNOTE: {zero} sized to ZERO contracts even under the {PCS_RISK_PER_TRADE_PCT:.0f}% defined-risk override and narrowest-achievable "
              f"width — reported plainly, not forced to a non-zero number, per instruction.")
    elif all(r.get("contracts", 0) > 0 for r in results if "error" not in r):
        print(f"\nAll {len(results)} stress windows sized to >=1 contract under the {PCS_RISK_PER_TRADE_PCT:.0f}% defined-risk override.")


if __name__ == "__main__":
    main()
