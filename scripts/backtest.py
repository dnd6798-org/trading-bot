"""
Backtest runner — validates the EMA/ATR crossover signal (spec §2) against
historical BTC/USD and ETH/USD 1h candle data before touching any live-loop
code (data_ingestion.py's live fetch, execution.py, position_management.py).

Answers the still-open calibration questions (playbook v6 §7):
  - Is 9/21 the right EMA pair, or does the data suggest otherwise?
  - What ATR multiplier for stop-loss/take-profit?

Usage:
    python scripts/backtest.py
    python scripts/backtest.py --days 180 --symbols BTC/USD
    python scripts/backtest.py --ema-pairs 9,21 12,26 --atr-multipliers 2 3

Mechanics, all simplifications specific to this offline backtest (not the
live pipeline):
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
DEFAULT_DAYS = 365
DEFAULT_CAPITAL = 100.0

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
    pnl: float
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
):
    """Walk-forward simulation of one (ema_pair, atr_multiplier) combo over one symbol's candles."""
    signal_indices, atr = compute_signal_indices(candles, ema_fast_period, ema_slow_period)

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
        exit_index = len(candles) - 1
        for j in range(i + 1, len(candles)):
            c = candles[j]
            hit_stop = c.low <= stop_price
            hit_tp = c.high >= take_profit_price
            if hit_stop:
                exit_price = stop_price  # stop assumed to hit first if both trigger in-bar
            elif hit_tp:
                exit_price = take_profit_price
            if exit_price is not None:
                exit_index = j
                break

        if exit_price is None:
            # Signal never resolved within available data — mark to the last close.
            exit_price = candles[-1].close

        pnl = position_size * (exit_price - entry_price)
        equity += pnl
        equity_curve.append(equity)
        trades.append(Trade(
            entry_index=i,
            exit_index=exit_index,
            entry_timestamp=candles[i].timestamp,
            exit_timestamp=candles[exit_index].timestamp,
            entry_price=entry_price,
            exit_price=exit_price,
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
        }

    wins = [t for t in trades if t.pnl > 0]
    ending_capital = equity_curve[-1]

    peak = equity_curve[0]
    max_drawdown_pct = 0.0
    for e in equity_curve:
        peak = max(peak, e)
        drawdown_pct = (peak - e) / peak * 100 if peak > 0 else 0.0
        max_drawdown_pct = max(max_drawdown_pct, drawdown_pct)

    return {
        "trade_count": len(trades),
        "win_rate_pct": len(wins) / len(trades) * 100,
        "total_return_pct": (ending_capital - starting_capital) / starting_capital * 100,
        "max_drawdown_pct": max_drawdown_pct,
        "avg_r_multiple": sum(t.r_multiple for t in trades) / len(trades),
    }


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--symbols", nargs="+", default=TRADING_PAIRS)
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--capital", type=float, default=DEFAULT_CAPITAL)
    parser.add_argument(
        "--ema-pairs", nargs="+", default=None,
        help="e.g. --ema-pairs 9,21 12,26 (defaults to a small sweep)",
    )
    parser.add_argument(
        "--atr-multipliers", nargs="+", type=float, default=DEFAULT_ATR_MULTIPLIERS,
    )
    args = parser.parse_args()

    if args.ema_pairs:
        args.ema_pairs = [tuple(int(p) for p in pair.split(",")) for pair in args.ema_pairs]
    else:
        args.ema_pairs = DEFAULT_EMA_PAIRS
    return args


def main():
    args = parse_args()
    end = datetime.now(timezone.utc) - timedelta(minutes=20)  # crypto bars need a short settle delay
    start = end - timedelta(days=args.days)

    header = f"{'symbol':<10}{'ema':<10}{'atr_mult':<10}{'trades':<8}{'win%':<8}{'return%':<10}{'maxdd%':<8}{'avg_R':<8}"
    print(header)
    print("-" * len(header))

    for symbol in args.symbols:
        candles = fetch_historical_candles(symbol, start, end)
        if not candles:
            print(f"{symbol}: no candle data returned, skipping")
            continue

        for ema_fast, ema_slow in args.ema_pairs:
            for atr_multiplier in args.atr_multipliers:
                trades, equity_curve = simulate(
                    candles, ema_fast, ema_slow, atr_multiplier, capital=args.capital,
                )
                stats = summarize(trades, equity_curve, args.capital)
                print(
                    f"{symbol:<10}{f'{ema_fast}/{ema_slow}':<10}{atr_multiplier:<10}"
                    f"{stats['trade_count']:<8}{stats['win_rate_pct']:<8.1f}"
                    f"{stats['total_return_pct']:<10.2f}{stats['max_drawdown_pct']:<8.2f}"
                    f"{stats['avg_r_multiple']:<8.2f}"
                )


if __name__ == "__main__":
    main()
