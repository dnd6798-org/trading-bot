"""
Track B guardrail-implementation milestone (spec v32). Covers exactly the
three risk_filter.py checks implemented this session — check_trade_count_
limit(), check_daily_loss_limit(), check_combined_open_risk_budget() —
against both the global .env config (get_guardrail_config(), unaffected,
still governs crypto/Track A) and the new Track B override config
(get_track_b_guardrail_config(), spec v32). check_drawdown_limit() and
evaluate() are still NotImplementedError, out of scope this session — not
tested here.

check_daily_loss_limit()'s halt path is tested against the REAL
halt_state.py mechanism (not mocked) — redirected to a tmp_path file via
monkeypatch so tests never touch the repo-root halt_state.json — since
"same mechanism as the existing daily-loss circuit breaker" means halt_
state.py's real persisted-halt design, not a substitute.
"""
from types import SimpleNamespace

import pytest

from src import halt_state
from src import telegram_bot
from src.config import (
    GuardrailConfig,
    get_guardrail_config,
    get_track_b_guardrail_config,
    MAX_SINGLE_POSITION_NOTIONAL_PCT,
)
from src.risk_filter import (
    check_trade_count_limit,
    check_daily_loss_limit,
    check_combined_open_risk_budget,
    check_asset_class_concentration,
    TRACK_B_ASSET_CLASS_GROUPS,
    CONCENTRATION_ALERT_THRESHOLD_PCT,
)


@pytest.fixture(autouse=True)
def isolated_halt_state(tmp_path, monkeypatch):
    """Every test in this file gets its own throwaway halt_state.json."""
    monkeypatch.setattr(halt_state, "_STATE_PATH", str(tmp_path / "halt_state.json"))


# --- get_track_b_guardrail_config: layering, not replacement ---------------

def test_track_b_config_overrides_the_four_rescaled_fields():
    global_cfg = get_guardrail_config()
    track_b_cfg = get_track_b_guardrail_config()

    # Rescaled (spec v32, locked values).
    assert track_b_cfg.max_trades_per_day == 8
    assert track_b_cfg.max_daily_loss_pct == 4.0
    assert track_b_cfg.max_combined_open_risk_pct == 8.0
    # Clarification fix (spec v32 clarification pass): max_position_size_pct
    # is the SAME spec §4.1 concept as MAX_SINGLE_POSITION_NOTIONAL_PCT —
    # originally missed, left at the stale global 25% here while the
    # backtest already used 55%. Now overridden too, sourced from the one
    # canonical constant (see the single-source test below).
    assert track_b_cfg.max_position_size_pct == 55.0
    assert track_b_cfg.max_position_size_pct == MAX_SINGLE_POSITION_NOTIONAL_PCT

    # Passed through unchanged from the global config — not hardcoded
    # here, compared directly against get_guardrail_config()'s own
    # values, so a future .env change can't silently desync this test.
    assert track_b_cfg.max_risk_per_trade_pct == global_cfg.max_risk_per_trade_pct
    assert track_b_cfg.max_drawdown_pct == global_cfg.max_drawdown_pct

    # The global config itself is untouched by the Track B override
    # existing — crypto/Track A must see the same numbers as before,
    # INCLUDING max_position_size_pct staying at the legacy 25% globally
    # even though Track B now overrides its own copy to 55%.
    assert global_cfg.max_trades_per_day == 6
    assert global_cfg.max_daily_loss_pct == 3.0
    assert global_cfg.max_combined_open_risk_pct == 1.5
    assert global_cfg.max_position_size_pct == 25.0


def test_max_single_position_notional_pct_is_the_single_source_for_both_consumers():
    # Regression guard for the exact gap the clarification pass fixed:
    # get_track_b_guardrail_config() and scripts/backtest_etf_donchian.py
    # (the backtest's own notional_sanity_cap_pct override) must both
    # read the ONE constant in src/config.py, not two independently-set
    # numbers that happened to agree today but could silently drift
    # apart tomorrow (they briefly did: 25% vs. 55%, before this fix).
    from scripts.backtest_etf_donchian import MAX_SINGLE_POSITION_NOTIONAL_PCT as backtest_constant

    track_b_cfg = get_track_b_guardrail_config()

    assert backtest_constant == MAX_SINGLE_POSITION_NOTIONAL_PCT == 55.0
    assert track_b_cfg.max_position_size_pct == backtest_constant


# --- check_trade_count_limit: gates at 6 (global) vs 8 (Track B) -----------

def test_check_trade_count_limit_gates_at_global_default_of_6():
    cfg = GuardrailConfig(1.0, 25.0, 3.0, max_trades_per_day=6, max_combined_open_risk_pct=1.5, max_drawdown_pct=10.0)
    assert check_trade_count_limit(5, cfg) is True
    assert check_trade_count_limit(6, cfg) is False


def test_check_trade_count_limit_gates_at_track_b_value_of_8_not_global_6():
    cfg = GuardrailConfig(1.0, 25.0, 3.0, max_trades_per_day=8, max_combined_open_risk_pct=8.0, max_drawdown_pct=10.0)
    # A count that would already be blocked under the global cap (6) must
    # still be allowed under Track B's wider cap (8) — proves the two
    # configs genuinely gate independently, not that one silently wins.
    assert check_trade_count_limit(6, cfg) is True
    assert check_trade_count_limit(7, cfg) is True
    assert check_trade_count_limit(8, cfg) is False


def test_check_trade_count_limit_parameter_is_explicitly_named_entry_count_not_trade_count():
    # Regression guard for the clarification fix: the parameter was
    # renamed today_trade_count -> today_entry_count specifically so a
    # future caller can't ambiguously feed it entries+exits (which would
    # falsify the "can never legitimately bind" property documented for
    # Track B's cap of 8 — see check_trade_count_limit()'s own docstring
    # and config.get_track_b_guardrail_config()'s docstring for why).
    import inspect
    params = list(inspect.signature(check_trade_count_limit).parameters)
    assert params[0] == "today_entry_count"


def test_check_trade_count_limit_scenario_illustrating_why_exits_must_not_be_counted():
    # Concrete divergence, not just a documented convention: on an
    # ordinary Track B shock day, exits are processed before entries
    # (simulate_rotational_ensemble()'s convention, backtest_donchian_
    # ensemble.py) — so by the time the 5th entry of the day is being
    # evaluated, all 8 open positions may have ALREADY exited. If a
    # single counter increments on every trade EVENT (8 exits + 4 entries
    # so far = 12), the 5th entry is wrongly blocked even though only 4
    # real entries have happened. Counted correctly (entries only, 4 so
    # far), the 5th entry is correctly still allowed.
    cfg = GuardrailConfig(1.0, 55.0, 4.0, max_trades_per_day=8, max_combined_open_risk_pct=8.0, max_drawdown_pct=10.0)
    entries_so_far_correct = 4               # 4 real entries counted
    entries_so_far_if_exits_also_counted = 8 + 4  # + all 8 exits, wrongly

    assert check_trade_count_limit(entries_so_far_correct, cfg) is True    # 5th entry correctly still allowed
    assert check_trade_count_limit(entries_so_far_if_exits_also_counted, cfg) is False  # wrongly blocked


def test_check_trade_count_limit_using_real_configs_does_not_cross_contaminate():
    global_cfg = get_guardrail_config()
    track_b_cfg = get_track_b_guardrail_config()
    # 7 trades: blocked under the real global config (cap 6), allowed
    # under the real Track B config (cap 8) — the two real, .env-sourced
    # configs must disagree here, or the override isn't actually wired.
    assert check_trade_count_limit(7, global_cfg) is False
    assert check_trade_count_limit(7, track_b_cfg) is True


# --- check_combined_open_risk_budget: gates at 1.5% (global) vs 8% (Track B) -

def test_check_combined_open_risk_budget_gates_at_track_b_8pct_not_global_1_5pct():
    # 2.0% already committed across open positions — over the global 1.5%
    # budget (must return None, fully committed) but well under Track B's
    # 8% budget (must return the real remaining amount, 6.0%).
    open_positions = [SimpleNamespace(risk_pct=1.2), SimpleNamespace(risk_pct=0.8)]
    global_cfg = get_guardrail_config()
    track_b_cfg = get_track_b_guardrail_config()

    assert check_combined_open_risk_budget(open_positions, None, global_cfg) is None
    remaining = check_combined_open_risk_budget(open_positions, None, track_b_cfg)
    assert remaining is not None
    assert abs(remaining - 6.0) < 1e-9


def test_check_combined_open_risk_budget_returns_none_when_track_b_budget_also_exhausted():
    # 8 positions at 1% each = the full Track B 8% budget, nothing left —
    # confirms the budget itself is a real ceiling, not effectively
    # unlimited just because it's larger than the global number.
    open_positions = [SimpleNamespace(risk_pct=1.0) for _ in range(8)]
    track_b_cfg = get_track_b_guardrail_config()

    assert check_combined_open_risk_budget(open_positions, None, track_b_cfg) is None


def test_check_combined_open_risk_budget_with_no_open_positions_returns_full_budget():
    track_b_cfg = get_track_b_guardrail_config()
    remaining = check_combined_open_risk_budget([], None, track_b_cfg)
    assert abs(remaining - 8.0) < 1e-9


# --- check_daily_loss_limit: real halt_state.py mechanism ------------------

def test_check_daily_loss_limit_within_limit_returns_true_and_does_not_halt():
    account_state = SimpleNamespace(day_start_equity=10_000.0, equity=9_800.0)  # -2.0%
    cfg = get_track_b_guardrail_config()  # -4.0% limit

    assert check_daily_loss_limit(account_state, cfg) is True
    assert halt_state.load_halt_state().halted is False


def test_check_daily_loss_limit_breach_halts_via_the_real_halt_state_mechanism():
    account_state = SimpleNamespace(day_start_equity=10_000.0, equity=9_550.0)  # -4.5%, breaches -4.0%
    cfg = get_track_b_guardrail_config()

    result = check_daily_loss_limit(account_state, cfg)

    assert result is False
    state = halt_state.load_halt_state()
    assert state.halted is True
    assert "daily loss" in state.reason.lower()
    assert state.halted_at is not None


def test_check_daily_loss_limit_uses_track_b_threshold_not_global_threshold():
    # -3.5% loss: breaches the GLOBAL 3% limit but is still within Track
    # B's wider 4% limit — the same account_state must produce opposite
    # halt outcomes depending on which config is passed, proving the
    # override actually changes behavior rather than being unused.
    account_state = SimpleNamespace(day_start_equity=10_000.0, equity=9_650.0)  # -3.5%
    global_cfg = get_guardrail_config()
    track_b_cfg = get_track_b_guardrail_config()

    assert check_daily_loss_limit(account_state, global_cfg) is False
    assert halt_state.load_halt_state().halted is True

    halt_state.clear_halt()  # simulate a fresh day / human-cleared halt before the next check

    assert check_daily_loss_limit(account_state, track_b_cfg) is True
    assert halt_state.load_halt_state().halted is False


def test_check_daily_loss_limit_handles_zero_day_start_equity_without_dividing_by_zero():
    account_state = SimpleNamespace(day_start_equity=0.0, equity=0.0)
    cfg = get_track_b_guardrail_config()

    assert check_daily_loss_limit(account_state, cfg) is True
    assert halt_state.load_halt_state().halted is False


# --- check_asset_class_concentration: soft, non-blocking Telegram alert ----

@pytest.fixture(autouse=True)
def captured_telegram_messages(monkeypatch):
    """
    telegram_bot.send_message() is still a NotImplementedError stub (out
    of scope for this milestone) — redirect it to a list capture so these
    tests exercise the real call site in risk_filter.py without needing
    the real Telegram integration built first.
    """
    sent = []
    monkeypatch.setattr(telegram_bot, "send_message", lambda text: sent.append(text))
    return sent


def test_concentration_alert_fires_when_group_exceeds_65pct_threshold(captured_telegram_messages):
    # SPY + QQQ together = 40% notional, both in Domestic Equities —
    # combined 70% > the 65% threshold.
    open_positions = [
        SimpleNamespace(symbol="SPY", notional_pct_of_equity=40.0),
        SimpleNamespace(symbol="QQQ", notional_pct_of_equity=30.0),
    ]

    triggered = check_asset_class_concentration(open_positions)

    assert triggered == ["Domestic Equities"]
    assert len(captured_telegram_messages) == 1
    assert "Domestic Equities" in captured_telegram_messages[0]
    assert "70.0%" in captured_telegram_messages[0]


def test_concentration_alert_does_not_fire_at_or_below_threshold(captured_telegram_messages):
    open_positions = [
        SimpleNamespace(symbol="SPY", notional_pct_of_equity=40.0),
        SimpleNamespace(symbol="QQQ", notional_pct_of_equity=25.0),  # combined exactly 65.0%, not > threshold
    ]

    triggered = check_asset_class_concentration(open_positions)

    assert triggered == []
    assert captured_telegram_messages == []


def test_concentration_alert_never_blocks_or_resizes_the_underlying_trade(captured_telegram_messages):
    # This check's return value must be purely advisory — simulate a
    # caller that ignores it entirely (the only correct usage) and
    # confirm nothing about the position list or a hypothetical trade
    # decision is touched: the function is read-only over open_positions
    # and returns a plain list, nothing that could gate a RiskDecision.
    open_positions = [
        SimpleNamespace(symbol="GLD", notional_pct_of_equity=40.0),
        SimpleNamespace(symbol="DBC", notional_pct_of_equity=30.0),
        SimpleNamespace(symbol="VNQ", notional_pct_of_equity=10.0),
    ]
    original_positions_snapshot = list(open_positions)

    triggered = check_asset_class_concentration(open_positions)

    assert triggered == ["Alternatives"]
    assert open_positions == original_positions_snapshot  # untouched, not resized
    assert isinstance(triggered, list)  # advisory data only, not a RiskDecision


def test_concentration_alert_groups_are_the_confirmed_8_symbol_track_b_universe():
    # Regression guard: the confirmed grouping (user-confirmed before
    # implementation, see CLAUDE.md) covers exactly the 8 real Track B
    # symbols, no more, no fewer, no duplicates or typos.
    all_grouped_symbols = set()
    for symbols in TRACK_B_ASSET_CLASS_GROUPS.values():
        all_grouped_symbols |= symbols
    assert all_grouped_symbols == {"SPY", "QQQ", "IWM", "EFA", "AGG", "GLD", "DBC", "VNQ"}
    assert TRACK_B_ASSET_CLASS_GROUPS["Domestic Equities"] == {"SPY", "QQQ", "IWM"}
    assert TRACK_B_ASSET_CLASS_GROUPS["International Equities"] == {"EFA"}
    assert TRACK_B_ASSET_CLASS_GROUPS["Bonds"] == {"AGG"}
    assert TRACK_B_ASSET_CLASS_GROUPS["Alternatives"] == {"GLD", "DBC", "VNQ"}


def test_concentration_alert_singleton_groups_can_never_trigger_alone():
    # EFA/AGG are singleton groups — a single position is capped at 55%
    # notional (MAX_SINGLE_POSITION_NOTIONAL_PCT), below the 65% alert
    # threshold, so these groups can structurally never fire on their
    # own. Confirmed directly, not just asserted in a comment.
    open_positions = [SimpleNamespace(symbol="EFA", notional_pct_of_equity=55.0)]
    assert check_asset_class_concentration(open_positions) == []

    open_positions = [SimpleNamespace(symbol="AGG", notional_pct_of_equity=55.0)]
    assert check_asset_class_concentration(open_positions) == []


def test_concentration_alert_default_threshold_constant_is_65():
    assert CONCENTRATION_ALERT_THRESHOLD_PCT == 65.0
