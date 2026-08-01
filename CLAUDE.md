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

`src/config.py`, `src/halt_state.py`, `src/signal_generation.py` (EMA/ATR/
volume + long-only crossover detection), `src/data_ingestion.py`'s
historical fetch (`fetch_historical_candles`, via Alpaca crypto market
data), and `scripts/backtest.py` are real and working, with passing tests.
Everything else in `src/` is still a stub with a docstring pointing to the
spec section it implements — `execution.py`, `position_management.py`,
`risk_filter.py`'s real checks, and `data_ingestion.py`'s live fetch are
untouched.

`scripts/backtest.py` now models transaction costs (Alpaca crypto Tier 1
taker fee, 0.25%/leg + an assumed 5bps/leg slippage) and does a proper
calibration (first 270d) / held-out validation (last 90d) split rather
than reporting in-sample-optimized numbers.

**2026-08-01 session finding, important:** over the most recent 1-year
window, no EMA/ATR combo tested is convincingly net-profitable on either
symbol after fees. ETH's best calibration combo (12/26, 2.5x ATR) is
roughly breakeven out-of-sample (+0.06% over 90d); BTC's best combo stays
net-negative in both calibration and validation. Gross-of-fees, ETH's
best combo is clearly positive (+4.47% calibration) while BTC's best
gross combo is still ~flat (-1.71%) — so fees make things worse but
aren't the root cause for BTC specifically. Diagnostics point to a
signal-quality gap rather than a volatility or fee-drag explanation: BTC
and ETH get an identical number of raw crossover signals (56 each) and
BTC's average ATR-as-%-of-price is actually *lower* than ETH's, yet BTC's
stop-hit rate is far higher (58-69% vs 39-52%) — BTC's crossovers just
don't follow through on 1h in this window. Full sweep/validation tables
are in chat history from this session, not yet transcribed into
`session-playbook-v6.md` §7.

EMA/ATR values in `.env` remain unlocked. Given the above, "lock in 9/21"
is not supported by this data — a human decision is needed on how to
proceed (different params, drop BTC from initial live pairs, try a
different timeframe, or conclude the strategy needs rework before going
live at all). Don't treat any single combo as a locked decision.

**Next milestone:** none decided yet — likely either iterating on backtest
calibration (e.g. testing a stop/take-profit asymmetry, since v1 backtest
assumes symmetric 1:1 ATR-based exits) or resolving the crypto
bracket-order design gap so `execution.py` can be built. Confirm with the
user before starting either.

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
