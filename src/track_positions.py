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

SELL ATTRIBUTION (spec v57 §10.27, Milestone 3): Track B's resting stop
orders carry no client_order_id, so a SELL fill cannot be attributed from
that. Track C's (future) execution module stamps every order with a "tc-"
client_order_id (TRACK_C_CLIENT_ORDER_ID_PREFIX / is_track_c_client_order_
id()). The listener's SELL branch now routes the decrement to "track_c"
when the sell order's client_order_id matches that prefix, else "track_b"
(the unchanged default — Track B's stops have no client_order_id, so this
is a no-op for the current live system). The BUY branch recognises both
"tb-" (execution.py's decode_client_order_id(), full protection path) and
"tc-" (ledger-only, no stop — Track C is no-stop-by-design).

SELF-HEAL: heal_track_c_ownership_ledger() (below) reconstructs Track C's
holdings from Track C's OWN "tc-" order history alone, never from Alpaca's
combined position total — so execution.heal_track_b_ownership_ledger() can
safely subtract it (max(0, alpaca_total - track_c_known)) for a shared
symbol without circular trust.

RECONCILE / heal_track_c_ownership_ledger() are BUILT AND TESTED ONLY this
milestone; neither is wired into a live path yet (Track C has no rebalance
loop — that's Milestone 4).
"""
import json
import os
from dataclasses import dataclass

from alpaca.trading.enums import OrderSide, QueryOrderStatus
from alpaca.trading.requests import GetOrdersRequest

from . import halt_state
from . import telegram_bot

_STATE_PATH = os.environ.get("TRACK_POSITIONS_STATE_PATH", "track_positions_state.json")

VALID_TRACKS = ("track_b", "track_c")

# Track C's (not-yet-built) execution module will stamp every order it
# submits — entries AND exits alike, since Track C is no-stop-by-design
# and so nothing prevents a client_order_id on any of its orders — with a
# client_order_id starting "tc-", mirroring execution.py's "tb-"
# convention for Track B (spec v57 §10.27). This is the ONLY signal the
# shared fill listener / self-heal has to attribute a fill to Track C vs.
# Track B.
TRACK_C_CLIENT_ORDER_ID_PREFIX = "tc"

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


def is_track_c_client_order_id(client_order_id: str | None) -> bool:
    """True iff client_order_id starts with 'tc-' (Track C's future
    execution module's convention, mirroring execution.py's 'tb-'
    convention for Track B). Never raises on None/empty."""
    return bool(client_order_id) and client_order_id.startswith(f"{TRACK_C_CLIENT_ORDER_ID_PREFIX}-")


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


def heal_track_c_ownership_ledger(trading_client, universe) -> dict:
    """
    Daily/per-run self-heal for the 'track_c' ledger (spec v57 §10.27) —
    INDEPENDENT of Alpaca's combined per-symbol position total (unlike
    Track B's heal in execution.heal_track_b_ownership_ledger(), which
    reads the total directly). Track C's true holding in each universe
    symbol is reconstructed entirely from Track C's OWN order history,
    identified by the 'tc-' client_order_id prefix
    (is_track_c_client_order_id()) — never from the shared position total
    — so there is no circular trust when execution.heal_track_b_ownership_
    ledger() subsequently treats this function's output as its trusted
    subtrahend for a shared symbol (AGG).

    For each symbol in `universe`: queries ALL orders for that symbol
    (QueryOrderStatus.ALL, covering full order history), keeps only those
    whose client_order_id matches is_track_c_client_order_id(), and sums
    filled_qty for BUY sides minus filled_qty for SELL sides. Floors the
    result at 0 (same convention as adjust_track_qty()). Sets (absolute,
    idempotent) the 'track_c' ledger entry via set_track_qty().

    `universe` is a REQUIRED, caller-supplied parameter (no default) —
    Track C's exact universe list is not locked in this milestone; this
    function only builds the mechanism.

    Returns the healed track_c sub-ledger (symbol -> qty, only entries
    above RECONCILE_EPSILON) for the run log, same shape as
    execution.heal_track_b_ownership_ledger()'s return value.

    Not wired into any live/scheduled path yet (Track C has no execution
    module or scheduled job — that's Milestone 4).
    """
    healed = {}
    for symbol in universe:
        orders = trading_client.get_orders(
            GetOrdersRequest(status=QueryOrderStatus.ALL, symbols=[symbol])
        )
        net_qty = 0.0
        for o in orders:
            if not is_track_c_client_order_id(getattr(o, "client_order_id", None)):
                continue
            filled = float(o.filled_qty or 0)
            if filled <= 0:
                continue
            if o.side == OrderSide.BUY:
                net_qty += filled
            elif o.side == OrderSide.SELL:
                net_qty -= filled
        qty = max(net_qty, 0.0)
        set_track_qty("track_c", symbol, qty)
        if qty > RECONCILE_EPSILON:
            healed[symbol] = qty
    return healed
