"""
Backtest runner — validates the EMA/ATR crossover signal (spec §2) against
historical BTC/USD and ETH/USD 1h candle data before touching any live-loop
code (data_ingestion.py's live fetch, execution.py, position_management.py).

Answers the still-open calibration questions (playbook v6 §7):
  - Is 9/21 the right EMA pair, or does the data suggest otherwise?
  - What ATR multiplier for stop-loss/take-profit?

Usage:
    python scripts/backtest.py
    python scripts/backtest.py --calibration-days 180 --validation-days 60 --symbols BTC/USD
    python scripts/backtest.py --ema-pairs 9,21 12,26 --atr-multipliers 2 3
    python scripts/backtest.py --no-fees   # compare against zero transaction costs

Methodology:
  - The fetched range splits into a calibration period (default: first 270
    days) and a held-out validation period (default: last 90 days). Combos
    are swept and ranked on the calibration period ONLY; the top 2 per
    symbol are then re-evaluated on the validation period to check whether
    they hold up out-of-sample. Nothing in the calibration table should be
    treated as a real signal until it survives that validation step.
  - Both periods are simulated as one continuous walk-forward run — an
    open position and compounded equity carry across the calibration/
    validation boundary rather than resetting, since a live bot wouldn't
    reset either. Per-period stats (return, drawdown) are computed
    relative to that period's own starting equity, not the original
    capital, so validation reflects "does this combo keep working from
    here" rather than a re-blend with calibration performance.
  - Every combo is also run with fee_pct=0/slippage_bps=0 to report a
    gross-of-costs number alongside the net one, so fee drag is visible
    rather than baked silently into a single figure.

Transaction cost model:
  - fee_pct (default 0.25% per leg): Alpaca crypto's Tier 1 TAKER rate
    (0-$100k 30-day volume — where a $100 test account lives), per
    https://docs.alpaca.markets/us/docs/crypto-fees. Taker, not maker,
    because both entries (market-style crossover fill) and exits
    (stop-loss / take-profit) are assumed to cross the spread rather than
    rest on the book.
  - slippage_bps (default 5 bps per leg): NOT a published number — OHLCV
    bars carry no bid/ask, so this is a placeholder estimate for spread/
    slippage cost. Treat it as a knob to stress-test, not a measured fact.

Other mechanics, all simplifications specific to this offline backtest
(not the live pipeline):
  - Long-only (spec §2 v1; short handling is still open, playbook v6 §7).
  - One open position per symbol at a time — a signal firing while a
    position is already open is skipped rather than pyramided.
  - Stop-loss and take-profit are symmetric: both are `atr_multiplier *
    ATR` away from entry (1:1 reward:risk). This isn't a locked design
    choice, just the simplest way to isolate the multiplier being swept.
  - If a candle's high and low both cross the take-profit and stop-loss
    levels in the same bar, the stop is assumed to hit first (worst case
    — 1h bars can't tell us the intrabar path).
  - Each symbol is backtested independently against the full starting
    capital (spec §4.3's combined cross-symbol risk budget is a live
    guardrail, not a backtest concern here).
"""
import argparse
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # run directly: python scripts/backtest.py

from src.data_ingestion import fetch_historical_candles, TRADING_PAIRS
from src.signal_generation import compute_ema, compute_atr

DEFAULT_EMA_PAIRS = [(9, 21), (12, 26), (8, 17)]
DEFAULT_ATR_MULTIPLIERS = [1.5, 2.0, 2.5, 3.0]
DEFAULT_CALIBRATION_DAYS = 270
DEFAULT_VALIDATION_DAYS = 90
DEFAULT_CAPITAL = 100.0
TOP_N_FOR_VALIDATION = 2

# Alpaca crypto Tier 1 taker fee (docs.alpaca.markets/us/docs/crypto-fees),
# applied per leg (entry + exit). Slippage is an unmeasured placeholder —
# see module docstring.
DEFAULT_TAKER_FEE_PCT = 0.25
DEFAULT_SLIPPAGE_BPS = 5.0

# Position sizing below is a simplified, inline version of spec §4.1 (1%
# risk/trade, capped at 25% max notional) for backtest purposes only. It
# is NOT the guardrail enforcement path — once risk_filter.py's real
# implementation exists, check this against it so the two don't silently
# diverge on the same math.
DEFAULT_RISK_PER_TRADE_PCT = 1.0
DEFAULT_MAX_POSITION_PCT = 25.0

ATR_PERIOD = 14
VOLUME_LOOKBACK = 20


@dataclass
class Trade:
    entry_index: int
    exit_index: int
    entry_timestamp: str
    exit_timestamp: str
    entry_price: float
    exit_price: float
    exit_reason: str  # "stop" | "take_profit" | "eol"
    gross_pnl: float
    fees_paid: float
    pnl: float  # net of fees
    r_multiple: float


def _volume_confirms_series(candles, lookback=VOLUME_LOOKBACK):
    """
    Same semantics as signal_generation.volume_confirms (current volume >
    average of the preceding `lookback` candles), computed incrementally
    with a rolling sum instead of re-slicing per index — the O(n^2)
    slice-per-candle approach is too slow over a year of hourly bars.
    """
    volumes = [c.volume for c in candles]
    n = len(volumes)
    confirms = [False] * n
    if n <= lookback:
        return confirms

    window_sum = sum(volumes[:lookback])
    for i in range(lookback, n):
        confirms[i] = volumes[i] > (window_sum / lookback)
        window_sum += volumes[i] - volumes[i - lookback]
    return confirms


def compute_signal_indices(candles, ema_fast_period, ema_slow_period):
    """
    Indices where a long signal fires: fast EMA crosses above slow EMA,
    confirmed by above-average volume. All three series (EMA fast, EMA
    slow, ATR) are causal — index i only depends on candles[0..i], so this
    is walk-forward correct without needing to re-run per-slice.
    """
    closes = [c.close for c in candles]
    ema_fast = compute_ema(closes, ema_fast_period)
    ema_slow = compute_ema(closes, ema_slow_period)
    atr = compute_atr(candles, period=ATR_PERIOD)
    vol_confirms = _volume_confirms_series(candles)

    indices = []
    for i in range(1, len(candles)):
        if None in (ema_fast[i], ema_slow[i], ema_fast[i - 1], ema_slow[i - 1], atr[i]):
            continue
        crossed_up = ema_fast[i - 1] <= ema_slow[i - 1] and ema_fast[i] > ema_slow[i]
        if crossed_up and vol_confirms[i]:
            indices.append(i)
    return indices, atr


def simulate(
    candles,
    ema_fast_period,
    ema_slow_period,
    atr_multiplier,
    capital=DEFAULT_CAPITAL,
    risk_pct=DEFAULT_RISK_PER_TRADE_PCT,
    max_position_pct=DEFAULT_MAX_POSITION_PCT,
    fee_pct=DEFAULT_TAKER_FEE_PCT,
    slippage_bps=DEFAULT_SLIPPAGE_BPS,
):
    """
    Walk-forward simulation of one (ema_pair, atr_multiplier) combo over
    one symbol's candles, continuous across the full range passed in
    (calibration/validation splitting happens post-hoc on the returned
    trades/equity_curve — see run_walk_forward).
    """
    signal_indices, atr = compute_signal_indices(candles, ema_fast_period, ema_slow_period)
    cost_frac_per_leg = fee_pct / 100 + slippage_bps / 10000

    trades = []
    equity = capital
    equity_curve = [equity]
    position_open_until = -1

    for i in signal_indices:
        if i <= position_open_until:
            continue  # already in a position — spec's one-position-per-symbol assumption

        entry_price = candles[i].close
        stop_distance = atr[i] * atr_multiplier
        if stop_distance <= 0:
            continue
        stop_price = entry_price - stop_distance
        take_profit_price = entry_price + stop_distance

        risk_amount = equity * (risk_pct / 100)
        position_size = risk_amount / stop_distance
        max_notional = equity * (max_position_pct / 100)
        notional = position_size * entry_price
        if notional > max_notional:
            position_size = max_notional / entry_price

        exit_price = None
        exit_reason = None
        exit_index = len(candles) - 1
        for j in range(i + 1, len(candles)):
            c = candles[j]
            hit_stop = c.low <= stop_price
            hit_tp = c.high >= take_profit_price
            if hit_stop:
                exit_price = stop_price  # stop assumed to hit first if both trigger in-bar
                exit_reason = "stop"
            elif hit_tp:
                exit_price = take_profit_price
                exit_reason = "take_profit"
            if exit_price is not None:
                exit_index = j
                break

        if exit_price is None:
            # Signal never resolved within available data — mark to the last close.
            exit_price = candles[-1].close
            exit_reason = "eol"

        gross_pnl = position_size * (exit_price - entry_price)
        fees_paid = position_size * (entry_price + exit_price) * cost_frac_per_leg
        pnl = gross_pnl - fees_paid

        equity += pnl
        equity_curve.append(equity)
        trades.append(Trade(
            entry_index=i,
            exit_index=exit_index,
            entry_timestamp=candles[i].timestamp,
            exit_timestamp=candles[exit_index].timestamp,
            entry_price=entry_price,
            exit_price=exit_price,
            exit_reason=exit_reason,
            gross_pnl=gross_pnl,
            fees_paid=fees_paid,
            pnl=pnl,
            r_multiple=pnl / risk_amount if risk_amount else 0.0,
        ))
        position_open_until = exit_index

    return trades, equity_curve


def summarize(trades, equity_curve, starting_capital):
    if not trades:
        return {
            "trade_count": 0,
            "win_rate_pct": 0.0,
            "total_return_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "avg_r_multiple": 0.0,
            "stop_rate_pct": 0.0,
            "take_profit_rate_pct": 0.0,
            "eol_rate_pct": 0.0,
            "avg_holding_bars": 0.0,
            "total_fees_paid": 0.0,
        }

    wins = [t for t in trades if t.pnl > 0]
    ending_capital = equity_curve[-1]

    peak = equity_curve[0]
    max_drawdown_pct = 0.0
    for e in equity_curve:
        peak = max(peak, e)
        drawdown_pct = (peak - e) / peak * 100 if peak > 0 else 0.0
        max_drawdown_pct = max(max_drawdown_pct, drawdown_pct)

    n = len(trades)
    return {
        "trade_count": n,
        "win_rate_pct": len(wins) / n * 100,
        "total_return_pct": (ending_capital - starting_capital) / starting_capital * 100,
        "max_drawdown_pct": max_drawdown_pct,
        "avg_r_multiple": sum(t.r_multiple for t in trades) / n,
        "stop_rate_pct": sum(1 for t in trades if t.exit_reason == "stop") / n * 100,
        "take_profit_rate_pct": sum(1 for t in trades if t.exit_reason == "take_profit") / n * 100,
        "eol_rate_pct": sum(1 for t in trades if t.exit_reason == "eol") / n * 100,
        "avg_holding_bars": sum(t.exit_index - t.entry_index for t in trades) / n,
        "total_fees_paid": sum(t.fees_paid for t in trades),
    }


def diagnose(candles, ema_fast_period=9, ema_slow_period=21):
    """
    Symbol-level context independent of any one combo's P&L — helps
    separate "the signal doesn't suit this symbol's price action" from
    "fees/whipsaws are the problem" (playbook v6 §7).
    """
    closes = [c.close for c in candles]
    atr = compute_atr(candles, period=ATR_PERIOD)
    atr_pct_values = [atr[i] / candles[i].close * 100 for i in range(len(candles)) if atr[i] is not None]
    signal_indices, _ = compute_signal_indices(candles, ema_fast_period, ema_slow_period)

    return {
        "buy_hold_return_pct": (closes[-1] - closes[0]) / closes[0] * 100,
        "avg_atr_pct_of_price": sum(atr_pct_values) / len(atr_pct_values) if atr_pct_values else 0.0,
        "raw_crossover_signal_count": len(signal_indices),
        "candle_count": len(candles),
    }


def run_walk_forward(
    candles,
    cutoff_timestamp,
    ema_fast_period,
    ema_slow_period,
    atr_multiplier,
    capital=DEFAULT_CAPITAL,
    fee_pct=DEFAULT_TAKER_FEE_PCT,
    slippage_bps=DEFAULT_SLIPPAGE_BPS,
):
    """
    Runs one continuous simulate() pass, then splits the resulting trades
    into calibration (entry before cutoff_timestamp) and validation (entry
    at/after cutoff_timestamp) subsets, each summarized relative to its own
    starting equity so validation reflects "does this keep working from
    here," not a re-blend with calibration performance.
    """
    trades, equity_curve = simulate(
        candles, ema_fast_period, ema_slow_period, atr_multiplier,
        capital=capital, fee_pct=fee_pct, slippage_bps=slippage_bps,
    )
    split_idx = sum(1 for t in trades if t.entry_timestamp < cutoff_timestamp)

    calib_trades = trades[:split_idx]
    calib_curve = equity_curve[:split_idx + 1]
    valid_trades = trades[split_idx:]
    valid_curve = equity_curve[split_idx:]

    calibration = summarize(calib_trades, calib_curve, calib_curve[0])
    validation = summarize(valid_trades, valid_curve, valid_curve[0] if valid_curve else capital)
    return calibration, validation


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--symbols", nargs="+", default=TRADING_PAIRS)
    parser.add_argument("--calibration-days", type=int, default=DEFAULT_CALIBRATION_DAYS)
    parser.add_argument("--validation-days", type=int, default=DEFAULT_VALIDATION_DAYS)
    parser.add_argument("--capital", type=float, default=DEFAULT_CAPITAL)
    parser.add_argument(
        "--ema-pairs", nargs="+", default=None,
        help="e.g. --ema-pairs 9,21 12,26 (defaults to a small sweep)",
    )
    parser.add_argument("--atr-multipliers", nargs="+", type=float, default=DEFAULT_ATR_MULTIPLIERS)
    parser.add_argument("--fee-pct", type=float, default=DEFAULT_TAKER_FEE_PCT, help="per-leg taker fee, percent")
    parser.add_argument("--slippage-bps", type=float, default=DEFAULT_SLIPPAGE_BPS, help="per-leg slippage estimate, bps")
    parser.add_argument("--no-fees", action="store_true", help="zero out fees/slippage for comparison")
    args = parser.parse_args()

    if args.ema_pairs:
        args.ema_pairs = [tuple(int(p) for p in pair.split(",")) for pair in args.ema_pairs]
    else:
        args.ema_pairs = DEFAULT_EMA_PAIRS
    if args.no_fees:
        args.fee_pct = 0.0
        args.slippage_bps = 0.0
    return args


def _print_table(rows, columns):
    widths = {key: max(len(label), *(len(f"{row[key]}") for row in rows)) + 2 if rows else len(label) + 2
              for key, label in columns}
    print("".join(f"{label:<{widths[key]}}" for key, label in columns))
    print("-" * sum(widths.values()))
    for row in rows:
        print("".join(f"{row[key]:<{widths[key]}}" for key, _ in columns))


def main():
    args = parse_args()
    end = datetime.now(timezone.utc) - timedelta(minutes=20)  # crypto bars need a short settle delay
    total_days = args.calibration_days + args.validation_days
    start = end - timedelta(days=total_days)
    cutoff_ts = (end - timedelta(days=args.validation_days)).isoformat()

    for symbol in args.symbols:
        candles = fetch_historical_candles(symbol, start, end)
        if not candles:
            print(f"{symbol}: no candle data returned, skipping")
            continue

        diag = diagnose(candles)
        print(f"\n=== {symbol} ===")
        print(
            f"buy&hold return over period: {diag['buy_hold_return_pct']:.2f}%  |  "
            f"avg ATR as % of price: {diag['avg_atr_pct_of_price']:.2f}%  |  "
            f"raw 9/21 crossover signals: {diag['raw_crossover_signal_count']} "
            f"over {diag['candle_count']} candles"
        )

        calibration_rows = []
        for ema_fast, ema_slow in args.ema_pairs:
            for atr_multiplier in args.atr_multipliers:
                calib_net, _ = run_walk_forward(
                    candles, cutoff_ts, ema_fast, ema_slow, atr_multiplier,
                    capital=args.capital, fee_pct=args.fee_pct, slippage_bps=args.slippage_bps,
                )
                calib_gross, _ = run_walk_forward(
                    candles, cutoff_ts, ema_fast, ema_slow, atr_multiplier,
                    capital=args.capital, fee_pct=0.0, slippage_bps=0.0,
                )
                calibration_rows.append({
                    "ema": f"{ema_fast}/{ema_slow}", "ema_pair": (ema_fast, ema_slow),
                    "atr_mult": atr_multiplier,
                    "trades": calib_net["trade_count"],
                    "win%": f"{calib_net['win_rate_pct']:.1f}",
                    "net_return%": f"{calib_net['total_return_pct']:.2f}",
                    "gross_return%": f"{calib_gross['total_return_pct']:.2f}",
                    "maxdd%": f"{calib_net['max_drawdown_pct']:.2f}",
                    "avg_R": f"{calib_net['avg_r_multiple']:.2f}",
                    "stop%": f"{calib_net['stop_rate_pct']:.0f}",
                    "tp%": f"{calib_net['take_profit_rate_pct']:.0f}",
                    "_net_return_raw": calib_net["total_return_pct"],
                })

        print(f"\n-- calibration period (first {args.calibration_days}d) --")
        print(f"(fee model: {args.fee_pct:.2f}% taker + {args.slippage_bps:.0f}bps slippage per leg, net vs. gross shown)")
        _print_table(calibration_rows, [
            ("ema", "ema"), ("atr_mult", "atr_mult"), ("trades", "trades"), ("win%", "win%"),
            ("net_return%", "net_return%"), ("gross_return%", "gross_return%"),
            ("maxdd%", "maxdd%"), ("avg_R", "avg_R"), ("stop%", "stop%"), ("tp%", "tp%"),
        ])

        top_combos = sorted(
            (r for r in calibration_rows if r["trades"] > 0),
            key=lambda r: r["_net_return_raw"], reverse=True,
        )[:TOP_N_FOR_VALIDATION]

        if not top_combos:
            print(f"\nNo combo took any trades in the calibration period for {symbol} — skipping validation.")
            continue

        print(f"\n-- out-of-sample validation (last {args.validation_days}d), top {len(top_combos)} calibration combos --")
        validation_rows = []
        for combo in top_combos:
            ema_fast, ema_slow = combo["ema_pair"]
            _, valid_net = run_walk_forward(
                candles, cutoff_ts, ema_fast, ema_slow, combo["atr_mult"],
                capital=args.capital, fee_pct=args.fee_pct, slippage_bps=args.slippage_bps,
            )
            _, valid_gross = run_walk_forward(
                candles, cutoff_ts, ema_fast, ema_slow, combo["atr_mult"],
                capital=args.capital, fee_pct=0.0, slippage_bps=0.0,
            )
            validation_rows.append({
                "ema": combo["ema"], "atr_mult": combo["atr_mult"],
                "trades": valid_net["trade_count"],
                "win%": f"{valid_net['win_rate_pct']:.1f}",
                "net_return%": f"{valid_net['total_return_pct']:.2f}",
                "gross_return%": f"{valid_gross['total_return_pct']:.2f}",
                "maxdd%": f"{valid_net['max_drawdown_pct']:.2f}",
                "avg_R": f"{valid_net['avg_r_multiple']:.2f}",
            })
        _print_table(validation_rows, [
            ("ema", "ema"), ("atr_mult", "atr_mult"), ("trades", "trades"), ("win%", "win%"),
            ("net_return%", "net_return%"), ("gross_return%", "gross_return%"),
            ("maxdd%", "maxdd%"), ("avg_R", "avg_R"),
        ])


if __name__ == "__main__":
    main()
