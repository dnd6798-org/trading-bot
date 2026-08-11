"""
Track B (spec v23 §10.1): multi-asset ETF Donchian breakout + ATR trailing
stop, on Alpaca's commission-free stock/ETF product. First non-crypto
strategy backtest in this repo. Reuses the crypto ensemble's signal/exit/
sizing mechanism unchanged (CLAUDE.md finding 14, which spec v23 numbers
as "finding 15" — an already-flagged, pre-existing numbering drift between
this repo's session-numbered findings and the external spec, not a new
discrepancy introduced here) — only the universe, data source, and fee
model change.

Why this design (per kickoff instruction): finding 14/15 was the crypto
search's best result — it beat buy-and-hold net-of-fees but missed the
folds-consistency bar (3/5 vs. the required >=4/5), and its return was
concentrated in a handful of symbols. Two changes target that directly:
zero commission removes fee drag as a factor, and a genuinely diversified
multi-asset-class universe (equities, developed-ex-US equities, bonds,
gold, broad commodities, REITs — instead of BTC/ETH, which move together)
should give the folds-consistency measure a fairer test, since it's less
likely every asset sits in the same regime at the same time.

Universe (8 ETFs, spec v23 §10.1): SPY, QQQ, IWM, EFA, AGG, GLD, DBC, VNQ.

Signal — UNCHANGED from finding 14/15, only the universe/fees/sizing-input
data source changed, per instruction ("do not change the logic"):
  - Long entry: daily close breaks above the causal 100-day Donchian
    channel high (CHANNEL_LENGTH, compute_donchian_levels() from
    backtest_donchian.py, reused unchanged — window [i-100, i), current
    day excluded).
  - Exit: 3.0x ATR(14) trailing stop (ATR_MULTIPLIER), Chandelier-style,
    ratchets in the trade's favor only, using the PRIOR day's extreme-
    close/ATR so today's trigger check has no lookahead — identical
    formula to simulate_rotational_ensemble()'s exit block
    (backtest_donchian_ensemble.py), imported and reused directly, not
    reimplemented, since it's still in a fully reusable state (generic
    over symbol_data/universe_order, no crypto-specific assumption
    anywhere in its body).
  - Long-only (these ETFs are shortable on Alpaca, but per instruction
    changing universe+fees+long/short simultaneously would make a pass/
    fail hard to diagnose — short-side testing is an explicit follow-on,
    not this milestone).
  - Position sizing: spec §4.1's real 1%-of-equity-risk formula
    (position_size = risk_amount / (atr_multiplier * entry_ATR)), shrunk
    under a portfolio-level equal-risk-contribution budget when needed —
    simulate_rotational_ensemble()'s existing mechanism (finding 13/14),
    imported and reused directly. This is the first backtest since the
    original EMA crossover (findings 1-5) with a genuine ATR-based stop
    distance to size off — MACD D1H1, RSI mean-reversion, and (implicitly)
    GEM all lacked one and fell back to a flat 25%-of-equity notional cap
    instead; that fallback is NOT used here, per instruction.

KNOWN, EMPIRICALLY-CONFIRMED DEVIATION FROM THE ORIGINAL KICKOFF (decided
BEFORE any backtest ran, not in response to results — see the exchange
that produced this file): the kickoff specified a 2006-02-03 (DBC
inception) start, ~20 years of history. This account's Alpaca stock market
data is truncated at 2016-01-04 regardless of requested start date or feed
parameter (SIP and IEX both truncate identically) — confirmed empirically
for all 8 tickers, including GLD/AGG/QQQ whose real inception dates are
2004/2003/1999, so this is an account/data-plan tier limit, not a
per-symbol gap. Decision (user, before any numbers existed): proceed with
the available ~10.6-year window (2016-01-04 -> present) rather than pause
or blend in a second data vendor, and drop from 5 anchored folds to 3
(~3.2yr initial train + 3 test folds of roughly ~2.4yr each over the
shortened span, exact boundaries computed and printed at runtime, not
hardcoded) rather than risk the same fold-level sample-starvation problem
5 folds caused on this shorter span. IMPORTANT INTERPRETIVE CONSEQUENCE:
this window excludes the 2008 financial crisis and the 2020 COVID crash's
lead-in entirely — a result here is evidence about POST-2016 regimes only,
not the same breadth-of-regime claim the original 20-year design would
have supported. Flagged here and repeated in the runtime output, not
buried.

Fee model: 0% commission (Alpaca stock/ETF, commission-free) + 5bps/leg
slippage placeholder (ETF_SLIPPAGE_BPS) — wider than GEM's 2bps assumption
per instruction, since this universe includes less-liquid names (DBC,
VNQ) alongside deeply liquid ones (SPY, QQQ); an explicit judgment call,
not a measured number, same epistemic status as the crypto findings'
slippage placeholder.

Portfolio construction: MAX_CONCURRENT_POSITIONS = 8, i.e. equal to the
full universe size — a judgment call (the kickoff specified "up to N
concurrent open positions" without pinning N). At N=8 the slot-COUNT cap
never binds on its own (every symbol can always find a slot if it wants
one); TOTAL_PORTFOLIO_RISK_BUDGET_PCT (8 x 1% = 8%, same derivation as
finding 13/14) was believed at the time to be the only sizing constraint
that could actually shrink a trade, which was arguably the more honest
test of equal-risk-contribution sizing than letting a tight slot cap do
double duty as an implicit risk control the way the crypto milestones'
narrower N/universe ratio did.

**CORRECTION (Track B risk-budget stress-test milestone, spec v29
§10.1, run after this backtest's verdict was already locked in): the
claim above — that the risk budget is the only thing that can shrink a
trade — was WRONG, discovered only once the new `entry_sizing_log`
instrumentation made it visible.** `NOTIONAL_SANITY_CAP_PCT` (100%,
backtest_donchian_ensemble.py), described everywhere in this codebase as
a "loose... essentially never binds for these liquid symbols" leverage
backstop, in fact bound on **13 of AGG's 15 total trades (87%) in this
exact backtest** — every one of those 13 was sized to EXACTLY 100% of
account equity in AGG alone, not the 1%-of-equity risk-based size the
strategy's own design intends. Root cause: AGG (bonds) has a very small
ATR relative to its price, so the risk-based formula
(position_size = risk_amount / (ATR_MULTIPLIER * ATR)) demands a very
large position to hit a $100-scale 1%-equity risk target off a tiny stop
distance — the notional backstop is not a rare edge case for this
symbol, it is AGG's normal, silently-operating sizing path. This does
NOT change any trade that was taken or Track B's reported returns (the
resize logic itself computed correctly — see the stress-test milestone's
report) and does NOT reopen Track B's passed verdict, but it does mean
the "worst-case ~8% aggregate risk exposure" mental model this docstring
and backtest_donchian_ensemble.py's both describe is incomplete: a
single AGG position could, and repeatedly did, consume 100% of account
notional on its own, which is a real concentration/leverage
consideration for anything built on top of this strategy (execution.py,
guardrail rescaling) — flagged for that future work, not resolved here.

NEW THIS MILESTONE, not part of any crypto finding: a Pattern Day Trader
(PDT) / same-day round-trip check (check_no_same_day_round_trips()).
Crypto has no PDT restriction, so this was never relevant before; a
margin account under $25,000 loses trading privileges after 4+ day trades
(same-symbol buy+sell same calendar day) in 5 rolling business days. By
construction, simulate_rotational_ensemble()'s day-by-day loop processes
exits (using ONLY positions that were already open at the start of that
day's iteration) before entries, so a position opened today is never
exit-checked until a LATER date's iteration — a same-day round trip is
structurally impossible, not merely unlikely. This is verified against
the actual produced trade list at runtime (comparing each trade's entry
date to its exit date), not just asserted from the mechanism's design.

Reuses, unchanged, via direct import (not copy-paste):
  - compute_donchian_levels() (backtest_donchian.py)
  - compute_atr() (src/signal_generation.py)
  - resample_candles()/summarize()/_print_table()/ATR_PERIOD/
    DEFAULT_RISK_PER_TRADE_PCT (backtest.py) — resample_candles() isn't
    actually invoked (stock data arrives daily already), imported anyway
    only where genuinely used, see below.
  - compute_fold_boundaries() (backtest_walkforward.py)
  - EnsembleTrade, simulate_rotational_ensemble(),
    slice_ensemble_trades_by_folds(), per_symbol_diagnostics(),
    compute_buy_and_hold_symbol_return(),
    compute_buy_and_hold_portfolio_return(), PAPER_VALIDATION_CAPITAL,
    THIN_FOLD_TRADE_THRESHOLD (backtest_donchian_ensemble.py) — all fully
    generic over symbol_data/universe_order already, no crypto-specific
    assumption in any of their bodies, so none needed modification.

New in this file: fetch_historical_stock_candles() is called from
src/data_ingestion.py (not this file) — see that module for the fetch
itself. This file adds compute_channel_long_entry_indices() (a thin,
locally-parameterized wrapper — the crypto file's own version of this
function hardcodes its CHANNEL_LENGTH as a module global rather than a
parameter, so it wasn't imported directly to avoid a fragile cross-file
global-coupling dependency), build_symbol_series() (stock-daily variant
of the crypto file's same-named function — no hourly-to-daily resample
step needed), and check_no_same_day_round_trips().

Usage:
    python scripts/backtest_etf_donchian.py
    python scripts/backtest_etf_donchian.py --max-positions 8 --atr-multiplier 3.0
"""
import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data_ingestion import fetch_historical_stock_candles
from src.signal_generation import compute_atr
from scripts.backtest import (
    summarize,
    _print_table,
    ATR_PERIOD,
    DEFAULT_RISK_PER_TRADE_PCT,
)
from scripts.backtest_donchian import compute_donchian_levels
from scripts.backtest_walkforward import compute_fold_boundaries
from scripts.backtest_donchian_ensemble import (
    EnsembleTrade,
    simulate_rotational_ensemble,
    slice_ensemble_trades_by_folds,
    per_symbol_diagnostics,
    compute_buy_and_hold_symbol_return,
    compute_buy_and_hold_portfolio_return,
    PAPER_VALIDATION_CAPITAL,
    THIN_FOLD_TRADE_THRESHOLD,
)

UNIVERSE = ["SPY", "QQQ", "IWM", "EFA", "AGG", "GLD", "DBC", "VNQ"]  # spec v23 §10.1
CHANNEL_LENGTH = 100   # unchanged from finding 14/15 — see module docstring
ATR_MULTIPLIER = 3.0   # unchanged from finding 14/15 — see module docstring
MAX_CONCURRENT_POSITIONS = 8  # = universe size, a judgment call — see module docstring
TOTAL_PORTFOLIO_RISK_BUDGET_PCT = MAX_CONCURRENT_POSITIONS * DEFAULT_RISK_PER_TRADE_PCT

# Commission-free stock/ETF product (Alpaca) — the only fee-model change
# from the crypto findings' 0.25%/leg taker fee. Slippage widened from
# GEM's 2bps to 5bps per instruction (DBC/VNQ are less liquid than the
# core equity ETFs in this universe) — an explicit judgment call, not a
# measured number.
ETF_COMMISSION_PCT = 0.0
ETF_SLIPPAGE_BPS = 5.0

# Deviation from the crypto milestones' 5-fold/365-day-anchor default —
# see module docstring's "KNOWN, EMPIRICALLY-CONFIRMED DEVIATION" section.
NUM_FOLDS = 3
INITIAL_TRAIN_DAYS = 365

# Requested per the original kickoff (DBC's actual inception) — the
# account-level 2016-01-04 truncation means this is NOT what the fetch
# will actually return; see module docstring. Kept as the requested start
# rather than hardcoded to 2016 so a future account/data-plan upgrade
# would pick up more history automatically, without a code change.
REQUESTED_START = datetime(2006, 2, 3, tzinfo=timezone.utc)


def compute_channel_long_entry_indices(candles, channel_length=CHANNEL_LENGTH):
    """
    Long entry indices where close breaks above the causal channel_length-
    day Donchian high — same rule as backtest_donchian_ensemble.py's
    function of the same name, reparameterized on channel_length rather
    than reading a module global, so this file doesn't depend on that
    file's CHANNEL_LENGTH staying at 100.
    """
    upper, _ = compute_donchian_levels(candles, channel_length)
    atr = compute_atr(candles, period=ATR_PERIOD)

    entry_indices = set()
    for i in range(len(candles)):
        if atr[i] is None:
            continue
        if upper[i] is not None and candles[i].close > upper[i]:
            entry_indices.add(i)
    return entry_indices, atr


def build_symbol_series(symbol, start, end):
    """
    Fetches this symbol's daily history directly (Alpaca serves stock
    daily bars natively — no hourly-fetch-then-resample step the crypto
    build_symbol_series() needed) and precomputes entry signal indices,
    ATR(14), and a date-string -> index map, same shape as the crypto
    ensemble's symbol_data dicts so simulate_rotational_ensemble() and the
    other imported ensemble functions work unmodified.
    """
    candles = fetch_historical_stock_candles(symbol, start, end)
    if not candles:
        return None
    entry_indices, atr = compute_channel_long_entry_indices(candles)
    date_index = {c.timestamp[:10]: i for i, c in enumerate(candles)}
    return {
        "symbol": symbol,
        "candles": candles,
        "atr": atr,
        "entry_indices": entry_indices,
        "date_index": date_index,
    }


def check_no_same_day_round_trips(trades):
    """
    PDT guard (new this milestone — crypto has no PDT restriction, see
    module docstring). Returns the list of any trades whose entry and
    exit fall on the same calendar date — should always be empty by
    construction (simulate_rotational_ensemble() processes exits, using
    only positions already open at the start of that day's iteration,
    before entries), but verified against the actual trade list rather
    than assumed from the mechanism's design.
    """
    return [t for t in trades if t.entry_timestamp[:10] == t.exit_timestamp[:10]]


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--symbols", nargs="+", default=UNIVERSE)
    parser.add_argument("--max-positions", type=int, default=MAX_CONCURRENT_POSITIONS)
    parser.add_argument("--atr-multiplier", type=float, default=ATR_MULTIPLIER)
    parser.add_argument("--folds", type=int, default=NUM_FOLDS)
    parser.add_argument("--initial-train-days", type=int, default=INITIAL_TRAIN_DAYS)
    return parser.parse_args()


def main():
    args = parse_args()
    end = datetime.now(timezone.utc) - timedelta(minutes=20)  # SIP recent-data embargo, same convention as backtest.py's crypto settle delay

    print(f"=== Track B: 8-ETF rotational Donchian ensemble (100d channel + 3.0x ATR stop, daily entries, risk-budget sizing — ported from finding 14/15) ===")
    print(f"requested start: {REQUESTED_START.date()} (DBC inception) — see module docstring for the confirmed 2016-01-04 account-level data floor")
    symbol_data = {}
    for symbol in args.symbols:
        series = build_symbol_series(symbol, REQUESTED_START, end)
        if series is None:
            print(f"{symbol}: no candle data returned, excluding from this run")
            continue
        symbol_data[symbol] = series
        first, last = series["candles"][0], series["candles"][-1]
        print(f"  {symbol}: {first.timestamp[:10]} -> {last.timestamp[:10]}  ({len(series['candles'])} daily candles, {len(series['entry_indices'])} raw long-entry signals)")

    universe_order = [s for s in args.symbols if s in symbol_data]
    calendar = sorted(set().union(*(s["date_index"].keys() for s in symbol_data.values())))
    actual_start = datetime.fromisoformat(calendar[0]).replace(tzinfo=timezone.utc)
    actual_end = datetime.fromisoformat(calendar[-1]).replace(tzinfo=timezone.utc)
    folds = compute_fold_boundaries(
        actual_start, actual_end, num_folds=args.folds, initial_train_days=args.initial_train_days
    )
    total_risk_budget_pct = args.max_positions * DEFAULT_RISK_PER_TRADE_PCT

    print(f"\nshared calendar: {calendar[0]} -> {calendar[-1]}  ({len(calendar)} trading days, entries evaluated daily)")
    print(f"channel length: {CHANNEL_LENGTH}d  |  max concurrent positions: {args.max_positions}  |  ATR trailing-stop multiplier: {args.atr_multiplier}")
    print(f"total portfolio risk budget: {total_risk_budget_pct:.1f}%  |  per-trade risk target: {DEFAULT_RISK_PER_TRADE_PCT:.1f}%  |  capital: ${PAPER_VALIDATION_CAPITAL:,.0f}")
    print(f"fold boundaries (initial train {args.initial_train_days}d, then {args.folds} contiguous test windows) — EXACT boundaries, computed from actual fetched data:")
    for fold in folds:
        print(
            f"  fold {fold['fold']}: train {fold['train_start'].date()} -> {fold['train_end'].date()}"
            f"  |  test {fold['test_start'].date()} -> {fold['test_end'].date()}"
        )
    print(f"(fee model: {ETF_COMMISSION_PCT:.2f}% commission + {ETF_SLIPPAGE_BPS:.0f}bps slippage per leg)")
    print("NOTE: window excludes the 2008 financial crisis and the 2020 COVID crash's lead-in — see module docstring.")

    net_trades, net_curve, skipped_log = simulate_rotational_ensemble(
        symbol_data, universe_order, max_positions=args.max_positions, atr_multiplier=args.atr_multiplier,
        capital=PAPER_VALIDATION_CAPITAL, fee_pct=ETF_COMMISSION_PCT, slippage_bps=ETF_SLIPPAGE_BPS,
    )
    gross_trades, gross_curve, _ = simulate_rotational_ensemble(
        symbol_data, universe_order, max_positions=args.max_positions, atr_multiplier=args.atr_multiplier,
        capital=PAPER_VALIDATION_CAPITAL, fee_pct=0.0, slippage_bps=0.0,
    )

    net_folds, net_pooled = slice_ensemble_trades_by_folds(net_trades, net_curve, folds, PAPER_VALIDATION_CAPITAL)
    gross_folds, gross_pooled = slice_ensemble_trades_by_folds(gross_trades, gross_curve, folds, PAPER_VALIDATION_CAPITAL)

    print(f"\n=== Portfolio-level results ({len(net_trades)} total trades, {len(skipped_log)} signals skipped) ===")
    rows = []
    for fold, net, gross in zip(folds, net_folds, gross_folds):
        rows.append({
            "fold": fold["fold"],
            "test_window": f"{fold['test_start'].date()}..{fold['test_end'].date()}",
            "n": net["trade_count"],
            "flag": "THIN" if net["trade_count"] < THIN_FOLD_TRADE_THRESHOLD else "",
            "win%": f"{net['win_rate_pct']:.1f}",
            "net%": f"{net['total_return_pct']:.2f}",
            "gross%": f"{gross['total_return_pct']:.2f}",
            "max_dd%": f"{net['max_drawdown_pct']:.2f}",
        })
    rows.append({
        "fold": "POOLED",
        "test_window": f"{folds[0]['test_start'].date()}..{folds[-1]['test_end'].date()}",
        "n": net_pooled["trade_count"],
        "flag": "THIN" if net_pooled["trade_count"] < THIN_FOLD_TRADE_THRESHOLD else "",
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
        print(
            f"WARNING: fold(s) {thin_folds} have fewer than {THIN_FOLD_TRADE_THRESHOLD} trades — "
            f"read these as thin/inconclusive samples, not as clean pass/fail evidence."
        )

    positive = sum(1 for net in net_folds if net["trade_count"] > 0 and net["total_return_pct"] > 0)
    negative = sum(1 for net in net_folds if net["trade_count"] > 0 and net["total_return_pct"] < 0)
    flat_or_no_trades = len(net_folds) - positive - negative
    print(
        f"folds net-positive: {positive}/{len(net_folds)}  |  "
        f"net-negative: {negative}/{len(net_folds)}  |  "
        f"flat/no-trades: {flat_or_no_trades}/{len(net_folds)}"
    )

    # PDT / same-day round-trip check — new this milestone, see module docstring.
    print(f"\n=== PDT / same-day round-trip check (new this milestone — crypto has no PDT restriction) ===")
    violations = check_no_same_day_round_trips(net_trades)
    if violations:
        print(f"FAIL: {len(violations)} trade(s) entered and exited on the same calendar day:")
        for v in violations[:10]:
            print(f"  {v.symbol}: entry {v.entry_timestamp}  exit {v.exit_timestamp}")
    else:
        print(f"PASS: 0 of {len(net_trades)} trades entered and exited on the same calendar day.")

    # Mandatory buy-and-hold comparison (CLAUDE.md, permanent requirement).
    print(f"\n=== Buy-and-hold benchmark (equal-weighted, buy-at-window-start/hold-to-window-end, no rebalancing) ===")
    bh_rows = []
    for fold in folds:
        test_start_date = fold["test_start"].date().isoformat()
        test_end_date = fold["test_end"].date().isoformat()
        bh_blend, _ = compute_buy_and_hold_portfolio_return(symbol_data, universe_order, test_start_date, test_end_date)
        bh_rows.append({
            "fold": fold["fold"],
            "test_window": f"{test_start_date}..{test_end_date}",
            "bh_8etf_blend%": f"{bh_blend:.2f}" if bh_blend is not None else "n/a",
        })
    pooled_test_start_date = folds[0]["test_start"].date().isoformat()
    pooled_test_end_date = folds[-1]["test_end"].date().isoformat()
    bh_blend_pooled, bh_by_symbol = compute_buy_and_hold_portfolio_return(symbol_data, universe_order, pooled_test_start_date, pooled_test_end_date)
    bh_rows.append({
        "fold": "POOLED",
        "test_window": f"{pooled_test_start_date}..{pooled_test_end_date}",
        "bh_8etf_blend%": f"{bh_blend_pooled:.2f}" if bh_blend_pooled is not None else "n/a",
    })
    _print_table(bh_rows, [
        ("fold", "fold"), ("test_window", "test_window"), ("bh_8etf_blend%", "bh_8etf_blend%"),
    ])
    print("  per-symbol pooled buy-and-hold %:")
    print("   ", ", ".join(f"{sym}={ret:.1f}%" for sym, ret in sorted(bh_by_symbol.items(), key=lambda kv: -kv[1])))
    print(
        f"\nstrategy pooled net-of-costs {net_pooled['total_return_pct']:.2f}%  vs.  "
        f"buy-and-hold 8-ETF equal-weight blend {bh_blend_pooled:.2f}%"
    )

    print(f"\n=== Per-symbol diagnostics (pooled from fold 1 test start onward, informational only — concentration check) ===")
    diag_rows = per_symbol_diagnostics(net_trades, folds[0]["test_start"].isoformat())
    _print_table(
        [{"symbol": r["symbol"], "n": r["trade_count"], "net_pnl": f"${r['net_pnl']:.2f}", "gross_pnl": f"${r['gross_pnl']:.2f}"} for r in diag_rows],
        [("symbol", "symbol"), ("n", "n"), ("net_pnl", "net_pnl"), ("gross_pnl", "gross_pnl")],
    )

    skipped_pooled = [s for s in skipped_log if s["date"] >= folds[0]["test_start"].isoformat()[:10]]
    print(f"\nskipped signals, pooled test period: {len(skipped_pooled)} of {len(skipped_log)} total")
    if skipped_pooled:
        by_reason = {}
        for s in skipped_pooled:
            by_reason[s["reason"]] = by_reason.get(s["reason"], 0) + 1
        print("  by reason:", ", ".join(f"{reason}={count}" for reason, count in sorted(by_reason.items(), key=lambda kv: -kv[1])))
        by_symbol_skips = {}
        for s in skipped_pooled:
            by_symbol_skips[s["symbol"]] = by_symbol_skips.get(s["symbol"], 0) + 1
        print("  by symbol:", ", ".join(f"{sym}={count}" for sym, count in sorted(by_symbol_skips.items(), key=lambda kv: -kv[1])))


if __name__ == "__main__":
    main()
