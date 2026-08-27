"""
src/capital_ledger.py (spec v53 §10.23, Milestone 1) — the shared
capital-partition arithmetic. Covers the pure allocation math and the
fetch-fresh helper (against a minimal fake client, no network).
"""
from types import SimpleNamespace

import pytest

from src import capital_ledger


class _FakeAccount:
    def __init__(self, equity):
        self.equity = equity


class _FakeTradingClient:
    def __init__(self, equity):
        self._equity = equity
        self.get_account_calls = 0

    def get_account(self):
        self.get_account_calls += 1
        # Return a fresh object each call so a test can prove the helper
        # re-reads rather than caching.
        return _FakeAccount(self._equity)


def test_allocated_capital_is_equity_times_fraction():
    assert capital_ledger.allocated_capital(10_000.0, 0.70) == 7_000.0
    assert capital_ledger.allocated_capital(10_000.0, 0.30) == 3_000.0


def test_allocated_capital_handles_zero_and_full_allocation():
    assert capital_ledger.allocated_capital(12_345.67, 0.0) == 0.0
    assert capital_ledger.allocated_capital(12_345.67, 1.0) == 12_345.67


def test_get_available_capital_fetches_equity_fresh_and_applies_the_fraction():
    client = _FakeTradingClient(equity=20_000.0)
    assert capital_ledger.get_available_capital(client, 0.70) == 14_000.0
    assert client.get_account_calls == 1


def test_get_available_capital_re_reads_on_every_call_never_caches():
    client = _FakeTradingClient(equity=10_000.0)
    capital_ledger.get_available_capital(client, 0.70)
    client._equity = 8_000.0  # account equity moved
    assert capital_ledger.get_available_capital(client, 0.70) == 5_600.0
    assert client.get_account_calls == 2


def test_get_available_capital_coerces_string_equity_like_the_real_account_field():
    # Alpaca's account.equity comes back as a string — the helper must
    # float() it, same as execution.build_account_state() already does.
    client = SimpleNamespace(get_account=lambda: SimpleNamespace(equity="10000"))
    assert capital_ledger.get_available_capital(client, 0.30) == 3_000.0
