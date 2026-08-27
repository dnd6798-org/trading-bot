"""
Position-ownership ledger (spec v55 §10.25, Milestone 2).

Track B and (from Milestone 3) Track C share ONE Alpaca account, and
Alpaca has no per-strategy position concept — it reports a single
combined position per symbol. Track C's risk-off asset is AGG, the same
symbol Track B trades directly, so both tracks can legitimately hold AGG
at the same time with no broker-side way to tell whose shares are whose.

This module tracks each track's own share count per symbol, in a
persisted JSON file (same pattern/location convention as
src/halt_state.py — the simplest thing that's easy to audit by hand).
Structure:

    {"track_b": {"<symbol>": <qty>, ...}, "track_c": {"<symbol>": <qty>, ...}}

WHO UPDATES IT (spec v55 §10.25, decided in the Milestone 2 brief):
  - src/fill_listener.py's handle_trade_update() — the real-time path:
    increments track_b on a confirmed Track B BUY fill (cumulative
    filled_qty), decrements track_b on a SELL fill for a universe symbol.
  - src/execution.py's run_daily_execution_job() — the daily self-heal:
    sets track_b's per-symbol qty to Alpaca's actual combined position
    for every universe symbol each run, correcting any drift from missed
    WebSocket events / listener downtime (the same listener-plus-daily-
    fallback pattern protect_unprotected_fills() already uses for stop
    protection).
  - Track C's own execution code (Milestone 3, NOT built yet) will
    update the "track_c" side after its own fills.

RECONCILIATION: reconcile_symbol() sums track_b + track_c for a symbol
and compares against Alpaca's actual combined position. A mismatch
beyond RECONCILE_EPSILON is a serious integrity failure — it fires an
URGENT Telegram alert (same severity/shape as execution.py's
unprotected-position alert) and halts Track C's autonomous trading via
halt_state.set_track_c_halt() (NOT Track B's halt — the two are
independent by design). This milestone only BUILDS and TESTS
reconcile_symbol(); it is not wired into any live path (Track C has no
rebalance loop yet — that's Milestone 3).

SELL ATTRIBUTION LIMITATION, flagged (not silently assumed away): Track
B's resting stop orders carry no client_order_id, so a SELL fill cannot
be attributed to Track B vs. Track C from the event alone. The listener
decrements "track_b" on any universe-symbol sell, floored at 0. Today
this is correct — only Track B places sells. Once Track C is live
(Milestone 3), a Track C AGG sell would be mis-attributed to track_b
until the next daily self-heal corrects it, and reconcile_symbol() would
catch a genuine drift in the meantime (fail-safe: it halts Track C).
Milestone 3 must give Track C's own sells a track_c-side decrement and
revisit this heuristic.
"""
import json
import os
from dataclasses import dataclass

from . import halt_state
from . import telegram_bot

_STATE_PATH = os.environ.get("TRACK_POSITIONS_STATE_PATH", "track_positions_state.json")

VALID_TRACKS = ("track_b", "track_c")

# Mismatch tolerance for reconcile_symbol() (spec v55 §10.25, confirmed in
# the Milestone 2 brief). Track B position sizing produces fractional
# shares rounded to 4dp (execution.submit_entry_and_stop()), and Alpaca
# reports position qty as a string that gets float()d — an exact ==
# comparison would be fragile. 1e-6 is far below one ten-thousandth of a
# share (the sizing rounding granularity) and well above float noise.
RECONCILE_EPSILON = 1e-6


@dataclass
class ReconcileResult:
    symbol: str
    expected: float          # ledger track_b + track_c for this symbol
    actual: float            # Alpaca's actual combined position qty
    matched: bool            # abs(expected - actual) <= RECONCILE_EPSILON
    halted_track_c: bool     # True iff this call just halted Track C


def _empty_ledger() -> dict:
    return {"track_b": {}, "track_c": {}}


def load_ledger() -> dict:
    """
    Full ledger as a plain dict. A missing file, or a file missing either
    top-level track key, is normalised to the empty shape — never raises
    for a not-yet-created ledger, same as halt_state.load_halt_state().
    """
    if not os.path.exists(_STATE_PATH):
        return _empty_ledger()
    with open(_STATE_PATH) as f:
        raw = json.load(f)
    ledger = _empty_ledger()
    for track in VALID_TRACKS:
        ledger[track] = {k: float(v) for k, v in (raw.get(track) or {}).items()}
    return ledger


def _save_ledger(ledger: dict) -> None:
    with open(_STATE_PATH, "w") as f:
        json.dump(ledger, f, indent=2, sort_keys=True)


def _check_track(track: str) -> None:
    if track not in VALID_TRACKS:
        raise ValueError(f"unknown track {track!r}; expected one of {VALID_TRACKS}")


def get_track_qty(track: str, symbol: str) -> float:
    _check_track(track)
    return load_ledger()[track].get(symbol, 0.0)


def set_track_qty(track: str, symbol: str, qty: float) -> None:
    """
    Absolute set (used by the daily self-heal — 'this is the truth from
    Alpaca'). A qty at/below RECONCILE_EPSILON removes the key entirely,
    keeping the file free of zero/near-zero cruft.
    """
    _check_track(track)
    ledger = load_ledger()
    if qty <= RECONCILE_EPSILON:
        ledger[track].pop(symbol, None)
    else:
        ledger[track][symbol] = float(qty)
    _save_ledger(ledger)


def adjust_track_qty(track: str, symbol: str, delta: float) -> float:
    """
    Relative adjust (used by the listener — +increment on a buy fill,
    -increment on a sell fill). Floors the result at 0 (a sell can never
    drive a track's holding negative); a result at/below RECONCILE_EPSILON
    removes the key. Returns the new qty.
    """
    _check_track(track)
    ledger = load_ledger()
    new_qty = ledger[track].get(symbol, 0.0) + delta
    if new_qty <= RECONCILE_EPSILON:
        ledger[track].pop(symbol, None)
        new_qty = 0.0
    else:
        ledger[track][symbol] = new_qty
    _save_ledger(ledger)
    return new_qty


def _alpaca_position_qty(trading_client, symbol: str) -> float:
    for p in trading_client.get_all_positions():
        if p.symbol == symbol:
            return float(p.qty)
    return 0.0


def reconcile_symbol(trading_client, symbol: str, epsilon: float = RECONCILE_EPSILON) -> ReconcileResult:
    """
    Sums ledger['track_b'][symbol] + ledger['track_c'][symbol] and
    compares against Alpaca's actual current combined position for
    `symbol`. Within `epsilon` -> matched, no side effects. Beyond it ->
    a serious integrity failure:
      - fires an URGENT Telegram alert (same severity/shape as
        execution.py's "URGENT — UNPROTECTED POSITION" alert), and
      - halts Track C's autonomous trading via
        halt_state.set_track_c_halt() (independent of Track B's halt).

    Meant to be called after every Track C rebalance (Milestone 3) — this
    milestone builds and tests it only; nothing invokes it in a live path
    yet.
    """
    ledger = load_ledger()
    expected = ledger["track_b"].get(symbol, 0.0) + ledger["track_c"].get(symbol, 0.0)
    actual = _alpaca_position_qty(trading_client, symbol)
    matched = abs(expected - actual) <= epsilon

    if matched:
        return ReconcileResult(symbol=symbol, expected=expected, actual=actual, matched=True, halted_track_c=False)

    already_halted = halt_state.load_track_c_halt().halted
    telegram_bot.send_message(
        f"URGENT — POSITION LEDGER MISMATCH: {symbol} — ownership ledger (Track B + Track C) shows "
        f"{expected} shares but Alpaca reports {actual}. Track C autonomous trading is halted pending "
        f"manual reconciliation."
    )
    halt_state.set_track_c_halt(
        f"position ledger mismatch for {symbol}: ledger {expected} vs Alpaca {actual}"
    )
    return ReconcileResult(
        symbol=symbol, expected=expected, actual=actual, matched=False,
        halted_track_c=not already_halted,
    )
