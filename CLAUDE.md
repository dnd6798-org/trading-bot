# CLAUDE.md

This file is read fresh at the start of every coding session. It is the
code-phase equivalent of `trading-bot-spec-v6.md` — the source of truth
for how to work in this repo, not what to build (that's the spec).

**If this file and chat history disagree, this file wins.** Update it
whenever a real decision is made during a coding session — don't rely on
conversation history to carry context forward.

---

## What this project is

Automated crypto day-trading bot. BTC/USD + ETH/USD, 9/21 EMA crossover on
1h candles, ATR-based exits, trend-following. Starting on $100 paper-proven
test capital via Alpaca. Full architecture: `trading-bot-spec-v6.md`.
Process/session discipline: `session-playbook-v6.md`. Both live in project
knowledge — read them if this file references something you need more
detail on.

## Current status

**Milestone: backtest / signal-validation (spec §2, playbook v6 §7) —
IN PROGRESS, not complete, no decision locked yet.**

`src/config.py`, `src/halt_state.py`, `src/signal_generation.py` (EMA/ATR/
volume + long-only crossover detection), `src/data_ingestion.py`'s
historical fetch (`fetch_historical_candles`, via Alpaca crypto market
data), `scripts/backtest.py`, and `scripts/backtest_trend_filter.py` are
real and working, with passing tests. Everything else in `src/` is still
a stub with a docstring pointing to the spec section it implements —
`execution.py`, `position_management.py`, `risk_filter.py`'s real checks,
and `data_ingestion.py`'s live fetch are untouched.

### Findings so far (2026-08 session, spans several rounds)

1. Baseline 9/21 EMA crossover + volume confirmation, fee-aware (Alpaca
   0.25%/leg taker + 5bps/leg slippage placeholder), is net-negative on
   both BTC/USD and ETH/USD across every ATR multiplier tested
   (1.5x-3.0x), at every timeframe tested (1h, 4h, daily), over the full
   available history (2021-01-03 → present, ~5.6 years).
2. Ruled out: insufficient data, a bad/unrepresentative time window, and
   a signal-generation bug. An independent, from-scratch daily sanity
   check (`scripts/sanity_check_daily_signal.py`, deliberately not
   reusing any of `backtest.py`'s logic) confirmed the crossover/volume
   logic — 17 vs. 19 signals, with the gap fully explained by
   day-boundary alignment, not a bug.
3. Root cause identified: gross-of-fees returns are roughly flat-to-weak
   *everywhere* (best result found: BTC daily +3.44% gross over 5.5yr) —
   this is a genuine weak/absent edge in the bare crossover, not
   primarily a fee-drag artifact, though fee drag does compound it badly
   at 1h (net -38% to -52% on ~300-380 trades/symbol over the full
   history).
4. Tested a higher-timeframe trend filter (daily 50-SMA and daily 200-SMA)
   on top of the 4h signal (`scripts/backtest_trend_filter.py`): daily-200
   is untestable with the current validation window — price stayed below
   it for the entire 180-day holdout (zero trades, not disproven). Daily-50
   shows partial, thin improvement (BTC calibration losses roughly halved;
   ETH 2 of 4 ATR variants turn slightly net-positive in validation), but
   sample sizes (5-8 validation trades) are too small to call validated.

### Code state

`scripts/backtest.py` (baseline signal + fee model + calibration/
validation split + `--candle-hours` resampling), `scripts/
backtest_trend_filter.py` (SMA filter variant, reuses `backtest.py`'s
trade mechanics unchanged via `simulate()`'s `precomputed_signals`
override), `scripts/sanity_check_daily_signal.py` (independent one-off
check, not meant to be maintained). No `.env` or locked spec parameters
touched. Nothing merged or promoted — still `paper` branch working state.

### Not yet decided (blocks next steps)

Whether to extend the validation window, try an ADX-based filter instead
of/alongside the SMA filter, formally propose the daily-50 filter as a
spec amendment, or reconsider the strategy family entirely if no filter
produces a validated edge. **This decision is being made in a separate
spec/planning chat, not here — check for updated guidance before
starting new backtest work.**

### Pre-coding checklist state

**Not cleared for a new coding milestone.** Per this file's own
convention (a session's "Done" = tests passing + code committed +
spec/playbook updated *on an actual decision*), no decision was locked
this session — so `session-playbook-v6.md`'s pre-coding checklist should
be treated as not satisfied until the open decision above is resolved
elsewhere. Don't start `execution.py` or any other new milestone without
checking for updated guidance first.

### Blocked/pending, unrelated to backtest

`execution.py`'s OCO-fallback design is still waiting on the signal
decision above before it makes sense to start — on top of its own
separate crypto bracket-order design gap (see "Hard rules" below).

**Next milestone:** none decided — do not start without checking the
separate spec/planning chat first.

## Hard rules — never do these

- **Never commit directly to `main`.** All work happens on `paper` or a
  feature branch off it. `main` is only updated through the promotion
  pipeline (spec §3.3): automated tests + soak period + Telegram approval.
- **Never remove or weaken a guardrail check** in `risk_filter.py` without
  an explicit, current instruction to do so in the session. The numbers in
  `.env` (1% risk/trade, 25% max position, 3% daily loss, 6 trades/day cap,
  1.5% combined open-risk, 10% max drawdown) are locked decisions (spec
  §4.1–4.3) — treat them as load-bearing, not tunable defaults.
- **Never let a promotion to `main`/live happen without the Telegram
  approve step.** Even if paper results look great. No auto-merge, no
  timeout-based promotion.
- **Never commit `.env` or any real credential.** `.gitignore` already
  excludes it; `.env.example` is the documented template with blanked
  values. If you ever need to add a new required env var, add it to
  `.env.example` too, in the same commit.
- **Never implement `execution.py`'s order placement** until the crypto
  bracket-order design gap (documented in that file's docstring) is
  resolved and folded into the spec. Alpaca doesn't support bracket/OCO
  orders for crypto — only market/limit/stop_limit. The fallback
  (software-emulated OCO) needs to be locked in before this module is
  built for real, not improvised mid-session.
- **Never auto-resume trading after a crash/restart.** `halt_state.py`
  must be checked on every boot; if halted, stay halted until a human
  clears it via Telegram. This mirrors the "restart ≠ resume" rule that's
  also locked for the DigitalOcean droplet itself (spec §2, §4.5).

## Coding conventions

- One coding session = one milestone, scoped to a single pipeline stage
  (spec §3.1: data ingestion → signal generation → risk filter → execution
  → position management; then §3.2 journaling/governance; then §3.3
  promotion pipeline). Don't sprawl across stages in one session.
- Every module's docstring should reference the spec section it implements
  (see existing stubs for the pattern) — this keeps code and spec
  traceable to each other without needing chat history.
- Commit frequently, in small working units. A session that loses context
  partway through should cost nothing — the next session picks up from
  `CLAUDE.md` + `git log` + current file state.
- "Done" for a session = tests passing + code committed +
  (`trading-bot-spec-v6.md` or `session-playbook-v6.md` updated, if an
  actual decision was made, not just an implementation detail).

## Environment

- `TRADING_ENV` in `.env` controls paper vs. live — one codebase, config
  difference only (spec §2, v6). Never fork logic on this; branch on the
  flag inside `config.py`-derived values if behavior must differ.
- Default assumption for any session unless told otherwise: **you are
  working against paper**, never live, regardless of what's technically
  possible with the credentials present.

## Division of labor (session-playbook-v6.md §8)

Claude Code executes directly in this repo: writes code, runs tests,
handles git add/commit/push, opens PRs from `paper`. The human's role is
approvals only — reviewing/merging PRs into `main`, and Telegram
approve/reject for the promotion pipeline. Propose and execute freely
within the guardrails above; anything that crosses one of the "never do
this" rules requires an explicit, current go-ahead first.
