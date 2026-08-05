"""
EXPERIMENT — higher-timeframe trend filter on top of the locked v1 signal
(9/21 EMA crossover + volume confirmation, spec §2), tested at 4h candles.

This is NOT a parameter search like scripts/backtest.py's sweep — it's a
proposed ADDITION to the signal itself. Flagging explicitly per the
2026-08 session: nothing here is decided or folded into spec §2 until a
human reviews the results and says so. If adopted, it would need a spec
update (a new confirmation filter alongside the existing volume filter).

Rule under test: only take a (bullish) crossover when price is above a
daily N-period SMA — tested for N=50 and N=200 separately. v1 is
long-only (bearish/short signals aren't generated at all — playbook v6
§7, short handling still open), so only the long half of the classic
trend-filter rule ("skip bearish crossovers below the SMA") is testable;
the short half doesn't apply yet.

Reuses scripts/backtest.py's simulate() / run_walk_forward() /
resample_candles() / compute_trend_filtered_signal_indices() so trade
mechanics, the fee model, and calibration/validation methodology are
identical to every other backtest run this session — only signal
selection differs, via simulate()'s precomputed_signals override.

Usage:
    python scripts/backtest_trend_filter.py
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data_ingestion import fetch_historical_candles, TRADING_PAIRS
from scripts.backtest import (
    resample_candles,
    compute_trend_filtered_signal_indices,
    run_walk_forward,
    _print_table,
    DEFAULT_CAPITAL,
    DEFAULT_TAKER_FEE_PCT,
    DEFAULT_SLIPPAGE_BPS,
)

EMA_FAST, EMA_SLOW = 9, 21
ATR_MULTIPLIERS = [1.5, 2.0, 2.5, 3.0]
SMA_PERIODS = [50, 200]
CANDLE_HOURS = 4
BARS_PER_DAY = 24 // CANDLE_HOURS  # 6 four-hour bars per daily bar
CALIBRATION_DAYS = 1860
VALIDATION_DAYS = 180


def main():
    end = datetime.now(timezone.utc) - timedelta(minutes=20)
    start = end - timedelta(days=CALIBRATION_DAYS + VALIDATION_DAYS)
    cutoff_ts = (end - timedelta(days=VALIDATION_DAYS)).isoformat()

    for symbol in TRADING_PAIRS:
        hourly = fetch_historical_candles(symbol, start, end)
        if not hourly:
            print(f"{symbol}: no candle data returned, skipping")
            continue

        candles_4h = resample_candles(hourly, CANDLE_HOURS)
        candles_daily = resample_candles(hourly, 24)

        print(f"\n=== {symbol}: 4h signal, daily-SMA trend filter ===")
        print(f"4h candles: {len(candles_4h)}  |  daily candles: {len(candles_daily)}")

        rows = []
        for sma_period in SMA_PERIODS:
            for atr_multiplier in ATR_MULTIPLIERS:
                filtered_indices, atr = compute_trend_filtered_signal_indices(
                    candles_4h, EMA_FAST, EMA_SLOW,
                    higher_tf_candles=candles_daily, higher_tf_sma_period=sma_period,
                    bars_per_higher_tf_unit=BARS_PER_DAY,
                )
                net_calib, net_valid = run_walk_forward(
                    candles_4h, cutoff_ts, EMA_FAST, EMA_SLOW, atr_multiplier,
                    capital=DEFAULT_CAPITAL, fee_pct=DEFAULT_TAKER_FEE_PCT, slippage_bps=DEFAULT_SLIPPAGE_BPS,
                    precomputed_signals=(filtered_indices, atr),
                )
                gross_calib, gross_valid = run_walk_forward(
                    candles_4h, cutoff_ts, EMA_FAST, EMA_SLOW, atr_multiplier,
                    capital=DEFAULT_CAPITAL, fee_pct=0.0, slippage_bps=0.0,
                    precomputed_signals=(filtered_indices, atr),
                )
                rows.append({
                    "sma": f"daily-{sma_period}", "atr_mult": atr_multiplier,
                    "cal_n": net_calib["trade_count"],
                    "cal_win%": f"{net_calib['win_rate_pct']:.1f}",
                    "cal_net%": f"{net_calib['total_return_pct']:.2f}",
                    "cal_gross%": f"{gross_calib['total_return_pct']:.2f}",
                    "val_n": net_valid["trade_count"],
                    "val_win%": f"{net_valid['win_rate_pct']:.1f}",
                    "val_net%": f"{net_valid['total_return_pct']:.2f}",
                    "val_gross%": f"{gross_valid['total_return_pct']:.2f}",
                })

        print(f"(fee model: {DEFAULT_TAKER_FEE_PCT:.2f}% taker + {DEFAULT_SLIPPAGE_BPS:.0f}bps slippage per leg)")
        print(f"(calibration = first {CALIBRATION_DAYS}d, validation = held-out last {VALIDATION_DAYS}d)")
        _print_table(rows, [
            ("sma", "sma"), ("atr_mult", "atr_mult"),
            ("cal_n", "cal_n"), ("cal_win%", "cal_win%"), ("cal_net%", "cal_net%"), ("cal_gross%", "cal_gross%"),
            ("val_n", "val_n"), ("val_win%", "val_win%"), ("val_net%", "val_net%"), ("val_gross%", "val_gross%"),
        ])


if __name__ == "__main__":
    main()
