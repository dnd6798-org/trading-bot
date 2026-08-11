"""
Track B notional-concentration investigation (spec v30 §10.2). Diagnostic
and fix-design work, NOT a re-test of Track B's already-passed verdict
(pooled net-of-costs +73.64%, 3/3 folds net-positive, see CLAUDE.md
"Track B findings") — follows directly from the risk-budget stress-test
milestone (spec v29 §10.1, commit 23f8e02), which found the
NOTIONAL_SANITY_CAP_PCT backstop (100% of equity,
backtest_donchian_ensemble.py) — documented everywhere in this codebase
as a rare "near-zero-ATR edge case" — actually bound on 13 of AGG's 15
total trades in Track B's real, original 8-slot backtest, each one sized
to exactly 100% of account equity.

This script answers the first two of this milestone's four required
questions (the other two — the cap fix and the sensitivity rerun — are
scripts/backtest_etf_donchian.py's new --max-position-notional-pct flag,
see that file and CLAUDE.md for the rerun results):

  1. FULL QUANTIFICATION across all 8 Track B symbols (not just AGG) over
     the complete real 2016-01-04 -> present history: how often does the
     notional backstop bind, and at what severity (both the % of equity
     it was actually capped to, which is mechanically always ~100% by
     construction whenever it binds, and — more informatively — what %
     of equity the risk-based formula NATURALLY wanted before any cap
     trimmed it, via the new entry_sizing_log
     uncapped_notional_pct_of_equity field, backtest_donchian_
     ensemble.py). Also reports the same distribution for every symbol's
     UNCAPPED trades, to see how close other symbols came without
     actually tripping the 100% cap.
  2. ROOT-CAUSE CONFIRMATION: the working diagnosis from the prior
     milestone was that a low ATR-to-price ratio, combined with the
     ATR_MULTIPLIER trailing-stop distance, causes the risk-based sizing
     formula (position_size = risk_amount / (ATR_MULTIPLIER * ATR)) to
     demand an oversized position. This is checked two ways: (a)
     algebraically — notional_pct_of_equity for an UNCAPPED trade
     collapses to risk_pct / (ATR_MULTIPLIER * atr_to_price_fraction),
     i.e. inversely proportional to both the ATR-to-price ratio AND the
     multiplier — verified directly against real logged trades, not just
     asserted; (b) empirically — a rank correlation between each entry's
     atr_to_price_pct and its uncapped_notional_pct_of_equity across all
     8 symbols, which should be strongly negative if the diagnosis is
     right.

Reuses build_symbol_series()/UNIVERSE/REQUESTED_START/
PAPER_VALIDATION_CAPITAL/ATR_MULTIPLIER from backtest_etf_donchian.py and
simulate_rotational_ensemble() (with the entry_sizing_log instrumentation
added for the prior milestone, now extended with the notional/ATR fields
this milestone needed — see that function's docstring) from
backtest_donchian_ensemble.py, unchanged — no strategy logic is touched
here, only reporting. Runs Track B's ORIGINAL, unmodified configuration
(max_positions=8, total_risk_budget_pct=8%, notional_sanity_cap_pct=100%,
the default) — this is deliberately the exact setup that produced Track
B's passed verdict, not the reduced-cap setup the prior milestone used.

One-off script, not meant to be maintained — same convention as
scripts/select_universe.py, scripts/verify_finding12_sizing.py,
scripts/stress_test_track_b_risk_budget.py.

Usage:
    python scripts/quantify_track_b_notional_concentration.py
"""
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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

TRACK_B_MAX_POSITIONS = 8  # Track B's original, already-passed setting — equal to the full universe size
TRACK_B_RISK_BUDGET_PCT = 8.0  # = 8 slots x 1%, Track B's original setting
TRACK_B_NOTIONAL_CAP_PCT = 100.0  # Track B's original, already-passed setting — the backstop under investigation


def _pctile(values, p):
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * p
    f, c = int(k), min(int(k) + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def _spearman(xs, ys):
    """Spearman rank correlation, no scipy dependency (not in this repo's requirements)."""
    n = len(xs)
    if n < 2:
        return None
    rank_x = {v: r for r, v in enumerate(sorted(range(n), key=lambda i: xs[i]))}
    rank_y = {v: r for r, v in enumerate(sorted(range(n), key=lambda i: ys[i]))}
    rx = [rank_x[i] for i in range(n)]
    ry = [rank_y[i] for i in range(n)]
    mean_rx, mean_ry = sum(rx) / n, sum(ry) / n
    cov = sum((rx[i] - mean_rx) * (ry[i] - mean_ry) for i in range(n))
    var_x = sum((v - mean_rx) ** 2 for v in rx)
    var_y = sum((v - mean_ry) ** 2 for v in ry)
    if var_x == 0 or var_y == 0:
        return None
    return cov / (var_x * var_y) ** 0.5


def main():
    end = datetime.now(timezone.utc) - timedelta(minutes=20)  # SIP recent-data embargo, same convention as backtest_etf_donchian.py

    print("=== Track B notional-concentration quantification (spec v30 §10.2) ===")
    print("DIAGNOSTIC ONLY — does not reopen Track B's passed verdict (pooled net +73.64%, 3/3 folds, see CLAUDE.md).")
    print(f"Running Track B's ORIGINAL configuration: max_positions={TRACK_B_MAX_POSITIONS}, "
          f"risk_budget={TRACK_B_RISK_BUDGET_PCT:.1f}%, notional_cap={TRACK_B_NOTIONAL_CAP_PCT:.1f}% (the backstop under investigation).\n")

    symbol_data = {}
    for symbol in UNIVERSE:
        series = build_symbol_series(symbol, REQUESTED_START, end)
        if series is None:
            print(f"{symbol}: no candle data returned, excluding from this run")
            continue
        symbol_data[symbol] = series
    universe_order = [s for s in UNIVERSE if s in symbol_data]

    entry_sizing_log = []
    trades, equity_curve, skipped_log = simulate_rotational_ensemble(
        symbol_data, universe_order,
        max_positions=TRACK_B_MAX_POSITIONS, atr_multiplier=ATR_MULTIPLIER,
        capital=PAPER_VALIDATION_CAPITAL, total_risk_budget_pct=TRACK_B_RISK_BUDGET_PCT,
        notional_sanity_cap_pct=TRACK_B_NOTIONAL_CAP_PCT,
        fee_pct=ETF_COMMISSION_PCT, slippage_bps=ETF_SLIPPAGE_BPS,
        entry_sizing_log=entry_sizing_log,
    )
    print(f"{len(trades)} trades taken, {len(entry_sizing_log)} entries logged, {len(skipped_log)} signals skipped "
          f"({ {r['reason'] for r in skipped_log} or 'none'}).")
    print("(sanity check: this should reproduce Track B's original trade count — 219 total trades per CLAUDE.md 'Track B findings' 1.)\n")

    # --- Question 1: full 8-symbol binding frequency/severity table --------
    print("=== Q1: notional-backstop binding frequency & severity, all 8 symbols ===")
    rows = []
    for symbol in universe_order:
        sym_entries = [e for e in entry_sizing_log if e["symbol"] == symbol]
        if not sym_entries:
            continue
        capped = [e for e in sym_entries if e["shrunk_by_notional_cap"]]
        uncapped_pcts = [e["uncapped_notional_pct_of_equity"] for e in sym_entries]
        rows.append({
            "symbol": symbol,
            "n_entries": len(sym_entries),
            "n_capped": len(capped),
            "pct_capped": f"{100 * len(capped) / len(sym_entries):.1f}%",
            "mean_uncapped_notional_pct": f"{statistics.mean(uncapped_pcts):.1f}%",
            "median_uncapped_notional_pct": f"{statistics.median(uncapped_pcts):.1f}%",
            "max_uncapped_notional_pct": f"{max(uncapped_pcts):.1f}%",
            "mean_atr_to_price_pct": f"{statistics.mean(e['atr_to_price_pct'] for e in sym_entries):.3f}%",
        })
    header = f"{'symbol':8} {'n':>4} {'capped':>7} {'%cap':>7} {'mean_unc%':>10} {'med_unc%':>9} {'max_unc%':>9} {'mean_atr/px%':>13}"
    print(header)
    for r in sorted(rows, key=lambda r: -r["n_capped"]):
        print(f"{r['symbol']:8} {r['n_entries']:>4} {r['n_capped']:>7} {r['pct_capped']:>7} "
              f"{r['mean_uncapped_notional_pct']:>10} {r['median_uncapped_notional_pct']:>9} "
              f"{r['max_uncapped_notional_pct']:>9} {r['mean_atr_to_price_pct']:>13}")

    total_capped = sum(r["n_capped"] for r in rows)
    other_symbols_capped = [r for r in rows if r["symbol"] != "AGG" and r["n_capped"] > 0]
    print(f"\ntotal notional-backstop binds across all 8 symbols: {total_capped}")
    print(f"symbols other than AGG that ever hit the cap: {[r['symbol'] for r in other_symbols_capped] or 'NONE'}")

    # How close did OTHER symbols get, even without tripping the cap? —
    # answers "is AGG uniquely affected, or do others approach it during
    # their own low-vol stretches?"
    print("\nhow close each non-AGG symbol's uncapped sizing got to the 100% cap (95th percentile, informational):")
    for symbol in universe_order:
        if symbol == "AGG":
            continue
        pcts = [e["uncapped_notional_pct_of_equity"] for e in entry_sizing_log if e["symbol"] == symbol]
        if pcts:
            print(f"  {symbol}: p50={_pctile(pcts, 0.5):.1f}%  p95={_pctile(pcts, 0.95):.1f}%  max={max(pcts):.1f}%")

    # --- Question 2: root-cause confirmation --------------------------------
    print("\n=== Q2: root-cause confirmation (ATR-to-price ratio driving oversized notional) ===")
    # (a) Algebraic check against real logged entries: for trades whose
    # risk_amount was NOT shrunk by the risk budget (target risk fully
    # granted), notional_pct_of_equity (uncapped) should equal
    # risk_pct / (ATR_MULTIPLIER * atr_to_price_fraction) exactly.
    clean_entries = [e for e in entry_sizing_log if not e["shrunk_by_risk_budget"]]
    risk_pct = 1.0  # DEFAULT_RISK_PER_TRADE_PCT, Track B's per-trade target, unchanged
    max_abs_err = 0.0
    for e in clean_entries:
        atr_to_price_fraction = e["atr_to_price_pct"] / 100
        predicted_notional_pct = risk_pct / (ATR_MULTIPLIER * atr_to_price_fraction)
        err = abs(predicted_notional_pct - e["uncapped_notional_pct_of_equity"])
        max_abs_err = max(max_abs_err, err)
    print(
        f"(a) algebraic check across {len(clean_entries)} entries with unshrunk risk "
        f"(notional_pct_of_equity == risk_pct / (ATR_MULTIPLIER * atr_to_price_fraction)): "
        f"max abs error = {max_abs_err:.6f} percentage points -> {'CONFIRMED' if max_abs_err < 1e-6 else 'MISMATCH'}"
    )

    # (b) Empirical: rank correlation between atr_to_price_pct and
    # uncapped_notional_pct_of_equity across all logged entries — should
    # be strongly negative (lower ATR-to-price -> higher notional demand).
    xs = [e["atr_to_price_pct"] for e in entry_sizing_log]
    ys = [e["uncapped_notional_pct_of_equity"] for e in entry_sizing_log]
    rho = _spearman(xs, ys)
    print(f"(b) empirical: Spearman rank correlation(atr_to_price_pct, uncapped_notional_pct_of_equity) across "
          f"{len(entry_sizing_log)} entries = {rho:.4f} -> {'CONFIRMED (strong negative)' if rho is not None and rho < -0.5 else 'weak/unclear'}")

    # (c) Trailing-stop-distance interaction: stop_distance =
    # ATR_MULTIPLIER * entry_atr appears directly in the denominator of
    # the notional formula above (via the algebraic identity in (a)) — a
    # WIDER multiplier (as Track B's 3.0x is, vs. the crypto ensemble's
    # earlier 2.5x) makes the stop distance LARGER, which makes the
    # oversized-notional effect SMALLER, not bigger, for a given ATR/price
    # ratio; a narrower multiplier would make this worse. Quantify directly:
    print(f"(c) trailing-stop-distance interaction: ATR_MULTIPLIER={ATR_MULTIPLIER} is a direct multiplicative "
          f"term in the same denominator as the ATR-to-price ratio (see (a)'s formula) — a SMALLER multiplier "
          f"would worsen the oversized-notional effect for the same ATR/price ratio, a LARGER one would ease it. "
          f"Not independently tunable from the ATR-to-price ratio's effect; both act on the same stop_distance term.")

    # AGG-specific detail, for the report.
    agg_entries = [e for e in entry_sizing_log if e["symbol"] == "AGG"]
    if agg_entries:
        agg_atr_pcts = [e["atr_to_price_pct"] for e in agg_entries]
        other_atr_pcts = [e["atr_to_price_pct"] for e in entry_sizing_log if e["symbol"] != "AGG"]
        print(f"\nAGG's mean ATR-to-price ratio: {statistics.mean(agg_atr_pcts):.3f}% "
              f"vs. all-other-symbols' mean: {statistics.mean(other_atr_pcts):.3f}% "
              f"({statistics.mean(other_atr_pcts) / statistics.mean(agg_atr_pcts):.1f}x higher)")


if __name__ == "__main__":
    main()
