"""
ONE-OFF VERIFICATION — finding 13's required pre-code check (CLAUDE.md,
finding 13 "Required verification step"). Not meant to be maintained.

Finding 12's script (backtest_donchian_ensemble.py) never persisted
per-trade position-sizing data — only pooled/per-symbol summary numbers
were printed and recorded in CLAUDE.md. This script re-runs finding 12's
EXACT entry-sizing formula, UNCHANGED (copied verbatim from
simulate_rotational_ensemble() in backtest_donchian_ensemble.py — same
risk_amount = equity * 1%, position_size = risk_amount / (2.5 * ATR),
capped at 12.5% of equity notional), adding only an entry-time log of
notional $ and notional-as-%-of-equity per trade. No sizing LOGIC is
changed here — this is read-only diagnostics on finding 12's own formula,
run against the same $100 capital finding 12 actually used, to answer one
question: was sizing effectively flat (every trade near the 12.5% cap),
or did it vary meaningfully with each symbol's ATR, with the cap binding
only occasionally? That answer determines how big a change finding 13's
Part 2 (volatility-targeted sizing) actually needs to be.

Usage:
    python scripts/verify_finding12_sizing.py
"""
import sys
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.backtest import (
    DEFAULT_CAPITAL, DEFAULT_TAKER_FEE_PCT, DEFAULT_SLIPPAGE_BPS, DEFAULT_RISK_PER_TRADE_PCT,
)
from scripts.backtest_donchian_ensemble import (
    UNIVERSE, ATR_MULTIPLIER, MAX_CONCURRENT_POSITIONS, SLOT_MAX_POSITION_PCT,
    build_symbol_series,
)


def simulate_with_sizing_log(symbol_data, universe_order, max_positions, atr_multiplier,
                              capital, risk_pct, max_position_pct, fee_pct, slippage_bps):
    """
    Verbatim copy of simulate_rotational_ensemble()'s loop (same formula,
    same ordering, same tie-break) with one addition: an entry-time
    sizing_log entry per trade opened, recording notional $/%% and
    whether the 12.5% cap bound. No sizing behavior is changed.
    """
    cost_frac_per_leg = fee_pct / 100 + slippage_bps / 10000
    calendar = sorted(set().union(*(s["date_index"].keys() for s in symbol_data.values())))

    open_positions = {}
    equity = capital
    sizing_log = []

    for date in calendar:
        for symbol in list(open_positions.keys()):
            series = symbol_data[symbol]
            idx = series["date_index"].get(date)
            if idx is None:
                continue
            pos = open_positions[symbol]
            candle = series["candles"][idx]
            prior_atr = series["atr"][idx - 1] if idx > 0 and series["atr"][idx - 1] is not None else pos["entry_atr"]
            stop_price = pos["extreme_close"] - atr_multiplier * prior_atr
            hit_stop = candle.low <= stop_price
            is_last_candle = idx == len(series["candles"]) - 1
            if hit_stop or is_last_candle:
                exit_price = stop_price if hit_stop else candle.close
                gross_pnl = pos["position_size"] * (exit_price - pos["entry_price"])
                fees_paid = pos["position_size"] * (pos["entry_price"] + exit_price) * cost_frac_per_leg
                equity += gross_pnl - fees_paid
                del open_positions[symbol]
            else:
                pos["extreme_close"] = max(pos["extreme_close"], candle.close)

        for symbol in universe_order:
            if symbol in open_positions:
                continue
            series = symbol_data[symbol]
            idx = series["date_index"].get(date)
            if idx is None or idx not in series["entry_indices"]:
                continue
            if len(open_positions) >= max_positions:
                continue

            candle = series["candles"][idx]
            entry_atr = series["atr"][idx]
            if entry_atr is None or entry_atr <= 0:
                continue

            risk_amount = equity * (risk_pct / 100)
            stop_distance = atr_multiplier * entry_atr
            if stop_distance <= 0:
                continue
            position_size = risk_amount / stop_distance
            max_notional = equity * (max_position_pct / 100)
            uncapped_notional = position_size * candle.close
            capped = uncapped_notional > max_notional
            if capped:
                position_size = max_notional / candle.close

            actual_notional = position_size * candle.close
            sizing_log.append({
                "symbol": symbol,
                "date": date,
                "equity_at_entry": equity,
                "atr_at_entry": entry_atr,
                "notional": actual_notional,
                "notional_pct_of_equity": 100.0 * actual_notional / equity,
                "capped": capped,
            })

            open_positions[symbol] = {
                "entry_index": idx,
                "entry_timestamp": candle.timestamp,
                "entry_price": candle.close,
                "entry_atr": entry_atr,
                "extreme_close": candle.close,
                "position_size": position_size,
                "risk_amount": risk_amount,
            }

    return sizing_log


def main():
    end = datetime.now(timezone.utc) - timedelta(minutes=20)
    start = datetime(2021, 1, 3, tzinfo=timezone.utc)

    print(f"=== Finding 13 verification: re-deriving finding 12's actual per-trade sizing ({len(UNIVERSE)} symbols, ${DEFAULT_CAPITAL:.0f} capital, unchanged formula) ===")
    symbol_data = {}
    for symbol in UNIVERSE:
        series = build_symbol_series(symbol, start, end)
        if series is None:
            print(f"{symbol}: no candle data, excluding")
            continue
        symbol_data[symbol] = series
    universe_order = [s for s in UNIVERSE if s in symbol_data]

    sizing_log = simulate_with_sizing_log(
        symbol_data, universe_order,
        max_positions=MAX_CONCURRENT_POSITIONS, atr_multiplier=ATR_MULTIPLIER,
        capital=DEFAULT_CAPITAL, risk_pct=DEFAULT_RISK_PER_TRADE_PCT,
        max_position_pct=SLOT_MAX_POSITION_PCT,
        fee_pct=DEFAULT_TAKER_FEE_PCT, slippage_bps=DEFAULT_SLIPPAGE_BPS,
    )

    print(f"\n{len(sizing_log)} total entries opened over full history (2021-01-03 -> present)\n")

    by_symbol = {}
    for row in sizing_log:
        by_symbol.setdefault(row["symbol"], []).append(row)

    header = f"{'symbol':<10}{'n':>4}{'mean%':>9}{'min%':>9}{'max%':>9}{'stdev%':>9}{'capped':>9}"
    print(header)
    print("-" * len(header))
    overall_pcts = []
    for symbol in universe_order:
        rows = by_symbol.get(symbol, [])
        if not rows:
            print(f"{symbol:<10}{0:>4}{'--':>9}{'--':>9}{'--':>9}{'--':>9}{'--':>9}")
            continue
        pcts = [r["notional_pct_of_equity"] for r in rows]
        overall_pcts.extend(pcts)
        n_capped = sum(1 for r in rows if r["capped"])
        stdev = statistics.pstdev(pcts) if len(pcts) > 1 else 0.0
        print(f"{symbol:<10}{len(rows):>4}{statistics.mean(pcts):>9.2f}{min(pcts):>9.2f}{max(pcts):>9.2f}{stdev:>9.2f}{n_capped:>5}/{len(rows):<3}")

    print(f"\noverall: n={len(overall_pcts)}  mean={statistics.mean(overall_pcts):.2f}%  "
          f"min={min(overall_pcts):.2f}%  max={max(overall_pcts):.2f}%  "
          f"stdev={statistics.pstdev(overall_pcts):.2f}%  "
          f"capped={sum(1 for r in sizing_log if r['capped'])}/{len(sizing_log)}")

    print("\n=== BCH/USD vs XRP/USD detail ===")
    for symbol in ("BCH/USD", "XRP/USD"):
        rows = by_symbol.get(symbol, [])
        print(f"\n{symbol}: {len(rows)} entries")
        for r in rows:
            print(f"  {r['date']}  equity=${r['equity_at_entry']:.2f}  ATR={r['atr_at_entry']:.4f}  "
                  f"notional=${r['notional']:.2f}  ({r['notional_pct_of_equity']:.2f}% of equity)  capped={r['capped']}")


if __name__ == "__main__":
    main()
