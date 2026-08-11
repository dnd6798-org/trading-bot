"""
Track B risk-budget shrink-under-pressure stress test (spec v29 §10.1).
Diagnostic milestone only — does NOT reopen Track B's already-passed
verdict (pooled net-of-costs +73.64%, 3/3 folds net-positive, max
drawdown 5.69% vs. the 8-ETF buy-and-hold blend's 26.47%, see CLAUDE.md
"Track B findings"). That result was produced with
MAX_CONCURRENT_POSITIONS = 8, exactly equal to the full 8-symbol
universe, so the slot-count cap could never bind by construction and the
portfolio-level risk budget was the only mechanism that could ever shrink
a trade — and even that path went unexercised in practice (0 signals
skipped for any reason in the original run, per "Track B findings" 1).
This closes that honesty gap before execution.py is built on top of this
strategy: confirm the shrink-under-pressure mechanism behaves correctly
when it is actually forced to bind, not just that it CAN in principle.

Two checks, per the milestone's own required scope:
  1. Unit-level correctness — a direct synthetic scenario, NOT run from
     this script: see
     tests/test_backtest_donchian_ensemble.py::
     test_simulate_rotational_ensemble_binds_both_slot_cap_and_risk_budget_in_one_scenario
     and the two entry_sizing_log tests alongside it. Those construct a
     6-symbol/4-slot/3.5%-budget scenario where the slot cap AND the risk
     budget both bind in a single run, including a partial shrink (not
     just an outright rejection), and assert the resulting sizes and skip
     reasons exactly.
  2. Real-data behavioral check — THIS script. Reruns Track B's exact
     universe/window/signal/exit (UNIVERSE, REQUESTED_START,
     build_symbol_series(), ATR_MULTIPLIER, imported unchanged from
     scripts/backtest_etf_donchian.py) through simulate_rotational_
     ensemble() (imported unchanged from
     scripts/backtest_donchian_ensemble.py) with MAX_CONCURRENT_POSITIONS
     cut from 8 to REDUCED_MAX_POSITIONS=4 and the total risk budget cut
     PROPORTIONALLY (4 x 1% = 4%, same derivation
     backtest_etf_donchian.py's own main() already uses for
     total_risk_budget_pct = max_positions * DEFAULT_RISK_PER_TRADE_PCT)
     — forcing both constraints to compete for real historical
     signal-overlap instead of a hand-built synthetic case.

No strategy logic is touched by this script — it is pure instrumentation
and reporting on top of the exact same, already-tested simulation
function Track B's passed verdict came from. The one code change this
milestone required was adding an opt-in `entry_sizing_log` parameter to
simulate_rotational_ensemble() (backtest_donchian_ensemble.py) — purely
additive, defaults to None, changes no behavior and no return signature
for any existing caller (see that function's docstring and the new
backward-compatibility test alongside the two above).

NOT a profitability test — per instruction, this script deliberately does
NOT print net/gross/folds-positive numbers from the reduced-cap rerun, so
the output can't be read as a new adopt/reject bar. It reports only:
  (a) how many real historical instances forced the slot-count cap and/or
      the risk budget to bind (skipped_log, by reason), and
  (b) for every instance where the risk budget actually shrunk a trade,
      a direct arithmetic check that the granted risk exactly equals the
      remaining budget at that moment (not silently over- or
      under-allocated), plus a portfolio-wide over-allocation sanity
      check across every accepted entry, not just the shrunk ones.

UNEXPECTED FINDING FROM RUNNING THIS SCRIPT (reported here since it's the
main thing this milestone surfaced): the risk-budget shrink path itself
(the mechanism this milestone set out to stress-test) worked correctly
when forced to bind (14 of 196 entries at max_positions=4, all verified
exactly), but a SEPARATE, previously-undocumented mechanism turned out to
be doing real, silent work — the loose 100%-of-equity NOTIONAL_SANITY_
CAP_PCT backstop (backtest_donchian_ensemble.py), described everywhere in
this codebase as a "near-zero-ATR edge case" that "essentially never
binds for these liquid symbols." Confirmed by rerunning Track B's EXACT
original 8-slot/8%-budget configuration (not just this script's reduced
4-slot rerun) with the new instrumentation: it bound on 13 of AGG's 15
total trades (87%) in the real, already-passed Track B backtest, each one
sized to exactly 100% of account equity — AGG's low ATR-relative-to-price
makes the notional backstop AGG's normal sizing path, not an edge case.
This does not change any trade taken or Track B's reported returns (the
resize arithmetic itself is correct — see the spot-check below and
backtest_etf_donchian.py's module docstring correction for the full
writeup) and does not reopen Track B's verdict, but it means the "~8%
worst-case aggregate risk" mental model is incomplete for this universe —
flagged for whatever picks this strategy up next, not resolved here.

One-off script, not meant to be maintained — same convention as
scripts/select_universe.py, scripts/verify_finding12_sizing.py,
scripts/compute_gem_benchmarks.py, scripts/check_options_data_availability.py.

Usage:
    python scripts/stress_test_track_b_risk_budget.py
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.backtest import DEFAULT_RISK_PER_TRADE_PCT
from scripts.backtest_etf_donchian import (
    UNIVERSE,
    ATR_MULTIPLIER,
    ETF_COMMISSION_PCT,
    ETF_SLIPPAGE_BPS,
    REQUESTED_START,
    build_symbol_series,
)
from scripts.backtest_donchian_ensemble import (
    simulate_rotational_ensemble,
    PAPER_VALIDATION_CAPITAL,
)

# Down from Track B's original 8 (== full universe size, per that
# milestone's own flagged judgment call — see backtest_etf_donchian.py's
# module docstring) — chosen to force real competition for slots across
# an 8-symbol universe without being so tight it starves every fold, same
# consideration finding 11->12's slot-cap widening (4->8) already
# demonstrated matters for this class of strategy.
REDUCED_MAX_POSITIONS = 4
SPOT_CHECK_COUNT = 10


def main():
    end = datetime.now(timezone.utc) - timedelta(minutes=20)  # SIP recent-data embargo, same convention as backtest_etf_donchian.py

    print("=== Track B risk-budget shrink-under-pressure stress test (spec v29 §10.1) ===")
    print("DIAGNOSTIC ONLY — does not reopen Track B's passed verdict (pooled net +73.64%, 3/3 folds, see CLAUDE.md).")
    print("Original run: MAX_CONCURRENT_POSITIONS=8 (= full 8-symbol universe) -> the slot-count cap could never bind by construction.")
    total_risk_budget_pct = REDUCED_MAX_POSITIONS * DEFAULT_RISK_PER_TRADE_PCT
    print(
        f"This run: MAX_CONCURRENT_POSITIONS={REDUCED_MAX_POSITIONS} "
        f"(risk budget cut proportionally, {REDUCED_MAX_POSITIONS} x {DEFAULT_RISK_PER_TRADE_PCT:.1f}% = {total_risk_budget_pct:.1f}%, was 8.0%)\n"
    )

    symbol_data = {}
    for symbol in UNIVERSE:
        series = build_symbol_series(symbol, REQUESTED_START, end)
        if series is None:
            print(f"{symbol}: no candle data returned, excluding from this run")
            continue
        symbol_data[symbol] = series
        first, last = series["candles"][0], series["candles"][-1]
        print(f"  {symbol}: {first.timestamp[:10]} -> {last.timestamp[:10]}  ({len(series['candles'])} daily candles, {len(series['entry_indices'])} raw long-entry signals)")

    universe_order = [s for s in UNIVERSE if s in symbol_data]

    entry_sizing_log = []
    trades, equity_curve, skipped_log = simulate_rotational_ensemble(
        symbol_data, universe_order,
        max_positions=REDUCED_MAX_POSITIONS, atr_multiplier=ATR_MULTIPLIER,
        capital=PAPER_VALIDATION_CAPITAL, total_risk_budget_pct=total_risk_budget_pct,
        fee_pct=ETF_COMMISSION_PCT, slippage_bps=ETF_SLIPPAGE_BPS,
        entry_sizing_log=entry_sizing_log,
    )

    print(f"\n{len(trades)} trades taken, {len(entry_sizing_log)} entries accepted and sized, {len(skipped_log)} signals skipped.")
    print("(trade count is reported for context only — NOT a re-run of the adopt/reject bar; no net/gross/folds numbers are reported below.)")

    by_reason = {}
    for s in skipped_log:
        by_reason[s["reason"]] = by_reason.get(s["reason"], 0) + 1
    print(f"\nskipped signals by reason: {by_reason if by_reason else '(none)'}")
    by_symbol_skips = {}
    for s in skipped_log:
        by_symbol_skips[s["symbol"]] = by_symbol_skips.get(s["symbol"], 0) + 1
    if by_symbol_skips:
        print("skipped signals by symbol:", ", ".join(f"{sym}={n}" for sym, n in sorted(by_symbol_skips.items(), key=lambda kv: -kv[1])))

    shrunk_by_budget = [e for e in entry_sizing_log if e["shrunk_by_risk_budget"]]
    shrunk_by_notional = [e for e in entry_sizing_log if e["shrunk_by_notional_cap"]]
    print(f"\nentries shrunk by the risk budget (granted < target): {len(shrunk_by_budget)} of {len(entry_sizing_log)}")
    print(
        f"entries shrunk by the notional sanity backstop: {len(shrunk_by_notional)} of {len(entry_sizing_log)}  "
        f"(this backstop was documented as a rare near-zero-ATR edge case — if this count is non-trivial, see "
        f"the by-symbol breakdown below; a real, previously-undocumented finding this milestone surfaced is that "
        f"it is NOT rare for AGG, see backtest_etf_donchian.py's module docstring correction)"
    )
    if shrunk_by_notional:
        by_symbol_notional = {}
        for e in shrunk_by_notional:
            by_symbol_notional[e["symbol"]] = by_symbol_notional.get(e["symbol"], 0) + 1
        print("  notional-backstop shrinks by symbol:", ", ".join(f"{sym}={n}" for sym, n in sorted(by_symbol_notional.items(), key=lambda kv: -kv[1])))

    print(f"\n=== Spot-check: up to {SPOT_CHECK_COUNT} risk-budget-shrunk entries, verified arithmetic ===")
    if shrunk_by_budget:
        for e in shrunk_by_budget[:SPOT_CHECK_COUNT]:
            expected_granted = e["available_risk_budget"]
            ok = abs(e["granted_risk_amount"] - expected_granted) < 1e-6
            print(
                f"  {e['date']} {e['symbol']}: equity=${e['equity']:.2f}  committed_before=${e['committed_risk_before']:.4f}  "
                f"target=${e['target_risk_amount']:.4f}  available_budget=${e['available_risk_budget']:.4f}  "
                f"granted=${e['granted_risk_amount']:.4f}  {'OK' if ok else 'MISMATCH'}"
            )
        all_ok = all(abs(e["granted_risk_amount"] - e["available_risk_budget"]) < 1e-6 for e in shrunk_by_budget)
        print(f"\nall {len(shrunk_by_budget)} risk-budget-shrunk entries verified (granted_risk_amount == available_risk_budget): {'PASS' if all_ok else 'FAIL'}")
    else:
        print("no risk-budget-shrunk entries occurred in this run — see the report for what this does and doesn't imply.")

    # No-crash / no-over-allocation sanity check across the WHOLE run, not
    # just the spot-checked subset: at no accepted entry should committed
    # risk plus the newly granted risk_amount exceed the budget cap.
    over_budget = [
        e for e in entry_sizing_log
        if e["committed_risk_before"] + e["granted_risk_amount"] > e["equity"] * (total_risk_budget_pct / 100) + 1e-6
    ]
    print(
        f"\nover-budget-allocation check across all {len(entry_sizing_log)} accepted entries: "
        f"{'FAIL — ' + str(len(over_budget)) + ' violation(s)' if over_budget else 'PASS — no entry ever pushed committed risk above the budget cap'}"
    )

    # Structural cap sanity check: at no point in the trade list did more
    # than REDUCED_MAX_POSITIONS positions exist open simultaneously.
    max_concurrent_seen = 0
    open_count = 0
    events = sorted(
        [(t.entry_timestamp, "open") for t in trades] + [(t.exit_timestamp, "close") for t in trades]
    )
    for _, kind in events:
        open_count += 1 if kind == "open" else -1
        max_concurrent_seen = max(max_concurrent_seen, open_count)
    print(
        f"max concurrent open positions observed in the trade list: {max_concurrent_seen} "
        f"(cap was {REDUCED_MAX_POSITIONS}) -> {'PASS' if max_concurrent_seen <= REDUCED_MAX_POSITIONS else 'FAIL — cap violated'}"
    )


if __name__ == "__main__":
    main()
