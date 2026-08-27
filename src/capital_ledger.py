"""
Shared capital ledger (spec v53 §10.23, Milestone 1).

Alpaca has no sub-account feature for individual retail accounts, so the
70/30 capital partition between Track B and the future Track C is
enforced entirely in application code. Each track must size its
positions against (its allocation fraction * current total account
equity) — never the full account balance — so that once Track C's own
execution code is built (a separate, future milestone), the two
strategies cannot silently double-count the same capital.

Deliberately tiny: this module owns only the allocation arithmetic and
one fetch-fresh helper. The allocation fractions themselves are the
single source of truth in src/config.py
(TRACK_B_ALLOCATION_PCT / TRACK_C_ALLOCATION_PCT, plus
config._validate_allocations()) — this module never re-reads them from
the environment.

Track C has NO execution code yet — this module exists so Track B is
ready for it, per the Milestone 1 brief. Nothing here is Track-C-
specific: get_available_capital() / allocated_capital() take whichever
allocation fraction they are handed.
"""
from alpaca.trading.client import TradingClient


def allocated_capital(account_equity: float, allocation_pct: float) -> float:
    """
    A track's currently-available capital: account_equity * allocation_pct.

    Pure arithmetic, no I/O — the caller supplies a freshly-fetched
    equity value. `allocation_pct` is a fraction in [0, 1] (e.g. 0.70),
    NOT a percentage out of 100 — matching how config.TRACK_B_ALLOCATION_
    PCT is stored.
    """
    return account_equity * allocation_pct


def get_available_capital(trading_client: TradingClient, allocation_pct: float) -> float:
    """
    A track's currently-available capital, pulling total account equity
    FRESH from Alpaca on every call — never a cached or stale value.

    Reads the same `GET /v2/account` `.equity` field that
    execution.py's build_account_state() already uses, so a track's
    sizing base always reflects the account's real current equity at the
    moment of sizing. Delegates the arithmetic to allocated_capital().
    """
    account = trading_client.get_account()
    return allocated_capital(float(account.equity), allocation_pct)
