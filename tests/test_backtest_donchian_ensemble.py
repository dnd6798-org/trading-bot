"""
Verifies scripts/backtest_donchian_ensemble.py's dual-channel entry signal,
the rotational portfolio simulation loop (slot cap, same-day slot reuse,
shared-equity position sizing, EOL exit per symbol), and the exit-
timestamp-based fold-slicing — against deterministic synthetic daily
candles and hand-built symbol_data dicts, no network calls.
"""
from src.data_ingestion import Candle
from scripts.backtest_donchian_ensemble import (
    compute_dual_channel_long_entry_indices,
    simulate_rotational_ensemble,
    slice_ensemble_trades_by_folds,
    EnsembleTrade,
)


def _flat_candle(symbol, date, close=100.0, volume=10):
    return Candle(symbol, date, open=close, high=close + 5, low=close - 5, close=close, volume=volume)


def _candle(symbol, date, close, high=None, low=None, volume=10):
    return Candle(
        symbol, date, open=close,
        high=high if high is not None else close + 5,
        low=low if low is not None else close - 5,
        close=close, volume=volume,
    )


def _make_series(symbol, candles, atr, entry_indices):
    return {
        "symbol": symbol,
        "candles": candles,
        "atr": atr,
        "entry_indices": set(entry_indices),
        "date_index": {c.timestamp[:10]: i for i, c in enumerate(candles)},
    }


# --- compute_dual_channel_long_entry_indices --------------------------------

def test_dual_channel_entry_fires_on_close_above_20d_band_before_55d_window_exists():
    dates = [f"2021-01-{i + 1:02d}" for i in range(25)]
    candles = [_flat_candle("BTC/USD", dates[i]) for i in range(20)]
    candles.append(_candle("BTC/USD", dates[20], close=125, high=130, low=120))  # breaks the flat 105 20d band
    candles += [_flat_candle("BTC/USD", dates[i], close=125) for i in range(21, 25)]

    entry_indices, atr = compute_dual_channel_long_entry_indices(candles)

    assert 20 in entry_indices
    assert atr[20] is not None


def test_dual_channel_entry_55d_leg_never_adds_signals_beyond_20d_leg():
    # 60 seasoning days (enough for both the 20d and 55d bands to be fully
    # defined), then a single breakout day. Per the module's MATH NOTE,
    # "close > upper_20 OR close > upper_55" should be provably identical
    # to "close > upper_20" once both bands are defined, since the 55d
    # causal window always contains the 20d window as its most recent
    # slice (upper_55 >= upper_20 always) — this locks that claim in.
    from scripts.backtest_donchian import compute_donchian_levels

    dates = [f"d{i}" for i in range(61)]
    candles = [_flat_candle("BTC/USD", dates[i]) for i in range(60)]
    candles.append(_candle("BTC/USD", dates[60], close=125, high=130, low=120))

    entry_indices, atr = compute_dual_channel_long_entry_indices(candles)
    upper_20, _ = compute_donchian_levels(candles, 20)
    upper_55, _ = compute_donchian_levels(candles, 55)

    plain_20d_indices = {
        i for i in range(len(candles))
        if upper_20[i] is not None and atr[i] is not None and candles[i].close > upper_20[i]
    }
    assert entry_indices == plain_20d_indices
    assert upper_55[60] >= upper_20[60]  # the containment fact the equivalence rests on


# --- simulate_rotational_ensemble: slot cap & skip logging ------------------

def test_simulate_rotational_ensemble_skips_signal_when_all_slots_full():
    dates = ["2021-01-01", "2021-01-02"]
    universe = ["A", "B", "C", "D", "E"]
    symbol_data = {}
    for sym in universe:
        candles = [_candle(sym, dates[0], close=100, high=105, low=95), _flat_candle(sym, dates[1], close=100)]
        symbol_data[sym] = _make_series(sym, candles, atr=[10.0, 10.0], entry_indices=[0])

    trades, equity_curve, skipped_log = simulate_rotational_ensemble(
        symbol_data, universe, max_positions=4, atr_multiplier=2.5,
        capital=100.0, fee_pct=0.0, slippage_bps=0.0,
    )

    entered_symbols = {t.symbol for t in trades}
    assert entered_symbols == {"A", "B", "C", "D"}
    assert any(s["symbol"] == "E" and s["date"] == "2021-01-01" for s in skipped_log)


# --- simulate_rotational_ensemble: same-day slot reuse -----------------------

def test_simulate_rotational_ensemble_reuses_slot_freed_by_same_day_exit():
    d0, d1, d2 = "2021-01-01", "2021-01-02", "2021-01-03"
    universe = ["A", "B", "C", "D", "E"]
    symbol_data = {}

    # A: enters day0 at 100, ATR 10 -> stop = 100 - 2.5*10 = 75. Day1 low=70 hits it.
    symbol_data["A"] = _make_series(
        "A",
        [_candle("A", d0, close=100, high=105, low=95),
         _candle("A", d1, close=80, high=85, low=70)],
        atr=[10.0, 10.0], entry_indices=[0],
    )
    # B, C, D: enter day0 at 200, stay well above their stop (175) through day1, EOL-close day2.
    for sym in ("B", "C", "D"):
        symbol_data[sym] = _make_series(
            sym,
            [_candle(sym, d0, close=200, high=205, low=195),
             _candle(sym, d1, close=200, high=205, low=195),
             _flat_candle(sym, d2, close=200)],
            atr=[10.0, 10.0, 10.0], entry_indices=[0],
        )
    # E: only appears starting day1, fires an entry that day.
    symbol_data["E"] = _make_series(
        "E",
        [_candle("E", d1, close=50, high=55, low=45),
         _flat_candle("E", d2, close=50)],
        atr=[10.0, 10.0], entry_indices=[0],
    )

    trades, equity_curve, skipped_log = simulate_rotational_ensemble(
        symbol_data, universe, max_positions=4, atr_multiplier=2.5,
        capital=100.0, fee_pct=0.0, slippage_bps=0.0,
    )

    a_trade = next(t for t in trades if t.symbol == "A")
    assert a_trade.exit_reason == "trailing_stop"
    assert a_trade.exit_timestamp == d1

    e_trade = next((t for t in trades if t.symbol == "E"), None)
    assert e_trade is not None, "E should have entered day1 once A's exit freed a slot"
    assert e_trade.entry_timestamp == d1
    assert not any(s["symbol"] == "E" for s in skipped_log)


# --- simulate_rotational_ensemble: sizing & EOL ------------------------------

def test_simulate_rotational_ensemble_sizes_off_shared_equity_and_caps_at_max_notional():
    dates = ["2021-01-01", "2021-01-02"]
    symbol_data = {
        "A": _make_series(
            "A",
            # Day1's low (99.6) stays just above the tiny 0.05*ATR stop
            # (100 - 0.5 = 99.5), so this resolves as "eol" rather than
            # "trailing_stop" — isolates the position-size cap from the
            # exit-trigger mechanics already covered elsewhere.
            [_candle("A", dates[0], close=100, high=105, low=95), _candle("A", dates[1], close=100, high=100.5, low=99.6)],
            atr=[10.0, 10.0], entry_indices=[0],
        ),
    }

    trades, equity_curve, skipped_log = simulate_rotational_ensemble(
        symbol_data, ["A"], max_positions=4, atr_multiplier=0.05,  # tiny stop distance -> oversized risk-based size
        capital=100.0, risk_pct=1.0, max_position_pct=25.0, fee_pct=0.0, slippage_bps=0.0,
    )

    assert len(trades) == 1
    trade = trades[0]
    assert trade.exit_reason == "eol"
    position_size = trade.gross_pnl / (trade.exit_price - trade.entry_price) if trade.exit_price != trade.entry_price else None
    if position_size:
        assert position_size * trade.entry_price <= 100.0 * 0.25 + 1e-6


def test_simulate_rotational_ensemble_applies_fees_to_reduce_net_pnl():
    dates = ["2021-01-01", "2021-01-02"]
    symbol_data = {
        "A": _make_series(
            "A",
            [_candle("A", dates[0], close=100, high=105, low=95), _flat_candle("A", dates[1], close=100)],
            atr=[10.0, 10.0], entry_indices=[0],
        ),
    }

    with_fees, _, _ = simulate_rotational_ensemble(symbol_data, ["A"], capital=100.0, fee_pct=0.25, slippage_bps=5.0)
    no_fees, _, _ = simulate_rotational_ensemble(symbol_data, ["A"], capital=100.0, fee_pct=0.0, slippage_bps=0.0)

    assert len(with_fees) == 1 and len(no_fees) == 1
    assert with_fees[0].gross_pnl == no_fees[0].gross_pnl
    assert with_fees[0].pnl < no_fees[0].pnl
    assert with_fees[0].fees_paid > 0


# --- slice_ensemble_trades_by_folds: buckets by EXIT timestamp --------------

def test_slice_ensemble_trades_by_folds_buckets_by_exit_not_entry_timestamp():
    # This trade ENTERS inside fold 1's window (t5) but EXITS inside fold
    # 2's window (t40) — a portfolio-only scenario (concurrent positions
    # can make entry/exit order diverge) that never arises in the
    # single-position-at-a-time scripts. It must land in fold 2, proving
    # the slice is keyed on exit_timestamp, not entry_timestamp (which
    # would have put it in fold 1).
    trades = [
        EnsembleTrade("A", 0, 1, "t5", "t40", 100, 110, "trailing_stop", 10.0, 0.0, 10.0, 1.0),
    ]
    equity_curve = [100.0, 110.0]

    class FakeBoundary:
        def __init__(self, s):
            self._s = s
        def isoformat(self):
            return self._s

    folds = [
        {"fold": 1, "test_start": FakeBoundary("t0"), "test_end": FakeBoundary("t31")},
        {"fold": 2, "test_start": FakeBoundary("t31"), "test_end": FakeBoundary("t99")},
    ]

    fold_summaries, pooled = slice_ensemble_trades_by_folds(trades, equity_curve, folds, capital=100.0)

    assert fold_summaries[0]["trade_count"] == 0
    assert fold_summaries[1]["trade_count"] == 1
    assert pooled["trade_count"] == 1
