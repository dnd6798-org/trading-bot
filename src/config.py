"""
Single source of truth for environment/config loading.

Every other module reads settings from here — nothing else should call
os.environ directly or hardcode paper vs. live. This keeps the environment
switch (spec §2, v6 "Environment separation & code promotion pipeline")
a config-only decision, never a code fork.
"""
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


def _get(name: str, required: bool = True, default=None):
    val = os.environ.get(name, default)
    if required and not val:
        raise RuntimeError(f"Missing required env var: {name}")
    return val


@dataclass(frozen=True)
class AlpacaConfig:
    api_key: str
    secret_key: str
    base_url: str
    paper: bool


@dataclass(frozen=True)
class TelegramConfig:
    bot_token: str
    chat_id: str


@dataclass(frozen=True)
class GuardrailConfig:
    max_risk_per_trade_pct: float
    max_position_size_pct: float
    max_daily_loss_pct: float
    max_trades_per_day: int
    max_combined_open_risk_pct: float
    max_drawdown_pct: float


@dataclass(frozen=True)
class StrategyConfig:
    ema_fast_period: int
    ema_slow_period: int
    atr_multiplier: float | None  # None until locked via backtest (playbook v6 §7)


@dataclass(frozen=True)
class HeartbeatConfig:
    daily_job_url: str | None
    listener_url: str | None = None


TRADING_ENV = _get("TRADING_ENV", default="paper")
IS_PAPER = TRADING_ENV.lower() == "paper"

# Track B single-position notional cap (spec v30 §10.2, moved here from
# scripts/backtest_etf_donchian.py in the spec v32 guardrail-rescaling
# milestone's clarification pass — see CLAUDE.md). THE canonical
# definition: both get_track_b_guardrail_config() below (as GuardrailConfig's
# max_position_size_pct — spec §4.1's "max notional position size", the
# same concept, just Track B's own value instead of the legacy crypto/
# global 25%) and backtest_etf_donchian.py (as its notional_sanity_cap_pct
# backtest override) import THIS constant rather than each hardcoding
# their own copy — before this fix they were two independently-set
# numbers (this GuardrailConfig field defaulted to the untouched global
# 25% while the backtest already used 55%) that could silently drift
# apart, not a single source of truth. Grounded in
# scripts/quantify_track_b_notional_concentration.py's real-data result,
# NOT a round number: across all 219 real trades in Track B's original
# backtest, every one of the 7 non-AGG symbols' uncapped, risk-based
# position sizing topped out at 54.6% of equity (global max across 204
# non-AGG entries) — 55% sits one point above that empirical ceiling,
# fully covering AGG's pathological low-ATR/price sizing (which reached
# up to 161.5%) while affecting zero of the other 7 symbols' real trades.
# See CLAUDE.md "Current status" for the full quantification and
# threshold-sweep table.
MAX_SINGLE_POSITION_NOTIONAL_PCT = 55.0

# Capital partition between the concurrently-running strategy tracks
# (spec v53 §10.23, Milestone 1). Alpaca has no sub-account feature for
# individual retail accounts, so the 70/30 Track B / (future) Track C
# split is enforced entirely in application code: each track sizes its
# positions against (its allocation fraction * current total account
# equity), never the full balance — see src/capital_ledger.py. THE
# canonical definition of both numbers: nothing else reads
# TRACK_B_ALLOCATION_PCT / TRACK_C_ALLOCATION_PCT from the environment
# (same single-source-of-truth convention as
# MAX_SINGLE_POSITION_NOTIONAL_PCT above). Stored as fractions in [0, 1]
# (0.70, not 70) — the form capital_ledger.allocated_capital() expects.
# _validate_allocations() is factored out so it can be unit-tested
# directly with arbitrary values; it is also called once here so a bad
# partition fails loudly on import (startup), not at first trade.


def _validate_allocations(track_b_pct: float, track_c_pct: float) -> None:
    """
    Raises RuntimeError (same style as _get's missing-var error) if the
    capital partition is invalid. Never silently clamps or ignores:
      - each allocation must be in [0, 1]
      - the two must sum to no more than 1.0 (small float tolerance)
    """
    for name, pct in (("TRACK_B_ALLOCATION_PCT", track_b_pct), ("TRACK_C_ALLOCATION_PCT", track_c_pct)):
        if not (0.0 <= pct <= 1.0):
            raise RuntimeError(f"{name} must be between 0 and 1 (inclusive); got {pct!r}")
    total = track_b_pct + track_c_pct
    if total > 1.0 + 1e-9:
        raise RuntimeError(
            "TRACK_B_ALLOCATION_PCT + TRACK_C_ALLOCATION_PCT must sum to no more than 1.0; "
            f"got {track_b_pct!r} + {track_c_pct!r} = {total!r}"
        )


TRACK_B_ALLOCATION_PCT = float(_get("TRACK_B_ALLOCATION_PCT", required=False, default="0.70"))
TRACK_C_ALLOCATION_PCT = float(_get("TRACK_C_ALLOCATION_PCT", required=False, default="0.30"))
_validate_allocations(TRACK_B_ALLOCATION_PCT, TRACK_C_ALLOCATION_PCT)


def get_alpaca_config() -> AlpacaConfig:
    prefix = "ALPACA_PAPER" if IS_PAPER else "ALPACA_LIVE"
    return AlpacaConfig(
        api_key=_get(f"{prefix}_API_KEY"),
        secret_key=_get(f"{prefix}_SECRET_KEY"),
        base_url=_get(f"{prefix}_BASE_URL"),
        paper=IS_PAPER,
    )


def get_telegram_config() -> TelegramConfig:
    return TelegramConfig(
        bot_token=_get("TELEGRAM_BOT_TOKEN"),
        chat_id=_get("TELEGRAM_CHAT_ID"),
    )


def get_guardrail_config() -> GuardrailConfig:
    return GuardrailConfig(
        max_risk_per_trade_pct=float(_get("MAX_RISK_PER_TRADE_PCT")),
        max_position_size_pct=float(_get("MAX_POSITION_SIZE_PCT")),
        max_daily_loss_pct=float(_get("MAX_DAILY_LOSS_PCT")),
        max_trades_per_day=int(_get("MAX_TRADES_PER_DAY")),
        max_combined_open_risk_pct=float(_get("MAX_COMBINED_OPEN_RISK_PCT")),
        max_drawdown_pct=float(_get("MAX_DRAWDOWN_PCT")),
    )


def get_track_b_guardrail_config() -> GuardrailConfig:
    """
    Track B (spec v32) guardrail overrides, layered on top of
    get_guardrail_config()'s global .env numbers rather than replacing
    them — crypto/Track A keep reading get_guardrail_config() unchanged.
    Reuses the SAME GuardrailConfig dataclass (not a separate type) so
    risk_filter.py's checks work identically regardless of which config
    is passed in — the same Track-B-only-override/shared-function pattern
    already used for MAX_SINGLE_POSITION_NOTIONAL_PCT (above — this
    function is one of its two consumers) applied to the live guardrail
    config instead of a backtest parameter.

    The legacy spec §4.2 numbers (3% daily loss, 6 trades/day,
    1.5% combined open-risk, 25% max position size) were sized for
    intraday BTC/ETH crypto trading and don't transfer to Track B's
    actual cadence (daily-bar signal evaluation across an 8-symbol
    universe, ~2-3 trades/month pooled — see "Track B findings",
    CLAUDE.md). 4 of 6 fields are rescaled here:
      - max_trades_per_day: 6 -> 8, matching the 8-symbol universe size.
        CLARIFICATION (spec v32 clarification pass): this counts ENTRY
        signals only, one per symbol per day — NOT entries + exits. The
        "can never legitimately bind" property this number is documented
        as having (a defense-in-depth duplicate-order/scheduler-bug
        catcher, a separate code path from MAX_CONCURRENT_POSITIONS) is
        FALSE if exits are also counted: all 8 slots could exit AND all 8
        refill with new entries on the same shock day (16 events),
        exceeding 8 on an entirely ordinary day. Whatever future caller
        computes today's count (execution.py, not built yet) MUST count
        entries only — see risk_filter.check_trade_count_limit()'s
        today_entry_count parameter, named explicitly to make this
        unambiguous rather than leaving it to a generic "trade count".
      - max_daily_loss_pct: 3% -> 4%, rescaled from "3x per-trade risk"
        (the crypto framing) to roughly half the new open-risk budget
        below, sized for several concurrent positions gapping through
        their stops on the same shock day, not sequential intraday losses.
      - max_combined_open_risk_pct: 1.5% -> 8%, deliberately UNDISCOUNTED
        (= MAX_CONCURRENT_POSITIONS(8) x max_risk_per_trade_pct(1%)),
        matching exactly what Track B's original backtest validated (the
        slot cap never bound, no cross-symbol correlation discount was
        applied there — see "Track B findings" and the notional-
        concentration milestone, spec v30 §10.2) rather than introducing
        a new, never-backtested correlation discount at this stage.
      - max_position_size_pct: 25% -> MAX_SINGLE_POSITION_NOTIONAL_PCT
        (55%, above). CLARIFICATION (spec v32 clarification pass): this
        field is the SAME spec §4.1 concept ("max notional position
        size") as MAX_SINGLE_POSITION_NOTIONAL_PCT — missed when this
        function was first written, since that constant predates this
        function and lived only in the backtest script. Now sourced from
        the single constant above rather than left at the stale global
        25%, which would have silently disagreed with the 55% already
        validated for Track B.
    max_risk_per_trade_pct and max_drawdown_pct are passed through
    UNCHANGED from the global config — max_drawdown_pct in particular has
    no Track-B override by explicit instruction (not cadence-dependent,
    stays at the global 10%).
    """
    base = get_guardrail_config()
    return GuardrailConfig(
        max_risk_per_trade_pct=base.max_risk_per_trade_pct,
        max_position_size_pct=MAX_SINGLE_POSITION_NOTIONAL_PCT,
        max_daily_loss_pct=float(_get("MAX_DAILY_LOSS_PCT_TRACK_B", required=False, default="4.0")),
        max_trades_per_day=int(_get("MAX_TRADES_PER_DAY_TRACK_B", required=False, default="8")),
        max_combined_open_risk_pct=float(_get("MAX_TOTAL_OPEN_RISK_PCT_TRACK_B", required=False, default="8.0")),
        max_drawdown_pct=base.max_drawdown_pct,
    )


def get_heartbeat_config() -> HeartbeatConfig:
    """
    Dead-man's-switch heartbeat URL (spec v34 §10.6) — pinged by
    execution.py's __main__ once at the end of every daily job run that
    completes with no per-step errors; Healthchecks.io alerts if a ping
    doesn't arrive within its configured window.

    Read with required=False, even though .env.example documents
    HEALTHCHECKS_DAILY_HEARTBEAT_URL as a value that must actually be
    filled in for the heartbeat to function — a deliberate, flagged
    deviation from treating it as required=True here: coupling a
    monitoring add-on to a hard crash of the entire daily job (which
    still needs to protect/ratchet real open positions regardless of
    whether monitoring is configured) would contradict the fail-toward-
    alert-never-toward-crash convention execution.py already uses
    everywhere else. A missing/blank URL means the ping is silently
    skipped and logged, not a job failure — see execution.py's
    send_daily_heartbeat().

    Provider note (spec v38 §10.8): this env var was renamed from
    UPTIMEROBOT_DAILY_JOB_HEARTBEAT_URL when the heartbeat-monitoring
    provider switched from UptimeRobot to Healthchecks.io — rename only,
    the read pattern (required=False, fail-toward-warning) is unchanged.
    """
    return HeartbeatConfig(
        daily_job_url=_get("HEALTHCHECKS_DAILY_HEARTBEAT_URL", required=False, default=None)
    )


def get_listener_heartbeat_config() -> HeartbeatConfig:
    """
    Fill-listener liveness heartbeat URL (listener-heartbeat design
    session, 2026-08-22 — see CLAUDE.md "Current status") — pinged every
    5 minutes by fill_listener.py's heartbeat_loop() while
    MonitoredTradingStream's own consecutive-failure counter stays below
    its existing 5-failure alert threshold. Healthchecks.io alerts if no
    ping arrives within its configured window (~15 minutes — 3 missed
    pings, narrower than the daily job's ~26h window since this is a
    continuously-running process where a missed heartbeat is meaningful
    within minutes, not a once-daily job). This closes a gap none of the
    existing mechanisms cover: MonitoredTradingStream's own URGENT alert
    only fires from INSIDE a still-running process attempting to
    reconnect — it cannot fire if the process has died outright,
    crash-looped past systemd's StartLimitBurst, or the whole droplet is
    down.

    Same required=False / fail-toward-warning convention as
    get_heartbeat_config(), for the same reason: a missing/blank URL must
    never crash the listener — losing fill protection because monitoring
    wasn't configured would be far worse than losing the monitoring
    signal itself. See fill_listener.py's send_listener_heartbeat().

    Provider note (spec v38 §10.8): this env var was renamed from
    UPTIMEROBOT_LISTENER_HEARTBEAT_URL when the heartbeat-monitoring
    provider switched from UptimeRobot to Healthchecks.io — rename only,
    the read pattern (required=False, fail-toward-warning) is unchanged.
    """
    return HeartbeatConfig(
        daily_job_url=None,
        listener_url=_get("HEALTHCHECKS_LISTENER_HEARTBEAT_URL", required=False, default=None),
    )


def get_track_c_heartbeat_config() -> HeartbeatConfig:
    """
    Track C (DMSR) rebalance-job heartbeat (spec v59 §10.29, Milestone
    4) — a THIRD Healthchecks.io monitor, alongside the daily job's and
    the fill listener's. Pinged once at the end of every
    src/track_c_execution.py run that completes with no per-step errors
    (its main() -> send_track_c_heartbeat()). The trading-bot-track-c
    timer fires every weekday but the job self-gates to a monthly
    rebalance, so a healthy day is usually a no-op — the ping still
    fires (liveness is independent of trading activity), so configure
    this monitor's schedule the same way as the daily job's (weekday
    cron, generous grace), NOT as a once-a-month check.

    Same required=False / fail-toward-warning convention as
    get_heartbeat_config() / get_listener_heartbeat_config(), for the
    same reason: a missing/blank URL must never crash the rebalance job
    (which must still be free to submit/attribute real orders regardless
    of whether monitoring is configured). A missing URL is logged and
    the ping skipped — see track_c_execution.send_track_c_heartbeat().
    """
    return HeartbeatConfig(
        daily_job_url=_get("HEALTHCHECKS_TRACK_C_HEARTBEAT_URL", required=False, default=None)
    )


def get_log_level() -> str:
    """
    Process log level (spec v42 §10.11, daily-job per-symbol DEBUG-logging
    milestone) — read at process startup (execution.py's main()) to set
    the module logger's level. Defaults to "INFO", matching the level
    execution.py's __main__ hardcoded before this milestone, so an
    unset/missing LOG_LEVEL reproduces the exact prior behavior. Not
    validated against Python's logging level names here — an invalid
    value simply fails at the logging.basicConfig()/setLevel() call site,
    the same way any other misconfigured env var in this repo surfaces at
    first use rather than being pre-validated in config.py.
    """
    return _get("LOG_LEVEL", required=False, default="INFO")


def get_strategy_config() -> StrategyConfig:
    atr_raw = _get("ATR_MULTIPLIER", required=False, default="")
    return StrategyConfig(
        ema_fast_period=int(_get("EMA_FAST_PERIOD", default="9")),
        ema_slow_period=int(_get("EMA_SLOW_PERIOD", default="21")),
        atr_multiplier=float(atr_raw) if atr_raw else None,
    )
