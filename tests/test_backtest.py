"""
Verifies backtest simulation mechanics (entry/exit resolution, position
sizing cap, summary stats) against deterministic synthetic candles — no
network calls. Indicator math itself is covered by test_signal_generation.py;
this covers scripts/backtest.py's simulate()/summarize() logic layered on top.
"""
from src.data_ingestion import Candle
from scripts.backtest import simulate, summarize, Trade


def _crossover_candles():
    """
    Same synthetic series as test_signal_generation's crossover fixture: a
    25-candle decline followed by a 5-candle rise that flips the 9/21 EMA
    crossover (with a volume spike) on the final candle, index 29, entry
    close = 100.0.
    """
    candles = []
    price = 100.0
    for i in range(25):
        price -= 1.0
        candles.append(Candle("BTC/USD", f"t{i}", open=price + 1, high=price + 1.5, low=price - 0.5, close=price, volume=10))
    for i in range(25, 30):
        price += 5.0
        candles.append(Candle("BTC/USD", f"t{i}", open=price - 5, high=price + 0.5, low=price - 5.5, close=price, volume=10 if i < 29 else 100))
    return candles


def test_simulate_exits_at_take_profit_when_high_reaches_it():
    candles = _crossover_candles()
    # ATR(14) at the entry candle (index 29) is ~3.24; atr_multiplier=2 puts
    # take-profit at entry + ~6.48 = ~106.48. This candle's high clears it
    # without its low touching the stop, so the trade should close on a win.
    candles.append(Candle("BTC/USD", "t30", open=101, high=110, low=99, close=105, volume=10))

    trades, equity_curve = simulate(candles, ema_fast_period=9, ema_slow_period=21, atr_multiplier=2.0, capital=100.0)

    assert len(trades) == 1
    trade = trades[0]
    assert trade.entry_index == 29
    assert trade.exit_index == 30
    assert trade.pnl > 0
    assert equity_curve[-1] > 100.0


def test_simulate_exits_at_stop_loss_when_low_reaches_it():
    candles = _crossover_candles()
    # Same setup, but this candle's low blows through the stop (~93.52)
    # instead — the trade should close on a loss.
    candles.append(Candle("BTC/USD", "t30", open=99, high=101, low=90, close=95, volume=10))

    trades, equity_curve = simulate(candles, ema_fast_period=9, ema_slow_period=21, atr_multiplier=2.0, capital=100.0)

    assert len(trades) == 1
    trade = trades[0]
    assert trade.pnl < 0
    assert trade.exit_price < trade.entry_price
    assert equity_curve[-1] < 100.0


def test_simulate_prefers_stop_when_both_hit_in_same_bar():
    candles = _crossover_candles()
    # A wide bar whose low clears the stop AND whose high clears the
    # take-profit — worst-case assumption is the stop hit first.
    candles.append(Candle("BTC/USD", "t30", open=100, high=115, low=85, close=100, volume=10))

    trades, _ = simulate(candles, ema_fast_period=9, ema_slow_period=21, atr_multiplier=2.0, capital=100.0)

    assert len(trades) == 1
    assert trades[0].pnl < 0


def test_simulate_caps_position_size_at_max_notional():
    candles = _crossover_candles()
    # A very tight ATR multiplier makes the risk-sized position far larger
    # than 25% of capital notional-wise, so the max-position cap should bind.
    candles.append(Candle("BTC/USD", "t30", open=101, high=200, low=99, close=150, volume=10))

    trades, _ = simulate(
        candles, ema_fast_period=9, ema_slow_period=21, atr_multiplier=0.1,
        capital=100.0, risk_pct=1.0, max_position_pct=25.0,
    )

    assert len(trades) == 1
    trade = trades[0]
    implied_position_size = trade.pnl / (trade.exit_price - trade.entry_price)
    max_notional = 100.0 * 0.25
    assert implied_position_size * trade.entry_price <= max_notional + 1e-6


def test_simulate_holds_position_open_and_skips_overlapping_signal():
    # Two consecutive signals where the first trade's stop/take-profit
    # hasn't resolved yet by the time the second signal would fire should
    # not open a second, overlapping position.
    candles = _crossover_candles()
    candles.append(Candle("BTC/USD", "t30", open=101, high=101, low=99, close=100, volume=10))  # still open
    candles.append(Candle("BTC/USD", "t31", open=101, high=110, low=99, close=105, volume=10))  # resolves

    trades, _ = simulate(candles, ema_fast_period=9, ema_slow_period=21, atr_multiplier=2.0, capital=100.0)

    assert len(trades) == 1


def test_summarize_computes_win_rate_return_and_drawdown():
    trades = [
        Trade(0, 1, "t0", "t1", entry_price=100, exit_price=110, pnl=10.0, r_multiple=1.0),
        Trade(2, 3, "t2", "t3", entry_price=110, exit_price=100, pnl=-15.0, r_multiple=-1.5),
        Trade(4, 5, "t4", "t5", entry_price=100, exit_price=105, pnl=5.0, r_multiple=0.5),
    ]
    # Equity path: 100 -> 110 (peak) -> 95 (trough) -> 100
    equity_curve = [100.0, 110.0, 95.0, 100.0]

    stats = summarize(trades, equity_curve, starting_capital=100.0)

    assert stats["trade_count"] == 3
    assert round(stats["win_rate_pct"], 2) == round(2 / 3 * 100, 2)
    assert stats["total_return_pct"] == 0.0  # ended flat vs. starting capital
    assert round(stats["max_drawdown_pct"], 4) == round((110 - 95) / 110 * 100, 4)
    assert round(stats["avg_r_multiple"], 4) == round((1.0 - 1.5 + 0.5) / 3, 4)


def test_summarize_handles_no_trades():
    stats = summarize([], [100.0], starting_capital=100.0)
    assert stats["trade_count"] == 0
    assert stats["win_rate_pct"] == 0.0
    assert stats["total_return_pct"] == 0.0
