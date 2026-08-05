"""
Independent sanity check for backtest.py's daily-candle results — does NOT
import or reuse compute_signal_indices, resample_candles, compute_ema, or
volume_confirms. Everything here is written from scratch specifically so a
bug shared between this script and scripts/backtest.py can't hide the same
way in both places.

Two deliberate differences from backtest.py's --candle-hours 24 resampling,
both chosen to stress-test the thing being checked:
  - Groups hourly candles by their UTC calendar date (the date portion of
    the timestamp), not by "every 24 sequential candles". If the hourly
    data has any gaps, count-based grouping would silently drift out of
    calendar-day alignment over time; date-based grouping wouldn't. Any
    day with != 24 hourly candles is reported so gaps are visible.
  - EMA and the volume-average check are reimplemented plainly here.

Not a locked script — throwaway diagnostic, run directly, not imported.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data_ingestion import fetch_historical_candles

EMA_FAST = 9
EMA_SLOW = 21
VOLUME_LOOKBACK = 20


def group_by_calendar_day(hourly_candles):
    days = {}
    for c in hourly_candles:
        date_key = c.timestamp[:10]  # "YYYY-MM-DD"
        days.setdefault(date_key, []).append(c)
    daily = []
    for date_key in sorted(days):
        group = days[date_key]
        daily.append({
            "date": date_key,
            "close": group[-1].close,
            "volume": sum(g.volume for g in group),
            "hour_count": len(group),
        })
    return daily


def ema(values, period):
    if len(values) < period:
        return [None] * len(values)
    out = [None] * len(values)
    out[period - 1] = sum(values[:period]) / period
    k = 2 / (period + 1)
    for i in range(period, len(values)):
        out[i] = values[i] * k + out[i - 1] * (1 - k)
    return out


def main():
    end = datetime.now(timezone.utc) - timedelta(minutes=20)
    start = datetime(2021, 1, 3, tzinfo=timezone.utc)  # matches this session's max-history runs

    hourly = fetch_historical_candles("BTC/USD", start, end)
    daily = group_by_calendar_day(hourly)

    incomplete_days = [d for d in daily if d["hour_count"] != 24]
    print(f"{len(hourly)} hourly candles -> {len(daily)} calendar days "
          f"({len(incomplete_days)} days with != 24 hourly candles, "
          f"first/last day are expected to be partial)")

    closes = [d["close"] for d in daily]
    volumes = [d["volume"] for d in daily]
    fast = ema(closes, EMA_FAST)
    slow = ema(closes, EMA_SLOW)

    crossover_count = 0
    volume_confirmed_count = 0
    for i in range(1, len(daily)):
        if None in (fast[i], slow[i], fast[i - 1], slow[i - 1]):
            continue
        crossed_up = fast[i - 1] <= slow[i - 1] and fast[i] > slow[i]
        if not crossed_up:
            continue
        crossover_count += 1
        if i < VOLUME_LOOKBACK:
            continue
        avg_volume = sum(volumes[i - VOLUME_LOOKBACK:i]) / VOLUME_LOOKBACK
        if volumes[i] > avg_volume:
            volume_confirmed_count += 1
            print(f"  volume-confirmed signal on {daily[i]['date']}: close={closes[i]:.2f}")

    print(f"\nBullish 9/21 EMA crossovers (no volume filter): {crossover_count}")
    print(f"Bullish crossovers + volume confirmation: {volume_confirmed_count}")


if __name__ == "__main__":
    main()
